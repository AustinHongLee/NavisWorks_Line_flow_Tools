# -*- coding: utf-8 -*-
"""3D pipe identity candidate collection and scoring."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from utils.utils_common import CommonUtils, PIPE_SEG_PATTERN, STRUCTURAL_KEYWORDS


_FILE_EXT_RE = re.compile(r"\.[a-zA-Z]{2,4}$")
_PIPE_PHRASE_RE = re.compile(r"\bPIPE\s+(/[^\s,]+)", re.IGNORECASE)


@dataclass(frozen=True)
class IdentityCandidate:
    raw: str
    normalized: str
    source: str
    score: float
    reason: str


class IdentityResolver:
    """Collect pipe-id candidates without losing source/reason metadata."""

    def __init__(
        self,
        sep: str = "___",
        raw_prefix: str = "/",
        known_iso_keys: set[str] | None = None,
    ):
        self.sep = sep
        self.raw_prefix = raw_prefix
        self.known_iso_keys = {str(k).strip() for k in (known_iso_keys or set()) if str(k).strip()}

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    @staticmethod
    def _is_file_like(value: str) -> bool:
        return bool(_FILE_EXT_RE.search(value.strip()))

    @staticmethod
    def _is_structural(value: str) -> bool:
        upper = value.strip().upper()
        return any(k in upper for k in STRUCTURAL_KEYWORDS)

    @staticmethod
    def _is_valid_norm(value: str) -> bool:
        return bool(value and PIPE_SEG_PATTERN.match(value.strip()))

    @staticmethod
    def _drop_last_segment(value: str) -> str:
        parts = str(value).strip().split("-")
        if len(parts) >= 4:
            return "-".join(parts[:-1])
        return str(value).strip()

    def _is_known_compatible(self, normalized: str) -> bool:
        if not self.known_iso_keys:
            return True
        norm = str(normalized).strip()
        if norm in self.known_iso_keys:
            return True
        if self._drop_last_segment(norm) in self.known_iso_keys:
            return True
        return False

    def _clean_raw(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("/") or not self.raw_prefix:
            return raw
        return self.raw_prefix + re.sub(r"^[^A-Za-z0-9]+", "", raw)

    def _make_candidate(
        self,
        raw_value: str,
        source: str,
        score: float,
        reason: str,
        add_prefix: bool = False,
    ) -> IdentityCandidate | None:
        raw_value = self._as_text(raw_value)
        if not raw_value:
            return None
        if self._is_file_like(raw_value) or self._is_structural(raw_value):
            return None

        raw = self._clean_raw(raw_value) if add_prefix else raw_value.strip()
        normalized = CommonUtils.normalize_line(raw)
        if self._is_file_like(normalized) or not self._is_valid_norm(normalized):
            return None
        if not self._is_known_compatible(normalized):
            return None

        if self.known_iso_keys:
            if normalized in self.known_iso_keys:
                score += 0.08
                reason += "；命中 ISO 管線清單"
            elif self._drop_last_segment(normalized) in self.known_iso_keys:
                score += 0.04
                reason += "；去末段後命中 ISO 管線清單"

        return IdentityCandidate(
            raw=raw,
            normalized=normalized,
            source=source,
            score=round(min(float(score), 1.0), 4),
            reason=reason,
        )

    def _pipe_phrase_candidates(
        self,
        text: str,
        source: str,
        score: float,
    ) -> list[IdentityCandidate]:
        candidates: list[IdentityCandidate] = []
        for m in _PIPE_PHRASE_RE.finditer(text):
            cand = self._make_candidate(
                m.group(1),
                source=f"{source}:pipe_phrase",
                score=score,
                reason="從 'PIPE /...' 片段取得管線身分證",
            )
            if cand:
                candidates.append(cand)
        return candidates

    def collect_candidates(self, row: pd.Series) -> list[IdentityCandidate]:
        candidates: list[IdentityCandidate] = []

        pipeline_id = self._as_text(row.get("PipelineId", ""))
        display_name = self._as_text(row.get("DisplayName", ""))
        path = self._as_text(row.get("Path", ""))

        if pipeline_id:
            candidates.extend(
                self._pipe_phrase_candidates(pipeline_id, "PipelineId", 0.97)
            )
            cand = self._make_candidate(
                pipeline_id,
                source="PipelineId",
                score=0.95,
                reason="PipelineId 本身符合管線格式",
            )
            if cand:
                candidates.append(cand)

        if display_name and display_name != pipeline_id:
            candidates.extend(
                self._pipe_phrase_candidates(display_name, "DisplayName", 0.9)
            )
            cand = self._make_candidate(
                display_name,
                source="DisplayName",
                score=0.86,
                reason="DisplayName 本身符合管線格式",
            )
            if cand:
                candidates.append(cand)

        segments = [s for s in path.split(self.sep) if str(s).strip()]
        total = max(len(segments), 1)
        for idx, segment in enumerate(segments):
            segment = self._as_text(segment)
            if not segment:
                continue
            depth_bonus = min(idx / total, 1.0) * 0.08
            candidates.extend(
                self._pipe_phrase_candidates(
                    segment,
                    f"Path[{idx}]",
                    0.82 + depth_bonus,
                )
            )
            cand = self._make_candidate(
                segment,
                source=f"Path[{idx}]",
                score=0.72 + depth_bonus,
                reason="Path 片段符合管線格式",
                add_prefix=True,
            )
            if cand:
                candidates.append(cand)

        return self._dedupe(candidates)

    @staticmethod
    def _dedupe(candidates: list[IdentityCandidate]) -> list[IdentityCandidate]:
        best_by_key: dict[tuple[str, str], IdentityCandidate] = {}
        for cand in candidates:
            key = (cand.normalized, cand.raw)
            old = best_by_key.get(key)
            if old is None or cand.score > old.score:
                best_by_key[key] = cand
        return sorted(
            best_by_key.values(),
            key=lambda c: (-c.score, c.source, c.raw),
        )

    def resolve(self, row: pd.Series) -> dict[str, object]:
        candidates = self.collect_candidates(row)
        best = candidates[0] if candidates else None
        trace = [
            {
                "raw": c.raw,
                "normalized": c.normalized,
                "source": c.source,
                "score": c.score,
                "reason": c.reason,
            }
            for c in candidates[:5]
        ]
        if best is None:
            return {
                "Raw_3D_PipeCode": "",
                "ISO_Match_Key": "",
                "MatchSource": "",
                "ConfidencePrimary": 0.0,
                "IdentityReason": "未找到符合管線格式的 3D 身分證候選",
                "CandidateCount": 0,
                "CandidateTrace": "[]",
            }

        return {
            "Raw_3D_PipeCode": best.raw,
            "ISO_Match_Key": best.normalized,
            "MatchSource": best.source,
            "ConfidencePrimary": best.score,
            "IdentityReason": best.reason,
            "CandidateCount": len(candidates),
            "CandidateTrace": json.dumps(trace, ensure_ascii=False),
        }
