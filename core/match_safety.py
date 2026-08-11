# -*- coding: utf-8 -*-
"""Shared safety evaluation for ISO/3D review candidates.

Scores only rank candidates.  This module owns the outer automation gate so
the matcher and the human review workbench use the same family/ownership
semantics.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Sequence

from core.match_evidence import compare_match_evidence
from utils.utils_common import normalize_line_v2


PatternSignature = tuple[tuple[int, str, str], ...]

_IDENTITY_BLOCK_CODES = {
    "identity_mutation",
    "candidate_extra_token",
    "candidate_missing_token",
    "derived_stem_match",
    "derived_stem_relation",
}
_OUTER_GATE_CODES = {
    "auto_block_multiple_families",
    "auto_block_competing_iso",
}


def iso_family_key(value: object) -> str:
    """Return the ownership family key, not an individual ISO/spool row."""

    normalized, _events = normalize_line_v2(str(value or ""))
    return (normalized or str(value or "")).strip().upper()


def pattern_signature(
    iso_value: object,
    candidate: Mapping[str, object],
) -> PatternSignature:
    """Return an exact, position-aware punctuation-difference signature."""

    candidate_value = (
        candidate.get("line_3d")
        or candidate.get("raw_3d")
        or candidate.get("three_d_raw")
        or ""
    )
    comparison = compare_match_evidence(iso_value, candidate_value)
    if comparison.classification != "punctuation_only":
        return ()
    return tuple(
        (change.gap_index, change.iso_symbol, change.candidate_symbol)
        for change in comparison.punctuation_changes
    )


def pattern_signature_label(signature: PatternSignature) -> str:
    if not signature:
        return "非純符號差異"

    def visible(value: str) -> str:
        return value.replace(" ", "␠") if value else "∅"

    return "；".join(
        f"{visible(left)} → {visible(right)}（位置 {gap}）"
        for gap, left, right in signature
    )


def annotate_family_aware_safety(
    cases: Iterable[MutableMapping[str, object]],
) -> None:
    """Apply the final safety gate at ISO-family granularity.

    Multiple spools/rows belonging to the same ISO family are not competitors.
    A 3D ITEM is blocked only when evidence-safe claims come from different ISO
    families.
    """

    case_list = list(cases)
    safe_item_claims: dict[str, set[str]] = defaultdict(set)
    for item in case_list:
        family = iso_family_key(item.get("iso_line", ""))
        candidates = item.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, MutableMapping):
                continue
            if candidate.get("pair_auto_safe") is True:
                safe_item_claims[str(candidate.get("item_id", ""))].add(family)

    for item in case_list:
        family = iso_family_key(item.get("iso_line", ""))
        candidates = item.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        safe_family_ids = {
            str(candidate.get("family_id", ""))
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and candidate.get("pair_auto_safe") is True
            and str(candidate.get("family_id", "")).strip()
        }
        unique_independent_family = len(safe_family_ids) == 1
        for candidate in candidates:
            if not isinstance(candidate, MutableMapping):
                continue
            item_id = str(candidate.get("item_id", ""))
            reciprocal_best = (
                candidate.get("pair_auto_safe") is True
                and safe_item_claims.get(item_id, set()) == {family}
            )
            evidence = candidate.get("evidence")
            evidence_map: MutableMapping[str, object]
            if isinstance(evidence, MutableMapping):
                evidence_map = evidence
            else:
                evidence_map = {}
            classification = str(evidence_map.get("classification", ""))
            evidence_authorized = bool(
                classification == "exact"
                or evidence_map.get("approved_punctuation_alias") is True
            )
            reason_codes = [
                str(code)
                for code in (candidate.get("reason_codes", []) or [])
                if str(code) not in _OUTER_GATE_CODES
            ]
            no_identity_mutation = not any(
                code in _IDENTITY_BLOCK_CODES for code in reason_codes
            )
            ownership_passes = str(candidate.get("ownership_status", "")) in {
                "available",
                "same_family",
            }
            safety_checks = {
                "evidence_authorized": evidence_authorized,
                "no_identity_mutation": no_identity_mutation,
                "unique_independent_family": unique_independent_family,
                "reciprocal_best": reciprocal_best,
                "ownership_passes": ownership_passes,
            }
            final_safe = (
                candidate.get("pair_auto_safe") is True
                and all(safety_checks.values())
            )
            if not unique_independent_family:
                reason_codes.append("auto_block_multiple_families")
            if candidate.get("pair_auto_safe") is True and not reciprocal_best:
                reason_codes.append("auto_block_competing_iso")
            reason_codes = list(dict.fromkeys(reason_codes))
            candidate["auto_safe"] = final_safe
            candidate["safety_checks"] = safety_checks
            candidate["reason_codes"] = reason_codes
            evidence_map["auto_safe"] = final_safe
            evidence_map["safety_checks"] = safety_checks
            evidence_map["reason_codes"] = reason_codes
            evidence_map["family_id"] = candidate.get("family_id", "")
            evidence_map["family_role"] = candidate.get("family_role", "")
            evidence_map["ownership_status"] = candidate.get(
                "ownership_status", ""
            )
            candidate["evidence"] = dict(evidence_map)


@dataclass(frozen=True)
class SymbolBatchPreview:
    signature: PatternSignature
    member_cases: tuple[int, ...]
    eligible: tuple[tuple[int, int], ...]
    excluded: tuple[tuple[int, str], ...]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)


def preview_symbol_batch(
    cases: Sequence[Mapping[str, object]],
    signature: PatternSignature,
    *,
    skip_cases: Iterable[int] = (),
) -> SymbolBatchPreview:
    """Preview a human-authorized symbol group without bypassing hard gates."""

    skipped = set(skip_cases)
    members: list[int] = []
    per_case: dict[int, list[tuple[int, Mapping[str, object]]]] = {}
    claims: dict[str, set[str]] = defaultdict(set)

    for case_idx, case in enumerate(cases):
        if case_idx in skipped:
            continue
        iso_line = case.get("iso_line", "")
        family = iso_family_key(iso_line)
        matches: list[tuple[int, Mapping[str, object]]] = []
        candidates = case.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate_idx, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                continue
            if pattern_signature(iso_line, candidate) != signature:
                continue
            evidence = candidate.get("evidence")
            evidence_map = evidence if isinstance(evidence, Mapping) else {}
            if str(evidence_map.get("classification", "")) != "punctuation_only":
                continue
            matches.append((candidate_idx, candidate))
            claims[str(candidate.get("item_id", ""))].add(family)
        if matches:
            members.append(case_idx)
            per_case[case_idx] = matches

    eligible: list[tuple[int, int]] = []
    excluded: list[tuple[int, str]] = []
    for case_idx in members:
        case = cases[case_idx]
        family = iso_family_key(case.get("iso_line", ""))
        accepted: list[int] = []
        reject_reasons: set[str] = set()
        for candidate_idx, candidate in per_case[case_idx]:
            ownership = str(candidate.get("ownership_status", ""))
            item_id = str(candidate.get("item_id", ""))
            family_id = str(candidate.get("family_id", "")).strip()
            if not item_id or item_id.startswith("ephemeral:"):
                reject_reasons.add("ITEM 身分無法穩定確認")
                continue
            if ownership not in {"available", "same_family"}:
                reject_reasons.add("ITEM 已被其他 ISO 使用")
                continue
            if not family_id:
                reject_reasons.add("缺少 3D 家族證據")
                continue
            if claims.get(item_id, set()) != {family}:
                reject_reasons.add("不同 ISO 家族競爭同一 ITEM")
                continue
            accepted.append(candidate_idx)
        accepted_families = {
            str(per_case[case_idx][
                next(i for i, pair in enumerate(per_case[case_idx]) if pair[0] == idx)
            ][1].get("family_id", ""))
            for idx in accepted
        }
        if len(accepted) == 1 and len(accepted_families) == 1:
            eligible.append((case_idx, accepted[0]))
        elif len(accepted) > 1:
            excluded.append((case_idx, "同一模式仍有多個候選"))
        else:
            excluded.append((
                case_idx,
                "、".join(sorted(reject_reasons)) or "沒有通過安全條件的候選",
            ))

    return SymbolBatchPreview(
        signature=signature,
        member_cases=tuple(members),
        eligible=tuple(eligible),
        excluded=tuple(excluded),
    )


__all__ = [
    "PatternSignature",
    "SymbolBatchPreview",
    "annotate_family_aware_safety",
    "iso_family_key",
    "pattern_signature",
    "pattern_signature_label",
    "preview_symbol_batch",
]
