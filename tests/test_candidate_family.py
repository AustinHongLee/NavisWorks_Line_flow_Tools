# -*- coding: utf-8 -*-
from core.candidate_family import annotate_candidate_families


def test_path_ancestry_folds_children_without_equating_identity():
    rows = annotate_candidate_families(
        [
            {
                "line_3d": "CHWR-32145-2\"-S1P4-C30",
                "path": "MODEL___AREA___32145",
                "score": 0.86,
            },
            {
                "line_3d": "CHWR-32145-2\"-S1P4-C30-B1",
                "path": "MODEL___AREA___32145___B1",
                "score": 0.70,
            },
            {
                "line_3d": "CHWR-32145-2\"-S1P4-C30-B2",
                "path": "MODEL___AREA___32145___B2",
                "score": 0.70,
            },
        ]
    )

    assert rows[0]["family_role"] == "root"
    assert rows[1]["family_role"] == "child"
    assert rows[2]["family_role"] == "child"
    assert {row["family_id"] for row in rows} == {rows[0]["item_id"]}
    assert rows[0]["family_member_count"] == 3
    assert rows[1]["family_identity_equivalent"] is False


def test_similar_names_without_path_proof_remain_independent():
    rows = annotate_candidate_families(
        [
            {"line_3d": "CHWR-32145-2\"-S1P4-C30", "path": "MODEL___A"},
            {"line_3d": "CHWR-32145A-2\"-S1P4-C30", "path": "MODEL___B"},
        ]
    )

    assert rows[0]["family_role"] == "independent"
    assert rows[1]["family_role"] == "independent"
    assert rows[0]["family_id"] != rows[1]["family_id"]
    assert rows[0]["independent_family_count"] == 2


def test_nearest_actual_ancestor_becomes_display_parent():
    rows = annotate_candidate_families(
        [
            {"line_3d": "ROOT", "path": "MODEL___ROOT"},
            {"line_3d": "MID", "path": "MODEL___ROOT___MID"},
            {"line_3d": "LEAF", "path": "MODEL___ROOT___MID___LEAF"},
        ]
    )

    assert rows[2]["family_parent_item_id"] == rows[1]["item_id"]
    assert rows[2]["family_id"] == rows[0]["item_id"]
