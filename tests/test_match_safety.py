# -*- coding: utf-8 -*-
from core.match_safety import (
    annotate_family_aware_safety,
    pattern_signature,
    preview_symbol_batch,
)


def _candidate(item_id: str, *, pair_safe: bool = True) -> dict:
    return {
        "line_3d": 'CHWR-32118-2"-S1P4-C30',
        "item_id": item_id,
        "family_id": "3d-family-a",
        "ownership_status": "available",
        "pair_auto_safe": pair_safe,
        "reason_codes": ["punctuation_only", "punctuation_alias_approved"],
        "evidence": {
            "classification": "punctuation_only",
            "approved_punctuation_alias": True,
            "punctuation_changes": [
                {
                    "gap_index": 3,
                    "iso_symbol": "_",
                    "candidate_symbol": '"',
                }
            ],
        },
    }


def test_same_iso_family_spools_are_not_reciprocal_competitors():
    cases = [
        {
            "iso_line": "CHWR-32118-2_-S1P4-C30",
            "iso_spool": "1",
            "candidates": [_candidate("item-a")],
        },
        {
            "iso_line": "CHWR-32118-2_-S1P4-C30",
            "iso_spool": "2",
            "candidates": [_candidate("item-a")],
        },
    ]

    annotate_family_aware_safety(cases)

    assert all(case["candidates"][0]["auto_safe"] for case in cases)
    assert all(
        case["candidates"][0]["safety_checks"]["reciprocal_best"]
        for case in cases
    )


def test_different_iso_families_still_block_the_same_item():
    cases = [
        {"iso_line": "LINE-A", "candidates": [_candidate("item-a")]},
        {"iso_line": "LINE-B", "candidates": [_candidate("item-a")]},
    ]

    annotate_family_aware_safety(cases)

    assert not any(case["candidates"][0]["auto_safe"] for case in cases)
    assert all(
        "auto_block_competing_iso" in case["candidates"][0]["reason_codes"]
        for case in cases
    )


def test_symbol_batch_groups_exact_signature_and_keeps_conflicts_out():
    first = _candidate("item-a", pair_safe=False)
    second = _candidate("item-a", pair_safe=False)
    conflict = _candidate("item-a", pair_safe=False)
    cases = [
        {
            "iso_line": "CHWR-32118-2_-S1P4-C30",
            "iso_spool": "1",
            "candidates": [first],
        },
        {
            "iso_line": "CHWR-32118-2_-S1P4-C30",
            "iso_spool": "2",
            "candidates": [second],
        },
        {"iso_line": "OTHER-999_", "candidates": [conflict]},
    ]
    signature = pattern_signature(cases[0]["iso_line"], first)

    preview = preview_symbol_batch(cases, signature)

    # The OTHER case has a different alphanumeric skeleton, so it is not a
    # member of this exact punctuation signature.
    assert preview.member_cases == (0, 1)
    assert preview.eligible == ((0, 0), (1, 0))
    assert preview.excluded == ()
