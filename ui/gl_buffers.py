"""Reusable compatibility-OpenGL buffer for [x, y, r, g, b, a] vertices."""

import ctypes

import numpy as np
import OpenGL.GL as gl


class ColoredVertexBuffer:
    """Own a VBO; callers must have the owning GL context current."""

    def __init__(self):
        self._vbo = None
        self._capacity_bytes = 0

    @property
    def gl(self):
        return gl

    @property
    def vbo(self):
        return self._vbo

    def initialize(self):
        self.cleanup()
        ids = self.gl.glGenBuffers(1)
        self._vbo = int(ids) if isinstance(ids, (int, np.integer)) else int(ids[0])

    def cleanup(self):
        if self._vbo is not None:
            self.gl.glDeleteBuffers(1, [self._vbo])
        self._vbo = None
        self._capacity_bytes = 0

    def _upload(self, vertices):
        if self._vbo is None:
            raise RuntimeError('initialize() requires a current OpenGL context')
        api = self.gl
        api.glBindBuffer(api.GL_ARRAY_BUFFER, self._vbo)
        try:
            if vertices.nbytes > self._capacity_bytes:
                api.glBufferData(api.GL_ARRAY_BUFFER, vertices.nbytes, vertices, api.GL_DYNAMIC_DRAW)
                self._capacity_bytes = vertices.nbytes
            else:
                api.glBufferSubData(api.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        finally:
            api.glBindBuffer(api.GL_ARRAY_BUFFER, 0)

    def _draw_arrays(self, mode, starts, counts, line_width=None):
        api = self.gl
        if line_width is not None:
            api.glLineWidth(line_width)
        api.glBindBuffer(api.GL_ARRAY_BUFFER, self._vbo)
        api.glEnableClientState(api.GL_VERTEX_ARRAY)
        api.glEnableClientState(api.GL_COLOR_ARRAY)
        try:
            api.glVertexPointer(2, api.GL_FLOAT, 24, ctypes.c_void_p(0))
            api.glColorPointer(4, api.GL_FLOAT, 24, ctypes.c_void_p(8))
            for start, count in zip(starts, counts):
                api.glDrawArrays(mode, int(start), int(count))
        finally:
            api.glDisableClientState(api.GL_VERTEX_ARRAY)
            api.glDisableClientState(api.GL_COLOR_ARRAY)
            api.glBindBuffer(api.GL_ARRAY_BUFFER, 0)
