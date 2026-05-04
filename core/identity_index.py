# -*- coding: utf-8 -*-
"""建立調查頁使用的 ISO ↔ 3D 身份索引。"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from core.iso_matcher import _strip_size_segment
from utils.utils_common import normalize_line_v2


INDEX_COLUMNS = [
    "iso_norm",
    "iso_norm_drop_last",
    "iso_norm_strip_size",
    "iso_series_prefix",
    "iso_pipe_raw",
    "iso_spool",
    "match_3d_strict_count",
    "match_3d_droplast_count",
    "match_3d_family_count",
    "match_3d_series_count",
    "sample_3d_paths",
]


def _read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _drop_last(value: str) -> str:
    parts = [p for p in str(value).strip().split("-") if p]
    if len(parts) <= 1:
        return str(value).strip()
    return "-".join(parts[:-1])


def _series_prefix(value: str) -> str:
    dropped = _drop_last(value)
    parts = [p for p in dropped.split("-") if p]
    if len(parts) <= 1:
        return dropped
    return "-".join(parts[:-1])


def _sample_paths(df: pd.DataFrame, limit: int = 3) -> str:
    if df.empty:
        return ""
    values: list[str] = []
    for col in ["PipeNodePath", "Path", "Raw_3D_PipeCode", "ISO_Match_Key"]:
        if col not in df.columns:
            continue
        for value in df[col].astype(str).tolist():
            clean = value.strip()
            if clean and clean not in values:
                values.append(clean)
            if len(values) >= limit:
                return " | ".join(values)
    return " | ".join(values)


def build_identity_index(
    resolved_mapping_path: str,
    minus1_path: str,
    output_path: Optional[str] = None,
) -> str:
    """從 resolved_mapping/minus_1 建立調查用索引檔。"""
    resolved = _read_csv(resolved_mapping_path)
    minus1 = _read_csv(minus1_path)
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(resolved_mapping_path)),
            "identity_index.csv",
        )
    if resolved.empty:
        pd.DataFrame(columns=INDEX_COLUMNS).to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig",
        )
        return output_path

    if "管線編號" not in resolved.columns:
        resolved["管線編號"] = ""
    if "流水號" not in resolved.columns:
        resolved["流水號"] = ""
    if "ISO_Match_Key" not in minus1.columns:
        minus1["ISO_Match_Key"] = ""
    minus_keys = minus1["ISO_Match_Key"].astype(str)

    rows: list[dict[str, object]] = []
    for _, row in resolved[["流水號", "管線編號"]].drop_duplicates().iterrows():
        iso_raw = str(row.get("管線編號", "")).strip()
        iso_spool = str(row.get("流水號", "")).strip()
        iso_norm, _events = normalize_line_v2(iso_raw)
        drop_last = _drop_last(iso_norm)
        strip_size = _strip_size_segment(iso_norm)
        series = _series_prefix(iso_norm)

        strict_mask = minus_keys.eq(iso_norm) if iso_norm else pd.Series(False, index=minus1.index)
        drop_mask = minus_keys.eq(drop_last) if drop_last else pd.Series(False, index=minus1.index)
        family_mask = minus_keys.str.contains(drop_last, case=False, regex=False, na=False) if drop_last else pd.Series(False, index=minus1.index)
        series_mask = minus_keys.str.contains(series, case=False, regex=False, na=False) if series else pd.Series(False, index=minus1.index)
        sample_df = minus1[strict_mask | drop_mask | family_mask | series_mask]

        rows.append(
            {
                "iso_norm": iso_norm,
                "iso_norm_drop_last": drop_last,
                "iso_norm_strip_size": strip_size,
                "iso_series_prefix": series,
                "iso_pipe_raw": iso_raw,
                "iso_spool": iso_spool,
                "match_3d_strict_count": int(strict_mask.sum()),
                "match_3d_droplast_count": int(drop_mask.sum()),
                "match_3d_family_count": int(family_mask.sum()),
                "match_3d_series_count": int(series_mask.sum()),
                "sample_3d_paths": _sample_paths(sample_df),
            }
        )

    pd.DataFrame(rows, columns=INDEX_COLUMNS).to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )
    return output_path
