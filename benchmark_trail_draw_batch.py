"""
Trail 渲染第二阶段 benchmark：batch（builder + client arrays + glDrawArrays）vs legacy（逐顶点 immediate mode）

无真实 GL 上下文：用 mock GL 分别驱动两条生产路径（SimulationWidget._draw_trails），
测量 CPU 侧数据准备 + 提交调用的耗时与 GL 调用次数差异。
真实驱动下逐顶点提交的开销只会更高，因此这里是保守下界。

场景（9 体）：
    A. 满轨迹 9x1000（无采样）
    B. 超限轨迹 9x1500（采样到 1000）

用法：
    python benchmark_trail_draw_batch.py
"""

import statistics
import time
from collections import deque
from types import SimpleNamespace
from unittest import mock

import numpy as np

from physics import Camera
import ui.simulation_widget as sw
from ui.simulation_widget import SimulationWidget
from test_trail_builder import _old_vertex_buffer


class _CountGl:
    """mock GL：统计各函数调用次数（无真实 GL 上下文）。"""

    GL_LINE_STRIP = 0x0B03
    GL_VERTEX_ARRAY = 0x8074
    GL_COLOR_ARRAY = 0x8076
    GL_FLOAT = 0x1406

    def __init__(self):
        self.counts = {}

    def __getattr__(self, name):
        def _fn(*args):
            self.counts[name] = self.counts.get(name, 0) + 1

        return _fn

    def total(self):
        return sum(self.counts.values())


def _make_body(name, n, rng, color):
    pts = rng.uniform(-1e4, 1e4, (n, 2))
    trail = deque((np.asarray(p, dtype=np.float64) for p in pts), maxlen=1000)
    return SimpleNamespace(
        name=name,
        color=np.asarray(color, dtype=np.float32),
        trail=trail,
    )


def _make_scene(n_points):
    rng = np.random.default_rng(0)
    colors = [
        (1.0, 0.8, 0.2), (0.9, 0.9, 0.9), (0.6, 0.8, 1.0),
        (1.0, 0.5, 0.3), (0.9, 0.8, 0.6), (0.8, 0.7, 0.5),
        (0.6, 1.0, 0.8), (0.5, 0.7, 1.0), (0.7, 0.5, 0.4),
    ]
    return [
        _make_body(f'body{i}', n_points, rng, colors[i % len(colors)])
        for i in range(9)
    ]


def _make_widget(bodies, camera):
    w = SimulationWidget.__new__(SimulationWidget)
    w.engine = SimpleNamespace(bodies=bodies)
    w.camera = camera
    w.trail_render_sampling = 1000
    w._trail_builder = sw.TrailVertexBuilder(1000)
    w._render_phase_timer = None
    w._cpu_profiler = None
    return w


def _bench(widget, mode, repeat=300):
    gl = _CountGl()
    with mock.patch.object(sw, 'gl', gl):
        widget._trail_render_mode = mode
        widget._draw_trails()  # warmup
        times = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            widget._draw_trails()
            times.append((time.perf_counter() - t0) * 1000.0)
        calls = dict(gl.counts)
    return statistics.median(times), statistics.mean(times), calls


def main():
    camera = Camera(
        viewport_width=1280, viewport_height=720,
        center_x=0.0, center_y=0.0, zoom=1.0,
    )
    scenarios = (
        ('满轨迹 9x1000 (无采样)', 1000),
        ('超限 9x1500 (采样到1000)', 1500),
    )
    for label, n_points in scenarios:
        bodies = _make_scene(n_points)
        widget = _make_widget(bodies, camera)

        # 正确性校验：batch 顶点与 legacy 参考数据层逐位一致（< 1e-6）
        old = np.vstack([_old_vertex_buffer(b, camera) for b in bodies])
        new, starts, counts = widget._trail_builder.build(bodies, camera)
        max_diff = float(np.max(np.abs(new - old))) if new.size else 0.0
        assert new.shape == old.shape, (new.shape, old.shape)
        assert max_diff < 1e-6, max_diff

        legacy_ms, legacy_avg, legacy_calls = _bench(widget, 'legacy')
        batch_ms, batch_avg, batch_calls = _bench(widget, 'batch')

        legacy_gl = sum(legacy_calls.values())
        batch_gl = sum(batch_calls.values())

        print(f'[{label}]')
        print(f'  legacy : {legacy_ms:8.3f} ms/frame (avg {legacy_avg:.3f})  gl_calls={legacy_gl}')
        print(f'  batch  : {batch_ms:8.3f} ms/frame (avg {batch_avg:.3f})  gl_calls={batch_gl}')
        print(f'  speedup: {legacy_ms / batch_ms:6.2f}x   gl_calls 减少 {legacy_gl / max(batch_gl, 1):6.1f}x')
        print(f'  vertices={new.shape[0]}  glDrawArrays={batch_calls.get("glDrawArrays", 0)}'
              f'  legacy glVertex2f={legacy_calls.get("glVertex2f", 0)}')


if __name__ == '__main__':
    main()
