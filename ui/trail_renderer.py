"""
Trail 渲染数据层 + VBO 批量渲染器

第一阶段（TrailVertexBuilder）：
    将 immediate mode 的逐顶点数据准备（list 拷贝、逐点采样、逐点坐标转换）
    重构为纯 numpy 批量生成 interleaved float32 顶点：
        [x, y, r, g, b, a]   （NDC 坐标 + RGBA 颜色/透明度）

第二阶段（TrailRenderer）：
    VBO 生命周期管理 + 每帧 upload/draw：
        trail data -> TrailVertexBuilder -> glBufferSubData
        -> 每 body 一次 glDrawArrays(GL_LINE_STRIP)（暂不使用 glMultiDrawArrays）

顶点公式与 ui/simulation_widget.py::_draw_trail 完全一致（逐位复现）：
    ndc_x = ((wx - camera.center_x) * camera.zoom + w * 0.5) / w * 2.0 - 1.0
    ndc_y = 1.0 - (-(wy - camera.center_y) * camera.zoom + h * 0.5) / h * 2.0
    alpha = 0.15 + 0.65 * np.linspace(0.0, 1.0, m)

本模块不修改 physics 与 trail 数据结构。
"""

import time

import numpy as np
import OpenGL.GL as gl

from .gl_buffers import ColoredVertexBuffer
from .render_coordinates import world_to_ndc


class TrailVertexBuilder:
    """批量构建轨迹顶点数据（无 OpenGL / Qt 依赖，可 headless 测试）。

    输入（鸭子类型，不依赖具体类型）：
        bodies : 可迭代对象，每个元素需具备：
                 trail  : deque of np.ndarray (2,) float64（世界坐标，DU）
                 color  : np.ndarray (3,) float32（归一化 RGB，0-1）
        camera : world_to_screen / center_x / center_y / zoom / viewport dimensions

    输出：
        vertices : (N, 6) float32 —— interleaved [x, y, r, g, b, a]
        starts   : (K,) int64    —— 每个 body 的起始顶点索引
        counts   : (K,) int64    —— 每个 body 的顶点数量

    N = sum(counts)，K = 实际参与绘制的 body 数量（轨迹点数 >= 2）。
    """

    def __init__(self, sampling_limit: int = 1000) -> None:
        self.sampling_limit = int(sampling_limit)

    def build(self, bodies, camera):
        """构建所有天体的 interleaved 轨迹顶点缓冲。

        全 numpy 实现：无逐顶点 Python 循环（仅按 body 迭代）。
        """
        prepared = []
        for body in bodies:
            n = len(body.trail)
            if n < 2:
                continue
            if n > self.sampling_limit:
                # Convert only sampled points; deque indexing in a loop is O(n*k).
                history = list(body.trail)
                points = [history[i] for i in self._sample_indices(n, self.sampling_limit)]
            else:
                points = body.trail
            arr = np.asarray(points, dtype=np.float64)
            if len(arr) < 2:
                continue
            prepared.append((arr, body.color))

        total = sum(len(arr) for arr, _ in prepared)
        vertices = np.empty((total, 6), dtype=np.float32)
        starts = np.empty(len(prepared), dtype=np.int64)
        counts = np.empty(len(prepared), dtype=np.int64)

        offset = 0
        for i, (arr, color) in enumerate(prepared):
            m = len(arr)
            starts[i] = offset
            counts[i] = m
            self._fill_block(vertices[offset:offset + m], arr, color, camera)
            offset += m
        return vertices, starts, counts

    @staticmethod
    def _sample_indices(n: int, max_points: int) -> np.ndarray:
        """向量化均匀采样索引，与 _draw_trail 的逐点循环逐位一致。"""
        step = n / max_points
        indices = (
            n - 1 - np.arange(max_points, dtype=np.float64) * step
        ).astype(np.int64)
        return indices[::-1]

    @staticmethod
    def _fill_block(block: np.ndarray, arr: np.ndarray, color, camera) -> None:
        """将单个 body 的采样轨迹写入 interleaved 顶点块。

        全部通过 numpy 列赋值完成（slicing + broadcasting），无逐顶点循环。
        """
        alphas = 0.15 + 0.65 * np.linspace(0.0, 1.0, len(arr))

        block[:, :2] = world_to_ndc(arr, camera)
        block[:, 2] = color[0]
        block[:, 3] = color[1]
        block[:, 4] = color[2]
        block[:, 5] = alphas


class TrailRenderer(ColoredVertexBuffer):
    """VBO 批量渲染器（第二阶段：替换 immediate mode 逐顶点提交）。

    职责：
      - VBO 创建 / 销毁（initialize / cleanup，需在有效 GL 上下文中调用）
      - 每帧：TrailVertexBuilder 生成 interleaved 顶点 -> glBufferSubData 上传
      - 绘制：每 body 一次 glDrawArrays(GL_LINE_STRIP)（暂不使用 glMultiDrawArrays）

    视觉与旧路径完全一致：同 NDC 顶点 / RGBA / GL_LINE_STRIP / 线宽 1.5 / blending。
    """

    def __init__(self, sampling_limit: int = 1000) -> None:
        super().__init__()
        self.builder = TrailVertexBuilder(sampling_limit)
        self._cache_key = None
        self._cache_sources = ()
        self._cached_draw = None

    @property
    def sampling_limit(self) -> int:
        return self.builder.sampling_limit

    @sampling_limit.setter
    def sampling_limit(self, value: int) -> None:
        self.builder.sampling_limit = int(value)

    @property
    def gl(self):
        return gl

    def cleanup(self):
        super().cleanup()
        self._cache_key = None
        self._cache_sources = ()
        self._cached_draw = None

    def render(self, bodies, camera, phase=None, line_width: float = 1.5, revision=None):
        """每帧渲染：trail data -> numpy 顶点 -> glBufferSubData -> 每 body 一次 glDrawArrays。

        phase : 可选，提供 add(name, seconds)（如 RenderPhaseTimer），
                记录 trail_prepare / trail_upload / trail_draw 三个阶段耗时。
        返回  (顶点数, 参与绘制的 body 数)；无可见轨迹时返回 (0, 0)。
        """
        if self._vbo is None:
            raise RuntimeError('TrailRenderer.initialize() 必须在有效 GL 上下文中先行调用')
        # A caller-supplied revision permits reusing already uploaded vertices
        # between physics ticks. With revision=None always rebuild, preserving
        # the public renderer's support for arbitrarily mutable input arrays.
        key = None
        if revision is not None:
            bodies = tuple(bodies)
            sources = tuple(
                (body, body.trail[0], body.trail[-1]) if body.trail else (body,)
                for body in bodies
            )
            key = (
                revision, self.sampling_limit,
                camera.center_x, camera.center_y, camera.zoom,
                camera.viewport_width, camera.viewport_height,
                tuple((id(b), id(b.trail), len(b.trail),
                       id(b.trail[0]) if b.trail else None,
                       id(b.trail[-1]) if b.trail else None, tuple(b.color)) for b in bodies),
            )
            if key == self._cache_key:
                starts, counts, result = self._cached_draw
                t0 = time.perf_counter() if phase is not None else None
                if result[0]:
                    self._draw(starts, counts, line_width)
                if phase is not None:
                    phase.add('trail_draw', time.perf_counter() - t0)
                return result
        if phase is not None:
            t0 = time.perf_counter()
        vertices, starts, counts = self.builder.build(bodies, camera)
        if phase is not None:
            phase.add('trail_prepare', time.perf_counter() - t0)
        if vertices.size == 0:
            self._cache_key = key
            self._cache_sources = sources if key is not None else ()
            self._cached_draw = (starts, counts, (0, 0))
            return 0, 0
        if phase is not None:
            t1 = time.perf_counter()
        self._upload(vertices)
        if phase is not None:
            phase.add('trail_upload', time.perf_counter() - t1)
            t2 = time.perf_counter()
        self._draw(starts, counts, line_width)
        if phase is not None:
            phase.add('trail_draw', time.perf_counter() - t2)
        result = int(vertices.shape[0]), int(len(starts))
        self._cache_key = key
        self._cache_sources = sources if key is not None else ()
        self._cached_draw = (starts, counts, result)
        return result

    def _draw(self, starts, counts, line_width: float) -> None:
        self._draw_arrays(gl.GL_LINE_STRIP, starts, counts, line_width)
