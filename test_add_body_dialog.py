"""
Add Body Dialog 单元测试

测试:
1. XY模式输入: vx=1, vy=2 -> velocity=(1, 2)
2. Polar模式输入: speed=10, theta=90 -> velocity~(0, 10)
3. 模式切换: XY -> Polar -> XY 数值保持一致
"""

import unittest
import sys
import numpy as np

from PyQt6.QtWidgets import QApplication

# 确保只有一个 QApplication 实例
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.add_body_dialog import AddBodyDialog
from physics.mode import Mode


class TestAddBodyDialogXYMode(unittest.TestCase):
    """测试笛卡尔坐标速度输入模式"""

    def setUp(self):
        """创建对话框并切换到XY模式"""
        self.dialog = AddBodyDialog(mode=Mode.SIMULATION)
        # 切换到笛卡尔模式
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

    def tearDown(self):
        self.dialog.close()

    def test_velocity_mode_is_cartesian(self):
        """验证切换后模式为cartesian"""
        self.assertEqual(self.dialog._velocity_mode, 'cartesian')

    def test_stack_shows_cartesian_page(self):
        """验证堆叠组件显示笛卡尔页面"""
        self.assertEqual(self.dialog.vel_stack.currentIndex(), 0)

    def test_xy_input_vx1_vy2(self):
        """XY输入: vx=1, vy=2 -> velocity=(1, 2)"""
        self.dialog.vx_spin.setValue(1.0)
        self.dialog.vy_spin.setValue(2.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 1.0, places=5)
        self.assertAlmostEqual(body.velocity[1], 2.0, places=5)

    def test_xy_input_negative_values(self):
        """XY输入: vx=-3, vy=-4"""
        self.dialog.vx_spin.setValue(-3.0)
        self.dialog.vy_spin.setValue(-4.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], -3.0, places=5)
        self.assertAlmostEqual(body.velocity[1], -4.0, places=5)

    def test_xy_input_zero(self):
        """XY输入: vx=0, vy=0"""
        self.dialog.vx_spin.setValue(0.0)
        self.dialog.vy_spin.setValue(0.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 0.0, places=5)
        self.assertAlmostEqual(body.velocity[1], 0.0, places=5)


class TestAddBodyDialogPolarMode(unittest.TestCase):
    """测试极坐标速度输入模式"""

    def setUp(self):
        """创建对话框，默认就是极坐标模式"""
        self.dialog = AddBodyDialog(mode=Mode.SIMULATION)

    def tearDown(self):
        self.dialog.close()

    def test_default_mode_is_polar(self):
        """默认模式为极坐标"""
        self.assertEqual(self.dialog._velocity_mode, 'polar')
        self.assertTrue(self.dialog.polar_radio.isChecked())

    def test_stack_shows_polar_page(self):
        """堆叠组件默认显示极坐标页面"""
        self.assertEqual(self.dialog.vel_stack.currentIndex(), 1)

    def test_polar_input_speed10_theta90(self):
        """Polar输入: speed=10, theta=90 -> velocity~(0, 10)"""
        self.dialog.speed_spin.setValue(10.0)
        self.dialog.direction_spin.setValue(90.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 0.0, places=4)
        self.assertAlmostEqual(body.velocity[1], 10.0, places=4)

    def test_polar_input_speed5_theta0(self):
        """Polar输入: speed=5, theta=0 -> velocity~(5, 0)"""
        self.dialog.speed_spin.setValue(5.0)
        self.dialog.direction_spin.setValue(0.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 5.0, places=4)
        self.assertAlmostEqual(body.velocity[1], 0.0, places=4)

    def test_polar_input_speed5_theta180(self):
        """Polar输入: speed=5, theta=180 -> velocity~(-5, 0)"""
        self.dialog.speed_spin.setValue(5.0)
        self.dialog.direction_spin.setValue(180.0)

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], -5.0, places=4)
        self.assertAlmostEqual(body.velocity[1], 0.0, places=3)


class TestAddBodyDialogModeSwitch(unittest.TestCase):
    """测试速度输入模式切换"""

    def setUp(self):
        self.dialog = AddBodyDialog(mode=Mode.SIMULATION)

    def tearDown(self):
        self.dialog.close()

    def test_polar_to_cartesian_conversion(self):
        """Polar -> Cartesian: 数值自动转换保持一致"""
        # 设置极坐标
        self.dialog.speed_spin.setValue(10.0)
        self.dialog.direction_spin.setValue(45.0)

        # 切换到笛卡尔
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # 验证转换后的笛卡尔值
        expected_vx = 10.0 * np.cos(np.radians(45.0))
        expected_vy = 10.0 * np.sin(np.radians(45.0))

        self.assertAlmostEqual(self.dialog.vx_spin.value(), expected_vx, places=3)
        self.assertAlmostEqual(self.dialog.vy_spin.value(), expected_vy, places=3)
        self.assertEqual(self.dialog._velocity_mode, 'cartesian')

    def test_cartesian_to_polar_conversion(self):
        """Cartesian -> Polar: 数值自动转换保持一致"""
        # 先切换到笛卡尔
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # 设置笛卡尔值
        self.dialog.vx_spin.setValue(3.0)
        self.dialog.vy_spin.setValue(4.0)

        # 切换到极坐标
        self.dialog.polar_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # 验证转换后的极坐标值
        expected_speed = 5.0  # sqrt(9+16)
        expected_angle = np.degrees(np.arctan2(4.0, 3.0))

        self.assertAlmostEqual(self.dialog.speed_spin.value(), expected_speed, places=2)
        self.assertAlmostEqual(self.dialog.direction_spin.value(), expected_angle, places=1)
        self.assertEqual(self.dialog._velocity_mode, 'polar')

    def test_round_trip_xy_polar_xy(self):
        """XY -> Polar -> XY: 数值在合理精度内保持一致"""
        # 设置初始XY值
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        self.dialog.vx_spin.setValue(1.0)
        self.dialog.vy_spin.setValue(2.0)

        original_vx = self.dialog.vx_spin.value()
        original_vy = self.dialog.vy_spin.value()

        # XY -> Polar
        self.dialog.polar_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # Polar -> XY
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # 验证往返转换后数值一致（精度受direction_spin限制）
        self.assertAlmostEqual(self.dialog.vx_spin.value(), original_vx, places=2)
        self.assertAlmostEqual(self.dialog.vy_spin.value(), original_vy, places=2)

    def test_round_trip_produces_same_body(self):
        """XY -> Polar -> XY 后创建的Body速度一致"""
        # 设置XY模式
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()
        self.dialog.vx_spin.setValue(1.0)
        self.dialog.vy_spin.setValue(2.0)

        body_before = self.dialog.get_body()

        # XY -> Polar
        self.dialog.polar_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # Polar -> XY
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        body_after = self.dialog.get_body()

        self.assertAlmostEqual(body_before.velocity[0], body_after.velocity[0], places=2)
        self.assertAlmostEqual(body_before.velocity[1], body_after.velocity[1], places=2)

    def test_get_body_uses_correct_mode_after_switch(self):
        """切换模式后 get_body 使用正确的输入字段"""
        # 从默认polar开始
        self.dialog.speed_spin.setValue(7.0)
        self.dialog.direction_spin.setValue(30.0)

        body_polar = self.dialog.get_body()

        # 切换到cartesian
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        # 修改笛卡尔值
        self.dialog.vx_spin.setValue(100.0)
        self.dialog.vy_spin.setValue(200.0)

        body_cart = self.dialog.get_body()

        # polar的结果不应该等于cartesian的结果
        self.assertNotAlmostEqual(body_polar.velocity[0], body_cart.velocity[0], places=1)
        self.assertAlmostEqual(body_cart.velocity[0], 100.0, places=3)
        self.assertAlmostEqual(body_cart.velocity[1], 200.0, places=3)


if __name__ == '__main__':
    unittest.main()
