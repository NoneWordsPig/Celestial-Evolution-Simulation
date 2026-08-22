"""
Qt Event Loop 详细分析脚本
用于分析Qt事件分发、QTimer竞争、渲染瓶颈等
"""
import sys
import time
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QEvent

# 添加项目路径
sys.path.insert(0, '.')

from ui.main_window import MainWindow
from ui.styles import apply_global_style
from ui.qt_event_analyzer import QtEventAnalyzer


class QtEventAnalysisApplication(QApplication):
    """用于分析Qt事件循环的应用类"""
    
    def __init__(self, argv):
        super().__init__(argv)
        self.analyzer = QtEventAnalyzer()
        self.event_counts = defaultdict(int)
        self.event_times = defaultdict(float)
        self.timer_info = {}
        self.last_event_time = None
        self.total_idle_time = 0.0
        self.frame_count = 0
        self.paintgl_count = 0
        self.update_count = 0
        
    def notify(self, receiver, event):
        """分析所有Qt事件"""
        if not self.analyzer.enabled:
            return super().notify(receiver, event)
            
        event_start = time.perf_counter()
        event_type_name = self._get_event_name(event.type())
        
        # 特殊处理计时器事件
        if event.type() == QEvent.Type.Timer:
            self._handle_timer_event(receiver, event)
        
        # 调用原始处理
        result = super().notify(receiver, event)
        
        # 记录统计
        duration = time.perf_counter() - event_start
        self.event_counts[event_type_name] += 1
        self.event_times[event_type_name] += duration
        
        # 特殊事件处理
        if event.type() == QEvent.Type.Paint:
            self.paintgl_count += 1
            self.analyzer.record_paintgl(duration)
        elif event.type() == QEvent.Type.UpdateRequest:
            self.update_count += 1
            self.analyzer.record_update()
        
        # 计算空闲时间
        if self.last_event_time is not None:
            idle = event_start - self.last_event_time
            if idle > 0.001:  # 忽略微小空闲
                self.total_idle_time += idle
                self.analyzer.record_event('idle', idle)
        
        self.last_event_time = time.perf_counter()
        return result
    
    def _get_event_name(self, event_type) -> str:
        """获取事件名称"""
        try:
            return str(event_type).replace('QEvent.Type.', '')
        except:
            return f"Unknown({event_type})"
    
    def _handle_timer_event(self, receiver, event):
        """处理计时器事件，尝试识别计时器类型"""
        try:
            timer_id = event.timerId()
            if timer_id not in self.timer_info:
                # 尝试识别计时器
                timer_name = self._identify_timer(receiver, timer_id)
                self.timer_info[timer_id] = {
                    'name': timer_name,
                    'count': 0,
                    'total_time': 0.0
                }
            
            # 记录计时器触发
            self.timer_info[timer_id]['count'] += 1
        except Exception as e:
            pass
    
    def _identify_timer(self, receiver, timer_id) -> str:
        """尝试识别计时器名称"""
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
        
        for attr, name in known_timers.items():
            if hasattr(receiver, attr):
                timer_obj = getattr(receiver, attr)
                if hasattr(timer_obj, 'timerId') and timer_obj.timerId() == timer_id:
                    return f"{receiver_name}.{name}"
        
        return f"{receiver_name}.Timer_{timer_id}"
    
    def start_analysis(self):
        """开始分析"""
        self.analyzer.enable()
        self.start_time = time.perf_counter()
        print("Qt Event Analysis Started")
        
    def get_analysis_report(self) -> dict:
        """获取分析报告"""
        elapsed = time.perf_counter() - self.start_time if hasattr(self, 'start_time') else 0.0
        
        # 计算各阶段每帧平均时间
        frame_count = max(1, self.frame_count)
        
        return {
            'duration_seconds': elapsed,
            'frame_count': frame_count,
            'paintgl_count': self.paintgl_count,
            'update_count': self.update_count,
            'paintgl_rate': self.paintgl_count / elapsed if elapsed > 0 else 0,
            'update_rate': self.update_count / elapsed if elapsed > 0 else 0,
            'total_idle_time': self.total_idle_time,
            'idle_percentage': (self.total_idle_time / elapsed * 100) if elapsed > 0 else 0,
            'event_stats': dict(self.event_counts),
            'event_times': {k: v * 1000.0 for k, v in self.event_times.items()},  # 转换为ms
            'timer_info': self.timer_info
        }


def run_detailed_analysis():
    """运行详细的Qt事件分析"""
    print("="*80)
    print("Qt Event Loop Detailed Analysis")
    print("="*80)
    print()
    
    # 创建分析应用
    app = QtEventAnalysisApplication(sys.argv)
    app.setStyle('Fusion')
    apply_global_style(app)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 启动分析
    app.start_analysis()
    
    # 记录开始时间
    start_time = time.time()
    analysis_duration = 30.0  # 分析30秒
    
    print(f"Starting analysis for {analysis_duration} seconds...")
    print("Please interact with the application normally.")
    print()
    
    # 创建定时器来定期打印状态
    status_timer = QTimer()
    status_timer.timeout.connect(lambda: print_status_update(app, start_time))
    status_timer.start(5000)  # 每5秒打印一次状态
    
    # 创建定时器来停止分析
    stop_timer = QTimer()
    stop_timer.setSingleShot(True)
    stop_timer.timeout.connect(lambda: finalize_analysis(app, status_timer))
    stop_timer.start(int(analysis_duration * 1000))
    
    # 运行应用
    result = app.exec()
    
    return result


def print_status_update(app, start_time):
    """打印状态更新"""
    elapsed = time.time() - start_time
    report = app.get_analysis_report()
    
    print(f"[{elapsed:.1f}s] Status Update:")
    print(f"  paintGL calls: {report['paintgl_count']} ({report['paintgl_rate']:.1f} Hz)")
    print(f"  update() calls: {report['update_count']} ({report['update_rate']:.1f} Hz)")
    print(f"  Idle time: {report['total_idle_time']:.2f}s ({report['idle_percentage']:.1f}%)")
    print()


def finalize_analysis(app, status_timer):
    """完成分析并打印最终报告"""
    status_timer.stop()
    app.analyzer.disable()
    
    print()
    print("="*80)
    print("Final Analysis Report")
    print("="*80)
    print()
    
    # 使用分析器打印详细报告
    app.analyzer.print_detailed_report()
    
    # 获取自定义报告
    report = app.get_analysis_report()
    
    # 打印帧时间分解
    print("Frame Time Breakdown:")
    print("-"*80)
    
    elapsed = report['duration_seconds']
    frame_count = max(1, report['frame_count'])
    
    # 计算各部分时间
    timer_total = sum(info['count'] for info in report['timer_info'].values())
    paint_total = report['event_times'].get('Paint', 0.0)
    update_total = report['event_times'].get('UpdateRequest', 0.0)
    idle_total = report['total_idle_time'] * 1000.0  # 转换为ms
    
    # 计算其他时间
    total_ms = elapsed * 1000.0
    other_ms = max(0.0, total_ms - timer_total - paint_total - update_total - idle_total)
    
    print(f"{'Component':<20} {'Total(ms)':>12} {'PerFrame(ms)':>15} {'Percentage':>12}")
    print("-"*80)
    print(f"{'Qt Event Dispatch':<20} {timer_total:>12.2f} {timer_total/frame_count:>15.2f} {timer_total/total_ms*100:>11.1f}%")
    print(f"{'Timer Callbacks':<20} {timer_total:>12.2f} {timer_total/frame_count:>15.2f} {timer_total/total_ms*100:>11.1f}%")
    print(f"{'paintGL Execution':<20} {paint_total:>12.2f} {paint_total/frame_count:>15.2f} {paint_total/total_ms*100:>11.1f}%")
    print(f"{'swapBuffers':<20} {'N/A':>12} {'N/A':>15} {'N/A':>12}%")
    print(f"{'Idle/Wait':<20} {idle_total:>12.2f} {idle_total/frame_count:>15.2f} {idle_total/total_ms*100:>11.1f}%")
    print(f"{'Other':<20} {other_ms:>12.2f} {other_ms/frame_count:>15.2f} {other_ms/total_ms*100:>11.1f}%")
    print("-"*80)
    print(f"{'Total':<20} {total_ms:>12.2f} {total_ms/frame_count:>15.2f} {100.0:>11.1f}%")
    print()
    
    # 计时器详细分析
    print("Timer Details:")
    print("-"*80)
    print(f"{'Timer':<30} {'Triggers':>10} {'Rate(Hz)':>10}")
    print("-"*80)
    
    for timer_id, info in report['timer_info'].items():
        rate = info['count'] / elapsed if elapsed > 0 else 0
        print(f"{info['name']:<30} {info['count']:>10} {rate:>10.1f}")
    
    print()
    
    # 性能问题诊断
    print("Performance Issues Diagnosis:")
    print("-"*80)
    
    issues = []
    
    # 检查paintGL频率
    if report['paintgl_rate'] < 30:
        issues.append(f"Low paintGL rate ({report['paintgl_rate']:.1f} Hz) - Rendering may be laggy")
    
    # 检查update()频率
    if report['update_rate'] > 120:
        issues.append(f"High update() rate ({report['update_rate']:.1f} Hz) - May indicate unnecessary redraws")
    
    # 检查空闲时间
    if report['idle_percentage'] > 50:
        issues.append(f"High idle time ({report['idle_percentage']:.1f}%) - May indicate event processing bottlenecks")
    
    # 检查计时器竞争
    timer_count = len(report['timer_info'])
    if timer_count > 3:
        issues.append(f"Multiple timers ({timer_count}) competing for GUI thread")
    
    if issues:
        for issue in issues:
            print(f"• {issue}")
    else:
        print("No major performance issues detected.")
    
    print()
    print("="*80)
    
    # 导出时间线
    try:
        timeline_file = f"qt_event_timeline_{int(time.time())}.csv"
        app.analyzer.export_timeline(timeline_file)
        print(f"Timeline data exported to: {timeline_file}")
    except Exception as e:
        print(f"Failed to export timeline: {e}")
    
    print()
    print("Analysis complete. Closing application...")
    app.quit()


if __name__ == '__main__':
    from collections import defaultdict
    run_detailed_analysis()
