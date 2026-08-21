"""
CPU-side Renderer 深度 profiling（本阶段只测量，不做任何优化、不改视觉效果）。

Pass 1（阶段计时 + 帧分解 + 频率）：
    以 GL_GPU_PROFILING=timer 模式运行（无 glFinish，非阻塞 GPU 计时），
    挂接 SimulationWidget 的 RenderPhaseTimer，逐阶段累计 paintGL 内部耗时：
        gl_clear / trail_prepare / trail_transform / trail_upload_draw /
        body_prepare / body_upload_draw / qpainter_begin / scale_bar /
        overlay / qpainter_end / other / paintgl_total
    同时把一帧拆成：Physics / Render CPU / GPU execution / GPU wait /
    Qt event dispatch / idle(frame limiter + scheduling slack) / 帧周期。
    并统计 update() 请求、paint 事件、paintGL 调用频率（检查重复绘制）。

Pass 2（调用/分配计数）：
    包装 gl* 调用、numpy 创建函数、Qt 构造器与轨迹采样，
    统计每帧的 Python->GL 调用数、numpy 转换/拷贝、Qt 对象创建、list 拷贝。

场景：scenes/solar_system.json 太阳系九体（加载后移除 Moon，不改任何文件）。

用法：
    python benchmark_render_deep.py
    python benchmark_render_deep.py --speeds 0.1,1,2,5,10 --rounds 2
        --warmup 2 --duration 6 --count-speeds 0.1,1,5

结果写入 logs/render_deep_profile.csv（追加）。
"""

import argparse
import csv
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 窗口级主线程 busy 累计（类级包装 ProfilingApplication.notify）。
# 只累计最外层 notify 跨度：Qt 事件处理内部会嵌套发送事件，避免重复计时。
_BUSY = {'total': 0.0, 'active': False, 'depth': 0, 't0': 0.0}


def _spin(window, app, seconds: float) -> None:
    """QEventLoop 泵事件（保持平台 paint 事件正常派发）。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    keeper = _start_visibility_keeper(window, loop)
    loop.exec()
    keeper.stop()


def _start_visibility_keeper(window, loop, interval_ms: int = 250):
    """远程桌面/前台锁定可能最小化测试窗口；定时恢复以保持渲染。"""
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
    """加载场景 -> 移除 Moon（九体）-> 设置倍率。"""
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
    """类级包装：统计 render tick（update 请求）与 paintGL 调用。"""
    from ui.simulation_widget import SimulationWidget

    counts = {'render_ticks': 0, 'paintgl': 0}
    originals = {}

    def _wrap(attr):
        orig = getattr(SimulationWidget, attr)
        originals[attr] = orig

        if attr == 'paintGL':
            def w(self, *a, **k):
                counts['paintgl'] += 1
                return orig(self, *a, **k)
        else:  # _on_render_tick
            def w(self, *a, **k):
                counts['render_ticks'] += 1
                return orig(self, *a, **k)

        setattr(SimulationWidget, attr, w)

    for attr in ('paintGL', '_on_render_tick'):
        _wrap(attr)
    return counts, originals


def _restore_frame_counters(originals):
    from ui.simulation_widget import SimulationWidget
    for attr, orig in originals.items():
        setattr(SimulationWidget, attr, orig)


def _drain(history, seen, buckets):
    """把新关闭的 profiler 帧加入统计桶（去重，强引用防 id 复用）。"""
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
        buckets['render_wall'].append(render_wall)
        buckets['gpu_wait'].append(gpu_wait)
        buckets['gpu_time'].append(f.get('gpu_time', 0.0) * 1000.0)
        buckets['ui'].append(ui)
        # Qt dispatch = notify 总时长 - 已单独计时的 physics/ui/render
        render_cpu = max(0.0, render_wall - gpu_wait)
        buckets['render_cpu'].append(render_cpu)


def _measure_frame(window, app, frame_counts, duration, sampler_ms=150):
    """测量窗口：累计 profiler 帧 + 频率计数，返回统计 dict。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    prof = window.profiler
    seen = {id(f): f for f in list(prof.history)}
    buckets = {k: [] for k in (
        'period', 'physics', 'render_wall', 'gpu_wait', 'gpu_time',
        'ui', 'render_cpu',
    )}

    frame_counts['render_ticks'] = 0
    frame_counts['paintgl'] = 0
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
    # 窗口级总量：避免 qt_events 的跨帧归因偏差
    busy_total = _BUSY['total']
    physics_total = sum(buckets['physics'])
    render_total = sum(buckets['render_wall'])
    ui_total = sum(buckets['ui'])
    qt_overhead_total = max(0.0, busy_total - physics_total - render_total - ui_total)
    idle_total = max(0.0, elapsed - busy_total)
    return {
        'frames': n,
        'elapsed': elapsed,
        'paintgl': frame_counts['paintgl'],
        'render_ticks': frame_counts['render_ticks'],
        'period_avg': statistics.fmean(buckets['period']),
        'period_p95': _p95(buckets['period']),
        'physics': statistics.fmean(buckets['physics']),
        'render_wall': statistics.fmean(buckets['render_wall']),
        'render_cpu': statistics.fmean(buckets['render_cpu']),
        'gpu_wait': statistics.fmean(buckets['gpu_wait']),
        'gpu_time': statistics.fmean(buckets['gpu_time']),
        'ui': statistics.fmean(buckets['ui']),
        'qt_overhead': qt_overhead_total / n,
        'idle': idle_total / n,
        'busy_fraction': busy_total / elapsed,
        'paints_per_frame': frame_counts['paintgl'] / n,
        'fps_paintgl': frame_counts['paintgl'] / elapsed,
        'fps_update': frame_counts['render_ticks'] / elapsed,
    }


def _p95(values):
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    return s[int(round(0.95 * (len(s) - 1)))]


def _run_timing_pass(window, app, scene, args, phase_timer, frame_counts):
    """Pass 1：逐速度测量阶段耗时 + 帧分解 + 频率。"""
    rows = []
    for speed in args.speeds:
        for _round in range(args.rounds):
            _load_nine_body(window, scene, speed)
            _spin(window, app, args.warmup)
            phase_timer.clear()
            stats = _measure_frame(window, app, frame_counts, args.duration)
            if stats is None:
                continue
            paints = stats['paintgl']
            row = {
                'speed': speed, 'round': _round,
                'paints': paints, 'frames': stats['frames'],
            }
            for name, ms in phase_timer.phases.items():
                row[f'ph_{name}'] = (ms * 1000.0 / paints) if paints else 0.0
            for key in (
                'period_avg', 'period_p95', 'physics', 'render_wall',
                'render_cpu', 'gpu_wait', 'gpu_time', 'ui', 'qt_overhead',
                'idle', 'busy_fraction', 'paints_per_frame', 'fps_paintgl',
                'fps_update',
            ):
                row[key] = stats[key]
            rows.append(row)
    return rows


def _install_call_counters():
    """
    Pass 2：包装 gl*/numpy/Qt 构造/轨迹采样，统计每帧调用与对象创建。
    返回 (counts, restore)。
    """
    from ui import simulation_widget as sw
    counts = {
        'gl': {},
        'np': {'calls': {}, 'elems': {}},
        'qt': {},
        'trail_sample_calls': 0,
        'trail_sample_in': 0,
        'trail_sample_out': 0,
        'trail_draw_calls': 0,
        'trail_points': 0,
        'body_draw_calls': 0,
    }
    restores = []

    for name in (
        'glClear', 'glColor4f', 'glVertex2f', 'glBegin', 'glEnd',
        'glLineWidth', 'glBeginQuery', 'glEndQuery',
    ):
        orig = getattr(sw.gl, name)

        def make_wrapper(orig_fn, fn_name):
            def wrapper(*a, **k):
                counts['gl'][fn_name] = counts['gl'].get(fn_name, 0) + 1
                return orig_fn(*a, **k)
            return wrapper

        setattr(sw.gl, name, make_wrapper(orig, name))
        restores.append((sw.gl, name, orig))

    # numpy 创建函数（仅统计渲染路径的 asarray/empty/linspace）
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

    # Qt 构造器
    for name in ('QColor', 'QPen', 'QFont'):
        orig = getattr(sw, name)

        def make_qtwrap(orig_fn, qt_name):
            def wrapper(*a, **k):
                counts['qt'][qt_name] = counts['qt'].get(qt_name, 0) + 1
                return orig_fn(*a, **k)
            return wrapper

        setattr(sw, name, make_qtwrap(orig, name))
        restores.append((sw, name, orig))

    # 轨迹采样与绘制（类级包装）
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
        counts['trail_draw_calls'] += 1
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


def _run_count_pass(window, app, scene, args, counts, frame_counts, restore):
    """Pass 2：统计每帧 gl 调用 / numpy 转换 / Qt 对象 / list 拷贝。"""
    rows = []
    try:
        for speed in args.count_speeds:
            _load_nine_body(window, scene, speed)
            _spin(window, app, args.warmup)
            _reset_counts(counts)
            stats = _measure_frame(window, app, frame_counts, args.duration)
            if stats is None:
                continue
            paints = max(1, stats['paintgl'])
            rows.append({
                'speed': speed,
                'paints': stats['paintgl'],
                'frames': stats['frames'],
                'gl_per_paint': sum(counts['gl'].values()) / paints,
                'gl_vertex_per_paint': (
                    counts['gl'].get('glVertex2f', 0)
                    + counts['gl'].get('glColor4f', 0)
                ) / paints,
                'gl_begin_end': (
                    counts['gl'].get('glBegin', 0)
                    + counts['gl'].get('glEnd', 0)
                ) / paints,
                'np_calls_per_paint': (
                    sum(counts['np']['calls'].values())
                ) / paints,
                'np_elems_per_paint': (
                    sum(counts['np']['elems'].values())
                ) / paints,
                'qt_objects_per_paint': (
                    sum(counts['qt'].values())
                ) / paints,
                'qcolor_per_paint': counts['qt'].get('QColor', 0) / paints,
                'qpen_per_paint': counts['qt'].get('QPen', 0) / paints,
                'qfont_per_paint': counts['qt'].get('QFont', 0) / paints,
                'trail_sample_calls_per_paint': (
                    counts['trail_sample_calls'] / paints
                ),
                'trail_sample_out_per_paint': (
                    counts['trail_sample_out'] / paints
                ),
                'trail_points_per_paint': counts['trail_points'] / paints,
                'body_draws_per_paint': counts['body_draw_calls'] / paints,
                'gl_clear_per_paint': counts['gl'].get('glClear', 0) / paints,
                'gl_query_per_paint': (
                    counts['gl'].get('glBeginQuery', 0)
                    + counts['gl'].get('glEndQuery', 0)
                ) / paints,
            })
    finally:
        restore()
    return rows


def _reset_counts(counts):
    counts['gl'].clear()
    counts['np']['calls'].clear()
    counts['np']['elems'].clear()
    counts['qt'].clear()
    counts['trail_sample_calls'] = 0
    counts['trail_sample_in'] = 0
    counts['trail_sample_out'] = 0
    counts['trail_draw_calls'] = 0
    counts['trail_points'] = 0
    counts['body_draw_calls'] = 0


def _write_csv(timing_rows, count_rows):
    out = ROOT / 'logs' / 'render_deep_profile.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with open(out, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['section'] + [
                'speed', 'round', 'paints', 'frames',
                'period_avg_ms', 'period_p95_ms', 'physics_ms',
                'render_wall_ms', 'render_cpu_ms', 'gpu_wait_ms',
                'gpu_time_ms', 'ui_ms', 'qt_overhead_ms', 'idle_ms',
                'busy_fraction', 'paints_per_frame', 'fps_paintgl',
                'fps_update',
                'ph_paintgl_total', 'ph_gl_clear', 'ph_trail_prepare',
                'ph_trail_transform', 'ph_trail_upload_draw',
                'ph_body_prepare', 'ph_body_upload_draw',
                'ph_qpainter_begin', 'ph_scale_bar', 'ph_overlay',
                'ph_qpainter_end', 'ph_other',
            ])
        for r in timing_rows:
            w.writerow(['timing'] + [
                r.get(k, '') for k in (
                    'speed', 'round', 'paints', 'frames',
                    'period_avg', 'period_p95', 'physics', 'render_wall',
                    'render_cpu', 'gpu_wait', 'gpu_time', 'ui',
                    'qt_overhead', 'idle', 'busy_fraction',
                    'paints_per_frame', 'fps_paintgl', 'fps_update',
                )
            ] + [
                r.get(k, '') for k in (
                    'ph_paintgl_total', 'ph_gl_clear', 'ph_trail_prepare',
                    'ph_trail_transform', 'ph_trail_upload_draw',
                    'ph_body_prepare', 'ph_body_upload_draw',
                    'ph_qpainter_begin', 'ph_scale_bar', 'ph_overlay',
                    'ph_qpainter_end', 'ph_other',
                )
            ])
        w.writerow([])
        w.writerow(['counts'] + ['speed', 'paints', 'frames',
                                 'gl_calls', 'gl_vertex', 'gl_begin_end',
                                 'np_calls', 'np_elems', 'qt_objects',
                                 'qcolor', 'qpen', 'qfont',
                                 'trail_samples', 'trail_sample_out',
                                 'trail_points', 'body_draws'])
        for r in count_rows:
            w.writerow(['counts'] + [
                r.get(k, '') for k in (
                    'speed', 'paints', 'frames',
                    'gl_per_paint', 'gl_vertex_per_paint', 'gl_begin_end',
                    'np_calls_per_paint', 'np_elems_per_paint',
                    'qt_objects_per_paint', 'qcolor_per_paint',
                    'qpen_per_paint', 'qfont_per_paint',
                    'trail_sample_calls_per_paint',
                    'trail_sample_out_per_paint',
                    'trail_points_per_paint', 'body_draws_per_paint',
                )
            ])
    print(f"CSV -> {out}")


def _print_tables(timing_rows, count_rows):
    print()
    print('=== 阶段耗时（每 paintGL，ms，两轮中位数）===')
    header = (
        f"{'x':>4} {'paintGL':>8} {'glclear':>8} {'trailPrep':>9} "
        f"{'trailXf':>8} {'trailDraw':>9} {'bodyPrep':>8} {'bodyDraw':>8} "
        f"{'QPainter':>8} {'scaleBar':>8} {'overlay':>8} {'other':>7} {'GPU':>6}"
    )
    print(header)
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(
            r.get(f'ph_{key}', 0.0) for r in rows
        )
        gpu_per_paint = statistics.median(
            r['gpu_time'] / max(1.0, r['paints_per_frame']) for r in rows
        )
        print(
            f"{speed:>4g} {med('paintgl_total'):8.3f} {med('gl_clear'):8.3f} "
            f"{med('trail_prepare'):9.3f} {med('trail_transform'):8.3f} "
            f"{med('trail_upload_draw'):9.3f} {med('body_prepare'):8.3f} "
            f"{med('body_upload_draw'):8.3f} "
            f"{med('qpainter_begin') + med('qpainter_end'):8.3f} "
            f"{med('scale_bar'):8.3f} {med('overlay'):8.3f} "
            f"{med('other'):7.3f} {gpu_per_paint:6.2f}"
        )

    print()
    print('=== 帧分解（ms，两轮中位数）===')
    print(
        f"{'x':>4} {'period':>8} {'physics':>8} {'renderCPU':>9} "
        f"{'gpuTime':>8} {'gpuWait':>8} {'ui':>6} {'qtOver':>7} {'idle':>7} {'busy%':>6} {'p95':>8}"
    )
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(r[key] for r in rows)
        print(
            f"{speed:>4g} {med('period_avg'):8.2f} {med('physics'):8.2f} "
            f"{med('render_cpu'):9.2f} {med('gpu_time'):8.2f} "
            f"{med('gpu_wait'):8.2f} {med('ui'):6.2f} "
            f"{med('qt_overhead'):7.2f} {med('idle'):7.2f} "
            f"{med('busy_fraction') * 100.0:6.1f} {med('period_p95'):8.2f}"
        )

    print()
    print('=== 频率（/sec）===')
    print(
        f"{'x':>4} {'paintGL':>8} {'update':>7} "
        f"{'paints/frame':>12} {'renderCPU/paint':>15}"
    )
    for speed in sorted({r['speed'] for r in timing_rows}):
        rows = [r for r in timing_rows if r['speed'] == speed]
        med = lambda key: statistics.median(r[key] for r in rows)
        render_cpu_per_paint = med('render_wall') / max(1.0, med('paints_per_frame'))
        print(
            f"{speed:>4g} {med('fps_paintgl'):8.2f} "
            f"{med('fps_update'):7.2f} "
            f"{med('paints_per_frame'):12.2f} {render_cpu_per_paint:15.3f}"
        )

    if count_rows:
        print()
        print('=== 每 paintGL 的调用/分配计数 ===')
        print(
            f"{'x':>4} {'glCalls':>8} {'glVertex+Color':>14} {'npCalls':>8} "
            f"{'npElems':>9} {'QtObj':>6} {'QColor':>7} {'QPen':>5} {'QFont':>6} "
            f"{'trailPts':>9} {'bodyDraw':>9}"
        )
        for r in count_rows:
            print(
                f"{r['speed']:>4g} {r['gl_per_paint']:8.0f} "
                f"{r['gl_vertex_per_paint']:14.0f} "
                f"{r['np_calls_per_paint']:8.1f} "
                f"{r['np_elems_per_paint']:9.0f} "
                f"{r['qt_objects_per_paint']:6.1f} "
                f"{r['qcolor_per_paint']:7.1f} {r['qpen_per_paint']:5.1f} "
                f"{r['qfont_per_paint']:6.1f} "
                f"{r['trail_points_per_paint']:9.0f} "
                f"{r['body_draws_per_paint']:9.0f}"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--speeds', default='0.1,1,2,5,10',
        help='阶段计时用倍率（默认 0.1,1,2,5,10）',
    )
    parser.add_argument(
        '--count-speeds', default='0.1,1,5',
        help='调用/分配计数用倍率（默认 0.1,1,5）',
    )
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--warmup', type=float, default=2.0)
    parser.add_argument('--duration', type=float, default=6.0)
    parser.add_argument('--scene', default='scenes/solar_system.json')
    args = parser.parse_args()
    args.speeds = [float(s) for s in args.speeds.split(',') if s.strip()]
    args.count_speeds = [float(s) for s in args.count_speeds.split(',') if s.strip()]

    os.environ['PERF_LOG'] = '0'
    os.environ['GL_GPU_PROFILING'] = 'timer'

    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    from ui.profiler import ProfilingApplication
    from ui.simulation_widget import RenderPhaseTimer

    # 类级包装 notify：累计主线程 busy（含 paint/physics/UI/所有 Qt 事件分发）
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

    # 帧计数器必须在 MainWindow 创建前安装：
    # start_animation 连接的是绑定方法，类级包装要早于连接。
    frame_counts, originals = _install_frame_counters()

    window = MainWindow()
    window.resize(1400, 900)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()
    _spin(window, app, 1.0)

    phase_timer = RenderPhaseTimer()
    window.sim_widget.set_render_phase_timer(phase_timer)

    try:
        timing_rows = _run_timing_pass(
            window, app, scene, args, phase_timer, frame_counts
        )
        call_counts, restore = _install_call_counters()
        count_rows = _run_count_pass(
            window, app, scene, args, call_counts, frame_counts, restore
        )
    finally:
        _restore_frame_counters(originals)
        window.sim_widget.set_render_phase_timer(None)

    window.close()
    _write_csv(timing_rows, count_rows)
    _print_tables(timing_rows, count_rows)
    app.quit()


if __name__ == '__main__':
    main()
