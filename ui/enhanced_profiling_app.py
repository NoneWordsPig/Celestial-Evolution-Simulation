"""
增强版Qt应用分析器
提供详细的Qt事件循环分析功能
"""
import time
from PyQt6.QtCore import QApplication, QEvent, QTimer
from PyQt6.QtWidgets import QWidget
from .qt_event_analyzer import get_global_analyzer


class EnhancedProfilingApplication(QApplication):
    """
    增强版分析应用
    
    在原有ProfilingApplication基础上，提供更详细的Qt事件分析：
    1. 按事件类型分类统计
    2. QTimer回调详细分析
    3. paintGL调用分析
    4. update()调用分析
    5. 空闲时间计算
    """
    
    def __init__(self, argv):
        super().__init__(argv)
        self.analyzer = get_global_analyzer()
        self._event_handlers = {}
        self._timer_callbacks = {}
        self._last_event_time = None
        self._idle_start_time = None
        self._total_idle_time = 0.0
        
    def notify(self, receiver, event):
        """重写notify方法来分析所有Qt事件"""
        analyzer = self.analyzer
        
        if not analyzer.enabled:
            return super().notify(receiver, event)
        
        # 记录事件开始时间
        event_start = time.perf_counter()
        
        # 特殊处理某些事件类型
        event_type = self._get_event_type_name(event.type())
        
        # 处理QTimer事件
        if event.type() == QEvent.Type.Timer:
            self._handle_timer_event(receiver, event, event_start)
        
        # 调用原始事件处理
        result = super().notify(receiver, event)
        
        # 记录事件处理时间
        event_duration = time.perf_counter() - event_start
        analyzer.record_event(event_type, event_duration)
        
        # 特殊处理paint事件
        if event.type() == QEvent.Type.Paint:
            analyzer.record_paintgl(event_duration)
        
        # 计算空闲时间
        self._update_idle_time(event_start)
        
        self._last_event_time = time.perf_counter()
        return result
    
    def _get_event_type_name(self, event_type) -> str:
        """获取事件类型名称"""
        try:
            return str(event_type).replace('QEvent.Type.', '')
        except:
            return f"Unknown_{event_type}"
    
    def _handle_timer_event(self, receiver, event, start_time):
        """处理计时器事件"""
        try:
            timer_id = event.timerId()
            
            # 尝试获取计时器信息
            if isinstance(receiver, QWidget):
                # 查找QTimer对象
                for child in receiver.findChildren(QTimer):
                    if child.timerId() == timer_id:
                        timer_name = self._get_timer_name(receiver, child)
                        self.analyzer.register_timer(timer_id, timer_name)
                        
                        # 记录计时器触发
                        callback_start = time.perf_counter()
                        break
        except:
            pass
    
    def _get_timer_name(self, receiver, timer) -> str:
        """获取计时器名称"""
        # 尝试从已知的计时器属性推断名称
        receiver_name = receiver.__class__.__name__
        
        # 检查已知的计时器属性
        known_timers = {
            '_physics_timer': 'PhysicsTimer',
            '_render_timer': 'RenderTimer', 
            '_status_timer': 'StatusTimer',
            '_inspector_timer': 'InspectorTimer',
            '_ref_frame_timer': 'RefFrameTimer',
            '_rate_check_timer': 'RateCheckTimer'
        }
        
        for attr_name, timer_name in known_timers.items():
            if hasattr(receiver, attr_name):
                if getattr(receiver, attr_name) is timer:
                    return f"{receiver_name}.{timer_name}"
        
        return f"{receiver_name}.Timer_{timer.timerId()}"
    
    def _update_idle_time(self, event_start):
        """更新空闲时间统计"""
        if self._last_event_time is not None:
            idle_duration = event_start - self._last_event_time
            if idle_duration > 0.001:  # 忽略微小空闲时间
                self.analyzer.record_event('idle', idle_duration)
                self._total_idle_time += idle_duration
    
    def start_analysis(self):
        """开始分析"""
        self.analyzer.enable()
        self._last_event_time = time.perf_counter()
        print("Qt Event Analysis Started")
    
    def stop_analysis(self):
        """停止分析"""
        self.analyzer.disable()
        print("Qt Event Analysis Stopped")
    
    def print_report(self):
        """打印分析报告"""
        self.analyzer.print_detailed_report()
        
    def get_frame_breakdown(self) -> dict:
        """获取帧时间分解"""
        summary = self.analyzer.get_summary()
        
        # 计算各部分时间
        total_time = summary['elapsed_seconds']
        if total_time == 0:
            return {}
        
        # 从事件统计中提取各部分时间
        event_stats = summary['event_stats']
        
        qt_dispatch = event_stats.get('Timer', {}).get('total_ms', 0.0)
        qt_dispatch += event_stats.get('Paint', {}).get('total_ms', 0.0)
        qt_dispatch += event_stats.get('UpdateRequest', {}).get('total_ms', 0.0)
        
        timer_callbacks = sum(
            stats['total_ms'] for stats in summary['timer_stats'].values()
        )
        
        paintgl_execution = event_stats.get('Paint', {}).get('total_ms', 0.0)
        
        swapbuffers = event_stats.get('swapBuffers', {}).get('total_ms', 0.0)
        
        idle_time = event_stats.get('idle', {}).get('total_ms', 0.0)
        
        # 计算其他时间
        total_accounted = qt_dispatch + timer_callbacks + paintgl_execution + swapbuffers + idle_time
        other = max(0.0, (total_time * 1000.0) - total_accounted)
        
        # 计算每帧平均值
        frame_count = max(1, summary['frame_count'])
        
        return {
            'qt_event_dispatch_ms_per_frame': qt_dispatch / frame_count,
            'timer_callbacks_ms_per_frame': timer_callbacks / frame_count,
            'paintgl_execution_ms_per_frame': paintgl_execution / frame_count,
            'swapbuffers_ms_per_frame': swapbuffers / frame_count,
            'idle_wait_ms_per_frame': idle_time / frame_count,
            'other_ms_per_frame': other / frame_count,
            'total_ms_per_frame': (total_time * 1000.0) / frame_count
        }


def create_profiling_app(argv):
    """创建分析应用实例"""
    return EnhancedProfilingApplication(argv)
