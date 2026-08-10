"""
碰撞融合完整测试套件

测试范围：
1. 碰撞判定（使用 physical_radius）
2. 非碰撞情况
3. 质量守恒
4. 动量守恒
5. 体积守恒（半径计算）
6. physical/render radius 独立性
7. 多体碰撞不重复融合
8. 碰撞算法安全性
"""

import unittest
import numpy as np
from physics import Body, CollisionHandler


class TestCollisionDetection(unittest.TestCase):
    """测试碰撞判定"""
    
    def test_collision_when_touching(self):
        """天体刚好接触时不发生碰撞（严格小于）"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=5.0, position=(10.0, 0.0))
        
        # 距离 = 10，半径和 = 10，刚好接触，不触发碰撞（严格 <）
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 0)
    
    def test_collision_when_overlapping(self):
        """天体重叠时发生碰撞"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=5.0, position=(8.0, 0.0))
        
        # 距离 = 8 < 半径和 = 10，应该碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 1)
    
    def test_no_collision_when_separated(self):
        """天体分离时不发生碰撞"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=5.0, position=(12.0, 0.0))
        
        # 距离 = 12 > 半径和 = 10，不应该碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 0)
    
    def test_collision_uses_physical_radius_only(self):
        """碰撞检测只使用 physical_radius，忽略 render_radius"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=1.0, render_radius=100.0,
                  position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=1.0, render_radius=100.0,
                  position=(5.0, 0.0))
        
        # 距离 = 5，physical_radius 和 = 2，不应该碰撞
        # render_radius 很大但不影响碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 0)
    
    def test_collision_with_different_radii(self):
        """不同半径的天体碰撞"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=10.0, physical_radius=10.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=2.0, position=(11.0, 0.0))
        
        # 距离 = 11 < 半径和 = 12，应该碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 1)


class TestCollisionConservation(unittest.TestCase):
    """测试碰撞守恒定律"""
    
    def test_mass_conservation(self):
        """质量守恒"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=100.0, physical_radius=5.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=50.0, physical_radius=3.0,
                  position=(7.0, 0.0), velocity=(-2.0, 0.0))
        
        merged = handler.merge_bodies(b1, b2)
        
        # 质量守恒
        expected_mass = 100.0 + 50.0
        self.assertAlmostEqual(merged.mass, expected_mass, places=10)
    
    def test_momentum_conservation(self):
        """动量守恒"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=100.0, physical_radius=5.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=50.0, physical_radius=3.0,
                  position=(7.0, 0.0), velocity=(-2.0, 0.0))
        
        # 初始总动量
        initial_momentum = b1.momentum() + b2.momentum()
        
        merged = handler.merge_bodies(b1, b2)
        
        # 融合后动量
        final_momentum = merged.momentum()
        
        # 动量守恒
        np.testing.assert_array_almost_equal(final_momentum, initial_momentum)
    
    def test_momentum_conservation_2d(self):
        """2D 动量守恒"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=10.0, physical_radius=2.0,
                  position=(0.0, 0.0), velocity=(3.0, 4.0))
        b2 = Body(name="B", mass=5.0, physical_radius=1.5,
                  position=(3.0, 0.0), velocity=(-1.0, 2.0))
        
        initial_momentum = b1.momentum() + b2.momentum()
        merged = handler.merge_bodies(b1, b2)
        final_momentum = merged.momentum()
        
        np.testing.assert_array_almost_equal(final_momentum, initial_momentum)
    
    def test_position_is_center_of_mass(self):
        """融合后位置是质心"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=100.0, physical_radius=5.0,
                  position=(0.0, 0.0), velocity=(0.0, 0.0))
        b2 = Body(name="B", mass=100.0, physical_radius=5.0,
                  position=(10.0, 0.0), velocity=(0.0, 0.0))
        
        merged = handler.merge_bodies(b1, b2)
        
        # 质量相等，质心在中点
        expected_pos = np.array([5.0, 0.0])
        np.testing.assert_array_almost_equal(merged.position, expected_pos)
    
    def test_position_weighted_by_mass(self):
        """融合后位置按质量加权"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=300.0, physical_radius=5.0,
                  position=(0.0, 0.0), velocity=(0.0, 0.0))
        b2 = Body(name="B", mass=100.0, physical_radius=3.0,
                  position=(10.0, 0.0), velocity=(0.0, 0.0))
        
        merged = handler.merge_bodies(b1, b2)
        
        # 质心 = (300*0 + 100*10) / 400 = 2.5
        expected_pos = np.array([2.5, 0.0])
        np.testing.assert_array_almost_equal(merged.position, expected_pos)


class TestVolumeConservation(unittest.TestCase):
    """测试体积守恒（半径计算）"""
    
    def test_volume_conservation_equal_radii(self):
        """相同半径的体积守恒"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=1.0)
        b2 = Body(name="B", mass=1.0, physical_radius=1.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        # V_new = V1 + V2 = (4/3)π(1³) + (4/3)π(1³) = 2 * (4/3)π
        # r_new = (1³ + 1³)^(1/3) = 2^(1/3) ≈ 1.2599
        expected_radius = (1.0**3 + 1.0**3) ** (1.0/3.0)
        self.assertAlmostEqual(merged.physical_radius, expected_radius, places=10)
    
    def test_volume_conservation_different_radii(self):
        """不同半径的体积守恒"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=3.0)
        b2 = Body(name="B", mass=1.0, physical_radius=4.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        # r_new = (3³ + 4³)^(1/3) = (27 + 64)^(1/3) = 91^(1/3)
        expected_radius = (3.0**3 + 4.0**3) ** (1.0/3.0)
        self.assertAlmostEqual(merged.physical_radius, expected_radius, places=10)
    
    def test_radius_not_additive(self):
        """半径不是简单相加"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0)
        b2 = Body(name="B", mass=1.0, physical_radius=5.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        # 体积守恒：r_new = (5³ + 5³)^(1/3) = (250)^(1/3) ≈ 6.3
        # 不是 5 + 5 = 10
        self.assertLess(merged.physical_radius, 10.0)
        self.assertGreater(merged.physical_radius, 5.0)
    
    def test_large_small_body_merge(self):
        """大天体和小天体融合"""
        handler = CollisionHandler()
        b1 = Body(name="Star", mass=1000.0, physical_radius=10.0)
        b2 = Body(name="Planet", mass=1.0, physical_radius=1.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        # r_new = (10³ + 1³)^(1/3) = (1001)^(1/3) ≈ 10.003
        expected_radius = (10.0**3 + 1.0**3) ** (1.0/3.0)
        self.assertAlmostEqual(merged.physical_radius, expected_radius, places=10)
        # 新半径略大于大天体半径
        self.assertGreater(merged.physical_radius, 10.0)


class TestRadiusIndependence(unittest.TestCase):
    """测试 physical_radius 和 render_radius 独立性"""
    
    def test_merge_preserves_independence(self):
        """融合后两个半径仍然独立"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=10.0, physical_radius=2.0, render_radius=8.0)
        b2 = Body(name="B", mass=5.0, physical_radius=1.0, render_radius=5.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        # physical_radius 使用体积守恒
        expected_phys = (2.0**3 + 1.0**3) ** (1.0/3.0)
        self.assertAlmostEqual(merged.physical_radius, expected_phys, places=10)
        
        # render_radius 也使用体积守恒，但基于各自的 render_radius
        expected_render = (8.0**3 + 5.0**3) ** (1.0/3.0)
        self.assertAlmostEqual(merged.render_radius, expected_render, places=10)
        
        # 两者不相等
        self.assertNotAlmostEqual(merged.physical_radius, merged.render_radius, places=2)
    
    def test_render_radius_does_not_affect_collision(self):
        """render_radius 不影响碰撞检测"""
        handler = CollisionHandler()
        
        # 大 render_radius，小 physical_radius
        b1 = Body(name="A", mass=1.0, physical_radius=0.5, render_radius=50.0,
                  position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=0.5, render_radius=50.0,
                  position=(5.0, 0.0))
        
        # 距离 = 5，physical_radius 和 = 1.0，不应该碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 0)
    
    def test_modifying_render_does_not_affect_physical(self):
        """修改 render_radius 不影响 physical_radius"""
        b = Body(name="Test", mass=1.0, physical_radius=3.0, render_radius=3.0)
        
        b.render_radius = 100.0
        
        self.assertAlmostEqual(b.physical_radius, 3.0)
        self.assertAlmostEqual(b.render_radius, 100.0)


class TestMultiBodyCollision(unittest.TestCase):
    """测试多体碰撞"""
    
    def test_no_duplicate_merge(self):
        """同一 collision pass 中不重复融合"""
        handler = CollisionHandler()
        
        # 三个天体，A 和 B 碰撞，B 和 C 碰撞
        b1 = Body(name="A", mass=1.0, physical_radius=2.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=2.0, position=(3.0, 0.0))
        b3 = Body(name="C", mass=1.0, physical_radius=2.0, position=(6.0, 0.0))
        
        # A-B 碰撞（距离 3 < 半径和 4）
        # B-C 碰撞（距离 3 < 半径和 4）
        # 但 B 只能参与一次融合
        
        result = handler.resolve_collisions([b1, b2, b3])
        
        # 应该只发生一次融合，结果是 2 个天体
        self.assertEqual(len(result), 2)
    
    def test_multiple_independent_collisions(self):
        """多个独立碰撞"""
        handler = CollisionHandler()
        
        # 两对独立碰撞
        b1 = Body(name="A", mass=1.0, physical_radius=2.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=2.0, position=(3.0, 0.0))
        b3 = Body(name="C", mass=1.0, physical_radius=2.0, position=(100.0, 0.0))
        b4 = Body(name="D", mass=1.0, physical_radius=2.0, position=(103.0, 0.0))
        
        result = handler.resolve_collisions([b1, b2, b3, b4])
        
        # 两对碰撞，结果是 2 个天体
        self.assertEqual(len(result), 2)
    
    def test_no_collision_preserves_all_bodies(self):
        """无碰撞时保留所有天体"""
        handler = CollisionHandler()
        
        b1 = Body(name="A", mass=1.0, physical_radius=1.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=1.0, position=(10.0, 0.0))
        b3 = Body(name="C", mass=1.0, physical_radius=1.0, position=(20.0, 0.0))
        
        result = handler.resolve_collisions([b1, b2, b3])
        
        self.assertEqual(len(result), 3)
    
    def test_total_mass_after_multi_merge(self):
        """多次融合后总质量守恒"""
        handler = CollisionHandler()
        
        bodies = [
            Body(name="A", mass=10.0, physical_radius=2.0, position=(0.0, 0.0)),
            Body(name="B", mass=20.0, physical_radius=3.0, position=(4.0, 0.0)),
            Body(name="C", mass=30.0, physical_radius=4.0, position=(100.0, 0.0)),
        ]
        
        initial_mass = sum(b.mass for b in bodies)
        
        result = handler.resolve_collisions(bodies)
        final_mass = sum(b.mass for b in result)
        
        self.assertAlmostEqual(final_mass, initial_mass, places=10)
    
    def test_total_momentum_after_multi_merge(self):
        """多次融合后总动量守恒"""
        handler = CollisionHandler()
        
        bodies = [
            Body(name="A", mass=10.0, physical_radius=2.0,
                 position=(0.0, 0.0), velocity=(1.0, 0.0)),
            Body(name="B", mass=20.0, physical_radius=3.0,
                 position=(4.0, 0.0), velocity=(-0.5, 0.0)),
            Body(name="C", mass=30.0, physical_radius=4.0,
                 position=(100.0, 0.0), velocity=(0.0, 2.0)),
        ]
        
        initial_momentum = sum(b.momentum() for b in bodies)
        
        result = handler.resolve_collisions(bodies)
        final_momentum = sum(b.momentum() for b in result)
        
        np.testing.assert_array_almost_equal(final_momentum, initial_momentum)


class TestCollisionEdgeCases(unittest.TestCase):
    """测试碰撞边界情况"""
    
    def test_single_body_no_collision(self):
        """单个天体不会碰撞"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        
        collisions = handler.detect_collisions([b1])
        self.assertEqual(len(collisions), 0)
    
    def test_empty_list_no_collision(self):
        """空列表不会碰撞"""
        handler = CollisionHandler()
        
        collisions = handler.detect_collisions([])
        self.assertEqual(len(collisions), 0)
    
    def test_same_position_collision(self):
        """同位置天体碰撞"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=5.0, position=(0.0, 0.0))
        
        # 距离 = 0 < 半径和 = 10，应该碰撞
        collisions = handler.detect_collisions([b1, b2])
        self.assertEqual(len(collisions), 1)
    
    def test_merge_name_combination(self):
        """融合后名称组合"""
        handler = CollisionHandler()
        b1 = Body(name="Star", mass=1.0, physical_radius=1.0)
        b2 = Body(name="Planet", mass=1.0, physical_radius=1.0)
        
        merged = handler.merge_bodies(b1, b2)
        
        self.assertEqual(merged.name, "Star+Planet")
    
    def test_merge_color_blend(self):
        """融合后颜色混合"""
        handler = CollisionHandler()
        b1 = Body(name="A", mass=1.0, physical_radius=1.0, color=(1.0, 0.0, 0.0))
        b2 = Body(name="B", mass=1.0, physical_radius=1.0, color=(0.0, 0.0, 1.0))
        
        merged = handler.merge_bodies(b1, b2)
        
        # 质量相等，颜色应该是平均
        expected_color = np.array([0.5, 0.0, 0.5])
        np.testing.assert_array_almost_equal(merged.color, expected_color)


if __name__ == '__main__':
    unittest.main(verbosity=2)
