# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

import gui.tabs.tab_json as tab_json
from gui.main_window import MainWindow


@contextmanager
def _shown_main_window() -> Iterator[tuple[QApplication, MainWindow]]:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    try:
        yield app, window
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_project_path_switch_clears_the_bound_run_and_export_session(tmp_path):
    old_project = tmp_path / "old-project"
    new_project = tmp_path / "new-project"
    old_project.mkdir()
    new_project.mkdir()

    with _shown_main_window() as (app, window):
        window.txt_base_dir.setText(str(old_project))
        app.processEvents()

        old_worker = object()
        old_export_df = pd.DataFrame(
            {"Raw_3D_PipeCode": ["OLD-PIPE"]}
        )
        window._active_run_id = "old-run-id"
        window._worker = old_worker
        window._v2_iso_df = old_export_df
        window.btn_resume_review.setVisible(True)
        app.processEvents()

        assert window._worker is old_worker
        assert window._v2_iso_df is old_export_df
        assert window.btn_resume_review.isVisible()

        window.txt_base_dir.setText(str(new_project))
        app.processEvents()

        assert window._active_run_id == ""
        assert window._worker is None
        assert window._v2_iso_df is None
        assert not window.btn_resume_review.isVisible()
        assert window.txt_base_dir.text() == str(new_project)
        assert QApplication.instance() is app
        assert window.centralWidget() is not None
        assert window.isVisible()


def test_json_export_button_starts_disabled():
    with _shown_main_window() as (_app, window):
        assert not window._v2_btn_export.isEnabled()


def test_duplicate_filter_column_resets_the_second_row_and_warns_inline(
    monkeypatch,
):
    source_df = pd.DataFrame(
        {
            "Raw_3D_PipeCode": ["PIPE-1", "PIPE-2"],
            "流水號": ["L-1", "L-2"],
            "系統": ["A", "B"],
            "Resolved": ["1", "1"],
        }
    )
    monkeypatch.setattr(
        tab_json,
        "read_iso_match",
        lambda _path: source_df.copy(),
    )

    with _shown_main_window() as (app, window):
        window._v2_load_source("memory.csv")
        window.pages.setCurrentIndex(2)
        app.processEvents()

        first_row, second_row = window._v2_filter_row_widgets[:2]
        first_row["cbo_col"].setCurrentText("系統")
        app.processEvents()
        second_row["cbo_col"].setCurrentText("系統")
        app.processEvents()

        assert first_row["active_col"] == "系統"
        assert first_row["cbo_col"].currentText() == "系統"
        assert second_row["active_col"] is None
        assert second_row["cbo_col"].currentText() == "（不篩選）"
        assert not second_row["btn_val"].isVisible()

        json_page = window.pages.widget(2)
        duplicate_warnings = [
            label
            for label in json_page.findChildren(QLabel)
            if "系統" in label.text() and "已使用" in label.text()
        ]
        assert duplicate_warnings
        assert any(label.isVisible() for label in duplicate_warnings)


def test_filter_with_more_than_display_limit_is_blocked_instead_of_truncated(
    monkeypatch,
):
    warnings = []
    monkeypatch.setattr(
        tab_json.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    class UnexpectedPopup:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("unsafe truncated popup must not open")

    monkeypatch.setattr(tab_json, "FilterPopup", UnexpectedPopup)

    with _shown_main_window() as (_app, window):
        window._v2_iso_df = pd.DataFrame(
            {"流水號": [f"S-{index:05d}" for index in range(5001)]}
        )
        row = window._v2_filter_row_widgets[0]
        row["active_col"] = "流水號"

        window._on_filter_val_clicked(0)

        assert warnings
        assert "5,001" in warnings[-1][2]
        assert "不會開啟或套用篩選" in warnings[-1][2]


def test_manual_cleanup_requires_confirmation_before_deleting(monkeypatch, tmp_path):
    evidence = tmp_path / "123_minus_1.csv"
    evidence.write_text("evidence", encoding="utf-8")
    questions = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: questions.append(args) or QMessageBox.StandardButton.No,
    )

    with _shown_main_window() as (_app, window):
        window.txt_base_dir.setText(str(tmp_path))
        window._on_cleanup()

        assert questions
        assert evidence.is_file()
        assert "123_minus_1.csv" in questions[-1][2]
        assert "證據會減少" in questions[-1][2]
