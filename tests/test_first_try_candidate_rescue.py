# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd

from core.first_try_candidate_rescue import find_first_try_candidates


def test_rescues_existing_first_try_item_with_auditable_context(tmp_path):
    first_try = tmp_path / "First_try.csv"
    pd.DataFrame(
        [
            {
                "Path": "HPR_INSU.RVM___/E2511-HPR___/E2511-PIPE___/TRIM-OIL-DITCH-PIPE",
                "DisplayName": "/TRIM-OIL-DITCH-PIPE",
                "Class": "Pipe",
                "Level": "3",
                "PipelineId": "/TRIM-OIL-DITCH-PIPE",
            },
            {
                "Path": "HPR_INSU.RVM___/E2511-HPR___/OTHER-LINE",
                "DisplayName": "/OTHER-LINE",
                "Class": "Pipe",
                "Level": "3",
                "PipelineId": "/OTHER-LINE",
            },
        ]
    ).to_csv(first_try, index=False, encoding="utf-8-sig")
    original = first_try.read_bytes()

    results = find_first_try_candidates(
        str(first_try),
        "TRIM-OIL-DITCH-PIPE",
        dataset_revision="sha256:test",
    )

    assert results
    exact = next(item for item in results if item["line_3d"] == "TRIM-OIL-DITCH-PIPE")
    assert exact["raw_3d"] == "/TRIM-OIL-DITCH-PIPE"
    assert exact["path"].endswith("___/TRIM-OIL-DITCH-PIPE")
    assert exact["level"] == "3"
    assert exact["item_id"].startswith("fallback:sha256:test:")
    assert exact["source"] == "First_try 補找"
    assert exact["pair_auto_safe"] is False
    assert exact["auto_safe"] is False
    assert first_try.read_bytes() == original


def test_does_not_offer_text_only_or_missing_source(tmp_path):
    text_only = tmp_path / "First_try.csv"
    pd.DataFrame(
        [
            {
                "Path": "",
                "DisplayName": "/TRIM-OIL-DITCH-PIPE",
                "Class": "Pipe",
                "Level": "3",
                "PipelineId": "/TRIM-OIL-DITCH-PIPE",
            }
        ]
    ).to_csv(text_only, index=False, encoding="utf-8-sig")

    assert find_first_try_candidates(
        str(text_only), "TRIM-OIL-DITCH-PIPE"
    ) == []
    assert find_first_try_candidates(
        str(tmp_path / "missing.csv"), "TRIM-OIL-DITCH-PIPE"
    ) == []
