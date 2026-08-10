"""
独立 UnitSystem 单元测试

验证 Scientific Normalization：
    1 AU        -> 1 DU
    1 M_sun     -> 1 MU
    5.972e24 kg -> 约 3.003e-6 MU
    地球轨道速度 -> 约 1 个归一化速度单位
    1 year      -> 约 2π 个归一化时间单位

以及 parse / format / to_simulation / from_simulation 接口。
"""

import math
import unittest

from physics.unit_system import (
    UnitSystem, G_SI, AU, SOLAR_MASS,
)


class TestScientificNormalization(unittest.TestCase):
    """科学归一化核心换算"""

    def setUp(self):
        self.us = UnitSystem()

    def test_g_sim_is_one(self):
        self.assertEqual(self.us.G_sim, 1.0)

    def test_T0_formula(self):
        """T0 = sqrt(L0^3 / (G_SI * M0))"""
        expected = math.sqrt(AU ** 3 / (G_SI * SOLAR_MASS))
        self.assertAlmostEqual(self.us.T0, expected, places=12)

    def test_1_au_is_1_du(self):
        self.assertAlmostEqual(self.us.to_simulation(1.0, 'AU'), 1.0, places=12)

    def test_1_m_sun_is_1_mu(self):
        self.assertAlmostEqual(
            self.us.to_simulation(1.0, 'M_sun'), 1.0, places=12
        )

    def test_earth_mass_approximately_3_003e_6_mu(self):
        """5.972e24 kg -> 约 3.003e-6 MU"""
        mu = self.us.to_simulation(5.972e24, 'kg')
        self.assertAlmostEqual(mu, 3.003e-6, delta=3.003e-6 * 0.01)

    def test_earth_orbital_velocity_approximately_1(self):
        """v = sqrt(G*M_sun/AU) 约等于 1 个归一化速度单位"""
        v = math.sqrt(G_SI * SOLAR_MASS / AU)
        vu = self.us.to_simulation(v, 'm/s')
        self.assertAlmostEqual(vu, 1.0, places=6)

    def test_earth_velocity_km_s(self):
        """常用值 29.78 km/s 约等于 1"""
        vu = self.us.to_simulation(29.78, 'km/s')
        self.assertAlmostEqual(vu, 1.0, places=3)

    def test_one_year_approximately_2pi_tu(self):
        """1 year -> 约 2π TU"""
        tu = self.us.to_simulation(1.0, 'year')
        self.assertAlmostEqual(tu, 2.0 * math.pi, delta=0.01)

    def test_from_simulation_2pi_year_is_one_year(self):
        """2π TU -> 约 1 year（交叉验证）"""
        years = self.us.from_simulation(2.0 * math.pi, 'year')
        self.assertAlmostEqual(years, 1.0, delta=0.01)

    def test_from_simulation_au_and_m(self):
        self.assertAlmostEqual(self.us.from_simulation(1.0, 'AU'), 1.0)
        self.assertAlmostEqual(self.us.from_simulation(1.0, 'm'), AU)

    def test_1_au_t0_is_1_velocity_unit(self):
        """1 AU/T0 即标准速度单位"""
        self.assertAlmostEqual(self.us.to_simulation(1.0, 'AU/T0'), 1.0, places=12)

    def test_day_equals_86400_s(self):
        self.assertAlmostEqual(
            self.us.to_simulation(1.0, 'day'),
            self.us.to_simulation(86400.0, 's'),
            places=9,
        )


class TestParse(unittest.TestCase):
    """parse() 接口"""

    def setUp(self):
        self.us = UnitSystem()

    def test_parse_common_formats(self):
        cases = [
            ("1 AU", (1.0, 'AU')),
            ("5.972e24 kg", (5.972e24, 'kg')),
            ("3.003e-6 M_sun", (3.003e-6, 'M_sun')),
            ("29.78 km/s", (29.78, 'km/s')),
            ("1 year", (1.0, 'year')),
            ("9.8 m/s²", (9.8, 'm/s²')),
            ("0.1", (0.1, '')),
            ("1e-6", (1e-6, '')),
            ("1 AU/T0", (1.0, 'AU/T0')),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.us.parse(text), expected)

    def test_parse_case_and_aliases(self):
        self.assertEqual(self.us.parse("1 au"), (1.0, 'AU'))
        self.assertEqual(self.us.parse("1 Msun"), (1.0, 'M_sun'))
        self.assertEqual(self.us.parse("1 yr"), (1.0, 'year'))
        self.assertEqual(self.us.parse("9.8 m/s2"), (9.8, 'm/s²'))

    def test_parse_unsupported_unit_raises(self):
        with self.assertRaises(ValueError):
            self.us.parse("1 parsec")

    def test_parse_invalid_number_raises(self):
        with self.assertRaises(ValueError):
            self.us.parse("abc AU")


class TestFormat(unittest.TestCase):
    """format() 接口"""

    def setUp(self):
        self.us = UnitSystem()

    def test_format_au(self):
        self.assertEqual(self.us.format(1.0, 'AU'), "1 AU")

    def test_format_m_sun_scientific(self):
        self.assertEqual(self.us.format(3.003e-6, 'M_sun'), "3.003e-6 M_sun")

    def test_format_plain_simulation(self):
        self.assertEqual(self.us.format(1e-6, ''), "1e-6")


class TestRoundTrip(unittest.TestCase):
    """to_simulation / from_simulation 往返一致性"""

    def setUp(self):
        self.us = UnitSystem()

    CASES = [
        (1.0, 'AU'),
        (AU, 'm'),
        (1.5e8, 'km'),
        (1.0, 'M_sun'),
        (5.972e24, 'kg'),
        (1.0, 'year'),
        (1.0, 'day'),
        (86400.0, 's'),
        (29.78, 'km/s'),
        (1.0, 'AU/T0'),
        (9.8, 'm/s²'),
        (1e-3, 'km/s²'),
    ]

    def test_round_trip(self):
        for value, unit in self.CASES:
            with self.subTest(unit=unit):
                sim = self.us.to_simulation(value, unit)
                back = self.us.from_simulation(sim, unit)
                self.assertAlmostEqual(back, value, places=6)


class TestSimulationUnitAliases(unittest.TestCase):
    """DU / MU / TU 身份映射"""

    def setUp(self):
        self.us = UnitSystem()

    def test_identity_units(self):
        self.assertEqual(self.us.to_simulation(3.0, 'DU'), 3.0)
        self.assertEqual(self.us.to_simulation(2.0, 'MU'), 2.0)
        self.assertEqual(self.us.to_simulation(5.0, 'TU'), 5.0)
        self.assertEqual(self.us.to_simulation(7.0, 'DU/TU'), 7.0)
        self.assertEqual(self.us.to_simulation(4.0, 'DU/TU²'), 4.0)


if __name__ == '__main__':
    unittest.main()
