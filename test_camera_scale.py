"""
Camera 和 ScaleBar 单元测试
"""

import unittest
import numpy as np
from physics import Camera, ScaleBar, compute_nice_number, Mode, UnitSystem, UnitConverter


class TestCameraBasics(unittest.TestCase):
    """测试 Camera 基本功能"""
    
    def test_default_initialization(self):
        """默认初始化"""
        cam = Camera()
        self.assertEqual(cam.center_x, 0.0)
        self.assertEqual(cam.center_y, 0.0)
        self.assertEqual(cam.zoom, 1.0)
        self.assertEqual(cam.viewport_width, 800)
        self.assertEqual(cam.viewport_height, 600)
        self.assertEqual(cam.min_zoom, 0.001)
        self.assertEqual(cam.max_zoom, 2000.0)
    
    def test_custom_initialization(self):
        """自定义初始化"""
        cam = Camera(
            viewport_width=1024,
            viewport_height=768,
            center_x=10.0,
            center_y=20.0,
            zoom=2.0
        )
        self.assertEqual(cam.center_x, 10.0)
        self.assertEqual(cam.center_y, 20.0)
        self.assertEqual(cam.zoom, 2.0)
        self.assertEqual(cam.viewport_width, 1024)
        self.assertEqual(cam.viewport_height, 768)
    
    def test_zoom_limits(self):
        """缩放范围限制"""
        cam = Camera(min_zoom=0.1, max_zoom=100.0)
        
        # 尝试缩放到极小值
        cam.zoom_at_point(400, 300, 0.001)
        self.assertGreaterEqual(cam.zoom, 0.1)
        
        # 尝试缩放到极大值
        cam.zoom_at_point(400, 300, 10000.0)
        self.assertLessEqual(cam.zoom, 100.0)


class TestCoordinateTransform(unittest.TestCase):
    """测试坐标变换"""
    
    def test_world_to_screen_center(self):
        """世界中心映射到屏幕中心"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        sx, sy = cam.world_to_screen(0.0, 0.0)
        self.assertAlmostEqual(sx, 400.0)
        self.assertAlmostEqual(sy, 300.0)
    
    def test_world_to_screen_offset(self):
        """世界偏移映射到屏幕偏移"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=10.0)
        
        # 世界坐标 (1, 0) 应该在屏幕中心右侧 10 像素
        sx, sy = cam.world_to_screen(1.0, 0.0)
        self.assertAlmostEqual(sx, 410.0)
        self.assertAlmostEqual(sy, 300.0)
        
        # 世界坐标 (0, 1) 应该在屏幕中心上方 10 像素（Y 轴翻转）
        sx, sy = cam.world_to_screen(0.0, 1.0)
        self.assertAlmostEqual(sx, 400.0)
        self.assertAlmostEqual(sy, 290.0)
    
    def test_screen_to_world_center(self):
        """屏幕中心映射到世界中心"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=5.0, center_y=10.0, zoom=1.0)
        wx, wy = cam.screen_to_world(400.0, 300.0)
        self.assertAlmostEqual(wx, 5.0)
        self.assertAlmostEqual(wy, 10.0)
    
    def test_roundtrip_transform(self):
        """坐标变换往返一致性"""
        cam = Camera(viewport_width=1024, viewport_height=768, center_x=3.0, center_y=-5.0, zoom=15.0)
        
        # 世界 → 屏幕 → 世界
        world_x, world_y = 7.5, -2.3
        sx, sy = cam.world_to_screen(world_x, world_y)
        wx, wy = cam.screen_to_world(sx, sy)
        self.assertAlmostEqual(wx, world_x)
        self.assertAlmostEqual(wy, world_y)
        
        # 屏幕 → 世界 → 屏幕
        screen_x, screen_y = 123.0, 456.0
        wx, wy = cam.screen_to_world(screen_x, screen_y)
        sx, sy = cam.world_to_screen(wx, wy)
        self.assertAlmostEqual(sx, screen_x)
        self.assertAlmostEqual(sy, screen_y)


class TestZoomAtPoint(unittest.TestCase):
    """测试以鼠标为中心的缩放"""
    
    def test_zoom_at_center(self):
        """在屏幕中心缩放"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        # 在屏幕中心 (400, 300) 缩放 2 倍
        cam.zoom_at_point(400, 300, 2.0)
        
        # 缩放后，屏幕中心仍然对应世界中心
        wx, wy = cam.screen_to_world(400, 300)
        self.assertAlmostEqual(wx, 0.0)
        self.assertAlmostEqual(wy, 0.0)
        self.assertAlmostEqual(cam.zoom, 2.0)
    
    def test_zoom_at_offset_point(self):
        """在偏移点缩放"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        # 在屏幕 (500, 300) 处缩放 2 倍
        # 该点对应的世界坐标是 (100, 0)
        wx_before, wy_before = cam.screen_to_world(500, 300)
        
        cam.zoom_at_point(500, 300, 2.0)
        
        # 缩放后，该屏幕点仍然对应相同的世界坐标
        wx_after, wy_after = cam.screen_to_world(500, 300)
        self.assertAlmostEqual(wx_after, wx_before)
        self.assertAlmostEqual(wy_after, wy_before)
    
    def test_zoom_in_moves_camera_toward_point(self):
        """放大时摄像机向鼠标位置移动"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        # 在屏幕右侧 (600, 300) 放大
        cam.zoom_at_point(600, 300, 2.0)
        
        # 摄像机中心应该向右移动
        self.assertGreater(cam.center_x, 0.0)
    
    def test_zoom_out_moves_camera_away_from_point(self):
        """缩小时摄像机远离鼠标位置"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=10.0)
        
        # 在屏幕右侧 (600, 300) 缩小
        cam.zoom_at_point(600, 300, 0.5)
        
        # 摄像机中心应该向左移动
        self.assertLess(cam.center_x, 0.0)


class TestPan(unittest.TestCase):
    """测试平移"""
    
    def test_pan_right(self):
        """向右拖拽"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        # 向右拖拽 100 像素
        cam.pan(100, 0)
        
        # 摄像机中心应该向左移动 100 个世界单位
        self.assertAlmostEqual(cam.center_x, -100.0)
        self.assertAlmostEqual(cam.center_y, 0.0)
    
    def test_pan_up(self):
        """向上拖拽"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        # 向上拖拽 50 像素（屏幕 Y 减小，dy=-50）
        # 摄像机中心应该向下移动（Y 轴翻转）
        cam.pan(0, -50)
        
        # 摄像机中心应该向下移动 50 个世界单位
        self.assertAlmostEqual(cam.center_x, 0.0)
        self.assertAlmostEqual(cam.center_y, -50.0)
    
    def test_pan_with_zoom(self):
        """有缩放时的平移"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=10.0)
        
        # 向右拖拽 100 像素
        cam.pan(100, 0)
        
        # 摄像机中心应该向左移动 10 个世界单位（100 / 10）
        self.assertAlmostEqual(cam.center_x, -10.0)


class TestResetCamera(unittest.TestCase):
    """测试重置摄像机"""
    
    def test_reset_to_default(self):
        """重置到默认状态"""
        cam = Camera(
            viewport_width=800,
            viewport_height=600,
            center_x=0.0,
            center_y=0.0,
            zoom=1.0
        )
        
        # 修改摄像机状态
        cam.center_x = 100.0
        cam.center_y = 200.0
        cam.zoom = 5.0
        
        # 重置
        cam.reset()
        
        # 应该恢复到默认状态
        self.assertAlmostEqual(cam.center_x, 0.0)
        self.assertAlmostEqual(cam.center_y, 0.0)
        self.assertAlmostEqual(cam.zoom, 1.0)
    
    def test_set_custom_default(self):
        """设置自定义默认状态"""
        cam = Camera()
        cam.set_default(center_x=10.0, center_y=20.0, zoom=3.0)
        
        # 修改摄像机状态
        cam.center_x = 0.0
        cam.zoom = 1.0
        
        # 重置
        cam.reset()
        
        # 应该恢复到自定义默认状态
        self.assertAlmostEqual(cam.center_x, 10.0)
        self.assertAlmostEqual(cam.center_y, 20.0)
        self.assertAlmostEqual(cam.zoom, 3.0)


class TestFitAllBodies(unittest.TestCase):
    """测试 Fit All Bodies"""
    
    def test_fit_single_body(self):
        """适配单个天体"""
        cam = Camera(viewport_width=800, viewport_height=600)
        positions = np.array([[0.0, 0.0]])
        
        cam.fit_all_bodies(positions)
        
        # 中心应该在天体位置
        self.assertAlmostEqual(cam.center_x, 0.0)
        self.assertAlmostEqual(cam.center_y, 0.0)
    
    def test_fit_multiple_bodies(self):
        """适配多个天体"""
        cam = Camera(viewport_width=800, viewport_height=600)
        positions = np.array([
            [-10.0, -5.0],
            [10.0, 5.0]
        ])
        
        cam.fit_all_bodies(positions, padding=0.0)
        
        # 中心应该在包围盒中心
        self.assertAlmostEqual(cam.center_x, 0.0)
        self.assertAlmostEqual(cam.center_y, 0.0)
        
        # 缩放应该使包围盒刚好适应视口
        # 世界宽度 20，视口宽度 800，zoom = 800 / 20 = 40
        # 世界高度 10，视口高度 600，zoom = 600 / 10 = 60
        # 取较小值 40
        self.assertAlmostEqual(cam.zoom, 40.0)
    
    def test_fit_empty_positions(self):
        """适配空位置列表"""
        cam = Camera()
        cam.center_x = 5.0
        cam.zoom = 2.0
        
        cam.fit_all_bodies(np.array([]))
        
        # 不应该改变摄像机状态
        self.assertAlmostEqual(cam.center_x, 5.0)
        self.assertAlmostEqual(cam.zoom, 2.0)


class TestNiceNumber(unittest.TestCase):
    """测试 1-2-5 序列"""
    
    def test_small_values(self):
        """小值"""
        self.assertAlmostEqual(compute_nice_number(0.3), 0.2)
        self.assertAlmostEqual(compute_nice_number(0.7), 0.5)
        self.assertAlmostEqual(compute_nice_number(1.2), 1.0)
        self.assertAlmostEqual(compute_nice_number(1.8), 2.0)
        self.assertAlmostEqual(compute_nice_number(3.0), 2.0)
        self.assertAlmostEqual(compute_nice_number(4.0), 5.0)
        self.assertAlmostEqual(compute_nice_number(7.0), 5.0)
        self.assertAlmostEqual(compute_nice_number(8.0), 10.0)
    
    def test_large_values(self):
        """大值"""
        self.assertAlmostEqual(compute_nice_number(15.0), 20.0)
        self.assertAlmostEqual(compute_nice_number(35.0), 50.0)
        self.assertAlmostEqual(compute_nice_number(70.0), 50.0)
        self.assertAlmostEqual(compute_nice_number(150.0), 200.0)
        self.assertAlmostEqual(compute_nice_number(350.0), 500.0)
    
    def test_exact_powers_of_10(self):
        """10 的幂次"""
        self.assertAlmostEqual(compute_nice_number(1.0), 1.0)
        self.assertAlmostEqual(compute_nice_number(10.0), 10.0)
        self.assertAlmostEqual(compute_nice_number(100.0), 100.0)
        self.assertAlmostEqual(compute_nice_number(1000.0), 1000.0)


class TestScaleBar(unittest.TestCase):
    """测试动态比例尺"""
    
    def test_scale_bar_basic(self):
        """基本比例尺计算"""
        cam = Camera(viewport_width=800, viewport_height=600, zoom=10.0)
        scale_bar = ScaleBar(target_pixel_length=150.0)
        
        world_dist, pixel_len, label = scale_bar.compute(cam, Mode.SIMULATION)
        
        # 像素长度应该在合理范围内
        self.assertGreater(pixel_len, 80.0)
        self.assertLess(pixel_len, 250.0)
        
        # 标签应该包含单位
        self.assertIn("DU", label)
    
    def test_scale_bar_changes_with_zoom(self):
        """比例尺随缩放变化"""
        cam = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        scale_bar = ScaleBar(target_pixel_length=150.0)
        
        world_dist_1, _, _ = scale_bar.compute(cam, Mode.SIMULATION)
        
        cam.zoom = 10.0
        world_dist_2, _, _ = scale_bar.compute(cam, Mode.SIMULATION)
        
        # 缩放 10 倍后，比例尺对应的世界距离应该缩小约 10 倍
        self.assertAlmostEqual(world_dist_2, world_dist_1 / 10.0, delta=world_dist_1 * 0.5)
    
    def test_scale_bar_scientific_mode_with_converter(self):
        """科学模式下的比例尺（有现实映射）"""
        cam = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        scale_bar = ScaleBar(target_pixel_length=150.0)
        converter = UnitConverter.solar_system()
        
        world_dist, pixel_len, label = scale_bar.compute(
            cam, Mode.SCIENTIFIC, converter=converter
        )
        
        # 标签应该包含现实单位
        self.assertTrue("m" in label or "AU" in label)
    
    def test_scale_bar_scientific_mode_without_converter(self):
        """科学模式下的比例尺（无现实映射）"""
        cam = Camera(viewport_width=800, viewport_height=600, zoom=1.0)
        scale_bar = ScaleBar(target_pixel_length=150.0)
        
        world_dist, pixel_len, label = scale_bar.compute(cam, Mode.SCIENTIFIC)
        
        # 标签应该包含 DU 和提示
        self.assertIn("DU", label)
        self.assertIn("未设置", label)


class TestVisibleWorldBounds(unittest.TestCase):
    """测试可见世界范围"""
    
    def test_visible_bounds_center(self):
        """中心在原点时的可见范围"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=0.0, center_y=0.0, zoom=1.0)
        
        min_x, min_y, max_x, max_y = cam.get_visible_world_bounds()
        
        # 可见范围应该是 [-400, 400] x [-300, 300]
        self.assertAlmostEqual(min_x, -400.0)
        self.assertAlmostEqual(max_x, 400.0)
        self.assertAlmostEqual(min_y, -300.0)
        self.assertAlmostEqual(max_y, 300.0)
    
    def test_visible_bounds_offset(self):
        """中心偏移时的可见范围"""
        cam = Camera(viewport_width=800, viewport_height=600, center_x=10.0, center_y=20.0, zoom=1.0)
        
        min_x, min_y, max_x, max_y = cam.get_visible_world_bounds()
        
        # 可见范围应该是 [10-400, 10+400] x [20-300, 20+300]
        self.assertAlmostEqual(min_x, -390.0)
        self.assertAlmostEqual(max_x, 410.0)
        self.assertAlmostEqual(min_y, -280.0)
        self.assertAlmostEqual(max_y, 320.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
