"""
Qt Event Loop 详细分析器
用于分析Qt事件分发、QTimer竞争、渲染瓶颈等
"""
import time
import threading
from collections import defaultdict, deque
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from PyQt6.QtCore import QObject, QTimerEvent


@dataclass
class EventStats:
    """事件统计"""
    count: int = 0
    total_time: float = 0.0
    max_time: float = 0.0
    min_time: float = float('inf')
    last_time: float = 0.0
    
    def add(self, duration: float):
        self.count += 1
        self.total_time += duration
        self.max_time = max(self.max_time, duration)
        self.min_time = min(self.min_time, duration)
        self.last_time = duration
    
    def avg_time(self) -> float:
        return self.total_time / self.count if self.count > 0 else 0.0


class QtEventAnalyzer:
    """
    Qt事件循环详细分析器
    
    监控：
    1. QApplication事件分发
    2. 各个QTimer的触发和耗时
    3. paintGL调用频率和耗时
    4. update()调用频率
    5. 空闲时间
    """
    
    def __init__(self):
        self.enabled = False
        self.start_time = time.perf_counter()
        
        # 事件统计
        self.event_stats: Dict[str, EventStats] = defaultdict(EventStats)
        self.timer_stats: Dict[str, EventStats] = defaultdict(EventStats)
        
        # 调用频率统计
        self.update_calls = 0
        self.paintgl_calls = 0
        self.swapbuffer_calls = 0
        
        # 时间线记录
        self.timeline: deque = deque(maxlen=1000)
        self.last_paintgl_time = None
        self.paintgl_intervals: deque = deque(maxlen=100)
        
        # 帧统计
        self.frame_count = 0
        self.frame_times: deque = deque(maxlen=60)
        
        # 线程安全锁
        self.lock = threading.Lock()
        
        # 计时器名称映射
        self.timer_names: Dict[int, str] = {}
        
    def enable(self):
        """启用分析"""
        self.enabled = True
        self.start_time = time.perf_counter()
        
    def disable(self):
        """禁用分析"""
        self.enabled = False
        
    def record_event(self, event_type: str, duration: float):
        """记录事件处理时间"""
        if not self.enabled:
            return
            
        with self.lock:
            stats = self.event_stats[event_type]
            stats.add(duration)
            
            # 添加到时间线
            self.timeline.append({
                'time': time.perf_counter() - self.start_time,
                'type': 'event',
                'name': event_type,
                'duration': duration
            })
    
    def record_timer(self, timer_id: int, callback_name: str, duration: float):
        """记录计时器回调时间"""
        if not self.enabled:
            return
            
        timer_name = self.timer_names.get(timer_id, f"Timer_{timer_id}")
        full_name = f"{timer_name}:{callback_name}"
        
        with self.lock:
            stats = self.timer_stats[full_name]
            stats.add(duration)
            
            # 添加到时间线
            self.timeline.append({
                'time': time.perf_counter() - self.start_time,
                'type': 'timer',
                'name': full_name,
                'duration': duration
            })
    
    def register_timer(self, timer_id: int, name: str):
        """注册计时器名称"""
        self.timer_names[timer_id] = name
        
    def record_update(self):
        """记录update()调用"""
        if not self.enabled:
            return
        self.update_calls += 1
        
    def record_paintgl(self, duration: float):
        """记录paintGL调用"""
        if not self.enabled:
            return
            
        with self.lock:
            self.paintgl_calls += 1
            now = time.perf_counter()
            
            # 计算paintGL间隔
            if self.last_paintgl_time is not None:
                interval = now - self.last_paintgl_time
                self.paintgl_intervals.append(interval)
            self.last_paintgl_time = now
            
            # 记录paintGL统计
            stats = self.event_stats['paintGL']
            stats.add(duration)
            
            # 添加到时间线
            self.timeline.append({
                'time': now - self.start_time,
                'type': 'render',
                'name': 'paintGL',
                'duration': duration
            })
    
    def record_swapbuffer(self, duration: float):
        """记录swapBuffers调用"""
        if not self.enabled:
            return
        self.swapbuffer_calls += 1
        
        with self.lock:
            stats = self.event_stats['swapBuffers']
            stats.add(duration)
    
    def record_frame(self, duration: float):
        """记录完整帧时间"""
        if not self.enabled:
            return
            
        with self.lock:
            self.frame_count += 1
            self.frame_times.append(duration)
    
    def get_summary(self) -> Dict:
        """获取统计摘要"""
        with self.lock:
            current_time = time.perf_counter()
            elapsed = current_time - self.start_time
            
            # 计算平均值
            avg_paintgl_interval = 0.0
            if self.paintgl_intervals:
                avg_paintgl_interval = sum(self.paintgl_intervals) / len(self.paintgl_intervals)
            
            avg_frame_time = 0.0
            if self.frame_times:
                avg_frame_time = sum(self.frame_times) / len(self.frame_times)
            
            return {
                'elapsed_seconds': elapsed,
                'update_calls': self.update_calls,
                'paintgl_calls': self.paintgl_calls,
                'swapbuffer_calls': self.swapbuffer_calls,
                'frame_count': self.frame_count,
                'update_rate': self.update_calls / elapsed if elapsed > 0 else 0.0,
                'paintgl_rate': self.paintgl_calls / elapsed if elapsed > 0 else 0.0,
                'frame_rate': self.frame_count / elapsed if elapsed > 0 else 0.0,
                'avg_paintgl_interval_ms': avg_paintgl_interval * 1000.0,
                'avg_frame_time_ms': avg_frame_time * 1000.0,
                'event_stats': {
                    name: {
                        'count': stats.count,
                        'total_ms': stats.total_time * 1000.0,
                        'avg_ms': stats.avg_time() * 1000.0,
                        'max_ms': stats.max_time * 1000.0,
                        'min_ms': stats.min_time * 1000.0 if stats.min_time != float('inf') else 0.0,
                    }
                    for name, stats in self.event_stats.items()
                },
                'timer_stats': {
                    name: {
                        'count': stats.count,
                        'total_ms': stats.total_time * 1000.0,
                        'avg_ms': stats.avg_time() * 1000.0,
                        'max_ms': stats.max_time * 1000.0,
                        'rate': stats.count / elapsed if elapsed > 0 else 0.0,
                    }
                    for name, stats in self.timer_stats.items()
                }
            }
    
    def print_detailed_report(self):
        """打印详细报告"""
        summary = self.get_summary()
        
        print("=" * 80)
        print("Qt Event Loop Detailed Analysis Report")
        print("=" * 80)
        print()
        
        # 基本信息
        print(f"Analysis Duration: {summary['elapsed_seconds']:.2f} seconds")
        print(f"Total Frames: {summary['frame_count']}")
        print(f"Frame Rate: {summary['frame_rate']:.1f} FPS")
        print()
        
        # 调用频率
        print("Call Frequencies:")
        print("-" * 80)
        print(f"update() calls:       {summary['update_calls']:6d} ({summary['update_rate']:6.1f} calls/sec)")
        print(f"paintGL() calls:     {summary['paintgl_calls']:6d} ({summary['paintgl_rate']:6.1f} calls/sec)")
        print(f"swapBuffers() calls: {summary['swapbuffer_calls']:6d}")
        print(f"Avg paintGL interval: {summary['avg_paintgl_interval_ms']:6.2f} ms")
        print()
        
        # 事件统计
        print("Event Processing Times:")
        print("-" * 80)
        print(f"{'Event':<20} {'Count':>8} {'Total(ms)':>12} {'Avg(ms)':>10} {'Max(ms)':>10}")
        print("-" * 80)
        
        event_stats = summary['event_stats']
        for name in sorted(event_stats.keys()):
            stats = event_stats[name]
            print(f"{name:<20} {stats['count']:>8} {stats['total_ms']:>12.2f} {stats['avg_ms']:>10.2f} {stats['max_ms']:>10.2f}")
        
        print()
        
        # 计时器统计
        print("Timer Callback Statistics:")
        print("-" * 80)
        print(f"{'Timer':<30} {'Count':>8} {'Total(ms)':>12} {'Avg(ms)':>10} {'Rate(Hz)':>10}")
        print("-" * 80)
        
        timer_stats = summary['timer_stats']
        for name in sorted(timer_stats.keys()):
            stats = timer_stats[name]
            print(f"{name:<30} {stats['count']:>8} {stats['total_ms']:>12.2f} {stats['avg_ms']:>10.2f} {stats['rate']:>10.1f}")
        
        print()
        
        # 帧时间分析
        if self.frame_times:
            print("Frame Time Analysis:")
            print("-" * 80)
            frame_times_ms = [t * 1000.0 for t in self.frame_times]
            print(f"Avg Frame Time: {sum(frame_times_ms) / len(frame_times_ms):.2f} ms")
            print(f"Min Frame Time: {min(frame_times_ms):.2f} ms")
            print(f"Max Frame Time: {max(frame_times_ms):.2f} ms")
            print()
        
        # 性能瓶颈分析
        print("Performance Bottleneck Analysis:")
        print("-" * 80)
        
        # 找出耗时最长的事件
        if event_stats:
            sorted_events = sorted(event_stats.items(), key=lambda x: x[1]['avg_ms'], reverse=True)
            if sorted_events:
                slowest_event = sorted_events[0]
                print(f"Slowest Event: {slowest_event[0]} (avg {slowest_event[1]['avg_ms']:.2f} ms)")
        
        # 找出最频繁的计时器
        if timer_stats:
            sorted_timers = sorted(timer_stats.items(), key=lambda x: x[1]['rate'], reverse=True)
            if sorted_timers:
                most_frequent_timer = sorted_timers[0]
                print(f"Most Frequent Timer: {most_frequent_timer[0]} ({most_frequent_timer[1]['rate']:.1f} Hz)")
        
        # 检查paintGL调用频率
        if summary['paintgl_rate'] < 30:
            print(f"WARNING: Low paintGL rate ({summary['paintgl_rate']:.1f} Hz) - may cause rendering lag")
        
        # 检查update()调用频率
        if summary['update_rate'] > 100:
            print(f"WARNING: High update() rate ({summary['update_rate']:.1f} Hz) - may indicate unnecessary redraws")
        
        print()
        print("=" * 80)
    
    def export_timeline(self, filename: str):
        """导出时间线到CSV"""
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['time', 'type', 'name', 'duration'])
            for entry in self.timeline:
                writer.writerow([
                    f"{entry['time']:.6f}",
                    entry['type'],
                    entry['name'],
                    f"{entry['duration']:.6f}"
                ])
        print(f"Timeline exported to {filename}")


# 全局分析器实例
_global_analyzer = QtEventAnalyzer()

def get_global_analyzer() -> QtEventAnalyzer:
    """获取全局分析器实例"""
    return _global_analyzer
