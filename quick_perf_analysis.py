"""
Quick Performance Log Analysis
"""
import re
from collections import defaultdict
import statistics

def analyze_performance_log(log_path="logs/performance.log"):
    """分析性能日志"""
    
    metrics = defaultdict(list)
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                # 解析summary行: [perf] frame avg=XX.XX max=XX.XX 1s=XX.XX | ...
                if '[perf]' in line:
                    # 解析各个指标
                    parts = line.split('|')
                    for part in parts:
                        # 匹配指标名称和数值
                        match = re.search(r'(\w+)\s+avg=\s*([\d.]+)\s+max=\s*([\d.]+)\s+1s=\s*([\d.]+)', part)
                        if match:
                            name = match.group(1)
                            avg_val = float(match.group(2))
                            max_val = float(match.group(3))
                            recent_val = float(match.group(4))
                            
                            metrics[name].append({
                                'avg_ms': avg_val,
                                'max_ms': max_val,
                                'recent_ms': recent_val
                            })
    except Exception as e:
        print(f"Error reading log: {e}")
        return None
    
    return metrics

def print_analysis(metrics):
    """打印分析结果"""
    if not metrics:
        print("No metrics found")
        return
    
    print("="*80)
    print("Performance Log Analysis")
    print("="*80)
    
    # 计算统计信息
    stats = {}
    for name, values in metrics.items():
        if values:
            avg_values = [v['avg_ms'] for v in values]
            stats[name] = {
                'mean': statistics.mean(avg_values),
                'max': max(avg_values),
                'min': min(avg_values),
                'count': len(values)
            }
    
    print(f"\nMetrics Analysis (based on {len(list(metrics.values())[0])} samples):\n")
    print(f"{'Metric':<15} {'Mean(ms)':>12} {'Max(ms)':>12} {'Min(ms)':>12} {'% of Frame':>15}")
    print("-"*80)
    
    if 'frame' in stats:
        frame_mean = stats['frame']['mean']
        
        # 按重要性排序
        priority = ['frame', 'qt', 'render_cpu', 'render_wall', 'physics', 'ui', 'gpu_wait', 'unaccounted']
        
        for metric in priority:
            if metric in stats:
                s = stats[metric]
                pct = (s['mean'] / frame_mean * 100) if frame_mean > 0 else 0
                print(f"{metric:<15} {s['mean']:>12.2f} {s['max']:>12.2f} {s['min']:>12.2f} {pct:>14.1f}%")
        
        # 其他指标
        for metric, s in stats.items():
            if metric not in priority:
                pct = (s['mean'] / frame_mean * 100) if frame_mean > 0 else 0
                print(f"{metric:<15} {s['mean']:>12.2f} {s['max']:>12.2f} {s['min']:>12.2f} {pct:>14.1f}%")
    
    # 瓶颈分析
    print("\n" + "="*80)
    print("Bottleneck Analysis")
    print("="*80)
    
    if 'frame' in stats and 'qt' in stats and 'render_cpu' in stats and 'physics' in stats:
        frame_time = stats['frame']['mean']
        qt_time = stats['qt']['mean']
        render_time = stats['render_cpu']['mean']
        physics_time = stats['physics']['mean']
        
        print(f"\nFrame Time Breakdown:")
        print(f"  Total Frame:    {frame_time:.2f} ms ({100.0:.1f}%)")
        print(f"  Qt Events:      {qt_time:.2f} ms ({qt_time/frame_time*100:.1f}%)")
        print(f"  Render CPU:     {render_time:.2f} ms ({render_time/frame_time*100:.1f}%)")
        print(f"  Physics:        {physics_time:.2f} ms ({physics_time/frame_time*100:.1f}%)")
        
        other_time = frame_time - qt_time - render_time - physics_time
        print(f"  Other:          {other_time:.2f} ms ({other_time/frame_time*100:.1f}%)")
        
        # 识别瓶颈
        print(f"\nPrimary Bottlenecks:")
        bottlenecks = [
            ('Qt Events', qt_time, qt_time/frame_time*100),
            ('Rendering', render_time, render_time/frame_time*100),
            ('Physics', physics_time, physics_time/frame_time*100)
        ]
        
        bottlenecks.sort(key=lambda x: x[1], reverse=True)
        
        for name, time_val, pct in bottlenecks:
            if pct > 50:
                print(f"  [CRITICAL] {name}: {time_val:.2f} ms ({pct:.1f}%)")
            elif pct > 20:
                print(f"  [MAJOR] {name}: {time_val:.2f} ms ({pct:.1f}%)")
            elif pct > 10:
                print(f"  [MINOR] {name}: {time_val:.2f} ms ({pct:.1f}%)")

# 运行分析
metrics = analyze_performance_log()
if metrics:
    print_analysis(metrics)
else:
    print("No performance data to analyze")

print("\n" + "="*80)
print("Analysis Complete")
print("="*80)
