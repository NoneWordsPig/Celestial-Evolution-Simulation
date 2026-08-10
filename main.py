"""
天体引力模拟器

主入口文件

启动 PyQt6 桌面应用
"""

import sys
from PyQt6.QtWidgets import QApplication
from ui import MainWindow


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
