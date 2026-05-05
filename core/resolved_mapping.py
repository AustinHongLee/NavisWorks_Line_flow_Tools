# -*- coding: utf-8 -*-
"""Build the final, JSON-safe mapping from iso_match output."""
from __future__ import annotations

from datetime import datetime
import os
from typing import Callable, Optional

import pandas as pd


MATCH_TYPE_SCORES = {
    "strict": 1.0,
    "strip_size": 0.95,
    "drop_last_seg": 0.85,
    "fallback_base": 0.7,
    "fuzzy_manual": 0.9,
    "loose_only": 0.5,
}


OUTPUT_COLUMNS = [
    "Resolved",
    "ResolutionStatus",
    "ResolutionReason",
    "ResolvedAt",
    "ResolvedBy",
    "流水號",
    "管線編號",
    "ISO_Match_Key",
    "Raw_3D_PipeCode",
    "PipeNodePath",
    "ScopeRoot",
    "ParentArea",
    "PipeNodeLevel",
    "MatchType",
    "MatchScore",
    "MatchSource",
    "ConfidencePrimary",
    "IdentityReason",
    "CollisionCount",
    "CollisionParents",
    "NeedsDecision",
    "群組",
]


def _read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet = "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
        try:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
        finally:
            try:
                xls.close()
            except Exception:
                pass
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return df.rename(columns={c: str(c).strip() for c in df.columns})


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _to_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _score_match(
    match_type: object,
    confidence: object,
    explicit_score: object = "",
) -> float:
    explicit = _to_float(explicit_score)
    if explicit > 0:
        return explicit
    mt = str(match_type).strip()
    if mt in MATCH_TYPE_SCORES:
        return MATCH_TYPE_SCORES[mt]
    return _to_float(confidence)


def build_resolved_mapping(
    iso_match_path: str,
    output_path: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> dict[str, int | str]:
    """Create ``resolved_mapping.csv`` from ``iso_match.xlsx``.

    Rows with collisions are retained for audit but marked ``Resolved=0`` so
    JSON export can skip them by default.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not os.path.exists(iso_match_path):
        raise FileNotFoundError(f"找不到 iso_match 檔案：{iso_match_path}")

    df = _read_table(iso_match_path)
    if "Raw_3D_PipeCode" not in df.columns and "Raw_last" in df.columns:
        df = df.rename(columns={"Raw_last": "Raw_3D_PipeCode"})
    if "Raw_3D_PipeCode" not in df.columns:
        raise ValueError("iso_match 缺少必要欄位 Raw_3D_PipeCode")

    output_columns = list(OUTPUT_COLUMNS)
    for col in df.columns:
        col_name = str(col).strip()
        if not col_name or col_name.startswith("__"):
            continue
        if col_name not in output_columns:
            output_columns.append(col_name)

    for col in output_columns:
        if col not in df.columns:
            df[col] = ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["Raw_3D_PipeCode"] = df["Raw_3D_PipeCode"].astype(str).str.strip()
    df["NeedsDecision"] = df["NeedsDecision"].astype(str).str.strip()
    df["MatchScore"] = df.apply(
        lambda r: _score_match(
            r.get("MatchType", ""),
            r.get("ConfidencePrimary", ""),
            r.get("MatchScore", ""),
        ),
        axis=1,
    )

    statuses: list[str] = []
    reasons: list[str] = []
    resolved_flags: list[int] = []
    for _, row in df.iterrows():
        raw = str(row.get("Raw_3D_PipeCode", "")).strip()
        if not raw:
            resolved_flags.append(0)
            statuses.append("no_raw")
            reasons.append("沒有可輸出的 3D Raw_3D_PipeCode")
        elif _truthy(row.get("NeedsDecision", "")):
            resolved_flags.append(0)
            statuses.append("needs_decision")
            reasons.append("同一流水號對應多個 ParentArea/ScopeRoot，需人工決定")
        else:
            resolved_flags.append(1)
            statuses.append("auto")
            reasons.append("非碰撞列，自動納入 JSON-safe mapping")

    df["Resolved"] = resolved_flags
    df["ResolutionStatus"] = statuses
    df["ResolutionReason"] = reasons
    df["ResolvedAt"] = now
    df["ResolvedBy"] = df.apply(
        lambda r: (
            "user"
            if int(r.get("Resolved", 0)) == 1
            and str(r.get("MatchType", "")).strip() == "fuzzy_manual"
            else ("auto" if int(r.get("Resolved", 0)) == 1 else "")
        ),
        axis=1,
    )

    result = df[output_columns].drop_duplicates(
        subset=[
            "Resolved",
            "ResolutionStatus",
            "流水號",
            "Raw_3D_PipeCode",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
        ],
        keep="first",
    )

    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(iso_match_path)),
            "resolved_mapping.csv",
        )
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    identity_index_path = ""
    minus1_path = os.path.join(
        os.path.dirname(os.path.abspath(output_path)),
        "123_minus_1.csv",
    )
    if os.path.exists(minus1_path):
        try:
            from core.identity_index import build_identity_index

            identity_index_path = build_identity_index(
                output_path,
                minus1_path,
            )
            _log(f"[ResolvedMapping] 已建立調查索引：{identity_index_path}")
        except Exception as exc:
            _log(f"[ResolvedMapping] 調查索引建立失敗，略過：{exc}")

    total = int(len(result))
    resolved = int((result["Resolved"].astype(str) == "1").sum())
    needs = int((result["ResolutionStatus"] == "needs_decision").sum())
    no_raw = int((result["ResolutionStatus"] == "no_raw").sum())
    _log(
        f"[ResolvedMapping] 已輸出 {output_path}，"
        f"resolved={resolved}, needs_decision={needs}, no_raw={no_raw}, total={total}"
    )

    return {
        "path": output_path,
        "identity_index_path": identity_index_path,
        "total": total,
        "resolved": resolved,
        "needs_decision": needs,
        "no_raw": no_raw,
    }
