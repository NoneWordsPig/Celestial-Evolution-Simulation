"""
Performance Profiling Data Analyzer
分析现有的profiling输出数据，识别Qt事件循环瓶颈
"""
import re
from pathlib import Path
from collections import defaultdict
import statistics

def parse_perf_log_line(line):
    """解析单行性能日志"""
    # 示例行: [perf] frame avg=16.50 max=20.10 1s=16.20 | physics avg=8.50 max=12.00 1s=8.80 | ...
    
    if not line.startswith('[perf]'):
        return None
    
    # 移除 [perf] 前缀
    content = line[7:].strip()
    
    # 按管道符分割各个指标
    parts = content.split('|')
    
    metrics = {}
    for part in parts:
        # 提取指标名称和数值
        # 格式: "frame avg=16.50 max=20.10 1s=16.20"
        metric_match = re.match(r'(\w+)\s+avg=([\d.]+)\s+max=([\d.]+)\s+1s=([\d.]+)', part.strip())
        if metric_match:
            name = metric_match.group(1)
            metrics[name] = {
                'avg_ms': float(metric_match.group(2)),
                'max_ms': float(metric_match.group(3)),
                'recent_1s_ms': float(metric_match.group(4))
            }
    
    return metrics

def analyze_performance_logs(log_dir="."):
    """分析性能日志"""
    log_path = Path(log_dir)
    
    # 查找性能日志文件
    log_files = list(log_path.glob("logs/performance.log"))
    if not log_files:
        print("No performance log files found in logs/ directory")
        return None
    
    # 使用最新的日志文件
    latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
    print(f"Analyzing log file: {latest_log}")
    
    metrics_history = defaultdict(list)
    
    try:
        with open(latest_log, 'r', encoding='utf-8') as f:
            for line in f:
                metrics = parse_perf_log_line(line)
                if metrics:
                    for name, values in metrics.items():
                        metrics_history[name].append(values)
    except Exception as e:
        print(f"Error reading log file: {e}")
        return None
    
    return metrics_history

def calculate_statistics(metrics_history):
    """计算统计信息"""
    stats = {}
    
    for metric_name, values_list in metrics_history.items():
        if not values_list:
            continue
        
        avg_values = [v['avg_ms'] for v in values_list]
        max_values = [v['max_ms'] for v in values_list]
        recent_values = [v['recent_1s_ms'] for v in values_list]
        
        stats[metric_name] = {
            'avg_avg_ms': statistics.mean(avg_values),
            'avg_max_ms': statistics.mean(max_values),
            'avg_recent_ms': statistics.mean(recent_values),
            'max_avg_ms': max(avg_values),
            'max_max_ms': max(max_values),
            'max_recent_ms': max(recent_values),
            'min_avg_ms': min(avg_values),
            'sample_count': len(values_list)
        }
    
    return stats

def print_performance_analysis():
    """打印性能分析结果"""
    print("="*80)
    print("Performance Profiling Data Analysis")
    print("="*80)
    
    metrics_history = analyze_performance_logs()
    if not metrics_history:
        print("No performance data available for analysis")
        return
    
    stats = calculate_statistics(metrics_history)
    
    if not stats:
        print("No valid metrics found in log data")
        return
    
    # 打印统计摘要
    print(f"\nPerformance Metrics Summary (averaged over {len(list(metrics_history.values())[0])} samples):\n")
    print(f"{'Metric':<20} {'Avg(ms)':>12} {'Max(ms)':>12} {'Recent(ms)':>12} {'Peak(ms)':>12}")
    print("-"*80)
    
    # 按重要性排序显示指标
    priority_order = ['frame', 'physics', 'render_cpu', 'render_wall', 'qt', 'ui', 'gpu_wait', 'unaccounted']
    
    for metric_name in priority_order:
        if metric_name in stats:
            s = stats[metric_name]
            print(f"{metric_name:<20} {s['avg_avg_ms']:>12.2f} {s['avg_max_ms']:>12.2f} {s['avg_recent_ms']:>12.2f} {s['max_max_ms']:>12.2f}")
    
    # 显示其他指标
    for metric_name, s in stats.items():
        if metric_name not in priority_order:
            print(f"{metric_name:<20} {s['avg_avg_ms']:>12.2f} {s['avg_max_ms']:>12.2f} {s['avg_recent_ms']:>12.2f} {s['max_max_ms']:>12.2f}")
    
    # 瓶颈分析
    print("\n" + "="*80)
    print("Bottleneck Analysis")
    print("="*80)
    
    if 'frame' in stats and 'physics' in stats and 'render_cpu' in stats:
        frame_avg = stats['frame']['avg_avg_ms']
        physics_avg = stats['physics']['avg_avg_ms']
        render_cpu_avg = stats['render_cpu']['avg_avg_ms']
        
        physics_pct = (physics_avg / frame_avg * 100) if frame_avg > 0 else 0
        render_pct = (render_cpu_avg / frame_avg * 100) if frame_avg > 0 else 0
        
        print(f"\nFrame Time Composition:")
        print(f"  Total Frame: {frame_avg:.2f} ms")
        print(f"  Physics:     {physics_avg:.2f} ms ({physics_pct:.1f}%)")
        print(f"  Render CPU:  {render_cpu_avg:.2f} ms ({render_pct:.1f}%)")
        
        other_time = frame_avg - physics_avg - render_cpu_avg
        other_pct = (other_time / frame_avg * 100) if frame_avg > 0 else 0
        print(f"  Other:       {other_time:.2f} ms ({other_pct:.1f}%)")
        
        # 识别主要瓶颈
        print(f"\nPrimary Bottleneck:")
        if physics_avg > render_cpu_avg and physics_avg > other_time:
            print(f"  [PHYSICS] Physics calculation is the main bottleneck")
            print(f"  -> Consider physics optimization or reduce simulation complexity")
        elif render_cpu_avg > physics_avg and render_cpu_avg > other_time:
            print(f"  [RENDER] Rendering is the main bottleneck")
            print(f"  -> Consider render optimization or reduce visual complexity")
        elif other_time > physics_avg and other_time > render_cpu_avg:
            print(f"  [OTHER] Other overhead (Qt events, UI, etc.) is the main bottleneck")
            print(f"  -> Consider Qt event optimization or UI update consolidation")
    
    # Qt事件分析
    if 'qt' in stats:
        qt_avg = stats['qt']['avg_avg_ms']
        print(f"\nQt Event Processing:")
        print(f"  Average Qt overhead: {qt_avg:.2f} ms")
        
        if 'frame' in stats:
            frame_avg = stats['frame']['avg_avg_ms']
            qt_pct = (qt_avg / frame_avg * 100) if frame_avg > 0 else 0
            print(f"  Qt percentage of frame time: {qt_pct:.1f}%")
            
            if qt_pct > 20:
                print(f"  [HIGH] Qt event processing consumes significant time")
            elif qt_pct > 10:
                print(f"  [MODERATE] Qt overhead is noticeable")
            else:
                print(f"  [OK] Qt overhead is minimal")
    
    # GPU等待分析
    if 'gpu_wait' in stats:
        gpu_wait_avg = stats['gpu_wait']['avg_avg_ms']
        print(f"\nGPU Wait Time:")
        print(f"  Average GPU wait: {gpu_wait_avg:.2f} ms")
        
        if 'render_wall' in stats:
            render_wall_avg = stats['render_wall']['avg_avg_ms']
            gpu_pct = (gpu_wait_avg / render_wall_avg * 100) if render_wall_avg > 0 else 0
            print(f"  GPU wait percentage of render wall: {gpu_pct:.1f}%")
            
            if gpu_pct > 50:
                print(f"  [HIGH] CPU is spending significant time waiting for GPU")
            elif gpu_pct > 30:
                print(f"  [MODERATE] GPU sync overhead is noticeable")
            else:
                print(f"  [OK] GPU synchronization is efficient")
    
    # UI更新分析
    if 'ui' in stats:
        ui_avg = stats['ui']['avg_avg_ms']
        print(f"\nUI Update Overhead:")
        print(f"  Average UI update time: {ui_avg:.2f} ms")
        
        if 'frame' in stats:
            frame_avg = stats['frame']['avg_avg_ms']
            ui_pct = (ui_avg / frame_avg * 100) if frame_avg > 0 else 0
            print(f"  UI percentage of frame time: {ui_pct:.1f}%")
            
            if ui_pct > 15:
                print(f"  [HIGH] UI updates consume significant frame time")
            elif ui_pct > 8:
                print(f"  [MODERATE] UI overhead is noticeable")
            else:
                print(f"  [OK] UI overhead is minimal")
    
    # 性能趋势分析
    print(f"\n" + "="*80)
    print("Performance Trends")
    print("="*80)
    
    if 'frame' in stats:
        frame_values = [v['avg_ms'] for v in metrics_history['frame']]
        if len(frame_values) > 1:
            # 简单趋势分析
            first_half = frame_values[:len(frame_values)//2]
            second_half = frame_values[len(frame_values)//2:]
            
            first_avg = statistics.mean(first_half) if first_half else 0
            second_avg = statistics.mean(second_half) if second_half else 0
            
            trend_pct = ((second_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0
            
            print(f"\nFrame Time Trend:")
            print(f"  First half average: {first_avg:.2f} ms")
            print(f"  Second half average: {second_avg:.2f} ms")
            print(f"  Trend: {trend_pct:+.1f}%")
            
            if abs(trend_pct) < 5:
                print(f"  [STABLE] Performance is stable over time")
            elif trend_pct > 0:
                print(f"  [DEGRADING] Performance is degrading over time")
            else:
                print(f"  [IMPROVING] Performance is improving over time")
    
    # 峰值分析
    if 'frame' in stats:
        frame_max = stats['frame']['max_max_ms']
        frame_avg = stats['frame']['avg_avg_ms']
        spike_ratio = frame_max / frame_avg if frame_avg > 0 else 0
        
        print(f"\nPeak Performance Analysis:")
        print(f"  Average frame time: {frame_avg:.2f} ms")
        print(f"  Peak frame time: {frame_max:.2f} ms")
        print(f"  Spike ratio: {spike_ratio:.2f}x")
        
        if spike_ratio > 3:
            print(f"  [HIGHLY VARIABLE] Severe performance spikes detected")
        elif spike_ratio > 2:
            print(f"  [VARIABLE] Moderate performance variation")
        else:
            print(f"  [CONSISTENT] Performance is consistent")

if __name__ == '__main__':
    print_performance_analysis()
    
    print("\n" + "="*80)
    print("Analysis Complete")
    print("="*80)
    print("\nRecommendations:")
    print("1. If Qt overhead is high: Consider timer consolidation and event optimization")
    print("2. If physics is bottleneck: Focus on physics algorithm optimization")  
    print("3. If render is bottleneck: Consider render optimization and GPU utilization")
    print("4. If GPU wait is high: Check for pipeline stalls and synchronization issues")
    print("5. Monitor performance trends to identify degradation over time")

