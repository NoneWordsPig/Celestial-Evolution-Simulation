"""
Main Window

主窗口，整合所有组件
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar, QLabel,
    QMessageBox, QToolBar
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction

from physics import (
    PhysicsEngine, Camera, Mode, UnitSystem, UnitConverter,
    SimulationFormatter, ScientificFormatter
)
from .simulation_widget import SimulationWidget
from .body_list_widget import BodyListWidget
from .inspector_widget import InspectorWidget
from .control_panel import ControlPanel
from .add_body_dialog import AddBodyDialog


class MainWindow(QMainWindow):
    """
    主窗口
    
    布局：
    - 顶部：菜单栏 + 工具栏
    - 左侧：天体列表
    - 中间：OpenGL 模拟视图
    - 右侧：检查器
    - 底部：状态栏
    """
    
    def __init__(self):
        super().__init__()
        
        # 核心组件
        self.engine = PhysicsEngine(integrator_type='verlet', dt=0.1, time_scale=1.0)
        self.camera = Camera(viewport_width=800, viewport_height=600, zoom=10.0)
        
        # 模式和单位
        self.mode = Mode.SIMULATION
        self.unit_system = UnitSystem()
        self.converter = None  # 可以设置为 UnitConverter.solar_system()
        
        # 添加示例天体
        self._add_demo_bodies()
        
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
        self._status_timer.start(100)  # 10 Hz
    
    def _add_demo_bodies(self):
        """添加示例天体"""
        from physics import Body
        import numpy as np
        
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
            velocity=(0.0, 10.0),  # 圆轨道速度
            color=(0.3, 0.5, 1.0)
        )
        self.engine.add_body(planet)
    
    def _setup_ui(self):
        """设置 UI"""
        self.setWindowTitle("天体引力模拟器")
        self.setMinimumSize(1200, 800)
        
        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 控制面板
        self.control_panel = ControlPanel(self.engine)
        main_layout.addWidget(self.control_panel)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：天体列表
        self.body_list = BodyListWidget(
            self.engine, self.mode, self.unit_system, self.converter
        )
        self.body_list.setMinimumWidth(200)
        splitter.addWidget(self.body_list)
        
        # 中间：模拟视图
        self.sim_widget = SimulationWidget(self.engine, self.camera)
        self.sim_widget.setMinimumWidth(600)
        splitter.addWidget(self.sim_widget)
        
        # 右侧：检查器
        self.inspector = InspectorWidget(
            self.engine, self.mode, self.unit_system, self.converter
        )
        self.inspector.setMinimumWidth(250)
        splitter.addWidget(self.inspector)
        
        # 设置分割比例
        splitter.setSizes([200, 600, 250])
        
        main_layout.addWidget(splitter)
        
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
        """设置工具栏"""
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        
        add_action = QAction("添加", self)
        add_action.triggered.connect(self._on_add_body)
        toolbar.addAction(add_action)
        
        toolbar.addSeparator()
        
        reset_action = QAction("重置摄像机", self)
        reset_action.triggered.connect(self._on_reset_camera)
        toolbar.addAction(reset_action)
        
        fit_action = QAction("适应全部", self)
        fit_action.triggered.connect(self._on_fit_all_bodies)
        toolbar.addAction(fit_action)
    
    def _setup_statusbar(self):
        """设置状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        self.fps_label = QLabel("FPS: 0")
        self.body_count_label = QLabel("天体: 0")
        self.time_label = QLabel("时间: 0.00 TU")
        
        self.statusbar.addPermanentWidget(self.fps_label)
        self.statusbar.addPermanentWidget(self.body_count_label)
        self.statusbar.addPermanentWidget(self.time_label)
    
    def _connect_signals(self):
        """连接信号"""
        # 控制面板
        self.control_panel.play_requested.connect(self.sim_widget.resume)
        self.control_panel.pause_requested.connect(self.sim_widget.pause)
        self.control_panel.step_requested.connect(self.sim_widget.step)
        
        # 天体列表
        self.body_list.body_selected.connect(self._on_body_selected)
        self.body_list.body_delete_requested.connect(self._on_delete_body)
        
        # 模拟视图
        self.sim_widget.body_clicked.connect(self._on_body_clicked)
    
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
            import numpy as np
            positions = np.array([b.position for b in self.engine.bodies])
            self.camera.fit_all_bodies(positions)
            self.sim_widget.update()
    
    def _set_mode(self, mode: Mode):
        """设置模式"""
        self.mode = mode
        
        # 更新菜单
        self.sim_mode_action.setChecked(mode == Mode.SIMULATION)
        self.sci_mode_action.setChecked(mode == Mode.SCIENTIFIC)
        
        # 更新组件
        self.body_list.set_mode(mode, self.unit_system, self.converter)
        self.inspector.set_mode(mode, self.unit_system, self.converter)
    
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
            "- 模拟/科学模式切换"
        )
    
    def _update_status(self):
        """更新状态栏"""
        # FPS（简化处理）
        self.fps_label.setText("FPS: ~60")
        
        # 天体数量
        self.body_count_label.setText(f"天体: {len(self.engine.bodies)}")
        
        # 时间
        if self.mode == Mode.SIMULATION:
            formatter = SimulationFormatter(self.unit_system)
        else:
            formatter = ScientificFormatter(self.unit_system, self.converter)
        
        time_str = formatter.format_time(self.engine.simulation_time)
        self.time_label.setText(f"时间: {time_str}")
