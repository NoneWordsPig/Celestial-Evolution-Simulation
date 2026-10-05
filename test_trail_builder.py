"""
TrailVertexBuilder 单元测试（数据层重构，第一阶段）

验证新 numpy 批量顶点生成与旧 immediate mode 数据路径逐位一致：
    (x, y, r, g, b, a) 误差 < 1e-6

旧路径参考实现逐字复刻 ui/simulation_widget.py::_draw_trail 的数据准备：
    list(body.trail) -> _sample_trail -> np.asarray -> NDC -> alphas -> 逐顶点提交
"""

import unittest
from collections import deque
from types import SimpleNamespace

import numpy as np

from physics import Camera
from ui.trail_renderer import TrailVertexBuilder


# ---------------------------------------------------------------------------
# 旧路径参考实现（严格复刻 _draw_trail，仅用于对比，不参与生产代码）
# ---------------------------------------------------------------------------

def _old_sample_trail(pts: list, max_points: int) -> list:
    """逐字复刻 simulation_widget._sample_trail。"""
    n = len(pts)
    if n <= max_points:
        return pts
    step = n / max_points
    indices = [int(n - 1 - i * step) for i in range(max_points)]
    indices.reverse()
    return [pts[i] for i in indices]


def _old_vertex_buffer(body, camera, sampling_limit: int = 1000):
    """复刻 _draw_trail 的数据准备 + 逐顶点 interleave（模拟 glColor4f/glVertex2f）。"""
    history = list(body.trail)
    pts = _old_sample_trail(history, sampling_limit)
    n = len(pts)
    if n < 2:
        return np.empty((0, 6), dtype=np.float32)
    color = body.color
    w = camera.viewport_width
    h = camera.viewport_height
    m = len(pts)
    arr = np.asarray(pts, dtype=np.float64)
    ndc = np.empty((m, 2), dtype=np.float64)
    ndc[:, 0] = (
        (arr[:, 0] - camera.center_x) * camera.zoom + w * 0.5
    ) / w * 2.0 - 1.0
    ndc[:, 1] = 1.0 - (
        -(arr[:, 1] - camera.center_y) * camera.zoom + h * 0.5
    ) / h * 2.0
    alphas = 0.15 + 0.65 * np.linspace(0.0, 1.0, m)
    out = np.empty((m, 6), dtype=np.float32)
    for i in range(m):
        out[i, 0] = float(ndc[i, 0])
        out[i, 1] = float(ndc[i, 1])
        out[i, 2] = float(color[0])
        out[i, 3] = float(color[1])
        out[i, 4] = float(color[2])
        out[i, 5] = float(alphas[i])
    return out


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def _make_body(name: str, points, color=(0.9, 0.4, 0.2), maxlen=1000):
    """构造最小可用 body（仅 trail + color，与渲染器解耦）。"""
    trail = deque(
        (np.asarray(p, dtype=np.float64) for p in points), maxlen=maxlen
    )
    return SimpleNamespace(
        name=name,
        color=np.asarray(color, dtype=np.float32),
        trail=trail,
    )


def _make_camera(width=1280, height=720, center_x=3.0, center_y=-2.0, zoom=1.5):
    return Camera(
        viewport_width=width,
        viewport_height=height,
        center_x=center_x,
        center_y=center_y,
        zoom=zoom,
    )


class TestTrailVertexBuilder(unittest.TestCase):
    def setUp(self):
        self.builder = TrailVertexBuilder()
        self.camera = _make_camera()

    def _assert_same(self, body, camera=None):
        """单 body：新 build() 与旧路径逐位对比（误差 < 1e-6）。"""
        camera = camera or self.camera
        old = _old_vertex_buffer(body, camera)
        vertices, starts, counts = self.builder.build([body], camera)
        self.assertEqual(vertices.shape, old.shape)
        np.testing.assert_allclose(vertices, old, rtol=0.0, atol=1e-6)
        self.assertEqual(list(starts), [0] if len(old) else [])
        self.assertEqual(list(counts), [len(old)] if len(old) else [])

    def test_short_trails_skipped(self):
        """0 / 1 个点的轨迹不参与绘制。"""
        for n in (0, 1):
            body = _make_body(f'short{n}', [np.zeros(2, dtype=np.float64)] * n)
            vertices, starts, counts = self.builder.build([body], self.camera)
            self.assertEqual(vertices.shape, (0, 6))
            self.assertEqual(starts.size, 0)
            self.assertEqual(counts.size, 0)

    def test_two_points(self):
        body = _make_body(
            'b', [np.array([0.0, 0.0]), np.array([1.0, 1.0])]
        )
        self._assert_same(body)

    def test_no_sampling(self):
        rng = np.random.default_rng(42)
        body = _make_body('b', rng.uniform(-100.0, 100.0, (500, 2)))
        self._assert_same(body)

    def test_exact_limit(self):
        rng = np.random.default_rng(7)
        body = _make_body('b', rng.uniform(-100.0, 100.0, (1000, 2)))
        self._assert_same(body)

    def test_sampling_above_limit(self):
        for n in (1001, 1250, 1500, 2500, 4096):
            rng = np.random.default_rng(n)
            body = _make_body('b', rng.uniform(-1e4, 1e4, (n, 2)), maxlen=n)
            self._assert_same(body)

    def test_sampling_indices_match(self):
        """向量化采样索引与旧逐点循环逐位一致。"""
        for n in (1001, 1200, 1500, 3000):
            idx = TrailVertexBuilder._sample_indices(n, 1000)
            step = n / 1000
            old = [int(n - 1 - i * step) for i in range(1000)]
            old.reverse()
            self.assertEqual(idx.tolist(), old)

    def test_custom_sampling_limit(self):
        builder = TrailVertexBuilder(sampling_limit=500)
        rng = np.random.default_rng(21)
        body = _make_body('b', rng.uniform(-1e3, 1e3, (900, 2)))
        old = _old_vertex_buffer(body, self.camera, sampling_limit=500)
        vertices, starts, counts = builder.build([body], self.camera)
        self.assertEqual(vertices.shape, old.shape)
        np.testing.assert_allclose(vertices, old, rtol=0.0, atol=1e-6)

    def test_multiple_bodies_concatenated(self):
        """多 body：interleaved 拼接顺序 / start / count 正确。"""
        rng = np.random.default_rng(11)
        bodies = []
        expected = []
        for i in range(9):
            n = int(rng.integers(2, 2200))
            color = tuple(rng.uniform(0.0, 1.0, 3))
            body = _make_body(
                f'b{i}', rng.uniform(-500.0, 500.0, (n, 2)), color=color
            )
            bodies.append(body)
            old = _old_vertex_buffer(body, self.camera)
            if len(old):
                expected.append(old)

        vertices, starts, counts = self.builder.build(bodies, self.camera)

        ref = np.vstack(expected)
        np.testing.assert_allclose(vertices, ref, rtol=0.0, atol=1e-6)
        expected_counts = [len(e) for e in expected]
        expected_starts = np.cumsum([0] + expected_counts)[:-1]
        self.assertEqual(list(starts), list(expected_starts))
        self.assertEqual(list(counts), expected_counts)

    def test_camera_transform_applied(self):
        cam = _make_camera(
            width=1920, height=1080, center_x=-50.0, center_y=80.0, zoom=0.02
        )
        rng = np.random.default_rng(3)
        body = _make_body('b', rng.uniform(-1e5, 1e5, (777, 2)))
        self._assert_same(body, camera=cam)

    def test_color_columns(self):
        rng = np.random.default_rng(5)
        body = _make_body('b', rng.uniform(-10.0, 10.0, (50, 2)), color=(0.1, 0.5, 0.9))
        vertices, _, _ = self.builder.build([body], self.camera)
        self.assertTrue(np.allclose(
            vertices[:, 2:5],
            np.array([0.1, 0.5, 0.9], dtype=np.float32),
            rtol=0.0, atol=1e-7,
        ))

    def test_dtype_and_layout(self):
        rng = np.random.default_rng(9)
        body = _make_body('b', rng.uniform(-10.0, 10.0, (64, 2)))
        vertices, starts, counts = self.builder.build([body], self.camera)
        self.assertEqual(vertices.dtype, np.float32)
        self.assertEqual(vertices.shape, (64, 6))
        self.assertTrue(vertices.flags['C_CONTIGUOUS'])
        self.assertEqual(list(starts), [0])
        self.assertEqual(list(counts), [64])

    def test_empty_bodies(self):
        vertices, starts, counts = self.builder.build([], self.camera)
        self.assertEqual(vertices.shape, (0, 6))
        self.assertEqual(starts.size, 0)
        self.assertEqual(counts.size, 0)

    def test_randomized_fuzz(self):
        """随机化模糊测试：随机轨迹 / 颜色 / camera，误差 < 1e-6。"""
        rng = np.random.default_rng(12345)
        for trial in range(20):
            n = int(rng.integers(2, 3000))
            color = tuple(rng.uniform(0.0, 1.0, 3))
            pts = rng.uniform(-1e6, 1e6, (n, 2))
            body = _make_body(f'f{trial}', pts, color=color)
            cam = _make_camera(
                width=int(rng.integers(320, 2560)),
                height=int(rng.integers(240, 1440)),
                center_x=float(rng.uniform(-1e4, 1e4)),
                center_y=float(rng.uniform(-1e4, 1e4)),
                zoom=float(10.0 ** rng.uniform(-2.0, 2.0)),
            )
            old = _old_vertex_buffer(body, cam)
            vertices, starts, counts = self.builder.build([body], cam)
            self.assertEqual(vertices.shape, old.shape)
            np.testing.assert_allclose(vertices, old, rtol=0.0, atol=1e-6)
            self.assertEqual(list(starts), [0])
            self.assertEqual(list(counts), [len(old)])


if __name__ == '__main__':
    unittest.main()
