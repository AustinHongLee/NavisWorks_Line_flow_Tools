# -*- coding: utf-8 -*-
import unittest

from utils.utils_common import normalize_line, normalize_line_v2


class NormalizeLineV1RegressionTests(unittest.TestCase):
    def test_strip_prefix_slash(self):
        self.assertEqual(normalize_line("/AC-1701-100"), "AC-1701-100")

    def test_keep_fraction_in_size(self):
        result = normalize_line('1/2"-AC')
        self.assertEqual(result, normalize_line('1/2"-AC'))


class NormalizeLineV2Tests(unittest.TestCase):
    def _check(self, raw, expected_norm):
        norm, _events = normalize_line_v2(raw, sep="-", apply_size_norm=True)
        self.assertEqual(norm, expected_norm, f"raw={raw!r}")

    def test_bug_dot_under(self):
        self._check("/1.1_2-S11UG-N4-60371", "1-1/2-S11UG-N4-60371")

    def test_under_fraction_half(self):
        self._check("/1_2-S11-P-20909T", "1/2-S11-P-20909T")

    def test_under_fraction_three_quarter(self):
        self._check("/3_4-S11G-N4-20951Q", "3/4-S11G-N4-20951Q")

    def test_mixed_space(self):
        self._check("/1 1/2-S11UG-N4-60371", "1-1/2-S11UG-N4-60371")

    def test_mixed_under(self):
        self._check("/1_1/2-S11UG-N4-60371", "1-1/2-S11UG-N4-60371")

    def test_mixed_dash(self):
        self._check("/1-1/2-S11UG-N4-60371", "1-1/2-S11UG-N4-60371")

    def test_float(self):
        self._check("/1.5-S11UG-N4-60371", "1-1/2-S11UG-N4-60371")

    def test_int_size_unchanged(self):
        self._check("AC-1701-100-AA1B-NA", "AC-1701-100-AA1B-NA")
        self._check("/AC-1701-100-AA1B-NA", "AC-1701-100-AA1B-NA")
        self._check("AR-12001-50-A1B-HC2", "AR-12001-50-A1B-HC2")

    def test_no_size_segment(self):
        self._check("AC-1701", "AC-1701")

    def test_trailing_identity_fraction_is_preserved(self):
        self._check(
            'E3302-3/4"DRAIN-S1P4-2/2',
            'E3302-3/4"DRAIN-S1P4-2/2',
        )

    def test_apply_size_norm_off_keeps_legacy_shape(self):
        norm, _events = normalize_line_v2(
            "/1.1_2-S11UG-N4-60371",
            sep="-",
            apply_size_norm=False,
        )
        self.assertIn("1.1_2", norm)


if __name__ == "__main__":
    unittest.main()
