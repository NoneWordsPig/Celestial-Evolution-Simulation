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
        self._max_trail_length = 500
        
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
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)  # 纯黑背景
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_LINE_SMOOTH)
    
    def resizeGL(self, w: int, h: int):
        """调整大小"""
        gl.glViewport(0, 0, w, h)
        self.camera.viewport_width = w
        self.camera.viewport_height = h
    
    def paintGL(self):
        """渲染"""
        profiler = self._profiler
        if profiler is not None:
            t0 = time.perf_counter()

        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        
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
            # GPU 同步等待：CPU 等 GPU 完成命令（仅分析，不改绘制）
            t_gpu = time.perf_counter()
            gl.glFinish()
            gpu_sync = time.perf_counter() - t_gpu
            profiler.add_render_parts(
                render=(t_end - t0) * 1000.0,
                trails=(t_bodies - t_trails) * 1000.0,
                render_bodies=(t_overlay - t_bodies) * 1000.0,
                overlay=(t_end - t_overlay) * 1000.0,
                gpu_sync=gpu_sync * 1000.0,
            )
    
    def _draw_bodies(self):
        """绘制所有天体"""
        for i, body in enumerate(self.engine.bodies):
            self._draw_body(body, i)
    
    def _draw_body(self, body: Body, index: int):
        """绘制单个天体（简洁明快风格）"""
        # 世界坐标 -> 屏幕坐标
        sx, sy = self.camera.world_to_screen(body.position[0], body.position[1])
        
        # 计算屏幕半径
        render_radius_world = body.render_radius
        screen_radius = render_radius_world * self.camera.zoom
        screen_radius = max(screen_radius, self.min_render_radius_px)
        
        # 转换为 NDC
        w = self.camera.viewport_width
        h = self.camera.viewport_height
        
        ndc_x = (sx / w) * 2.0 - 1.0
        ndc_y = 1.0 - (sy / h) * 2.0
        
        # 使用不同的 x/y 半径来补偿宽高比
        ndc_rx = screen_radius / w * 2.0
        ndc_ry = screen_radius / h * 2.0
        
        color = body.color
        segments = 32
        
        # 1. 柔和外发光（单层，低透明度）
        glow_radius_mult = 1.3
        gl.glColor4f(color[0], color[1], color[2], 0.15)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(ndc_x, ndc_y)
        for j in range(segments + 1):
            angle = 2.0 * np.pi * j / segments
            gl.glVertex2f(
                ndc_x + ndc_rx * glow_radius_mult * np.cos(angle),
                ndc_y + ndc_ry * glow_radius_mult * np.sin(angle)
            )
        gl.glEnd()
        
        # 2. 主体圆形（实心）
        gl.glColor4f(color[0], color[1], color[2], 1.0)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(ndc_x, ndc_y)
        for j in range(segments + 1):
            angle = 2.0 * np.pi * j / segments
            gl.glVertex2f(
                ndc_x + ndc_rx * np.cos(angle),
                ndc_y + ndc_ry * np.sin(angle)
            )
        gl.glEnd()
        
        # 3. 选中光环（保留，仅选中时显示）
        if index == self._selected_body_index:
            gl.glColor4f(1.0, 1.0, 1.0, 0.8)
            gl.glLineWidth(2.0)
            gl.glBegin(gl.GL_LINE_LOOP)
            for j in range(segments):
                angle = 2.0 * np.pi * j / segments
                gl.glVertex2f(
                    ndc_x + ndc_rx * 1.4 * np.cos(angle),
                    ndc_y + ndc_ry * 1.4 * np.sin(angle)
                )
            gl.glEnd()

    def _draw_trails(self):
        """绘制轨迹"""
        for body in self.engine.bodies:
            if len(body.trail) < 2:
                continue
            self._draw_trail(body)
    
    def _draw_trail(self, body: Body):
        """绘制单个轨迹（颜色 = 星体颜色，单条 GL_LINE_STRIP 渐变）"""
        trail = list(body.trail)[-self._max_trail_length:]

        if len(trail) < 2:
            return
        
        color = body.color
        w = self.camera.viewport_width
        h = self.camera.viewport_height
        n = len(trail)

        gl.glLineWidth(1.5)
        gl.glBegin(gl.GL_LINE_STRIP)
        for i, point in enumerate(trail):
            # 透明度渐变：越旧越透明，越新越亮
            alpha = 0.15 + 0.65 * (i / n)
            gl.glColor4f(
                float(color[0]), float(color[1]), float(color[2]), alpha
            )
            sx, sy = self.camera.world_to_screen(point[0], point[1])
            gl.glVertex2f((sx / w) * 2.0 - 1.0, 1.0 - (sy / h) * 2.0)
        gl.glEnd()
    
    def _draw_overlay(self):
        """绘制 2D overlay（比例尺 + 性能分析，均为只读覆盖层）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 绘制比例尺
        self._draw_scale_bar(painter)

        # 绘制性能分析（左上角覆盖层，不改变 UI 排版）
        self._draw_profiler_stats(painter)
        
        painter.end()
    
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
        summary = self._profiler.summary()
        if summary is None:
            return

        periods = self._profiler.frame_period_history_ms()
        rows = self._profiler_rows(summary, periods)

        title_font = QFont("Consolas")
        title_font.setPointSize(10)
        title_font.setBold(True)
        body_font = QFont("Consolas")
        body_font.setPointSize(9)

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
        """把 FrameProfiler.summary() 组织为 9 分类 + Unaccounted 细分表格。"""

        def ms(key: str) -> str:
            return f"{s[key]:.1f}"

        period = max(s['frame_period'], 1e-6)
        unaccounted = max(s['unaccounted_ms'], 1e-6)

        def pct_frame(v: float) -> str:
            return f"{v / period * 100.0:.1f}%"

        def pct_unacc(v: float) -> str:
            return f"{v / unaccounted * 100.0:.1f}%"

        return [
            {'type': 'title', 'title': '性能分析'},
            {'type': 'metrics', 'items': [
                ('FPS', f"{s['fps']:.1f}"),
                ('平均', f"{ms('period_avg_ms')}ms"),
                ('p95', f"{ms('period_p95_ms')}ms"),
                ('峰值', f"{ms('period_max_ms')}ms"),
            ]},
            {'type': 'sparkline', 'periods': periods},
            {'type': 'table', 'rows': [
                ('1 Force calculation', s['force_ms'], f"{s['pct_force']:.1f}%", PROFILER_PHYSICS, period),
                ('2 Integrator(RK4) update', s['integrator_update_ms'], f"{s['pct_integrator']:.1f}%", PROFILER_PHYSICS, period),
                ('3 Collision detection', s['collision_ms'], f"{s['pct_collision']:.1f}%", PROFILER_PHYSICS, period),
                ('4 Trail/history update', s['trajectory_ms'], f"{s['pct_trajectory']:.1f}%", PROFILER_PHYSICS, period),
                ('5 Body state update', s['body_state_ms'], f"{s['pct_body_state']:.1f}%", PROFILER_PHYSICS, period),
                ('6 Momentum calculation', s['momentum_ms'], f"{s['pct_momentum']:.1f}%", PROFILER_UI, period),
                ('7 Energy calculation', s['energy_ms'], f"{s['pct_energy']:.1f}%", PROFILER_UI, period),
                ('8 UI synchronization', s['ui_sync_ms'], f"{s['pct_ui_sync']:.1f}%", PROFILER_UI, period),
                ('9 Unaccounted Time', s['unaccounted_ms'], pct_frame(s['unaccounted_ms']), PROFILER_WARN, period),
                ('  a. Qt event processing', s['qt_events_ms'], pct_unacc(s['qt_events_ms']), PROFILER_WARN, unaccounted),
                ('  b. sleep / frame limiter', s['sleep_ms'], pct_unacc(s['sleep_ms']), PROFILER_WARN, unaccounted),
                ('  c. OS scheduling waiting', s['os_wait_ms'], pct_unacc(s['os_wait_ms']), PROFILER_WARN, unaccounted),
                ('  d. GPU synchronization', s['gpu_sync_ms'], pct_unacc(s['gpu_sync_ms']), PROFILER_WARN, unaccounted),
                ('  e. unknown / untracked', s['unknown_ms'], pct_unacc(s['unknown_ms']), PROFILER_WARN, unaccounted),
                ('Render', s['render_net_ms'], f"{s['pct_render']:.1f}%", PROFILER_RENDER, period),
            ]},
            {'type': 'metrics', 'items': [
                ('引擎', f"{ms('engine_ms')}ms"),
                ('天体', f"{s['bodies']:.0f}"),
                ('子步/帧', f"{s['substeps']:.1f}"),
                ('融合', f"{s['merges']:.2f}"),
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
