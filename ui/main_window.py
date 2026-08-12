"""
主窗口

优化后的主窗口布局 - Simulation View 占据最大区域
集成质心参考系和过渡动画
"""

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar, QLabel,
    QMessageBox, QToolBar, QPushButton, QFrame,
    QFileDialog, QInputDialog, QSlider, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction

from physics import (
    PhysicsEngine, Camera, Mode, UnitSystem, UnitConverter,
    SimulationFormatter, ScientificFormatter,
    ReferenceFrame, TransitionManager
)
from .simulation_widget import SimulationWidget
from .body_list_widget import BodyListWidget
from .inspector_widget import InspectorWidget
from .control_panel import ControlPanel
from .add_body_dialog import AddBodyDialog
from .styles import apply_global_style, apply_button_style, PANEL_STYLE
from physics.scene_manager import SceneManager
from .toast import Toast
from .profiler import FrameProfiler, ProfilingApplication, PerformanceLogger


# 速度滑杆范围（对数刻度）
SPEED_MIN = 0.1
SPEED_MAX = 20.0

# 整数倍速预设档位
SPEED_PRESETS = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]

# 倍率切换后的稳定等待时间，之后才执行一次“倍率已达上限”检测
RATE_CHECK_DELAY_MS = 600


class MainWindow(QMainWindow):
    """
    主窗口
    
    优化布局：
    - Simulation View 占据中央最大区域（>=75%）
    - 左侧：可折叠天体列表（紧凑）
    - 右侧：可折叠检查器（紧凑）
    - 顶部：紧凑工具栏
    - 底部：状态栏
    """
    
    def __init__(self):
        super().__init__()
        
        # 核心组件
        self.engine = PhysicsEngine(integrator_type='rk4', dt=0.001, time_scale=1.0)
        self.camera = Camera(viewport_width=800, viewport_height=600, zoom=10.0)
        
        # 参考系和过渡管理
        self.reference_frame = ReferenceFrame()
        self.transition_manager = TransitionManager()
        
        # 模式和单位
        self.mode = Mode.SIMULATION
        self.unit_system = UnitSystem()
        self.converter = None

        # 场景管理器（JSON 读写，不参与物理计算）
        self.scene_manager = SceneManager()

        # 倍率切换后的上限检测定时器（仅在切换后做一次性检测）
        self._rate_check_timer = QTimer(self)
        self._rate_check_timer.setSingleShot(True)
        self._rate_check_timer.timeout.connect(self._on_rate_check_timeout)
        
        # 跟随质心标志（默认关闭）
        self.follow_com = False
        
        # 添加示例天体
        self._add_demo_bodies()
        
        # 设置 UI
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()

        # 帧率落后提示气泡（仅提示，不修改任何设置）
        self.toast = Toast(self.centralWidget())

        self._connect_signals()
        
        # 启动动画
        self.sim_widget.start_animation()
        
        # 状态更新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(100)

        # 检查器 10 Hz 刷新（未选中时为空操作），避免高频重建
        self._inspector_timer = QTimer(self)
        self._inspector_timer.timeout.connect(self._refresh_inspector)
        self._inspector_timer.start(100)
        
        # 参考系更新定时器
        self._ref_frame_timer = QTimer(self)
        self._ref_frame_timer.timeout.connect(self._update_reference_frame)
        self._ref_frame_timer.start(50)  # 20 Hz

        # 性能分析器（运行时包装计时，不修改任何物理算法）
        self.profiler = FrameProfiler(self.engine, self.reference_frame)
        self.profiler.attach()
        self.sim_widget.set_profiler(self.profiler)
        self.profiler.attach_ui(self)

        # 逐帧性能日志（每帧输出，每秒统计均值/峰值/1s 窗口均值）
        log_path = Path(
            os.environ.get(
                'PERF_LOG_PATH',
                str(Path(__file__).resolve().parent.parent / 'logs' / 'performance.log'),
            )
        )
        self.performance_logger = PerformanceLogger(
            self.profiler,
            path=log_path,
            enabled=os.environ.get('PERF_LOG', '1') == '1',
        )
        self.profiler.set_frame_listener(self.performance_logger.record)
        
        # 应用样式
        self.setStyleSheet(PANEL_STYLE)
    
    def _add_demo_bodies(self):
        """添加示例天体"""
        from physics import Body
        
        # 中心恒星
        star = Body(
            name="Star",
            mass=1000.0,
            physical_radius=5.0,
            render_radius=5.0,
            position=(0.0, 0.0),
            velocity=(0.0, 0.0),
            color=(1.0, 0.8, 0.0)
        )
        self.engine.add_body(star)
        
        # 行星
        planet = Body(
            name="Planet",
            mass=1.0,
            physical_radius=1.0,
            render_radius=1.0,
            position=(10.0, 0.0),
            velocity=(0.0, 10.0),
            color=(0.3, 0.5, 1.0)
        )
        self.engine.add_body(planet)
    
    def _setup_ui(self):
        """设置 UI - 优化布局"""
        self.setWindowTitle("天体引力模拟器")
        self.setMinimumSize(1200, 800)
        
        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 主分割器 - 水平布局
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧面板（天体列表）- 紧凑
        self.left_panel = QWidget()
        self.left_panel.setMinimumWidth(100)
        self.left_panel.setMaximumWidth(300)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        
        self.body_list = BodyListWidget(
            self.engine, self.mode, self.unit_system, self.converter
        )
        left_layout.addWidget(self.body_list)
        
        self.main_splitter.addWidget(self.left_panel)
        
        # 中间：模拟视图 - 占据最大区域
        self.sim_widget = SimulationWidget(
            self.engine, self.camera,
            reference_frame=self.reference_frame
        )
        self.main_splitter.addWidget(self.sim_widget)
        
        # 右侧面板（检查器）- 紧凑
        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(100)
        self.right_panel.setMaximumWidth(350)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)
        
        self.inspector = InspectorWidget(
            self.engine, self.mode, self.unit_system, self.converter
        )
        right_layout.addWidget(self.inspector)
        
        self.main_splitter.addWidget(self.right_panel)
        
        # 设置分割比例 - Simulation View 占据 >=75%
        # 左侧 120px，中间最大化，右侧 180px
        self.main_splitter.setSizes([120, 960, 180])
        self.main_splitter.setStretchFactor(0, 0)  # 左侧固定
        self.main_splitter.setStretchFactor(1, 1)  # 中间可拉伸（模拟区域）
        self.main_splitter.setStretchFactor(2, 0)  # 右侧固定
        
        main_layout.addWidget(self.main_splitter)
        
        # 初始刷新
        self.body_list.refresh()
    
    def _setup_menu(self):
        """设置菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        add_action = QAction("添加天体(&A)", self)
        add_action.setShortcut("Ctrl+A")
        add_action.triggered.connect(self._on_add_body)
        file_menu.addAction(add_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&Q)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")
        
        reset_camera_action = QAction("重置摄像机(&R)", self)
        reset_camera_action.triggered.connect(self._on_reset_camera)
        view_menu.addAction(reset_camera_action)
        
        fit_action = QAction("适应所有天体(&F)", self)
        fit_action.triggered.connect(self._on_fit_all_bodies)
        view_menu.addAction(fit_action)
        
        view_menu.addSeparator()
        
        toggle_left_action = QAction("显示/隐藏天体列表", self)
        toggle_left_action.triggered.connect(self._toggle_left_panel)
        view_menu.addAction(toggle_left_action)
        
        toggle_right_action = QAction("显示/隐藏检查器", self)
        toggle_right_action.triggered.connect(self._toggle_right_panel)
        view_menu.addAction(toggle_right_action)

        view_menu.addSeparator()

        # 性能分析覆盖层开关（仅控制模拟视图左上角的显示）
        self.profiler_overlay_action = QAction("显示性能分析(&P)", self)
        self.profiler_overlay_action.setCheckable(True)
        self.profiler_overlay_action.setChecked(True)
        self.profiler_overlay_action.triggered.connect(
            self.sim_widget.set_profiler_overlay_visible
        )
        view_menu.addAction(self.profiler_overlay_action)
        
        # 参考系菜单
        ref_menu = menubar.addMenu("参考系(&R)")
        
        self.follow_com_action = QAction("跟随质心", self)
        self.follow_com_action.setCheckable(True)
        self.follow_com_action.setChecked(self.follow_com)
        self.follow_com_action.triggered.connect(self._toggle_follow_com)
        ref_menu.addAction(self.follow_com_action)
        
        reset_ref_action = QAction("重置参考系", self)
        reset_ref_action.triggered.connect(self._on_reset_reference_frame)
        ref_menu.addAction(reset_ref_action)
        
        # 模式菜单
        mode_menu = menubar.addMenu("模式(&M)")
        
        self.sim_mode_action = QAction("模拟模式", self)
        self.sim_mode_action.setCheckable(True)
        self.sim_mode_action.setChecked(True)
        self.sim_mode_action.triggered.connect(lambda: self._set_mode(Mode.SIMULATION))
        mode_menu.addAction(self.sim_mode_action)
        
        self.sci_mode_action = QAction("科学模式", self)
        self.sci_mode_action.setCheckable(True)
        self.sci_mode_action.setChecked(False)
        self.sci_mode_action.triggered.connect(lambda: self._set_mode(Mode.SCIENTIFIC))
        mode_menu.addAction(self.sci_mode_action)

        # 场景菜单
        self.scene_menu = menubar.addMenu("场景(&C)")

        load_action = QAction("加载场景(&L)", self)
        load_action.triggered.connect(self._on_load_scene)
        self.scene_menu.addAction(load_action)

        save_action = QAction("保存场景(&S)", self)
        save_action.triggered.connect(self._on_save_scene)
        self.scene_menu.addAction(save_action)

        self.scene_menu.addSeparator()

        import_action = QAction("导入场景(&I)", self)
        import_action.triggered.connect(self._on_import_scene)
        self.scene_menu.addAction(import_action)

        export_action = QAction("导出场景(&E)", self)
        export_action.triggered.connect(self._on_export_scene)
        self.scene_menu.addAction(export_action)

        # 动态场景列表（启动时自动扫描 scenes/ 目录）
        self._scene_scan_actions = []
        self._scene_separator = None
        self._refresh_scene_menu()
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_toolbar(self):
        """设置工具栏 - 紧凑设计"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        self.addToolBar(toolbar)
        
        # 播放控制
        self.play_btn = QPushButton("▶")
        apply_button_style(self.play_btn, 'primary')
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setToolTip("播放/暂停")
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self._on_play_pause)
        toolbar.addWidget(self.play_btn)
        
        self.step_btn = QPushButton("⏭")
        apply_button_style(self.step_btn, 'toolbar')
        self.step_btn.setFixedSize(36, 36)
        self.step_btn.setToolTip("单步执行")
        self.step_btn.clicked.connect(self._on_step)
        toolbar.addWidget(self.step_btn)
        
        toolbar.addSeparator()
        
        # 添加天体
        self.add_btn = QPushButton("➕ 添加")
        apply_button_style(self.add_btn, 'primary')
        self.add_btn.clicked.connect(self._on_add_body)
        toolbar.addWidget(self.add_btn)
        
        toolbar.addSeparator()
        
        # 摄像机控制
        self.reset_camera_btn = QPushButton("🎯")
        apply_button_style(self.reset_camera_btn, 'toolbar')
        self.reset_camera_btn.setFixedSize(36, 36)
        self.reset_camera_btn.setToolTip("重置摄像机")
        self.reset_camera_btn.clicked.connect(self._on_reset_camera)
        toolbar.addWidget(self.reset_camera_btn)
        
        self.fit_btn = QPushButton("🔍")
        apply_button_style(self.fit_btn, 'toolbar')
        self.fit_btn.setFixedSize(36, 36)
        self.fit_btn.setToolTip("适应全部")
        self.fit_btn.clicked.connect(self._on_fit_all_bodies)
        toolbar.addWidget(self.fit_btn)
        
        toolbar.addSeparator()
        
        # 参考系控制
        self.reset_ref_btn = QPushButton("⚖️")
        apply_button_style(self.reset_ref_btn, 'toolbar')
        self.reset_ref_btn.setFixedSize(36, 36)
        self.reset_ref_btn.setToolTip("重置参考系")
        self.reset_ref_btn.clicked.connect(self._on_reset_reference_frame)
        toolbar.addWidget(self.reset_ref_btn)
        
        self.follow_com_btn = QPushButton("📍")
        apply_button_style(self.follow_com_btn, 'toolbar')
        self.follow_com_btn.setFixedSize(36, 36)
        self.follow_com_btn.setToolTip("跟随质心")
        self.follow_com_btn.setCheckable(True)
        self.follow_com_btn.setChecked(self.follow_com)
        self.follow_com_btn.clicked.connect(self._toggle_follow_com)
        toolbar.addWidget(self.follow_com_btn)
        
        toolbar.addSeparator()
        
        # 演进速度滑杆（对数刻度）
        self.speed_control = self._create_speed_slider()
        toolbar.addWidget(self.speed_control)
        
        toolbar.addSeparator()
        
        # 模式切换
        self.mode_btn = QPushButton("🔬")
        apply_button_style(self.mode_btn, 'toolbar')
        self.mode_btn.setFixedSize(36, 36)
        self.mode_btn.setToolTip("切换科学模式")
        self.mode_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self.mode_btn)
    
    def _create_speed_slider(self):
        """创建对数刻度的速度滑杆（0.1× - 100×）"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("速度:"))

        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        # 对数刻度：0 位置 = 0.1×，100 位置 = 1×，230 位置 = 20×（SPEED_MAX）
        self.speed_slider.setRange(0, self._multiplier_to_slider(SPEED_MAX))
        # 轨道点击/方向键按 1 位置微调，保证任意方向都能平滑调节
        self.speed_slider.setSingleStep(1)
        self.speed_slider.setPageStep(1)
        self.speed_slider.setFixedWidth(150)
        self.speed_slider.setToolTip("演进速度（对数刻度，1× = 旧版 5×）")
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        layout.addWidget(self.speed_slider)

        self.speed_label = QLabel("1×")
        self.speed_label.setFixedWidth(48)
        layout.addWidget(self.speed_label)

        # 整数倍速预设下拉框（选中后滑杆同步移动到对应位置）
        self.speed_preset_combo = QComboBox()
        for m in SPEED_PRESETS:
            self.speed_preset_combo.addItem(f"{m:g}×", m)
        self.speed_preset_combo.setFixedWidth(64)
        self.speed_preset_combo.currentIndexChanged.connect(
            self._on_speed_preset_changed
        )
        layout.addWidget(self.speed_preset_combo)

        # 统一入口：引擎 + 滑杆 + 标签 + 预设同步到 1×
        self._set_speed_control(1.0)
        return widget

    def _slider_to_multiplier(self, pos: int) -> float:
        """滑杆位置 -> 倍率（对数刻度）"""
        if pos >= self._multiplier_to_slider(SPEED_MAX):
            # 顶格位置精确归一到 SPEED_MAX（20×），避免对数刻度舍入出 19.95×
            return SPEED_MAX
        return SPEED_MIN * (10.0 ** (pos / 100.0))

    def _multiplier_to_slider(self, multiplier: float) -> int:
        """倍率 -> 滑杆位置"""
        return int(round(100.0 * math.log10(multiplier / SPEED_MIN)))

    def _nearest_preset_index(self, multiplier: float) -> int:
        """距离当前倍率最近的预设档位下标（对数距离）"""
        return min(
            range(len(SPEED_PRESETS)),
            key=lambda i: abs(math.log10(SPEED_PRESETS[i] / multiplier)),
        )

    def _set_speed_control(self, multiplier: float):
        """
        统一设置演进速度：引擎 + 滑杆位置 + 标签 + 预设档位。

        滑块回写时 blockSignals，防止 setValue 触发 valueChanged 造成重入，
        保证预设档位使用精确倍率而非滑杆取整值。
        """
        multiplier = float(multiplier)
        self.engine.time_scale = multiplier
        self.speed_label.setText(f"{multiplier:.3g}×")

        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(self._multiplier_to_slider(multiplier))
        self.speed_slider.blockSignals(False)

        self.speed_preset_combo.blockSignals(True)
        self.speed_preset_combo.setCurrentIndex(self._nearest_preset_index(multiplier))
        self.speed_preset_combo.blockSignals(False)

        # 倍率切换后等待一段稳定期，再做一次上限检测（拖动过程中持续重启，松手后才检测）
        self._rate_check_timer.start(RATE_CHECK_DELAY_MS)
    
    def _setup_statusbar(self):
        """设置状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        self.fps_label = QLabel("FPS: 0")
        self.body_count_label = QLabel("天体: 0")
        self.time_label = QLabel("时间: 0.00 TU")
        self.com_label = QLabel("质心: (0.00, 0.00)")
        
        self.statusbar.addPermanentWidget(self.fps_label)
        self.statusbar.addPermanentWidget(self.body_count_label)
        self.statusbar.addPermanentWidget(self.time_label)
        self.statusbar.addPermanentWidget(self.com_label)
    
    def _connect_signals(self):
        """连接信号"""
        # 天体列表
        self.body_list.body_selected.connect(self._on_body_selected)
        self.body_list.body_delete_requested.connect(self._on_delete_body)
        
        # 模拟视图
        self.sim_widget.body_clicked.connect(self._on_body_clicked)

        # 倍率切换后检测到“已达上限” -> 仅提示，不修改任何设置
        self.sim_widget.rate_limit_detected.connect(self._on_rate_limit)
    
    def _on_play_pause(self):
        """播放/暂停"""
        if self.play_btn.isChecked():
            self.play_btn.setText("⏸")
            self.sim_widget.resume()
        else:
            self.play_btn.setText("▶")
            self.sim_widget.pause()
    
    def _on_step(self):
        """单步执行"""
        self.sim_widget.step()
    
    def _on_speed_slider_changed(self, pos: int):
        """速度滑杆变化"""
        self._set_speed_control(self._slider_to_multiplier(pos))

    def _on_speed_preset_changed(self, index: int):
        """预设倍速选择：滑块移动到对应位置，引擎使用精确倍率"""
        if index < 0:
            return
        self._set_speed_control(self.speed_preset_combo.itemData(index))
    
    def _on_add_body(self):
        """添加天体"""
        dialog = AddBodyDialog(self.mode, self.unit_system, self.converter, self)
        if dialog.exec():
            body = dialog.get_body()
            self.engine.add_body(body)
            self.body_list.refresh()

    def _on_load_scene(self):
        """加载场景：读取 JSON 并恢复到引擎/相机"""
        default_dir = str(self.scene_manager.scenes_directory)
        path, _ = QFileDialog.getOpenFileName(
            self, "加载场景", default_dir, "Scene JSON (*.json)"
        )
        if path:
            self._load_scene_from_path(path)

    def _on_import_scene(self):
        """导入场景：从任意路径读取 JSON 并应用到当前模拟"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入场景", "", "Scene JSON (*.json)"
        )
        if path:
            self._load_scene_from_path(path)

    def _on_save_scene(self):
        """保存场景：当前状态写入 scenes/<名称>.json"""
        name, ok = QInputDialog.getText(self, "保存场景", "场景名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        path = self.scene_manager.scenes_directory / f"{name}.json"
        self.scene_manager.export_scene(
            self.engine, self.camera, path, name=name
        )
        self._refresh_scene_menu()
        self.statusBar().showMessage(f"场景已保存: {path}")

    def _on_export_scene(self):
        """导出场景：当前状态写入指定 JSON 文件"""
        default_file = str(self.scene_manager.scenes_directory / "scene.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出场景", default_file, "Scene JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        name = Path(path).stem
        self.scene_manager.export_scene(
            self.engine, self.camera, path, name=name
        )
        self._refresh_scene_menu()
        self.statusBar().showMessage(f"场景已导出: {path}")

    def _load_scene_from_path(self, path):
        """应用场景文件到引擎/相机"""
        try:
            scene = self.scene_manager.import_scene(
                path, self.engine, self.camera
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "加载场景失败", str(exc))
            return
        # 场景导入可能重建积分器，让性能分析器重新挂接计时
        self.profiler.refresh()
        # 场景中的 time_scale 同步到滑杆/标签/预设档位
        self._set_speed_control(self.engine.time_scale)
        self.body_list.refresh()
        self.inspector.select_body(-1)
        self.inspector.refresh()
        self.sim_widget.update()
        self.statusBar().showMessage(f"已加载场景: {scene.get('name', path)}")

    def _refresh_scene_menu(self):
        """扫描 scenes/ 目录并刷新动态场景列表"""
        if self._scene_separator is not None:
            self.scene_menu.removeAction(self._scene_separator)
            self._scene_separator = None
        for action in self._scene_scan_actions:
            self.scene_menu.removeAction(action)
        self._scene_scan_actions.clear()

        scenes = self.scene_manager.scan_scenes()
        if not scenes:
            return

        self._scene_separator = self.scene_menu.addSeparator()
        for info in scenes:
            action = QAction(info['name'], self)
            if info.get('description'):
                action.setToolTip(info['description'])
            action.triggered.connect(
                lambda checked, p=info['path']: self._load_scene_from_path(p)
            )
            self.scene_menu.addAction(action)
            self._scene_scan_actions.append(action)
    
    def _on_body_selected(self, index: int):
        """天体被选中"""
        self.inspector.select_body(index)
        self.inspector.refresh()
    
    def _on_body_clicked(self, index: int):
        """天体被点击"""
        self.body_list.list_widget.setCurrentRow(index)
        self.inspector.select_body(index)
        self.inspector.refresh()

    def _on_rate_check_timeout(self):
        """倍率稳定后执行一次上限检测（仅提示，不修改任何设置）"""
        self.sim_widget.start_rate_check()

    def _on_rate_limit(self):
        """当前倍率下引擎已撞单帧子步上限：提高倍率不再加速，仅弹窗告知"""
        if self.toast.is_showing:
            return
        self.toast.show_message("倍率已达上限", 5000)
    
    def _on_delete_body(self, index: int):
        """删除天体"""
        if 0 <= index < len(self.engine.bodies):
            body = self.engine.bodies[index]
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要删除天体 '{body.name}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.engine.remove_body(index)
                self.body_list.refresh()
                self.inspector.select_body(-1)
                self.inspector.refresh()
    
    def _on_reset_camera(self):
        """重置摄像机"""
        self.camera.reset()
        self.sim_widget.update()
    
    def _on_fit_all_bodies(self):
        """适应所有天体"""
        if len(self.engine.bodies) > 0:
            positions = np.array([b.position for b in self.engine.bodies])
            self.camera.fit_all_bodies(positions)
            self.sim_widget.update()
    
    def _on_reset_reference_frame(self):
        """重置参考系"""
        # 计算当前质心
        com_pos = self.reference_frame.compute_center_of_mass(self.engine.bodies)
        com_vel = self.reference_frame.compute_center_of_mass_velocity(self.engine.bodies)
        
        # 启动摄像机过渡到质心
        self.transition_manager.start_camera_transition(
            self.camera, com_pos, duration=0.8
        )
        
        # 启动动量修正过渡
        self.transition_manager.start_momentum_correction(
            self.engine.bodies, com_vel, duration=1.0
        )
    
    def _toggle_follow_com(self):
        """切换跟随质心"""
        self.follow_com = not self.follow_com
        self.follow_com_action.setChecked(self.follow_com)
        self.follow_com_btn.setChecked(self.follow_com)
    
    def _toggle_mode(self):
        """切换模式"""
        if self.mode == Mode.SIMULATION:
            self._set_mode(Mode.SCIENTIFIC)
        else:
            self._set_mode(Mode.SIMULATION)
    
    def _set_mode(self, mode: Mode):
        """设置模式"""
        self.mode = mode
        
        # 更新菜单
        self.sim_mode_action.setChecked(mode == Mode.SIMULATION)
        self.sci_mode_action.setChecked(mode == Mode.SCIENTIFIC)
        
        # 更新按钮文本
        if mode == Mode.SIMULATION:
            self.mode_btn.setText("🔬")
            self.mode_btn.setToolTip("切换科学模式")
        else:
            self.mode_btn.setText("🎮")
            self.mode_btn.setToolTip("切换模拟模式")
        
        # 更新组件
        self.body_list.set_mode(mode, self.unit_system, self.converter)
        self.inspector.set_mode(mode, self.unit_system, self.converter)
        self.sim_widget.set_mode(mode, self.unit_system, self.converter)
    
    def _toggle_left_panel(self):
        """切换左侧面板"""
        self.left_panel.setVisible(not self.left_panel.isVisible())
    
    def _toggle_right_panel(self):
        """切换右侧面板"""
        self.right_panel.setVisible(not self.right_panel.isVisible())
    
    def _on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "天体引力模拟器\n\n"
            "基于 Physics Engine + PyQt6 + OpenGL\n\n"
            "功能：\n"
            "- 多体引力模拟\n"
            "- 碰撞融合\n"
            "- 轨迹显示\n"
            "- 质心参考系\n"
            "- 模拟/科学模式切换"
        )

    def _update_status(self):
        """更新状态栏"""
        summary = self.profiler.summary()
        if summary is not None:
            self.fps_label.setText(f"FPS: {summary['fps']:.0f}")
        else:
            self.fps_label.setText("FPS: --")
        self.body_count_label.setText(f"天体: {len(self.engine.bodies)}")
        
        if self.mode == Mode.SIMULATION:
            formatter = SimulationFormatter(self.unit_system)
        else:
            formatter = ScientificFormatter(self.unit_system, self.converter)
        
        time_str = formatter.format_time(self.engine.simulation_time)
        self.time_label.setText(f"时间: {time_str}")
        
        # 更新质心显示
        com = self.reference_frame.center_of_mass
        self.com_label.setText(f"质心: ({com[0]:.2f}, {com[1]:.2f})")

    def _refresh_inspector(self):
        """10 Hz 刷新检查器（无选中天体时为空操作）。"""
        self.inspector.refresh()
    
    def _update_reference_frame(self):
        """更新参考系"""
        # 更新过渡
        dt = 0.05  # 50ms
        self.transition_manager.update(dt)
        
        # 计算质心
        self.reference_frame.compute_all(self.engine.bodies)
        
        # 跟随质心
        if self.follow_com and not self.transition_manager.is_camera_transition_active:
            com = self.reference_frame.center_of_mass
            # 平滑跟随
            self.camera.center_x += (com[0] - self.camera.center_x) * 0.1
            self.camera.center_y += (com[1] - self.camera.center_y) * 0.1


def main():
    """主函数"""
    app = ProfilingApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    apply_global_style(app)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
