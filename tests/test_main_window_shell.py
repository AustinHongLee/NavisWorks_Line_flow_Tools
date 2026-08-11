# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import QApplication

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
        QCoreApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        app.processEvents()


def test_sidebar_navigation_matches_the_actual_workflow_stages():
    with _shown_main_window() as (_app, window):
        assert [button.text() for button in window._nav_btns] == [
            "專案設定",
            "ISO 比對",
            "JSON 輸出",
            "稽核調查",
        ]
        assert all(not button.icon().isNull() for button in window._nav_btns)
        assert all(
            button.property("motion-role") == "quiet"
            for button in window._nav_btns
        )


def test_sidebar_uses_the_high_resolution_brand_mark():
    with _shown_main_window() as (_app, window):
        pixmap = window.lbl_brand_icon.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.width() <= 48
        assert pixmap.height() <= 48

    brand_dir = Path(__file__).resolve().parents[1] / "assets" / "branding"
    icon = QIcon(str(brand_dir / "pipeline_ops_v2.ico"))
    sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes


def test_sidebar_states_include_a_non_colour_current_marker():
    with _shown_main_window() as (app, window):
        assert [label.text() for label in window._nav_state_labels].count("●") == 1
        assert window._nav_state_labels[0].text() == "●"

        window._nav_btns[2].click()
        QTest.qWait(650)
        app.processEvents()

        assert window.pages.currentIndex() == 2
        assert [label.text() for label in window._nav_state_labels].count("●") == 1
        assert window._nav_state_labels[2].text() == "●"


def test_run_action_starts_disabled_with_project_guidance():
    with _shown_main_window() as (_app, window):
        assert not window.btn_run_all.isEnabled()
        assert "請先" in window.btn_run_all.toolTip()
        assert "專案" in window.btn_run_all.toolTip()


def test_cleanup_defaults_safe_and_is_locked_only_while_running():
    with _shown_main_window() as (app, window):
        assert not window.chk_auto_cleanup.isChecked()
        assert window.btn_cleanup is not None
        assert window.btn_cleanup.isEnabled()

        window._set_running(True)
        app.processEvents()
        assert not window.btn_cleanup.isEnabled()
        assert not window.btn_run_all.isEnabled()
        assert not window.btn_header_action.isEnabled()
        assert not window.btn_detect_level.isEnabled()

        window._set_running(False)
        app.processEvents()
        assert window.btn_cleanup.isEnabled()
        assert not window.btn_run_all.isEnabled()
        assert window.btn_header_action.isEnabled()
        assert window.btn_detect_level.isEnabled()


def test_running_guard_prevents_a_second_worker_start():
    with _shown_main_window() as (_app, window):
        started: list[dict] = []
        window._run_ready = True
        window._is_running = True
        window._start_worker = lambda params: started.append(params)

        window._on_run_all()

        assert started == []


def test_run_inspector_starts_hidden_and_header_toggle_controls_it():
    with _shown_main_window() as (app, window):
        assert window.run_inspector.isHidden()

        window.btn_toggle_inspector.click()
        app.processEvents()
        assert window.run_inspector.isVisible()

        window.btn_toggle_inspector.click()
        app.processEvents()
        assert window.run_inspector.isHidden()


def test_progress_area_appears_when_progress_is_reported():
    with _shown_main_window() as (app, window):
        assert window.progress_widget.isHidden()

        window._on_progress(10, "處理中")
        app.processEvents()

        assert window.progress_widget.isVisible()
        assert window.progress_bar.value() == 10
        assert window.lbl_progress.text() == "處理中"


def test_header_action_guides_an_empty_project_back_to_setup():
    with _shown_main_window() as (app, window):
        assert window.btn_header_action.text() == "選擇專案"
        assert not window.btn_header_action.icon().isNull()
        assert window.btn_header_action.property("motion-role") == "primary"

        window._nav_btns[1].click()
        QTest.qWait(350)
        app.processEvents()

        assert window.pages.currentIndex() == 1
        assert window.btn_header_action.text() == "返回專案設定"


def test_recent_project_memory_does_not_probe_an_offline_path(monkeypatch):
    with _shown_main_window() as (_app, window):
        window._recent_project_dir = r"\\offline-server\archived-project"

        def fail_if_probed(_path):
            raise AssertionError("startup must not stat a recent network path")

        monkeypatch.setattr("gui.main_window.os.path.isdir", fail_if_probed)

        text, tooltip = window._continuity_memory_text("")

        assert text == "最近專案：archived-project"
        assert tooltip == r"\\offline-server\archived-project"


def test_shutdown_releases_button_motion_before_qapplication_teardown():
    with _shown_main_window() as (_app, window):
        assert window._button_motion.installed_count > 0

        window.shutdown()
        window.shutdown()

        assert window._button_motion.installed_count == 0


def test_close_is_ignored_while_a_pipeline_worker_is_running():
    class RunningWorker:
        @staticmethod
        def isRunning():  # noqa: N802 - mirrors QThread
            return True

    with _shown_main_window() as (_app, window):
        window.hide()
        window._worker = RunningWorker()
        event = QCloseEvent()

        window.closeEvent(event)

        assert not event.isAccepted()
        assert window._button_motion.installed_count > 0
        window._worker = None
