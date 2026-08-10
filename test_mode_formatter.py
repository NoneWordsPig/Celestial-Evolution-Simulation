"""
Mode + Formatter + 模式切换 单元测试

测试范围：
1. Mode 枚举
2. SimulationFormatter 格式化
3. ScientificFormatter 格式化（有/无现实映射）
4. 模式切换前后物理状态完全一致
5. Physics Engine 只读查询接口
"""

import math
import copy
import unittest
import numpy as np

from physics import (
    Body, PhysicsEngine, GravitySolver,
    Mode, SimulationFormatter, ScientificFormatter,
    UnitSystem, UnitConverter,
)


class TestModeEnum(unittest.TestCase):
    """测试 Mode 枚举"""

    def test_two_modes_exist(self):
        """存在两种模式"""
        self.assertIsNotNone(Mode.SIMULATION)
        self.assertIsNotNone(Mode.SCIENTIFIC)

    def test_modes_are_distinct(self):
        """两种模式互不相同"""
        self.assertNotEqual(Mode.SIMULATION, Mode.SCIENTIFIC)

    def test_is_simulation_property(self):
        """is_simulation 属性"""
        self.assertTrue(Mode.SIMULATION.is_simulation)
        self.assertFalse(Mode.SCIENTIFIC.is_simulation)

    def test_is_scientific_property(self):
        """is_scientific 属性"""
        self.assertFalse(Mode.SIMULATION.is_scientific)
        self.assertTrue(Mode.SCIENTIFIC.is_scientific)

    def test_display_name(self):
        """显示名称"""
        self.assertEqual(Mode.SIMULATION.display_name, "模拟")
        self.assertEqual(Mode.SCIENTIFIC.display_name, "科学")

    def test_no_string_comparison(self):
        """Mode 不使用字符串比较"""
        self.assertNotEqual(Mode.SIMULATION, "SIMULATION")
        self.assertNotEqual(Mode.SCIENTIFIC, "SCIENTIFIC")
        self.assertIsInstance(Mode.SIMULATION, Mode)
        self.assertIsInstance(Mode.SCIENTIFIC, Mode)


class TestSimulationFormatter(unittest.TestCase):
    """测试 SimulationFormatter"""

    def setUp(self):
        self.fmt = SimulationFormatter()

    def test_format_mass(self):
        """质量格式化"""
        result = self.fmt.format_mass(1000.0)
        self.assertIn("MU", result)
        self.assertIn("1000", result)

    def test_format_distance(self):
        """距离格式化"""
        result = self.fmt.format_distance(10.0)
        self.assertIn("DU", result)
        self.assertIn("10", result)

    def test_format_position(self):
        """位置格式化"""
        result = self.fmt.format_position(10.0, 5.0)
        self.assertIn("X:", result)
        self.assertIn("Y:", result)
        self.assertIn("DU", result)

    def test_format_velocity(self):
        """速度格式化"""
        result = self.fmt.format_velocity(10.0)
        self.assertIn("DU/TU", result)

    def test_format_velocity_vector(self):
        """速度向量格式化"""
        result = self.fmt.format_velocity_vector(3.0, 4.0)
        self.assertIn("Vx:", result)
        self.assertIn("Vy:", result)

    def test_format_time(self):
        """时间格式化"""
        result = self.fmt.format_time(12.5)
        self.assertIn("TU", result)
        self.assertIn("12.5", result)

    def test_format_energy(self):
        """能量格式化"""
        result = self.fmt.format_energy(-500.0)
        self.assertIn("-500", result)

    def test_format_momentum(self):
        """动量格式化"""
        result = self.fmt.format_momentum(0.0, 10.0)
        self.assertIn("Px:", result)
        self.assertIn("Py:", result)

    def test_format_force(self):
        """力格式化"""
        result = self.fmt.format_force(1.5, -2.3)
        self.assertIn("Fx:", result)
        self.assertIn("Fy:", result)

    def test_no_scientific_notation(self):
        """模拟模式不使用科学计数法"""
        result = self.fmt.format_mass(1e10)
        self.assertNotIn("\u00d7", result)  # 无 × 符号（科学计数法标志）


class TestScientificFormatterNoMapping(unittest.TestCase):
    """测试 ScientificFormatter（无现实映射）"""

    def setUp(self):
        self.fmt = ScientificFormatter()

    def test_has_no_real_mapping(self):
        """无现实映射"""
        self.assertFalse(self.fmt.has_real_mapping)

    def test_mass_shows_fallback_warning(self):
        """质量显示回退提示"""
        result = self.fmt.format_mass(1000.0)
        self.assertIn("\u672a\u8bbe\u7f6e", result)  # "未设置"

    def test_distance_shows_fallback_warning(self):
        """距离显示回退提示"""
        result = self.fmt.format_distance(10.0)
        self.assertIn("\u672a\u8bbe\u7f6e", result)

    def test_velocity_shows_fallback_warning(self):
        """速度显示回退提示"""
        result = self.fmt.format_velocity(10.0)
        self.assertIn("\u672a\u8bbe\u7f6e", result)

    def test_time_shows_fallback_warning(self):
        """时间显示回退提示"""
        result = self.fmt.format_time(12.5)
        self.assertIn("\u672a\u8bbe\u7f6e", result)


class TestScientificFormatterWithMapping(unittest.TestCase):
    """测试 ScientificFormatter（有现实映射）"""

    def setUp(self):
        self.converter = UnitConverter.solar_system()
        self.fmt = ScientificFormatter(converter=self.converter)

    def test_has_real_mapping(self):
        """有现实映射"""
        self.assertTrue(self.fmt.has_real_mapping)

    def test_mass_shows_real_unit(self):
        """质量显示现实单位"""
        result = self.fmt.format_mass(1.0)
        # solar_system converter uses "Solar Mass" as unit
        self.assertIn(self.converter.real_mass_unit, result)

    def test_mass_scientific_notation(self):
        """质量使用科学计数法"""
        result = self.fmt.format_mass(1.0)
        self.assertIn("\u00d7", result)  # × 符号

    def test_distance_shows_meters(self):
        """距离显示米"""
        result = self.fmt.format_distance(1.0)
        # Should show AU or m
        self.assertTrue("m" in result or "AU" in result)

    def test_velocity_shows_km_per_s(self):
        """速度显示 km/s 或 m/s"""
        result = self.fmt.format_velocity(10.0)
        self.assertTrue("km/s" in result or "m/s" in result)

    def test_time_shows_days_or_years(self):
        """时间显示 days 或 years"""
        result = self.fmt.format_time(10.0)
        self.assertTrue("day" in result.lower() or "year" in result.lower())

    def test_energy_shows_joules(self):
        """能量显示焦耳"""
        result = self.fmt.format_energy(-100.0)
        self.assertIn("J", result)

    def test_momentum_shows_kg_m_per_s(self):
        """动量显示 kg*m/s"""
        result = self.fmt.format_momentum(0.0, 10.0)
        self.assertIn("kg", result)

    def test_no_fallback_warning_with_mapping(self):
        """有映射时不显示回退提示"""
        result = self.fmt.format_mass(1.0)
        self.assertNotIn("\u672a\u8bbe\u7f6e", result)


class TestModeSwitchPhysicsConsistency(unittest.TestCase):
    """测试模式切换前后物理状态完全一致"""

    def _create_engine_with_bodies(self):
        """创建带天体的引擎"""
        engine = PhysicsEngine(integrator_type='verlet', dt=0.01, time_scale=1.0)
        engine.add_body(Body(
            name="Star", mass=1000.0, physical_radius=2.0,
            position=(0.0, 0.0), velocity=(0.0, 0.0)
        ))
        engine.add_body(Body(
            name="Planet", mass=1.0, physical_radius=0.5,
            position=(10.0, 0.0), velocity=(0.0, 10.0)
        ))
        return engine

    def test_mode_switch_does_not_change_bodies(self):
        """模式切换不改变天体数据"""
        engine = self._create_engine_with_bodies()
        snapshot_before = engine.snapshot()

        # 模拟模式切换（仅改变 UI 层变量，不影响引擎）
        current_mode = Mode.SIMULATION
        current_mode = Mode.SCIENTIFIC
        current_mode = Mode.SIMULATION

        snapshot_after = engine.snapshot()

        # 验证物理状态完全一致
        self.assertEqual(snapshot_before['simulation_time'],
                        snapshot_after['simulation_time'])
        self.assertEqual(snapshot_before['body_count'],
                        snapshot_after['body_count'])
        for b_before, b_after in zip(snapshot_before['bodies'],
                                     snapshot_after['bodies']):
            self.assertEqual(b_before['mass'], b_after['mass'])
            np.testing.assert_array_equal(b_before['position'],
                                         b_after['position'])
            np.testing.assert_array_equal(b_before['velocity'],
                                         b_after['velocity'])
            self.assertEqual(b_before['physical_radius'],
                           b_after['physical_radius'])

    def test_mode_switch_does_not_change_simulation_time(self):
        """模式切换不改变模拟时间"""
        engine = self._create_engine_with_bodies()

        # 运行几步
        for _ in range(10):
            engine.step()

        time_before = engine.simulation_time

        # 切换模式
        mode = Mode.SIMULATION
        mode = Mode.SCIENTIFIC

        time_after = engine.simulation_time
        self.assertEqual(time_before, time_after)

    def test_mode_switch_does_not_pause(self):
        """模式切换不暂停模拟"""
        engine = self._create_engine_with_bodies()
        time_scale_before = engine.time_scale

        # 切换模式
        mode = Mode.SIMULATION
        mode = Mode.SCIENTIFIC

        time_scale_after = engine.time_scale
        self.assertEqual(time_scale_before, time_scale_after)

    def test_simulation_runs_identically_regardless_of_mode(self):
        """无论当前模式如何，物理模拟运行结果完全相同"""
        # 运行 A：mode = SIMULATION
        engine_a = self._create_engine_with_bodies()
        mode_a = Mode.SIMULATION  # 模式仅存在于 UI 层
        for _ in range(50):
            engine_a.step()

        # 运行 B：mode = SCIENTIFIC
        engine_b = self._create_engine_with_bodies()
        mode_b = Mode.SCIENTIFIC
        for _ in range(50):
            engine_b.step()

        # 物理结果应完全相同
        self.assertAlmostEqual(engine_a.simulation_time,
                              engine_b.simulation_time)
        self.assertAlmostEqual(engine_a.total_energy(),
                              engine_b.total_energy(), places=10)
        for ba, bb in zip(engine_a.bodies, engine_b.bodies):
            np.testing.assert_array_almost_equal(ba.position, bb.position)
            np.testing.assert_array_almost_equal(ba.velocity, bb.velocity)

    def test_mode_is_not_stored_in_engine(self):
        """PhysicsEngine 不存储 Mode"""
        engine = self._create_engine_with_bodies()
        self.assertFalse(hasattr(engine, 'mode'))
        self.assertFalse(hasattr(engine, 'current_mode'))


class TestEngineQueryInterfaces(unittest.TestCase):
    """测试 Physics Engine 只读查询接口"""

    def setUp(self):
        self.engine = PhysicsEngine(integrator_type='verlet', dt=0.01)
        self.engine.add_body(Body(
            name="Star", mass=1000.0, physical_radius=2.0,
            position=(0.0, 0.0), velocity=(0.0, 0.0)
        ))
        self.engine.add_body(Body(
            name="Planet", mass=1.0, physical_radius=0.5,
            position=(10.0, 0.0), velocity=(0.0, 10.0)
        ))

    def test_get_body_state(self):
        """获取天体状态快照"""
        state = self.engine.get_body_state(0)
        self.assertEqual(state['name'], "Star")
        self.assertAlmostEqual(state['mass'], 1000.0)
        np.testing.assert_array_equal(state['position'], [0.0, 0.0])

    def test_get_body_state_is_copy(self):
        """状态快照是副本，修改不影响引擎"""
        state = self.engine.get_body_state(0)
        state['mass'] = 99999.0
        self.assertAlmostEqual(self.engine.bodies[0].mass, 1000.0)

    def test_body_acceleration(self):
        """计算天体加速度"""
        acc = self.engine.body_acceleration(1)
        # Planet at (10,0), Star at (0,0), mass=1000
        # a = G*M/r^2 = 1000/100 = 10 (toward star, -x direction)
        self.assertLess(acc[0], 0)  # 指向 -x
        self.assertAlmostEqual(acc[1], 0.0, places=6)

    def test_body_net_force(self):
        """计算天体净引力"""
        force = self.engine.body_net_force(1)
        # With softening≈0（默认 ε=1e-8）: F ≈ G*M*m / r^2
        # = 1000*1 / 100 = 10
        self.assertLess(force[0], 0)  # toward -x
        self.assertGreater(abs(force[0]), 5.0)  # reasonable magnitude

    def test_body_distances(self):
        """计算天体间距"""
        distances = self.engine.body_distances(0)
        self.assertEqual(len(distances), 1)  # 只有 1 个其他天体
        self.assertAlmostEqual(distances[0], 10.0, places=6)

    def test_body_kinetic_energy(self):
        """计算天体动能"""
        ke = self.engine.body_kinetic_energy(1)
        # KE = 0.5 * m * v^2 = 0.5 * 1.0 * 100 = 50
        self.assertAlmostEqual(ke, 50.0, places=6)

    def test_get_all_body_states(self):
        """获取所有天体状态"""
        states = self.engine.get_all_body_states()
        self.assertEqual(len(states), 2)
        self.assertEqual(states[0]['name'], "Star")
        self.assertEqual(states[1]['name'], "Planet")

    def test_snapshot(self):
        """完整状态快照"""
        snap = self.engine.snapshot()
        self.assertIn('simulation_time', snap)
        self.assertIn('body_count', snap)
        self.assertIn('bodies', snap)
        self.assertEqual(snap['body_count'], 2)

    def test_snapshot_is_deep_copy(self):
        """快照是深拷贝"""
        snap = self.engine.snapshot()
        snap['bodies'][0]['mass'] = 99999.0
        self.assertAlmostEqual(self.engine.bodies[0].mass, 1000.0)

    def test_query_does_not_modify_state(self):
        """查询接口不修改物理状态"""
        snap_before = self.engine.snapshot()

        # 调用所有查询接口
        self.engine.get_body_state(0)
        self.engine.body_acceleration(0)
        self.engine.body_net_force(0)
        self.engine.body_distances(0)
        self.engine.body_kinetic_energy(0)
        self.engine.get_all_body_states()
        self.engine.snapshot()

        snap_after = self.engine.snapshot()

        self.assertEqual(snap_before['simulation_time'],
                        snap_after['simulation_time'])
        for b1, b2 in zip(snap_before['bodies'], snap_after['bodies']):
            np.testing.assert_array_equal(b1['position'], b2['position'])
            np.testing.assert_array_equal(b1['velocity'], b2['velocity'])


class TestFormatterWithEngine(unittest.TestCase):
    """测试 Formatter 与 Engine 配合使用"""

    def test_simulation_formatter_with_engine_data(self):
        """SimulationFormatter 格式化引擎数据"""
        engine = PhysicsEngine()
        engine.add_body(Body(name="Star", mass=1000.0, physical_radius=2.0,
                            position=(0.0, 0.0)))
        engine.add_body(Body(name="Planet", mass=1.0, physical_radius=0.5,
                            position=(10.0, 0.0), velocity=(0.0, 10.0)))

        fmt = SimulationFormatter()
        state = engine.get_body_state(1)

        mass_str = fmt.format_mass(state['mass'])
        self.assertIn("MU", mass_str)

        pos_str = fmt.format_position(state['position'][0], state['position'][1])
        self.assertIn("DU", pos_str)

        vel_str = fmt.format_velocity_vector(state['velocity'][0], state['velocity'][1])
        self.assertIn("DU/TU", vel_str)

        time_str = fmt.format_time(engine.simulation_time)
        self.assertIn("TU", time_str)

        energy_str = fmt.format_energy(engine.total_energy())
        self.assertIsInstance(energy_str, str)

    def test_scientific_formatter_with_engine_data(self):
        """ScientificFormatter 格式化引擎数据"""
        engine = PhysicsEngine()
        engine.add_body(Body(name="Star", mass=1.0, physical_radius=2.0,
                            position=(0.0, 0.0)))
        engine.add_body(Body(name="Planet", mass=1e-6, physical_radius=0.5,
                            position=(1.0, 0.0), velocity=(0.0, 1.0)))

        converter = UnitConverter.solar_system()
        fmt = ScientificFormatter(converter=converter)
        state = engine.get_body_state(0)

        mass_str = fmt.format_mass(state['mass'])
        self.assertIn(converter.real_mass_unit, mass_str)

        energy_str = fmt.format_energy(engine.total_energy())
        self.assertIn("J", energy_str)


if __name__ == '__main__':
    unittest.main(verbosity=2)
