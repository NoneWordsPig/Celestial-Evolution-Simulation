"""
天体引力模拟器

主入口文件
"""

import sys
from ui.main_window import MainWindow
from ui.styles import apply_global_style
from ui.profiler import ProfilingApplication


def main():
    """主函数"""
    app = ProfilingApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    apply_global_style(app)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
