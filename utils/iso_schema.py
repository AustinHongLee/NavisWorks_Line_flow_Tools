# -*- coding: utf-8 -*-
"""ISO workbook schema detection helpers.

Keep sheet/column detection in one place so GUI, workers, and core matching do
not drift apart as project-specific ISO layouts change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from utils.utils_common import CommonUtils, normalize_line_v2


PREFERRED_SHEETS = {
    "dwg no.all": 5,
    "drawing list": 4,
}

PIPE_EXACT_NAMES = [
    "line num",
    "line_no",
    "line no",
    "line number",
    "pipe no",
    "pipe number",
    "管線編號",
    "管線號",
]

PIPE_SKIP_NAMES = {
    "管線材質",
    "管線等級",
    "line type",
    "line class",
}

SPOOL_EXACT_NAMES = [
    "流水號",
    "series no",
    "spool no",
    "spool",
]

CATEGORY_EXACT_NAMES = [
    "發包分類",
    "category",
]


@dataclass
class IsoSchema:
    sheet_name: str
    pipe_col: str
    spool_col: str
    category_col: str = "發包分類"
    warnings: list[str] = field(default_factory=list)


def _norm_header(value: object) -> str:
    return str(value).strip().lower()


def _clean_columns(cols: list[object]) -> list[str]:
    return [str(c).strip() for c in cols if str(c).strip()]


def read_columns(xls: pd.ExcelFile, sheet_name: str) -> list[str]:
    df = pd.read_excel(
        xls,
        sheet_name=sheet_name,
        nrows=0,
        dtype=str,
        engine="openpyxl",
    )
    return _clean_columns(list(df.columns))


def detect_pipe_col(cols: list[str]) -> Optional[str]:
    by_norm = {_norm_header(c): c for c in cols}
    for name in PIPE_EXACT_NAMES:
        if name in by_norm:
            return by_norm[name]

    for c in cols:
        cl = _norm_header(c)
        if c in PIPE_SKIP_NAMES or cl in PIPE_SKIP_NAMES:
            continue
        if "管線" in cl or "line" in cl or "pipe" in cl:
            return c
    return None


def detect_spool_col(cols: list[str]) -> Optional[str]:
    by_norm = {_norm_header(c): c for c in cols}
    for name in SPOOL_EXACT_NAMES:
        if name in by_norm:
            return by_norm[name]

    for c in cols:
        cl = _norm_header(c)
        if "流水" in cl or "spool" in cl or "series" in cl:
            return c
    return None


def detect_category_col(cols: list[str]) -> str:
    by_norm = {_norm_header(c): c for c in cols}
    for name in CATEGORY_EXACT_NAMES:
        if name in by_norm:
            return by_norm[name]

    for c in cols:
        cl = _norm_header(c)
        if "分類" in c or "category" in cl:
            return c
    return "發包分類"


def score_sheet(xls: pd.ExcelFile, sheet_name: str) -> int:
    try:
        cols = read_columns(xls, sheet_name)
    except Exception:
        return -1

    score = PREFERRED_SHEETS.get(_norm_header(sheet_name), 0)
    if detect_pipe_col(cols):
        score += 2
    if detect_spool_col(cols):
        score += 1
    if "drawing" in sheet_name.lower():
        score += 1
    return score


def pick_best_sheet(xls: pd.ExcelFile) -> str:
    best_name = xls.sheet_names[0]
    best_score = -1
    for name in xls.sheet_names:
        s = score_sheet(xls, name)
        if s > best_score:
            best_score = s
            best_name = name
    return best_name


def detect_schema(
    xls: pd.ExcelFile,
    sheet_name: Optional[str] = None,
    pipe_col_override: Optional[str] = None,
    spool_col_override: Optional[str] = None,
) -> IsoSchema:
    warnings: list[str] = []
    if sheet_name:
        if sheet_name not in xls.sheet_names:
            raise ValueError(
                f"ISO 檔案中找不到指定工作表：{sheet_name}，可用工作表：{xls.sheet_names}"
            )
        sheet_to_use = sheet_name
    else:
        sheet_to_use = pick_best_sheet(xls)

    cols = read_columns(xls, sheet_to_use)

    if pipe_col_override:
        if pipe_col_override not in cols:
            raise ValueError(
                f"ISO 工作表找不到使用者指定的管線編號欄位：{pipe_col_override}"
            )
        pipe_col = pipe_col_override
    else:
        pipe_col = detect_pipe_col(cols)
        if not pipe_col:
            raise ValueError(
                "ISO 清單找不到『管線編號』或名稱中含 'line' 的欄位，"
                "請檢查 ISO 欄位名稱，或在 GUI 指定管線欄位名。"
            )

    if spool_col_override:
        if spool_col_override not in cols:
            raise ValueError(
                f"ISO 工作表找不到使用者指定的流水號欄位：{spool_col_override}"
            )
        spool_col = spool_col_override
    else:
        spool_col = detect_spool_col(cols)
        if not spool_col:
            spool_col = "流水號"
            warnings.append("ISO 清單找不到流水號欄位，已建立空白流水號欄。")

    return IsoSchema(
        sheet_name=sheet_to_use,
        pipe_col=pipe_col,
        spool_col=spool_col,
        category_col=detect_category_col(cols),
        warnings=warnings,
    )


def load_iso_line_key_set(
    iso_path: str,
    sheet_name: Optional[str] = None,
    pipe_col_override: Optional[str] = None,
) -> set[str]:
    xls = pd.ExcelFile(iso_path, engine="openpyxl")
    try:
        schema = detect_schema(
            xls,
            sheet_name=sheet_name,
            pipe_col_override=pipe_col_override,
        )
        df = pd.read_excel(
            xls,
            sheet_name=schema.sheet_name,
            dtype=str,
            engine="openpyxl",
        ).fillna("")
    finally:
        try:
            xls.close()
        except Exception:
            pass

    keys: set[str] = set()
    if schema.pipe_col in df.columns:
        for value in df[schema.pipe_col].astype(str).str.strip().tolist():
            norm = CommonUtils.normalize_line(value)
            if norm:
                keys.add(norm)
            norm_v2, _events = normalize_line_v2(value)
            if norm_v2:
                keys.add(norm_v2)
    return keys
