"""
统一 UI 样式系统

提供现代扁平化风格的 QSS 样式表
"""


# 主色调
PRIMARY_COLOR = "#2196F3"
PRIMARY_HOVER = "#1976D2"
PRIMARY_PRESSED = "#0D47A1"

SECONDARY_COLOR = "#424242"
SECONDARY_HOVER = "#616161"
SECONDARY_PRESSED = "#212121"

DANGER_COLOR = "#F44336"
DANGER_HOVER = "#D32F2F"
DANGER_PRESSED = "#B71C1C"

SUCCESS_COLOR = "#4CAF50"
SUCCESS_HOVER = "#388E3C"
SUCCESS_PRESSED = "#1B5E20"

# 背景色
BG_COLOR = "#1E1E1E"
BG_LIGHT = "#2D2D2D"
BG_LIGHTER = "#3D3D3D"

# 文字颜色
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#B0B0B0"
TEXT_DISABLED = "#666666"

# 边框
BORDER_COLOR = "#404040"
BORDER_FOCUS = PRIMARY_COLOR


# 通用按钮样式
BUTTON_STYLE = f"""
QPushButton {{
    background-color: {SECONDARY_COLOR};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {SECONDARY_HOVER};
}}

QPushButton:pressed {{
    background-color: {SECONDARY_PRESSED};
}}

QPushButton:disabled {{
    background-color: {BG_LIGHTER};
    color: {TEXT_DISABLED};
}}
"""

# 主要按钮样式（蓝色）
PRIMARY_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {PRIMARY_COLOR};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {PRIMARY_HOVER};
}}

QPushButton:pressed {{
    background-color: {PRIMARY_PRESSED};
}}

QPushButton:disabled {{
    background-color: {BG_LIGHTER};
    color: {TEXT_DISABLED};
}}
"""

# 危险按钮样式（红色）
DANGER_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {DANGER_COLOR};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {DANGER_HOVER};
}}

QPushButton:pressed {{
    background-color: {DANGER_PRESSED};
}}

QPushButton:disabled {{
    background-color: {BG_LIGHTER};
    color: {TEXT_DISABLED};
}}
"""

# 成功按钮样式（绿色）
SUCCESS_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {SUCCESS_COLOR};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {SUCCESS_HOVER};
}}

QPushButton:pressed {{
    background-color: {SUCCESS_PRESSED};
}}

QPushButton:disabled {{
    background-color: {BG_LIGHTER};
    color: {TEXT_DISABLED};
}}
"""

# 工具栏按钮样式（紧凑）
TOOLBAR_BUTTON_STYLE = f"""
QPushButton {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {BG_LIGHTER};
    border-color: {PRIMARY_COLOR};
}}

QPushButton:pressed {{
    background-color: {SECONDARY_COLOR};
}}

QPushButton:checked {{
    background-color: {PRIMARY_COLOR};
    border-color: {PRIMARY_COLOR};
}}
"""

# 面板样式
PANEL_STYLE = f"""
QWidget {{
    background-color: {BG_COLOR};
    color: {TEXT_PRIMARY};
}}

QGroupBox {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_PRIMARY};
}}

QLabel {{
    color: {TEXT_PRIMARY};
    background-color: transparent;
}}

QListWidget {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    color: {TEXT_PRIMARY};
}}

QListWidget::item {{
    padding: 8px;
    border-bottom: 1px solid {BORDER_COLOR};
}}

QListWidget::item:selected {{
    background-color: {PRIMARY_COLOR};
}}

QListWidget::item:hover {{
    background-color: {BG_LIGHTER};
}}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 6px;
    color: {TEXT_PRIMARY};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {BORDER_FOCUS};
}}

QComboBox {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER_COLOR};
    border-radius: 4px;
    padding: 6px;
    color: {TEXT_PRIMARY};
}}

QComboBox:hover {{
    border-color: {PRIMARY_COLOR};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER_COLOR};
    color: {TEXT_PRIMARY};
    selection-background-color: {PRIMARY_COLOR};
}}

QScrollBar:vertical {{
    background-color: {BG_COLOR};
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {SECONDARY_COLOR};
    min-height: 20px;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {SECONDARY_HOVER};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QStatusBar {{
    background-color: {BG_LIGHT};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER_COLOR};
}}

QMenuBar {{
    background-color: {BG_LIGHT};
    color: {TEXT_PRIMARY};
    border-bottom: 1px solid {BORDER_COLOR};
}}

QMenuBar::item:selected {{
    background-color: {PRIMARY_COLOR};
}}

QMenu {{
    background-color: {BG_LIGHT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
}}

QMenu::item:selected {{
    background-color: {PRIMARY_COLOR};
}}

QToolBar {{
    background-color: {BG_LIGHT};
    border-bottom: 1px solid {BORDER_COLOR};
    spacing: 8px;
    padding: 4px;
}}

QSplitter::handle {{
    background-color: {BORDER_COLOR};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}
"""


def apply_global_style(app):
    """
    应用全局样式到应用程序
    
    Args:
        app: QApplication 实例
    """
    app.setStyleSheet(PANEL_STYLE)


def apply_button_style(button, style_type='default'):
    """
    应用按钮样式
    
    Args:
        button: QPushButton 实例
        style_type: 'default', 'primary', 'danger', 'success', 'toolbar'
    """
    if style_type == 'primary':
        button.setStyleSheet(PRIMARY_BUTTON_STYLE)
    elif style_type == 'danger':
        button.setStyleSheet(DANGER_BUTTON_STYLE)
    elif style_type == 'success':
        button.setStyleSheet(SUCCESS_BUTTON_STYLE)
    elif style_type == 'toolbar':
        button.setStyleSheet(TOOLBAR_BUTTON_STYLE)
    else:
        button.setStyleSheet(BUTTON_STYLE)
