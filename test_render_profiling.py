"""Regression checks for actual-paint FPS and GL timer resource cleanup."""

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from ui.profiler import FrameProfiler, PerformanceLogger
from ui.simulation_widget import SimulationWidget, _GpuTimerQueryRing
import ui.simulation_widget as sw


class TestRenderProfiling(unittest.TestCase):
    def test_fps_uses_paints_and_keeps_work_between_paints(self):
        engine = SimpleNamespace(bodies=[], advance=mock.Mock(return_value=1))
        profiler = FrameProfiler(engine)
        widget = SimulationWidget.__new__(SimulationWidget)
        widget.engine = engine
        widget._profiler = profiler
        widget._render_phase_timer = None
        widget._cpu_profiler = None
        widget._gpu_profiling_mode = 'none'
        widget._show_trails = False
        widget._draw_bodies = mock.Mock()
        widget._draw_overlay = mock.Mock()
        widget._is_paused = False
        widget._last_tick_time = 1.0
        widget._trail_revision = 0
        widget._update_rate_check = mock.Mock()
        with mock.patch.object(sw, 'gl'), mock.patch('time.perf_counter') as clock:
            clock.return_value = 1.0
            widget.paintGL()
            clock.return_value = 1.0 + 1.0 / 120.0
            widget._on_animation_tick()
            profiler.record('step', 0.002)
            self.assertEqual(len(profiler.history), 0)
            clock.return_value = 1.0 + 1.0 / 60.0
            widget.paintGL()
            self.assertAlmostEqual(profiler.summary()['fps'], 60.0)
            self.assertAlmostEqual(profiler.history[0]['physics'], 0.002)
            widget._is_paused = True
            clock.return_value = 1.0 + 2.0 / 60.0
            widget.paintGL()
            self.assertAlmostEqual(profiler.summary()['fps'], 60.0)

    def test_gpu_query_cleanup_accepts_numpy_query_ids(self):
        ring = _GpuTimerQueryRing()
        ring.supported = True
        ring.queries = np.arange(1, 9, dtype=np.uint32)
        with mock.patch.object(sw, 'gl') as api:
            ring.cleanup()
            self.assertEqual(api.glDeleteQueries.call_args.args[0], 8)
        self.assertFalse(ring.supported)
        self.assertEqual(ring.queries, [])

    def test_log_flushes_once_per_second_instead_of_each_frame(self):
        logger = PerformanceLogger(None)
        logger._file = mock.Mock()
        frame = FrameProfiler._new_frame()
        frame['period'] = 1.0 / 60.0
        with mock.patch('time.perf_counter', return_value=10.0), mock.patch('builtins.print'):
            logger.record(frame)
            self.assertEqual(logger._file.flush.call_count, 1)
            with mock.patch('time.perf_counter', return_value=10.1):
                logger.record(frame)
            self.assertEqual(logger._file.flush.call_count, 1)
        logger.close()
        self.assertIsNone(logger._file)


if __name__ == '__main__':
    unittest.main()
