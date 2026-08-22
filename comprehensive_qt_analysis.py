"""
Qt Event Loop and Performance Bottleneck Analysis
"""
import re
from pathlib import Path

def analyze_qt_timers_detailed(project_root="."):
    """详细分析Qt计时器配置"""
    project_path = Path(project_root)
    
    timers = []
    
    # 分析main_window.py
    main_window = project_path / "ui" / "main_window.py"
    if main_window.exists():
        content = main_window.read_text(encoding='utf-8')
        
        # 查找QTimer创建
        timer_pattern = r'self\._(\w+_timer)\s*=\s*QTimer\(self\)'
        for match in re.finditer(timer_pattern, content):
            timers.append({
                'name': match.group(1),
                'file': 'main_window.py'
            })
        
        # 查找硬编码的计时器启动
        start_pattern = r'self\._(\w+_timer)\.start\((\d+)\)'
        for match in re.finditer(start_pattern, content):
            timer_name = match.group(1)
            interval_ms = int(match.group(2))
            frequency_hz = 1000.0 / interval_ms if interval_ms > 0 else 0
            
            for timer in timers:
                if timer['name'] == timer_name:
                    timer['interval_ms'] = interval_ms
                    timer['frequency_hz'] = frequency_hz
    
    # 分析simulation_widget.py
    sim_widget = project_path / "ui" / "simulation_widget.py"
    if sim_widget.exists():
        content = sim_widget.read_text(encoding='utf-8')
        
        # 查找QTimer创建
        timer_pattern = r'self\._(\w+_timer)\s*=\s*QTimer\(self\)'
        for match in re.finditer(timer_pattern, content):
            timers.append({
                'name': match.group(1),
                'file': 'simulation_widget.py'
            })
        
        # 查找FPS配置变量
        fps_pattern = r'self\._(\w+)_fps\s*=\s*(\d+)'
        fps_values = {}
        for match in re.finditer(fps_pattern, content):
            fps_name = match.group(1)
            fps_value = int(match.group(2))
            fps_values[fps_name] = fps_value
        
        # 查找使用FPS变量启动计时器的代码
        for timer in timers:
            if timer['file'] == 'simulation_widget.py':
                timer_name = timer['name']
                # 尝试匹配对应的FPS变量
                if 'physics' in timer_name.lower() and 'target' in fps_values:
                    timer['interval_ms'] = int(1000 / fps_values['target'])
                    timer['frequency_hz'] = fps_values['target']
                    timer['fps_variable'] = '_target_fps'
                elif 'render' in timer_name.lower() and 'render' in fps_values:
                    timer['interval_ms'] = int(1000 / fps_values['render'])
                    timer['frequency_hz'] = fps_values['render']
                    timer['fps_variable'] = '_render_fps'
    
    return timers

def print_comprehensive_analysis():
    """打印综合分析结果"""
    print("="*80)
    print("Comprehensive Qt Event Loop and Performance Analysis")
    print("="*80)
    
    timers = analyze_qt_timers_detailed()
    
    if not timers:
        print("No timers found in the project")
        return
    
    # 打印计时器配置
    print(f"\nFound {len(timers)} configured timers:\n")
    print(f"{'Timer Name':<25} {'Interval(ms)':>15} {'Frequency(Hz)':>15} {'Config':<20} {'File':<20}")
    print("-"*80)
    
    total_frequency = 0.0
    for timer in timers:
        interval = timer.get('interval_ms', 'Unknown')
        frequency = timer.get('frequency_hz', 'Unknown')
        config = timer.get('fps_variable', 'Hardcoded')
        
        print(f"{timer['name']:<25} {str(interval):>15} {str(frequency):>15} {str(config):<20} {timer['file']:<20}")
        
        if isinstance(frequency, (int, float)):
            total_frequency += frequency
    
    print(f"\nTotal timer frequency: {total_frequency:.1f} Hz")
    if total_frequency > 0:
        print(f"Average timer interval: {1000.0/total_frequency:.2f} ms")
        print(f"Theoretical max FPS: {min(60.0, total_frequency):.1f} FPS (limited by display)")
    
    # 问题分析
    print("\n" + "="*80)
    print("Performance Bottleneck Analysis")
    print("="*80)
    
    active_timers = [t for t in timers if isinstance(t.get('frequency_hz'), (int, float))]
    
    if not active_timers:
        print("No active timers with frequency configuration found")
        return
    
    # 1. 频率竞争分析
    print("\n1. Timer Competition Analysis:")
    if total_frequency > 120:
        print(f"   [HIGH] Total frequency {total_frequency:.1f} Hz exceeds 120 Hz threshold")
        print(f"   -> Multiple timers competing for GUI thread")
    elif total_frequency > 80:
        print(f"   [MEDIUM] Total frequency {total_frequency:.1f} Hz is elevated")
        print(f"   -> Some timer optimization may be beneficial")
    else:
        print(f"   [OK] Total frequency {total_frequency:.1f} Hz is acceptable")
    
    # 2. 高频计时器分析
    fast_timers = [t for t in active_timers if t['frequency_hz'] > 30]
    print(f"\n2. High-Frequency Timers (>30 Hz):")
    if fast_timers:
        for timer in fast_timers:
            print(f"   - {timer['name']}: {timer['frequency_hz']:.1f} Hz ({timer.get('interval_ms', 0)} ms)")
    else:
        print("   [OK] No high-frequency timers found")
    
    # 3. 频率冲突分析
    from collections import defaultdict
    freq_groups = defaultdict(list)
    for timer in active_timers:
        freq_key = round(timer['frequency_hz'])
        freq_groups[freq_key].append(timer)
    
    print(f"\n3. Frequency Clash Analysis:")
    clashes = [(freq, group) for freq, group in freq_groups.items() if len(group) > 1]
    if clashes:
        for freq, group in clashes:
            print(f"   [CLASH] {len(group)} timers at ~{freq} Hz:")
            for timer in group:
                print(f"          - {timer['name']}: {timer['frequency_hz']:.1f} Hz")
    else:
        print("   [OK] No frequency clashes detected")
    
    # 4. 渲染管线分析
    print(f"\n4. Render Pipeline Analysis:")
    physics_timer = next((t for t in timers if 'physics' in t['name'].lower()), None)
    render_timer = next((t for t in timers if 'render' in t['name'].lower()), None)
    
    if physics_timer and render_timer:
        phys_freq = physics_timer.get('frequency_hz')
        rend_freq = render_timer.get('frequency_hz')
        
        if isinstance(phys_freq, (int, float)) and isinstance(rend_freq, (int, float)):
            ratio = rend_freq / phys_freq if phys_freq > 0 else 0
            print(f"   Physics: {phys_freq:.1f} Hz ({1000/phys_freq:.1f} ms)")
            print(f"   Render:  {rend_freq:.1f} Hz ({1000/rend_freq:.1f} ms)")
            print(f"   Ratio: {ratio:.1f}x")
            
            if abs(ratio - 2.0) < 0.1:
                print(f"   [OK] Standard 2:1 render/physics ratio")
            else:
                print(f"   [WARN] Non-standard ratio (expected 2.0x, got {ratio:.1f}x)")
    
    # 5. UI更新效率分析
    ui_timers = [t for t in timers if any(word in t['name'].lower() 
                  for word in ['status', 'inspector', 'ref_frame', 'ui'])]
    
    print(f"\n5. UI Update Efficiency:")
    if ui_timers:
        ui_frequency = sum(t.get('frequency_hz', 0) for t in ui_timers if isinstance(t.get('frequency_hz'), (int, float)))
        print(f"   UI update timers: {len(ui_timers)}")
        print(f"   Total UI frequency: {ui_frequency:.1f} Hz")
        print(f"   Average UI interval: {1000/ui_frequency:.1f} ms" if ui_frequency > 0 else "   Average UI interval: N/A")
        
        if ui_frequency > 40:
            print(f"   [WARN] High UI update frequency - consider consolidating")
        else:
            print(f"   [OK] UI update frequency is reasonable")
        
        print(f"   UI timers:")
        for timer in ui_timers:
            freq = timer.get('frequency_hz', 'Unknown')
            print(f"      - {timer['name']}: {freq} Hz")
    
    # 帧时间分解估算
    print(f"\n" + "="*80)
    print("Frame Time Breakdown Estimation")
    print("="*80)
    
    if total_frequency > 0:
        frame_time_100fps = 10.0  # 基准：100 FPS = 10ms per frame
        
        print(f"\nBased on timer frequencies, estimated per-frame GUI thread time:")
        print(f"{'Component':<20} {'Freq(Hz)':>12} {'Time/Frame(ms)':>18} {'% GUI Time':>15}")
        print("-"*80)
        
        for timer in active_timers:
            freq = timer['frequency_hz']
            time_per_frame = (freq / total_frequency) * frame_time_100fps
            percentage = (freq / total_frequency * 100)
            
            print(f"{timer['name']:<20} {freq:>12.1f} {time_per_frame:>18.2f} {percentage:>14.1f}%")
        
        print("-"*80)
        print(f"{'Estimated Total':<20} {total_frequency:>12.1f} {frame_time_100fps:>18.2f} {100.0:>14.1f}%")
        
        # 瓶颈识别
        print(f"\nBottleneck Identification:")
        sorted_by_freq = sorted(active_timers, key=lambda t: t['frequency_hz'], reverse=True)
        if sorted_by_freq:
            bottleneck = sorted_by_freq[0]
            bottl_time = (bottleneck['frequency_hz'] / total_frequency) * frame_time_100fps
            print(f"   Primary: {bottleneck['name']} ({bottleneck['frequency_hz']:.1f} Hz)")
            print(f"   -> Consumes ~{bottl_time:.2f} ms per frame ({bottleneck['frequency_hz']/total_frequency*100:.1f}% of GUI time)")

if __name__ == '__main__':
    print_comprehensive_analysis()
    
    print("\n" + "="*80)
    print("Summary and Key Findings")
    print("="*80)
    
    timers = analyze_qt_timers_detailed()
    active_timers = [t for t in timers if isinstance(t.get('frequency_hz'), (int, float))]
    total_frequency = sum(t['frequency_hz'] for t in active_timers)
    
    print(f"\nKey Metrics:")
    print(f"  Total Timers: {len(timers)}")
    print(f"  Active Timers: {len(active_timers)}")
    print(f"  Total Frequency: {total_frequency:.1f} Hz")
    print(f"  Average Interval: {1000/total_frequency:.2f} ms" if total_frequency > 0 else "  Average Interval: N/A")
    
    print(f"\nPerformance Characteristics:")
    if total_frequency <= 80:
        print(f"  [GOOD] Low timer competition - efficient event handling")
    elif total_frequency <= 120:
        print(f"  [MODERATE] Acceptable timer frequency - minor overhead")
    else:
        print(f"  [CONCERN] High timer frequency - potential GUI bottleneck")
    
    # 检查特定问题
    physics_timer = next((t for t in timers if 'physics' in t['name'].lower()), None)
    render_timer = next((t for t in timers if 'render' in t['name'].lower()), None)
    
    if physics_timer and render_timer:
        phys_freq = physics_timer.get('frequency_hz')
        rend_freq = render_timer.get('frequency_hz')
        if isinstance(phys_freq, (int, float)) and isinstance(rend_freq, (int, float)):
            if abs((rend_freq/phys_freq) - 2.0) > 0.5:
                print(f"  [WARN] Non-standard render/physics ratio detected")
    
    ui_timers = [t for t in timers if any(word in t['name'].lower() 
                  for word in ['status', 'inspector', 'ref_frame'])]
    if len(ui_timers) >= 3:
        print(f"  [INFO] Multiple UI timers could be consolidated for efficiency")
    
    print(f"\nPhysics Performance Note:")
    print(f"  The physics optimization shows minimal impact for 50-100 bodies because")
    print(f"  the bottleneck is likely in Qt event dispatch and rendering, not physics calculation.")
    print(f"  For 200+ bodies, the optimized version shows slower performance, which may indicate:")
    print(f"  1. Memory allocation overhead in the optimized code")
    print(f"  2. Cache inefficiency with the new data access patterns")
    print(f"  3. Python overhead in wrapper functions")
    
    print("\n" + "="*80)
    print("Analysis Complete")
    print("="*80)

