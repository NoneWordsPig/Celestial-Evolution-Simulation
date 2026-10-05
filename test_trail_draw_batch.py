"""
TrailRenderer（VBO 批量渲染）单元测试（第二阶段）

用 mock GL 记录器验证生产路径（无真实 GL 上下文 / 无 Qt 实例化）：
  - VBO 生命周期：initialize 创建（防重复）/ cleanup 删除
  - 每帧流程：builder 顶点 -> glBufferData(首次扩容)/glBufferSubData -> 每 body 一次 glDrawArrays
  - VBO 内指针偏移（0 / 8 字节）、stride、client states、line width、GL_LINE_STRIP
  - profiler 阶段键：trail_prepare / trail_upload / trail_draw
  - widget 层：old_trail_renderer=True 回退逐顶点 immediate mode；False（默认）走 VBO 路径
  - 顶点数据与 legacy 参考实现逐位一致（< 1e-6）
"""

import ctypes
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import ui.trail_renderer as tr
from ui.trail_renderer import TrailRenderer
import ui.simulation_widget as sw
from ui.simulation_widget import SimulationWidget
from test_trail_builder import _old_vertex_buffer, _make_body, _make_camera


# GL 常量整数值（与 OpenGL.GL 一致，供 mock 断言使用）
GL_LINE_STRIP = 0x0B03
GL_ARRAY_BUFFER = 0x8892
GL_DYNAMIC_DRAW = 0x88E8
GL_VERTEX_ARRAY = 0x8074
GL_COLOR_ARRAY = 0x8076
GL_FLOAT = 0x1406


class GlRecorder:
    """记录 GL 调用的 mock；GL_ 常量直接作为类属性提供。"""

    GL_LINE_STRIP = GL_LINE_STRIP
    GL_ARRAY_BUFFER = GL_ARRAY_BUFFER
    GL_DYNAMIC_DRAW = GL_DYNAMIC_DRAW
    GL_VERTEX_ARRAY = GL_VERTEX_ARRAY
    GL_COLOR_ARRAY = GL_COLOR_ARRAY
    GL_FLOAT = GL_FLOAT

    def __init__(self, vbo_id=7):
        self.vbo_id = vbo_id
        self.calls = []

    def __getattr__(self, name):
        if name.startswith('GL_'):
            raise AttributeError(name)

        def _record(*args):
            self.calls.append((name, args))
            if name == 'glGenBuffers':
                return [self.vbo_id]

        return _record

    def named(self, name):
        return [args for call_name, args in self.calls if call_name == name]


def _ptr_value(ptr) -> int:
    value = ctypes.cast(ptr, ctypes.c_void_p).value
    return 0 if value is None else value


def _make_widget(bodies, camera, old_renderer=False, sampling=1000):
    """用 __new__ 构造最小 SimulationWidget（不创建 QWidget / GL 上下文）。"""
    w = SimulationWidget.__new__(SimulationWidget)
    w.engine = SimpleNamespace(bodies=bodies)
    w.camera = camera
    w.old_trail_renderer = old_renderer
    w.trail_render_sampling = sampling
    w._trail_renderer = TrailRenderer(sampling)
    w._render_phase_timer = None
    w._cpu_profiler = None
    w._trail_revision = None  # Exercise the uncached upload path in these tests.
    return w


def _bodies(seed=11):
    """3 个 body：点数 3 / 1000 / 1500（1500 被 maxlen=1000 截断为 1000）。"""
    rng = np.random.default_rng(seed)
    colors = [
        (1.0, 0.8, 0.2), (0.9, 0.9, 0.9), (0.6, 0.8, 1.0),
    ]
    return [
        _make_body(f'b{i}', rng.uniform(-1e4, 1e4, (n, 2)), color=colors[i])
        for i, n in enumerate((3, 1000, 1500))
    ]


class TestTrailRenderer(unittest.TestCase):
    def setUp(self):
        self.camera = _make_camera()
        self.recorder = GlRecorder()

    def _renderer(self):
        r = TrailRenderer(1000)
        with mock.patch.object(tr, 'gl', self.recorder):
            r.initialize()
        return r

    def test_initialize_cleanup(self):
        r = TrailRenderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            r.initialize()
            self.assertEqual(r.vbo, 7)
            r.initialize()  # 防重复：先清理再重建
            self.assertEqual(len(self.recorder.named('glGenBuffers')), 2)
            r.cleanup()
            self.assertIsNone(r.vbo)
            self.assertEqual(len(self.recorder.named('glDeleteBuffers')), 2)

    def test_cleanup_without_initialize_is_noop(self):
        r = TrailRenderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            r.cleanup()
        self.assertEqual(self.recorder.calls, [])

    def test_render_without_initialize_raises(self):
        r = TrailRenderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            with self.assertRaises(RuntimeError):
                r.render(_bodies(), self.camera)

    def test_render_upload_draw_flow(self):
        bodies = _bodies()
        r = self._renderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            n, k = r.render(bodies, self.camera)
            n2, k2 = r.render(bodies, self.camera)

        self.assertEqual((n, k), (2003, 3))
        self.assertEqual((n2, k2), (2003, 3))

        # 首帧容量不足：glBufferData 扩容；第二帧走 glBufferSubData
        self.assertEqual(len(self.recorder.named('glBufferData')), 1)
        subdata = self.recorder.named('glBufferSubData')
        self.assertEqual(len(subdata), 1)
        data_args = self.recorder.named('glBufferData')[0]
        self.assertEqual(data_args[0], GL_ARRAY_BUFFER)
        self.assertEqual(data_args[1], 2003 * 24)
        self.assertEqual(data_args[3], GL_DYNAMIC_DRAW)
        sub_args = subdata[0]
        self.assertEqual(sub_args[0], GL_ARRAY_BUFFER)
        self.assertEqual(sub_args[1], 0)
        self.assertEqual(sub_args[2], 2003 * 24)

        # 每 body 一次 glDrawArrays(GL_LINE_STRIP, start, count)
        draws = self.recorder.named('glDrawArrays')
        self.assertEqual(len(draws), 6)  # 两帧 x 3 body
        expected = [(GL_LINE_STRIP, 0, 3), (GL_LINE_STRIP, 3, 1000),
                    (GL_LINE_STRIP, 1003, 1000)] * 2
        self.assertEqual(draws, expected)

        # 指针：VBO 内字节偏移 0 / 8，stride 24
        vp = self.recorder.named('glVertexPointer')[0]
        self.assertEqual(vp[:3], (2, GL_FLOAT, 24))
        self.assertEqual(_ptr_value(vp[3]), 0)
        cp = self.recorder.named('glColorPointer')[0]
        self.assertEqual(cp[:3], (4, GL_FLOAT, 24))
        self.assertEqual(_ptr_value(cp[3]), 8)

        # 线宽 / client states
        self.assertEqual(self.recorder.named('glLineWidth')[0], (1.5,))
        enabled = self.recorder.named('glEnableClientState')
        disabled = self.recorder.named('glDisableClientState')
        # 两帧，每帧 enable/disable 一次 vertex + color
        self.assertEqual(len(enabled), 4)
        self.assertEqual(len(disabled), 4)
        self.assertEqual(
            [a[0] for a in enabled[:2]], [GL_VERTEX_ARRAY, GL_COLOR_ARRAY]
        )
        self.assertEqual(
            [a[0] for a in disabled[:2]], [GL_VERTEX_ARRAY, GL_COLOR_ARRAY]
        )

    def test_vertex_data_matches_legacy(self):
        bodies = _bodies()
        r = self._renderer()
        vertices, starts, counts = r.builder.build(bodies, self.camera)
        ref = np.vstack([
            _old_vertex_buffer(b, self.camera) for b in bodies
            if len(b.trail) >= 2
        ])
        self.assertEqual(vertices.shape, ref.shape)
        np.testing.assert_allclose(vertices, ref, rtol=0.0, atol=1e-6)
        self.assertEqual(list(starts), [0, 3, 1003])
        self.assertEqual(list(counts), [3, 1000, 1000])

    def test_phase_keys(self):
        bodies = _bodies()
        r = self._renderer()
        timer = sw.RenderPhaseTimer()
        with mock.patch.object(tr, 'gl', self.recorder):
            r.render(bodies, self.camera, phase=timer)
        for key in ('trail_prepare', 'trail_upload', 'trail_draw'):
            self.assertIn(key, timer.phases)

    def test_short_trails_skipped(self):
        bodies = [
            _make_body('a', [np.zeros(2, dtype=np.float64)] * 0),
            _make_body('b', [np.zeros(2, dtype=np.float64)]),
        ]
        r = self._renderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            n, k = r.render(bodies, self.camera)
        self.assertEqual((n, k), (0, 0))
        self.assertEqual(self.recorder.named('glBufferData'), [])
        self.assertEqual(self.recorder.named('glBufferSubData'), [])
        self.assertEqual(self.recorder.named('glDrawArrays'), [])

    def test_widget_vbo_path(self):
        bodies = _bodies()
        w = _make_widget(bodies, self.camera)
        with mock.patch.object(sw, 'gl', self.recorder), mock.patch.object(tr, 'gl', self.recorder):
            w._trail_renderer.initialize()
            w._draw_trails()
            w._draw_trails()  # 第二帧走 glBufferSubData
        self.assertEqual(len(self.recorder.named('glDrawArrays')), 6)
        self.assertEqual(len(self.recorder.named('glBufferData')), 1)
        self.assertEqual(len(self.recorder.named('glBufferSubData')), 1)
        self.assertEqual(self.recorder.named('glBegin'), [])
        self.assertEqual(self.recorder.named('glVertex2f'), [])

    def test_widget_old_path(self):
        bodies = _bodies()
        w = _make_widget(bodies, self.camera, old_renderer=True)
        with mock.patch.object(sw, 'gl', self.recorder):
            w._draw_trails()
        total = sum(len(b.trail) for b in bodies if len(b.trail) >= 2)
        self.assertEqual(len(self.recorder.named('glBegin')), 3)
        self.assertEqual(len(self.recorder.named('glEnd')), 3)
        self.assertEqual(len(self.recorder.named('glColor4f')), total)
        self.assertEqual(len(self.recorder.named('glVertex2f')), total)
        self.assertEqual(self.recorder.named('glDrawArrays'), [])

    def test_sampling_limit_sync(self):
        rng = np.random.default_rng(5)
        body = _make_body('b', rng.uniform(-1.0, 1.0, (1200, 2)))
        w = _make_widget([body], self.camera, sampling=1000)
        w.trail_render_sampling = 500
        with mock.patch.object(sw, 'gl', self.recorder), mock.patch.object(tr, 'gl', self.recorder):
            w._trail_renderer.initialize()
            w._draw_trails()
        self.assertEqual(w._trail_renderer.sampling_limit, 500)
        draws = self.recorder.named('glDrawArrays')
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0][2], 500)

    def test_set_old_trail_renderer(self):
        w = _make_widget([], self.camera)
        w.set_old_trail_renderer(True)
        self.assertTrue(w.old_trail_renderer)
        w.set_old_trail_renderer(False)
        self.assertFalse(w.old_trail_renderer)

    def test_revision_reuses_upload_and_invalidates_for_camera_and_color(self):
        bodies = _bodies()
        r = self._renderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            with mock.patch.object(r.builder, 'build', wraps=r.builder.build) as build:
                r.render(bodies, self.camera, revision=0)
                r.render(bodies, self.camera, revision=0)
                self.assertEqual(build.call_count, 1)
                self.camera.center_x += 1
                r.render(bodies, self.camera, revision=0)
                bodies[0].color[0] = 0.2
                r.render(bodies, self.camera, revision=0)
                r.render(bodies, self.camera, revision=1)
                self.assertEqual(build.call_count, 4)
        self.assertEqual(len(self.recorder.named('glBufferData')), 1)
        self.assertEqual(len(self.recorder.named('glBufferSubData')), 3)
        self.assertEqual(len(self.recorder.named('glDrawArrays')), 15)

    def test_full_deque_append_invalidates_even_without_revision_change(self):
        bodies = _bodies()
        r = self._renderer()
        with mock.patch.object(tr, 'gl', self.recorder):
            r.render(bodies, self.camera, revision=0)
            bodies[1].trail.append(np.array([5.0, 6.0]))
            r.render(bodies, self.camera, revision=0)
        self.assertEqual(len(self.recorder.named('glBufferSubData')), 1)

    def test_reinitialization_discards_uploaded_cache(self):
        r = self._renderer()
        bodies = _bodies()
        with mock.patch.object(tr, 'gl', self.recorder):
            r.render(bodies, self.camera, revision=0)
            r.initialize()
            r.render(bodies, self.camera, revision=0)
        self.assertEqual(len(self.recorder.named('glBufferData')), 2)


if __name__ == '__main__':
    unittest.main()
