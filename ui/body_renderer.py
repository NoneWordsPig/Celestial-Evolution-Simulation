"""Batch body disks and halos without mutating simulation state."""

import time

import numpy as np
import OpenGL.GL as gl

from .gl_buffers import ColoredVertexBuffer
from .render_coordinates import world_to_ndc


CIRCLE_SEGMENTS = 32
_ANGLES = np.arange(CIRCLE_SEGMENTS + 1) * (2.0 * np.pi / CIRCLE_SEGMENTS)
UNIT_CIRCLE = np.column_stack((np.cos(_ANGLES), np.sin(_ANGLES)))
_TRIANGLES = np.zeros((CIRCLE_SEGMENTS, 3, 2), dtype=np.float64)
_TRIANGLES[:, 1] = UNIT_CIRCLE[:-1]
_TRIANGLES[:, 2] = UNIT_CIRCLE[1:]
VERTICES_PER_BODY = 2 * CIRCLE_SEGMENTS * 3


def build_body_vertices(bodies, camera, minimum_radius=3.0, selected=-1):
    """Return interleaved disk/glow triangles and an optional selection loop.

    Coordinate calculations stay float64 until the final GPU buffer. Glow and
    disk triangles retain body order so alpha blending matches the fan path.
    """
    n = len(bodies)
    has_selection = 0 <= selected < n
    count = n * VERTICES_PER_BODY
    vertices = np.empty((count + CIRCLE_SEGMENTS * has_selection, 6), dtype=np.float32)
    if not n:
        return vertices, count
    positions = np.asarray([b.position for b in bodies], dtype=np.float64)
    w, h = camera.viewport_width, camera.viewport_height
    centers = world_to_ndc(positions, camera)
    radii = np.maximum(np.asarray([b.render_radius for b in bodies]) * camera.zoom, minimum_radius)
    radii = radii[:, None] * np.array([2.0 / w, 2.0 / h])
    blocks = vertices[:count].reshape(n, 2, CIRCLE_SEGMENTS, 3, 6)
    scales = np.array([1.3, 1.0])
    blocks[..., :2] = (
        centers[:, None, None, None, :]
        + radii[:, None, None, None, :] * scales[None, :, None, None, None]
        * _TRIANGLES[None, None, :, :, :]
    )
    blocks[..., 2:5] = np.asarray([b.color for b in bodies])[:, None, None, None, :]
    blocks[..., 5] = np.array([0.15, 1.0])[None, :, None, None]
    if has_selection:
        vertices[count:, :2] = centers[selected] + radii[selected] * 1.4 * UNIT_CIRCLE[:-1]
        vertices[count:, 2:] = (1.0, 1.0, 1.0, 0.8)
    return vertices, count


class BodyRenderer(ColoredVertexBuffer):
    """Share VBO ownership, upload and client array setup with TrailRenderer."""

    def render(self, bodies, camera, minimum_radius=3.0, selected=-1, phase=None):
        t0 = time.perf_counter() if phase is not None else None
        vertices, count = build_body_vertices(bodies, camera, minimum_radius, selected)
        if phase is not None:
            phase.add('body_prepare', time.perf_counter() - t0)
            t0 = time.perf_counter()
        if not vertices.size:
            return
        self._upload(vertices)
        if len(vertices) > count:
            # Preserve the old ordering: selection ring before subsequent bodies.
            split = (selected + 1) * VERTICES_PER_BODY
            self._draw_arrays(gl.GL_TRIANGLES, [0], [split])
            self._draw_arrays(gl.GL_LINE_LOOP, [count], [CIRCLE_SEGMENTS], 2.0)
            if split < count:
                self._draw_arrays(gl.GL_TRIANGLES, [split], [count - split])
        else:
            self._draw_arrays(gl.GL_TRIANGLES, [0], [count])
        if phase is not None:
            phase.add('body_upload_draw', time.perf_counter() - t0)
