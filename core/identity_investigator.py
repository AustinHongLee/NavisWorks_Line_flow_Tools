# -*- coding: utf-8 -*-
"""跨中間檔的 read-only 身份調查工具。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pandas as pd

from utils.utils_common import normalize_line_v2


_MAX_ROWS = 200


@dataclass(frozen=True)
class InvestigationPaths:
    base_dir: str
    first_csv: str
    first_try_trace_csv: str
    candidates_csv: str
    minus1_csv: str
    iso_match_xlsx: str
    resolved_mapping_csv: str
    identity_index_csv: str


def make_paths(base_dir: str, first_name: str = "First_try.csv") -> InvestigationPaths:
    base = os.path.abspath(str(base_dir or ""))
    return InvestigationPaths(
        base_dir=base,
        first_csv=os.path.join(base, first_name or "First_try.csv"),
        first_try_trace_csv=os.path.join(base, "first_try_trace.csv"),
        candidates_csv=os.path.join(base, "candidates.csv"),
        minus1_csv=os.path.join(base, "123_minus_1.csv"),
        iso_match_xlsx=os.path.join(base, "iso_match.xlsx"),
        resolved_mapping_csv=os.path.join(base, "resolved_mapping.csv"),
        identity_index_csv=os.path.join(base, "identity_index.csv"),
    )


def _read_csv(path: str, usecols: list[str] | None = None) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(
            path,
            dtype=str,
            encoding="utf-8-sig",
            usecols=lambda c: usecols is None or c in usecols,
        ).fillna("")
    except Exception:
        return pd.DataFrame()


def _read_iso_match(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet = "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
        try:
            return pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
        finally:
            try:
                xls.close()
            except Exception:
                pass
    except Exception:
        return pd.DataFrame()


def _text_mask(df: pd.DataFrame, columns: list[str], needles: list[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    mask = pd.Series(False, index=df.index)
    usable_cols = [c for c in columns if c in df.columns]
    clean_needles = [n for n in needles if n]
    if not usable_cols or not clean_needles:
        return mask
    for col in usable_cols:
        series = df[col].astype(str)
        for needle in clean_needles:
            mask = mask | series.str.contains(needle, case=False, regex=False, na=False)
    return mask


def _drop_last(value: str) -> str:
    parts = [p for p in str(value).strip().split("-") if p]
    if len(parts) <= 1:
        return str(value).strip()
    return "-".join(parts[:-1])


def _series_prefix(value: str) -> str:
    drop = _drop_last(value)
    parts = [p for p in drop.split("-") if p]
    if len(parts) <= 1:
        return drop
    return "-".join(parts[:-1])


def _records(df: pd.DataFrame, columns: list[str], limit: int = _MAX_ROWS) -> list[dict[str, str]]:
    if df.empty:
        return []
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return (
        df[columns]
        .head(limit)
        .fillna("")
        .astype(str)
        .to_dict("records")
    )


def _level_summary(df: pd.DataFrame) -> list[dict[str, str]]:
    if df.empty:
        return []
    for col in ["Level", "Raw_3D_PipeCode", "ISO_Match_Key", "ScopeRoot", "ParentArea", "MatchSource"]:
        if col not in df.columns:
            df[col] = ""
    grouped = []
    for level, g in df.groupby(df["Level"].astype(str), dropna=False):
        first = g.iloc[0]
        grouped.append({
            "Level": str(level),
            "筆數": str(len(g)),
            "Raw_3D_PipeCode": str(first.get("Raw_3D_PipeCode", "")),
            "ISO_Match_Key": str(first.get("ISO_Match_Key", "")),
            "ScopeRoot": str(first.get("ScopeRoot", "")),
            "ParentArea": str(first.get("ParentArea", "")),
            "MatchSource": str(first.get("MatchSource", "")),
        })
    return sorted(grouped, key=lambda r: (r["Level"].zfill(4), r["Raw_3D_PipeCode"]))


def investigate_identity(
    query: str,
    paths: InvestigationPaths,
    max_rows: int = _MAX_ROWS,
) -> dict[str, Any]:
    """查詢一條 ISO/3D 字串在各中間檔的可見脈絡。"""
    raw_query = str(query or "").strip()
    normalized, norm_events = normalize_line_v2(raw_query)
    drop_last = _drop_last(normalized)
    series = _series_prefix(normalized)
    compact = raw_query.strip("/")
    needles = list(dict.fromkeys([
        raw_query,
        compact,
        normalized,
        drop_last,
        series,
    ]))

    minus1 = _read_csv(paths.minus1_csv)
    first_trace = _read_csv(paths.first_try_trace_csv)
    if not first_trace.empty:
        first = first_trace
        first_source = "first_try_trace.csv"
    else:
        first = _read_csv(
            paths.first_csv,
            usecols=["Path", "DisplayName", "Class", "Level", "PipelineId"],
        )
        first_source = "First_try.csv"
    resolved = _read_csv(paths.resolved_mapping_csv)
    iso_match = _read_iso_match(paths.iso_match_xlsx)
    identity_index = _read_csv(paths.identity_index_csv)
    candidates = _read_csv(paths.candidates_csv)

    iso_source = resolved if not resolved.empty else iso_match
    iso_mask = _text_mask(
        iso_source,
        ["流水號", "管線編號", "ISO_Match_Key", "Raw_3D_PipeCode"],
        needles,
    )
    iso_hits = iso_source[iso_mask].copy() if not iso_source.empty else pd.DataFrame()

    minus_mask = _text_mask(
        minus1,
        [
            "Path",
            "DisplayName",
            "PipelineId",
            "Raw_3D_PipeCode",
            "ISO_Match_Key",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
        ],
        needles,
    )
    minus_hits = minus1[minus_mask].copy() if not minus1.empty else pd.DataFrame()

    first_mask = _text_mask(
        first,
        [
            "Path",
            "DisplayName",
            "PipelineId",
            "best_candidate_raw",
            "best_candidate_normalized",
        ],
        needles,
    )
    first_hits = first[first_mask].copy() if not first.empty else pd.DataFrame()

    index_mask = _text_mask(
        identity_index,
        [
            "iso_norm",
            "iso_norm_drop_last",
            "iso_series_prefix",
            "iso_pipe_raw",
            "iso_spool",
            "sample_3d_paths",
        ],
        needles,
    )
    index_hits = identity_index[index_mask].copy() if not identity_index.empty else pd.DataFrame()

    candidate_mask = _text_mask(
        candidates,
        [
            "candidate_kind",
            "iso_candidate",
            "raw",
            "normalized",
            "matched_terms",
            "missing_terms",
            "reason",
            "Path",
            "DisplayName",
            "PipelineId",
        ],
        needles,
    )
    candidate_hits = candidates[candidate_mask].copy() if not candidates.empty else pd.DataFrame()

    family = {
        "query": raw_query,
        "normalized": normalized,
        "normalize_events": "; ".join(norm_events),
        "drop_last": drop_last,
        "series_prefix": series,
        "strict_3d_count": "0",
        "drop_last_3d_count": "0",
        "series_3d_count": "0",
        "minus1_hit_count": str(len(minus_hits)),
        "first_try_hit_count": str(len(first_hits)),
        "iso_hit_count": str(len(iso_hits)),
        "identity_index_hit_count": str(len(index_hits)),
        "candidate_hit_count": str(len(candidate_hits)),
        "first_try_source": first_source,
    }
    if not minus1.empty and "ISO_Match_Key" in minus1.columns:
        keys = minus1["ISO_Match_Key"].astype(str)
        family["strict_3d_count"] = str((keys == normalized).sum())
        family["drop_last_3d_count"] = str((keys == drop_last).sum())
        family["series_3d_count"] = str(keys.str.contains(series, case=False, regex=False, na=False).sum()) if series else "0"
    if not index_hits.empty:
        idx_row = index_hits.iloc[0]
        for target, source in [
            ("strict_3d_count", "match_3d_strict_count"),
            ("drop_last_3d_count", "match_3d_droplast_count"),
            ("series_3d_count", "match_3d_series_count"),
        ]:
            value = str(idx_row.get(source, "")).strip()
            if value:
                family[target] = value

    iso_columns = [
        "流水號",
        "管線編號",
        "ISO_Match_Key",
        "Raw_3D_PipeCode",
        "Resolved",
        "ResolutionStatus",
        "MatchType",
        "MatchScore",
        "NeedsDecision",
    ]
    minus_columns = [
        "Level",
        "Raw_3D_PipeCode",
        "ISO_Match_Key",
        "DisplayName",
        "PipelineId",
        "ScopeRoot",
        "ParentArea",
        "MatchSource",
        "ConfidencePrimary",
        "IdentityReason",
    ]
    first_columns = [
        "Path",
        "DisplayName",
        "Class",
        "Level",
        "PipelineId",
        "included_in_minus_1",
        "exclude_reason",
        "exclude_detail",
        "best_candidate_normalized",
        "minus_1_row_idx",
        "recall_candidate_count",
        "best_recall_iso",
        "best_recall_score",
        "best_recall_raw",
        "best_recall_terms",
        "best_recall_reason",
    ]
    candidate_columns = [
        "candidate_kind",
        "score",
        "iso_candidate",
        "raw",
        "normalized",
        "source",
        "matched_terms",
        "reason",
        "review_status",
        "Path",
    ]

    return {
        "paths": paths.__dict__,
        "query": raw_query,
        "family": family,
        "iso_rows": _records(iso_hits, iso_columns, max_rows),
        "level_summary": _level_summary(minus_hits),
        "minus1_rows": _records(minus_hits, minus_columns, max_rows),
        "first_try_rows": _records(first_hits, first_columns, max_rows),
        "candidate_rows": _records(candidate_hits, candidate_columns, max_rows),
        "identity_index_rows": _records(index_hits, [
            "iso_spool",
            "iso_pipe_raw",
            "iso_norm",
            "iso_norm_drop_last",
            "match_3d_droplast_count",
            "match_3d_family_count",
            "sample_3d_paths",
        ], max_rows),
        "has_first_try": os.path.exists(paths.first_csv),
        "has_first_try_trace": os.path.exists(paths.first_try_trace_csv),
        "has_identity_index": os.path.exists(paths.identity_index_csv),
        "has_candidates": os.path.exists(paths.candidates_csv),
        "has_minus1": os.path.exists(paths.minus1_csv),
        "has_iso_source": os.path.exists(paths.resolved_mapping_csv) or os.path.exists(paths.iso_match_xlsx),
    }
