"""
Trail 渲染数据层（第一阶段重构：只改数据层，不动 OpenGL 绘制）

将 immediate mode 的逐顶点数据准备（list 拷贝、逐点采样、逐点坐标转换）
重构为纯 numpy 批量生成 interleaved float32 顶点：

    [x, y, r, g, b, a]   （NDC 坐标 + RGBA 颜色/透明度）

顶点公式与 ui/simulation_widget.py::_draw_trail 完全一致（逐位复现）：
    ndc_x = ((wx - camera.center_x) * camera.zoom + w * 0.5) / w * 2.0 - 1.0
    ndc_y = 1.0 - (-(wy - camera.center_y) * camera.zoom + h * 0.5) / h * 2.0
    alpha = 0.15 + 0.65 * np.linspace(0.0, 1.0, m)

本模块不涉及任何 OpenGL 调用 / VBO / shader，也不修改 physics 与 trail 数据结构。
"""

import numpy as np


class TrailVertexBuilder:
    """批量构建轨迹顶点数据（无 OpenGL / Qt 依赖，可 headless 测试）。

    输入（鸭子类型，不依赖具体类型）：
        bodies : 可迭代对象，每个元素需具备：
                 trail  : deque of np.ndarray (2,) float64（世界坐标，DU）
                 color  : np.ndarray (3,) float32（归一化 RGB，0-1）
        camera : center_x / center_y / zoom / viewport_width / viewport_height

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
            arr = np.asarray(body.trail, dtype=np.float64)
            if n > self.sampling_limit:
                arr = arr[self._sample_indices(n, self.sampling_limit)]
            if len(arr) < 2:
                continue
            prepared.append((arr, body.color))

        total = sum(len(arr) for arr, _ in prepared)
        vertices = np.empty((total, 6), dtype=np.float32)
        starts = np.empty(len(prepared), dtype=np.int64)
        counts = np.empty(len(prepared), dtype=np.int64)

        w = camera.viewport_width
        h = camera.viewport_height
        offset = 0
        for i, (arr, color) in enumerate(prepared):
            m = len(arr)
            starts[i] = offset
            counts[i] = m
            self._fill_block(vertices[offset:offset + m], arr, color, camera, w, h)
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
    def _fill_block(block: np.ndarray, arr: np.ndarray, color, camera, w, h) -> None:
        """将单个 body 的采样轨迹写入 interleaved 顶点块。

        全部通过 numpy 列赋值完成（slicing + broadcasting），无逐顶点循环。
        """
        ndc_x = ((arr[:, 0] - camera.center_x) * camera.zoom + w * 0.5) / w * 2.0 - 1.0
        ndc_y = 1.0 - (-(arr[:, 1] - camera.center_y) * camera.zoom + h * 0.5) / h * 2.0
        alphas = 0.15 + 0.65 * np.linspace(0.0, 1.0, len(arr))

        block[:, 0] = ndc_x
        block[:, 1] = ndc_y
        block[:, 2] = color[0]
        block[:, 3] = color[1]
        block[:, 4] = color[2]
        block[:, 5] = alphas