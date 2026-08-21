"""
A/B 性能测试：Renderer 的 glFinish 同步策略

同一绘制代码，仅 GPU 同步/计时方式不同：
    finish - 旧行为：paintGL 末尾 gl.glFinish()（CPU 强制等待 GPU）
    none   - 完全移除 glFinish（正常模式）
    timer  - GL_ARB_timer_query：测量 GPU 实际执行时间，延迟读回（非阻塞）

场景：scenes/solar_system.json 中的太阳系九体
（Sun + 八大行星；脚本加载后移除 Moon，不改动任何场景文件）。

每个 (模式, 倍率) 组合都会重新加载场景，保证轨迹/状态从同一初始条件开始。

用法：
    python benchmark_gl_sync.py
    python benchmark_gl_sync.py --modes none,finish --speeds 0.1,1,2,5,10
        --warmup 2.5 --duration 8 --scene scenes/solar_system.json

结果输出到 logs/gl_sync_ab_test.csv（追加）。
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run_app(args):
    # 关闭逐帧性能日志的控制台输出，保持基准输出干净
    os.environ['PERF_LOG'] = '0'
    os.environ['PERF_LOG_PATH'] = str(ROOT / 'logs' / 'gl_sync_ab_test.log')

    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    from ui.profiler import ProfilingApplication
    from ui.simulation_widget import SimulationWidget

    app = ProfilingApplication(sys.argv)
    app.setStyle('Fusion')

    scene = Path(args.scene)
    if not scene.is_absolute():
        scene = ROOT / scene
    diag = os.environ.get('GL_SYNC_DIAG') == '1'

    # 渲染帧计数：类级包装（Qt 虚拟分派会调用类方法，实例属性替换不可靠）
    paints = {'n': 0}
    updates = {'n': 0}
    paint_events = {'n': 0}
    _orig_paint = SimulationWidget.paintGL
    _orig_render_tick = SimulationWidget._on_render_tick
    _orig_event = SimulationWidget.event

    def _counted_paint(self, *fn_args, **fn_kwargs):
        paints['n'] += 1
        return _orig_paint(self, *fn_args, **fn_kwargs)

    def _counted_render_tick(self, *fn_args, **fn_kwargs):
        updates['n'] += 1
        return _orig_render_tick(self, *fn_args, **fn_kwargs)

    def _counted_event(self, event, *fn_args, **fn_kwargs):
        from PyQt6.QtGui import QPaintEvent
        if isinstance(event, QPaintEvent):
            paint_events['n'] += 1
        return _orig_event(self, event, *fn_args, **fn_kwargs)

    SimulationWidget.paintGL = _counted_paint
    SimulationWidget._on_render_tick = _counted_render_tick
    SimulationWidget.event = _counted_event

    results = []
    os.environ['GL_GPU_PROFILING'] = args.modes[0]
    window = MainWindow()
    window.resize(1400, 900)
    # 置顶显示，降低被其他窗口遮挡导致绘制暂停的风险
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()

    # 等待首帧渲染与 GL 上下文就绪
    _spin(window, app, 1.0)

    # 按倍速交错模式顺序执行，使时间相关干扰（如远程桌面最小化）对三种模式均等
    for speed in args.speeds:
        for mode in args.modes:
            window.sim_widget.set_gpu_profiling_mode(mode)
            for round_idx in range(args.rounds):
                if diag:
                    updates['n'] = 0
                    paint_events['n'] = 0
                row = _run_speed_case(
                    window, app, paints, scene, mode, speed,
                    args.warmup, args.duration, diag, round_idx,
                )
                if diag:
                    print(
                        f"[diag] {mode} x{speed} r{round_idx}: "
                        f"render_ticks={updates['n']} paint_events={paint_events['n']} "
                        f"paintGL={paints['n']} hist={len(window.profiler.history)}"
                    )
                    s = window.profiler.summary()
                    if s:
                        print(
                            f"[diag] summary {mode} x{speed}: "
                            f"frame={s['period_avg_ms']:.1f} "
                            f"physics={s['physics_ms']:.2f} "
                            f"render_cpu={s['render_cpu_ms']:.2f} "
                            f"render_wall={s['render_wall_ms']:.2f} "
                            f"gpu_wait={s['gpu_wait_ms']:.2f} "
                            f"gpu_time={s['gpu_time_ms']:.2f} "
                            f"qt={s['qt_dispatch_ms']:.2f} "
                            f"unaccounted={s['unaccounted_ms']:.2f}"
                        )
                results.append(row)
                _print_row(row)

    window.close()

    SimulationWidget.paintGL = _orig_paint
    SimulationWidget._on_render_tick = _orig_render_tick
    SimulationWidget.event = _orig_event
    _write_csv(results)
    _print_table(results)
    app.quit()


def _run_speed_case(window, app, paints, scene, mode, speed,
                    warmup, duration, diag, round_idx):
    """加载场景 -> 预热 -> 测量，返回单轮指标字典。"""
    # 若平台窗口未暴露（远程桌面/被遮挡/最小化），尝试恢复并置前，
    # 否则 Qt 会抑制绘制，渲染指标不可测。
    if not window.windowHandle().isExposed():
        window.showNormal()
        window.raise_()
        window.activateWindow()
        _spin(window, app, 0.3)
    # 重新加载场景：每次从同一初始状态开始（轨迹清空）
    window._load_scene_from_path(str(scene))
    # 太阳系九体：Sun + 八大行星（移除 Moon）
    body_count = len(window.engine.bodies)
    for i, body in enumerate(window.engine.bodies):
        if body.name == 'Moon':
            window.engine.remove_body(i)
            body_count = len(window.engine.bodies)
            break
    window.engine.time_scale = float(speed)
    window.sim_widget.update()
    if diag:
        print(
            f"[diag] {mode} x{speed} r{round_idx} pre_warmup: "
            f"win_visible={window.isVisible()} "
            f"w_visible={window.sim_widget.isVisible()} "
            f"w_exposed={window.windowHandle().isExposed()} "
            f"paints={paints['n']} hist={len(window.profiler.history)}"
        )

    # 预热：填充 profiler 历史与轨迹，稳定帧率
    _spin(window, app, warmup)
    if diag:
        print(
            f"[diag] {mode} x{speed} r{round_idx} post_warmup: "
            f"paints={paints['n']} hist={len(window.profiler.history)}"
        )

    # 测量窗口
    row = _measure(window, app, paints, mode, speed, body_count, duration, diag)
    if diag:
        print(
            f"[diag] {mode} x{speed} r{round_idx} post_measure: "
            f"paints={paints['n']} hist={len(window.profiler.history)}"
        )
    return row


def _spin(window, app, seconds: float) -> None:
    """使用 QEventLoop 运行 Qt 事件循环指定时长（保持平台事件正常派发）。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    keeper = _start_visibility_keeper(window, loop)
    loop.exec()
    keeper.stop()


def _start_visibility_keeper(window, loop, interval_ms: int = 150):
    """
    远程桌面/前台锁定可能把测试窗口最小化；定时恢复窗口以保持渲染持续。
    返回可停止的 QTimer。
    """
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


def _measure(window, app, paints, mode, speed, body_count, duration, diag=False):
    """在测量窗口内累计 profiler 帧数据，返回指标字典。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    prof = window.profiler

    # 预热帧不进入统计：强引用记录已关闭帧（防止 deque 淘汰后 id 被复用）
    seen = {id(f): f for f in list(prof.history)}
    paints_before = paints['n']

    periods = []
    physics = []
    render_wall = []
    gpu_wait = []
    gpu_time = []
    render_cpu = []

    t0 = time.perf_counter()
    end = t0 + duration

    loop = QEventLoop()
    sampler = QTimer()
    sampler.setInterval(50)

    def _sample():
        _drain_history(prof.history, seen, periods, physics, render_wall,
                       gpu_wait, gpu_time, render_cpu)
        if diag and int(time.perf_counter() * 2) % 2 == 0:
            print(
                f"[diag] {mode} x{speed} measure "
                f"t={time.perf_counter() - t0:5.2f}s "
                f"exposed={window.windowHandle().isExposed()} "
                f"state={window.windowState().name} "
                f"paints={paints['n']}"
            )
        if time.perf_counter() >= end:
            sampler.stop()
            loop.quit()

    sampler.timeout.connect(_sample)
    sampler.start()
    keeper = _start_visibility_keeper(window, loop)
    QTimer.singleShot(int((duration + 1.0) * 1000), loop.quit)  # 安全兜底
    loop.exec()
    keeper.stop()
    _drain_history(prof.history, seen, periods, physics, render_wall,
                   gpu_wait, gpu_time, render_cpu)
    elapsed = time.perf_counter() - t0

    n = len(periods)
    if n == 0:
        return {
            'mode': mode, 'speed': speed, 'bodies': body_count,
            'duration_s': elapsed, 'frames': 0,
            'period_avg_ms': 0.0, 'period_p95_ms': 0.0,
            'physics_ms': 0.0, 'render_wall_ms': 0.0,
            'render_cpu_ms': 0.0, 'gpu_wait_ms': 0.0, 'gpu_time_ms': 0.0,
            'fps_profiler': 0.0, 'fps_render': 0.0,
        }

    return {
        'mode': mode, 'speed': speed, 'bodies': body_count,
        'duration_s': elapsed, 'frames': n,
        'period_avg_ms': statistics.fmean(periods),
        'period_p95_ms': _p95(periods),
        'physics_ms': statistics.fmean(physics),
        'render_wall_ms': statistics.fmean(render_wall),
        'render_cpu_ms': statistics.fmean(render_cpu),
        'gpu_wait_ms': statistics.fmean(gpu_wait),
        'gpu_time_ms': statistics.fmean(gpu_time),
        'fps_profiler': n / elapsed,
        'fps_render': (paints['n'] - paints_before) / elapsed,
    }


def _drain_history(history, seen, periods, physics, render_wall,
                   gpu_wait, gpu_time, render_cpu):
    """累计新关闭的帧（去重），口径与 FrameProfiler.summary 一致。"""
    for f in list(history):
        if id(f) in seen:
            continue
        seen[id(f)] = f
        if f['period'] <= 0.0:
            continue
        periods.append(f['period'] * 1000.0)
        physics.append(f['physics'] * 1000.0)
        wall = f['render'] * 1000.0
        wait = min(f['gpu_sync'] * 1000.0, wall)
        render_wall.append(wall)
        gpu_wait.append(wait)
        gpu_time.append(f.get('gpu_time', 0.0) * 1000.0)
        render_cpu.append(max(0.0, wall - wait))


def _p95(values):
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    return s[int(round(0.95 * (len(s) - 1)))]


def _print_row(row):
    print(
        f"[{row['mode']:>6}] x{row['speed']:<4g} "
        f"frame={row['period_avg_ms']:6.2f}ms "
        f"render_cpu={row['render_cpu_ms']:6.2f}ms "
        f"gpu_wait={row['gpu_wait_ms']:6.2f}ms "
        f"gpu_time={row['gpu_time_ms']:6.2f}ms "
        f"physics={row['physics_ms']:6.2f}ms "
        f"fps(render)={row['fps_render']:5.1f} "
        f"fps(frame)={row['fps_profiler']:5.1f} "
        f"frames={row['frames']}"
    )


def _write_csv(results):
    out = ROOT / 'logs' / 'gl_sync_ab_test.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with open(out, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                'mode', 'speed', 'bodies', 'duration_s', 'frames',
                'period_avg_ms', 'period_p95_ms', 'physics_ms',
                'render_wall_ms', 'render_cpu_ms', 'gpu_wait_ms',
                'gpu_time_ms', 'fps_profiler', 'fps_render',
            ],
        )
        if new_file:
            writer.writeheader()
        for row in results:
            writer.writerow(row)
    print(f"CSV -> {out}")


def _print_table(results):
    """按 (模式, 倍率) 分组，输出各指标中位数。"""
    by_combo = {}
    for r in results:
        by_combo.setdefault((r['mode'], r['speed']), []).append(r)

    print()
    print("模式    x      Frame(med)  Frame(p95)  RenderCPU  GPUwait  GPUtimer  Physics  FPS(render)  FPS(frame)")
    for (mode, speed), rows in sorted(by_combo.items()):
        r = {
            'mode': mode, 'speed': speed,
            'period_avg_ms': statistics.median(x['period_avg_ms'] for x in rows),
            'period_p95_ms': statistics.median(x['period_p95_ms'] for x in rows),
            'render_cpu_ms': statistics.median(x['render_cpu_ms'] for x in rows),
            'gpu_wait_ms': statistics.median(x['gpu_wait_ms'] for x in rows),
            'gpu_time_ms': statistics.median(x['gpu_time_ms'] for x in rows),
            'physics_ms': statistics.median(x['physics_ms'] for x in rows),
            'fps_render': statistics.median(x['fps_render'] for x in rows),
            'fps_profiler': statistics.median(x['fps_profiler'] for x in rows),
        }
        print(
            f"{r['mode']:>6}  x{r['speed']:<4g} "
            f"{r['period_avg_ms']:9.2f}  {r['period_p95_ms']:9.2f}  "
            f"{r['render_cpu_ms']:8.2f}  {r['gpu_wait_ms']:7.2f}  "
            f"{r['gpu_time_ms']:8.2f}  {r['physics_ms']:7.2f}  "
            f"{r['fps_render']:11.1f}  {r['fps_profiler']:9.1f}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--modes', default='none,finish,timer',
        help='逗号分隔的 GPU 同步模式（默认 none,finish,timer）',
    )
    parser.add_argument(
        '--speeds', default='0.1,1,2,5,10',
        help='逗号分隔的倍率（默认 0.1,1,2,5,10）',
    )
    parser.add_argument('--rounds', type=int, default=2, help='每个组合的重复轮数')
    parser.add_argument('--warmup', type=float, default=2.0, help='预热秒数')
    parser.add_argument('--duration', type=float, default=7.0, help='测量秒数')
    parser.add_argument('--scene', default='scenes/solar_system.json')
    args = parser.parse_args()

    args.modes = [m.strip().lower() for m in args.modes.split(',') if m.strip()]
    args.speeds = [float(s) for s in args.speeds.split(',') if s.strip()]
    _run_app(args)


if __name__ == '__main__':
    main()
