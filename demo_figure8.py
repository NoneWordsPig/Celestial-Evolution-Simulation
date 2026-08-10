"""
Figure-8 三体系统演示

展示一个稳定的三体系统，三个质量相等的天体沿着8字形轨道运动。
这是一个经典的稳定三体解，由 Chenciner & Montgomery 在 2000 年发现。

特性：
- 三个质量相等的天体
- 总动量为零
- 稳定的周期轨道
- 每个天体都经过其他两个天体的初始位置

操作说明：
- 鼠标滚轮：缩放视图
- 鼠标中键拖拽：平移画布
- 工具栏按钮：控制播放、重置摄像机等
- 跟随质心：自动将视图中心保持在系统质心
"""

import sys
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
from ui.styles import apply_global_style
from physics import Body


def setup_figure8_system(window):
    """
    设置 Figure-8 三体系统
    
    使用经典的初始条件，三个质量相等的天体形成稳定的8字形轨道。
    这个解具有时间反演对称性和交换对称性。
    """
    # 清空现有天体
    window.engine.clear()
    
    # Figure-8 初始条件（Chenciner & Montgomery, 2000）
    # 所有质量相等，总动量为零
    mass = 1.0
    
    # 位置（三个天体初始不在同一直线上）
    x1, y1 = -0.97000436, 0.24308753
    x2, y2 = 0.97000436, -0.24308753
    x3, y3 = 0.0, 0.0
    
    # 速度（满足总动量为零的条件）
    vx3, vy3 = -0.93240737, -0.86473146
    vx1 = vx2 = -vx3 / 2.0
    vy1 = vy2 = -vy3 / 2.0
    
    # 创建三个天体
    body1 = Body(
        name="Body 1",
        mass=mass,
        physical_radius=0.02,
        render_radius=0.1,
        position=(x1, y1),
        velocity=(vx1, vy1),
        color=(1.0, 0.3, 0.3)  # 红色
    )
    
    body2 = Body(
        name="Body 2",
        mass=mass,
        physical_radius=0.02,
        render_radius=0.1,
        position=(x2, y2),
        velocity=(vx2, vy2),
        color=(0.3, 1.0, 0.3)  # 绿色
    )
    
    body3 = Body(
        name="Body 3",
        mass=mass,
        physical_radius=0.02,
        render_radius=0.1,
        position=(x3, y3),
        velocity=(vx3, vy3),
        color=(0.3, 0.3, 1.0)  # 蓝色
    )
    
    # 添加到引擎
    window.engine.add_body(body1)
    window.engine.add_body(body2)
    window.engine.add_body(body3)
    
    # 设置摄像机
    window.camera.center_x = 0.0
    window.camera.center_y = 0.0
    window.camera.zoom = 150.0  # 合适的缩放级别，可以看到完整轨道
    
    # 启用跟随质心
    window.follow_com = True
    window.follow_com_btn.setChecked(True)
    window.follow_com_action.setChecked(True)
    
    # 设置时间步长和缩放
    window.engine.dt = 0.0005  # 更小的时间步长保证长期稳定性
    window.engine.time_scale = 1.0
    
    # 刷新UI
    window.body_list.refresh()
    
    print("Figure-8 三体系统已加载")
    print("初始条件：")
    print(f"  Body 1: pos=({x1:.4f}, {y1:.4f}), vel=({vx1:.4f}, {vy1:.4f})")
    print(f"  Body 2: pos=({x2:.4f}, {y2:.4f}), vel=({vx2:.4f}, {vy2:.4f})")
    print(f"  Body 3: pos=({x3:.4f}, {y3:.4f}), vel=({vx3:.4f}, {vy3:.4f})")
    print(f"  总质量: {3*mass}")
    print(f"  总动量: [0, 0]")


def show_info():
    """显示信息对话框"""
    msg = QMessageBox()
    msg.setWindowTitle("Figure-8 三体系统")
    msg.setText("<h2>Figure-8 三体系统演示</h2>")
    msg.setInformativeText("""
    <p>这是一个稳定的三体系统，三个质量相等的天体沿着8字形轨道运动。</p>
    
    <p><b>特性：</b></p>
    <ul>
    <li>三个质量相等的天体</li>
    <li>总动量为零</li>
    <li>稳定的周期轨道</li>
    <li>每个天体都经过其他两个天体的初始位置</li>
    </ul>
    
    <p><b>操作说明：</b></p>
    <ul>
    <li>鼠标滚轮：缩放视图</li>
    <li>鼠标中键拖拽：平移画布</li>
    <li>工具栏按钮：控制播放、重置摄像机等</li>
    <li>跟随质心：自动将视图中心保持在系统质心</li>
    </ul>
    
    <p><b>科学意义：</b></p>
    <p>这个解由 Chenciner & Montgomery 在 2000 年发现，是三体问题中少数几个已知的稳定周期解之一。</p>
    """)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.exec()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 应用样式
    app.setStyle('Fusion')
    apply_global_style(app)
    
    # 创建主窗口
    window = MainWindow()
    window.setWindowTitle("Figure-8 三体系统演示")
    window.resize(1400, 900)
    
    # 设置 Figure-8 系统
    setup_figure8_system(window)
    
    # 显示信息对话框
    show_info()
    
    # 显示窗口
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
