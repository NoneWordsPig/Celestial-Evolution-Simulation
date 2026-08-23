"""
模拟视图

OpenGL 渲染视图，显示天体和轨迹
添加比例尺显示和参考系支持
纯黑背景 + 发光效果、轨迹渐变
"""

import time

import numpy as np
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QPainter, QPen, QFont, QColor
import OpenGL.GL as gl

from physics import (
    PhysicsEngine, Camera, Body, Mode, UnitSystem, UnitConverter,
    SimulationFormatter, ScientificFormatter,
    ReferenceFrame, ScaleBar
)
from ui.trail_renderer import TrailRenderer


# 倍率上限检测窗口（帧数）与判定比例：
# 仅在倍率切换后的检测窗口内采样，引擎持续撞单帧子步上限才提示。
RATE_CHECK_FRAMES = 15
RATE_CHECK_CAPPED_MIN_RATIO = 0.6

# 性能分析覆盖层配色（与深色主题一致）
PROFILER_BG = QColor(10, 14, 26, 190)
PROFILER_BORDER = QColor(45, 51, 72)
PROFILER_TITLE = QColor(99, 102, 241)
PROFILER_LABEL = QColor(156, 163, 175)
PROFILER_VALUE = QColor(229, 231, 235)
PROFILER_PHYSICS = QColor(99, 102, 241)  # 靛蓝
PROFILER_UI = QColor(139, 92, 246)       # 紫
PROFILER_RENDER = QColor(6, 182, 212)    # 青
PROFILER_WARN = QColor(245, 158, 11)     # 琥珀（Unaccounted Time/瓶颈）
PROFILER_TREND = QColor(34, 211, 238)    # 趋势线亮青

# 预计算单位圆顶点（32 段，含闭合点），避免每帧每体重复三角函数
_CIRCLE_SEGMENTS = 32
_UNIT_CIRCLE = tuple(
    (
        np.cos(2.0 * np.pi * j / _CIRCLE_SEGMENTS),
        np.sin(2.0 * np.pi * j / _CIRCLE_SEGMENTS),
    )
    for j in range(_CIRCLE_SEGMENTS + 1)
)

# GPU 性能分析模式（仅影响同步/计时方式，不改变任何绘制内容）：
#   'none'   - 正常模式（默认）：paintGL 不调用 glFinish，不创建查询对象。
#   'finish' - 兼容旧行为：paintGL 末尾 gl.glFinish()，实测 CPU 等待 GPU 时间。
#   'timer'  - GL_ARB_timer_query / GL_EXT_timer_query：测量 GPU 实际执行时间，
#              结果延迟多帧读回（非阻塞），不强制 CPU 等待 GPU。
GPU_PROFILING_MODES = ('none', 'finish', 'timer')

# GPU 计时查询环形缓冲帧数：延迟读回，避免每帧阻塞等待结果。
_GPU_TIMER_RING = 8

try:
    # GL_ARB_timer_query 提供 GL_TIME_ELAPSED 与 64 位查询结果读回。
    from OpenGL.GL.ARB.timer_query import (
        GL_TIME_ELAPSED,
        glGetQueryObjectui64v,
    )
except Exception:  # pragma: no cover - 老驱动回退到 EXT 扩展
    try:
        from OpenGL.GL.EXT.timer_query import (
            GL_TIME_ELAPSED,
            glGetQueryObjectui64v,
        )
    except Exception:  # pragma: no cover - 无任何 timer query 支持
        GL_TIME_ELAPSED = None
        glGetQueryObjectui64v = None


def _query_result_ns(query_id: int) -> int:
    """读取 GL_TIME_ELAPSED 查询结果（纳秒），优先 64 位接口。"""
    if glGetQueryObjectui64v is not None:
        try:
            return int(glGetQueryObjectui64v(query_id, gl.GL_QUERY_RESULT))
        except Exception:  # pragma: no cover - 驱动不支持 64 位查询
            pass
    return int(gl.glGetQueryObjectiv(query_id, gl.GL_QUERY_RESULT))


class _GpuTimerQueryRing:
    """
    GL_TIME_ELAPSED 查询环形缓冲。

    begin_frame() 先非阻塞读回 ring_size 帧前已结束的查询结果，再开启本帧查询；
    end_frame() 结束查询。这样 CPU 不会等待 GPU 同步点，只会读到早已完成的旧结果。
    """

    def __init__(self, ring_size: int = _GPU_TIMER_RING):
        self.ring_size = int(ring_size)
        self.queries = []
        self.index = 0
        self.supported = False
        self._elapsed_seconds = 0.0

    def initialize(self) -> bool:
        """在有效 GL 上下文中初始化；驱动不支持时返回 False（静默降级）。"""
        if GL_TIME_ELAPSED is None:
            return False
        try:
            ext = gl.glGetString(gl.GL_EXTENSIONS)
            ext_text = (
                ext.decode('latin1') if isinstance(ext, bytes) else str(ext or '')
            )
            if (
                'GL_ARB_timer_query' not in ext_text
                and 'GL_EXT_timer_query' not in ext_text
            ):
                return False
            self.queries = gl.glGenQueries(self.ring_size)
            self.supported = True
            self.index = 0
            self._elapsed_seconds = 0.0
        except Exception:  # pragma: no cover - 任何失败均视为不支持
            self.queries = []
            self.supported = False
        return self.supported

    def begin_frame(self) -> None:
        """读回 ring_size 帧前结束的查询（非阻塞），然后开始本帧 GPU 计时。"""
        if not self.supported:
            return
        slot = self.index % self.ring_size
        if self.index >= self.ring_size:
            q = self.queries[slot]
            try:
                if gl.glGetQueryObjectiv(q, gl.GL_QUERY_RESULT_AVAILABLE):
                    self._elapsed_seconds = _query_result_ns(q) * 1e-9
                else:
                    self._elapsed_seconds = 0.0
            except Exception:  # pragma: no cover - 读回失败按 0 处理
                self._elapsed_seconds = 0.0
        else:
            self._elapsed_seconds = 0.0
        gl.glBeginQuery(GL_TIME_ELAPSED, self.queries[slot])

    def end_frame(self) -> None:
        """结束本帧 GPU 计时查询。"""
        if not self.supported:
            return
        gl.glEndQuery(GL_TIME_ELAPSED)
        self.index += 1

    def take_elapsed(self) -> float:
        """返回最近一次延迟读回的 GPU 执行时间（秒）。"""
        return self._elapsed_seconds

    def cleanup(self) -> None:
        """删除查询对象（在 GL 上下文销毁前调用，失败可忽略）。"""
        if self.supported and self.queries:
            try:
                gl.glDeleteQueries(self.queries)
            except Exception:  # pragma: no cover - 上下文销毁时驱动自行回收
                pass
            self.queries = []
            self.supported = False


class RenderPhaseTimer:
    """
    paintGL 内部各阶段耗时累计器（仅 profiling 模式挂接，不改变任何绘制）。

    phases[name] 累加秒数；paintGL 及各子方法在关键阶段边界调用 add()。
    未挂接时所有 add 调用均为 None 判断，零开销。
    """

    __slots__ = ('phases',)

    def __init__(self):
        self.phases = {}

    def add(self, name: str, seconds: float) -> None:
        if seconds > 0.0:
            self.phases[name] = self.phases.get(name, 0.0) + seconds

    def clear(self) -> None:
        self.phases.clear()


class CpuPipelineProfiler:
    """
    paintGL full-lifecycle CPU-side profiler (profiling only; no behavior change).

    phases[name] accumulates wall seconds; counts[name] accumulates occurrences.
    The paintEvent wrapper measures Qt-internal overhead outside paintGL:
    makeCurrent / GPU submit / swapBuffers / doneCurrent.
    """

    __slots__ = ('phases', 'counts')

    def __init__(self):
        self.phases = {}
        self.counts = {}

    def add(self, name: str, seconds: float) -> None:
        if seconds > 0.0:
            self.phases[name] = self.phases.get(name, 0.0) + seconds

    def bump(self, name: str, n: int = 1) -> None:
        if n > 0:
            self.counts[name] = self.counts.get(name, 0) + n

    def clear(self) -> None:
        self.phases.clear()
        self.counts.clear()


class SimulationWidget(QOpenGLWidget):
    """
    OpenGL 模拟视图
    
    负责：
    - 渲染天体（正圆 + 发光效果）
    - 渲染轨迹（渐变透明）
    - 纯黑背景
    - 渲染比例尺
    - 处理鼠标交互
    """
    
    # 信号
    body_clicked = pyqtSignal(int)
    camera_changed = pyqtSignal()
    rate_limit_detected = pyqtSignal()
    
    def __init__(
        self,
        engine: PhysicsEngine,
        camera: Camera,
        reference_frame: ReferenceFrame = None,
        parent=None
    ):
        super().__init__(parent)
        self.engine = engine
        self.camera = camera
        self.reference_frame = reference_frame or ReferenceFrame()
        
        # 模式
        self.mode = Mode.SIMULATION
        self.unit_system = UnitSystem()
        self.converter = None
        
        # 比例尺
        self.scale_bar = ScaleBar(target_pixel_length=150.0)
        
        # 鼠标交互
        self._mouse_pressed = False
        self._mouse_button = None
        self._last_mouse_pos = None
        
        # 渲染参数
        self.min_render_radius_px = 3.0
        self._show_trails = True
        # 轨迹渲染采样上限：完整轨迹保存在引擎，渲染最多绘制该点数（均匀采样）
        self.trail_render_sampling = 1000
        # 轨迹渲染：默认 VBO 批量（TrailRenderer）；old_trail_renderer=True 回退旧逐顶点 immediate mode（A/B 调试）
        self.old_trail_renderer = False
        self._trail_renderer = TrailRenderer(self.trail_render_sampling)

        # 性能覆盖层缓存（summary/行数据约 10 Hz 刷新，避免每帧重算）
        self._overlay_cache = None
        self._overlay_fonts = None
        
        # 选中的天体索引
        self._selected_body_index = -1
        
        # 主循环：物理定时器（固定步长推进）与渲染定时器（60 FPS）解耦
        self._physics_timer = QTimer(self)
        self._physics_timer.timeout.connect(self._on_animation_tick)
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_render_tick)
        self._is_paused = False
        self._target_fps = 30
        self._render_fps = 60
        self._last_tick_time = None  # 墙钟时间（平滑步进用）
        # 倍率上限检测窗口状态（仅在倍率切换后的一次性窗口内采样）
        self._fps_ema = float(self._target_fps)
        self._rate_check_active = False
        self._rate_check_frames = 0
        self._rate_check_capped = 0
        # 性能分析器（由 MainWindow 挂接，只计时不改状态/算法）
        self._profiler = None
        # 左上角性能分析覆盖层是否可见（视图菜单控制）
        self._show_profiler_overlay = True
        # GPU 同步/计时策略（正常模式默认不强制同步）
        self._gpu_profiling_mode = 'none'
        self._gpu_timer = _GpuTimerQueryRing()
        # CPU-side render pipeline profiler (None = disabled; profiling only)
        self._cpu_profiler = None
        # paintGL 内部阶段计时器（None = 关闭；仅 profiling 使用）
        self._render_phase_timer = None
        # 上下文销毁时驱动会回收 GL 对象；这里仅做尽力清理（对象销毁后调用无效）
        self.destroyed.connect(self._cleanup_gpu_timer)
        
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    
    def set_mode(self, mode: Mode, unit_system: UnitSystem = None, converter: UnitConverter = None):
        """设置模式"""
        self.mode = mode
        if unit_system:
            self.unit_system = unit_system
        if converter is not None:
            self.converter = converter
        self.update()

    def start_animation(self):
        """启动主循环：物理 30 Hz + 渲染 60 Hz，互不阻塞。"""
        self._last_tick_time = time.perf_counter()
        self._physics_timer.start(int(1000 / self._target_fps))
        self._render_timer.start(int(1000 / self._render_fps))
    
    def stop_animation(self):
        """停止主循环"""
        self._physics_timer.stop()
        self._render_timer.stop()

    def set_profiler(self, profiler) -> None:
        """挂接性能分析器（驱动帧计时，并上报渲染各子阶段耗时）。"""
        self._profiler = profiler

    def set_gpu_profiling_mode(self, mode: str) -> None:
        """
        设置 GPU 性能分析模式（不影响画面与物理结果）：
            'none'   - 正常模式：不调用 glFinish，不创建查询对象（默认）。
            'finish' - 旧行为：paintGL 末尾 glFinish，实测 CPU 等待 GPU。
            'timer'  - GL timer query 测量 GPU 实际执行时间，延迟读回，不阻塞 CPU。
        """
        mode = str(mode or 'none').strip().lower()
        if mode not in GPU_PROFILING_MODES:
            mode = 'none'
        self._gpu_profiling_mode = mode

    def set_render_phase_timer(self, timer) -> None:
        """挂接 paintGL 内部阶段计时器（None = 关闭；不影响绘制与物理）。"""
        self._render_phase_timer = timer

    def set_cpu_profiler(self, profiler) -> None:
        """Attach the CPU-side pipeline profiler (None disables; no behavior change)."""
        self._cpu_profiler = profiler

    def set_old_trail_renderer(self, enabled: bool) -> None:
        """A/B 调试开关：True 使用旧逐顶点 immediate mode 渲染轨迹，False（默认）使用 VBO 批量渲染。"""
        self.old_trail_renderer = bool(enabled)

    def set_profiler_overlay_visible(self, visible: bool) -> None:
        """显示/隐藏左上角性能分析覆盖层（仅影响显示，不改任何状态）。"""
        self._show_profiler_overlay = bool(visible)
        self.update()
    
    def pause(self):
        """暂停"""
        self._is_paused = True
    
    def resume(self):
        """恢复"""
        self._is_paused = False
        self._last_tick_time = None
    
    def step(self):
        """单步"""
        self.engine.step()
        self.update()
    
    def _on_animation_tick(self):
        """物理推进回调：仅推进模拟，不触发重绘（与渲染解耦）。"""
        profiler = self._profiler
        if profiler is not None:
            # 结束上一帧（含渲染/UI 耗时）并开始新一帧
            profiler.frame_start()
        if not self._is_paused:
            now = time.perf_counter()
            if self._last_tick_time is None:
                wall_dt = 1.0 / self._target_fps
            else:
                wall_dt = now - self._last_tick_time
                # 防止窗口卡顿/拖拽后一次性追赶过大
                wall_dt = min(wall_dt, 0.1)
            self._last_tick_time = now
            self.engine.advance(wall_dt)
            self._update_rate_check(wall_dt)

    def _on_render_tick(self):
        """渲染回调：仅请求重绘，不推进模拟。"""
        cpu = self._cpu_profiler
        if cpu is not None:
            cpu.bump('update_calls')
        self.update()

    def start_rate_check(self) -> None:
        """
        倍率切换后启动一次性帧率/上限检测窗口

        仅在窗口内采样；检测“引擎是否持续撞单帧子步上限”，
        若命中则发出 rate_limit_detected 信号（只提示，不修改任何设置）。
        """
        self._rate_check_active = True
        self._rate_check_frames = RATE_CHECK_FRAMES
        self._rate_check_capped = 0
        self._fps_ema = float(self._target_fps)

    def _update_rate_check(self, wall_dt: float) -> None:
        """检测窗口内逐帧采样：实测帧率 + 引擎是否被单帧子步上限截断"""
        if not self._rate_check_active:
            return
        if wall_dt <= 0.0:
            return

        inst_fps = 1.0 / wall_dt
        self._fps_ema = 0.9 * self._fps_ema + 0.1 * inst_fps
        if getattr(self.engine, "last_advance_capped", False):
            self._rate_check_capped += 1

        self._rate_check_frames -= 1
        if self._rate_check_frames <= 0:
            self._rate_check_active = False
            # 关键：只有当引擎持续撞单帧上限（提高倍率已无法加速）才提示；
            # 慢速倍率即使渲染帧率偏低也不算“上限”。
            capped_ratio = self._rate_check_capped / RATE_CHECK_FRAMES
            fps_lagging = self._fps_ema < self._target_fps
            if capped_ratio >= RATE_CHECK_CAPPED_MIN_RATIO and fps_lagging:
                self.rate_limit_detected.emit()
    
    def initializeGL(self):
        """初始化 OpenGL"""
        # 上下文可能被重建（窗口移动/平台事件），先清理旧查询对象再分配
        self._gpu_timer.cleanup()
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)  # 纯黑背景
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_LINE_SMOOTH)
        # GPU 计时查询（仅 profiling 模式使用；驱动不支持时静默降级为 none 行为）
        self._gpu_timer.initialize()
        # 轨迹 VBO
        self._trail_renderer.initialize()

    def _cleanup_gpu_timer(self):
        """GL 上下文销毁前清理计时查询对象。"""
        self._gpu_timer.cleanup()
        self._trail_renderer.cleanup()
    
    def resizeGL(self, w: int, h: int):
        """调整大小"""
        gl.glViewport(0, 0, w, h)
        self.camera.viewport_width = w
        self.camera.viewport_height = h
    
    def paintEvent(self, event):
        """
        Wrap QOpenGLWidget paintEvent: makeCurrent + paintGL + swap + doneCurrent.
        Measures wall time only; does not modify rendering behavior.
        """
        cpu = self._cpu_profiler
        if cpu is None:
            return super().paintEvent(event)
        cpu.bump('paint_calls')
        t0 = time.perf_counter()
        try:
            return super().paintEvent(event)
        finally:
            cpu.add('paint_event_total', time.perf_counter() - t0)

    def paintGL(self):
        """渲染"""
        profiler = self._profiler
        phase = self._render_phase_timer
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu_start = time.perf_counter()
            cpu.bump('paintgl_calls')
        if profiler is not None:
            t0 = time.perf_counter()

        gpu_timer = (
            self._gpu_timer
            if self._gpu_profiling_mode == 'timer' and profiler is not None
            else None
        )
        if gpu_timer is not None:
            # 延迟读回 + 开启本帧 GPU 计时（非阻塞，无 glFinish）
            gpu_timer.begin_frame()

        if phase is not None:
            t_ph = time.perf_counter()
        if cpu is not None:
            t_cpu_clear = time.perf_counter()
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        if phase is not None:
            phase.add('gl_clear', time.perf_counter() - t_ph)
        if cpu is not None:
            cpu.add('gl_clear', time.perf_counter() - t_cpu_clear)
        
        if profiler is not None:
            t_trails = time.perf_counter()
        # 绘制轨迹
        if self._show_trails:
            self._draw_trails()
        
        if profiler is not None:
            t_bodies = time.perf_counter()
        # 绘制天体
        self._draw_bodies()
        
        if profiler is not None:
            t_overlay = time.perf_counter()
        # 使用 QPainter 绘制 2D overlay（比例尺）
        self._draw_overlay()

        if profiler is not None:
            t_end = time.perf_counter()
            gpu_sync = 0.0
            gpu_time = 0.0
            if gpu_timer is not None:
                # GPU 实际执行时间（上一轮延迟读回，非阻塞）
                gpu_timer.end_frame()
                gpu_time = gpu_timer.take_elapsed() * 1000.0
            elif self._gpu_profiling_mode == 'finish':
                # 兼容旧行为：CPU 等 GPU 完成命令（仅 profiling 模式）
                t_gpu = time.perf_counter()
                gl.glFinish()
                gpu_sync = (time.perf_counter() - t_gpu) * 1000.0
            profiler.add_render_parts(
                render=(t_end - t0) * 1000.0,
                trails=(t_bodies - t_trails) * 1000.0,
                render_bodies=(t_overlay - t_bodies) * 1000.0,
                overlay=(t_end - t_overlay) * 1000.0,
                gpu_sync=gpu_sync,
                gpu_time=gpu_time,
            )
        if phase is not None and profiler is not None:
            # 阶段汇总：other = paintGL total - 已列出的子阶段
            phase.add('paintgl_total', t_end - t0)
            known = sum(
                phase.phases.get(k, 0.0)
                for k in (
                    'gl_clear',
                    'trail_prepare', 'trail_transform', 'trail_upload_draw',
                    'trail_upload', 'trail_draw',
                    'body_prepare', 'body_upload_draw',
                    'qpainter_begin', 'scale_bar', 'overlay', 'qpainter_end',
                )
            )
            phase.add('other', max(0.0, (t_end - t0) - known))
        if cpu is not None:
            cpu.add('paintgl_total', time.perf_counter() - t_cpu_start)
    
    def _draw_bodies(self):
        """绘制所有天体"""
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu = time.perf_counter()
        bodies = self.engine.bodies
        if cpu is not None:
            cpu.add('state_read', time.perf_counter() - t_cpu)
        for i, body in enumerate(bodies):
            self._draw_body(body, i)
    
    def _draw_body(self, body: Body, index: int):
        """绘制单个天体（简洁明快风格）"""
        phase = self._render_phase_timer
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu = time.perf_counter()
        if phase is not None:
            t0 = time.perf_counter()
        # 世界坐标 -> 屏幕坐标
        sx, sy = self.camera.world_to_screen(body.position[0], body.position[1])
        if cpu is not None:
            cpu.add('body_pos_conv', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        
        # 计算屏幕半径
        render_radius_world = body.render_radius
        screen_radius = render_radius_world * self.camera.zoom
        screen_radius = max(screen_radius, self.min_render_radius_px)
        if cpu is not None:
            cpu.add('body_radius_conv', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        
        # 转换为 NDC
        w = self.camera.viewport_width
        h = self.camera.viewport_height
        
        ndc_x = (sx / w) * 2.0 - 1.0
        ndc_y = 1.0 - (sy / h) * 2.0
        
        # 使用不同的 x/y 半径来补偿宽高比
        ndc_rx = screen_radius / w * 2.0
        ndc_ry = screen_radius / h * 2.0
        if cpu is not None:
            cpu.add('body_ndc', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        
        color = body.color
        glow_rx = ndc_rx * 1.3
        glow_ry = ndc_ry * 1.3
        if cpu is not None:
            cpu.add('body_color_conv', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
            cpu.bump('numpy_scalar_access', 5)
        if phase is not None:
            # body prepare = 相机/变换 + 半径/NDC/颜色计算（无 numpy，纯 Python 标量）
            phase.add('body_prepare', time.perf_counter() - t0)
            t1 = time.perf_counter()

        # 1. 柔和外发光（单层，低透明度，复用预计算单位圆）
        gl.glColor4f(color[0], color[1], color[2], 0.15)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(ndc_x, ndc_y)
        for ux, uy in _UNIT_CIRCLE:
            gl.glVertex2f(ndc_x + glow_rx * ux, ndc_y + glow_ry * uy)
        gl.glEnd()
        
        # 2. 主体圆形（实心）
        gl.glColor4f(color[0], color[1], color[2], 1.0)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(ndc_x, ndc_y)
        for ux, uy in _UNIT_CIRCLE:
            gl.glVertex2f(ndc_x + ndc_rx * ux, ndc_y + ndc_ry * uy)
        gl.glEnd()
        
        # 3. 选中光环（保留，仅选中时显示）
        if index == self._selected_body_index:
            gl.glColor4f(1.0, 1.0, 1.0, 0.8)
            gl.glLineWidth(2.0)
            gl.glBegin(gl.GL_LINE_LOOP)
            for ux, uy in _UNIT_CIRCLE[:-1]:
                gl.glVertex2f(ndc_x + ndc_rx * 1.4 * ux, ndc_y + ndc_ry * 1.4 * uy)
            gl.glEnd()
        if phase is not None:
            # body upload+draw = immediate mode 顶点提交（本渲染器无 VBO/VAO）
            phase.add('body_upload_draw', time.perf_counter() - t1)
        if cpu is not None:
            cpu.add('body_draw', time.perf_counter() - t_cpu)

    def _draw_trails(self):
        """绘制轨迹（默认 VBO 批量；old_trail_renderer=True 回退旧逐顶点 immediate mode）"""
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu = time.perf_counter()
        bodies = self.engine.bodies
        if cpu is not None:
            cpu.add('state_read', time.perf_counter() - t_cpu)
        if self.old_trail_renderer:
            for body in bodies:
                if len(body.trail) < 2:
                    continue
                self._draw_trail(body)
            return
        # VBO 路径：trail data -> numpy 顶点 -> glBufferSubData -> 每 body 一次 glDrawArrays
        if self._trail_renderer.sampling_limit != self.trail_render_sampling:
            self._trail_renderer.sampling_limit = self.trail_render_sampling
        self._trail_renderer.render(
            bodies, self.camera, phase=self._render_phase_timer
        )
        if cpu is not None:
            cpu.add('trail_draw', time.perf_counter() - t_cpu)
    
    def _draw_trail(self, body: Body):
        """绘制单个轨迹（颜色 = 星体颜色，单条 GL_LINE_STRIP 渐变）"""
        phase = self._render_phase_timer
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu = time.perf_counter()
        if phase is not None:
            t0 = time.perf_counter()
        history = list(body.trail)
        if cpu is not None:
            cpu.add('trail_history_read', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
            cpu.bump('trail_list_copy')
        pts = self._sample_trail(history, self.trail_render_sampling)
        if cpu is not None:
            cpu.add('trail_sample', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        n = len(pts)
        if n < 2:
            if phase is not None:
                phase.add('trail_prepare', time.perf_counter() - t0)
            return

        color = body.color
        w = self.camera.viewport_width
        h = self.camera.viewport_height
        m = len(pts)

        # 一次性向量化世界坐标 -> NDC（避免逐点 Python 坐标转换与临时对象）
        arr = np.asarray(pts, dtype=np.float64)
        if cpu is not None:
            cpu.add('trail_numpy_convert', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        if phase is not None:
            # trail prepare = 采样 + list -> numpy 转换（含每帧 list 拷贝）
            phase.add('trail_prepare', time.perf_counter() - t0)
            t1 = time.perf_counter()
        ndc = np.empty((m, 2), dtype=np.float64)
        cam = self.camera
        ndc[:, 0] = (
            (arr[:, 0] - cam.center_x) * cam.zoom + w * 0.5
        ) / w * 2.0 - 1.0
        ndc[:, 1] = 1.0 - (
            -(arr[:, 1] - cam.center_y) * cam.zoom + h * 0.5
        ) / h * 2.0
        alphas = 0.15 + 0.65 * np.linspace(0.0, 1.0, m)
        if cpu is not None:
            cpu.add('trail_vertex_gen', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        if phase is not None:
            # trail transform = 向量化世界坐标 -> NDC + 颜色透明度数组
            phase.add('trail_transform', time.perf_counter() - t1)
            t2 = time.perf_counter()

        gl.glLineWidth(1.5)
        gl.glBegin(gl.GL_LINE_STRIP)
        for i in range(m):
            gl.glColor4f(
                float(color[0]), float(color[1]), float(color[2]), alphas[i]
            )
            gl.glVertex2f(ndc[i, 0], ndc[i, 1])
        gl.glEnd()
        if phase is not None:
            # trail upload+draw = immediate mode 逐顶点提交（无 VBO/glBufferData）
            phase.add('trail_upload_draw', time.perf_counter() - t2)
        if cpu is not None:
            cpu.add('trail_draw', time.perf_counter() - t_cpu)
            cpu.bump('numpy_scalar_access', m * 3)

    @staticmethod
    def _sample_trail(pts: list, max_points: int) -> list:
        """均匀采样轨迹：保留完整数据，渲染最多 max_points 个连续采样点。"""
        n = len(pts)
        if n <= max_points:
            return pts
        step = n / max_points
        indices = [int(n - 1 - i * step) for i in range(max_points)]
        indices.reverse()
        return [pts[i] for i in indices]
    
    def _draw_overlay(self):
        """绘制 2D overlay（比例尺 + 性能分析，均为只读覆盖层）"""
        phase = self._render_phase_timer
        cpu = self._cpu_profiler
        if cpu is not None:
            t_cpu = time.perf_counter()
        if phase is not None:
            t0 = time.perf_counter()
        painter = QPainter(self)
        if cpu is not None:
            cpu.add('qpainter_begin', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        if phase is not None:
            phase.add('qpainter_begin', time.perf_counter() - t0)
            t1 = time.perf_counter()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 绘制比例尺
        self._draw_scale_bar(painter)
        if cpu is not None:
            cpu.add('qpainter_scale_bar', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        if phase is not None:
            phase.add('scale_bar', time.perf_counter() - t1)
            t2 = time.perf_counter()

        # 绘制性能分析（左上角覆盖层，不改变 UI 排版）
        self._draw_profiler_stats(painter)
        if cpu is not None:
            cpu.add('qpainter_overlay', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()
        if phase is not None:
            phase.add('overlay', time.perf_counter() - t2)
            t3 = time.perf_counter()
        
        painter.end()
        if cpu is not None:
            cpu.add('qpainter_end', time.perf_counter() - t_cpu)
        if phase is not None:
            phase.add('qpainter_end', time.perf_counter() - t3)
    
    def _draw_scale_bar(self, painter: QPainter):
        """绘制比例尺"""
        # 计算比例尺
        world_dist, pixel_len, label = self.scale_bar.compute(
            self.camera, self.mode, self.unit_system, self.converter
        )
        
        # 位置：左下角
        x = 20
        y = self.height() - 40
        
        # 绘制线条（转换为 int 以匹配 QPainter.drawLine 重载）
        x_end = int(x + pixel_len)
        pen = QPen(QColor(255, 255, 255, 200))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(int(x), int(y), x_end, int(y))
        
        # 绘制端点
        painter.drawLine(int(x), int(y) - 5, int(x), int(y) + 5)
        painter.drawLine(x_end, int(y) - 5, x_end, int(y) + 5)
        
        # 绘制标签
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 200))
        
        # 计算文本位置（居中）
        text_width = painter.fontMetrics().horizontalAdvance(label)
        text_x = x + (pixel_len - text_width) / 2
        painter.drawText(int(text_x), int(y - 10), label)

    def _draw_profiler_stats(self, painter: QPainter):
        """在模拟视图左上角绘制性能统计覆盖层（只读，不修改任何状态）。"""
        if self._profiler is None or not self._show_profiler_overlay:
            return
        now = time.perf_counter()
        cpu = self._cpu_profiler
        cache = self._overlay_cache
        # 性能数据独立刷新：约 10 Hz 重算统计，其余帧直接复用缓存
        if cache is None or now - cache[0] >= 0.1:
            t_cpu_recompute = time.perf_counter()
            summary = self._profiler.summary()
            if summary is None:
                return
            periods = self._profiler.frame_period_history_ms()
            self._overlay_cache = (
                now, summary, self._profiler_rows(summary, periods)
            )
            if cpu is not None:
                cpu.add('qpainter_overlay_recompute', time.perf_counter() - t_cpu_recompute)
        _, summary, rows = self._overlay_cache
        if cpu is not None:
            t_cpu = time.perf_counter()

        if self._overlay_fonts is None:
            title_font = QFont("Consolas")
            title_font.setPointSize(10)
            title_font.setBold(True)
            body_font = QFont("Consolas")
            body_font.setPointSize(9)
            self._overlay_fonts = (title_font, body_font)
        title_font, body_font = self._overlay_fonts

        # 先测量：面板内容宽度取最宽一行的“标签 + 值 + 间距”
        cell_pad = 28
        painter.setFont(title_font)
        title_fm = painter.fontMetrics()
        content_w = title_fm.horizontalAdvance(rows[0]['title'])
        title_h = title_fm.height() + 10
        painter.setFont(body_font)
        fm = painter.fontMetrics()
        for row in rows:
            if row['type'] == 'metrics':
                need = sum(
                    fm.horizontalAdvance(label) + fm.horizontalAdvance(value)
                    for label, value in row['items']
                ) + cell_pad * len(row['items'])
                content_w = max(content_w, need)
            elif row['type'] == 'table':
                row['label_w'] = max(
                    fm.horizontalAdvance(r[0]) for r in row['rows']
                )
                row['ms_w'] = max(
                    fm.horizontalAdvance(f"{r[1]:.1f}ms") for r in row['rows']
                )
                row['pct_w'] = max(
                    fm.horizontalAdvance(r[2]) for r in row['rows']
                )
                need = row['label_w'] + 12 + row['ms_w'] + 8 + row['pct_w'] + 70
                content_w = max(content_w, need)

        margin = 10
        x = 12
        y = 12
        panel_w = content_w + margin * 2

        # 行高与面板高度（标题下方留出额外间距）
        metrics_h = fm.height() + 5
        table_row_h = fm.height() + 2
        spark_h = 26
        panel_h = margin
        for row in rows:
            if row['type'] == 'title':
                panel_h += title_h + 6
            elif row['type'] == 'metrics':
                panel_h += metrics_h
            elif row['type'] == 'sparkline':
                panel_h += spark_h + 4
            elif row['type'] == 'table':
                panel_h += len(row['rows']) * table_row_h + 4
        panel_h += margin
        if cpu is not None:
            cpu.add('qpainter_overlay_measure', time.perf_counter() - t_cpu)
            t_cpu = time.perf_counter()

        # 半透明深色背景 + 边框，保证可读性且不遮挡交互
        painter.fillRect(x, y, int(panel_w), int(panel_h), PROFILER_BG)
        painter.setPen(PROFILER_BORDER)
        painter.drawRect(x, y, int(panel_w) - 1, int(panel_h) - 1)

        # 标题
        painter.setFont(title_font)
        painter.setPen(PROFILER_TITLE)
        painter.drawText(
            x + margin, y + margin + title_fm.ascent(), rows[0]['title']
        )
        cur_y = y + margin + title_h + 6

        # 内容行：指标行 / 帧周期趋势 / 9 分类表格
        painter.setFont(body_font)
        for row in rows[1:]:
            if row['type'] == 'metrics':
                items = row['items']
                cell_w = content_w / max(1, len(items))
                for i, (label, value) in enumerate(items):
                    cell_x = x + margin + i * cell_w
                    painter.setPen(PROFILER_LABEL)
                    painter.drawText(int(cell_x), cur_y + fm.ascent(), label)
                    value_w = fm.horizontalAdvance(value)
                    value_x = cell_x + cell_w - 12
                    painter.setPen(PROFILER_VALUE)
                    painter.drawText(
                        int(value_x - value_w), cur_y + fm.ascent(), value
                    )
                cur_y += metrics_h
            elif row['type'] == 'sparkline':
                self._draw_frame_trend(
                    painter, x + margin, cur_y + fm.height() - 2,
                    content_w, spark_h, row['periods'],
                )
                cur_y += spark_h + 4
            elif row['type'] == 'table':
                for label, value_ms, pct_text, color, bar_ref in row['rows']:
                    painter.setPen(PROFILER_LABEL)
                    painter.drawText(
                        int(x + margin), cur_y + fm.ascent(), label
                    )
                    ms_x = x + margin + row['label_w'] + 12
                    ms_text = f"{value_ms:.1f}ms"
                    painter.setPen(PROFILER_VALUE)
                    painter.drawText(
                        int(ms_x + row['ms_w'] - fm.horizontalAdvance(ms_text)),
                        cur_y + fm.ascent(), ms_text,
                    )
                    pct_x = ms_x + row['ms_w'] + 8
                    painter.setPen(color)
                    painter.drawText(
                        int(pct_x + row['pct_w'] - fm.horizontalAdvance(pct_text)),
                        cur_y + fm.ascent(), pct_text,
                    )
                    # 占比条：主行相对帧周期，Unaccounted 子行相对 Unaccounted
                    bar_x = pct_x + row['pct_w'] + 8
                    bar_w = (x + margin + content_w - 6) - bar_x
                    bar_h = fm.height() - 3
                    painter.fillRect(
                        int(bar_x), int(cur_y + 1), int(bar_w), int(bar_h),
                        QColor(30, 35, 51),
                    )
                    frac = min(1.0, max(0.0, value_ms / max(bar_ref, 1e-6)))
                    if frac > 0.01:
                        painter.fillRect(
                            int(bar_x), int(cur_y + 1),
                            max(1, int(bar_w * frac)), int(bar_h),
                            color,
                        )
                    cur_y += table_row_h
                cur_y += 4
        if cpu is not None:
            cpu.add('qpainter_overlay_draw', time.perf_counter() - t_cpu)

    def _draw_frame_trend(self, painter, x, y, w, h, periods):
        """绘制最近帧周期趋势（ms）：折线 + 平均值虚线。"""
        if len(periods) < 2 or w <= 0 or h <= 0:
            return
        max_p = max(periods)
        if max_p <= 0.0:
            return
        step = w / (len(periods) - 1)
        inner_h = h - 2

        # 基线
        painter.setPen(PROFILER_BORDER)
        painter.drawLine(int(x), int(y + h - 1), int(x + w), int(y + h - 1))

        # 帧周期折线
        pen = QPen(PROFILER_TREND)
        pen.setWidth(1)
        painter.setPen(pen)
        points = [
            (x + i * step, y + h - 1 - (p / max_p) * inner_h)
            for i, p in enumerate(periods)
        ]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        # 平均值虚线
        avg = sum(periods) / len(periods)
        y_avg = y + h - 1 - (avg / max_p) * inner_h
        pen = QPen(PROFILER_WARN)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(int(x), int(y_avg), int(x + w), int(y_avg))

    @staticmethod
    def _profiler_rows(s: dict, periods: list) -> list:
        """把 FrameProfiler.summary() 组织为阶段明细表（真实计算 vs 等待）。"""

        def ms(key: str) -> str:
            return f"{s[key]:.1f}"

        period = max(s['frame_period'], 1e-6)

        def pct_frame(v: float) -> str:
            return f"{v / period * 100.0:.1f}%"

        return [
            {'type': 'title', 'title': '性能分析'},
            {'type': 'metrics', 'items': [
                ('FPS', f"{s['fps']:.1f}"),
                ('Frame', f"{ms('period_avg_ms')}ms"),
                ('p95', f"{ms('period_p95_ms')}ms"),
                ('峰值', f"{ms('period_max_ms')}ms"),
            ]},
            {'type': 'sparkline', 'periods': periods},
            {'type': 'table', 'rows': [
                ('Physics', s['physics_ms'], pct_frame(s['physics_ms']), PROFILER_PHYSICS, period),
                ('  1 Force', s['force_ms'], pct_frame(s['force_ms']), PROFILER_PHYSICS, period),
                ('  2 Integrator', s['integrator_update_ms'], pct_frame(s['integrator_update_ms']), PROFILER_PHYSICS, period),
                ('  3 Collision', s['collision_ms'], pct_frame(s['collision_ms']), PROFILER_PHYSICS, period),
                ('  4 Trail', s['trail_ms'], pct_frame(s['trail_ms']), PROFILER_PHYSICS, period),
                ('  5 Body update', s['body_update_ms'], pct_frame(s['body_update_ms']), PROFILER_PHYSICS, period),
                ('UI callbacks', s['ui_ms'], pct_frame(s['ui_ms']), PROFILER_UI, period),
                ('Render CPU', s['render_cpu_ms'], pct_frame(s['render_cpu_ms']), PROFILER_RENDER, period),
                ('GPU Wait', s['gpu_wait_ms'], pct_frame(s['gpu_wait_ms']), PROFILER_WARN, period),
                ('Render Wall', s['render_wall_ms'], pct_frame(s['render_wall_ms']), PROFILER_RENDER, period),
                ('Qt dispatch', s['qt_dispatch_ms'], pct_frame(s['qt_dispatch_ms']), PROFILER_UI, period),
                ('Unaccounted', s['unaccounted_ms'], pct_frame(s['unaccounted_ms']), PROFILER_WARN, period),
            ]},
            {'type': 'metrics', 'items': [
                ('天体', f"{s['bodies']:.0f}"),
                ('子步/帧', f"{s['substeps']:.1f}"),
                ('融合', f"{s['merges']:.2f}"),
                ('物理', f"{ms('physics_ms')}ms"),
            ]},
        ]
    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下"""
        self._mouse_pressed = True
        self._mouse_button = event.button()
        self._last_mouse_pos = event.position()
        
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_click(event.position())
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动"""
        if self._mouse_pressed and self._mouse_button == Qt.MouseButton.MiddleButton:
            current_pos = event.position()
            dx = current_pos.x() - self._last_mouse_pos.x()
            dy = current_pos.y() - self._last_mouse_pos.y()
            self.camera.pan(dx, dy)
            self._last_mouse_pos = current_pos
            self.camera_changed.emit()
            self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放"""
        self._mouse_pressed = False
        self._mouse_button = None
    
    def wheelEvent(self, event: QWheelEvent):
        """滚轮缩放"""
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        
        pos = event.position()
        self.camera.zoom_at_point(pos.x(), pos.y(), factor)
        self.camera_changed.emit()
        self.update()
    
    def _handle_click(self, screen_pos):
        """处理点击"""
        sx = screen_pos.x()
        sy = screen_pos.y()
        
        for i, body in enumerate(self.engine.bodies):
            body_sx, body_sy = self.camera.world_to_screen(
                body.position[0], body.position[1]
            )
            
            screen_radius = body.render_radius * self.camera.zoom
            screen_radius = max(screen_radius, self.min_render_radius_px)
            
            dist = np.sqrt((sx - body_sx)**2 + (sy - body_sy)**2)
            if dist <= screen_radius:
                self._selected_body_index = i
                self.body_clicked.emit(i)
                self.update()
                return
        
        # 点击空白处取消选择
        self._selected_body_index = -1
        self.update()
