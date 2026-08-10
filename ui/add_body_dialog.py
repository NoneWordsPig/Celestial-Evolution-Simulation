"""
Add Body Dialog

添加天体对话框
支持两种速度输入模式：笛卡尔坐标（vx, vy）和极坐标（speed, angle）
"""

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QColorDialog, QLabel, QGroupBox,
    QRadioButton, QButtonGroup, QStackedWidget, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from physics import Body, Mode, UnitSystem, UnitConverter
from .scientific_number_input import ScientificNumberInput


class AddBodyDialog(QDialog):
    """
    添加天体对话框
    
    根据当前 Mode 显示不同的单位
    支持两种速度输入模式：
    - 笛卡尔坐标模式：vx, vy
    - 极坐标模式：speed, angle
    """
    
    def __init__(
        self,
        mode: Mode = Mode.SIMULATION,
        unit_system: UnitSystem = None,
        converter: UnitConverter = None,
        parent=None
    ):
        super().__init__(parent)
        self.mode = mode
        self.unit_system = unit_system or UnitSystem()
        self.converter = converter
        
        self._selected_color = (0.3, 0.5, 1.0)  # 默认蓝色
        self._velocity_mode = 'polar'  # 默认极坐标模式
        
        self.setWindowTitle("添加天体")
        self.setMinimumWidth(350)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()
        
        # 名称
        self.name_edit = QLineEdit("Planet")
        basic_layout.addRow("名称:", self.name_edit)
        
        # 质量
        if self.mode == Mode.SIMULATION:
            mass_unit = " MU"
        else:
            if self.converter:
                mass_unit = f" {self.converter.real_mass_unit}"
            else:
                mass_unit = " MU"

        self.mass_spin = ScientificNumberInput(
            value=1.0, min_value=1e-30, max_value=1e38, suffix=mass_unit
        )
        
        basic_layout.addRow("质量:", self.mass_spin)
        
        # 半径
        if self.mode == Mode.SIMULATION:
            radius_unit = " DU"
        else:
            if self.converter:
                radius_unit = f" {self.converter.real_distance_unit}"
            else:
                radius_unit = " DU"

        self.radius_spin = ScientificNumberInput(
            value=0.1, min_value=1e-30, max_value=1e12, suffix=radius_unit
        )
        
        basic_layout.addRow("半径:", self.radius_spin)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # 位置组
        pos_group = QGroupBox("位置")
        pos_layout = QFormLayout()
        
        if self.mode == Mode.SIMULATION:
            unit = " DU"
        else:
            if self.converter:
                unit = f" {self.converter.real_distance_unit}"
            else:
                unit = " DU"

        self.pos_x_spin = ScientificNumberInput(
            value=10.0, min_value=-1e18, max_value=1e18, suffix=unit
        )
        self.pos_y_spin = ScientificNumberInput(
            value=0.0, min_value=-1e18, max_value=1e18, suffix=unit
        )
        
        pos_layout.addRow("X:", self.pos_x_spin)
        pos_layout.addRow("Y:", self.pos_y_spin)
        
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)
        
        # 速度组
        vel_group = QGroupBox("速度")
        vel_layout = QVBoxLayout()
        
        # 速度输入模式选择
        mode_layout = QHBoxLayout()
        mode_label = QLabel("输入模式:")
        mode_layout.addWidget(mode_label)
        
        self.cartesian_radio = QRadioButton("X/Y")
        self.polar_radio = QRadioButton("V/θ")
        self.polar_radio.setChecked(True)  # 默认极坐标
        
        self.velocity_mode_group = QButtonGroup()
        self.velocity_mode_group.addButton(self.cartesian_radio, 0)
        self.velocity_mode_group.addButton(self.polar_radio, 1)
        
        mode_layout.addWidget(self.cartesian_radio)
        mode_layout.addWidget(self.polar_radio)
        mode_layout.addStretch()
        
        # 连接信号：模式切换时更新输入区域
        self.velocity_mode_group.buttonClicked.connect(self._on_velocity_mode_changed)
        
        vel_layout.addLayout(mode_layout)
        
        # 速度输入堆叠组件
        self.vel_stack = QStackedWidget()
        
        # 笛卡尔模式页面
        cartesian_page = QWidget()
        cartesian_layout = QFormLayout()
        
        if self.mode == Mode.SIMULATION:
            vel_unit = " DU/TU"
        else:
            if self.converter:
                vel_unit = " km/s"
            else:
                vel_unit = " DU/TU"

        self.vx_spin = ScientificNumberInput(
            value=0.0, min_value=-1e12, max_value=1e12, suffix=vel_unit
        )
        self.vy_spin = ScientificNumberInput(
            value=10.0, min_value=-1e12, max_value=1e12, suffix=vel_unit
        )
        
        cartesian_layout.addRow("vx:", self.vx_spin)
        cartesian_layout.addRow("vy:", self.vy_spin)
        
        cartesian_page.setLayout(cartesian_layout)
        self.vel_stack.addWidget(cartesian_page)
        
        # 极坐标模式页面
        polar_page = QWidget()
        polar_layout = QFormLayout()
        
        self.speed_spin = ScientificNumberInput(
            value=10.0, min_value=0.0, max_value=1e12, suffix=vel_unit
        )
        self.direction_spin = ScientificNumberInput(
            value=90.0, min_value=-360.0, max_value=360.0, suffix="°"
        )
        
        polar_layout.addRow("速率:", self.speed_spin)
        polar_layout.addRow("角度:", self.direction_spin)
        
        polar_page.setLayout(polar_layout)
        self.vel_stack.addWidget(polar_page)
        
        # 默认显示极坐标页面（与 polar_radio 选中状态一致）
        self.vel_stack.setCurrentIndex(1)
        
        vel_layout.addWidget(self.vel_stack)
        
        vel_group.setLayout(vel_layout)
        layout.addWidget(vel_group)
        
        # 连接信号
        self.cartesian_radio.toggled.connect(self._on_velocity_mode_changed)
        self.polar_radio.toggled.connect(self._on_velocity_mode_changed)
        
        # 颜色
        color_group = QGroupBox("颜色")
        color_layout = QHBoxLayout()
        
        self.color_label = QLabel("████")
        self._update_color_display()
        color_layout.addWidget(self.color_label)
        
        self.color_btn = QPushButton("选择颜色...")
        self.color_btn.clicked.connect(self._on_color_clicked)
        color_layout.addWidget(self.color_btn)
        
        color_layout.addStretch()
        
        color_group.setLayout(color_layout)
        layout.addWidget(color_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _on_velocity_mode_changed(self):
        """速度输入模式切换"""
        if self.cartesian_radio.isChecked():
            # 切换到笛卡尔模式
            # 从极坐标转换到笛卡尔
            speed = self.speed_spin.value()
            angle_rad = np.radians(self.direction_spin.value())
            vx = speed * np.cos(angle_rad)
            vy = speed * np.sin(angle_rad)
            
            self.vx_spin.setValue(vx)
            self.vy_spin.setValue(vy)
            
            self.vel_stack.setCurrentIndex(0)
            self._velocity_mode = 'cartesian'
        else:
            # 切换到极坐标模式
            # 从笛卡尔转换到极坐标
            vx = self.vx_spin.value()
            vy = self.vy_spin.value()
            
            speed = np.sqrt(vx**2 + vy**2)
            angle = np.degrees(np.arctan2(vy, vx))
            
            self.speed_spin.setValue(speed)
            self.direction_spin.setValue(angle)
            
            self.vel_stack.setCurrentIndex(1)
            self._velocity_mode = 'polar'
    
    def _on_color_clicked(self):
        """选择颜色"""
        color = QColorDialog.getColor(
            QColor(
                int(self._selected_color[0] * 255),
                int(self._selected_color[1] * 255),
                int(self._selected_color[2] * 255)
            ),
            self
        )
        if color.isValid():
            self._selected_color = (
                color.red() / 255.0,
                color.green() / 255.0,
                color.blue() / 255.0
            )
            self._update_color_display()
    
    def _update_color_display(self):
        """更新颜色显示"""
        r, g, b = self._selected_color
        self.color_label.setStyleSheet(
            f"background-color: rgb({int(r*255)}, {int(g*255)}, {int(b*255)}); "
            f"padding: 5px; border: 1px solid gray;"
        )
    
    def get_body(self) -> Body:
        """获取创建的天体"""
        # 转换单位
        if self.mode == Mode.SIMULATION:
            mass = self.mass_spin.value()
            radius = self.radius_spin.value()
            pos_x = self.pos_x_spin.value()
            pos_y = self.pos_y_spin.value()
        else:
            # 科学模式，需要转换
            if self.converter:
                mass = self.converter.real_to_sim_mass(self.mass_spin.value())
                radius = self.converter.real_to_sim_distance(self.radius_spin.value())
                pos_x = self.converter.real_to_sim_distance(self.pos_x_spin.value())
                pos_y = self.converter.real_to_sim_distance(self.pos_y_spin.value())
            else:
                mass = self.mass_spin.value()
                radius = self.radius_spin.value()
                pos_x = self.pos_x_spin.value()
                pos_y = self.pos_y_spin.value()
        
        # 获取速度向量
        if self._velocity_mode == 'cartesian':
            # 笛卡尔模式
            if self.mode == Mode.SIMULATION:
                vx = self.vx_spin.value()
                vy = self.vy_spin.value()
            else:
                if self.converter:
                    # km/s -> m/s -> 模拟单位
                    vx = self.converter.real_to_sim_velocity(self.vx_spin.value() * 1000.0)
                    vy = self.converter.real_to_sim_velocity(self.vy_spin.value() * 1000.0)
                else:
                    vx = self.vx_spin.value()
                    vy = self.vy_spin.value()
        else:
            # 极坐标模式
            if self.mode == Mode.SIMULATION:
                speed = self.speed_spin.value()
            else:
                if self.converter:
                    # km/s -> m/s -> 模拟单位
                    speed = self.converter.real_to_sim_velocity(self.speed_spin.value() * 1000.0)
                else:
                    speed = self.speed_spin.value()
            
            direction_rad = np.radians(self.direction_spin.value())
            vx = speed * np.cos(direction_rad)
            vy = speed * np.sin(direction_rad)
        
        return Body(
            name=self.name_edit.text(),
            mass=mass,
            physical_radius=radius,
            position=(pos_x, pos_y),
            velocity=(vx, vy),
            color=self._selected_color
        )
