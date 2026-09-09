# -*- coding: utf-8 -*-
"""Recover review candidates directly from an existing First_try export.

This is an explicit human-operated escape hatch.  It never writes project
files and never turns a score into a decision; it only proves that a candidate
identity exists in a concrete First_try row and returns its Path/Level context.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from core.candidate_family import annotate_candidate_families, candidate_item_id
from core.iso_recall_engine import IsoRecallEngine
from core.match_evidence import build_match_evidence
from core.scope_indexer import parse_scope_context
from utils.utils_common import normalize_line_v2


def _normalize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    n_cols = min(len(chunk.columns), 5)
    result = chunk.iloc[:, :n_cols].copy()
    names = ["Path", "DisplayName", "Class", "Level"]
    if n_cols >= 5:
        names.append("PipelineId")
    result.columns = names
    if "PipelineId" not in result.columns:
        result["PipelineId"] = ""
    return result.fillna("")


def find_first_try_candidates(
    first_try_path: str,
    iso_line: str,
    *,
    dataset_revision: str = "",
    max_results: int = 30,
) -> list[dict[str, Any]]:
    """Find evidence-backed candidates for one ISO directly in First_try.

    The initial pass is a vectorized literal search over identity-bearing
    fields, so even a very large export stays practical.  Only matching rows
    are scored by the normal recall engine.  Results are deduplicated by both
    physical ITEM and candidate identity; alternate identities from the same
    row remain visible instead of being silently collapsed.
    """

    path = os.path.abspath(str(first_try_path or ""))
    if not path or not os.path.isfile(path):
        return []
    iso_norm, _events = normalize_line_v2(str(iso_line or ""))
    iso_norm = iso_norm.strip()
    if not iso_norm:
        return []

    compact = iso_norm.lstrip("/")
    tokens = [part for part in compact.replace("/", "-").split("-") if part]
    anchors = sorted(
        {token for token in tokens if len(token) >= 3},
        key=len,
        reverse=True,
    )[:3]
    if not anchors:
        anchors = [compact]

    engine = IsoRecallEngine({iso_norm})
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    limit = max(1, min(int(max_results), 100))

    reader = pd.read_csv(
        path,
        dtype=str,
        encoding="utf-8-sig",
        low_memory=False,
        on_bad_lines="skip",
        chunksize=20_000,
    )
    for raw_chunk in reader:
        chunk = _normalize_chunk(raw_chunk)
        searchable = (
            chunk["PipelineId"].astype(str)
            + " "
            + chunk["DisplayName"].astype(str)
            + " "
            + chunk["Path"].astype(str)
        ).str.upper()
        mask = pd.Series(True, index=chunk.index)
        # Requiring all of the strongest ISO tokens gives broad punctuation
        # tolerance without flooding the review list with unrelated rows.
        for anchor in anchors:
            mask &= searchable.str.contains(
                anchor.upper(), case=False, regex=False, na=False
            )
        for _, row in chunk[mask].iterrows():
            recalled = engine.recall_row(row, max_candidates=5, min_score=0.0)
            for candidate in recalled:
                scope = parse_scope_context(
                    candidate.path or str(row.get("Path", "")),
                    "___",
                    iso_match_key=candidate.normalized_3d,
                    raw_3d_pipe_code=candidate.raw_3d,
                    level=candidate.level or str(row.get("Level", "")),
                )
                # Text-only identities cannot be audited or ownership-locked.
                if not str(scope.get("PipeNodePath", "")).strip():
                    continue
                evidence = dict(candidate.evidence or {})
                comparison = build_match_evidence(iso_norm, candidate.normalized_3d)
                evidence.update(comparison.to_dict())
                payload: dict[str, Any] = {
                    "line_3d": candidate.normalized_3d,
                    "raw_3d": candidate.raw_3d,
                    "score": candidate.score,
                    "reason": (candidate.reason + "; First_try 人工補找").strip("; "),
                    "trace": candidate.trace,
                    "path": scope["PipeNodePath"],
                    "scope": scope["ScopeRoot"],
                    "parent_area": scope["ParentArea"],
                    "level": scope["PipeNodeLevel"],
                    "evidence": evidence,
                    "pair_auto_safe": False,
                    "auto_safe": False,
                    "reason_codes": list(
                        dict.fromkeys([
                            *comparison.reason_codes,
                            "manual_first_try_rescue",
                        ])
                    ),
                    "ownership_status": "available",
                    "source": "First_try 補找",
                }
                payload["item_id"] = candidate_item_id(payload, dataset_revision)
                key = (
                    str(payload["item_id"]),
                    str(payload["line_3d"]).upper(),
                    str(payload["raw_3d"]).upper(),
                )
                if key in seen:
                    continue
                seen.add(key)
                found.append(payload)
                if len(found) >= limit:
                    return annotate_candidate_families(found)
    found.sort(key=lambda item: -float(item.get("score", 0.0)))
    return annotate_candidate_families(found)


__all__ = ["find_first_try_candidates"]
