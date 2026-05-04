# -*- coding: utf-8 -*-
"""ISO 反向召回：把 ISO 管線拆成搜尋線索後回查 First_try 列。

這層只產生「待確認候選」，不直接視為 3D 身分證。目的在於讓少尾碼、
尺寸格式不同、或只剩系統/管線主體可比對的案例有線索可看。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.size_normalizer import is_size_like
from utils.trace_builder import TraceBuilder
from utils.utils_common import STRUCTURAL_KEYWORDS, normalize_line_v2


_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_SLASH_RAW_RE = re.compile(r"(/[A-Z0-9][A-Z0-9_\-/.\"']*)", re.IGNORECASE)
_TRAILING_ALPHA_RE = re.compile(r"^(.+?\d)[A-Z]+$")
_FIELD_ORDER = ["PipelineId", "DisplayName", "Path"]
_GENERIC_TOKENS = {
    "PIPE",
    "LINE",
    "BRANCH",
    "VALVE",
    "FLANGE",
    "TEE",
    "ELBOW",
    "CAP",
    "OF",
    "THE",
}


@dataclass(frozen=True)
class IsoRecallCandidate:
    iso_key: str
    raw_3d: str
    normalized_3d: str
    source: str
    score: float
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    reason: str
    trace: str


@dataclass(frozen=True)
class _IsoRecord:
    key: str
    variants: tuple[str, ...]
    tokens: tuple[str, ...]
    token_weights: dict[str, float]


def _as_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _drop_last(value: str) -> str:
    parts = [p for p in str(value).strip().split("-") if p]
    if len(parts) <= 1:
        return str(value).strip()
    return "-".join(parts[:-1])


def _strip_trailing_alpha(value: str) -> str:
    match = _TRAILING_ALPHA_RE.match(str(value).strip())
    return match.group(1) if match else str(value).strip()


def _tokenize(value: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(str(value or "").upper()):
        if not token or token in _GENERIC_TOKENS:
            continue
        if len(token) <= 1:
            continue
        tokens.append(token)
        stripped = _strip_trailing_alpha(token)
        if stripped != token and len(stripped) >= 3:
            tokens.append(stripped)
    return list(dict.fromkeys(tokens))


def _token_weight(token: str) -> float:
    token = str(token).upper()
    if token in _GENERIC_TOKENS:
        return 0.0
    if token.isdigit():
        return 16.0 if len(token) >= 4 else 3.0
    if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
        return 22.0 if len(token) >= 5 else 12.0
    if len(token) >= 5:
        return 12.0
    if len(token) >= 3:
        return 7.0
    return 2.0


def _variant_priority(value: str) -> tuple[int, int]:
    parts = [p for p in str(value).split("-") if p]
    return (len(parts), len(value))


def _line_variants(normalized: str) -> list[str]:
    value = str(normalized).strip()
    if not value:
        return []

    variants: list[str] = [value]
    parts = [p for p in value.split("-") if p]
    if len(parts) >= 2:
        tail_stripped = _strip_trailing_alpha(parts[-1])
        if tail_stripped != parts[-1]:
            variants.append("-".join(parts[:-1] + [tail_stripped]))

    drop = _drop_last(value)
    if drop and drop != value:
        variants.append(drop)

    no_size_parts = parts[:]
    while no_size_parts and is_size_like(no_size_parts[0]):
        no_size_parts = no_size_parts[1:]
    if no_size_parts and no_size_parts != parts:
        no_size = "-".join(no_size_parts)
        variants.append(no_size)
        no_size_tail = _strip_trailing_alpha(no_size_parts[-1])
        if no_size_tail != no_size_parts[-1]:
            variants.append("-".join(no_size_parts[:-1] + [no_size_tail]))
        no_size_drop = _drop_last(no_size)
        if no_size_drop and no_size_drop != no_size:
            variants.append(no_size_drop)

    unique = list(dict.fromkeys(v for v in variants if v))
    return sorted(unique, key=_variant_priority, reverse=True)


def _field_values(row: pd.Series) -> dict[str, str]:
    return {field: _as_text(row.get(field, "")) for field in _FIELD_ORDER}


def _normalized_field(value: str) -> str:
    normalized, _events = normalize_line_v2(value)
    return normalized.upper()


def _normalize_row_raw(value: str) -> str:
    raw = _as_text(value)
    if not raw:
        return ""
    match = _SLASH_RAW_RE.search(raw)
    if match:
        return match.group(1).strip()
    if raw.startswith("/"):
        return raw
    return "/" + re.sub(r"^[^A-Za-z0-9]+", "", raw)


def _best_raw_for_record(row: pd.Series, record: _IsoRecord) -> tuple[str, str]:
    fields = _field_values(row)
    for field in ["PipelineId", "DisplayName"]:
        value = fields.get(field, "")
        if not value:
            continue
        value_upper = value.upper()
        normalized_upper = _normalized_field(value)
        if any(
            v.upper() in value_upper or v.upper() in normalized_upper
            for v in record.variants
        ):
            return _normalize_row_raw(value), field

    path = fields.get("Path", "")
    for segment in [s for s in path.split("___") if str(s).strip()]:
        segment_upper = segment.upper()
        normalized_upper = _normalized_field(segment)
        if any(
            v.upper() in segment_upper or v.upper() in normalized_upper
            for v in record.variants
        ):
            return _normalize_row_raw(segment), "Path"

    for field in ["PipelineId", "DisplayName"]:
        value = fields.get(field, "")
        if not value:
            continue
        tokens = set(_tokenize(value))
        if len(tokens.intersection(record.tokens)) >= 2:
            return _normalize_row_raw(value), field

    return "", ""


class IsoRecallEngine:
    """以 ISO 清單為搜尋索引，回查 First_try row 的可能 3D 候選。"""

    def __init__(self, known_iso_keys: set[str] | list[str] | tuple[str, ...]):
        self.records: list[_IsoRecord] = []
        self._token_index: dict[str, list[int]] = {}
        seen: set[str] = set()
        for raw_key in known_iso_keys or []:
            key, _events = normalize_line_v2(str(raw_key))
            key = key.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            variants = tuple(_line_variants(key))
            token_weights = {
                token: _token_weight(token)
                for token in _tokenize(" ".join(variants))
            }
            token_weights = {k: v for k, v in token_weights.items() if v > 0}
            record = _IsoRecord(
                key=key,
                variants=variants,
                tokens=tuple(token_weights.keys()),
                token_weights=token_weights,
            )
            idx = len(self.records)
            self.records.append(record)
            for token in record.tokens:
                self._token_index.setdefault(token, []).append(idx)

    def recall_row(
        self,
        row: pd.Series,
        max_candidates: int = 5,
        min_score: float = 0.35,
    ) -> list[IsoRecallCandidate]:
        if not self.records:
            return []

        fields = _field_values(row)
        combined = " ".join(v.upper() for v in fields.values() if v)
        row_tokens = set(_tokenize(combined))
        candidate_indices: set[int] = set()
        for token in row_tokens:
            candidate_indices.update(self._token_index.get(token, []))

        if not candidate_indices:
            return []

        scored: list[IsoRecallCandidate] = []
        for idx in candidate_indices:
            record = self.records[idx]
            candidate = self._score_record(row, fields, row_tokens, record)
            if candidate and candidate.score >= min_score:
                scored.append(candidate)

        scored.sort(
            key=lambda c: (
                -c.score,
                -len(c.matched_terms),
                c.iso_key,
                c.raw_3d,
            )
        )
        return scored[:max_candidates]

    def _score_record(
        self,
        row: pd.Series,
        fields: dict[str, str],
        row_tokens: set[str],
        record: _IsoRecord,
    ) -> IsoRecallCandidate | None:
        raw_3d, source = _best_raw_for_record(row, record)
        if not raw_3d:
            return None

        normalized_3d, norm_events = normalize_line_v2(raw_3d)
        normalized_upper = normalized_3d.upper()
        matched_terms = [
            token
            for token in record.tokens
            if token in row_tokens or token in normalized_upper
        ]
        if len(matched_terms) < 2 and not any(
            variant.upper() in normalized_upper for variant in record.variants
        ):
            return None

        missing_terms = [token for token in record.tokens if token not in matched_terms]
        score = 0.0
        reason_parts: list[str] = []
        best_variant = ""
        best_variant_source = ""
        for variant in record.variants:
            variant_upper = variant.upper()
            for field in _FIELD_ORDER:
                value_upper = fields.get(field, "").upper()
                field_norm = _normalized_field(fields.get(field, ""))
                if variant_upper and (
                    variant_upper in value_upper or variant_upper in field_norm
                ):
                    part_count = len([p for p in variant.split("-") if p])
                    variant_score = 0.54 + min(part_count, 4) * 0.08
                    if field == "PipelineId":
                        variant_score += 0.04
                    elif field == "DisplayName":
                        variant_score += 0.02
                    if variant == record.key:
                        variant_score += 0.04
                    if variant_score > score:
                        score = variant_score
                        best_variant = variant
                        best_variant_source = field

        if best_variant:
            reason_parts.append(
                f"{best_variant_source} 命中 ISO 變體 {best_variant}"
            )

        total_weight = sum(record.token_weights.values()) or 1.0
        matched_weight = sum(record.token_weights.get(t, 0.0) for t in matched_terms)
        token_score = 0.24 + min(matched_weight / total_weight, 1.0) * 0.44
        if len(matched_terms) >= 2:
            token_score += 0.06
            reason_parts.append("多 token 命中：" + ", ".join(matched_terms[:5]))
        if score < token_score:
            score = token_score

        ordered_variant = "-".join([t for t in record.tokens if t in matched_terms])
        if ordered_variant and ordered_variant in combined_normalized(fields):
            score += 0.04
            reason_parts.append("命中詞順序一致")

        display_or_pipeline = " ".join(
            [fields.get("PipelineId", ""), fields.get("DisplayName", "")]
        ).upper()
        if any(k in display_or_pipeline for k in STRUCTURAL_KEYWORDS):
            score -= 0.12
            reason_parts.append("子構件/branch 節點降權")

        if not best_variant and len(matched_terms) < 3:
            score = min(score, 0.58)
        score = max(0.0, min(score, 0.88))
        if not reason_parts:
            reason_parts.append("ISO token 反向召回")

        trace = (
            TraceBuilder()
            .add("candidate_kind", "iso_reverse_recall")
            .add("iso_key", record.key)
            .add("raw", raw_3d)
            .add("normalized", normalized_3d)
            .add("source", source)
            .add("score", f"{score:.2f}")
            .add("matched_terms", ",".join(matched_terms))
            .add("missing_terms", ",".join(missing_terms[:8]))
            .add("reason", "；".join(reason_parts))
            .extend_events(norm_events)
            .build()
        )
        return IsoRecallCandidate(
            iso_key=record.key,
            raw_3d=raw_3d,
            normalized_3d=normalized_3d,
            source=source,
            score=round(score, 4),
            matched_terms=tuple(matched_terms),
            missing_terms=tuple(missing_terms),
            reason="；".join(reason_parts),
            trace=trace,
        )


def combined_normalized(fields: dict[str, str]) -> str:
    values: list[str] = []
    for field in _FIELD_ORDER:
        value = fields.get(field, "")
        if not value:
            continue
        normalized, _events = normalize_line_v2(value)
        values.append(normalized.upper())
    return " ".join(values)
