# -*- coding: utf-8 -*-
import unittest

from core.size_normalizer import (
    STATUS_MATCHED,
    STATUS_NON_STANDARD,
    STATUS_PASSTHROUGH_INT,
    STATUS_UNKNOWN,
    is_size_like,
    normalize_size_token,
)


class NormalizeSizeTokenTests(unittest.TestCase):
    def _check(self, token, expected_canonical, expected_inches, expected_status):
        canonical, inches, status = normalize_size_token(token)
        self.assertEqual(canonical, expected_canonical, f"token={token!r}")
        self.assertEqual(inches, expected_inches, f"token={token!r}")
        self.assertEqual(status, expected_status, f"token={token!r}")

    def test_pure_int_50(self):
        self._check("50", "50", None, STATUS_PASSTHROUGH_INT)

    def test_pure_int_100(self):
        self._check("100", "100", None, STATUS_PASSTHROUGH_INT)

    def test_pure_int_150(self):
        self._check("150", "150", None, STATUS_PASSTHROUGH_INT)

    def test_pure_int_1(self):
        self._check("1", "1", None, STATUS_PASSTHROUGH_INT)

    def test_float_1_5(self):
        self._check("1.5", "1-1/2", 1.5, STATUS_MATCHED)

    def test_float_2_5(self):
        self._check("2.5", "2-1/2", 2.5, STATUS_MATCHED)

    def test_float_0_5(self):
        self._check("0.5", "1/2", 0.5, STATUS_MATCHED)

    def test_float_0_75(self):
        self._check("0.75", "3/4", 0.75, STATUS_MATCHED)

    def test_float_99_9(self):
        self._check("99.9", "99.9", 99.9, STATUS_NON_STANDARD)

    def test_frac_1_2(self):
        self._check("1/2", "1/2", 0.5, STATUS_MATCHED)

    def test_frac_3_4(self):
        self._check("3/4", "3/4", 0.75, STATUS_MATCHED)

    def test_frac_1_8(self):
        self._check("1/8", "1/8", 0.125, STATUS_MATCHED)

    def test_frac_3_8(self):
        self._check("3/8", "3/8", 0.375, STATUS_MATCHED)

    def test_under_frac_1_2(self):
        self._check("1_2", "1/2", 0.5, STATUS_MATCHED)

    def test_under_frac_3_4(self):
        self._check("3_4", "3/4", 0.75, STATUS_MATCHED)

    def test_under_frac_1_4(self):
        self._check("1_4", "1/4", 0.25, STATUS_MATCHED)

    def test_under_glued_11_2(self):
        self._check("11_2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_under_identifier_not_size(self):
        self._check("60371_2", "60371_2", None, STATUS_UNKNOWN)

    def test_glued_11_2(self):
        self._check("11/2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_glued_21_2(self):
        self._check("21/2", "2-1/2", 2.5, STATUS_MATCHED)

    def test_glued_31_2(self):
        self._check("31/2", "3-1/2", 3.5, STATUS_MATCHED)

    def test_mixed_1_space_1_2(self):
        self._check("1 1/2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_mixed_1_dash_1_2(self):
        self._check("1-1/2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_mixed_1_under_1_2(self):
        self._check("1_1/2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_mixed_2_space_1_2(self):
        self._check("2 1/2", "2-1/2", 2.5, STATUS_MATCHED)

    def test_mixed_2_dash_1_2(self):
        self._check("2-1/2", "2-1/2", 2.5, STATUS_MATCHED)

    def test_mixed_1_space_1_4(self):
        self._check("1 1/4", "1-1/4", 1.25, STATUS_MATCHED)

    def test_bug_1d1_2(self):
        self._check("1.1_2", "1-1/2", 1.5, STATUS_MATCHED)

    def test_bug_2d1_2(self):
        self._check("2.1_2", "2-1/2", 2.5, STATUS_MATCHED)

    def test_bug_1d1_4(self):
        self._check("1.1_4", "1-1/4", 1.25, STATUS_MATCHED)

    def test_bug_1d3_4(self):
        self._check("1.3_4", "1.3_4", 1.75, STATUS_NON_STANDARD)

    def test_unknown_AA1B(self):
        self._check("AA1B", "AA1B", None, STATUS_UNKNOWN)

    def test_unknown_empty(self):
        self._check("", "", None, STATUS_UNKNOWN)

    def test_unknown_foo(self):
        self._check("foo", "foo", None, STATUS_UNKNOWN)

    def test_unknown_12X34(self):
        self._check("12X34", "12X34", None, STATUS_UNKNOWN)


class IsSizeLikeTests(unittest.TestCase):
    def test_size_like_true_cases(self):
        for token in ("100", "1/2", "1_2", "3_4", "11_2", "1 1/2", "1.1_2", "1.5"):
            self.assertTrue(is_size_like(token), f"token={token!r}")

    def test_size_like_false_cases(self):
        for token in ("AA1B", "S11UG", "NA", "60371_2", ""):
            self.assertFalse(is_size_like(token), f"token={token!r}")

    def test_pure_int_is_size_like(self):
        self.assertTrue(is_size_like("60371"))


if __name__ == "__main__":
    unittest.main()
