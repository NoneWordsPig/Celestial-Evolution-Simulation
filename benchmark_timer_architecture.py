"""
Timer Architecture Performance Benchmark
用于测试当前timer架构的性能，为优化决策提供数据支持
"""
import time
import sys
from collections import defaultdict, deque
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication


class MockPhysicsEngine:
    """模拟物理引擎"""
    def __init__(self):
        self.simulation_time = 0.0
        self.bodies = []
        self.step_count = 0
        
    def step(self):
        """模拟物理步进"""
        self.simulation_time += 0.033
        self.step_count += 1
        
    def advance(self, wall_seconds):
        """模拟物理推进"""
        steps = int(wall_seconds * 30)
        for _ in range(steps):
            self.step()
        return steps


class OriginalTimerArchitecture(QObject):
    """原始多Timer架构"""
    
    frame_processed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.engine = MockPhysicsEngine()
        self.profiler = None
        
        # 原始Timer配置
        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self._on_physics_tick)
        
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._on_render_tick)
        
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._on_status_tick)
        
        self.inspector_timer = QTimer(self)
        self.inspector_timer.timeout.connect(self._on_inspector_tick)
        
        self.ref_frame_timer = QTimer(self)
        self.ref_frame_timer.timeout.connect(self._on_ref_frame_tick)
        
        # 性能统计
        self.stats = {
            'physics_ticks': 0,
            'render_ticks': 0,
            'status_ticks': 0,
            'inspector_ticks': 0,
            'ref_frame_ticks': 0,
            'total_events': 0,
            'frame_times': deque(maxlen=1000),
            'qt_dispatch_times': deque(maxlen=1000)
        }
        
        self._last_frame_time = None
        
    def start(self):
        """启动所有timer"""
        self.physics_timer.start(33)   # 30Hz
        self.render_timer.start(17)    # 60Hz
        self.status_timer.start(100)   # 10Hz
        self.inspector_timer.start(100) # 10Hz
        self.ref_frame_timer.start(50)  # 20Hz
        
    def stop(self):
        """停止所有timer"""
        self.physics_timer.stop()
        self.render_timer.stop()
        self.status_timer.stop()
        self.inspector_timer.stop()
        self.ref_frame_timer.stop()
    
    def _on_physics_tick(self):
        """物理tick"""
        t0 = time.perf_counter()
        self.engine.step()
        self.stats['physics_ticks'] += 1
        self.stats['total_events'] += 1
        self._record_event_time(t0)
    
    def _on_render_tick(self):
        """渲染tick"""
        t0 = time.perf_counter()
        # 模拟渲染请求
        self.stats['render_ticks'] += 1
        self.stats['total_events'] += 1
        self._record_event_time(t0)
        self._emit_frame_processed()
    
    def _on_status_tick(self):
        """状态更新tick"""
        t0 = time.perf_counter()
        # 模拟状态更新
        self.stats['status_ticks'] += 1
        self.stats['total_events'] += 1
        self._record_event_time(t0)
    
    def _on_inspector_tick(self):
        """检查器更新tick"""
        t0 = time.perf_counter()
        # 模拟检查器更新
        self.stats['inspector_ticks'] += 1
        self.stats['total_events'] += 1
        self._record_event_time(t0)
    
    def _on_ref_frame_tick(self):
        """参考系更新tick"""
        t0 = time.perf_counter()
        # 模拟参考系更新
        self.stats['ref_frame_ticks'] += 1
        self.stats['total_events'] += 1
        self._record_event_time(t0)
    
    def _record_event_time(self, t0):
        """记录事件处理时间"""
        duration = time.perf_counter() - t0
        self.stats['qt_dispatch_times'].append(duration * 1000)  # 转为ms
        
        if self._last_frame_time is not None:
            frame_time = time.perf_counter() - self._last_frame_time
            self.stats['frame_times'].append(frame_time * 1000)
        self._last_frame_time = time.perf_counter()
    
    def _emit_frame_processed(self):
        """发送帧处理完成信号"""
        frame_data = {
            'timestamp': time.time(),
            'frame_time': self.stats['frame_times'][-1] if self.stats['frame_times'] else 0,
            'qt_dispatch_time': self.stats['qt_dispatch_times'][-1] if self.stats['qt_dispatch_times'] else 0
        }
        self.frame_processed.emit(frame_data)
    
    def get_statistics(self):
        """获取统计信息"""
        return self.stats.copy()


def benchmark_original_architecture(duration_seconds=10):
    """测试原始架构性能"""
    print("="*70)
    print("Benchmarking Original Timer Architecture")
    print("="*70)
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    architecture = OriginalTimerArchitecture()
    
    # 收集帧数据
    frame_data = []
    
    def on_frame_processed(data):
        frame_data.append(data)
    
    architecture.frame_processed.connect(on_frame_processed)
    
    # 运行benchmark
    print(f"\\nRunning benchmark for {duration_seconds} seconds...")
    architecture.start()
    
    start_time = time.time()
    while time.time() - start_time < duration_seconds:
        app.processEvents()
        time.sleep(0.01)
    
    architecture.stop()
    
    # 分析结果
    stats = architecture.get_statistics()
    
    print("\\n" + "="*70)
    print("Original Architecture Results")
    print("="*70)
    
    total_time = duration_seconds
    print(f"\\nTimer Events:")
    print(f"  Physics ticks:   {stats['physics_ticks']:>6} ({stats['physics_ticks']/total_time:>6.1f} Hz)")
    print(f"  Render ticks:    {stats['render_ticks']:>6} ({stats['render_ticks']/total_time:>6.1f} Hz)")
    print(f"  Status ticks:    {stats['status_ticks']:>6} ({stats['status_ticks']/total_time:>6.1f} Hz)")
    print(f"  Inspector ticks: {stats['inspector_ticks']:>6} ({stats['inspector_ticks']/total_time:>6.1f} Hz)")
    print(f"  RefFrame ticks:  {stats['ref_frame_ticks']:>6} ({stats['ref_frame_ticks']/total_time:>6.1f} Hz)")
    print(f"  Total events:    {stats['total_events']:>6} ({stats['total_events']/total_time:>6.1f} Hz)")
    
    if stats['qt_dispatch_times']:
        qt_times = list(stats['qt_dispatch_times'])
        print(f"\\nQt Dispatch Performance:")
        print(f"  Average: {sum(qt_times)/len(qt_times):.3f} ms")
        print(f"  Min:     {min(qt_times):.3f} ms")
        print(f"  Max:     {max(qt_times):.3f} ms")
        print(f"  Total:   {sum(qt_times):.1f} ms")
        print(f"  Per sec: {sum(qt_times)/total_time:.1f} ms/sec")
    
    if stats['frame_times']:
        frame_times = list(stats['frame_times'])
        print(f"\\nFrame Performance:")
        print(f"  Average: {sum(frame_times)/len(frame_times):.1f} ms")
        print(f"  Min:     {min(frame_times):.1f} ms")
        print(f"  Max:     {max(frame_times):.1f} ms")
        fps = 1000.0 / (sum(frame_times)/len(frame_times)) if frame_times else 0
        print(f"  FPS:     {fps:.1f}")
    
    print(f"\\nTimer Overhead Analysis:")
    print(f"  Total timer frequency: {stats['total_events']/total_time:.1f} Hz")
    print(f"  Events per frame: {stats['total_events']/len(frame_data) if frame_data else 0:.1f}")
    print(f"  Estimated overhead: {stats['total_events']/total_time * 0.1:.1f} ms/sec")
    
    return stats


if __name__ == '__main__':
    try:
        results = benchmark_original_architecture(duration_seconds=5)
        print("\\n" + "="*70)
        print("Benchmark Complete")
        print("="*70)
        print("\\nRecommendation:")
        total_freq = results['total_events'] / 5.0  # 5秒测试
        if total_freq > 100:
            print(f"RECOMMEND: Unified scheduler (current: {total_freq:.0f}Hz > 100Hz threshold)")
        else:
            print(f"ACCEPTABLE: Current architecture (current: {total_freq:.0f}Hz is reasonable)")
    except Exception as e:
        print(f"Benchmark failed: {e}")
        print("Note: This requires a Qt environment to run properly")
