"""
Add Body 对话框接入独立 UnitSystem 的测试

验证：
1. 科学模式：现实单位 -> UnitSystem -> normalized simulation units
   - 1 M_sun -> mass = 1 MU
   - 1 AU   -> distance = 1 DU
2. 各类单位（kg/M_sun、m/km/AU、m/s/km/s/AU/T0）转换
3. 模拟模式：继续直接使用 normalized units（不受影响）
"""

import unittest
import sys

from PyQt6.QtWidgets import QApplication

# 确保只有一个 QApplication 实例
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.add_body_dialog import AddBodyDialog
from physics.mode import Mode
from physics import PhysicsEngine
from physics.unit_system import AU


class TestScientificModeWithUnitSystem(unittest.TestCase):
    """科学模式：UI 现实单位 -> UnitSystem -> normalized simulation units"""

    def setUp(self):
        self.dialog = AddBodyDialog(mode=Mode.SCIENTIFIC)

    def tearDown(self):
        self.dialog.close()

    def test_1_m_sun_1_au_engine_receives_normalized_values(self):
        """
        科学模式输入 1 M_sun、1 AU：
        最终 Physics Engine 收到 mass = 1、distance = 1
        """
        self.dialog.mass_spin.line_edit.setText("1")
        self.dialog.mass_unit_combo.setCurrentText("M_sun")

        self.dialog.radius_spin.line_edit.setText("1")
        self.dialog.radius_unit_combo.setCurrentText("AU")

        self.dialog.pos_x_spin.line_edit.setText("1")
        self.dialog.pos_x_unit_combo.setCurrentText("AU")
        self.dialog.pos_y_spin.line_edit.setText("0")
        self.dialog.pos_y_unit_combo.setCurrentText("AU")

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.mass, 1.0, places=12)
        self.assertAlmostEqual(body.physical_radius, 1.0, places=12)
        self.assertAlmostEqual(body.position[0], 1.0, places=12)
        self.assertAlmostEqual(body.position[1], 0.0, places=12)

        # Physics Engine 只接收 normalized values
        engine = PhysicsEngine()
        engine.add_body(body)
        self.assertAlmostEqual(engine.bodies[0].mass, 1.0, places=12)
        self.assertAlmostEqual(engine.bodies[0].physical_radius, 1.0, places=12)
        self.assertAlmostEqual(engine.bodies[0].position[0], 1.0, places=12)

    def test_mass_kg_to_mu(self):
        """5.972e24 kg -> 约 3.003e-6 MU"""
        self.dialog.mass_spin.line_edit.setText("5.972e24")
        self.dialog.mass_unit_combo.setCurrentText("kg")
        body = self.dialog.get_body()
        self.assertAlmostEqual(body.mass, 3.003e-6, delta=3.003e-6 * 0.01)

    def test_radius_km_to_du(self):
        """1.496e8 km（=1 AU）-> 1 DU"""
        self.dialog.radius_spin.line_edit.setText(f"{AU / 1000.0:.12g}")
        self.dialog.radius_unit_combo.setCurrentText("km")
        body = self.dialog.get_body()
        self.assertAlmostEqual(body.physical_radius, 1.0, places=6)

    def test_position_m_to_du(self):
        """1.496e11 m（=1 AU）-> 1 DU"""
        self.dialog.pos_x_spin.line_edit.setText(f"{AU:.12g}")
        self.dialog.pos_x_unit_combo.setCurrentText("m")
        body = self.dialog.get_body()
        self.assertAlmostEqual(body.position[0], 1.0, places=6)

    def test_velocity_km_s_to_normalized(self):
        """X/Y 模式：29.78 km/s -> 约 1 归一化速度单位"""
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        self.dialog.vx_spin.line_edit.setText("29.78")
        self.dialog.vx_unit_combo.setCurrentText("km/s")
        self.dialog.vy_spin.line_edit.setText("0")
        self.dialog.vy_unit_combo.setCurrentText("km/s")

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 1.0, places=3)
        self.assertAlmostEqual(body.velocity[1], 0.0, places=6)

    def test_polar_speed_au_t0(self):
        """V/θ 模式：speed=1 AU/T0, θ=90 -> (0, 1)"""
        self.dialog.speed_spin.line_edit.setText("1")
        self.dialog.speed_unit_combo.setCurrentText("AU/T0")
        self.dialog.direction_spin.line_edit.setText("90")

        body = self.dialog.get_body()
        self.assertAlmostEqual(body.velocity[0], 0.0, places=6)
        self.assertAlmostEqual(body.velocity[1], 1.0, places=6)

    def test_unit_selectors_exist_in_scientific_mode(self):
        self.assertEqual(
            [self.dialog.mass_unit_combo.itemText(i)
             for i in range(self.dialog.mass_unit_combo.count())],
            ["kg", "M_sun"],
        )
        self.assertEqual(
            [self.dialog.radius_unit_combo.itemText(i)
             for i in range(self.dialog.radius_unit_combo.count())],
            ["m", "km", "AU"],
        )
        self.assertEqual(
            [self.dialog.vx_unit_combo.itemText(i)
             for i in range(self.dialog.vx_unit_combo.count())],
            ["m/s", "km/s", "AU/T0"],
        )


class TestSimulationModeUnchanged(unittest.TestCase):
    """模拟模式：继续直接使用 normalized units"""

    def setUp(self):
        self.dialog = AddBodyDialog(mode=Mode.SIMULATION)

    def tearDown(self):
        self.dialog.close()

    def test_values_pass_through_directly(self):
        # 切换到 X/Y 输入模式（默认是 V/θ）
        self.dialog.cartesian_radio.setChecked(True)
        self.dialog._on_velocity_mode_changed()

        self.dialog.mass_spin.line_edit.setText("1")
        self.dialog.radius_spin.line_edit.setText("1")
        self.dialog.pos_x_spin.line_edit.setText("1")
        self.dialog.pos_y_spin.line_edit.setText("0")
        self.dialog.vx_spin.line_edit.setText("0.5")
        self.dialog.vy_spin.line_edit.setText("0")

        body = self.dialog.get_body()
        self.assertEqual(body.mass, 1.0)
        self.assertEqual(body.physical_radius, 1.0)
        self.assertEqual(body.position[0], 1.0)
        self.assertEqual(body.velocity[0], 0.5)

    def test_no_unit_selectors_in_simulation_mode(self):
        self.assertFalse(hasattr(self.dialog, 'mass_unit_combo'))
        self.assertFalse(hasattr(self.dialog, 'radius_unit_combo'))
        self.assertFalse(hasattr(self.dialog, 'pos_x_unit_combo'))
        self.assertFalse(hasattr(self.dialog, 'vx_unit_combo'))
        self.assertFalse(hasattr(self.dialog, 'speed_unit_combo'))


if __name__ == '__main__':
    unittest.main()
