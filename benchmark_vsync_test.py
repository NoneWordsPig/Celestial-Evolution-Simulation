"""
实验性 VSync Benchmark（纯脚本，不修改任何现有模块）

背景假设：
    GPU timer ~1-3ms，但 Render wall 几十 ms → 怀疑主要来源是
    QOpenGLWidget 的 swap/VSync 同步等待。

本脚本提供（仅运行时生效，无 UI 修改，不改 physics/renderer/timestep/数据结构）：
    1. 运行时切换 VSync（Windows WGL_EXT_swap_control）：
           ON  -> wglSwapIntervalEXT(1)
           OFF -> wglSwapIntervalEXT(0)
       并通过 wglGetSwapIntervalEXT 读回验证。
       （PyQt6 QOpenGLContext 无 setSwapInterval 绑定，故走 WGL 扩展。）
    2. paintGL 内 A/B/C 计时：
           A = CPU preparation   = paintgl_total - GL 提交子阶段
           B = OpenGL submit     = trail_upload_draw + body_upload_draw
           C = swapBuffers 等待  = QOpenGLWidget.aboutToCompose -> frameSwapped
       另记录 Frame total（相邻 present 间隔）与 GPU timer（非阻塞延迟读回）。
    3. 场景：太阳系九体（加载后移除 Moon），speed = 0.1/1/2/5/10。
    4. 输出 Markdown 表 + CSV(logs/vsync_ab_test.csv) + 瓶颈判断。

用法：
    python benchmark_vsync_test.py
    python benchmark_vsync_test.py --speeds 0.1,1,2,5,10 --duration 6
        --warmup 2 --rounds 1 --scene scenes/solar_system.json
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

# CSV 中保留的 paintGL 子阶段列（相位均值，ms/paint）
_PHASE_COLUMNS = (
    'ph_gl_clear', 'ph_trail_prepare', 'ph_trail_transform',
    'ph_trail_upload_draw', 'ph_body_prepare', 'ph_body_upload_draw',
    'ph_qpainter_begin', 'ph_scale_bar', 'ph_overlay', 'ph_qpainter_end',
    'ph_other',
)


def _load_wgl(state):
    """惰性解析 WGL_EXT_swap_control 函数（需在有效 GL 上下文内调用）。"""
    if state['set_fn'] is not None:
        return True
    if state.get('unsupported'):
        return False
    try:
        import ctypes
        opengl32 = ctypes.windll.opengl32
        get_proc = opengl32.wglGetProcAddress
        get_proc.restype = ctypes.c_void_p
        get_proc.argtypes = [ctypes.c_char_p]
        set_ptr = get_proc(b'wglSwapIntervalEXT')
        get_ptr = get_proc(b'wglGetSwapIntervalEXT')
        if not set_ptr or not get_ptr:
            state['unsupported'] = True
            return False
        swap_fn = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int)(int(set_ptr))
        get_fn = ctypes.WINFUNCTYPE(ctypes.c_int)(int(get_ptr))
        state['set_fn'] = swap_fn
        state['get_fn'] = get_fn
        state['supported'] = True
        return True
    except Exception as exc:  # pragma: no cover - 环境相关
        state['unsupported'] = True
        state['error'] = repr(exc)
        return False


def _apply_vsync(state, interval):
    """设置当前 GL 上下文 swap interval 并读回验证。"""
    if not _load_wgl(state):
        return None
    try:
        state['set_fn'](int(interval))
        readback = state['get_fn']()
        state['applied'] = int(interval)
        state['readback'] = readback
        return readback
    except Exception as exc:  # pragma: no cover - 驱动相关
        state['error'] = repr(exc)
        return None


def _run_app(args):
    # 关闭逐帧性能日志，保持基准输出干净；GPU 计时用非阻塞 timer query
    os.environ['PERF_LOG'] = '0'
    os.environ['PERF_LOG_PATH'] = str(ROOT / 'logs' / 'vsync_ab_test.log')
    os.environ['GL_GPU_PROFILING'] = 'timer'

    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    from PyQt6.QtCore import Qt
    from ui.main_window import MainWindow
    from ui.profiler import ProfilingApplication
    from ui.simulation_widget import SimulationWidget, RenderPhaseTimer

    app = ProfilingApplication(sys.argv)
    app.setStyle('Fusion')

    scene = Path(args.scene)
    if not scene.is_absolute():
        scene = ROOT / scene

    # ---------- 状态容器 ----------
    vsync = {
        'set_fn': None, 'get_fn': None, 'supported': False,
        'unsupported': False, 'error': None,
        'pending': None, 'applied': None, 'readback': None,
    }
    paints = {'n': 0}
    presents = {'times': [], 'waits': [], 'render_cpu': []}
    swap = {'compose_t': None, 'compose_paint': None, 'last_paint': None}

    # ---------- 类级包装 paintGL：A/B 计时 + 应用 VSync ----------
    _orig_paint = SimulationWidget.paintGL

    def _paint(self, *fn_args, **fn_kwargs):
        t_in = time.perf_counter()
        if vsync['pending'] is not None:
            _apply_vsync(vsync, vsync['pending'])
            vsync['pending'] = None
        phase_timer = getattr(self, '_render_phase_timer', None)
        prev = dict(phase_timer.phases) if phase_timer is not None else None
        try:
            _orig_paint(self, *fn_args, **fn_kwargs)
        finally:
            t_out = time.perf_counter()
            render_cpu_ms = (t_out - t_in) * 1000.0
            if prev is not None and phase_timer is not None:
                cur = dict(phase_timer.phases)
                delta = {
                    k: cur[k] - prev.get(k, 0.0)
                    for k in cur if cur[k] > prev.get(k, 0.0)
                }
                total = delta.get('paintgl_total', 0.0)
                if total > 0.0:
                    render_cpu_ms = total * 1000.0
            paints['n'] += 1
            swap['last_paint'] = {
                't': t_out, 'render_cpu_ms': render_cpu_ms,
            }

    SimulationWidget.paintGL = _paint

    window = MainWindow()
    window.resize(1400, 900)
    # 置顶显示，降低被其他窗口遮挡导致绘制暂停的风险
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()

    widget = window.sim_widget
    widget.set_render_phase_timer(RenderPhaseTimer())

    # ---------- C 段：swapBuffers 等待（合成开始 -> 交换完成） ----------
    def _on_about_to_compose():
        swap['compose_t'] = time.perf_counter()
        swap['compose_paint'] = swap['last_paint']

    def _on_frame_swapped():
        t = time.perf_counter()
        ct = swap['compose_t']
        if ct is not None:
            wait_ms = (t - ct) * 1000.0
            paint = swap['compose_paint'] or {}
            presents['times'].append(t)
            presents['waits'].append(wait_ms)
            presents['render_cpu'].append(paint.get('render_cpu_ms', 0.0))
            swap['compose_t'] = None

    widget.aboutToCompose.connect(_on_about_to_compose)
    widget.frameSwapped.connect(_on_frame_swapped)

    # 首帧渲染与 GL 上下文就绪，并探测 WGL 可用性
    _spin(window, app, 1.0)
    vsync['pending'] = 1
    widget.update()
    _spin(window, app, 0.5)
    print(
        f"[vsync] initial readback={vsync['readback']} "
        f"supported={vsync['supported']} err={vsync['error']}"
    )

    results = []
    # 逐 speed 交错 vsync 顺序，抵消时间相关漂移
    for speed_idx, speed in enumerate(args.speeds):
        order = (1, 0) if speed_idx % 2 == 0 else (0, 1)
        for vsync_interval in order:
            label = 'ON' if vsync_interval == 1 else 'OFF'
            for round_idx in range(args.rounds):
                row = _run_speed_case(
                    window, app, vsync, paints, presents, swap,
                    scene, vsync_interval, label, speed,
                    args.warmup, args.duration, round_idx,
                )
                results.append(row)
                _print_row(row)

    window.close()

    SimulationWidget.paintGL = _orig_paint
    widget.set_render_phase_timer(None)
    _write_csv(results)
    _print_table(results)
    _analyze(results)
    app.quit()


def _run_speed_case(window, app, vsync, paints, presents, swap,
                    scene, vsync_interval, label, speed,
                    warmup, duration, round_idx):
    """加载场景 -> 设 VSync -> 预热 -> 测量，返回单轮指标字典。"""
    # 若平台窗口未暴露（远程桌面/被遮挡/最小化），尝试恢复并置前
    if not window.windowHandle().isExposed():
        window.showNormal()
        window.raise_()
        window.activateWindow()
        _spin(window, app, 0.3)

    # 重新加载场景：每次从同一初始状态开始（轨迹清空）
    window._load_scene_from_path(str(scene))
    body_count = len(window.engine.bodies)
    for i, body in enumerate(window.engine.bodies):
        if body.name == 'Moon':
            window.engine.remove_body(i)
            body_count = len(window.engine.bodies)
            break
    window.engine.time_scale = float(speed)
    window.sim_widget.update()

    # 运行时切换 VSync：下一次 paint 内生效并读回验证
    vsync['pending'] = vsync_interval
    vsync['applied'] = None
    vsync['readback'] = None
    window.sim_widget.update()
    _spin(window, app, 0.4)
    readback = vsync['readback']
    print(
        f"[vsync] x{speed:<4g} {label}: applied={vsync['applied']} "
        f"readback={readback}"
    )

    # 预热：填充 profiler 历史与轨迹，稳定帧率
    _spin(window, app, warmup)
    # 测量前再断言一次（上下文可能被重建，swap interval 会复位）
    vsync['pending'] = vsync_interval

    row = _measure(window, app, vsync, paints, presents, swap,
                   label, speed, body_count, duration)
    row['readback'] = readback
    return row


def _spin(window, app, seconds: float) -> None:
    """使用 QEventLoop 运行 Qt 事件循环指定时长。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    keeper = _start_visibility_keeper(window, loop)
    loop.exec()
    keeper.stop()


def _start_visibility_keeper(window, loop, interval_ms: int = 150):
    """定时恢复被遮挡/最小化的测试窗口，保持渲染持续。"""
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


def _measure(window, app, vsync, paints, presents, swap,
             label, speed, body_count, duration):
    """在测量窗口内累计 present 样本与 profiler 帧数据，返回指标字典。"""
    from PyQt6.QtCore import QEventLoop, QTimer
    prof = window.profiler

    seen = {id(f): f for f in list(prof.history)}
    paints_before = paints['n']
    pres_before = len(presents['times'])

    phase_timer = window.sim_widget._render_phase_timer
    prev_phases = dict(phase_timer.phases) if phase_timer is not None else {}

    periods = []
    physics = []
    gpu_time = []

    t0 = time.perf_counter()
    end = t0 + duration

    loop = QEventLoop()
    sampler = QTimer()
    sampler.setInterval(50)

    def _sample():
        _drain_profiler(prof.history, seen, periods, physics, gpu_time)
        if time.perf_counter() >= end:
            sampler.stop()
            loop.quit()

    sampler.timeout.connect(_sample)
    sampler.start()
    keeper = _start_visibility_keeper(window, loop)
    QTimer.singleShot(int((duration + 1.0) * 1000), loop.quit)  # 安全兜底
    loop.exec()
    keeper.stop()
    _drain_profiler(prof.history, seen, periods, physics, gpu_time)
    elapsed = time.perf_counter() - t0

    # paintGL 各子阶段均值（按本窗口内 paint 数归一）
    phases_ms = {}
    n_paint = paints['n'] - paints_before
    if phase_timer is not None and n_paint > 0:
        cur_phases = dict(phase_timer.phases)
        phases_ms = {
            k: (cur_phases[k] - prev_phases.get(k, 0.0)) * 1000.0 / n_paint
            for k in cur_phases if cur_phases[k] > prev_phases.get(k, 0.0)
        }

    idx = pres_before
    times = presents['times'][idx:]
    waits = presents['waits'][idx:]
    rcpu = presents['render_cpu'][idx:]

    n_pres = len(times)
    frame_ms = 0.0
    fps = 0.0
    swap_wait_ms = 0.0
    render_cpu_ms = 0.0
    if n_pres >= 2:
        intervals = [
            (times[i + 1] - times[i]) * 1000.0
            for i in range(n_pres - 1)
            if times[i + 1] > times[i]
        ]
        if intervals:
            frame_ms = statistics.fmean(intervals)
    if n_pres:
        fps = n_pres / elapsed
        swap_wait_ms = statistics.fmean(waits)
        render_cpu_ms = statistics.fmean(rcpu)

    return {
        'speed': speed,
        'vsync': label,
        'readback': vsync.get('readback'),
        'frames': n_pres,
        'frame_ms': frame_ms,
        'render_cpu_ms': render_cpu_ms,
        'gpu_ms': statistics.fmean(gpu_time) if gpu_time else 0.0,
        'swap_wait_ms': swap_wait_ms,
        'fps': fps,
        'period_ms': statistics.fmean(periods) if periods else 0.0,
        'physics_ms': statistics.fmean(physics) if physics else 0.0,
        'paints': paints['n'] - paints_before,
        'bodies': body_count,
        'duration_s': elapsed,
        'phases_ms': phases_ms,
    }


def _drain_profiler(history, seen, periods, physics, gpu_time):
    """累计新关闭的 profiler 帧（去重），取帧周期/物理/GPU 计时。"""
    for f in list(history):
        if id(f) in seen:
            continue
        seen[id(f)] = f
        if f['period'] <= 0.0:
            continue
        periods.append(f['period'] * 1000.0)
        physics.append(f['physics'] * 1000.0)
        gpu_time.append(f.get('gpu_time', 0.0) * 1000.0)


def _print_row(row):
    phases = row.get('phases_ms', {}) or {}
    phase_str = ' '.join(
        f"{k}={phases[k]:.2f}" for k in (
            'trail_prepare', 'trail_transform', 'trail_upload_draw',
            'body_prepare', 'body_upload_draw', 'overlay', 'other',
        ) if k in phases
    )
    print(
        f"[{row['vsync']:>3}] x{row['speed']:<4g} "
        f"frame={row['frame_ms']:6.2f}ms "
        f"render_cpu={row['render_cpu_ms']:6.2f}ms "
        f"gpu={row['gpu_ms']:6.2f}ms "
        f"swap_wait={row['swap_wait_ms']:6.2f}ms "
        f"fps={row['fps']:6.1f} presents={row['frames']}"
    )
    if phase_str:
        print(f"         phases: {phase_str}ms/paint")


def _write_csv(results):
    out = ROOT / 'logs' / 'vsync_ab_test.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    fieldnames = [
        'speed', 'vsync', 'readback', 'frames',
        'frame_ms', 'render_cpu_ms', 'gpu_ms',
        'swap_wait_ms', 'fps', 'period_ms', 'physics_ms',
        'paints', 'bodies', 'duration_s',
    ] + list(_PHASE_COLUMNS)
    with open(out, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if new_file:
            writer.writeheader()
        for row in results:
            out_row = dict(row)
            phases = row.get('phases_ms', {}) or {}
            for col in _PHASE_COLUMNS:
                out_row[col] = round(phases.get(col[3:], 0.0), 3)
            writer.writerow(out_row)
    print(f"CSV -> {out}")


def _print_table(results):
    """按 (speed, vsync) 分组输出用户要求的 Markdown 表。"""
    by_combo = {}
    for r in results:
        by_combo.setdefault((r['speed'], r['vsync']), []).append(r)

    print()
    print('| speed | vsync | frame | render cpu | gpu | swap wait | fps |')
    print('| - | - | - | - | - | - | - |')
    for speed in sorted({r['speed'] for r in results}):
        for vsync_label in ('ON', 'OFF'):
            rows = by_combo.get((speed, vsync_label), [])
            if not rows:
                continue

            def med(key):
                return statistics.median(r[key] for r in rows)

            print(
                f"| {speed:g} | {vsync_label} | {med('frame_ms'):.2f} ms | "
                f"{med('render_cpu_ms'):.2f} ms | {med('gpu_ms'):.2f} ms | "
                f"{med('swap_wait_ms'):.2f} ms | {med('fps'):.1f} |"
            )


def _analyze(results):
    """VSync ON vs OFF 对比，输出瓶颈判断。"""
    by_combo = {}
    for r in results:
        by_combo.setdefault((r['speed'], r['vsync']), []).append(r)

    print()
    print('=== 分析：swap 同步 vs CPU render ===')
    pairs = []
    for speed in sorted({r['speed'] for r in results}):
        on_rows = by_combo.get((speed, 'ON'), [])
        off_rows = by_combo.get((speed, 'OFF'), [])
        if not on_rows or not off_rows:
            continue
        on = on_rows[0]
        off = off_rows[0]
        pairs.append((speed, on, off))
        d_swap = on['swap_wait_ms'] - off['swap_wait_ms']
        d_frame = on['frame_ms'] - off['frame_ms']
        d_fps = off['fps'] - on['fps']
        print(
            f"x{speed:<4g} swap_wait ON={on['swap_wait_ms']:6.2f}ms "
            f"OFF={off['swap_wait_ms']:6.2f}ms (Δ{d_swap:+.2f}ms) | "
            f"frame ON={on['frame_ms']:6.2f} OFF={off['frame_ms']:6.2f}ms | "
            f"fps ON={on['fps']:5.1f} OFF={off['fps']:5.1f}"
        )
    if not pairs:
        print('无有效数据（没有同时包含 ON/OFF 的结果）')
        return

    avg_swap_on = statistics.fmean(on['swap_wait_ms'] for _, on, _ in pairs)
    avg_swap_off = statistics.fmean(off['swap_wait_ms'] for _, _, off in pairs)
    avg_fps_on = statistics.fmean(on['fps'] for _, on, _ in pairs)
    avg_fps_off = statistics.fmean(off['fps'] for _, _, off in pairs)
    avg_render_cpu = statistics.fmean(
        on['render_cpu_ms'] for _, on, _ in pairs
    )
    avg_gpu = statistics.fmean(on['gpu_ms'] for _, on, _ in pairs)

    print(f"\n平均 render cpu={avg_render_cpu:.2f}ms  gpu={avg_gpu:.2f}ms")
    print(f"平均 swap_wait: ON={avg_swap_on:.2f}ms  OFF={avg_swap_off:.2f}ms")
    print(f"平均 fps:       ON={avg_fps_on:.1f}  OFF={avg_fps_off:.1f}")

    if avg_swap_on >= 3.0:
        if avg_swap_off <= max(1.0, avg_swap_on * 0.3):
            if avg_fps_off > avg_fps_on * 1.15:
                print('判断：VSync OFF 后 Swap wait 显著下降且 FPS 明显提升'
                      ' → 瓶颈确认是 swap/VSync 同步。')
            else:
                print('判断：Swap wait 下降但 FPS 提升有限'
                      ' → 帧率仍受 Qt 合成/其他节流限制。')
        else:
            print('判断：VSync OFF 后 Swap wait 无明显变化'
                  ' → 继续调查 CPU render（或运行时切换对顶层合成未生效，'
                  '见 readback）。')
    else:
        print('判断：VSync ON 时 Swap wait 本身已很小'
              ' → swap 同步不是主要瓶颈，重点转向 CPU render。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speeds', default='0.1,1,2,5,10',
                        help='逗号分隔的倍率（默认 0.1,1,2,5,10）')
    parser.add_argument('--rounds', type=int, default=1, help='每组合重复轮数')
    parser.add_argument('--warmup', type=float, default=2.0, help='预热秒数')
    parser.add_argument('--duration', type=float, default=6.0, help='测量秒数')
    parser.add_argument('--scene', default='scenes/solar_system.json')
    parser.add_argument('--quick', action='store_true', help='快速冒烟测试')
    args = parser.parse_args()

    if args.quick:
        args.speeds = '1'
        args.duration = 2.0
        args.warmup = 1.0
    args.speeds = [float(s) for s in args.speeds.split(',') if s.strip()]
    _run_app(args)


if __name__ == '__main__':
    main()
