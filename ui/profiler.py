"""
运行时性能分析器（FrameProfiler）

设计原则：
- Physics 计时不再通过 monkey-patch 私有方法，而是由 PhysicsEngine 主动调用
  可选计时钩子（engine.set_timing / GravitySolver.set_timing）记录各阶段耗时；
  profiler 关闭时引擎走无计时快速路径，额外开销仅为一次 None 判断。
- 渲染计时由 SimulationWidget.paintGL 上报：
      Render Wall     = paintGL 整段墙钟耗时（含 glFinish 等待）
      GPU Wait        = paintGL 内 glFinish 实测等待（CPU 等 GPU）
      Render CPU      = Render Wall - GPU Wait（真正渲染计算耗时）
  PerformanceLogger 与屏幕 profiler 使用同一套定义。
- Qt 事件分发由 ProfilingApplication.notify 统计全事件分发墙钟（qt_events）；
  Qt dispatch（净分发开销）= notify 总时长 - 已单独计时的
  Physics / UI callbacks / Render Wall，避免重复计入。
- 等待时间（GPU Wait、Qt 空闲、OS 调度）一律不计入 Physics 或 Render CPU。

每帧输出（由 SimulationWidget 动画 tick 驱动）：
    profiler = FrameProfiler(engine, reference_frame)
    profiler.attach()               # engine.set_timing(profiler)
    profiler.frame_start()          # 结束上一帧、开始新一帧
    engine.advance(...)             # 引擎主动上报 force/integrator/collision/trail/body_update/step
    profiler.add_render_parts(...)  # paintGL 内上报 Render Wall / 子阶段 / GPU Wait
    profiler.attach_ui(main_window) # 包装 UI 回调计时（非物理，方法包装）
"""

import time
import types
from collections import deque

from PyQt6.QtWidgets import QApplication

# 当前激活的分析器（供 ProfilingApplication.notify 归因事件分发耗时）
_ACTIVE_PROFILER = None


class ProfilingApplication(QApplication):
    """仅在分析器激活时统计 Qt 事件分发耗时（不改变任何行为）。"""

    def notify(self, receiver, event) -> bool:
        profiler = _ACTIVE_PROFILER
        if profiler is None:
            return super().notify(receiver, event)
        t0 = time.perf_counter()
        try:
            return super().notify(receiver, event)
        finally:
            profiler._frame['qt_events'] += time.perf_counter() - t0


class FrameProfiler:
    """
    逐帧统计 Physics / UI / Render / Qt 各阶段耗时，输出滚动平均与百分比。

    作为 PhysicsEngine 的可选计时钩子（duck typing）：
        record(stage: str, seconds: float)      # force/integrator/collision/trail/body_update/step
        record_count(stage: str, count: int)    # merges

    阶段定义（单位 ms）：
        Physics        = 引擎 step 总耗时（固定 dt 子步，纯计算，无等待）
            force      = GravitySolver.compute_accelerations（RK4 k1..k4 合计）
            integrator = 积分器整段（含 force）
            collision  = 碰撞检测 + 融合
            trail      = 轨迹记录
            body_update= step - (integrator + collision + trail)（引擎簿记余量）
        UI callbacks   = 状态栏/检查器/参考系定时回调（包装 UI 方法）
        Render CPU     = Render Wall - GPU Wait
        GPU Wait       = paintGL 内 glFinish 实测
        Render Wall    = paintGL 整段墙钟（诊断用）
        Qt dispatch    = notify 总时长 - (Physics + UI callbacks + Render Wall)
        Unaccounted    = 帧周期 - (Physics + UI + Render CPU + GPU Wait + Qt dispatch)
    """

    def __init__(
        self,
        engine,
        reference_frame=None,
        history_frames: int = 60,
        target_fps: float = 30.0,
    ):
        self.engine = engine
        self.reference_frame = reference_frame  # 保留参数兼容（当前未使用）
        self.history = deque(maxlen=history_frames)
        self._frame = self._new_frame()
        self._frame_open = False
        self._last_start = None
        self._fps_ema = 0.0
        self._attached = False
        self._ui_attached = False
        self._ui_originals = []
        self._ui_timer_bindings = []
        self._frame_listener = None
        self.target_fps = float(target_fps)

    @staticmethod
    def _new_frame() -> dict:
        return {
            'period': 0.0,
            'physics': 0.0,
            'force': 0.0,
            'integrator': 0.0,
            'collision': 0.0,
            'trail': 0.0,
            'body_update': 0.0,
            'ui': 0.0,
            'render': 0.0,          # Render Wall（paintGL 墙钟，含 GPU 等待）
            'star': 0.0,
            'trails': 0.0,
            'render_bodies': 0.0,
            'overlay': 0.0,
            'gpu_sync': 0.0,        # GPU Wait（glFinish 实测）
            'qt_events': 0.0,       # QApplication.notify 总分发墙钟
            'substeps': 0,
            'merges': 0,
            'bodies': 0,
        }

    # ------------------------------------------------------------
    # Physics 计时钩子（由 PhysicsEngine / GravitySolver 主动调用）
    # ------------------------------------------------------------

    def record(self, stage: str, seconds: float) -> None:
        """接收引擎上报的阶段耗时（秒），不修改任何模拟状态。"""
        frame = self._frame
        if stage == 'step':
            frame['physics'] += seconds
            frame['substeps'] += 1
            frame['bodies'] = len(self.engine.bodies)
        elif stage == 'force':
            frame['force'] += seconds
        elif stage == 'integrator':
            frame['integrator'] += seconds
        elif stage == 'collision':
            frame['collision'] += seconds
        elif stage == 'trail':
            frame['trail'] += seconds
        elif stage == 'body_update':
            frame['body_update'] += seconds

    def record_count(self, stage: str, count: int) -> None:
        """接收引擎上报的计数（如碰撞融合次数）。"""
        if stage == 'merges':
            self._frame['merges'] += count

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------

    def attach(self) -> None:
        """安装引擎计时钩子（重复调用安全）。"""
        if self._attached:
            return
        global _ACTIVE_PROFILER
        _ACTIVE_PROFILER = self
        self.engine.set_timing(self)
        self._attached = True

    def refresh(self) -> None:
        """场景加载等引擎组件变更后重新挂接计时钩子（幂等）。"""
        if self._attached:
            self.engine.set_timing(self)

    def detach(self) -> None:
        """移除引擎计时钩子并恢复 UI 回调包装。"""
        global _ACTIVE_PROFILER
        if _ACTIVE_PROFILER is self:
            _ACTIVE_PROFILER = None
        self._detach_ui()
        if self._attached:
            self.engine.set_timing(None)
            self._attached = False

    def attach_ui(self, window) -> None:
        """包装主窗口 UI 定时回调与刷新（计入 UI callbacks 耗时；非物理部分）。"""
        if self._ui_attached:
            return

        targets = []
        for name in ('_update_status', '_update_reference_frame'):
            if getattr(window, name, None) is not None:
                targets.append((name, window))
        for widget_attr in ('inspector', 'body_list'):
            widget = getattr(window, widget_attr, None)
            if widget is not None and hasattr(widget, 'refresh'):
                targets.append(('refresh', widget))

        for name, owner in targets:
            orig = getattr(owner, name)

            def make_ui_wrap(orig_fn):
                def w(owner_self, *args, **kwargs):
                    t0 = time.perf_counter()
                    result = orig_fn(*args, **kwargs)
                    self._frame['ui'] += time.perf_counter() - t0
                    return result
                return w

            wrapped = types.MethodType(make_ui_wrap(orig), owner)
            setattr(owner, name, wrapped)
            self._ui_originals.append((owner, name, orig))

        # 信号槽捕获的是连接时的绑定方法，包装后需重新连接定时器
        for timer_attr, callback_attr in (
            ('_status_timer', '_update_status'),
            ('_ref_frame_timer', '_update_reference_frame'),
        ):
            timer = getattr(window, timer_attr, None)
            if timer is None:
                continue
            try:
                timer.timeout.disconnect()
            except TypeError:
                pass
            orig = getattr(window, callback_attr)
            timer.timeout.connect(orig)
            self._ui_timer_bindings.append((timer, orig))

        self._ui_attached = True

    def _detach_ui(self) -> None:
        """恢复被包装的 UI 方法并重连原始定时器回调。"""
        if not self._ui_attached:
            return
        for timer, orig in self._ui_timer_bindings:
            try:
                timer.timeout.disconnect()
            except TypeError:
                pass
            timer.timeout.connect(orig)
        self._ui_timer_bindings.clear()
        for owner, name, orig in self._ui_originals:
            setattr(owner, name, orig)
        self._ui_originals.clear()
        self._ui_attached = False

    def set_frame_listener(self, listener) -> None:
        """注册每帧回调（性能日志用），参数为刚关闭的帧字典。"""
        self._frame_listener = listener

    # ------------------------------------------------------------
    # 帧驱动（由 SimulationWidget 动画 tick 调用）
    # ------------------------------------------------------------

    def frame_start(self) -> None:
        """开始新帧：先把上一帧（含期间的渲染/UI/Qt 耗时）推入历史。"""
        now = time.perf_counter()
        period = 0.0
        if self._last_start is not None:
            period = now - self._last_start
            if period > 0.0:
                inst_fps = 1.0 / period
                if self._fps_ema > 0.0:
                    self._fps_ema = 0.9 * self._fps_ema + 0.1 * inst_fps
                else:
                    self._fps_ema = inst_fps
        self._last_start = now

        if self._frame_open:
            self._frame['period'] = period
            self.history.append(self._frame)
            if self._frame_listener is not None:
                self._frame_listener(self._frame)
        self._frame = self._new_frame()
        self._frame_open = True

    def frame_end(self) -> None:
        """结束当前帧并推入历史（通常由下一次 frame_start 隐式完成）。"""
        if self._frame_open:
            if self._last_start is not None:
                self._frame['period'] = max(
                    0.0, time.perf_counter() - self._last_start
                )
            self.history.append(self._frame)
            if self._frame_listener is not None:
                self._frame_listener(self._frame)
            self._frame = self._new_frame()
            self._frame_open = False

    def frame_period_history_ms(self) -> list:
        """最近各帧的墙钟帧周期（ms），用于趋势图（过滤无效周期）。"""
        return [f['period'] * 1000.0 for f in self.history if f['period'] > 0.0]

    def add_render(self, milliseconds: float) -> None:
        """渲染总耗时上报（兼容接口，单位 ms；内部统一按秒存储）。"""
        self._frame['render'] += milliseconds / 1000.0

    def add_render_parts(
        self,
        render: float,
        star: float = 0.0,
        trails: float = 0.0,
        render_bodies: float = 0.0,
        overlay: float = 0.0,
        gpu_sync: float = 0.0,
    ) -> None:
        """
        渲染各子阶段耗时上报（paintGL 内调用，单位 ms；内部统一按秒存储）。

        render   = paintGL 整段墙钟（Render Wall，含 GPU 等待）
        gpu_sync = glFinish 实测等待（GPU Wait；不计入 Render CPU）
        """
        self._frame['render'] += render / 1000.0
        self._frame['star'] += star / 1000.0
        self._frame['trails'] += trails / 1000.0
        self._frame['render_bodies'] += render_bodies / 1000.0
        self._frame['overlay'] += overlay / 1000.0
        self._frame['gpu_sync'] += gpu_sync / 1000.0

    # ------------------------------------------------------------
    # 统计输出
    # ------------------------------------------------------------

    def summary(self):
        """
        滚动统计（ms 与百分比，基准为帧周期；帧周期不可用时回退为已计入总和）。

        分类（对应 UI 面板）：
            Physics / UI callbacks / Render CPU / GPU Wait / Render Wall /
            Qt dispatch / Unaccounted
        """
        n = len(self.history)
        if n == 0:
            return None

        avg = {}
        mx = {}
        for key in self._new_frame():
            vals = [f[key] for f in self.history]
            avg[key] = sum(vals) / n
            mx[key] = max(vals)

        def ms(key: str) -> float:
            return avg[key] * 1000.0

        physics = ms('physics')
        force = ms('force')
        integrator = ms('integrator')
        integrator_update = max(0.0, integrator - force)
        collision = ms('collision')
        trail = ms('trail')
        body_update = ms('body_update')
        ui = ms('ui')

        # Render：统一口径
        render_wall = ms('render')
        gpu_wait = min(ms('gpu_sync'), render_wall)
        render_cpu = max(0.0, render_wall - gpu_wait)

        # Qt dispatch = notify 总时长 - 已单独计时的 Physics/UI/Render Wall
        qt_total = ms('qt_events')
        qt_dispatch = max(0.0, qt_total - physics - ui - render_wall)

        frame_period = (1000.0 / self._fps_ema) if self._fps_ema > 0.0 else 0.0
        accounted = physics + ui + render_cpu + gpu_wait + qt_dispatch
        denominator = (
            max(frame_period, accounted) if accounted > 0.0 else frame_period
        )
        unaccounted = max(0.0, frame_period - accounted)

        periods_ms = [
            f['period'] * 1000.0 for f in self.history if f['period'] > 0.0
        ]
        if periods_ms:
            periods_sorted = sorted(periods_ms)
            period_avg = sum(periods_ms) / len(periods_ms)
            period_p95 = periods_sorted[
                int(round(0.95 * (len(periods_sorted) - 1)))
            ]
            period_max = periods_sorted[-1]
        else:
            period_avg = frame_period
            period_p95 = 0.0
            period_max = 0.0

        def pct(value_ms: float) -> float:
            return (value_ms / denominator * 100.0) if denominator > 0.0 else 0.0

        return {
            'fps': self._fps_ema,
            'frame_period': frame_period,
            'period_avg_ms': period_avg,
            'period_p95_ms': period_p95,
            'period_max_ms': period_max,
            'physics_ms': physics,
            'force_ms': force,
            'integrator_ms': integrator,
            'integrator_update_ms': integrator_update,
            'collision_ms': collision,
            'trail_ms': trail,
            'body_update_ms': body_update,
            'ui_ms': ui,
            'render_cpu_ms': render_cpu,
            'gpu_wait_ms': gpu_wait,
            'render_wall_ms': render_wall,
            'qt_total_ms': qt_total,
            'qt_dispatch_ms': qt_dispatch,
            'unaccounted_ms': unaccounted,
            'substeps': avg['substeps'],
            'merges': avg['merges'],
            'bodies': avg['bodies'],
            'pct_physics': pct(physics),
            'pct_force': pct(force),
            'pct_integrator': pct(integrator_update),
            'pct_collision': pct(collision),
            'pct_trail': pct(trail),
            'pct_body_update': pct(body_update),
            'pct_ui': pct(ui),
            'pct_render_cpu': pct(render_cpu),
            'pct_gpu_wait': pct(gpu_wait),
            'pct_render_wall': pct(render_wall),
            'pct_qt': pct(qt_dispatch),
            'pct_unaccounted': pct(unaccounted),
        }


class PerformanceLogger:
    """
    逐帧性能日志：Frame / Physics / UI / Render CPU / GPU Wait / Render Wall / Qt / Unaccounted。

    与屏幕 profiler 使用完全相同的定义：
        Render CPU = Render Wall - GPU Wait；等待不计入 Render CPU。
    每帧输出一行到控制台与日志文件，并每秒输出一次统计：
    平均值（全量）、最大值、1 秒窗口平均值。
    """

    _METRIC_NAMES = (
        'frame', 'physics', 'ui', 'render_cpu',
        'gpu_wait', 'render_wall', 'qt', 'unaccounted',
    )

    def __init__(self, profiler, path=None, enabled=True):
        self.profiler = profiler
        self.enabled = enabled
        self._sum = [0.0] * len(self._METRIC_NAMES)
        self._max = [0.0] * len(self._METRIC_NAMES)
        self._window = deque()
        self._count = 0
        self._last_stats_at = 0.0
        self._file = None
        if enabled and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, 'a', encoding='utf-8')
            self._file.write(
                '# ts frame_ms physics_ms ui_ms render_cpu_ms '
                'gpu_wait_ms render_wall_ms qt_ms unaccounted_ms\n'
            )
            self._file.flush()

    @staticmethod
    def _frame_values(frame: dict):
        """把原始帧字典换算为与 summary 同口径的指标（ms）。"""
        period = frame['period'] * 1000.0
        physics = frame['physics'] * 1000.0
        ui = frame['ui'] * 1000.0
        render_wall = frame['render'] * 1000.0
        gpu_wait = min(frame['gpu_sync'] * 1000.0, render_wall)
        render_cpu = max(0.0, render_wall - gpu_wait)
        qt_total = frame['qt_events'] * 1000.0
        qt_dispatch = max(0.0, qt_total - physics - ui - render_wall)
        unaccounted = max(
            0.0,
            period - (physics + ui + render_cpu + gpu_wait + qt_dispatch),
        )
        return (
            period, physics, ui, render_cpu,
            gpu_wait, render_wall, qt_dispatch, unaccounted,
        )

    def record(self, frame: dict) -> None:
        """记录一帧（由 FrameProfiler 帧监听器调用）。"""
        if not self.enabled:
            return
        values = self._frame_values(frame)

        now = time.perf_counter()
        self._count += 1
        for i, v in enumerate(values):
            self._sum[i] += v
            if v > self._max[i]:
                self._max[i] = v
        self._window.append((now, values))
        while self._window and self._window[0][0] < now - 1.0:
            self._window.popleft()

        period, physics, ui, render_cpu, gpu_wait, render_wall, qt, unaccounted = values
        line = (
            f"frame={period:7.1f} physics={physics:7.2f} ui={ui:6.2f} "
            f"render_cpu={render_cpu:7.2f} gpu_wait={gpu_wait:6.2f} "
            f"render_wall={render_wall:7.2f} qt={qt:6.2f} "
            f"unaccounted={unaccounted:6.2f}"
        )
        print(line)
        if self._file is not None:
            self._file.write(
                f"{now:.3f} {period:.3f} {physics:.3f} {ui:.3f} "
                f"{render_cpu:.3f} {gpu_wait:.3f} {render_wall:.3f} "
                f"{qt:.3f} {unaccounted:.3f}\n"
            )
            self._file.flush()

        if now - self._last_stats_at >= 1.0:
            self._last_stats_at = now
            self._print_stats(now)

    def _print_stats(self, now: float) -> None:
        win_sum = [0.0] * len(self._METRIC_NAMES)
        n_win = 0
        for ts, vals in self._window:
            if ts >= now - 1.0:
                n_win += 1
                for i, v in enumerate(vals):
                    win_sum[i] += v
        parts = []
        for i, name in enumerate(self._METRIC_NAMES):
            avg = self._sum[i] / self._count if self._count else 0.0
            win_avg = win_sum[i] / n_win if n_win else 0.0
            parts.append(
                f"{name} avg={avg:6.2f} max={self._max[i]:6.2f} "
                f"1s={win_avg:6.2f}"
            )
        line = "[perf] " + " | ".join(parts)
        print(line)
        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        """关闭日志文件。"""
        if self._file is not None:
            self._file.close()
            self._file = None