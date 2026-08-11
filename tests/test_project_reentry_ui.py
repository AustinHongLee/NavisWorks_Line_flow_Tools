# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


@contextmanager
def _window():
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


def _capsule(
    project: Path,
    *,
    run_id: str,
    activity: datetime,
    event_type: str,
    status: str,
    stage: str,
    cases: int = 0,
) -> None:
    run_dir = project / ".flowdesk" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id}),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"status": status, "current_stage": stage}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "sequence": 1,
                "occurred_at": activity.isoformat(),
                "event_type": event_type,
                "stage": stage,
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if cases:
        (run_dir / "cases.json").write_text(
            json.dumps(
                {
                    "case_count": cases,
                    "cases": [
                        {"iso_line": f"LINE-{index}", "iso_spool": "S"}
                        for index in range(cases)
                    ],
                }
            ),
            encoding="utf-8",
        )


def test_failed_project_reentry_shows_absolute_and_six_month_memory(tmp_path: Path):
    activity = datetime.now().astimezone() - timedelta(days=183)
    _capsule(
        tmp_path,
        run_id="run-private-diagnostic-id",
        activity=activity,
        event_type="run.failed",
        status="failed",
        stage="extract",
    )

    with _window() as (app, window):
        window.txt_base_dir.setText(str(tmp_path))
        app.processEvents()

        assert activity.strftime("%Y/%m/%d %H:%M") in window.lbl_header_run.text()
        assert "約6個月前" in window.lbl_header_run.text()
        assert "掃描 3D 管線" in window.lbl_header_run.text()
        assert "run-private-diagnostic-id" not in window.lbl_header_run.text()
        assert "run-private-diagnostic-id" in window.lbl_header_run.toolTip()
        assert window.lbl_header_state.text() == "失敗"
        assert window.btn_header_action.text() == "修正專案"


def test_old_review_queue_is_visible_but_requires_revalidation(tmp_path: Path):
    activity = datetime.now().astimezone() - timedelta(days=366)
    _capsule(
        tmp_path,
        run_id="run-old-review",
        activity=activity,
        event_type="run.completed",
        status="completed",
        stage="review",
        cases=4,
    )

    with _window() as (app, window):
        window.txt_base_dir.setText(str(tmp_path))
        app.processEvents()

        assert "約1年前" in window.lbl_header_run.text()
        assert "尚待判讀 4 筆" in window.lbl_header_run.text()
        assert window.lbl_header_state.text() == "待判讀"
        assert window.btn_header_action.text() == "重新驗證設定"
        assert not window.btn_resume_review.isVisible()


def test_recent_project_is_one_click_but_never_auto_runs(tmp_path: Path):
    (tmp_path / "First_try.csv").write_text("id\n1\n", encoding="utf-8")

    with _window() as (app, window):
        window._recent_project_dir = str(tmp_path)
        window._refresh_workbench_header()

        assert window.btn_header_action.text() == "繼續上次專案"
        window.btn_header_action.click()
        app.processEvents()

        assert window.txt_base_dir.text() == str(tmp_path)
        assert window._worker is None
        assert not window._is_running
        assert window.lbl_header_project.text() == tmp_path.name
