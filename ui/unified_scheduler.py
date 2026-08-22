"""
统一帧调度器
用一个主Timer替代多个QTimer，减少GUI线程事件数量
"""
import time
from typing import Callable, Optional
from PyQt6.QtCore import QObject, QTimer


class UnifiedFrameScheduler(QObject):
    """
    统一帧调度器
    
    目标：用一个60Hz主Timer替代原有的多个QTimer
    - Physics: 30Hz固定timestep，保持原有逻辑
    - Render: 60Hz刷新频率
    - Status UI: 10Hz更新频率  
    - Inspector UI: 10Hz更新频率
    - Reference Frame: 20Hz更新频率
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 主Timer: 60Hz
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._on_frame_tick)
        
        # 回调函数
        self._physics_step_callback = None      # 物理步进回调
        self._render_request_callback = None    # 渲染请求回调
        self._status_update_callback = None     # 状态更新回调
        self._inspector_update_callback = None  # 检查器更新回调
        self._ref_frame_update_callback = None  # 参考系更新回调
        
        # 状态控制
        self._is_running = False
        self._is_paused = False
        
        # Physics accumulator (保持原有fixed timestep逻辑)
        self._physics_accumulator = 0.0
        self._physics_dt = 1.0 / 30.0  # 30Hz physics
        self._last_tick_time = None
        
        # 计数器 (用于控制不同频率的UI更新)
        self._frame_count = 0
        self._status_update_interval = 6   # 60Hz / 10Hz = 6 frames
        self._inspector_update_interval = 6  # 60Hz / 10Hz = 6 frames  
        self._ref_frame_update_interval = 3  # 60Hz / 20Hz = 3 frames
        
        # 性能统计
        self._total_ticks = 0
        self._physics_steps = 0
        self._render_requests = 0
        self._ui_updates = 0
    
    def set_physics_step_callback(self, callback: Callable[[float], int]):
        """设置物理步进回调函数
        
        Args:
            callback: 接收wall_seconds参数，返回执行的物理步数
        """
        self._physics_step_callback = callback
    
    def set_render_request_callback(self, callback: Callable[[], None]):
        """设置渲染请求回调函数"""
        self._render_request_callback = callback
    
    def set_status_update_callback(self, callback: Callable[[], None]):
        """设置状态更新回调函数"""
        self._status_update_callback = callback
    
    def set_inspector_update_callback(self, callback: Callable[[], None]):
        """设置检查器更新回调函数"""
        self._inspector_update_callback = callback
    
    def set_ref_frame_update_callback(self, callback: Callable[[], None]):
        """设置参考系更新回调函数"""
        self._ref_frame_update_callback = callback
    
    def set_physics_dt(self, dt: float):
        """设置物理时间步长"""
        self._physics_dt = dt
    
    def start(self):
        """启动调度器"""
        if self._is_running:
            return
            
        self._is_running = True
        self._is_paused = False
        self._last_tick_time = time.perf_counter()
        self._frame_count = 0
        self._frame_timer.start(int(1000 / 60))  # 60Hz主Timer
    
    def stop(self):
        """停止调度器"""
        self._is_running = False
        self._frame_timer.stop()
    
    def pause(self):
        """暂停物理计算，但继续渲染"""
        self._is_paused = True
        self._physics_accumulator = 0.0
        self._last_tick_time = None
    
    def resume(self):
        """恢复物理计算"""
        self._is_paused = False
        self._last_tick_time = time.perf_counter()
    
    def _on_frame_tick(self):
        """主帧tick处理 - 每16.7ms调用一次 (60Hz)"""
        self._total_ticks += 1
        self._frame_count += 1
        
        # 1. Physics步进 (保持原有fixed timestep + accumulator逻辑)
        if not self._is_paused and self._physics_step_callback:
            now = time.perf_counter()
            if self._last_tick_time is None:
                wall_dt = self._physics_dt  # 第一帧使用默认值
            else:
                wall_dt = now - self._last_tick_time
                # 防止窗口卡顿后一次性追赶过大
                wall_dt = min(wall_dt, 0.1)
            
            self._last_tick_time = now
            
            # 执行物理步进 (使用原有的accumulator逻辑)
            steps = self._physics_step_callback(wall_dt)
            self._physics_steps += steps
        
        # 2. 渲染请求 (每次都请求，60Hz)
        if self._render_request_callback:
            self._render_request_callback()
            self._render_requests += 1
        
        # 3. UI更新 (按频率控制)
        # Status update: 10Hz (每6帧一次)
        if self._frame_count % self._status_update_interval == 0:
            if self._status_update_callback:
                self._status_update_callback()
                self._ui_updates += 1
        
        # Inspector update: 10Hz (每6帧一次)
        if self._frame_count % self._inspector_update_interval == 0:
            if self._inspector_update_callback:
                self._inspector_update_callback()
                self._ui_updates += 1
        
        # Reference frame update: 20Hz (每3帧一次)
        if self._frame_count % self._ref_frame_update_interval == 0:
            if self._ref_frame_update_callback:
                self._ref_frame_update_callback()
                self._ui_updates += 1
    
    def get_statistics(self) -> dict:
        """获取调度器统计信息"""
        return {
            'total_ticks': self._total_ticks,
            'physics_steps': self._physics_steps,
            'render_requests': self._render_requests,
            'ui_updates': self._ui_updates,
            'current_frame': self._frame_count,
            'is_running': self._is_running,
            'is_paused': self._is_paused
        }
    
    def reset_statistics(self):
        """重置统计信息"""
        self._total_ticks = 0
        self._physics_steps = 0
        self._render_requests = 0
        self._ui_updates = 0
        self._frame_count = 0


# 用于对比的原始多Timer架构信息
class TimerArchitectureInfo:
    """原始timer架构信息"""
    
    ORIGINAL_TIMERS = {
        'physics_timer': {'frequency': 30, 'interval_ms': 33.3, 'file': 'simulation_widget.py'},
        'render_timer': {'frequency': 60, 'interval_ms': 16.7, 'file': 'simulation_widget.py'},
        'status_timer': {'frequency': 10, 'interval_ms': 100.0, 'file': 'main_window.py'},
        'inspector_timer': {'frequency': 10, 'interval_ms': 100.0, 'file': 'main_window.py'},
        'ref_frame_timer': {'frequency': 20, 'interval_ms': 50.0, 'file': 'main_window.py'}
    }
    
    @classmethod
    def get_total_frequency(cls) -> float:
        """获取原始架构总频率"""
        return sum(timer['frequency'] for timer in cls.ORIGINAL_TIMERS.values())
    
    @classmethod
    def get_average_interval(cls) -> float:
        """获取原始架构平均间隔"""
        total_freq = cls.get_total_frequency()
        return 1000.0 / total_freq if total_freq > 0 else 0.0
    
    @classmethod
    def print_comparison(cls):
        """打印架构对比"""
        print("="*70)
        print("Timer Architecture Comparison")
        print("="*70)
        
        print("\nOriginal Architecture:")
        print(f"{'Timer':<20} {'Freq(Hz)':>12} {'Interval(ms)':>15}")
        print("-"*70)
        for name, config in cls.ORIGINAL_TIMERS.items():
            print(f"{name:<20} {config['frequency']:>12} {config['interval_ms']:>15.1f}")
        
        total_freq = cls.get_total_frequency()
        avg_interval = cls.get_average_interval()
        
        print(f"\nTotal frequency: {total_freq} Hz")
        print(f"Average interval: {avg_interval:.2f} ms")
        print(f"Events per frame (60Hz): {total_freq/60:.1f}")
        
        print("\nUnified Architecture:")
        print(f"{'Component':<20} {'Freq(Hz)':>12} {'Interval(ms)':>15}")
        print("-"*70)
        print(f"{'Main Frame Timer':<20} {60:>12} {16.7:>15.1f}")
        print(f"{'Physics (via accumulator)':<20} {30:>12} {33.3:>15.1f}")
        print(f"{'Render (every tick)':<20} {60:>12} {16.7:>15.1f}")
        print(f"{'Status Update':<20} {10:>12} {100.0:>15.1f}")
        print(f"{'Inspector Update':<20} {10:>12} {100.0:>15.1f}")
        print(f"{'Ref Frame Update':<20} {20:>12} {50.0:>15.1f}")
        
        print(f"\nTotal timer events: {60} Hz (single main timer)")
        print(f"Reduction: {(total_freq - 60)/total_freq*100:.1f}% fewer timer events")
        print("\n" + "="*70)


if __name__ == '__main__':
    TimerArchitectureInfo.print_comparison()
