# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QCoreApplication

from core.run_ledger import RunLedger
from gui.worker import PipelineWorker


def test_worker_emits_structured_events_and_run_capsule(tmp_path):
    _app = QCoreApplication.instance() or QCoreApplication([])
    first = tmp_path / "First_try.csv"
    iso = tmp_path / "ISO_LIST.xlsx"
    first.write_text("Path,DisplayName\n/A,/LINE\n", encoding="utf-8")
    iso.write_bytes(b"fake-iso-input")

    params = {
        "base_dir": str(tmp_path),
        "first_name": first.name,
        "iso_list_path": str(iso),
        "sep": "___",
        "raw_prefix": "/",
        "filter_key": "",
        "id_level": 4,
        "scan_mode": "full",
        "iso_sheet": "Sheet1",
        "pipe_col": "Line",
        "spool_col": "Spool",
        "extra_headers": [],
        "limit_iso_cols": False,
        "write_first_try_trace": False,
        "write_candidates": False,
    }

    extractor = Mock()

    def build_intermediate(_source, output, **_kwargs):
        Path(output).write_text("ISO_Match_Key,Raw_3D_PipeCode\nA,/A\n", encoding="utf-8")
        return 3

    extractor.build_intermediate.side_effect = build_intermediate
    grouper = Mock()

    def parse_and_export(_source, csv_output, xlsx_output):
        Path(csv_output).write_text("ISO_Match_Key,Raw_3D_PipeCode\nA,/A\n", encoding="utf-8")
        Path(xlsx_output).write_bytes(b"group-workbook")
        return 2, 1

    grouper.parse_and_export.side_effect = parse_and_export
    matcher = Mock()
    matcher.fuzzy_unmatched = [{"iso_line": "ISO-X", "candidates": []}]

    def match_run(**kwargs):
        Path(kwargs["iso_output_path"]).write_bytes(b"match-workbook")
        return 2

    matcher.run.side_effect = match_run

    def build_mapping(*, output_path, **_kwargs):
        Path(output_path).write_text("Resolved,Raw_3D_PipeCode\n1,/A\n", encoding="utf-8")
        return {
            "path": output_path,
            "identity_index_path": "",
            "total": 1,
            "resolved": 1,
            "needs_decision": 0,
            "no_raw": 0,
            "ownership_conflicts": 0,
            "ownership_unverifiable": 0,
        }

    worker = PipelineWorker(params)
    events: list[dict] = []
    finished: list[tuple[bool, str]] = []
    worker.event_signal.connect(events.append)
    worker.finished_signal.connect(lambda ok, text: finished.append((ok, text)))

    with (
        patch("gui.worker.PipelineExtractor", return_value=extractor),
        patch("gui.worker.PipelineGrouper", return_value=grouper),
        patch("gui.worker.IsoMatcher", return_value=matcher),
        patch("gui.worker.build_resolved_mapping", side_effect=build_mapping),
    ):
        worker.run()

    assert finished and finished[-1][0] is True
    assert worker.run_id
    assert events[0]["event_type"] == "run.started"
    assert events[-1]["event_type"] == "run.completed"
    assert any(event["event_type"] == "review.requested" for event in events)
    metrics = {
        event["payload"].get("name")
        for event in events
        if event["event_type"] == "metric.recorded"
    }
    assert "mapping.ownership_conflicts" in metrics

    capsule = tmp_path / ".flowdesk" / "runs" / worker.run_id
    assert (capsule / "manifest.json").is_file()
    assert (capsule / "events.jsonl").is_file()
    assert (capsule / "artifacts.json").is_file()
    assert RunLedger(tmp_path).verify_hash_chain(worker.run_id)
