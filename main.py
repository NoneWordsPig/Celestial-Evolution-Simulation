"""
天体引力模拟器

主入口文件
"""

import sys
from ui.main_window import MainWindow
from ui.styles import apply_global_style
from ui.profiler import ProfilingApplication
from app_metadata import APP_NAME, VERSION


def main():
    """主函数"""
    app = ProfilingApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    
    # 设置应用样式
    app.setStyle('Fusion')
    apply_global_style(app)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    if '--smoke-test' in sys.argv:
        from tools.release_smoke import schedule_smoke_test
        index = sys.argv.index('--smoke-test')
        if index + 1 >= len(sys.argv):
            raise SystemExit('--smoke-test requires a JSON report path')
        schedule_smoke_test(app, window, sys.argv[index + 1])
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
