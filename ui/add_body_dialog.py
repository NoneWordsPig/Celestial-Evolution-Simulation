"""
Add Body Dialog

添加天体对话框
"""

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QPushButton, QHBoxLayout, QColorDialog, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from physics import Body, Mode, UnitSystem, UnitConverter


class AddBodyDialog(QDialog):
    """
    添加天体对话框
    
    根据当前 Mode 显示不同的单位
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
        self.mass_spin = QDoubleSpinBox()
        self.mass_spin.setRange(0.001, 1e12)
        self.mass_spin.setDecimals(3)
        self.mass_spin.setValue(1.0)
        
        if self.mode == Mode.SIMULATION:
            self.mass_spin.setSuffix(" MU")
        else:
            if self.converter:
                self.mass_spin.setSuffix(f" {self.converter.real_mass_unit}")
            else:
                self.mass_spin.setSuffix(" MU")
        
        basic_layout.addRow("质量:", self.mass_spin)
        
        # 半径
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.01, 1e6)
        self.radius_spin.setDecimals(2)
        self.radius_spin.setValue(1.0)
        
        if self.mode == Mode.SIMULATION:
            self.radius_spin.setSuffix(" DU")
        else:
            if self.converter:
                self.radius_spin.setSuffix(f" {self.converter.real_distance_unit}")
            else:
                self.radius_spin.setSuffix(" DU")
        
        basic_layout.addRow("半径:", self.radius_spin)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # 位置组
        pos_group = QGroupBox("位置")
        pos_layout = QFormLayout()
        
        self.pos_x_spin = QDoubleSpinBox()
        self.pos_x_spin.setRange(-1e9, 1e9)
        self.pos_x_spin.setDecimals(2)
        self.pos_x_spin.setValue(10.0)
        
        self.pos_y_spin = QDoubleSpinBox()
        self.pos_y_spin.setRange(-1e9, 1e9)
        self.pos_y_spin.setDecimals(2)
        self.pos_y_spin.setValue(0.0)
        
        if self.mode == Mode.SIMULATION:
            unit = " DU"
        else:
            if self.converter:
                unit = f" {self.converter.real_distance_unit}"
            else:
                unit = " DU"
        
        self.pos_x_spin.setSuffix(unit)
        self.pos_y_spin.setSuffix(unit)
        
        pos_layout.addRow("X:", self.pos_x_spin)
        pos_layout.addRow("Y:", self.pos_y_spin)
        
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)
        
        # 速度组
        vel_group = QGroupBox("速度")
        vel_layout = QFormLayout()
        
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.0, 1e6)
        self.speed_spin.setDecimals(3)
        self.speed_spin.setValue(10.0)
        
        self.direction_spin = QDoubleSpinBox()
        self.direction_spin.setRange(0.0, 360.0)
        self.direction_spin.setDecimals(1)
        self.direction_spin.setValue(90.0)
        self.direction_spin.setSuffix("°")
        
        if self.mode == Mode.SIMULATION:
            self.speed_spin.setSuffix(" DU/TU")
        else:
            if self.converter:
                self.speed_spin.setSuffix(" km/s")
            else:
                self.speed_spin.setSuffix(" DU/TU")
        
        vel_layout.addRow("速率:", self.speed_spin)
        vel_layout.addRow("方向:", self.direction_spin)
        
        vel_group.setLayout(vel_layout)
        layout.addWidget(vel_group)
        
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
            speed = self.speed_spin.value()
        else:
            # 科学模式，需要转换
            if self.converter:
                mass = self.converter.real_to_sim_mass(self.mass_spin.value())
                radius = self.converter.real_to_sim_distance(self.radius_spin.value())
                pos_x = self.converter.real_to_sim_distance(self.pos_x_spin.value())
                pos_y = self.converter.real_to_sim_distance(self.pos_y_spin.value())
                speed = self.converter.real_to_sim_velocity(self.speed_spin.value() * 1000.0)  # km/s -> m/s
            else:
                mass = self.mass_spin.value()
                radius = self.radius_spin.value()
                pos_x = self.pos_x_spin.value()
                pos_y = self.pos_y_spin.value()
                speed = self.speed_spin.value()
        
        # 计算速度分量
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
