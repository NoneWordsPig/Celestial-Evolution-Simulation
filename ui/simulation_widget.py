"""
模拟视图

OpenGL 渲染视图，显示天体和轨迹
添加比例尺显示和参考系支持
"""

import numpy as np
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QPainter, QPen, QFont
import OpenGL.GL as gl

from physics import (
    PhysicsEngine, Camera, Body, Mode, UnitSystem, UnitConverter,
    SimulationFormatter, ScientificFormatter,
    ReferenceFrame, ScaleBar
)


class SimulationWidget(QOpenGLWidget):
    """
    OpenGL 模拟视图
    
    负责：
    - 渲染天体（正圆）
    - 渲染轨迹
    - 渲染比例尺
    - 处理鼠标交互
    """
    
    # 信号
    body_clicked = pyqtSignal(int)
    camera_changed = pyqtSignal()
    
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
        
        # 动画
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_animation_tick)
        self._is_paused = False
        self._target_fps = 60
        
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
        """启动动画"""
        interval = int(1000 / self._target_fps)
        self._animation_timer.start(interval)
    
    def stop_animation(self):
        """停止动画"""
        self._animation_timer.stop()
    
    def pause(self):
        """暂停"""
        self._is_paused = True
    
    def resume(self):
        """恢复"""
        self._is_paused = False
    
    def step(self):
        """单步"""
        self.engine.step()
        self.update()
    
    def _on_animation_tick(self):
        """动画回调"""
        if not self._is_paused:
            self.engine.step()
        self.update()
    
    def initializeGL(self):
        """初始化 OpenGL"""
        gl.glClearColor(0.05, 0.05, 0.08, 1.0)
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
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        
        # 绘制轨迹
        if self._show_trails:
            self._draw_trails()
        
        # 绘制天体
        self._draw_bodies()
        
        # 使用 QPainter 绘制 2D overlay（比例尺）
        self._draw_overlay()
    
    def _draw_bodies(self):
        """绘制所有天体"""
        for i, body in enumerate(self.engine.bodies):
            self._draw_body(body, i)
    
    def _draw_body(self, body: Body, index: int):
        """绘制单个天体（正圆）"""
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
        
        # 关键修复：使用不同的 x/y 半径来补偿宽高比
        # NDC 中 x 范围 [-1, 1] 对应宽度 w 像素
        # NDC 中 y 范围 [-1, 1] 对应高度 h 像素
        # 所以 screen_radius 像素在 NDC 中需要不同的 x/y 半径
        ndc_rx = screen_radius / w * 2.0  # x 方向的 NDC 半径
        ndc_ry = screen_radius / h * 2.0  # y 方向的 NDC 半径
        
        # 绘制圆形（在 NDC 中是椭圆，但在屏幕上是正圆）
        color = body.color
        gl.glColor4f(color[0], color[1], color[2], 1.0)
        
        segments = 32
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(ndc_x, ndc_y)
        for j in range(segments + 1):
            angle = 2.0 * np.pi * j / segments
            gl.glVertex2f(
                ndc_x + ndc_rx * np.cos(angle),
                ndc_y + ndc_ry * np.sin(angle)
            )
        gl.glEnd()
        
        # 绘制边框
        gl.glColor4f(1.0, 1.0, 1.0, 0.5)
        gl.glBegin(gl.GL_LINE_LOOP)
        for j in range(segments):
            angle = 2.0 * np.pi * j / segments
            gl.glVertex2f(
                ndc_x + ndc_rx * np.cos(angle),
                ndc_y + ndc_ry * np.sin(angle)
            )
        gl.glEnd()
    
    def _draw_trails(self):
        """绘制轨迹"""
        for body in self.engine.bodies:
            if len(body.trail) < 2:
                continue
            self._draw_trail(body)
    
    def _draw_trail(self, body: Body):
        """绘制单个轨迹"""
        trail = body.trail[-self._max_trail_length:]
        
        color = body.color
        gl.glColor4f(color[0], color[1], color[2], 0.3)
        gl.glLineWidth(1.0)
        
        gl.glBegin(gl.GL_LINE_STRIP)
        for pos in trail:
            sx, sy = self.camera.world_to_screen(pos[0], pos[1])
            w = self.camera.viewport_width
            h = self.camera.viewport_height
            ndc_x = (sx / w) * 2.0 - 1.0
            ndc_y = 1.0 - (sy / h) * 2.0
            gl.glVertex2f(ndc_x, ndc_y)
        gl.glEnd()
    
    def _draw_overlay(self):
        """绘制 2D overlay（比例尺）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 绘制比例尺
        self._draw_scale_bar(painter)
        
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
        pen = QPen(Qt.GlobalColor.white)
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
        painter.setPen(Qt.GlobalColor.white)
        
        # 计算文本位置（居中）
        text_width = painter.fontMetrics().horizontalAdvance(label)
        text_x = x + (pixel_len - text_width) / 2
        painter.drawText(int(text_x), int(y - 10), label)
    
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
                self.body_clicked.emit(i)
                return
