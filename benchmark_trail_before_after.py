"""
Trail 优化前后完整性能分析（只测量，不优化、不改生产代码）

对比模式（同一二进制内的 A/B 开关）：
    before : old_trail_renderer=True  （旧逐顶点 immediate mode trail 绘制）
    after  : old_trail_renderer=False （新 VBO：builder + glBufferSubData + 每 body 一次 glDrawArrays）

场景：scenes/solar_system.json 太阳系九体（加载后移除 Moon）
倍率：0.1x / 1x / 2x / 5x / 10x
GPU：GL_GPU_PROFILING=timer（非阻塞 GL timer query，延迟读回）

拆分（ms）：
    Frame total / Qt dispatch / paintGL total / physics /
    trail(prepare / upload / draw / total) / body(prepare / draw) /
    QPainter overlay / GPU timer / GPU wait / swap+submit(CPU 代理) /
    GL calls per paint

用法：
    python benchmark_trail_before_after.py
"""

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _drain2(history, seen, buckets):
    """Move newly closed FrameProfiler frames into per-metric buckets (含 gpu_time)。"""
    for f in list(history):
        if id(f) in seen:
            continue
        seen[id(f)] = f
        if f['period'] <= 0.0:
            continue
        render_wall = f['render'] * 1000.0
        buckets['period'].append(f['period'] * 1000.0)
        buckets['physics'].append(f['physics'] * 1000.0)
        buckets['ui'].append(f['ui'] * 1000.0)
        buckets['gpu_wait'].append(min(f['gpu_sync'] * 1000.0, render_wall))
        buckets['gpu_time'].append(f['gpu_time'] * 1000.0)


def _p95(values):
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    return s[int(round(0.95 * (len(s) - 1)))]


def _measure(window, app, frame_counts, duration, sampler_ms=150):
    """Accumulate profiler frames + notify busy + paintGL counts for `duration` seconds."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from benchmark_render_pipeline import _BUSY, _start_visibility_keeper

    prof = window.profiler
    seen = {id(f): f for f in list(prof.history)}
    buckets = {k: [] for k in ('period', 'physics', 'ui', 'gpu_wait', 'gpu_time')}

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
        _drain2(prof.history, seen, buckets)
        if time.perf_counter() >= end:
            sampler.stop()
            loop.quit()

    sampler.timeout.connect(_sample)
    sampler.start()
    keeper = _start_visibility_keeper(window, loop)
    QTimer.singleShot(int((duration + 1.0) * 1000), loop.quit)
    loop.exec()
    keeper.stop()
    _drain2(prof.history, seen, buckets)
    _BUSY['active'] = False
    elapsed = time.perf_counter() - t0

    n = len(buckets['period'])
    if n == 0:
        return None
    return {
        'frames': n,
        'elapsed': elapsed,
        'paintgl': frame_counts['paintgl'],
        'period_avg': statistics.fmean(buckets['period']),
        'period_p95': _p95(buckets['period']),
        'physics_ms': statistics.fmean(buckets['physics']),
        'ui_ms': statistics.fmean(buckets['ui']),
        'gpu_wait_ms': statistics.fmean(buckets['gpu_wait']),
        'gpu_time_ms': statistics.fmean(buckets['gpu_time']),
        'busy_total': _BUSY['total'],
    }


# 新旧路径的 trail 三阶段 phase 键映射
_TRAIL_STAGES = {
    'before': ('trail_prepare', 'trail_transform', 'trail_upload_draw'),
    'after': ('trail_prepare', 'trail_upload', 'trail_draw'),
}


def _install_gl_counters():
    """轻量 GL 调用计数（sw.gl 与 tr.gl 是同一模块对象，两条路径都覆盖）。"""
    import ui.simulation_widget as sw

    counts = {}
    restores = []
    for name in (
        'glDrawArrays', 'glBufferSubData', 'glBufferData', 'glBindBuffer',
        'glGenBuffers', 'glDeleteBuffers', 'glBegin', 'glEnd',
        'glVertex2f', 'glColor4f', 'glLineWidth',
        'glVertexPointer', 'glColorPointer',
    ):
        if not hasattr(sw.gl, name):
            continue
        orig = getattr(sw.gl, name)

        def make_wrapper(orig_fn, fn_name):
            def wrapper(*a, **k):
                counts[fn_name] = counts.get(fn_name, 0) + 1
                return orig_fn(*a, **k)

            return wrapper

        setattr(sw.gl, name, make_wrapper(orig, name))
        restores.append((sw.gl, name, orig))

    def reset():
        counts.clear()

    def restore():
        for owner, attr, orig in restores:
            setattr(owner, attr, orig)

    return counts, reset, restore


def _run_cell(window, app, scene, speed, mode, args, frame_counts,
              phase_timer, cpu_profiler):
    from benchmark_render_pipeline import _spin, _load_nine_body

    widget = window.sim_widget
    widget.old_trail_renderer = (mode == 'before')
    _load_nine_body(window, scene, speed)
    _spin(window, app, args.warmup)

    phase_timer.clear()
    cpu_profiler.clear()
    stats = _measure(window, app, frame_counts, args.duration)
    if stats is None:
        return None

    n = max(1, stats['frames'])
    paints = max(1, stats['paintgl'])
    ph = phase_timer.phases
    paint_event_ms = cpu_profiler.phases.get('paint_event_total', 0.0) * 1000.0
    paintgl_ms = cpu_profiler.phases.get('paintgl_total', 0.0) * 1000.0
    qt_dispatch = max(
        0.0, stats['busy_total'] * 1000.0
        - stats['physics_ms'] * n - stats['ui_ms'] * n - paint_event_ms
    ) / n
    swap_submit = max(0.0, paint_event_ms - paintgl_ms) / n

    keys = _TRAIL_STAGES[mode]
    t_prep = ph.get(keys[0], 0.0) * 1000.0 / paints
    t_up = ph.get(keys[1], 0.0) * 1000.0 / paints
    t_draw = ph.get(keys[2], 0.0) * 1000.0 / paints

    qp_keys = ('qpainter_begin', 'scale_bar', 'overlay', 'qpainter_end')
    return {
        'mode': mode, 'speed': speed,
        'frames': stats['frames'], 'paints': stats['paintgl'],
        'frame_total': stats['period_avg'],
        'frame_p95': stats['period_p95'],
        'qt_dispatch': qt_dispatch,
        'paintgl_total': paintgl_ms / n,
        'physics': stats['physics_ms'],
        'ui': stats['ui_ms'],
        'trail_prepare': t_prep,
        'trail_upload': t_up,
        'trail_draw': t_draw,
        'trail_total': t_prep + t_up + t_draw,
        'body_prepare': ph.get('body_prepare', 0.0) * 1000.0 / paints,
        'body_draw': ph.get('body_upload_draw', 0.0) * 1000.0 / paints,
        'overlay': ph.get('overlay', 0.0) * 1000.0 / paints,
        'qpainter_total': sum(ph.get(k, 0.0) for k in qp_keys) * 1000.0 / paints,
        'gpu_time': stats['gpu_time_ms'],
        'gpu_wait': stats['gpu_wait_ms'],
        'swap_submit': swap_submit,
    }


def _run_count_cell(window, app, scene, speed, mode, args, frame_counts,
                    gl_counts, gl_reset):
    """仅计数（GL 包装器不在计时阶段安装，避免污染计时）。"""
    from benchmark_render_pipeline import _spin, _load_nine_body

    widget = window.sim_widget
    widget.old_trail_renderer = (mode == 'before')
    _load_nine_body(window, scene, speed)
    _spin(window, app, 0.5)
    gl_reset()
    stats = _measure(window, app, frame_counts, 2.0)
    if stats is None:
        return None
    paints = max(1, stats['paintgl'])
    return {
        'mode': mode, 'speed': speed,
        'gl_calls_per_paint': sum(gl_counts.values()) / paints,
    }


def _median(cells, key):
    vals = [c[key] for c in cells]
    return statistics.median(vals)


def _print_speed_table(cells, speed):
    """cells 需包含 gl_calls_per_paint（计数阶段补充）。"""
    before = [c for c in cells if c['mode'] == 'before' and c['speed'] == speed]
    after = [c for c in cells if c['mode'] == 'after' and c['speed'] == speed]
    if not before or not after:
        return
    b = {k: statistics.median(c[k] for c in before) for k in before[0]}
    a = {k: statistics.median(c[k] for c in after) for k in after[0]}
    rows = [
        ('Frame total', 'frame_total'),
        ('Qt dispatch', 'qt_dispatch'),
        ('paintGL total', 'paintgl_total'),
        ('physics', 'physics'),
        ('trail total', 'trail_total'),
        ('  trail prepare', 'trail_prepare'),
        ('  trail upload', 'trail_upload'),
        ('  trail draw', 'trail_draw'),
        ('body prepare', 'body_prepare'),
        ('body draw', 'body_draw'),
        ('QPainter overlay', 'overlay'),
        ('GPU timer', 'gpu_time'),
        ('GPU wait', 'gpu_wait'),
        ('swap+submit(CPU)', 'swap_submit'),
        ('GL calls/paint', 'gl_calls_per_paint'),
    ]
    print(f'--- {speed:g}x ---')
    print(f"{'module':<20} {'before(ms)':>11} {'after(ms)':>11} {'speedup':>9}")
    for label, key in rows:
        bv = b[key]
        av = a[key]
        spd = (bv / av) if av > 0 else float('inf')
        print(f"{label:<20} {bv:>11.3f} {av:>11.3f} {spd:>8.2f}x")
    print()


def _print_summary_table(cells):
    """跨倍率取中位数：模块 | before(ms) | after(ms) | speedup。"""
    speeds = sorted({c['speed'] for c in cells})
    rows = [
        ('Frame total', 'frame_total'),
        ('Qt dispatch', 'qt_dispatch'),
        ('paintGL total', 'paintgl_total'),
        ('physics', 'physics'),
        ('trail total', 'trail_total'),
        ('  trail prepare', 'trail_prepare'),
        ('  trail upload', 'trail_upload'),
        ('  trail draw', 'trail_draw'),
        ('body prepare', 'body_prepare'),
        ('body draw', 'body_draw'),
        ('QPainter overlay', 'overlay'),
        ('GPU timer', 'gpu_time'),
        ('GPU wait', 'gpu_wait'),
        ('swap+submit(CPU)', 'swap_submit'),
        ('GL calls/paint', 'gl_calls_per_paint'),
    ]
    print('=== 优化前 vs 优化后（各倍率中位数）===')
    print(f"{'模块':<20} {'before(ms)':>11} {'after(ms)':>11} {'speedup':>9}")
    for label, key in rows:
        bv = _median([c for c in cells if c['mode'] == 'before'], key)
        av = _median([c for c in cells if c['mode'] == 'after'], key)
        spd = (bv / av) if av > 0 else float('inf')
        print(f"{label:<20} {bv:>11.3f} {av:>11.3f} {spd:>8.2f}x")
    print()
    # trail total 各倍率明细
    print('=== trail total 各倍率（ms/paint）===')
    print(f"{'x':>5} {'before':>10} {'after':>10} {'speedup':>9}")
    for speed in speeds:
        bv = _median([c for c in cells if c['mode'] == 'before' and c['speed'] == speed], 'trail_total')
        av = _median([c for c in cells if c['mode'] == 'after' and c['speed'] == speed], 'trail_total')
        spd = (bv / av) if av > 0 else float('inf')
        print(f"{speed:>5g} {bv:>10.3f} {av:>10.3f} {spd:>8.2f}x")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speeds', default='0.1,1,2,5,10')
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--warmup', type=float, default=1.5)
    parser.add_argument('--duration', type=float, default=5.0)
    parser.add_argument('--scene', default='scenes/solar_system.json')
    parser.add_argument('--only', choices=('before', 'after'))
    args = parser.parse_args()
    speeds = [float(s) for s in args.speeds.split(',') if s.strip()]
    modes = ['before', 'after'] if not args.only else [args.only]

    os.environ['PERF_LOG'] = '0'
    os.environ['GL_GPU_PROFILING'] = 'timer'

    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    from ui.profiler import ProfilingApplication
    from ui.simulation_widget import CpuPipelineProfiler, RenderPhaseTimer
    from benchmark_render_pipeline import (
        _BUSY, _spin, _install_frame_counters, _restore_frame_counters,
    )

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

    phase_timer = RenderPhaseTimer()
    cpu_profiler = CpuPipelineProfiler()
    window.sim_widget.set_render_phase_timer(phase_timer)
    window.sim_widget.set_cpu_profiler(cpu_profiler)

    cells = []
    gl_restore = lambda: None
    try:
        for mode in modes:
            for speed in speeds:
                for rnd in range(args.rounds):
                    cell = _run_cell(
                        window, app, scene, speed, mode, args,
                        frame_counts, phase_timer, cpu_profiler,
                    )
                    if cell is not None:
                        cell['gl_calls_per_paint'] = float('nan')
                        cells.append(cell)
                        print(
                            f'[done] mode={mode} speed={speed:g} '
                            f'round={rnd} frames={cell["frames"]} '
                            f'paints={cell["paints"]} trail={cell["trail_total"]:.3f}ms',
                            flush=True,
                        )
        # 计数阶段（GL 包装器此刻才安装，避免污染上面的计时数据）
        gl_counts, gl_reset, gl_restore = _install_gl_counters()
        for mode in modes:
            for speed in speeds:
                gl_reset()
                ccell = _run_count_cell(
                    window, app, scene, speed, mode, args,
                    frame_counts, gl_counts, gl_reset,
                )
                if ccell is not None:
                    for cell in cells:
                        if (cell['mode'], cell['speed']) == (mode, speed):
                            cell['gl_calls_per_paint'] = ccell['gl_calls_per_paint']
    finally:
        window.sim_widget.set_render_phase_timer(None)
        window.sim_widget.set_cpu_profiler(None)
        _restore_frame_counters(originals)
        gl_restore()
        window.close()
    app.quit()

    if cells:
        for speed in speeds:
            _print_speed_table(cells, speed)
        _print_summary_table(cells)
    else:
        print('no measurements collected')


if __name__ == '__main__':
    main()
