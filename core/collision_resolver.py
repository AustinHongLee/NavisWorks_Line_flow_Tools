# -*- coding: utf-8 -*-
"""resolved_mapping collision 決策讀寫工具。"""
from __future__ import annotations

from datetime import datetime
import os
from typing import Optional

import pandas as pd


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _read_mapping(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 resolved_mapping.csv：{path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


CHOICE_COLUMNS = [
    "ParentArea",
    "ScopeRoot",
    "PipeNodeLevel",
    "Raw_3D_PipeCode",
    "PipeNodePath",
]


def _choice_col_for_sub(df: pd.DataFrame) -> str:
    """Choose the most useful dimension for a collision group."""
    fallback = ""
    for col in CHOICE_COLUMNS:
        if col not in df.columns:
            continue
        values = {
            str(v).strip()
            for v in df[col].tolist()
            if str(v).strip()
        }
        if values and not fallback:
            fallback = col
        if len(values) > 1:
            return col
    return fallback


def load_collision_groups(mapping_path: str) -> list[dict[str, object]]:
    """讀取 ``NeedsDecision=1`` 的 collision 群組。"""
    df = _read_mapping(mapping_path)
    required = {"流水號", "Raw_3D_PipeCode", "NeedsDecision"}
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("resolved_mapping 缺少欄位：" + ", ".join(missing))

    if not any(col in df.columns for col in CHOICE_COLUMNS):
        raise ValueError(
            "resolved_mapping 缺少 collision 決策欄位："
            + " / ".join(CHOICE_COLUMNS)
        )

    pending = df[df["NeedsDecision"].apply(_truthy)].copy()
    groups: list[dict[str, object]] = []
    for spool, sub in pending.groupby("流水號", sort=False):
        spool_key = str(spool).strip()
        if not spool_key:
            continue
        area_col = _choice_col_for_sub(sub)
        if not area_col:
            continue
        choices: list[dict[str, object]] = []
        for area, area_sub in sub.groupby(area_col, sort=False):
            area_key = str(area).strip()
            if not area_key:
                continue
            raws = [
                str(v).strip()
                for v in area_sub["Raw_3D_PipeCode"].tolist()
                if str(v).strip()
            ]
            paths = [
                str(v).strip()
                for v in area_sub.get("PipeNodePath", pd.Series([], dtype=str)).tolist()
                if str(v).strip()
            ]
            choices.append(
                {
                    "area": area_key,
                    "row_count": int(len(area_sub)),
                    "raw_count": int(len(set(raws))),
                    "sample_raw": raws[0] if raws else "",
                    "sample_path": paths[0] if paths else "",
                }
            )
        if len(choices) > 1:
            groups.append(
                {
                    "spool": spool_key,
                    "area_col": area_col,
                    "choices": choices,
                    "row_count": int(len(sub)),
                }
            )
    return groups


def apply_collision_decisions(
    mapping_path: str,
    decisions: dict[str, object],
    output_path: Optional[str] = None,
) -> dict[str, int | str]:
    """套用 collision 人工決策。

    ``decisions`` 支援舊格式 ``{"流水號": "區域值"}``，也支援新格式
    ``{"流水號": {"area_col": "PipeNodeLevel", "area": "5"}}``。
    """
    df = _read_mapping(mapping_path)
    if output_path is None:
        output_path = mapping_path
    if not decisions:
        return {"path": output_path, "selected": 0, "rejected": 0, "spools": 0}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    selected = 0
    rejected = 0

    for spool, decision in decisions.items():
        spool_key = str(spool).strip()
        if isinstance(decision, dict):
            area_col = str(decision.get("area_col", "")).strip()
            area = decision.get("area", "")
        else:
            area_col = ""
            area = decision
        area_key = str(area).strip()
        if not spool_key or not area_key:
            continue
        spool_mask = df["流水號"].astype(str).str.strip().eq(spool_key)
        pending_mask = df["NeedsDecision"].apply(_truthy) if "NeedsDecision" in df.columns else spool_mask
        target = spool_mask & pending_mask
        if not target.any():
            continue
        if not area_col or area_col not in df.columns:
            area_col = _choice_col_for_sub(df[target])
        if not area_col or area_col not in df.columns:
            continue
        choose = target & df[area_col].astype(str).str.strip().eq(area_key)
        reject = target & ~choose

        df.loc[choose, "Resolved"] = "1"
        df.loc[choose, "ResolutionStatus"] = "user_selected"
        df.loc[choose, "ResolutionReason"] = f"人工選定 {area_col}={area_key}"
        df.loc[choose, "ResolvedBy"] = "user"
        df.loc[choose, "ResolvedAt"] = now
        df.loc[choose, "NeedsDecision"] = "0"

        df.loc[reject, "Resolved"] = "0"
        df.loc[reject, "ResolutionStatus"] = "user_rejected"
        df.loc[reject, "ResolutionReason"] = f"人工排除，選定 {area_col}={area_key}"
        df.loc[reject, "ResolvedBy"] = "user"
        df.loc[reject, "ResolvedAt"] = now
        df.loc[reject, "NeedsDecision"] = "0"

        selected += int(choose.sum())
        rejected += int(reject.sum())

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return {
        "path": output_path,
        "selected": selected,
        "rejected": rejected,
        "spools": len(decisions),
    }
