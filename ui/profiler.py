"""
运行时性能分析器（FrameProfiler）

在不修改任何物理算法源码的前提下，通过运行时包装引擎/UI 方法，
按帧统计以下耗时（单位 ms）：

Physics 拆分：
 1 Force calculation        GravitySolver.compute_accelerations（RK4 k1..k4）
 2 Integrator(RK4) update   RK4Integrator.step - force（状态快照/预测/写入）
 3 Collision detection      CollisionHandler.resolve_collisions（检测/融合）
 4 Trail/history update     PhysicsEngine._record_trajectories
 5 Body state update        engine.advance - (积分器+碰撞+轨迹)（引擎余量/状态写入）
 9 Unaccounted Time         帧周期 - (1..8 + 渲染)：未被任何阶段计入的剩余
    细分：
      a. Qt event processing       QApplication.notify 分发开销（不含回调本身）
      b. sleep / frame limiter     目标帧间隔 - 已计入工作量（主动等待）
      c. OS scheduling waiting     定时器合并/调度造成的额外等待
      d. GPU synchronization       paintGL 内 glFinish 实测（CPU 等 GPU）
      e. unknown / untracked       归因异常余量（通常为 0）

等待时间一律不计入 Physics/Render 计算耗时。

UI/主线程：
 6 Momentum calculation     ReferenceFrame 质心位置/速度/总动量 + 引擎 total_momentum
 7 Energy calculation       引擎 kinetic/potential/body_kinetic_energy
 8 UI synchronization       MainWindow 状态栏/参考系定时回调 + 检查器刷新

渲染：SimulationWidget.paintGL 上报（star/trails/bodies/overlay 子阶段）。

用法（由 SimulationWidget 动画 tick 驱动）：
    profiler = FrameProfiler(engine, reference_frame)
    profiler.attach()
    profiler.frame_start()          # 结束上一帧、开始新一帧
    engine.advance(...)             # 内部各阶段自动计时
    profiler.add_render_parts(...)  # paintGL 内调用
    profiler.attach_ui(main_window) # 主窗口初始化完成后挂接 UI 回调计时
"""

import time
import types
from collections import deque

from PyQt6.QtWidgets import QApplication

_RK4_STAGES = ('k1', 'k2', 'k3', 'k4')

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
    """按帧统计引擎/渲染/UI 各阶段耗时，输出滚动平均/max/p95（ms 与百分比）。"""

    def __init__(
        self,
        engine,
        reference_frame=None,
        history_frames: int = 60,
        target_fps: float = 30.0,
    ):
        self.engine = engine
        self.reference_frame = reference_frame
        self.history = deque(maxlen=history_frames)
        self._frame = self._new_frame()
        self._frame_open = False
        self._last_start = None
        self._fps_ema = 0.0
        self._attached = False
        self._ui_attached = False
        self._originals = {}
        self._ui_timer_bindings = []
        self._in_rk4 = False
        self._stage_idx = 0
        self._wrapped_integrator = None
        self._frame_listener = None
        self.target_fps = float(target_fps)

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------

    def attach(self) -> None:
        """包装引擎方法（只加计时，不改算法）。重复调用安全。"""
        if self._attached:
            return
        global _ACTIVE_PROFILER
        _ACTIVE_PROFILER = self
        engine = self.engine

        orig_single = engine._single_step
        def single_step_wrapper(engine_self):
            t0 = time.perf_counter()
            orig_single()
            dt = time.perf_counter() - t0
            self._frame['physics'] += dt
            self._frame['substeps'] += 1
            self._frame['bodies'] = len(engine.bodies)
        self._originals['_single_step'] = orig_single
        engine._single_step = types.MethodType(single_step_wrapper, engine)

        # 引擎整帧总耗时（advance = 积分+碰撞+轨迹+循环/累加器余量）
        orig_advance = engine.advance
        def advance_wrapper(e_self, wall_seconds):
            t0 = time.perf_counter()
            result = orig_advance(wall_seconds)
            self._frame['engine'] += time.perf_counter() - t0
            return result
        self._originals['advance'] = orig_advance
        engine.advance = types.MethodType(advance_wrapper, engine)

        orig_step = engine.step
        def step_wrapper(e_self):
            t0 = time.perf_counter()
            result = orig_step()
            self._frame['engine'] += time.perf_counter() - t0
            return result
        self._originals['step'] = orig_step
        engine.step = types.MethodType(step_wrapper, engine)

        orig_record = engine._record_trajectories
        def record_wrapper(engine_self):
            t0 = time.perf_counter()
            orig_record()
            self._frame['trajectory'] += time.perf_counter() - t0
        self._originals['_record_trajectories'] = orig_record
        engine._record_trajectories = types.MethodType(record_wrapper, engine)

        solver = engine.gravity_solver
        orig_acc = solver.compute_accelerations
        def acc_wrapper(engine_self, bodies):
            t0 = time.perf_counter()
            result = orig_acc(bodies)
            dt = time.perf_counter() - t0
            self._frame['force'] += dt
            if self._in_rk4:
                stage = _RK4_STAGES[self._stage_idx % 4]
                self._frame[stage] += dt
                self._stage_idx += 1
            return result
        self._originals['compute_accelerations'] = orig_acc
        solver.compute_accelerations = types.MethodType(acc_wrapper, solver)

        handler = engine.collision_handler
        orig_detect = handler.detect_collisions
        def detect_wrapper(engine_self, bodies):
            t0 = time.perf_counter()
            result = orig_detect(bodies)
            self._frame['detect'] += time.perf_counter() - t0
            return result
        self._originals['detect_collisions'] = orig_detect
        handler.detect_collisions = types.MethodType(detect_wrapper, handler)

        orig_resolve = handler.resolve_collisions
        def resolve_wrapper(engine_self, bodies):
            t0 = time.perf_counter()
            result = orig_resolve(bodies)
            dt = time.perf_counter() - t0
            self._frame['collision'] += dt
            self._frame['merges'] += max(0, len(bodies) - len(result))
            return result
        self._originals['resolve_collisions'] = orig_resolve
        handler.resolve_collisions = types.MethodType(resolve_wrapper, handler)

        self._wrap_integrator()

        # 动量计算（质心位置/速度/总动量）——来自参考系与引擎只读查询
        if self.reference_frame is not None:
            for name in (
                'compute_center_of_mass',
                'compute_center_of_mass_velocity',
                'compute_total_momentum',
            ):
                orig = getattr(self.reference_frame, name)
                def make_momentum_wrap(orig_fn):
                    def w(rf_self, bodies):
                        t0 = time.perf_counter()
                        result = orig_fn(bodies)
                        self._frame['momentum'] += time.perf_counter() - t0
                        return result
                    return w
                self._originals['rf_' + name] = orig
                setattr(
                    self.reference_frame, name,
                    types.MethodType(make_momentum_wrap(orig), self.reference_frame),
                )

        orig_tm = engine.total_momentum
        def tm_wrapper(e_self):
            t0 = time.perf_counter()
            result = orig_tm()
            self._frame['momentum'] += time.perf_counter() - t0
            return result
        self._originals['total_momentum'] = orig_tm
        engine.total_momentum = types.MethodType(tm_wrapper, engine)

        # 能量计算（动能/势能/单体贴动能）
        for name in ('kinetic_energy', 'potential_energy', 'body_kinetic_energy'):
            orig = getattr(engine, name)
            def make_energy_wrap(orig_fn):
                def w(e_self, *args):
                    t0 = time.perf_counter()
                    result = orig_fn(*args)
                    self._frame['energy'] += time.perf_counter() - t0
                    return result
                return w
            self._originals['energy_' + name] = orig
            setattr(engine, name, types.MethodType(make_energy_wrap(orig), engine))

        self._attached = True

    def _wrap_integrator(self) -> None:
        """包装当前积分器的 step（RK4 额外按 k1..k4 阶段归因）。"""
        integrator = self.engine.integrator
        orig_step = integrator.step
        is_rk4 = type(integrator).__name__ == 'RK4Integrator'

        def step_wrapper(e_self, bodies, dt, **kwargs):
            if is_rk4:
                self._in_rk4 = True
                self._stage_idx = 0
            t0 = time.perf_counter()
            try:
                return orig_step(bodies, dt, **kwargs)
            finally:
                self._frame['integrator'] += time.perf_counter() - t0
                if is_rk4:
                    self._in_rk4 = False

        self._originals['integrator_step'] = orig_step
        integrator.step = types.MethodType(step_wrapper, integrator)
        self._wrapped_integrator = integrator

    def refresh(self) -> None:
        """引擎组件被替换（如 SceneManager 加载场景重建积分器）后重新挂接计时。"""
        if self._attached and self.engine.integrator is not self._wrapped_integrator:
            self._wrap_integrator()

    def attach_ui(self, window) -> None:
        """包装主窗口 UI 定时回调与刷新（计入 UI 同步耗时）。"""
        if self._ui_attached:
            return

        targets = []
        for name in ('_update_status', '_update_reference_frame'):
            obj = getattr(window, name, None)
            if obj is not None:
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
                    self._frame['ui_sync'] += time.perf_counter() - t0
                    return result
                return w
            setattr(owner, name, types.MethodType(make_ui_wrap(orig), owner))
            self._originals['ui_' + repr(owner) + name] = orig

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

    def detach(self) -> None:
        """恢复所有被包装的原始方法。"""
        global _ACTIVE_PROFILER
        if _ACTIVE_PROFILER is self:
            _ACTIVE_PROFILER = None
        engine = self.engine
        if self._ui_attached:
            for timer, orig in self._ui_timer_bindings:
                try:
                    timer.timeout.disconnect()
                except TypeError:
                    pass
                timer.timeout.connect(orig)
            self._ui_timer_bindings.clear()
            self._ui_attached = False

        if self._attached:
            if '_single_step' in self._originals:
                engine._single_step = self._originals['_single_step']
            if '_record_trajectories' in self._originals:
                engine._record_trajectories = self._originals['_record_trajectories']
            if 'advance' in self._originals:
                engine.advance = self._originals['advance']
            if 'step' in self._originals:
                engine.step = self._originals['step']
            if 'compute_accelerations' in self._originals:
                engine.gravity_solver.compute_accelerations = self._originals['compute_accelerations']
            if 'detect_collisions' in self._originals:
                engine.collision_handler.detect_collisions = self._originals['detect_collisions']
            if 'resolve_collisions' in self._originals:
                engine.collision_handler.resolve_collisions = self._originals['resolve_collisions']
            if 'integrator_step' in self._originals:
                engine.integrator.step = self._originals['integrator_step']
            self._wrapped_integrator = None
            if self.reference_frame is not None:
                for name in (
                    'compute_center_of_mass',
                    'compute_center_of_mass_velocity',
                    'compute_total_momentum',
                ):
                    key = 'rf_' + name
                    if key in self._originals:
                        setattr(self.reference_frame, name, self._originals[key])
            if 'total_momentum' in self._originals:
                engine.total_momentum = self._originals['total_momentum']
            for name in ('kinetic_energy', 'potential_energy', 'body_kinetic_energy'):
                key = 'energy_' + name
                if key in self._originals:
                    setattr(engine, name, self._originals[key])
            self._originals.clear()
            self._attached = False

    # ------------------------------------------------------------
    # 帧驱动（由 SimulationWidget 动画 tick 调用）
    # ------------------------------------------------------------

    def set_frame_listener(self, listener) -> None:
        """注册每帧回调（性能日志用），参数为刚关闭的帧字典。"""
        self._frame_listener = listener

    def frame_start(self) -> None:
        """开始新帧：先把上一帧（含期间的渲染/UI 耗时）推入历史。"""
        # 积分器可能被 SceneManager 替换（加载场景），检测到后自动重新挂接
        if (self._wrapped_integrator is not None
                and self.engine.integrator is not self._wrapped_integrator):
            self._wrap_integrator()
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
        """渲染总耗时上报（兼容接口，不细分阶段；内部统一按秒存储）。"""
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
        """渲染各子阶段耗时上报（paintGL 内调用，单位 ms；内部统一按秒存储）。"""
        self._frame['render'] += render / 1000.0
        self._frame['star'] += star / 1000.0
        self._frame['trails'] += trails / 1000.0
        self._frame['render_bodies'] += render_bodies / 1000.0
        self._frame['overlay'] += overlay / 1000.0
        self._frame['gpu_sync'] += gpu_sync / 1000.0

    # ------------------------------------------------------------
    # 统计输出
    # ------------------------------------------------------------

    @staticmethod
    def _new_frame() -> dict:
        return {
            'period': 0.0,
            'physics': 0.0,
            'engine': 0.0,
            'qt_events': 0.0,
            'force': 0.0,
            'k1': 0.0, 'k2': 0.0, 'k3': 0.0, 'k4': 0.0,
            'integrator': 0.0,
            'collision': 0.0,
            'detect': 0.0,
            'trajectory': 0.0,
            'momentum': 0.0,
            'energy': 0.0,
            'ui_sync': 0.0,
            'render': 0.0,
            'gpu_sync': 0.0,
            'star': 0.0,
            'trails': 0.0,
            'render_bodies': 0.0,
            'overlay': 0.0,
            'substeps': 0,
            'merges': 0,
            'bodies': 0,
        }

    def summary(self):
        """
        滚动统计（ms 与百分比，基准为帧周期；帧周期不可用时回退为已计入总和）。

        分类（对应 UI 面板）：
          1 Force calculation / 2 Integrator(RK4) update / 3 Collision detection
          4 Trail/history update / 5 Body state update（advance 内未细分余量）
          6 Momentum calculation / 7 Energy calculation / 8 UI synchronization
          9 Unaccounted Time（帧周期 - 1..8 - 渲染）
        """
        n = len(self.history)
        if n == 0:
            return None

        keys = self._new_frame()
        avg = {}
        mx = {}
        for key in keys:
            vals = [f[key] for f in self.history]
            avg[key] = sum(vals) / n
            mx[key] = max(vals)

        def ms(key: str) -> float:
            return avg[key] * 1000.0

        physics = ms('physics')
        engine_total = ms('engine')
        force = ms('force')
        integrator = ms('integrator')
        integrator_update = max(0.0, integrator - force)
        collision = ms('collision')
        detect = ms('detect')
        merge = max(0.0, collision - detect)
        trajectory = ms('trajectory')
        body_state = max(0.0, engine_total - integrator - collision - trajectory)
        momentum = ms('momentum')
        energy = ms('energy')
        ui_total = ms('ui_sync')
        ui_rest = max(0.0, ui_total - momentum - energy)
        render = ms('render')
        gpu_sync = min(ms('gpu_sync'), render)
        # 渲染 CPU 耗时 = 渲染墙钟总耗时 - GPU 同步等待（等待不计入计算耗时）
        render_cpu = max(0.0, render - gpu_sync)

        frame_period = (1000.0 / self._fps_ema) if self._fps_ema > 0.0 else 0.0
        accounted = engine_total + momentum + energy + ui_rest + render_cpu
        denominator = max(frame_period, accounted) if accounted > 0.0 else frame_period
        # 9 Unaccounted Time = 帧周期 - (1..5 + 6 + 7 + 8 + 渲染)
        unaccounted = max(0.0, frame_period - accounted)

        # Unaccounted Time 细分（仅 profiling，不改模拟逻辑；等待不计入计算耗时）：
        #   a. Qt event processing   notify 分发总耗时 - 已计入回调耗时
        #   b. sleep / frame limiter min(目标帧间隔 - 已计入工作量, 实际空闲)
        #   c. OS scheduling waiting 其余等待（定时器合并/调度延迟）
        #   d. GPU synchronization   paintGL 内 glFinish 实测（CPU 等 GPU）
        #   e. unknown / untracked   归因异常余量（通常为 0）
        # 五项合计恒等于 Unaccounted。
        interval_ms = (1000.0 / self.target_fps) if self.target_fps > 0.0 else 0.0
        work_per_frame = engine_total + ui_total + render
        qt_proc_ms = max(0.0, ms('qt_events') - work_per_frame)
        sleep_ms = (
            min(max(0.0, interval_ms - work_per_frame), unaccounted)
            if interval_ms > 0.0 else 0.0
        )
        remaining = max(0.0, unaccounted - qt_proc_ms - sleep_ms)
        gpu_sync_split = min(gpu_sync, remaining)
        remaining -= gpu_sync_split
        os_wait_ms = remaining
        unknown_ms = 0.0

        frame_ms = [(f['physics'] + f['render']) * 1000.0 for f in self.history]
        frame_sorted = sorted(frame_ms)
        frame_max = frame_sorted[-1]
        frame_p95 = frame_sorted[int(round(0.95 * (n - 1)))]

        # 基于真实墙钟帧周期的分布统计（平均/p95/峰值）
        periods_ms = [f['period'] * 1000.0 for f in self.history if f['period'] > 0.0]
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
            'frame_max': frame_max,
            'frame_p95': frame_p95,
            'period_avg_ms': period_avg,
            'period_p95_ms': period_p95,
            'period_max_ms': period_max,
            'physics_ms': physics,
            'physics_max': mx['physics'] * 1000.0,
            'engine_ms': engine_total,
            'force_ms': force,
            'integrator_ms': integrator,
            'integrator_update_ms': integrator_update,
            'collision_ms': collision,
            'collision_max': mx['collision'] * 1000.0,
            'detect_ms': detect,
            'merge_ms': merge,
            'trajectory_ms': trajectory,
            'body_state_ms': body_state,
            'momentum_ms': momentum,
            'energy_ms': energy,
            'ui_sync_ms': ui_rest,
            'ui_sync_total_ms': ui_total,
            'ui_sync_max': mx['ui_sync'] * 1000.0,
            'render_ms': render,
            'render_net_ms': render_cpu,
            'render_max': mx['render'] * 1000.0,
            'render_star_ms': ms('star'),
            'render_trails_ms': ms('trails'),
            'render_bodies_ms': ms('render_bodies'),
            'render_overlay_ms': ms('overlay'),
            'other_ms': unaccounted,
            'unaccounted_ms': unaccounted,
            'qt_events_ms': qt_proc_ms,
            'sleep_ms': sleep_ms,
            'os_wait_ms': os_wait_ms,
            'gpu_sync_ms': gpu_sync_split,
            'gpu_sync_total_ms': gpu_sync,
            'unknown_ms': unknown_ms,
            'stages_ms': [ms(k) for k in _RK4_STAGES],
            'substeps': avg['substeps'],
            'merges': avg['merges'],
            'bodies': avg['bodies'],
            'pct_physics': pct(physics),
            'pct_force': pct(force),
            'pct_integrator': pct(integrator_update),
            'pct_collision': pct(collision),
            'pct_trajectory': pct(trajectory),
            'pct_body_state': pct(body_state),
            'pct_momentum': pct(momentum),
            'pct_energy': pct(energy),
            'pct_ui_sync': pct(ui_rest),
            'pct_render': pct(render_cpu),
            'pct_other': pct(unaccounted),
            'pct_unaccounted': pct(unaccounted),
        }


class PerformanceLogger:
    """
    逐帧性能日志：Frame / Physics / Render / Qt event / Wait。

    每帧输出一行到控制台与日志文件，并每秒输出一次统计：
    平均值（全量）、最大值、1 秒窗口平均值。
    """

    _METRIC_NAMES = ('frame', 'physics', 'render', 'qt', 'wait')

    def __init__(self, profiler, path=None, enabled=True):
        self.profiler = profiler
        self.enabled = enabled
        self._sum = [0.0] * 5
        self._max = [0.0] * 5
        self._window = deque()
        self._count = 0
        self._last_stats_at = 0.0
        self._file = None
        if enabled and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, 'a', encoding='utf-8')
            self._file.write(
                '# ts frame_ms physics_ms render_ms qt_ms wait_ms\n'
            )
            self._file.flush()

    def record(self, frame: dict) -> None:
        """记录一帧（由 FrameProfiler 帧监听器调用）。"""
        if not self.enabled:
            return
        period = frame['period'] * 1000.0
        physics = frame['engine'] * 1000.0
        render = frame['render'] * 1000.0
        ui = frame['ui_sync'] * 1000.0
        qt = max(0.0, frame['qt_events'] * 1000.0 - physics - ui - render)
        wait = max(0.0, period - physics - render - ui - qt)
        values = (period, physics, render, qt, wait)

        now = time.perf_counter()
        self._count += 1
        for i, v in enumerate(values):
            self._sum[i] += v
            if v > self._max[i]:
                self._max[i] = v
        self._window.append((now, values))
        while self._window and self._window[0][0] < now - 1.0:
            self._window.popleft()

        line = (
            f"frame={period:7.1f} physics={physics:7.2f} "
            f"render={render:7.2f} qt={qt:7.2f} wait={wait:7.2f}"
        )
        print(line)
        if self._file is not None:
            self._file.write(
                f"{now:.3f} {period:.3f} {physics:.3f} "
                f"{render:.3f} {qt:.3f} {wait:.3f}\n"
            )
            self._file.flush()

        if now - self._last_stats_at >= 1.0:
            self._last_stats_at = now
            self._print_stats(now)

    def _print_stats(self, now: float) -> None:
        win_sum = [0.0] * 5
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
