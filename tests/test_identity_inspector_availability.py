# -*- coding: utf-8 -*-
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.identity_investigator import make_paths
from gui.dialogs import identity_inspector_dialog


def test_missing_evidence_is_not_rendered_as_zero(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    paths = make_paths(str(tmp_path))
    captured = {}

    def fake_investigate_identity(query, received_paths):
        captured["query"] = query
        captured["paths"] = received_paths
        return {
            "family": {
                "normalized": "TRIM-6FL216Q-N3-001",
                "drop_last": "TRIM-6FL216Q-N3",
                "series_prefix": "TRIM-6FL216Q",
                "strict_3d_count": "0",
                "series_3d_count": "0",
                "identity_index_hit_count": "0",
                "first_try_source": "First_try.csv",
                "normalize_events": "",
                "iso_hit_count": "0",
                "minus1_hit_count": "0",
                "candidate_hit_count": "0",
                "first_try_hit_count": "0",
                "drop_last_3d_count": "0",
            },
            "iso_rows": [],
            "candidate_rows": [],
            "minus1_rows": [],
            "first_try_rows": [],
            "level_summary": [],
            "has_iso_source": True,
            "has_minus1": False,
            "has_candidates": False,
            "has_identity_index": False,
            "has_first_try_trace": False,
            "has_first_try": False,
        }

    monkeypatch.setattr(
        identity_inspector_dialog,
        "investigate_identity",
        fake_investigate_identity,
    )

    widget = identity_inspector_dialog.IdentityInspectorWidget(
        None,
        paths_getter=lambda: paths,
    )
    try:
        widget.set_query("TRIM-6FL216Q-N3-001")
        app.processEvents()

        assert captured == {
            "query": "TRIM-6FL216Q-N3-001",
            "paths": paths,
        }
        assert "未保留" in widget.lbl_availability.text()
        assert "不等於 0" in widget.lbl_availability.text()

        assert widget._metric_labels["iso_hit_count"].text() == "0"
        for key in (
            "minus1_hit_count",
            "candidate_hit_count",
            "first_try_hit_count",
            "drop_last_3d_count",
        ):
            assert widget._metric_labels[key].text() == "—"

        assert widget.lbl_level_hint.text() == "未保留"
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
