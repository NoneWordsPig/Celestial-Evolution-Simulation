"""
CPU-side render pipeline profiling (measure only, no optimization, no behavior change).

Pass A (timing):
    Attaches SimulationWidget's CpuPipelineProfiler (paintEvent wrapper + fine-grained
    paintGL phase timers). For each speed (default 0.1/1/2/5/10 x) it reports:
        frame decomposition: Qt dispatch / paintGL CPU / makeCurrent+GPU submit+swap /
                             physics / UI / idle
        paintGL breakdown:   gl_clear / camera / state prepare / body prepare /
                             trail prepare / buffer upload / draw call / QPainter /
                             overlay / swap / other

Pass B (allocation/call counting):
    Wraps gl* calls, numpy factories, Qt constructors and QPainter.drawText to count
    per-frame Python<->GL traffic, numpy conversions and object creations.
    Also confirms there are no VBO/VAO/shader/texture allocations in the render path.

Scene: scenes/solar_system.json, Moon removed (nine-body), GPU profiling mode 'none'
(no glFinish, no timer query) so the numbers reflect pure CPU-side pipeline cost.

Usage:
    python benchmark_render_pipeline.py
    python benchmark_render_pipeline.py --speeds 0.1,1,2,5,10 --rounds 1
        --warmup 2 --duration 6 --count-duration 4 --scene scenes/solar_system.json

Results are appended to logs/render_pipeline_profile.csv.
"""

import argparse
import csv
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Window-level main-thread busy accumulator (class-level ProfilingApplication.notify wrap).
# Only the outermost notify span counts (nested events are excluded).
_BUSY = {'total': 0.0, 'active': False, 'depth': 0, 't0': 0.0}


def _spin(window, app, seconds):
    """Pump the event loop for a fixed wall duration."""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    keeper = _start_visibility_keeper(window, loop)
    loop.exec()
    keeper.stop()


def _start_visibility_keeper(window, loop, interval_ms=250):
    """Remote-desktop / foreground locks may minimize the test window; keep it exposed."""
    from PyQt6.QtCore import QTimer

    timer = QTimer()
    timer.setInterval(interval_ms)

    def _check():
        handle = window.windowHandle()
        if handle is not None and not handle.isExposed():
            window.showNormal()
            window.raise_()

    timer.timeout.connect(_check)
    timer.start()
    return timer


def _load_nine_body(window, scene, speed):
    """Load scene -> remove Moon (nine bodies) -> set multiplier."""
    window._load_scene_from_path(str(scene))
    body_count = len(window.engine.bodies)
    for i, body in enumerate(window.engine.bodies):
        if body.name == 'Moon':
            window.engine.remove_body(i)
            body_count = len(window.engine.bodies)
            break
    window.engine.time_scale = float(speed)
    window.sim_widget.update()
    return body_count


def _install_frame_counters():
    """Class-level wraps: count update() calls, render ticks and paintGL calls."""
    from PyQt6.QtWidgets import QWidget
    from ui.simulation_widget import SimulationWidget

    counts = {'render_ticks': 0, 'paintgl': 0, 'update_calls': 0}
    originals = {}

    orig_render_tick = SimulationWidget._on_render_tick

    def w_render_tick(self, *a, **k):
        counts['render_ticks'] += 1
        return orig_render_tick(self, *a, **k)

    originals['_on_render_tick'] = orig_render_tick
    SimulationWidget._on_render_tick = w_render_tick

    orig_paintgl = SimulationWidget.paintGL

    def w_paintgl(self, *a, **k):
        counts['paintgl'] += 1
        return orig_paintgl(self, *a, **k)

    originals['paintGL'] = orig_paintgl
    SimulationWidget.paintGL = w_paintgl

    orig_update = QWidget.update

    def w_update(self, *a, **k):
        counts['update_calls'] += 1
        return orig_update(self, *a, **k)

    originals['update'] = orig_update
    SimulationWidget.update = w_update

    return counts, originals


def _restore_frame_counters(originals):
    from ui.simulation_widget import SimulationWidget
    for attr, orig in originals.items():
        setattr(SimulationWidget, attr, orig)


def _drain(history, seen, buckets):
    """Move newly closed FrameProfiler frames into per-metric buckets."""
    for f in list(history):
        if id(f) in seen:
            continue
        seen[id(f)] = f
        if f['period'] <= 0.0:
            continue
        period = f['period'] * 1000.0
        physics = f['physics'] * 1000.0
        render_wall = f['render'] * 1000.0
        gpu_wait = min(f['gpu_sync'] * 1000.0, render_wall)
        ui = f['ui'] * 1000.0
        buckets['period'].append(period)
        buckets['physics'].append(physics)
        buckets['ui'].append(ui)
        buckets['gpu_wait'].append(gpu_wait)


def _p95(values):
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    return s[int(round(0.95 * (len(s) - 1)))]


def _measure_frame(window, app, frame_counts, duration, sampler_ms=150):
    """Measure window: accumulate profiler frames + notify busy, return aggregates."""
    from PyQt6.QtCore import QEventLoop, QTimer
    prof = window.profiler
    seen = {id(f): f for f in list(prof.history)}
    buckets = {k: [] for k in ('period', 'physics', 'ui', 'gpu_wait')}

    frame_counts['render_ticks'] = 0
    frame_counts['paintgl'] = 0
    frame_counts['update_calls'] = 0
    _BUSY['total'] = 0.0
    _BUSY['active'] = True
    t0 = time.perf_counter()
    end = t0 + duration

    loop = QEventLoop()
    sampler = QTimer()
    sampler.setInterval(sampler_ms)

    def _sample():
        _drain(prof.history, seen, buckets)
        if time.perf_counter() >= end:
            sampler.stop()
            loop.quit()

    sampler.timeout.connect(_sample)
    sampler.start()
    keeper = _start_visibility_keeper(window, loop)
    QTimer.singleShot(int((duration + 1.0) * 1000), loop.quit)
    loop.exec()
    keeper.stop()
    _drain(prof.history, seen, buckets)
    _BUSY['active'] = False
    elapsed = time.perf_counter() - t0

    n = len(buckets['period'])
    if n == 0:
        return None

    busy_total = _BUSY['total']
    physics_total = sum(buckets['physics'])
    ui_total = sum(buckets['ui'])
    idle_total = max(0.0, elapsed - busy_total)
    return {
        'frames': n,
        'elapsed': elapsed,
        'paintgl': frame_counts['paintgl'],
        'render_ticks': frame_counts['render_ticks'],
        'update_calls': frame_counts['update_calls'],
        'period_avg': statistics.fmean(buckets['period']),
        'period_p95': _p95(buckets['period']),
        'physics_total_ms': physics_total,
        'physics_ms': physics_total / n,
        'ui_total_ms': ui_total,
        'ui_ms': ui_total / n,
        'gpu_wait_ms': statistics.fmean(buckets['gpu_wait']),
        'busy_total': busy_total,
        'idle_total': idle_total,
        'busy_fraction': busy_total / elapsed,
        'paints_per_frame': frame_counts['paintgl'] / n,
        'fps_paintgl': frame_counts['paintgl'] / elapsed,
        'fps_update': frame_counts['update_calls'] / elapsed,
        'fps_render_tick': frame_counts['render_ticks'] / elapsed,
    }


# ---------------------------------------------------------------------------
# Pass A: fine-grained paintGL timing
# ---------------------------------------------------------------------------

# Aggregation of fine phases into the requested report rows.
_CAMERA_KEYS = ('body_pos_conv', 'body_ndc', 'trail_vertex_gen')
_STATE_KEYS = ('state_read', 'trail_history_read', 'trail_sample')
_BODY_PREP_KEYS = ('body_radius_conv', 'body_color_conv')
_TRAIL_PREP_KEYS = ('trail_numpy_convert',)
_DRAW_KEYS = ('body_draw', 'trail_draw')
_QPAINTER_KEYS = ('qpainter_begin', 'qpainter_scale_bar',
                  'qpainter_overlay', 'qpainter_end')


def _agg(phases, keys):
    return sum(phases.get(k, 0.0) for k in keys)


def _run_timing_pass(window, app, scene, args, cpu_profiler, frame_counts):
    rows = []
    for speed in args.speeds:
        for rnd in range(args.rounds):
            _load_nine_body(window, scene, speed)
            _spin(window, app, args.warmup)
            cpu_profiler.clear()
            stats = _measure_frame(window, app, frame_counts, args.duration)
            if stats is None:
                continue
            n = stats['frames']
            paints = stats['paintgl']
            phases = cpu_profiler.phases
            paint_event_s = phases.get('paint_event_total', 0.0)
            paintgl_s = phases.get('paintgl_total', 0.0)
            paint_event_ms = paint_event_s * 1000.0
            paintgl_ms = paintgl_s * 1000.0

            # Per-frame decomposition (frame total = period)
            qt_dispatch = max(
                0.0, stats['busy_total'] * 1000.0
                - stats['physics_total_ms'] - stats['ui_total_ms']
                - paint_event_ms
            ) / n
            swap_submit = max(0.0, paint_event_ms - paintgl_ms) / n
            paintgl_cpu = paintgl_ms / n
            idle = stats['idle_total'] / n

            row = {
                'speed': speed, 'round': rnd,
                'paints': paints, 'frames': n,
                'period_avg': stats['period_avg'],
                'period_p95': stats['period_p95'],
                'physics': stats['physics_ms'],
                'ui': stats['ui_ms'],
                'qt_dispatch': qt_dispatch,
                'paintgl_cpu': paintgl_cpu,
                'swap_submit': swap_submit,
                'idle': idle,
                'busy_fraction': stats['busy_fraction'],
                'paints_per_frame': stats['paints_per_frame'],
                'fps_paintgl': stats['fps_paintgl'],
                'fps_update': stats['fps_update'],
                'fps_render_tick': stats['fps_render_tick'],
            }
            # paintGL breakdown (per paint, ms)
            for name, secs in phases.items():
                row[f'ph_{name}'] = (secs * 1000.0 / paints) if paints else 0.0
            # aggregated report rows (per paint, ms)
            gl_clear = phases.get('gl_clear', 0.0) * 1000.0 / paints
            camera = _agg(phases, _CAMERA_KEYS) * 1000.0 / paints
            state = _agg(phases, _STATE_KEYS) * 1000.0 / paints
            body_prep = _agg(phases, _BODY_PREP_KEYS) * 1000.0 / paints
            trail_prep = _agg(phases, _TRAIL_PREP_KEYS) * 1000.0 / paints
            draw_call = _agg(phases, _DRAW_KEYS) * 1000.0 / paints
            qp = _agg(phases, _QPAINTER_KEYS) * 1000.0 / paints
            overlay = phases.get('qpainter_overlay', 0.0) * 1000.0 / paints
            known = (gl_clear + camera + state + body_prep + trail_prep
                     + draw_call + qp)
            other = max(0.0, paintgl_ms / paints - known)
            row.update({
                'ph_gl_clear': gl_clear,
                'ph_camera': camera,
                'ph_state_prepare': state,
                'ph_body_prepare': body_prep,
                'ph_trail_prepare': trail_prep,
                'ph_buffer_upload': 0.0,
                'ph_draw_call': draw_call,
                'ph_qpainter': qp,
                'ph_overlay': overlay,
                'ph_other': other,
            })
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Pass B: per-frame call / allocation counting
# ---------------------------------------------------------------------------

def _install_call_counters():
    """Wrap gl/numpy/Qt constructors/QPainter.drawText + trail/body draws."""
    from ui import simulation_widget as sw
    from PyQt6.QtGui import QPainter

    counts = {
        'gl': {},
        'np': {'calls': {}, 'elems': {}},
        'qt': {},
        'drawText_calls': 0,
        'drawText_time_s': 0.0,
        'fillRect_calls': 0,
        'drawLine_calls': 0,
        'trail_sample_calls': 0,
        'trail_sample_in': 0,
        'trail_sample_out': 0,
        'trail_points': 0,
        'body_draw_calls': 0,
    }
    restores = []

    for name in (
        'glClear', 'glColor4f', 'glVertex2f', 'glBegin', 'glEnd',
        'glLineWidth', 'glBindBuffer', 'glBufferData', 'glBufferSubData',
        'glGenBuffers', 'glDeleteBuffers', 'glGenVertexArrays',
        'glCreateShader', 'glCreateProgram', 'glUseProgram',
        'glGenTextures', 'glUniform1f', 'glUniform4f',
    ):
        if not hasattr(sw.gl, name):
            continue
        orig = getattr(sw.gl, name)

        def make_wrapper(orig_fn, fn_name):
            def wrapper(*a, **k):
                counts['gl'][fn_name] = counts['gl'].get(fn_name, 0) + 1
                return orig_fn(*a, **k)
            return wrapper

        setattr(sw.gl, name, make_wrapper(orig, name))
        restores.append((sw.gl, name, orig))

    # numpy factories used by the render path
    real_np = sw.np

    class _CountingNp:
        def __init__(self):
            self._real = real_np

        def asarray(self, obj, *a, **k):
            counts['np']['calls']['asarray'] = (
                counts['np']['calls'].get('asarray', 0) + 1
            )
            try:
                counts['np']['elems']['asarray'] = (
                    counts['np']['elems'].get('asarray', 0) + len(obj)
                )
            except TypeError:
                pass
            return self._real.asarray(obj, *a, **k)

        def empty(self, shape, *a, **k):
            counts['np']['calls']['empty'] = (
                counts['np']['calls'].get('empty', 0) + 1
            )
            try:
                counts['np']['elems']['empty'] = (
                    counts['np']['elems'].get('empty', 0)
                    + int(shape[0]) * int(shape[1])
                )
            except (TypeError, IndexError):
                pass
            return self._real.empty(shape, *a, **k)

        def linspace(self, start, stop, num, *a, **k):
            counts['np']['calls']['linspace'] = (
                counts['np']['calls'].get('linspace', 0) + 1
            )
            counts['np']['elems']['linspace'] = (
                counts['np']['elems'].get('linspace', 0) + int(num)
            )
            return self._real.linspace(start, stop, num, *a, **k)

        def __getattr__(self, name):
            return getattr(self._real, name)

    sw.np = _CountingNp()
    restores.append((sw, 'np', real_np))

    # Qt constructors
    for name in ('QColor', 'QPen', 'QFont', 'QPointF', 'QBrush'):
        orig = getattr(sw, name, None)
        if orig is None:
            continue

        def make_qtwrap(orig_fn, qt_name):
            def wrapper(*a, **k):
                counts['qt'][qt_name] = counts['qt'].get(qt_name, 0) + 1
                return orig_fn(*a, **k)
            return wrapper

        setattr(sw, name, make_qtwrap(orig, name))
        restores.append((sw, name, orig))

    # QPainter subclass: count drawText / fillRect / drawLine precisely
    class _CountingPainter(QPainter):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)

        def drawText(self, *a, **k):
            counts['drawText_calls'] += 1
            t0 = time.perf_counter()
            try:
                return super().drawText(*a, **k)
            finally:
                counts['drawText_time_s'] += time.perf_counter() - t0

        def fillRect(self, *a, **k):
            counts['fillRect_calls'] += 1
            return super().fillRect(*a, **k)

        def drawLine(self, *a, **k):
            counts['drawLine_calls'] += 1
            return super().drawLine(*a, **k)

    orig_qpainter = sw.QPainter
    sw.QPainter = _CountingPainter
    restores.append((sw, 'QPainter', orig_qpainter))

    # trail sampling / draw entry (class-level wraps)
    from ui.simulation_widget import SimulationWidget
    orig_sample = SimulationWidget._sample_trail

    def counted_sample(pts, max_points):
        counts['trail_sample_calls'] += 1
        counts['trail_sample_in'] += len(pts)
        out = orig_sample(pts, max_points)
        counts['trail_sample_out'] += len(out)
        return out

    SimulationWidget._sample_trail = staticmethod(counted_sample)
    restores.append((SimulationWidget, '_sample_trail', orig_sample))

    orig_trail = SimulationWidget._draw_trail

    def counted_trail(self, body):
        counts['trail_points'] += len(body.trail)
        return orig_trail(self, body)

    SimulationWidget._draw_trail = counted_trail
    restores.append((SimulationWidget, '_draw_trail', orig_trail))

    orig_body = SimulationWidget._draw_body

    def counted_body(self, body, index):
        counts['body_draw_calls'] += 1
        return orig_body(self, body, index)

    SimulationWidget._draw_body = counted_body
    restores.append((SimulationWidget, '_draw_body', orig_body))

    def restore():
        for owner, attr, orig in restores:
            setattr(owner, attr, orig)

    return counts, restore


def _reset_counts(counts):
    counts['gl'].clear()
    counts['np']['calls'].clear()
    counts['np']['elems'].clear()
    counts['qt'].clear()
    counts['drawText_calls'] = 0
    counts['drawText_time_s'] = 0.0
    counts['fillRect_calls'] = 0
    counts['drawLine_calls'] = 0
    counts['trail_sample_calls'] = 0
    counts['trail_sample_in'] = 0
    counts['trail_sample_out'] = 0
    counts['trail_points'] = 0
    counts['body_draw_calls'] = 0


def _run_count_pass(window, app, scene, args, cpu_profiler, counts, frame_counts,
                    restore):
    rows = []
    try:
        for speed in args.speeds:
            _load_nine_body(window, scene, speed)
            _spin(window, app, args.warmup)
            _reset_counts(counts)
            cpu_profiler.clear()
            stats = _measure_frame(window, app, frame_counts, args.count_duration)
            if stats is None:
                continue
            paints = max(1, stats['paintgl'])
            n = max(1, stats['frames'])
            c = counts
            rows.append({
                'speed': speed,
                'paints': stats['paintgl'],
                'frames': stats['frames'],
                'update_calls_per_s': stats['fps_update'],
                'paintgl_calls_per_s': stats['fps_paintgl'],
                'paint_events_per_s': (
                    cpu_profiler.counts.get('paint_calls', 0) / stats['elapsed']
                ),
                'paints_per_frame': stats['paints_per_frame'],
                'gl_calls_per_paint': sum(c['gl'].values()) / paints,
                'gl_vertex_per_paint': (
                    c['gl'].get('glVertex2f', 0)
                    + c['gl'].get('glColor4f', 0)
                ) / paints,
                'gl_begin_end': (
                    c['gl'].get('glBegin', 0) + c['gl'].get('glEnd', 0)
                ) / paints,
                'gl_vbo_vao_shader_per_paint': sum(
                    c['gl'].get(k, 0) for k in (
                        'glBindBuffer', 'glBufferData', 'glBufferSubData',
                        'glGenBuffers', 'glDeleteBuffers', 'glGenVertexArrays',
                        'glCreateShader', 'glCreateProgram', 'glUseProgram',
                        'glGenTextures', 'glUniform1f', 'glUniform4f',
                    )
                ) / paints,
                'np_calls_per_paint': sum(c['np']['calls'].values()) / paints,
                'np_elems_per_paint': sum(c['np']['elems'].values()) / paints,
                'qt_objects_per_paint': sum(c['qt'].values()) / paints,
                'qcolor_per_paint': c['qt'].get('QColor', 0) / paints,
                'qpen_per_paint': c['qt'].get('QPen', 0) / paints,
                'qfont_per_paint': c['qt'].get('QFont', 0) / paints,
                'qpointf_per_paint': c['qt'].get('QPointF', 0) / paints,
                'qbrush_per_paint': c['qt'].get('QBrush', 0) / paints,
                'drawtext_per_paint': c['drawText_calls'] / paints,
                'drawtext_ms_per_paint': c['drawText_time_s'] * 1000.0 / paints,
                'fillrect_per_paint': c['fillRect_calls'] / paints,
                'drawline_per_paint': c['drawLine_calls'] / paints,
                'trail_sample_calls_per_paint': c['trail_sample_calls'] / paints,
                'trail_sample_out_per_paint': c['trail_sample_out'] / paints,
                'trail_points_per_paint': c['trail_points'] / paints,
                'body_draws_per_paint': c['body_draw_calls'] / paints,
                'numpy_scalar_per_frame': (
                    cpu_profiler.counts.get('numpy_scalar_access', 0) / n
                ),
                'trail_list_copy_per_frame': (
                    cpu_profiler.counts.get('trail_list_copy', 0) / n
                ),
            })
    finally:
        restore()
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write_csv(timing_rows, count_rows):
    out = ROOT / 'logs' / 'render_pipeline_profile.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with open(out, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['section'] + [
                'speed', 'round', 'paints', 'frames',
                'period_avg_ms', 'period_p95_ms',
                'physics_ms', 'ui_ms', 'qt_dispatch_ms', 'paintgl_cpu_ms',
                'swap_submit_ms', 'idle_ms', 'busy_fraction',
                'paints_per_frame', 'fps_paintgl', 'fps_update',
                'ph_paintgl_total', 'ph_gl_clear', 'ph_camera',
                'ph_state_prepare', 'ph_body_prepare', 'ph_trail_prepare',
                'ph_buffer_upload', 'ph_draw_call', 'ph_qpainter',
                'ph_overlay', 'ph_other',
                'ph_body_pos_conv', 'ph_body_radius_conv',
                'ph_body_ndc', 'ph_body_color_conv', 'ph_body_draw',
                'ph_trail_history_read', 'ph_trail_sample',
                'ph_trail_numpy_convert', 'ph_trail_vertex_gen',
                'ph_trail_draw', 'ph_qpainter_begin', 'ph_qpainter_scale_bar',
                'ph_qpainter_overlay', 'ph_qpainter_overlay_recompute',
                'ph_qpainter_overlay_measure', 'ph_qpainter_overlay_draw',
                'ph_qpainter_end', 'ph_state_read', 'ph_paint_event_total',
            ])
        for r in timing_rows:
            keys = [
                'speed', 'round', 'paints', 'frames',
                'period_avg', 'period_p95', 'physics', 'ui', 'qt_dispatch',
                'paintgl_cpu', 'swap_submit', 'idle', 'busy_fraction',
                'paints_per_frame', 'fps_paintgl', 'fps_update',
                'ph_paintgl_total', 'ph_gl_clear', 'ph_camera',
                'ph_state_prepare', 'ph_body_prepare', 'ph_trail_prepare',
                'ph_buffer_upload', 'ph_draw_call', 'ph_qpainter',
                'ph_overlay', 'ph_other',
                'ph_body_pos_conv', 'ph_body_radius_conv',
                'ph_body_ndc', 'ph_body_color_conv', 'ph_body_draw',
                'ph_trail_history_read', 'ph_trail_sample',
                'ph_trail_numpy_convert', 'ph_trail_vertex_gen',
                'ph_trail_draw', 'ph_qpainter_begin', 'ph_qpainter_scale_bar',
                'ph_qpainter_overlay', 'ph_qpainter_overlay_recompute',
                'ph_qpainter_overlay_measure', 'ph_qpainter_overlay_draw',
                'ph_qpainter_end', 'ph_state_read', 'ph_paint_event_total',
            ]
            w.writerow(['timing'] + [r.get(k, '') for k in keys])
        w.writerow([])
        w.writerow(['counts'] + [
            'speed', 'paints', 'frames', 'update_calls_per_s',
            'paintgl_calls_per_s', 'paint_events_per_s', 'paints_per_frame',
            'gl_calls_per_paint', 'gl_vertex_per_paint', 'gl_begin_end',
            'gl_vbo_vao_shader_per_paint', 'np_calls_per_paint',
            'np_elems_per_paint', 'qt_objects_per_paint', 'qcolor_per_paint',
            'qpen_per_paint', 'qfont_per_paint', 'qpointf_per_paint',
            'qbrush_per_paint', 'drawtext_per_paint',
            'drawtext_ms_per_paint', 'fillrect_per_paint',
            'drawline_per_paint', 'trail_sample_calls_per_paint',
            'trail_sample_out_per_paint', 'trail_points_per_paint',
            'body_draws_per_paint', 'numpy_scalar_per_frame',
            'trail_list_copy_per_frame',
        ])
        for r in count_rows:
            w.writerow(['counts'] + [r.get(k, '') for k in [
                'speed', 'paints', 'frames', 'update_calls_per_s',
                'paintgl_calls_per_s', 'paint_events_per_s',
                'paints_per_frame', 'gl_calls_per_paint',
                'gl_vertex_per_paint', 'gl_begin_end',
                'gl_vbo_vao_shader_per_paint', 'np_calls_per_paint',
                'np_elems_per_paint', 'qt_objects_per_paint',
                'qcolor_per_paint', 'qpen_per_paint', 'qfont_per_paint',
                'qpointf_per_paint', 'qbrush_per_paint',
                'drawtext_per_paint', 'drawtext_ms_per_paint',
                'fillrect_per_paint', 'drawline_per_paint',
                'trail_sample_calls_per_paint',
                'trail_sample_out_per_paint', 'trail_points_per_paint',
                'body_draws_per_paint', 'numpy_scalar_per_frame',
                'trail_list_copy_per_frame',
            ]])
    print(f"CSV -> {out}")


def _print_tables(timing_rows, count_rows):
    print()
    print('=== Frame decomposition (ms/frame) ===')
    print(
        f"{'x':>4} {'period':>8} {'Qt':>7} {'paintGL':>8} {'swap+sub':>9} "
        f"{'physics':>8} {'ui':>6} {'idle':>7} {'busy%':>6}"
    )
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(r[key] for r in rows)
        print(
            f"{speed:>4g} {med('period_avg'):8.2f} {med('qt_dispatch'):7.2f} "
            f"{med('paintgl_cpu'):8.2f} {med('swap_submit'):9.2f} "
            f"{med('physics'):8.2f} {med('ui'):6.2f} {med('idle'):7.2f} "
            f"{med('busy_fraction') * 100.0:6.1f}"
        )

    print()
    print('=== paintGL breakdown (ms/paint) ===')
    print(
        f"{'x':>4} {'paintGL':>8} {'clear':>7} {'camera':>7} {'state':>7} "
        f"{'bodyPrep':>9} {'trailPrep':>10} {'bufUp':>6} {'drawCall':>9} "
        f"{'QPainter':>8} {'overlay':>8} {'swap':>6} {'other':>7}"
    )
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(r.get(f'ph_{key}', 0.0) for r in rows)
        swap_paint = statistics.median(
            max(0.0, r['ph_paint_event_total'] - r['ph_paintgl_total'])
            for r in rows
        )
        print(
            f"{speed:>4g} {med('paintgl_total'):8.3f} {med('gl_clear'):7.3f} "
            f"{med('camera'):7.3f} {med('state_prepare'):7.3f} "
            f"{med('body_prepare'):9.3f} {med('trail_prepare'):10.3f} "
            f"{med('buffer_upload'):6.1f} {med('draw_call'):9.3f} "
            f"{med('qpainter'):8.3f} {med('overlay'):8.3f} "
            f"{swap_paint:6.3f} {med('other'):7.3f}"
        )

    print()
    print('=== fine paintGL phases (ms/paint) ===')
    fine = [
        'gl_clear', 'state_read', 'body_pos_conv', 'body_radius_conv',
        'body_ndc', 'body_color_conv', 'body_draw', 'trail_history_read',
        'trail_sample', 'trail_numpy_convert', 'trail_vertex_gen',
        'trail_draw', 'qpainter_begin', 'qpainter_scale_bar',
        'qpainter_overlay', 'qpainter_overlay_recompute',
        'qpainter_overlay_measure', 'qpainter_overlay_draw', 'qpainter_end',
    ]
    print(f"{'x':>4} " + ' '.join(f'{name[:11]:>11}' for name in fine))
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(r.get(f'ph_{key}', 0.0) for r in rows)
        print(f"{speed:>4g} " + ' '.join(f'{med(k):11.3f}' for k in fine))

    if count_rows:
        print()
        print('=== calls / allocations per paint ===')
        print(
            f"{'x':>4} {'glCalls':>9} {'glVtx+Clr':>11} {'npCalls':>9} "
            f"{'npElems':>9} {'QtObj':>7} {'QColor':>7} {'QPen':>6} "
            f"{'QFont':>6} {'drawText':>9} {'fillRect':>9} {'trailPts':>9} "
            f"{'bodyDraw':>9}"
        )
        for r in count_rows:
            print(
                f"{r['speed']:>4g} {r['gl_calls_per_paint']:9.0f} "
                f"{r['gl_vertex_per_paint']:11.0f} "
                f"{r['np_calls_per_paint']:9.1f} "
                f"{r['np_elems_per_paint']:9.0f} "
                f"{r['qt_objects_per_paint']:7.1f} "
                f"{r['qcolor_per_paint']:7.1f} {r['qpen_per_paint']:6.1f} "
                f"{r['qfont_per_paint']:6.1f} {r['drawtext_per_paint']:9.1f} "
                f"{r['fillrect_per_paint']:9.1f} "
                f"{r['trail_points_per_paint']:9.0f} "
                f"{r['body_draws_per_paint']:9.0f}"
            )
        print()
        print('=== frequencies / sec ===')
        print(
            f"{'x':>4} {'update':>8} {'paintGL':>8} {'paintEvt':>9} "
            f"{'paints/frame':>12}"
        )
        for r in count_rows:
            print(
                f"{r['speed']:>4g} {r['update_calls_per_s']:8.1f} "
                f"{r['paintgl_calls_per_s']:8.1f} "
                f"{r['paint_events_per_s']:9.1f} "
                f"{r['paints_per_frame']:12.2f}"
            )
        print()
        print('=== VBO/VAO/shader/texture allocations per paint (render path) ===')
        for r in count_rows:
            print(
                f"{r['speed']:>4g} vbo_vao_shader={r['gl_vbo_vao_shader_per_paint']:g}"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speeds', default='0.1,1,2,5,10')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--warmup', type=float, default=2.0)
    parser.add_argument('--duration', type=float, default=6.0)
    parser.add_argument('--count-duration', type=float, default=4.0)
    parser.add_argument('--scene', default='scenes/solar_system.json')
    args = parser.parse_args()
    args.speeds = [float(s) for s in args.speeds.split(',') if s.strip()]

    os.environ['PERF_LOG'] = '0'
    # Pure CPU-side run: no glFinish, no GL timer query.
    os.environ['GL_GPU_PROFILING'] = 'none'

    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    from ui.profiler import ProfilingApplication
    from ui.simulation_widget import CpuPipelineProfiler

    _orig_notify = ProfilingApplication.notify

    def _busy_notify(self, receiver, event):
        if not _BUSY['active']:
            return _orig_notify(self, receiver, event)
        if _BUSY['depth'] == 0:
            _BUSY['t0'] = time.perf_counter()
        _BUSY['depth'] += 1
        try:
            return _orig_notify(self, receiver, event)
        finally:
            _BUSY['depth'] -= 1
            if _BUSY['depth'] == 0:
                _BUSY['total'] += time.perf_counter() - _BUSY['t0']

    ProfilingApplication.notify = _busy_notify

    app = ProfilingApplication(sys.argv)
    app.setStyle('Fusion')
    scene = Path(args.scene)
    if not scene.is_absolute():
        scene = ROOT / scene

    frame_counts, originals = _install_frame_counters()

    window = MainWindow()
    window.resize(1400, 900)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()
    _spin(window, app, 1.0)

    cpu_profiler = CpuPipelineProfiler()
    window.sim_widget.set_cpu_profiler(cpu_profiler)

    try:
        timing_rows = _run_timing_pass(
            window, app, scene, args, cpu_profiler, frame_counts
        )
        count_rows = []
        call_counts, restore = _install_call_counters()
        count_rows = _run_count_pass(
            window, app, scene, args, cpu_profiler, call_counts,
            frame_counts, restore,
        )
    finally:
        _restore_frame_counters(originals)
        window.sim_widget.set_cpu_profiler(None)

    window.close()
    _write_csv(timing_rows, count_rows)
    _print_tables(timing_rows, count_rows)
    app.quit()


if __name__ == '__main__':
    main()
