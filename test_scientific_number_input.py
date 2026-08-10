"""
ScientificNumberInput 单元测试

验证：
1. 支持格式：1, 0.1, 0.000001, 1e-6, 3.003e-6, 1.989e30
2. 输入 3.003e-6 读取后必须得到 3.003e-6
3. 显示最多约 15 位有效数字，无固定小数位
4. AddBodyDialog 各数值字段均可使用该控件
"""

import unittest
import sys

from PyQt6.QtWidgets import QApplication

# 确保只有一个 QApplication 实例
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.scientific_number_input import ScientificNumberInput
from ui.add_body_dialog import AddBodyDialog
from physics.mode import Mode


class TestScientificNumberInputParsing(unittest.TestCase):
    """验证支持的输入格式"""

    CASES = [
        ("1", 1.0),
        ("0.1", 0.1),
        ("0.000001", 0.000001),
        ("1e-6", 1e-6),
        ("3.003e-6", 3.003e-6),
        ("1.989e30", 1.989e30),
    ]

    def test_parse_supported_formats(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                widget = ScientificNumberInput()
                widget.line_edit.setText(text)
                self.assertEqual(widget.value(), expected)

    def test_round_trip_3_003e_6(self):
        """输入 3.003e-6，读取后必须得到 3.003e-6"""
        widget = ScientificNumberInput()
        widget.line_edit.setText("3.003e-6")
        self.assertEqual(widget.value(), 3.003e-6)

    def test_invalid_text_keeps_last_valid_value(self):
        widget = ScientificNumberInput(value=42.0)
        widget.line_edit.setText("abc")
        self.assertEqual(widget.value(), 42.0)

    def test_empty_text_keeps_last_valid_value(self):
        widget = ScientificNumberInput(value=42.0)
        widget.line_edit.setText("")
        self.assertEqual(widget.value(), 42.0)


class TestScientificNumberInputFormatting(unittest.TestCase):
    """验证显示格式"""

    def test_display_3_003e_6(self):
        widget = ScientificNumberInput(value=3.003e-6)
        self.assertEqual(widget.line_edit.text(), "3.003e-6")

    def test_display_1_989e30(self):
        widget = ScientificNumberInput(value=1.989e30)
        self.assertEqual(widget.line_edit.text(), "1.989e30")

    def test_display_1e_6(self):
        widget = ScientificNumberInput(value=1e-6)
        self.assertEqual(widget.line_edit.text(), "1e-6")

    def test_display_plain_numbers(self):
        for value, expected in [(1.0, "1"), (0.1, "0.1"), (0.000001, "1e-6")]:
            with self.subTest(value=value):
                widget = ScientificNumberInput(value=value)
                self.assertEqual(widget.line_edit.text(), expected)

    def test_no_fixed_decimals(self):
        """显示不应是固定两位/三位小数格式，指数不补零"""
        widget = ScientificNumberInput(value=3.003e-6)
        # 固定两位小数会把 3.003e-6 显示成 0.00
        self.assertNotEqual(widget.line_edit.text(), "0.00")
        self.assertNotEqual(widget.line_edit.text(), "0.000")
        self.assertNotIn("e-06", widget.line_edit.text())

    def test_about_15_significant_digits(self):
        """有效数字不超过约 15 位"""
        widget = ScientificNumberInput(value=1.23456789012345)
        text = widget.line_edit.text()
        mantissa = text.split('e')[0].replace('.', '').replace('-', '')
        self.assertLessEqual(len(mantissa.lstrip('0')), 15)


class TestAddBodyDialogScientificInputs(unittest.TestCase):
    """AddBodyDialog 各字段使用 ScientificNumberInput 且支持科学计数法"""

    FIELDS = [
        'mass_spin',
        'radius_spin',
        'pos_x_spin',
        'pos_y_spin',
        'vx_spin',
        'vy_spin',
        'speed_spin',
        'direction_spin',
    ]

    def setUp(self):
        self.dialog = AddBodyDialog(mode=Mode.SIMULATION)

    def tearDown(self):
        self.dialog.close()

    def test_all_fields_are_scientific_number_input(self):
        from ui.scientific_number_input import ScientificNumberInput as SNI
        for name in self.FIELDS:
            with self.subTest(field=name):
                self.assertIsInstance(getattr(self.dialog, name), SNI)

    def test_each_field_round_trips_3_003e_6(self):
        """每个字段输入 3.003e-6，读取后必须得到 3.003e-6"""
        for name in self.FIELDS:
            with self.subTest(field=name):
                field = getattr(self.dialog, name)
                field.line_edit.setText("3.003e-6")
                self.assertEqual(field.value(), 3.003e-6)

    def test_mass_accepts_1_989e30(self):
        """质量字段支持 1.989e30"""
        self.dialog.mass_spin.line_edit.setText("1.989e30")
        self.assertEqual(self.dialog.mass_spin.value(), 1.989e30)


if __name__ == '__main__':
    unittest.main()
