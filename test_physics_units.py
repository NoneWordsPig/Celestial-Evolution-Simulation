"""
Physics Engine 单元测试

测试范围：
1. Body 类：physical_radius 与 render_radius 分离
2. GravitySolver：G=1 的引力计算
3. 模拟单位下的圆轨道稳定性
4. UnitSystem：速度单位、时间单位推导
5. UnitConverter：单位转换接口
6. 碰撞融合中 physical_radius 与 render_radius 不互相污染
"""

import math
import numpy as np
import unittest

from physics import (
    Body, PhysicsEngine, GravitySolver, CollisionHandler,
    VelocityVerletIntegrator, RK4Integrator,
    UnitSystem, UnitConverter, DEFAULT_UNITS,
    G, SOFTENING,
)


class TestBodyRadiusSeparation(unittest.TestCase):
    """测试 Body 类 physical_radius 与 render_radius 的分离"""

    def test_default_render_equals_physical(self):
        """默认情况下 render_radius 等于 physical_radius"""
        body = Body(name="test", mass=1.0, physical_radius=5.0)
        self.assertAlmostEqual(body.physical_radius, 5.0)
        self.assertAlmostEqual(body.render_radius, 5.0)

    def test_independent_render_radius(self):
        """render_radius 可以独立设置，不影响 physical_radius"""
        body = Body(
            name="test", mass=1.0,
            physical_radius=2.0, render_radius=10.0
        )
        self.assertAlmostEqual(body.physical_radius, 2.0)
        self.assertAlmostEqual(body.render_radius, 10.0)

    def test_modifying_render_does_not_affect_physical(self):
        """修改 render_radius 不应影响 physical_radius"""
        body = Body(name="test", mass=1.0, physical_radius=3.0, render_radius=3.0)
        body.render_radius = 50.0
        self.assertAlmostEqual(body.physical_radius, 3.0)
        self.assertAlmostEqual(body.render_radius, 50.0)

    def test_modifying_physical_does_not_affect_render(self):
        """修改 physical_radius 不应自动修改 render_radius"""
        body = Body(name="test", mass=1.0, physical_radius=3.0, render_radius=10.0)
        body.physical_radius = 7.0
        self.assertAlmostEqual(body.physical_radius, 7.0)
        self.assertAlmostEqual(body.render_radius, 10.0)

    def test_radius_backward_compat_property(self):
        """radius 属性应返回 physical_radius（向后兼容）"""
        body = Body(name="test", mass=1.0, physical_radius=4.5, render_radius=20.0)
        self.assertAlmostEqual(body.radius, 4.5)
        self.assertAlmostEqual(body.radius, body.physical_radius)

    def test_minimum_render_radius(self):
        """render_radius 有最小值保护"""
        body = Body(name="test", mass=1.0, physical_radius=1.0, render_radius=0.001)
        self.assertGreaterEqual(body.render_radius, 0.1)


class TestGravityG1(unittest.TestCase):
    """测试 G=1 的引力计算"""

    def test_G_value(self):
        """确认 G=1"""
        self.assertEqual(G, 1.0)

    def test_two_body_force_magnitude(self):
        """两体引力大小：F = m1*m2 / (r^2 + softening^2)"""
        solver = GravitySolver(softening=0.0)
        b1 = Body(name="m1", mass=100.0, physical_radius=1.0,
                  position=(0.0, 0.0))
        b2 = Body(name="m2", mass=1.0, physical_radius=1.0,
                  position=(10.0, 0.0))
        
        accels = solver.compute_accelerations([b1, b2])
        
        # a2 = G * m1 / r^2 = 1.0 * 100 / 100 = 1.0 (toward b1, i.e. -x direction)
        expected_a2 = -100.0 / (10.0 ** 2)  # = -1.0
        self.assertAlmostEqual(accels[1][0], expected_a2, places=6)
        self.assertAlmostEqual(accels[1][1], 0.0, places=6)

    def test_newton_third_law(self):
        """牛顿第三定律：m1*a1 + m2*a2 = 0"""
        solver = GravitySolver(softening=0.0)
        b1 = Body(name="m1", mass=50.0, physical_radius=1.0,
                  position=(0.0, 0.0))
        b2 = Body(name="m2", mass=20.0, physical_radius=1.0,
                  position=(5.0, 3.0))
        
        accels = solver.compute_accelerations([b1, b2])
        
        force_on_1 = b1.mass * accels[0]
        force_on_2 = b2.mass * accels[1]
        total_force = force_on_1 + force_on_2
        
        self.assertAlmostEqual(total_force[0], 0.0, places=10)
        self.assertAlmostEqual(total_force[1], 0.0, places=10)

    def test_softening_prevents_singularity(self):
        """软化因子防止零距离时的奇点"""
        solver = GravitySolver(softening=5.0)
        b1 = Body(name="m1", mass=100.0, physical_radius=1.0,
                  position=(0.0, 0.0))
        b2 = Body(name="m2", mass=1.0, physical_radius=1.0,
                  position=(0.0, 0.0))  # 同位置
        
        accels = solver.compute_accelerations([b1, b2])
        
        # 加速度应为有限值
        self.assertTrue(np.all(np.isfinite(accels)))

    def test_potential_energy_negative(self):
        """引力势能应为负值"""
        solver = GravitySolver(softening=0.0)
        b1 = Body(name="m1", mass=100.0, physical_radius=1.0,
                  position=(0.0, 0.0))
        b2 = Body(name="m2", mass=1.0, physical_radius=1.0,
                  position=(10.0, 0.0))
        
        pe = solver.potential_energy([b1, b2])
        self.assertLess(pe, 0.0)
        # PE = -G * m1 * m2 / r = -100 / 10 = -10
        self.assertAlmostEqual(pe, -10.0, places=4)


class TestCircularOrbit(unittest.TestCase):
    """测试模拟单位下的圆轨道"""

    def test_circular_orbit_velocity_formula(self):
        """圆轨道速度 v = sqrt(G * M / r)"""
        units = UnitSystem()
        M = 1000.0  # MU
        r = 10.0    # DU
        v_expected = math.sqrt(1.0 * M / r)  # = 10.0
        v_computed = units.circular_orbital_velocity(M, r)
        self.assertAlmostEqual(v_computed, v_expected, places=10)
        self.assertAlmostEqual(v_computed, 10.0, places=10)

    def test_circular_orbit_stability_verlet(self):
        """Velocity Verlet 下圆轨道应保持稳定（能量守恒）"""
        central_mass = 1000.0
        orbit_radius = 10.0
        v_circular = math.sqrt(central_mass / orbit_radius)  # = 10.0
        
        engine = PhysicsEngine(integrator_type='verlet', dt=0.01, time_scale=1.0)
        engine.add_body(Body(
            name="Star", mass=central_mass, physical_radius=2.0,
            position=(0.0, 0.0), velocity=(0.0, 0.0)
        ))
        engine.add_body(Body(
            name="Planet", mass=1.0, physical_radius=0.5,
            position=(orbit_radius, 0.0), velocity=(0.0, v_circular)
        ))
        
        # 初始能量
        E_initial = engine.total_energy()
        
        # 运行一个完整轨道周期
        period = 2.0 * math.pi * math.sqrt(orbit_radius ** 3 / central_mass)
        n_steps = int(period / 0.01) + 10
        
        for _ in range(n_steps):
            engine.step()
        
        E_final = engine.total_energy()
        
        # Velocity Verlet 是辛积分器，能量误差应有界
        relative_error = abs((E_final - E_initial) / E_initial)
        self.assertLess(relative_error, 0.01, 
                        f"Energy drift too large: {relative_error:.6f}")

    def test_circular_orbit_stability_rk4(self):
        """RK4 下圆轨道应保持稳定（更高精度）"""
        central_mass = 1000.0
        orbit_radius = 10.0
        v_circular = math.sqrt(central_mass / orbit_radius)
        
        engine = PhysicsEngine(integrator_type='rk4', dt=0.01, time_scale=1.0)
        engine.add_body(Body(
            name="Star", mass=central_mass, physical_radius=2.0,
            position=(0.0, 0.0), velocity=(0.0, 0.0)
        ))
        engine.add_body(Body(
            name="Planet", mass=1.0, physical_radius=0.5,
            position=(orbit_radius, 0.0), velocity=(0.0, v_circular)
        ))
        
        E_initial = engine.total_energy()
        
        period = 2.0 * math.pi * math.sqrt(orbit_radius ** 3 / central_mass)
        n_steps = int(period / 0.01) + 10
        
        for _ in range(n_steps):
            engine.step()
        
        E_final = engine.total_energy()
        relative_error = abs((E_final - E_initial) / E_initial)
        self.assertLess(relative_error, 0.001,
                        f"Energy drift too large: {relative_error:.6f}")

    def test_orbit_period_formula(self):
        """轨道周期 T = 2*pi*sqrt(r^3 / (G*M))"""
        units = UnitSystem()
        M = 1000.0
        r = 10.0
        T_expected = 2.0 * math.pi * math.sqrt(r ** 3 / M)
        T_computed = units.orbital_period(M, r)
        self.assertAlmostEqual(T_computed, T_expected, places=10)


class TestUnitSystem(unittest.TestCase):
    """测试 UnitSystem 速度单位和时间单位推导"""

    def test_default_units_are_dimensionless(self):
        """默认模拟单位中 G=1, MU=1, DU=1, TU=1"""
        units = UnitSystem()
        self.assertEqual(units.G_value, 1.0)
        self.assertAlmostEqual(units.derived_time_unit(), 1.0)
        self.assertAlmostEqual(units.derived_velocity_unit(), 1.0)

    def test_velocity_unit_consistency(self):
        """速度单位 VU = sqrt(G * MU / DU) = DU / TU"""
        units = UnitSystem()
        vu_from_formula = math.sqrt(units.G_value * 1.0 / 1.0)
        vu_from_ratio = 1.0 / units.derived_time_unit()
        self.assertAlmostEqual(vu_from_formula, vu_from_ratio, places=10)

    def test_time_unit_consistency(self):
        """时间单位 TU = sqrt(DU^3 / (G * MU))"""
        units = UnitSystem()
        tu_from_formula = math.sqrt(1.0 ** 3 / (units.G_value * 1.0))
        self.assertAlmostEqual(units.derived_time_unit(), tu_from_formula, places=10)

    def test_unit_names(self):
        """单位名称显示正确"""
        units = UnitSystem()
        self.assertEqual(units.mass_unit, "MU")
        self.assertEqual(units.distance_unit, "DU")
        self.assertEqual(units.time_unit, "TU")
        self.assertEqual(units.velocity_unit, "DU/TU")

    def test_format_mass(self):
        """质量格式化"""
        units = UnitSystem()
        self.assertEqual(units.format_mass(1000.0), "1000.00 MU")

    def test_format_distance(self):
        """距离格式化"""
        units = UnitSystem()
        self.assertEqual(units.format_distance(10.0), "10.00 DU")

    def test_format_velocity(self):
        """速度格式化"""
        units = UnitSystem()
        self.assertEqual(units.format_velocity(10.0), "10.00 DU/TU")

    def test_format_time(self):
        """时间格式化"""
        units = UnitSystem()
        self.assertEqual(units.format_time(6.28), "6.28 TU")

    def test_default_units_global(self):
        """全局默认单位实例存在"""
        self.assertIsInstance(DEFAULT_UNITS, UnitSystem)
        self.assertEqual(DEFAULT_UNITS.G_value, 1.0)


class TestUnitConverter(unittest.TestCase):
    """测试 UnitConverter 单位转换接口"""

    def test_identity_converter(self):
        """恒等转换器：所有转换因子为 1"""
        converter = UnitConverter(
            real_distance_per_DU=1.0,
            real_mass_per_MU=1.0
        )
        self.assertAlmostEqual(converter.sim_to_real_distance(5.0), 5.0)
        self.assertAlmostEqual(converter.sim_to_real_mass(10.0), 10.0)

    def test_roundtrip_distance(self):
        """距离转换往返一致性"""
        converter = UnitConverter(
            real_distance_per_DU=1.496e11,
            real_mass_per_MU=1.989e30
        )
        original = 10.0
        real = converter.sim_to_real_distance(original)
        back = converter.real_to_sim_distance(real)
        self.assertAlmostEqual(back, original, places=10)

    def test_roundtrip_mass(self):
        """质量转换往返一致性"""
        converter = UnitConverter(
            real_distance_per_DU=1.496e11,
            real_mass_per_MU=1.989e30
        )
        original = 1000.0
        real = converter.sim_to_real_mass(original)
        back = converter.real_to_sim_mass(real)
        self.assertAlmostEqual(back, original, places=10)

    def test_roundtrip_time(self):
        """时间转换往返一致性"""
        converter = UnitConverter(
            real_distance_per_DU=1.496e11,
            real_mass_per_MU=1.989e30
        )
        original = 6.28
        real = converter.sim_to_real_time(original)
        back = converter.real_to_sim_time(real)
        self.assertAlmostEqual(back, original, places=8)

    def test_roundtrip_velocity(self):
        """速度转换往返一致性"""
        converter = UnitConverter(
            real_distance_per_DU=1.496e11,
            real_mass_per_MU=1.989e30
        )
        original = 10.0
        real = converter.sim_to_real_velocity(original)
        back = converter.real_to_sim_velocity(real)
        self.assertAlmostEqual(back, original, places=8)

    def test_solar_system_factory(self):
        """太阳系工厂方法"""
        converter = UnitConverter.solar_system()
        # 1 DU = 1 AU
        self.assertAlmostEqual(
            converter.sim_to_real_distance(1.0), 1.496e11, delta=1e8
        )
        # 1 MU = 1 Solar Mass
        self.assertAlmostEqual(
            converter.sim_to_real_mass(1.0), 1.989e30, delta=1e27
        )
        # TU 应为正数
        self.assertGreater(converter.real_time_per_TU, 0.0)
        # VU 应为正数
        self.assertGreater(converter.real_velocity_per_VU, 0.0)

    def test_derived_time_unit_physical(self):
        """推导的现实时间单位应有物理意义"""
        converter = UnitConverter.solar_system()
        # 1 TU = sqrt(AU^3 / (G * SolarMass))
        expected_TU = math.sqrt(
            1.496e11 ** 3 / (6.67430e-11 * 1.989e30)
        )
        self.assertAlmostEqual(
            converter.real_time_per_TU, expected_TU, delta=expected_TU * 0.01
        )

    def test_format_real_time_days(self):
        """格式化现实时间：1 TU 在太阳系单位下约 58 天"""
        converter = UnitConverter.solar_system()
        # 1 TU = sqrt(AU^3 / (G * SolarMass)) ~ 5.02e6 seconds ~ 58 days
        result = converter.format_real_time(1.0)
        self.assertIn("days", result.lower())

    def test_format_real_time_years(self):
        """格式化现实时间：大时间值显示为年"""
        converter = UnitConverter.solar_system()
        # 10 TU ~ 580 days ~ 1.59 years
        result = converter.format_real_time(10.0)
        self.assertIn("year", result.lower())

    def test_converter_does_not_affect_physics(self):
        """UnitConverter 不应影响物理引擎计算"""
        converter = UnitConverter.solar_system()
        
        # 物理引擎应始终使用模拟单位
        engine = PhysicsEngine(dt=0.01, time_scale=1.0)
        engine.add_body(Body(name="A", mass=100.0, physical_radius=1.0,
                            position=(0.0, 0.0)))
        engine.add_body(Body(name="B", mass=1.0, physical_radius=0.5,
                            position=(10.0, 0.0), velocity=(0.0, 1.0)))
        
        E_before = engine.total_energy()
        engine.step()
        E_after = engine.total_energy()
        
        # 物理引擎不受 converter 影响，能量应守恒
        self.assertAlmostEqual(E_before, E_after, places=4)


class TestCollisionRadiusIsolation(unittest.TestCase):
    """测试碰撞融合中 physical_radius 与 render_radius 不互相污染"""

    def test_merge_preserves_separate_radii(self):
        """融合后 physical_radius 和 render_radius 分别独立计算"""
        handler = CollisionHandler()
        
        b1 = Body(name="A", mass=10.0,
                  physical_radius=2.0, render_radius=8.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=5.0,
                  physical_radius=1.0, render_radius=5.0,
                  position=(2.0, 0.0), velocity=(-1.0, 0.0))
        
        merged = handler.merge_bodies(b1, b2)
        
        # physical_radius: 体积守恒 (2^3 + 1^3)^(1/3)
        expected_phys = (8.0 + 1.0) ** (1.0 / 3.0)
        self.assertAlmostEqual(merged.physical_radius, expected_phys, places=6)
        
        # render_radius: 体积守恒 (8^3 + 5^3)^(1/3)
        expected_render = (512.0 + 125.0) ** (1.0 / 3.0)
        self.assertAlmostEqual(merged.render_radius, expected_render, places=6)
        
        # 两者不应相等
        self.assertNotAlmostEqual(
            merged.physical_radius, merged.render_radius, places=2
        )

    def test_collision_uses_physical_radius_only(self):
        """碰撞检测只使用 physical_radius，忽略 render_radius"""
        handler = CollisionHandler()
        
        # 两个天体 physical_radius 很小但 render_radius 很大
        b1 = Body(name="A", mass=1.0,
                  physical_radius=0.5, render_radius=100.0,
                  position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0,
                  physical_radius=0.5, render_radius=100.0,
                  position=(5.0, 0.0))  # 距离 5 > 0.5+0.5=1.0
        
        collisions = handler.detect_collisions([b1, b2])
        # 不应检测到碰撞（physical_radius 之和 = 1.0 < 5.0）
        self.assertEqual(len(collisions), 0)

    def test_collision_detected_by_physical_radius(self):
        """碰撞检测由 physical_radius 决定"""
        handler = CollisionHandler()
        
        b1 = Body(name="A", mass=1.0,
                  physical_radius=3.0, render_radius=0.1,
                  position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0,
                  physical_radius=3.0, render_radius=0.1,
                  position=(5.0, 0.0))  # 距离 5 < 3+3=6
        
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 1)

    def test_large_render_small_physical_no_false_collision(self):
        """大 render_radius 不应导致错误碰撞"""
        handler = CollisionHandler()
        
        b1 = Body(name="A", mass=1.0,
                  physical_radius=0.1, render_radius=50.0,
                  position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0,
                  physical_radius=0.1, render_radius=50.0,
                  position=(10.0, 0.0))
        
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 0,
                        "render_radius should not trigger collision")

    def test_merge_chain_preserves_isolation(self):
        """多次融合后 physical_radius 和 render_radius 仍然独立"""
        handler = CollisionHandler()
        
        b1 = Body(name="A", mass=10.0,
                  physical_radius=1.0, render_radius=5.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=10.0,
                  physical_radius=1.0, render_radius=5.0,
                  position=(1.5, 0.0), velocity=(-1.0, 0.0))
        
        merged_once = handler.merge_bodies(b1, b2)
        
        b3 = Body(name="C", mass=10.0,
                  physical_radius=1.0, render_radius=5.0,
                  position=(3.0, 0.0), velocity=(-1.0, 0.0))
        
        # 手动设置 merged_once 的位置使其与 b3 碰撞
        merged_once.position = np.array([2.5, 0.0])
        
        merged_twice = handler.merge_bodies(merged_once, b3)
        
        # physical_radius: ((1^3+1^3)^(1/3))^3 + 1^3)^(1/3) = (2+1)^(1/3)
        expected_phys = (2.0 + 1.0) ** (1.0 / 3.0)
        self.assertAlmostEqual(merged_twice.physical_radius, expected_phys, places=6)
        
        # render_radius: ((5^3+5^3)^(1/3))^3 + 5^3)^(1/3) = (250+125)^(1/3)
        expected_render = (250.0 + 125.0) ** (1.0 / 3.0)
        self.assertAlmostEqual(merged_twice.render_radius, expected_render, places=6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
