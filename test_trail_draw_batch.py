"""
Trail 渲染接入单元测试（第二阶段：batch client arrays 绘制路径）

用 mock GL 记录器验证生产路径（无真实 GL 上下文 / 无 Qt 实例化）：
  - batch 路径（默认）顶点数据与 legacy 参考实现逐位一致（误差 < 1e-6）
  - GL 调用序列：client arrays 指针（stride / 颜色偏移正确）+ 每 body 一次 glDrawArrays
  - legacy 路径仍走逐顶点 immediate mode（glBegin / glColor4f / glVertex2f）
  - 短轨迹跳过、sampling limit 同步、render phase 计时键输出
"""

import ctypes
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock

import numpy as np

from physics import Camera
import ui.simulation_widget as sw
from ui.simulation_widget import SimulationWidget
from test_trail_builder import _old_vertex_buffer, _make_body, _make_camera


# GL 常量整数值（与 OpenGL.GL 一致，供 mock 断言使用）
GL_LINE_STRIP = 0x0B03
GL_VERTEX_ARRAY = 0x8074
GL_COLOR_ARRAY = 0x8076
GL_FLOAT = 0x1406


class GlRecorder:
    """记录 GL 调用的 mock；GL_ 常量直接作为类属性提供。"""

    GL_LINE_STRIP = GL_LINE_STRIP
    GL_VERTEX_ARRAY = GL_VERTEX_ARRAY
    GL_COLOR_ARRAY = GL_COLOR_ARRAY
    GL_FLOAT = GL_FLOAT

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith('GL_'):
            raise AttributeError(name)

        def _record(*args):
            self.calls.append((name, args))

        return _record

    def named(self, name):
        return [args for call_name, args in self.calls if call_name == name]


def _make_widget(bodies, camera, render_mode='batch', sampling=1000):
    """用 __new__ 构造最小 SimulationWidget（不创建 QWidget / GL 上下文）。"""
    w = SimulationWidget.__new__(SimulationWidget)
    w.engine = SimpleNamespace(bodies=bodies)
    w.camera = camera
    w._trail_render_mode = render_mode
    w.trail_render_sampling = sampling
    w._trail_builder = sw.TrailVertexBuilder(sampling)
    w._render_phase_timer = None
    w._cpu_profiler = None
    return w


def _ptr_value(ptr) -> int:
    return ctypes.cast(ptr, ctypes.c_void_p).value


class TestBatchDrawPath(unittest.TestCase):
    def setUp(self):
        self.camera = _make_camera()

    def _bodies(self, seed=11):
        rng = np.random.default_rng(seed)
        colors = [
            (1.0, 0.8, 0.2), (0.9, 0.9, 0.9), (0.6, 0.8, 1.0),
        ]
        bodies = []
        for i, n in enumerate((3, 1000, 1500)):
            body = _make_body(
                f'b{i}',
                rng.uniform(-1e4, 1e4, (n, 2)),
                color=colors[i],
            )
            bodies.append(body)
        return bodies

    def test_batch_vertices_match_legacy(self):
        """batch 生成的 interleaved 顶点与 legacy 参考实现逐位一致。"""
        bodies = self._bodies()
        w = _make_widget(bodies, self.camera)
        vertices, starts, counts = w._trail_builder.build(bodies, self.camera)
        ref = np.vstack([
            _old_vertex_buffer(b, self.camera) for b in bodies
            if len(b.trail) >= 2
        ])
        self.assertEqual(vertices.shape, ref.shape)
        np.testing.assert_allclose(vertices, ref, rtol=0.0, atol=1e-6)

    def test_batch_gl_call_sequence(self):
        """batch 路径：client arrays 指针 + 每 body 一次 glDrawArrays。"""
        bodies = self._bodies()
        w = _make_widget(bodies, self.camera)
        vertices, starts, counts = w._trail_builder.build(bodies, self.camera)

        recorder = GlRecorder()
        with mock.patch.object(sw, 'gl', recorder):
            w._draw_trails()

        stride = vertices.strides[0]
        self.assertEqual(stride, 24)
        draws = recorder.named('glDrawArrays')
        self.assertEqual(len(draws), len(starts))
        # 每体一条 GL_LINE_STRIP，start/count 与 builder 输出一致
        expected_draws = list(zip(starts.tolist(), counts.tolist()))
        actual_draws = [(args[1], args[2]) for args in draws]
        self.assertEqual(actual_draws, expected_draws)

        # 指针：stride 正确，颜色指针 = 顶点指针 + 2 * 4 字节
        vp = recorder.named('glVertexPointer')
        self.assertEqual(len(vp), 1)
        self.assertEqual(vp[0][:3], (2, GL_FLOAT, 24))
        vertex_ptr = vp[0][3]

        cp = recorder.named('glColorPointer')
        self.assertEqual(len(cp), 1)
        self.assertEqual(cp[0][:3], (4, GL_FLOAT, 24))
        color_ptr = cp[0][3]
        # interleaved [x, y, r, g, b, a]：颜色指针必须指向同一缓冲偏移 8 字节处
        self.assertEqual(_ptr_value(color_ptr), _ptr_value(vertex_ptr) + 8)

        # 顺序：lineWidth -> enable vertex/color -> pointer -> draws -> disable
        seq = [name for name, _ in recorder.calls]
        self.assertEqual(seq[0], 'glLineWidth')
        self.assertEqual(seq[1], 'glEnableClientState')
        self.assertEqual(seq[2], 'glEnableClientState')
        self.assertIn('glVertexPointer', seq)
        self.assertIn('glColorPointer', seq)
        self.assertEqual(seq[-2:], [
            'glDisableClientState', 'glDisableClientState',
        ])

    def test_legacy_mode_uses_immediate_mode(self):
        """legacy 路径保持逐顶点 glBegin/glColor4f/glVertex2f 提交。"""
        bodies = self._bodies()
        w = _make_widget(bodies, self.camera, render_mode='legacy')
        recorder = GlRecorder()
        with mock.patch.object(sw, 'gl', recorder):
            w._draw_trails()

        total_points = sum(len(b.trail) for b in bodies if len(b.trail) >= 2)
        self.assertEqual(len(recorder.named('glBegin')), 3)
        self.assertEqual(len(recorder.named('glEnd')), 3)
        self.assertEqual(len(recorder.named('glColor4f')), total_points)
        self.assertEqual(len(recorder.named('glVertex2f')), total_points)
        self.assertEqual(recorder.named('glDrawArrays'), [])
        self.assertEqual(recorder.named('glVertexPointer'), [])

    def test_batch_short_trails_skipped(self):
        """0 / 1 点轨迹：batch 不产生任何 GL 调用。"""
        bodies = [
            _make_body('a', [np.zeros(2, dtype=np.float64)] * 0),
            _make_body('b', [np.zeros(2, dtype=np.float64)]),
        ]
        w = _make_widget(bodies, self.camera)
        recorder = GlRecorder()
        with mock.patch.object(sw, 'gl', recorder):
            w._draw_trails()
        self.assertEqual(recorder.calls, [])

    def test_sampling_limit_sync(self):
        """trail_render_sampling 运行时变更后，batch 路径重建 builder。"""
        rng = np.random.default_rng(5)
        body = _make_body('b', rng.uniform(-1.0, 1.0, (1200, 2)))
        w = _make_widget([body], self.camera, sampling=1000)
        w.trail_render_sampling = 500
        recorder = GlRecorder()
        with mock.patch.object(sw, 'gl', recorder):
            w._draw_trails()
        self.assertEqual(w._trail_builder.sampling_limit, 500)
        draws = recorder.named('glDrawArrays')
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0][2], 500)

    def test_phase_timer_keys(self):
        """batch 路径仍输出 trail_prepare / trail_upload_draw 阶段键。"""
        bodies = self._bodies()
        w = _make_widget(bodies, self.camera)
        timer = sw.RenderPhaseTimer()
        w._render_phase_timer = timer
        recorder = GlRecorder()
        with mock.patch.object(sw, 'gl', recorder):
            w._draw_trails()
        self.assertIn('trail_prepare', timer.phases)
        self.assertIn('trail_upload_draw', timer.phases)

    def test_set_trail_render_mode(self):
        w = _make_widget([], self.camera)
        w.set_trail_render_mode('legacy')
        self.assertEqual(w._trail_render_mode, 'legacy')
        w.set_trail_render_mode('batch')
        self.assertEqual(w._trail_render_mode, 'batch')
        w.set_trail_render_mode('whatever')
        self.assertEqual(w._trail_render_mode, 'batch')
        w.set_trail_render_mode(None)
        self.assertEqual(w._trail_render_mode, 'batch')


if __name__ == '__main__':
    unittest.main()
