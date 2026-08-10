"""
UI 模块

PyQt6 桌面界面组件
"""

from .main_window import MainWindow
from .simulation_widget import SimulationWidget
from .body_list_widget import BodyListWidget
from .inspector_widget import InspectorWidget
from .control_panel import ControlPanel
from .add_body_dialog import AddBodyDialog

__all__ = [
    'MainWindow',
    'SimulationWidget',
    'BodyListWidget',
    'InspectorWidget',
    'ControlPanel',
    'AddBodyDialog',
]
