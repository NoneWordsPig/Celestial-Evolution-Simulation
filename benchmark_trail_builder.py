"""
TrailVertexBuilder 数据层 benchmark（第一阶段：只测数据层，不测 GL 绘制）

对比两条数据路径（均不含 OpenGL 调用）：
    old_data_prep : 复刻 _draw_trail（list 拷贝 + 逐点采样 + asarray + NDC + alpha + 逐顶点 interleave）
    new_build     : TrailVertexBuilder.build()（纯 numpy 批量）

场景（太阳系九体）：
    A. 满轨迹：9 体 x 1000 点（无采样）
    B. 超限轨迹：9 体 x 1500 点（采样到 1000）

用法：
    python benchmark_trail_builder.py
"""

import statistics
import time
from collections import deque
from types import SimpleNamespace

import numpy as np

from physics import Camera
from ui.trail_renderer import TrailVertexBuilder


_BUILDER = TrailVertexBuilder()


def _make_body(name: str, n: int, rng, color):
    pts = rng.uniform(-1e4, 1e4, (n, 2))
    trail = deque(
        (np.asarray(p, dtype=np.float64) for p in pts), maxlen=1000
    )
    return SimpleNamespace(name=name, color=np.asarray(color, dtype=np.float32), trail=trail)


def _make_scene(n_points: int):
    rng = np.random.default_rng(0)
    colors = [
        (1.0, 0.8, 0.2), (0.9, 0.9, 0.9), (0.6, 0.8, 1.0),
        (1.0, 0.5, 0.3), (0.9, 0.8, 0.6), (0.8, 0.7, 0.5),
        (0.6, 1.0, 0.8), (0.5, 0.7, 1.0), (0.7, 0.5, 0.4),
    ]
    return [_make_body(f'body{i}', n_points, rng, colors[i % len(colors)]) for i in range(9)]


def _old_sample_trail(pts: list, max_points: int) -> list:
    n = len(pts)
    if n <= max_points:
        return pts
    step = n / max_points
    indices = [int(n - 1 - i * step) for i in range(max_points)]
    indices.reverse()
    return [pts[i] for i in indices]


def old_data_prep(bodies, camera, sampling_limit: int = 1000):
    """复刻 _draw_trail 的完整数据准备 + 逐顶点 interleave（模拟逐顶点 GL 提交）。"""
    chunks = []
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
        out = np.empty((m, 6), dtype=np.float32)
        for i in range(m):
            out[i, 0] = float(ndc[i, 0])
            out[i, 1] = float(ndc[i, 1])
            out[i, 2] = float(color[0])
            out[i, 3] = float(color[1])
            out[i, 4] = float(color[2])
            out[i, 5] = float(alphas[i])
        chunks.append(out)
    if not chunks:
        return np.empty((0, 6), dtype=np.float32)
    return np.vstack(chunks)


def new_build(bodies, camera):
    return _BUILDER.build(bodies, camera)


def _bench(fn, bodies, camera, repeat: int = 200):
    fn(bodies, camera)  # warmup
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn(bodies, camera)
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times), statistics.mean(times)


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
        old_ms, old_avg = _bench(old_data_prep, bodies, camera)
        new_ms, new_avg = _bench(new_build, bodies, camera)

        # 正确性校验（数据层必须逐位一致）
        old = old_data_prep(bodies, camera)
        new, starts, counts = new_build(bodies, camera)
        assert new.shape == old.shape, (new.shape, old.shape)
        max_diff = float(np.max(np.abs(new - old))) if new.size else 0.0
        assert max_diff < 1e-6, max_diff

        print(f'[{label}]')
        print(f'  old_data_prep : {old_ms:8.3f} ms/frame (avg {old_avg:.3f})')
        print(f'  new_build     : {new_ms:8.3f} ms/frame (avg {new_avg:.3f})')
        print(f'  speedup       : {old_ms / new_ms:6.2f}x   max|diff| = {max_diff:.2e}')
        print(f'  vertices={new.shape[0]}  starts={list(starts)}  counts={list(counts)}')


if __name__ == '__main__':
    main()