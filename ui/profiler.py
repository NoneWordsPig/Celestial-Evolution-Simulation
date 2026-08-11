"""
运行时性能分析器（FrameProfiler）

在不修改任何物理算法源码的前提下，通过运行时包装引擎/UI 方法，
按帧统计以下耗时（单位 ms）：

Physics 拆分：
 1 Force calculation        GravitySolver.compute_accelerations（RK4 k1..k4）
 2 Integrator(RK4) update   RK4Integrator.step - force（状态快照/预测/写入）
 3 Collision detection      CollisionHandler.resolve_collisions（检测/融合）
 4 Trail/history update     PhysicsEngine._record_trajectories
 5 Body state update        无独立阶段：位置/速度写入发生在积分器内（并入 #2）
 9 Other                    帧周期 - 上述各项 - 渲染 - UI（含引擎杂项/空闲）

UI/主线程：
 6 Momentum calculation     ReferenceFrame 质心速度/总动量 + 引擎 total_momentum
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

_RK4_STAGES = ('k1', 'k2', 'k3', 'k4')


class FrameProfiler:
    """按帧统计引擎/渲染/UI 各阶段耗时，输出滚动平均/max/p95（ms 与百分比）。"""

    def __init__(self, engine, reference_frame=None, history_frames: int = 60):
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

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------

    def attach(self) -> None:
        """包装引擎方法（只加计时，不改算法）。重复调用安全。"""
        if self._attached:
            return
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

        if type(engine.integrator).__name__ == 'RK4Integrator':
            integrator = engine.integrator
            orig_step = integrator.step
            def rk4_step_wrapper(engine_self, bodies, dt):
                self._in_rk4 = True
                self._stage_idx = 0
                t0 = time.perf_counter()
                try:
                    return orig_step(bodies, dt)
                finally:
                    self._frame["integrator"] += time.perf_counter() - t0
                    self._in_rk4 = False
            self._originals['rk4_step'] = orig_step
            integrator.step = types.MethodType(rk4_step_wrapper, integrator)

        # 动量计算（质心速度/总动量）——来自参考系与引擎只读查询
        if self.reference_frame is not None:
            for name in ('compute_center_of_mass_velocity', 'compute_total_momentum'):
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
            if 'compute_accelerations' in self._originals:
                engine.gravity_solver.compute_accelerations = self._originals['compute_accelerations']
            if 'detect_collisions' in self._originals:
                engine.collision_handler.detect_collisions = self._originals['detect_collisions']
            if 'resolve_collisions' in self._originals:
                engine.collision_handler.resolve_collisions = self._originals['resolve_collisions']
            if 'rk4_step' in self._originals:
                engine.integrator.step = self._originals['rk4_step']
            if self.reference_frame is not None:
                for name in ('compute_center_of_mass_velocity', 'compute_total_momentum'):
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

    def frame_start(self) -> None:
        """开始新帧：先把上一帧（含期间的渲染/UI 耗时）推入历史。"""
        now = time.perf_counter()
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
            self.history.append(self._frame)
        self._frame = self._new_frame()
        self._frame_open = True

    def frame_end(self) -> None:
        """结束当前帧并推入历史（通常由下一次 frame_start 隐式完成）。"""
        if self._frame_open:
            self.history.append(self._frame)
            self._frame = self._new_frame()
            self._frame_open = False

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
    ) -> None:
        """渲染各子阶段耗时上报（paintGL 内调用，单位 ms；内部统一按秒存储）。"""
        self._frame['render'] += render / 1000.0
        self._frame['star'] += star / 1000.0
        self._frame['trails'] += trails / 1000.0
        self._frame['render_bodies'] += render_bodies / 1000.0
        self._frame['overlay'] += overlay / 1000.0

    # ------------------------------------------------------------
    # 统计输出
    # ------------------------------------------------------------

    @staticmethod
    def _new_frame() -> dict:
        return {
            'physics': 0.0,
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
          4 Trail/history update / 5 Body state update(并入2)
          6 Momentum calculation / 7 Energy calculation / 8 UI synchronization
          9 Other
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
        force = ms('force')
        integrator = ms('integrator')
        integrator_update = max(0.0, integrator - force)
        collision = ms('collision')
        detect = ms('detect')
        merge = max(0.0, collision - detect)
        trajectory = ms('trajectory')
        momentum = ms('momentum')
        energy = ms('energy')
        ui_total = ms('ui_sync')
        ui_rest = max(0.0, ui_total - momentum - energy)
        render = ms('render')

        frame_period = (1000.0 / self._fps_ema) if self._fps_ema > 0.0 else 0.0
        accounted = physics + ui_total + render
        denominator = max(frame_period, accounted) if accounted > 0.0 else frame_period
        # 9 Other = 帧周期 - (1..4 + 6..8 + 渲染)，含引擎杂项与帧空闲
        other = max(0.0, frame_period - (
            force + integrator_update + collision + trajectory
            + momentum + energy + ui_rest + render
        ))

        frame_ms = [(f['physics'] + f['render']) * 1000.0 for f in self.history]
        frame_sorted = sorted(frame_ms)
        frame_max = frame_sorted[-1]
        frame_p95 = frame_sorted[int(round(0.95 * (n - 1)))]

        def pct(value_ms: float) -> float:
            return (value_ms / denominator * 100.0) if denominator > 0.0 else 0.0

        return {
            'fps': self._fps_ema,
            'frame_period': frame_period,
            'frame_max': frame_max,
            'frame_p95': frame_p95,
            'physics_ms': physics,
            'physics_max': mx['physics'] * 1000.0,
            'force_ms': force,
            'integrator_ms': integrator,
            'integrator_update_ms': integrator_update,
            'collision_ms': collision,
            'collision_max': mx['collision'] * 1000.0,
            'detect_ms': detect,
            'merge_ms': merge,
            'trajectory_ms': trajectory,
            'momentum_ms': momentum,
            'energy_ms': energy,
            'ui_sync_ms': ui_rest,
            'ui_sync_total_ms': ui_total,
            'render_ms': render,
            'render_max': mx['render'] * 1000.0,
            'render_star_ms': ms('star'),
            'render_trails_ms': ms('trails'),
            'render_bodies_ms': ms('render_bodies'),
            'render_overlay_ms': ms('overlay'),
            'other_ms': other,
            'stages_ms': [ms(k) for k in _RK4_STAGES],
            'substeps': avg['substeps'],
            'merges': avg['merges'],
            'bodies': avg['bodies'],
            'pct_physics': pct(physics),
            'pct_force': pct(force),
            'pct_integrator': pct(integrator_update),
            'pct_collision': pct(collision),
            'pct_trajectory': pct(trajectory),
            'pct_momentum': pct(momentum),
            'pct_energy': pct(energy),
            'pct_ui_sync': pct(ui_rest),
            'pct_render': pct(render),
            'pct_other': pct(other),
        }
