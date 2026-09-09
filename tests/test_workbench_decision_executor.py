# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PyQt6.QtWidgets import QApplication

from core.candidate_family import candidate_item_id
from core.resolved_mapping import build_resolved_mapping
from core.run_ledger import RunLedger
from gui.main_window import MainWindow


def test_first_try_rescue_refreshes_ledger_ownership(tmp_path):
    app = QApplication.instance() or QApplication([])
    first_try = tmp_path / "First_try.csv"
    pd.DataFrame(
        [
            {
                "Path": "MODEL___AREA___/TRIM-OIL-DITCH-PIPE",
                "DisplayName": "/TRIM-OIL-DITCH-PIPE",
                "Class": "Pipe",
                "Level": "3",
                "PipelineId": "/TRIM-OIL-DITCH-PIPE",
            }
        ]
    ).to_csv(first_try, index=False, encoding="utf-8-sig")

    class ClaimedLedger:
        @staticmethod
        def get_ownership(_item_id):
            return {"family_id": "ANOTHER-ISO-FAMILY"}

    window = MainWindow()
    try:
        window.txt_base_dir.setText(str(tmp_path))
        window.txt_first_name.setText("First_try.csv")
        window._worker = SimpleNamespace(
            p={"base_dir": str(tmp_path), "first_name": "First_try.csv"},
            input_fingerprint="sha256:test-input",
            ledger=ClaimedLedger(),
        )

        candidates = window._rescue_first_try_candidates(
            {"iso_line": "TRIM-OIL-DITCH-PIPE"}
        )

        assert candidates
        assert candidates[0]["ownership_status"] == "claimed_by_other"
        assert candidates[0]["evidence"]["ownership_family"] == "ANOTHER-ISO-FAMILY"
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_human_workbench_apply_is_versioned_locked_and_audited(tmp_path):
    app = QApplication.instance() or QApplication([])
    dataset_revision = "sha256:test-input"
    iso_match = tmp_path / "iso_match.xlsx"
    mapping = tmp_path / "resolved_mapping.csv"
    pd.DataFrame(
        [
            {
                "管線編號": "LINE-A",
                "流水號": "1",
                "ISO_Match_Key": "3D-A",
                "Raw_3D_PipeCode": "/3D-A",
                "PipeNodePath": "MODEL___AREA___3D-A",
                "ScopeRoot": "AREA",
                "PipeNodeLevel": "2",
                "NeedsDecision": "0",
                "MatchType": "strict",
            }
        ]
    ).to_excel(iso_match, index=False, sheet_name="結果")
    build_resolved_mapping(
        str(iso_match),
        str(mapping),
        dataset_revision=dataset_revision,
    )

    window = MainWindow()
    window.txt_base_dir.setText(str(tmp_path))
    window.txt_first_name.setText("First_try.csv")
    window.chk_file_log.setChecked(False)
    ledger = RunLedger(tmp_path)
    run_id = ledger.start_run(
        input_fingerprint=dataset_revision,
        base_state_hash=window._sha256_file(str(mapping)),
    )
    ledger.finish_run(run_id, success=True, summary={"ready_for_review": True})
    window._worker = SimpleNamespace(
        ledger=ledger,
        run_id=run_id,
        input_fingerprint=dataset_revision,
    )

    candidate_meta = {
        "raw_3d": "/3D-B",
        "path": "MODEL___AREA___3D-B",
        "scope": "AREA",
        "level": "2",
    }
    item_id = candidate_item_id(candidate_meta, dataset_revision)
    selection = {
        "iso_line": "LINE-B",
        "iso_spool": "2",
        "line_3d": "3D-B",
        "raw_3d": "/3D-B",
        **candidate_meta,
        "item_id": item_id,
        "score": 0.86,
        "reason": "人工確認",
        "evidence": {"classification": "punctuation_only"},
        "reason_codes": ["punctuation_only"],
        "iso_metadata": {
            "系統": "P",
            "Class": "S1PA",
            "drawing_group2": "/LINE-B",
        },
        "decision_origin": "manual",
    }

    added, stats = window._apply_workbench_selections(
        [selection],
        [
            {
                "iso_symbol": "_",
                "candidate_symbol": '"',
                "pattern": '_ → "（位置 3）',
            }
        ],
    )

    assert added == 1
    assert stats["resolved"] == 2
    assert ledger.get_ownership(item_id)["family_id"] == "LINE-B"
    event_types = [event["event_type"] for event in ledger.list_events(run_id)]
    assert "decision.approved" in event_types
    assert "decision.applied" in event_types
    assert "ownership.claimed" in event_types
    assert "run.base_state_changed" in event_types
    assert "rule.activated" in event_types
    assert ledger.verify_hash_chain(run_id)
    capsule = tmp_path / ".flowdesk" / "runs" / run_id
    assert (capsule / "agent_context.json").is_file()
    version_root = tmp_path / ".flowdesk" / "versions" / run_id
    assert list(version_root.rglob("before_iso_match.xlsx"))
    rules = tmp_path / ".flowdesk" / "project_rules.json"
    assert rules.is_file()
    assert '"status": "approved"' in rules.read_text(encoding="utf-8")

    # Reusing the exact ITEM under another ISO family is a hard preflight stop;
    # neither output file may change.
    iso_hash_before = window._sha256_file(str(iso_match))
    mapping_hash_before = window._sha256_file(str(mapping))
    conflicting = dict(selection, iso_line="LINE-C", iso_spool="3")
    with pytest.raises(RuntimeError, match="單一歸屬鎖阻擋"):
        window._apply_workbench_selections([conflicting])
    assert window._sha256_file(str(iso_match)) == iso_hash_before
    assert window._sha256_file(str(mapping)) == mapping_hash_before
    context = window._last_conflict_context
    assert context["run_id"] == run_id
    assert context["selections"][0]["iso_line"] == "LINE-C"
    assert context["selections"][0]["iso_metadata"] == selection["iso_metadata"]
    assert context["conflict_items"][0]["source"] == "existing_ownership"
    assert context["conflict_items"][0]["existing_family"] == "LINE-B"
    conflict_events = [
        event
        for event in ledger.list_events(run_id)
        if event["event_type"] == "ownership.conflict"
    ]
    assert conflict_events[-1]["payload"]["conflict_items"][0]["item_id"] == item_id
    assert (
        conflict_events[-1]["payload"]["recovery_selections"][0]["iso_metadata"]
        == selection["iso_metadata"]
    )
    replay_request = {
        **conflict_events[-1]["payload"],
        "run_id": run_id,
        "event_id": conflict_events[-1]["event_id"],
    }
    window._conflict_contexts.clear()
    window._last_conflict_context = {}
    replay_context = window._conflict_context_for_request(replay_request)
    assert replay_context["selections"][0]["iso_metadata"] == selection["iso_metadata"]

    # The screenshot scenario: two selections inside the same pending batch
    # compete for one previously unclaimed ITEM.
    batch_candidate = {
        "raw_3d": "/3D-C",
        "path": "MODEL___AREA___3D-C",
        "scope": "AREA",
        "level": "2",
    }
    batch_item_id = candidate_item_id(batch_candidate, dataset_revision)
    first_claim = {
        **selection,
        **batch_candidate,
        "item_id": batch_item_id,
        "line_3d": "3D-C",
        "iso_line": "LINE-D",
        "iso_spool": "4",
    }
    second_claim = dict(first_claim, iso_line="LINE-E", iso_spool="5")
    with pytest.raises(RuntimeError, match="單一歸屬鎖阻擋"):
        window._apply_workbench_selections([first_claim, second_claim])
    batch_context = window._last_conflict_context
    assert batch_context["conflict_items"][0]["source"] == "same_change_set"
    assert batch_context["conflict_items"][0]["existing_family"] == "LINE-D"
    assert batch_context["conflict_items"][0]["requested_family"] == "LINE-E"
    latest_conflict = [
        event
        for event in ledger.list_events(run_id)
        if event["event_type"] == "ownership.conflict"
    ][-1]
    assert latest_conflict["payload"]["attempted_count"] == 2
    assert latest_conflict["payload"]["safe_count"] == 0
    assert len(latest_conflict["payload"]["recovery_selections"]) == 2
    assert latest_conflict["event_id"] in window._conflict_contexts

    # Repair lookup must still find the requested ISO even if a later action has
    # removed the original-side case from the remaining queue.
    window._worker.fuzzy_unmatched = [
        {
            "iso_line": "LINE-E",
            "iso_spool": "5",
            "candidates": [dict(batch_candidate, line_3d="3D-C")],
        }
    ]
    window._worker.applied_review_keys = {("LINE-D", "4")}
    repair_request = {
        **latest_conflict["payload"],
        "run_id": run_id,
        "event_id": latest_conflict["event_id"],
    }
    focused = window._review_cases_for_conflicts(repair_request)
    assert [(case["iso_line"], case["iso_spool"]) for case in focused] == [
        ("LINE-E", "5")
    ]

    window.close()
    app.processEvents()
