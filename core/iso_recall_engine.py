# -*- coding: utf-8 -*-
"""ISO 反向召回：把 ISO 管線拆成搜尋線索後回查 First_try 列。

這層只產生「待確認候選」，不直接視為 3D 身分證。目的在於讓少尾碼、
尺寸格式不同、或只剩系統/管線主體可比對的案例有線索可看。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from core.size_normalizer import is_size_like
from core.match_evidence import alnum_tokens, build_match_evidence
from core.scope_indexer import parse_scope_context
from utils.trace_builder import TraceBuilder
from utils.utils_common import STRUCTURAL_KEYWORDS, normalize_line_v2


_SLASH_RAW_RE = re.compile(r"(/[A-Z0-9][A-Z0-9_\-/.\"']*)", re.IGNORECASE)
_TRAILING_ALPHA_RE = re.compile(r"^(.+?\d)[A-Z]+$")
_DERIVED_STEM_FACTOR = 0.30
_DERIVED_TO_DERIVED_FACTOR = 0.15
_EXTRA_TOKEN_PENALTY = 0.08
_MUTATION_PENALTY = 0.10
_MISSING_TOKEN_PENALTY = 0.04
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
    evidence: dict[str, Any] = field(default_factory=dict)
    auto_safe: bool = False
    reason_codes: tuple[str, ...] = ()
    path: str = ""
    level: str = ""
    pipe_node_path: str = ""
    scope_root: str = ""
    parent_area: str = ""


@dataclass(frozen=True)
class _IsoRecord:
    key: str
    variants: tuple[str, ...]
    tokens: tuple[str, ...]
    token_weights: dict[str, float]
    original_tokens: tuple[str, ...]
    derived_sources: dict[str, str]


@dataclass(frozen=True)
class _TokenView:
    original: tuple[str, ...]
    derived_sources: dict[str, str]

    @property
    def all_tokens(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.original, *self.derived_sources.keys())))


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


def _token_view(value: str) -> _TokenView:
    original: list[str] = []
    derived_sources: dict[str, str] = {}
    for token in alnum_tokens(value):
        if not token or token in _GENERIC_TOKENS:
            continue
        if len(token) <= 1:
            continue
        original.append(token)
        stripped = _strip_trailing_alpha(token)
        if stripped != token and len(stripped) >= 3:
            derived_sources.setdefault(stripped, token)
    original_unique = tuple(dict.fromkeys(original))
    derived_sources = {
        token: source
        for token, source in derived_sources.items()
        if token not in original_unique
    }
    return _TokenView(original=original_unique, derived_sources=derived_sources)


def _tokenize(value: str) -> list[str]:
    """Broad recall tokens; original identity tokens always remain intact."""
    return list(_token_view(value).all_tokens)


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


def _best_raw_for_record(
    row: pd.Series,
    record: _IsoRecord,
    path_separator: str = "___",
) -> tuple[str, str]:
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
    for segment in [s for s in path.split(path_separator) if str(s).strip()]:
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

    def __init__(
        self,
        known_iso_keys: set[str] | list[str] | tuple[str, ...],
        approved_punctuation_aliases: Mapping[str, str] | None = None,
        path_separator: str = "___",
    ):
        self.records: list[_IsoRecord] = []
        self._token_index: dict[str, list[int]] = {}
        self.approved_punctuation_aliases = dict(
            approved_punctuation_aliases or {}
        )
        self.path_separator = str(path_separator)
        seen: set[str] = set()
        for raw_key in known_iso_keys or []:
            key, _events = normalize_line_v2(str(raw_key))
            key = key.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            variants = tuple(_line_variants(key))
            token_view = _token_view(key)
            token_weights = {
                token: _token_weight(token)
                for token in token_view.original
            }
            token_weights = {k: v for k, v in token_weights.items() if v > 0}
            record = _IsoRecord(
                key=key,
                variants=variants,
                tokens=token_view.all_tokens,
                token_weights=token_weights,
                original_tokens=token_view.original,
                derived_sources=token_view.derived_sources,
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
        row_view = _token_view(combined)
        row_tokens = set(row_view.all_tokens)
        candidate_indices: set[int] = set()
        for token in row_tokens:
            candidate_indices.update(self._token_index.get(token, []))

        if not candidate_indices:
            return []

        scored: list[IsoRecallCandidate] = []
        for idx in candidate_indices:
            record = self.records[idx]
            candidate = self._score_record(row, fields, row_view, record)
            retrieval_score = (
                float(candidate.evidence.get("retrieval_score", candidate.score))
                if candidate
                else 0.0
            )
            if candidate and retrieval_score >= min_score:
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
        row_view: _TokenView,
        record: _IsoRecord,
    ) -> IsoRecallCandidate | None:
        raw_3d, source = _best_raw_for_record(
            row,
            record,
            path_separator=self.path_separator,
        )
        if not raw_3d:
            return None

        normalized_3d, norm_events = normalize_line_v2(raw_3d)
        normalized_upper = normalized_3d.upper()
        path = _as_text(row.get("Path", ""))
        level = _as_text(row.get("Level", ""))
        scope_context = parse_scope_context(
            path,
            self.path_separator,
            iso_match_key=record.key,
            raw_3d_pipe_code=raw_3d,
            level=level,
        )
        row_original = set(row_view.original)
        row_derived = set(row_view.derived_sources)
        matched_terms: list[str] = []
        matched_weight = 0.0
        broad_matched_weight = 0.0
        matched_sources: set[str] = set()
        match_provenance: list[dict[str, Any]] = []

        for original in record.original_tokens:
            source_weight = record.token_weights.get(original, 0.0)
            term = ""
            factor = 0.0
            kind = ""
            if original in row_original:
                term = original
                factor = 1.0
                kind = "original_exact"
            elif original in row_derived:
                term = original
                factor = _DERIVED_STEM_FACTOR
                kind = "candidate_derived_stem"
            else:
                for derived, source_token in record.derived_sources.items():
                    if source_token != original:
                        continue
                    if derived in row_original:
                        term = derived
                        factor = _DERIVED_STEM_FACTOR
                        kind = "iso_derived_stem"
                        break
                    if derived in row_derived:
                        term = derived
                        factor = _DERIVED_TO_DERIVED_FACTOR
                        kind = "both_derived_stem"
                        break
            if not term:
                continue
            matched_sources.add(original)
            matched_terms.append(term)
            matched_weight += source_weight * factor
            broad_matched_weight += source_weight
            match_provenance.append({
                "term": term,
                "source_token": original,
                "kind": kind,
                "weight_factor": factor,
            })

        if len(matched_terms) < 2 and not any(
            variant.upper() in normalized_upper for variant in record.variants
        ):
            return None

        missing_terms = [
            token for token in record.original_tokens if token not in matched_sources
        ]
        score = 0.0
        retrieval_score = 0.0
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

        total_weight = sum(
            record.token_weights.get(token, 0.0)
            for token in record.original_tokens
        ) or 1.0
        token_score = 0.24 + min(matched_weight / total_weight, 1.0) * 0.44
        broad_token_score = (
            0.24
            + min(broad_matched_weight / total_weight, 1.0) * 0.44
        )
        if len(matched_terms) >= 2:
            token_score += 0.06
            broad_token_score += 0.06
            reason_parts.append("多 token 命中：" + ", ".join(matched_terms[:5]))
        if score < token_score:
            score = token_score
        retrieval_score = max(score, broad_token_score)

        ordered_variant = "-".join([t for t in record.tokens if t in matched_terms])
        if ordered_variant and ordered_variant in combined_normalized(fields):
            score += 0.04
            retrieval_score += 0.04
            reason_parts.append("命中詞順序一致")

        display_or_pipeline = " ".join(
            [fields.get("PipelineId", ""), fields.get("DisplayName", "")]
        ).upper()
        is_structural_node = any(
            keyword in display_or_pipeline for keyword in STRUCTURAL_KEYWORDS
        )
        if is_structural_node:
            score -= 0.12
            retrieval_score -= 0.12
            reason_parts.append("子構件/branch 節點降權")

        if not best_variant and len(matched_terms) < 3:
            score = min(score, 0.58)
            retrieval_score = min(retrieval_score, 0.58)

        comparison = build_match_evidence(
            record.key,
            normalized_3d,
            approved_punctuation_aliases=self.approved_punctuation_aliases,
        )
        evidence = comparison.to_dict()
        reason_codes = list(comparison.reason_codes)
        if is_structural_node:
            reason_codes.append("structural_node")
        if any(item["kind"] != "original_exact" for item in match_provenance):
            reason_codes.append("derived_stem_match")
            reason_parts.append("派生 stem 僅作低權重召回")

        if comparison.classification == "punctuation_only":
            score = max(score, 0.86)
            reason_parts.append("僅標點差異，英數 token 完整一致")

        penalty = 0.0
        if comparison.candidate_extra_tokens:
            extra_penalty = min(
                len(comparison.candidate_extra_tokens) * _EXTRA_TOKEN_PENALTY,
                0.24,
            )
            penalty += extra_penalty
            reason_codes.append("score_penalty_extra_token")
            reason_parts.append(
                "3D 額外 token："
                + ", ".join(comparison.candidate_extra_tokens)
                + f"（扣 {extra_penalty:.2f}）"
            )
        if comparison.identity_mutations:
            mutation_penalty = min(
                len(comparison.identity_mutations) * _MUTATION_PENALTY,
                0.30,
            )
            penalty += mutation_penalty
            reason_codes.append("score_penalty_identity_mutation")
            mutations_text = ", ".join(
                f"{item.iso_token}→{item.candidate_token}"
                for item in comparison.identity_mutations
            )
            reason_parts.append(
                f"身分 token 變異：{mutations_text}（扣 {mutation_penalty:.2f}）"
            )
        if comparison.iso_missing_tokens:
            missing_penalty = min(
                len(comparison.iso_missing_tokens) * _MISSING_TOKEN_PENALTY,
                0.16,
            )
            penalty += missing_penalty
            reason_codes.append("score_penalty_missing_token")

        score_before_penalty = score
        score -= penalty
        score = max(0.0, min(score, 0.88))
        retrieval_score = max(0.0, min(retrieval_score, 0.88))
        reason_codes = list(dict.fromkeys(reason_codes))
        auto_safe = (
            comparison.auto_safe
            and not any(
                item["kind"] != "original_exact" for item in match_provenance
            )
            and not is_structural_node
        )
        evidence.update({
            "match_provenance": match_provenance,
            "score_before_penalty": round(score_before_penalty, 4),
            "score_penalty": round(penalty, 4),
            "retrieval_score": round(retrieval_score, 4),
            "auto_safe": auto_safe,
            "reason_codes": reason_codes,
        })
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
            .add("evidence_class", comparison.classification)
            .add("auto_safe", "1" if auto_safe else "0")
            .add("reason_codes", ",".join(reason_codes))
            .add("extra_3d_tokens", ",".join(comparison.candidate_extra_tokens))
            .add("path", path)
            .add("level", level)
            .add("scope_root", scope_context.get("ScopeRoot", ""))
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
            evidence=evidence,
            auto_safe=auto_safe,
            reason_codes=tuple(reason_codes),
            path=path,
            level=level,
            pipe_node_path=scope_context.get("PipeNodePath", ""),
            scope_root=scope_context.get("ScopeRoot", ""),
            parent_area=scope_context.get("ParentArea", ""),
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
