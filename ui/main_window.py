"""
主窗口

优化后的主窗口布局 - Simulation View 占据最大区域
集成质心参考系和过渡动画
"""

import sys
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar, QLabel,
    QMessageBox, QToolBar, QPushButton, QFrame, QApplication
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
        self.engine = PhysicsEngine(integrator_type='verlet', dt=0.1, time_scale=1.0)
        self.camera = Camera(viewport_width=800, viewport_height=600, zoom=10.0)
        
        # 参考系和过渡管理
        self.reference_frame = ReferenceFrame()
        self.transition_manager = TransitionManager()
        
        # 模式和单位
        self.mode = Mode.SIMULATION
        self.unit_system = UnitSystem()
        self.converter = None
        
        # 跟随质心标志
        self.follow_com = True
        
        # 添加示例天体
        self._add_demo_bodies()
        
        # 设置 UI
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()
        
        # 启动动画
        self.sim_widget.start_animation()
        
        # 状态更新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(100)
        
        # 参考系更新定时器
        self._ref_frame_timer = QTimer(self)
        self._ref_frame_timer.timeout.connect(self._update_reference_frame)
        self._ref_frame_timer.start(50)  # 20 Hz
        
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
        
        # 时间缩放
        toolbar.addWidget(QLabel("速度:"))
        self.time_scale_combo = self._create_time_scale_combo()
        toolbar.addWidget(self.time_scale_combo)
        
        toolbar.addSeparator()
        
        # 模式切换
        self.mode_btn = QPushButton("🔬")
        apply_button_style(self.mode_btn, 'toolbar')
        self.mode_btn.setFixedSize(36, 36)
        self.mode_btn.setToolTip("切换科学模式")
        self.mode_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self.mode_btn)
    
    def _create_time_scale_combo(self):
        """创建时间缩放下拉框"""
        from PyQt6.QtWidgets import QComboBox
        combo = QComboBox()
        time_scales = [
            ("0.1×", 0.1),
            ("0.5×", 0.5),
            ("1×", 1.0),
            ("2×", 2.0),
            ("5×", 5.0),
            ("10×", 10.0),
            ("100×", 100.0),
        ]
        for label, value in time_scales:
            combo.addItem(label, value)
        combo.setCurrentIndex(2)  # 默认 1×
        combo.currentIndexChanged.connect(self._on_time_scale_changed)
        return combo
    
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
    
    def _on_time_scale_changed(self):
        """时间缩放变化"""
        value = self.time_scale_combo.currentData()
        self.engine.time_scale = value
    
    def _on_add_body(self):
        """添加天体"""
        dialog = AddBodyDialog(self.mode, self.unit_system, self.converter, self)
        if dialog.exec():
            body = dialog.get_body()
            self.engine.add_body(body)
            self.body_list.refresh()
    
    def _on_body_selected(self, index: int):
        """天体被选中"""
        self.inspector.select_body(index)
        self.inspector.refresh()
    
    def _on_body_clicked(self, index: int):
        """天体被点击"""
        self.body_list.list_widget.setCurrentRow(index)
        self.inspector.select_body(index)
        self.inspector.refresh()
    
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
        self.fps_label.setText("FPS: ~60")
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
    app = QApplication(sys.argv)
    
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
