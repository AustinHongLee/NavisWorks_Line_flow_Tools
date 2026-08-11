# -*- coding: utf-8 -*-
"""Token-preserving comparison evidence for pipe identity candidates.

This module deliberately separates *evidence* from canonical normalization.
Punctuation may explain a formatting-only difference, but alphanumeric tokens
are never rewritten (for example, ``32145A`` never becomes ``32145`` here).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping


_ALNUM_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_TRAILING_ALPHA_RE = re.compile(r"^(.+?\d)([A-Z]+)$")
_BRANCH_TOKEN_RE = re.compile(r"^B\d+$")


def alnum_tokens(value: object) -> tuple[str, ...]:
    """Return the original ordered ASCII alphanumeric tokens, upper-cased."""
    return tuple(_ALNUM_TOKEN_RE.findall(str(value or "").upper()))


@dataclass(frozen=True)
class IdentityMutation:
    iso_token: str
    candidate_token: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "iso_token": self.iso_token,
            "candidate_token": self.candidate_token,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class PunctuationChange:
    gap_index: int
    after_token: str
    before_token: str
    iso_symbol: str
    candidate_symbol: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_index": self.gap_index,
            "after_token": self.after_token,
            "before_token": self.before_token,
            "iso_symbol": self.iso_symbol,
            "candidate_symbol": self.candidate_symbol,
        }


@dataclass(frozen=True)
class MatchEvidence:
    classification: str
    iso_tokens: tuple[str, ...]
    candidate_tokens: tuple[str, ...]
    matched_tokens: tuple[str, ...]
    iso_missing_tokens: tuple[str, ...]
    candidate_extra_tokens: tuple[str, ...]
    identity_mutations: tuple[IdentityMutation, ...]
    iso_punctuation_shape: tuple[str, ...]
    candidate_punctuation_shape: tuple[str, ...]
    punctuation_changes: tuple[PunctuationChange, ...]
    reason_codes: tuple[str, ...]
    approved_punctuation_alias: bool
    auto_safe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "iso_tokens": list(self.iso_tokens),
            "candidate_tokens": list(self.candidate_tokens),
            "matched_tokens": list(self.matched_tokens),
            "iso_missing_tokens": list(self.iso_missing_tokens),
            "candidate_extra_tokens": list(self.candidate_extra_tokens),
            "identity_mutations": [item.to_dict() for item in self.identity_mutations],
            "punctuation_shape": {
                "iso": list(self.iso_punctuation_shape),
                "candidate": list(self.candidate_punctuation_shape),
            },
            "punctuation_changes": [
                item.to_dict() for item in self.punctuation_changes
            ],
            "reason_codes": list(self.reason_codes),
            "approved_punctuation_alias": self.approved_punctuation_alias,
            "auto_safe": self.auto_safe,
        }


def _mutation_kind(iso_token: str, candidate_token: str) -> str:
    iso_match = _TRAILING_ALPHA_RE.match(iso_token)
    candidate_match = _TRAILING_ALPHA_RE.match(candidate_token)
    if iso_match and iso_match.group(1) == candidate_token:
        return "trailing_alpha_removed"
    if candidate_match and candidate_match.group(1) == iso_token:
        return "trailing_alpha_added"
    return "alphanumeric_changed"


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _punctuation_spans(value: str) -> tuple[str, ...]:
    spans: list[str] = []
    cursor = 0
    for match in _ALNUM_TOKEN_RE.finditer(value):
        spans.append(value[cursor:match.start()])
        cursor = match.end()
    spans.append(value[cursor:])
    return tuple(spans)


def _approved_punctuation_match(
    iso_text: str,
    candidate_text: str,
    aliases: Mapping[str, str] | None,
) -> bool:
    if not aliases or iso_text == candidate_text:
        return False
    iso_spans = _punctuation_spans(iso_text)
    candidate_spans = _punctuation_spans(candidate_text)
    if len(iso_spans) != len(candidate_spans):
        return False

    def _normalized(span: str) -> tuple[str, ...]:
        return tuple(str(aliases.get(ch, ch)) for ch in span)

    return all(
        _normalized(left) == _normalized(right)
        for left, right in zip(iso_spans, candidate_spans)
    )


def _punctuation_changes(
    iso_tokens: tuple[str, ...],
    iso_spans: tuple[str, ...],
    candidate_spans: tuple[str, ...],
) -> tuple[PunctuationChange, ...]:
    if len(iso_spans) != len(candidate_spans):
        return ()
    changes: list[PunctuationChange] = []
    for gap_index, (iso_gap, candidate_gap) in enumerate(
        zip(iso_spans, candidate_spans)
    ):
        matcher = SequenceMatcher(None, iso_gap, candidate_gap, autojunk=False)
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            if opcode == "equal":
                continue
            changes.append(PunctuationChange(
                gap_index=gap_index,
                after_token=iso_tokens[gap_index - 1] if gap_index > 0 else "",
                before_token=(
                    iso_tokens[gap_index] if gap_index < len(iso_tokens) else ""
                ),
                iso_symbol=iso_gap[i1:i2],
                candidate_symbol=candidate_gap[j1:j2],
            ))
    return tuple(changes)


def build_match_evidence(
    iso_value: object,
    candidate_value: object,
    approved_punctuation_aliases: Mapping[str, str] | None = None,
) -> MatchEvidence:
    """Classify the exact token-level relationship between two identities.

    ``auto_safe`` is intentionally conservative: exact identity is safe;
    punctuation-only evidence remains review-only unless the caller supplies
    project-scoped aliases that explain every changed punctuation character.
    Automatic resolution must still require a unique candidate in scope.
    """
    iso_text = str(iso_value or "").strip().upper()
    candidate_text = str(candidate_value or "").strip().upper()
    iso = alnum_tokens(iso_text)
    candidate = alnum_tokens(candidate_text)
    iso_punctuation_shape = _punctuation_spans(iso_text)
    candidate_punctuation_shape = _punctuation_spans(candidate_text)

    matched: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    mutations: list[IdentityMutation] = []

    matcher = SequenceMatcher(None, iso, candidate, autojunk=False)
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            matched.extend(iso[i1:i2])
            continue
        if opcode == "delete":
            missing.extend(iso[i1:i2])
            continue
        if opcode == "insert":
            extra.extend(candidate[j1:j2])
            continue

        iso_changed = list(iso[i1:i2])
        candidate_changed = list(candidate[j1:j2])
        paired = min(len(iso_changed), len(candidate_changed))
        for offset in range(paired):
            if (
                _BRANCH_TOKEN_RE.match(iso_changed[offset])
                and _BRANCH_TOKEN_RE.match(candidate_changed[offset])
            ):
                missing.append(iso_changed[offset])
                extra.append(candidate_changed[offset])
                continue
            mutations.append(
                IdentityMutation(
                    iso_token=iso_changed[offset],
                    candidate_token=candidate_changed[offset],
                    kind=_mutation_kind(
                        iso_changed[offset], candidate_changed[offset]
                    ),
                )
            )
        missing.extend(iso_changed[paired:])
        extra.extend(candidate_changed[paired:])

    reason_codes: list[str] = []
    same_tokens = bool(iso) and iso == candidate
    punctuation_changes = (
        _punctuation_changes(
            iso,
            iso_punctuation_shape,
            candidate_punctuation_shape,
        )
        if same_tokens
        else ()
    )
    if iso_text == candidate_text and same_tokens:
        classification = "exact"
        reason_codes.append("exact_identity")
    elif same_tokens:
        classification = "punctuation_only"
        reason_codes.append("punctuation_only")
    elif mutations:
        classification = "identity_mutation"
        reason_codes.append("identity_mutation")
    elif extra or missing:
        classification = "extra_token"
    else:
        classification = "token_mismatch"
        reason_codes.append("token_mismatch")

    if extra:
        reason_codes.append("candidate_extra_token")
        if any(_BRANCH_TOKEN_RE.match(token) for token in extra):
            reason_codes.append("branch_extra_token")
    if missing:
        reason_codes.append("candidate_missing_token")
    if any(item.kind.startswith("trailing_alpha_") for item in mutations):
        reason_codes.append("derived_stem_relation")

    approved_punctuation_alias = (
        classification == "punctuation_only"
        and _approved_punctuation_match(
            iso_text,
            candidate_text,
            approved_punctuation_aliases,
        )
    )
    if classification == "punctuation_only":
        reason_codes.append(
            "punctuation_alias_approved"
            if approved_punctuation_alias
            else "punctuation_review_required"
        )
    auto_safe = classification == "exact" or approved_punctuation_alias
    return MatchEvidence(
        classification=classification,
        iso_tokens=iso,
        candidate_tokens=candidate,
        matched_tokens=_unique(matched),
        iso_missing_tokens=_unique(missing),
        candidate_extra_tokens=_unique(extra),
        identity_mutations=tuple(mutations),
        iso_punctuation_shape=iso_punctuation_shape,
        candidate_punctuation_shape=candidate_punctuation_shape,
        punctuation_changes=punctuation_changes,
        reason_codes=_unique(reason_codes),
        approved_punctuation_alias=approved_punctuation_alias,
        auto_safe=auto_safe,
    )


def compare_match_evidence(
    iso_value: object,
    candidate_value: object,
    approved_punctuation_aliases: Mapping[str, str] | None = None,
) -> MatchEvidence:
    """Alias with an explicit comparison-oriented name for UI/service callers."""
    return build_match_evidence(
        iso_value,
        candidate_value,
        approved_punctuation_aliases=approved_punctuation_aliases,
    )
