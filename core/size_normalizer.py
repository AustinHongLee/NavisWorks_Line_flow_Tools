# -*- coding: utf-8 -*-
"""管徑尺寸正規化：把各種 inch 分數變體規範成 NPS 標準字串。"""
from __future__ import annotations

import re
from typing import Final, Optional


NPS_SIZES: Final[dict[float, str]] = {
    0.125: "1/8",
    0.25: "1/4",
    0.375: "3/8",
    0.5: "1/2",
    0.75: "3/4",
    1.0: "1",
    1.25: "1-1/4",
    1.5: "1-1/2",
    2.0: "2",
    2.5: "2-1/2",
    3.0: "3",
    3.5: "3-1/2",
    4.0: "4",
    5.0: "5",
    6.0: "6",
    8.0: "8",
    10.0: "10",
    12.0: "12",
    14.0: "14",
    16.0: "16",
    18.0: "18",
    20.0: "20",
    24.0: "24",
    30.0: "30",
    36.0: "36",
    42.0: "42",
    48.0: "48",
}

STATUS_MATCHED: Final = "matched"
STATUS_NON_STANDARD: Final = "non_standard"
STATUS_PASSTHROUGH_INT: Final = "passthrough_int"
STATUS_UNKNOWN: Final = "unknown"

_FLOAT_RE: Final = re.compile(r"^\d+\.\d+$")
_FRACTION_RE: Final = re.compile(r"^(\d+)/(\d+)$")
_MIXED_RE: Final = re.compile(r"^(\d+)[\s\-_.](\d+)/(\d+)$")
_BUG_DOT_UNDER_RE: Final = re.compile(r"^(\d+)\.(\d+)_(\d+)$")
_ALPHA_RE: Final = re.compile(r"[A-Za-z]")
_NUMERIC_RE: Final = re.compile(r"^\d+(\.\d+)?$")


def _lookup_nps(
    value: float,
    nps_sizes: dict[float, str],
    tolerance: float = 0.001,
) -> str | None:
    for inches, canonical in nps_sizes.items():
        if abs(float(inches) - value) <= tolerance:
            return canonical
    return None


def _status_for_value(
    token: str,
    value: float,
    nps_sizes: dict[float, str],
) -> tuple[str, float, str]:
    canonical = _lookup_nps(value, nps_sizes)
    if canonical is not None:
        return canonical, value, STATUS_MATCHED
    return token, value, STATUS_NON_STANDARD


def _fraction_value(num: str, den: str) -> float | None:
    denominator = int(den)
    if denominator == 0:
        return None
    return int(num) / denominator


def normalize_size_token(
    token: str,
    nps_sizes: Optional[dict[float, str]] = None,
) -> tuple[str, float | None, str]:
    """把單一尺寸 token 規範化。

    整數值代表可能是 mm 或流水號片段，會原樣放行不解讀；其他
    inch 分數變體會先解析成數值，再對照 NPS 標準表。
    """
    original = "" if token is None else str(token)
    value = original.strip()
    sizes = nps_sizes or NPS_SIZES

    if not value:
        return original, None, STATUS_UNKNOWN

    if value.isdigit():
        return value, None, STATUS_PASSTHROUGH_INT

    if _FLOAT_RE.match(value):
        return _status_for_value(value, float(value), sizes)

    match = _FRACTION_RE.match(value)
    if match:
        frac_value = _fraction_value(match.group(1), match.group(2))
        if frac_value is None:
            return value, None, STATUS_UNKNOWN
        canonical = _lookup_nps(frac_value, sizes)
        if canonical is not None:
            return canonical, frac_value, STATUS_MATCHED

        numerator = int(match.group(1))
        denominator = int(match.group(2))
        if numerator >= 10 and frac_value > 5:
            glued = str(numerator)
            whole = int(glued[:-1])
            frac_num = int(glued[-1:])
            retry_value = whole + (frac_num / denominator)
            retry_canonical = _lookup_nps(retry_value, sizes)
            if retry_canonical is not None:
                return retry_canonical, retry_value, STATUS_MATCHED

        return value, frac_value, STATUS_NON_STANDARD

    match = _MIXED_RE.match(value)
    if match:
        denominator = int(match.group(3))
        if denominator == 0:
            return value, None, STATUS_UNKNOWN
        mixed_value = int(match.group(1)) + (int(match.group(2)) / denominator)
        return _status_for_value(value, mixed_value, sizes)

    match = _BUG_DOT_UNDER_RE.match(value)
    if match:
        denominator = int(match.group(3))
        if denominator == 0:
            return value, None, STATUS_UNKNOWN
        bug_value = int(match.group(1)) + (int(match.group(2)) / denominator)
        return _status_for_value(value, bug_value, sizes)

    return value, None, STATUS_UNKNOWN


def is_size_like(token: str) -> bool:
    """判斷 token 是否看起來像尺寸片段。"""
    value = "" if token is None else str(token).strip()
    if not value or _ALPHA_RE.search(value):
        return False
    if _NUMERIC_RE.match(value):
        return True
    if _FRACTION_RE.match(value):
        return True
    if _MIXED_RE.match(value):
        return True
    if _BUG_DOT_UNDER_RE.match(value):
        return True
    return False
