"""
SceneManager 独立单元测试

验证 Scene JSON 保存/加载/导入/导出往返：
- Body 状态（name / mass / radius / position / velocity / color）
- Simulation Time
- Camera
- Units

以及程序启动时的 scenes/ 目录扫描。
"""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from physics import PhysicsEngine, Camera, Body
from physics.scene_manager import SceneManager


def _make_engine_camera():
    """创建带状态（天体 + 已推进时间 + 相机）的引擎/相机"""
    engine = PhysicsEngine(integrator_type='rk4', dt=0.001, time_scale=3.0)
    engine.add_body(Body(
        name="Star", mass=1.0, physical_radius=0.00465, render_radius=0.00465,
        position=(0.0, 0.0), velocity=(0.0, 0.0), color=(1.0, 0.85, 0.25),
    ))
    engine.add_body(Body(
        name="Earth", mass=3.003e-6, physical_radius=4.26e-5,
        render_radius=4.26e-5,
        position=(0.9833, 0.0), velocity=(0.0, 1.0168), color=(0.3, 0.6, 1.0),
    ))
    for _ in range(5):
        engine.step()

    camera = Camera(
        viewport_width=1024, viewport_height=768,
        center_x=0.5, center_y=-0.2, zoom=42.0,
    )
    return engine, camera


class TestSceneManagerRoundTrip(unittest.TestCase):
    """创建场景 -> 保存 JSON -> 重新打开 -> Load，状态完全恢复"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.manager = SceneManager()
        self.engine, self.camera = _make_engine_camera()

    def _assert_engine_restored(self, engine2):
        self.assertAlmostEqual(engine2.dt, self.engine.dt)
        self.assertAlmostEqual(engine2.time_scale, self.engine.time_scale)
        self.assertAlmostEqual(
            engine2.simulation_time, self.engine.simulation_time
        )
        self.assertEqual(
            type(engine2.integrator).__name__,
            type(self.engine.integrator).__name__,
        )
        self.assertEqual(len(engine2.bodies), len(self.engine.bodies))

        for b2, b1 in zip(engine2.bodies, self.engine.bodies):
            self.assertEqual(b2.name, b1.name)
            self.assertAlmostEqual(b2.mass, b1.mass)
            self.assertAlmostEqual(b2.physical_radius, b1.physical_radius)
            self.assertAlmostEqual(b2.render_radius, b1.render_radius)
            np.testing.assert_array_almost_equal(b2.position, b1.position)
            np.testing.assert_array_almost_equal(b2.velocity, b1.velocity)
            np.testing.assert_array_almost_equal(
                b2.color.astype(float), b1.color.astype(float)
            )

    def _assert_camera_restored(self, camera2):
        self.assertAlmostEqual(camera2.center_x, self.camera.center_x)
        self.assertAlmostEqual(camera2.center_y, self.camera.center_y)
        self.assertAlmostEqual(camera2.zoom, self.camera.zoom)
        self.assertEqual(camera2.viewport_width, self.camera.viewport_width)
        self.assertEqual(camera2.viewport_height, self.camera.viewport_height)

    def test_save_then_reopen_then_load(self):
        """保存 JSON -> 新引擎/相机 -> Load Scene，全部正确恢复"""
        path = Path(self.tmpdir.name) / "scene.json"
        units = {"length": "AU", "mass": "M_sun", "time": "TU"}

        self.manager.export_scene(
            self.engine, self.camera, path,
            name="Test Scene", description="round trip", units=units,
        )

        # 模拟关闭程序后重新打开：全新的引擎/相机
        engine2 = PhysicsEngine()
        camera2 = Camera()

        scene = self.manager.import_scene(path, engine2, camera2)

        # Units / name / description / G 恢复
        self.assertEqual(scene['name'], "Test Scene")
        self.assertEqual(scene['description'], "round trip")
        self.assertEqual(scene['units'], units)
        self.assertEqual(scene['G'], 1.0)

        # Body / Simulation Time / Integrator / dt / time_scale
        self._assert_engine_restored(engine2)
        # Camera
        self._assert_camera_restored(camera2)

    def test_save_load_file_round_trip(self):
        """save_scene / load_scene 文件往返一致"""
        scene = self.manager.scene_to_dict(
            self.engine, self.camera, name="RT", description="d"
        )
        path = Path(self.tmpdir.name) / "rt.json"
        self.manager.save_scene(scene, path)
        loaded = self.manager.load_scene(path)
        self.assertEqual(loaded, scene)

    def test_verlet_integrator_restored(self):
        """积分器类型（verlet）随场景恢复"""
        engine = PhysicsEngine(integrator_type='verlet', dt=0.01, time_scale=1.0)
        engine.add_body(Body(name="A", mass=1.0, position=(0.0, 0.0)))
        camera = Camera(zoom=5.0)

        path = Path(self.tmpdir.name) / "verlet.json"
        self.manager.export_scene(engine, camera, path, name="V")

        engine2 = PhysicsEngine()
        camera2 = Camera()
        self.manager.import_scene(path, engine2, camera2)
        self.assertEqual(
            type(engine2.integrator).__name__, 'VelocityVerletIntegrator'
        )

    def test_scene_contains_required_fields(self):
        """Scene JSON 至少包含规定字段"""
        scene = self.manager.scene_to_dict(
            self.engine, self.camera, name="Required"
        )
        for key in (
            'name', 'description', 'units', 'G', 'integrator',
            'timestep', 'time_scale', 'simulation_time', 'camera', 'bodies',
        ):
            self.assertIn(key, scene)
        for body in scene['bodies']:
            for key in ('name', 'mass', 'radius', 'position', 'velocity'):
                self.assertIn(key, body)


class TestSceneManagerScan(unittest.TestCase):
    """启动扫描 scenes/ 目录"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.manager = SceneManager()

    def _write(self, name, content):
        path = Path(self.tmpdir.name) / name
        path.write_text(content, encoding='utf-8')
        return path

    def test_scan_finds_all_valid_json(self):
        self._write('a.json', json.dumps({
            "name": "Scene A", "description": "first", "bodies": []
        }))
        self._write('b.json', json.dumps({
            "name": "Scene B", "description": "second", "bodies": []
        }))
        self._write('broken.json', '{ not valid json ')
        self._write('notes.txt', 'not a scene')

        scenes = self.manager.scan_scenes(self.tmpdir.name)

        self.assertEqual(len(scenes), 2)
        self.assertEqual([s['name'] for s in scenes], ["Scene A", "Scene B"])

    def test_scan_missing_directory_returns_empty(self):
        self.assertEqual(
            self.manager.scan_scenes(str(Path(self.tmpdir.name) / "nope")),
            [],
        )

    def test_scan_default_scenes_directory(self):
        """项目 scenes/ 目录可被默认扫描"""
        self.assertTrue(self.manager.scenes_directory.is_dir())
        scenes = self.manager.scan_scenes()
        names = [s['name'] for s in scenes]
        self.assertIn("Figure-8 三体系统", names)


if __name__ == '__main__':
    unittest.main()
