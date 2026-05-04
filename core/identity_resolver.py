# -*- coding: utf-8 -*-
"""3D pipe identity candidate collection and scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from utils.trace_builder import TraceBuilder
from utils.utils_common import (
    PIPE_SEG_PATTERN,
    STRUCTURAL_KEYWORDS,
    normalize_line_v2,
)


_FILE_EXT_RE = re.compile(r"\.[a-zA-Z]{2,4}$")
_PIPE_PHRASE_RE = re.compile(r"\bPIPE\s+(/[^\s,]+)", re.IGNORECASE)


@dataclass(frozen=True)
class IdentityCandidate:
    raw: str
    normalized: str
    source: str
    score: float
    reason: str
    trace_events: tuple[str, ...] = ()


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
        self.known_iso_keys: set[str] = set()
        for key in known_iso_keys or set():
            text = str(key).strip()
            if not text:
                continue
            self.known_iso_keys.add(text)
            norm_v2, _events = normalize_line_v2(text)
            if norm_v2:
                self.known_iso_keys.add(norm_v2)

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

    @staticmethod
    def _trace_source(source: str) -> str:
        lower = str(source).strip().lower()
        if lower.startswith("pipelineid"):
            return "pipeline_id"
        if lower.startswith("displayname"):
            return "display_name"
        if lower.startswith("path"):
            return "path_smart"
        return lower or "unknown"

    def _build_candidate_trace(
        self,
        candidate: IdentityCandidate,
        row: pd.Series,
    ) -> str:
        tb = TraceBuilder()
        tb.add("raw", candidate.raw)
        tb.add("source", self._trace_source(candidate.source))
        if str(candidate.source).strip().lower().startswith("path"):
            tb.add("path", self._as_text(row.get("Path", "")))
        tb.add("level", self._as_text(row.get("Level", "")))
        tb.add("pattern_check", "pass")
        tb.extend_events(candidate.trace_events)
        tb.add("normalized", candidate.normalized)
        tb.add("score", f"{candidate.score:.2f}")
        tb.add("reason", candidate.reason)
        return tb.build()

    def _build_candidates_trace(self, candidates: list[IdentityCandidate]) -> str:
        tb = TraceBuilder().add("candidate_count", str(len(candidates)))
        for idx, cand in enumerate(candidates[:5], start=1):
            detail = (
                f"{idx}|{self._trace_source(cand.source)}|"
                f"{cand.normalized}|{cand.score:.2f}|{cand.reason}"
            )
            tb.add_event("candidate", detail)
        return tb.build()

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
        normalized, trace_events = normalize_line_v2(raw)
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
            trace_events=tuple(trace_events),
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
        if best is None:
            reason = "未找到符合管線格式的 3D 身分證候選"
            trace = (
                TraceBuilder()
                .add("source", "none")
                .add("level", self._as_text(row.get("Level", "")))
                .add("pattern_check", "fail")
                .add("reason", reason)
                .build()
            )
            return {
                "Raw_3D_PipeCode": "",
                "ISO_Match_Key": "",
                "MatchSource": "",
                "ConfidencePrimary": 0.0,
                "IdentityReason": trace,
                "CandidateCount": 0,
                "CandidateTrace": trace,
            }

        return {
            "Raw_3D_PipeCode": best.raw,
            "ISO_Match_Key": best.normalized,
            "MatchSource": best.source,
            "ConfidencePrimary": best.score,
            "IdentityReason": self._build_candidate_trace(best, row),
            "CandidateCount": len(candidates),
            "CandidateTrace": self._build_candidates_trace(candidates),
        }
