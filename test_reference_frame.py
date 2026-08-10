"""
参考系和过渡动画测试套件

测试范围：
1. 质心计算
2. 动量计算
3. 动量修正
4. 缓动函数
5. 过渡动画
"""

import unittest
import numpy as np
from physics import (
    Body, PhysicsEngine, Camera,
    ReferenceFrame, TransitionManager,
    CameraTransition, MomentumCorrectionTransition,
    ease_in_out_cubic, lerp
)


class TestReferenceFrame(unittest.TestCase):
    """测试质心参考系"""
    
    def test_center_of_mass_single_body(self):
        """单个天体的质心"""
        ref = ReferenceFrame()
        body = Body(name="A", mass=10.0, physical_radius=1.0, position=(5.0, 3.0))
        
        com = ref.compute_center_of_mass([body])
        
        np.testing.assert_array_almost_equal(com, [5.0, 3.0])
    
    def test_center_of_mass_equal_masses(self):
        """等质量天体的质心"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0, position=(10.0, 0.0))
        
        com = ref.compute_center_of_mass([b1, b2])
        
        np.testing.assert_array_almost_equal(com, [5.0, 0.0])
    
    def test_center_of_mass_unequal_masses(self):
        """不等质量天体的质心"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=30.0, physical_radius=1.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0, position=(10.0, 0.0))
        
        com = ref.compute_center_of_mass([b1, b2])
        
        # 质心 = (30*0 + 10*10) / 40 = 2.5
        np.testing.assert_array_almost_equal(com, [2.5, 0.0])
    
    def test_center_of_mass_2d(self):
        """2D 质心计算"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0, position=(10.0, 0.0))
        b3 = Body(name="C", mass=10.0, physical_radius=1.0, position=(0.0, 10.0))
        
        com = ref.compute_center_of_mass([b1, b2, b3])
        
        np.testing.assert_array_almost_equal(com, [10.0/3, 10.0/3])
    
    def test_center_of_mass_velocity(self):
        """质心速度计算"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(2.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(-2.0, 0.0))
        
        com_vel = ref.compute_center_of_mass_velocity([b1, b2])
        
        # 总动量为零，质心速度应为零
        np.testing.assert_array_almost_equal(com_vel, [0.0, 0.0])
    
    def test_total_momentum(self):
        """总动量计算"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=5.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(2.0, 0.0))
        
        momentum = ref.compute_total_momentum([b1, b2])
        
        # P = 10*1 + 5*2 = 20
        np.testing.assert_array_almost_equal(momentum, [20.0, 0.0])
    
    def test_momentum_correction(self):
        """动量修正"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(3.0, 0.0))
        
        # 修正前
        momentum_before = ref.compute_total_momentum([b1, b2])
        self.assertGreater(np.linalg.norm(momentum_before), 0)
        
        # 应用修正
        ref.apply_momentum_correction([b1, b2])
        
        # 修正后
        momentum_after = ref.compute_total_momentum([b1, b2])
        np.testing.assert_array_almost_equal(momentum_after, [0.0, 0.0], decimal=10)
    
    def test_relative_position(self):
        """相对位置计算"""
        ref = ReferenceFrame()
        b1 = Body(name="A", mass=10.0, physical_radius=1.0, position=(0.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0, position=(10.0, 0.0))
        
        ref.compute_center_of_mass([b1, b2])
        
        rel_pos = ref.get_relative_position(b1)
        np.testing.assert_array_almost_equal(rel_pos, [-5.0, 0.0])


class TestEasingFunctions(unittest.TestCase):
    """测试缓动函数"""
    
    def test_ease_in_out_cubic_boundaries(self):
        """缓动函数边界值"""
        self.assertAlmostEqual(ease_in_out_cubic(0.0), 0.0)
        self.assertAlmostEqual(ease_in_out_cubic(1.0), 1.0)
    
    def test_ease_in_out_cubic_midpoint(self):
        """缓动函数中点"""
        self.assertAlmostEqual(ease_in_out_cubic(0.5), 0.5)
    
    def test_ease_in_out_cubic_monotonic(self):
        """缓动函数单调性"""
        prev = 0.0
        for t in np.linspace(0, 1, 100):
            current = ease_in_out_cubic(t)
            self.assertGreaterEqual(current, prev)
            prev = current
    
    def test_lerp_boundaries(self):
        """线性插值边界"""
        a = np.array([0.0, 0.0])
        b = np.array([10.0, 10.0])
        
        np.testing.assert_array_almost_equal(lerp(a, b, 0.0), a)
        np.testing.assert_array_almost_equal(lerp(a, b, 1.0), b)
    
    def test_lerp_midpoint(self):
        """线性插值中点"""
        a = np.array([0.0, 0.0])
        b = np.array([10.0, 10.0])
        
        mid = lerp(a, b, 0.5)
        np.testing.assert_array_almost_equal(mid, [5.0, 5.0])


class TestCameraTransition(unittest.TestCase):
    """测试摄像机过渡"""
    
    def test_camera_transition_basic(self):
        """基本摄像机过渡"""
        camera = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        camera.center_x = 0.0
        camera.center_y = 0.0
        
        target = np.array([10.0, 10.0])
        transition = CameraTransition(camera, target, duration=1.0, threshold=0.0)
        transition.start()
        
        # 更新一半时间
        for _ in range(50):
            transition.update(0.01)
        
        # 应该在中间位置附近
        self.assertGreater(camera.center_x, 0.0)
        self.assertLess(camera.center_x, 10.0)
        
        # 完成过渡
        for _ in range(50):
            transition.update(0.01)
        
        # 应该到达目标
        np.testing.assert_array_almost_equal(
            [camera.center_x, camera.center_y], target, decimal=1
        )
    
    def test_camera_transition_threshold(self):
        """摄像机过渡阈值"""
        camera = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        camera.center_x = 0.0
        camera.center_y = 0.0
        
        target = np.array([0.05, 0.05])  # 小于阈值
        transition = CameraTransition(camera, target, duration=1.0, threshold=0.1)
        transition.start()
        
        # 应该直接跳转，不活跃
        self.assertFalse(transition.is_active)
        np.testing.assert_array_almost_equal(
            [camera.center_x, camera.center_y], target
        )


class TestMomentumCorrectionTransition(unittest.TestCase):
    """测试动量修正过渡"""
    
    def test_momentum_correction_basic(self):
        """基本动量修正"""
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(2.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(4.0, 0.0))
        
        ref = ReferenceFrame()
        v_offset = ref.compute_center_of_mass_velocity([b1, b2])
        
        transition = MomentumCorrectionTransition([b1, b2], v_offset, duration=1.0)
        transition.start()
        
        # 完成过渡
        for _ in range(100):
            transition.update(0.01)
        
        # 检查动量接近零
        final_momentum = sum(b.mass * b.velocity for b in [b1, b2])
        np.testing.assert_array_almost_equal(final_momentum, [0.0, 0.0], decimal=5)
    
    def test_momentum_correction_preserves_relative_velocity(self):
        """动量修正保持相对速度"""
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(3.0, 0.0))
        
        # 修正前相对速度
        rel_vel_before = b2.velocity - b1.velocity
        
        ref = ReferenceFrame()
        v_offset = ref.compute_center_of_mass_velocity([b1, b2])
        
        transition = MomentumCorrectionTransition([b1, b2], v_offset, duration=1.0)
        transition.start()
        
        # 完成过渡
        for _ in range(100):
            transition.update(0.01)
        
        # 修正后相对速度
        rel_vel_after = b2.velocity - b1.velocity
        
        # 相对速度应该保持不变
        np.testing.assert_array_almost_equal(rel_vel_after, rel_vel_before)


class TestTransitionManager(unittest.TestCase):
    """测试过渡管理器"""
    
    def test_manager_camera_transition(self):
        """管理器摄像机过渡"""
        camera = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        camera.center_x = 0.0
        camera.center_y = 0.0
        
        manager = TransitionManager()
        target = np.array([10.0, 10.0])
        
        manager.start_camera_transition(camera, target, duration=0.5, threshold=0.0)
        
        self.assertTrue(manager.is_camera_transition_active)
        
        # 更新
        for _ in range(50):
            manager.update(0.01)
        
        # 应该完成
        self.assertFalse(manager.is_camera_transition_active)
    
    def test_manager_momentum_transition(self):
        """管理器动量修正过渡"""
        b1 = Body(name="A", mass=10.0, physical_radius=1.0,
                  position=(0.0, 0.0), velocity=(1.0, 0.0))
        b2 = Body(name="B", mass=10.0, physical_radius=1.0,
                  position=(10.0, 0.0), velocity=(3.0, 0.0))
        
        ref = ReferenceFrame()
        v_offset = ref.compute_center_of_mass_velocity([b1, b2])
        
        manager = TransitionManager()
        manager.start_momentum_correction([b1, b2], v_offset, duration=0.5)
        
        self.assertTrue(manager.is_momentum_transition_active)
        
        # 更新
        for _ in range(50):
            manager.update(0.01)
        
        # 应该完成
        self.assertFalse(manager.is_momentum_transition_active)


if __name__ == '__main__':
    unittest.main(verbosity=2)
