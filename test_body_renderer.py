"""Validate fan-equivalent geometry, alpha/order and shared VBO submission."""

import unittest
from unittest import mock

import numpy as np
import OpenGL.GL as gl

from physics import Body, Camera
from ui.body_renderer import BodyRenderer, build_body_vertices, VERTICES_PER_BODY
import ui.gl_buffers as buffers
from test_trail_draw_batch import GlRecorder


class TestBodyRenderer(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(viewport_width=1280, viewport_height=720, zoom=25.0,
                             center_x=2.0, center_y=-3.0)
        self.bodies = [Body(position=(5.0, -1.0), physical_radius=0.01),
                       Body(position=(-4.0, 8.0), render_radius=2.0)]

    def test_triangles_match_original_fans_and_selection(self):
        vertices, count = build_body_vertices(self.bodies, self.camera, selected=0)
        reference = []
        for body in self.bodies:
            sx, sy = self.camera.world_to_screen(*body.position)
            center = np.array([sx / 1280 * 2 - 1, 1 - sy / 720 * 2])
            radius = max(body.render_radius * 25, 3)
            ndc_radius = radius * np.array([2 / 1280, 2 / 720])
            for factor, alpha in ((1.3, 0.15), (1.0, 1.0)):
                for j in range(32):
                    triangle = [center]
                    for k in (j, j + 1):
                        angle = 2 * np.pi * k / 32
                        triangle.append(center + ndc_radius * factor * [np.cos(angle), np.sin(angle)])
                    reference.extend([(*xy, *body.color, alpha) for xy in triangle])
        np.testing.assert_allclose(vertices[:count], reference, atol=1e-6, rtol=0)
        self.assertEqual(count, 2 * VERTICES_PER_BODY)
        self.assertEqual(vertices.dtype, np.float32)
        np.testing.assert_allclose(vertices[count:, 2:], np.tile([1, 1, 1, 0.8], (32, 1)))
        sx, sy = self.camera.world_to_screen(*self.bodies[0].position)
        center = np.array([sx / 1280 * 2 - 1, 1 - sy / 720 * 2])
        distances = (vertices[count:, :2] - center) / (3 * 1.4 * np.array([2 / 1280, 2 / 720]))
        np.testing.assert_allclose(np.linalg.norm(distances, axis=1), 1, atol=1e-5)

    def test_batch_submission_and_selected_order(self):
        recorder = GlRecorder()
        renderer = BodyRenderer()
        with mock.patch.object(buffers, 'gl', recorder):
            renderer.initialize()
            renderer.render(self.bodies, self.camera)
            self.assertEqual(recorder.named('glDrawArrays'), [(gl.GL_TRIANGLES, 0, 384)])
            recorder.calls.clear()
            renderer.render(self.bodies, self.camera, selected=0)
            self.assertEqual(recorder.named('glDrawArrays'), [
                (gl.GL_TRIANGLES, 0, 192), (gl.GL_LINE_LOOP, 384, 32),
                (gl.GL_TRIANGLES, 192, 192),
            ])
            self.assertEqual(recorder.named('glVertex2f'), [])
            renderer.cleanup()

    def test_render_does_not_modify_bodies(self):
        before = [(b.position.copy(), b.velocity.copy(), b.color.copy(), b.render_radius) for b in self.bodies]
        build_body_vertices(self.bodies, self.camera, selected=1)
        for body, (position, velocity, color, radius) in zip(self.bodies, before):
            np.testing.assert_array_equal(body.position, position)
            np.testing.assert_array_equal(body.velocity, velocity)
            np.testing.assert_array_equal(body.color, color)
            self.assertEqual(body.render_radius, radius)

    def test_empty_scene(self):
        vertices, count = build_body_vertices([], self.camera)
        self.assertEqual(vertices.shape, (0, 6))
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
