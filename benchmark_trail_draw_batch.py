"""
Trail 第二阶段 benchmark：旧 immediate mode vs 新 VBO（TrailRenderer）

无真实 GL 上下文：mock GL 驱动两条生产路径，测量 CPU 侧耗时与 GL 调用次数。
  - 旧路径 trail_draw          ：复刻 _draw_trail（list 拷贝 + 采样 + NDC/alpha + 逐顶点 glColor4f/glVertex2f）
  - 新路径 prepare/upload/draw ：TrailRenderer.render（builder + glBufferSubData + 每 body 一次 glDrawArrays）

场景（太阳系九体）：
    1x : 9 体 x 1000 轨迹点（= MAX_TRAJECTORY_LENGTH，渲染无采样）
    5x : 9 体 x 5000 轨迹点（数据准备 5 倍，渲染采样到 1000）

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
import ui.trail_renderer as tr
from ui.trail_renderer import TrailRenderer
from test_trail_builder import _old_vertex_buffer


# GL 常量整数值（与 OpenGL.GL 一致，供 mock 使用）
GL_LINE_STRIP = 0x0B03
GL_ARRAY_BUFFER = 0x8892
GL_DYNAMIC_DRAW = 0x88E8
GL_VERTEX_ARRAY = 0x8074
GL_COLOR_ARRAY = 0x8076
GL_FLOAT = 0x1406


class _CountGl:
    """mock GL：统计各函数调用次数（无真实 GL 上下文）。"""

    GL_LINE_STRIP = GL_LINE_STRIP
    GL_ARRAY_BUFFER = GL_ARRAY_BUFFER
    GL_DYNAMIC_DRAW = GL_DYNAMIC_DRAW
    GL_VERTEX_ARRAY = GL_VERTEX_ARRAY
    GL_COLOR_ARRAY = GL_COLOR_ARRAY
    GL_FLOAT = GL_FLOAT

    def __init__(self):
        self.counts = {}
        self._vbo_id = 1

    def __getattr__(self, name):
        def _fn(*args):
            self.counts[name] = self.counts.get(name, 0) + 1
            if name == 'glGenBuffers':
                return [self._vbo_id]

        return _fn

    def total(self):
        return sum(self.counts.values())


class _PhaseRecorder:
    """与 RenderPhaseTimer 同接口的轻量计时器（benchmark 用，避免依赖 UI）。"""

    def __init__(self):
        self.phases = {}

    def add(self, name, seconds):
        if seconds > 0.0:
            self.phases[name] = self.phases.get(name, 0.0) + seconds


def _make_body(name, n, rng, color):
    pts = rng.uniform(-1e4, 1e4, (n, 2))
    trail = deque(
        (np.asarray(p, dtype=np.float64) for p in pts), maxlen=5000
    )
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


def _old_sample_trail(pts: list, max_points: int) -> list:
    n = len(pts)
    if n <= max_points:
        return pts
    step = n / max_points
    indices = [int(n - 1 - i * step) for i in range(max_points)]
    indices.reverse()
    return [pts[i] for i in indices]


def _old_trail_draw(bodies, camera, gl, sampling_limit: int = 1000):
    """复刻 simulation_widget._draw_trail 的数据准备 + 逐顶点 GL 提交（mock）。"""
    for body in bodies:
        history = list(body.trail)
        pts = _old_sample_trail(history, sampling_limit)
        n = len(pts)
        if n < 2:
            continue
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
        gl.glLineWidth(1.5)
        gl.glBegin(gl.GL_LINE_STRIP)
        for i in range(m):
            gl.glColor4f(
                float(color[0]), float(color[1]), float(color[2]), alphas[i]
            )
            gl.glVertex2f(ndc[i, 0], ndc[i, 1])
        gl.glEnd()


def _bench_old(bodies, camera, gl, repeat: int = 300):
    _old_trail_draw(bodies, camera, gl)  # warmup
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        _old_trail_draw(bodies, camera, gl)
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times), statistics.mean(times)


def _bench_new(bodies, camera, gl, repeat: int = 300):
    renderer = TrailRenderer(1000)
    with mock.patch.object(tr, 'gl', gl):
        renderer.initialize()
        phase = _PhaseRecorder()
        renderer.render(bodies, camera, phase=phase)  # warmup
        phase = _PhaseRecorder()
        gl.counts = {}
        times = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            renderer.render(bodies, camera, phase=phase)
            times.append((time.perf_counter() - t0) * 1000.0)
        total_ms = statistics.median(times)
        avg = {
            k: phase.phases.get(k, 0.0) / repeat * 1000.0
            for k in ('trail_prepare', 'trail_upload', 'trail_draw')
        }
    return total_ms, avg


def main():
    camera = Camera(
        viewport_width=1280, viewport_height=720,
        center_x=0.0, center_y=0.0, zoom=1.0,
    )
    scenarios = (
        ('九体 1x (1000 点/体)', 1000),
        ('九体 5x (5000 点/体)', 5000),
    )
    for label, n_points in scenarios:
        bodies = _make_scene(n_points)

        # 正确性校验：新 builder 顶点与旧参考实现逐位一致（< 1e-6）
        renderer = TrailRenderer(1000)
        new_v, starts, counts = renderer.builder.build(bodies, camera)
        old_v = np.vstack([_old_vertex_buffer(b, camera) for b in bodies])
        max_diff = float(np.max(np.abs(new_v - old_v))) if new_v.size else 0.0
        assert new_v.shape == old_v.shape, (new_v.shape, old_v.shape)
        assert max_diff < 1e-6, max_diff

        gl = _CountGl()
        old_ms, _ = _bench_old(bodies, camera, gl)
        old_calls = gl.total()

        gl = _CountGl()
        new_ms, avg = _bench_new(bodies, camera, gl)
        new_calls = gl.total()

        print(f'[{label}]  vertices={new_v.shape[0]}  bodies={len(starts)}')
        print(f'  old  trail_draw           : {old_ms:8.3f} ms/frame  gl_calls={old_calls:>9d}')
        print(f'  new  prepare/upload/draw  : {new_ms:8.3f} ms/frame  gl_calls={new_calls:>9d}')
        print(f'       trail_prepare={avg["trail_prepare"]:7.3f}  trail_upload={avg["trail_upload"]:7.3f}'
              f'  trail_draw={avg["trail_draw"]:7.3f}')
        print(f'  speedup: {old_ms / new_ms:6.2f}x   max|diff| = {max_diff:.2e}')


if __name__ == '__main__':
    main()
