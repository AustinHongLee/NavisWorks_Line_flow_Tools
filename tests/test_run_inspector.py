# -*- coding: utf-8 -*-
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from gui.run_inspector import RunInspectorPanel


def test_run_inspector_coalesces_burst_updates_and_flushes_log():
    app = QApplication.instance() or QApplication([])
    panel = RunInspectorPanel()
    try:
        for index in range(40):
            panel.append_raw(f"line {index}")
            panel.ingest(
                f"[Step1] 身份解析進度：已處理 {index + 1}/40 列"
            )

        assert panel._render_timer.isActive()
        assert panel._raw_flush_timer.isActive()
        assert panel.raw_log.document().maximumBlockCount() == 2000

        QTest.qWait(240)
        app.processEvents()

        assert panel.state.step1_scanned == "40"
        assert panel.state.first_try_rows == "40"
        assert "line 39" in panel.raw_log.toPlainText()
        assert panel.raw_count_label.text() == "40 行"
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_ownership_conflict_is_an_actionable_finding():
    app = QApplication.instance() or QApplication([])
    panel = RunInspectorPanel()
    actions = []
    panel.action_requested.connect(actions.append)
    try:
        panel.ingest_event(
            {
                "run_id": "run-test",
                "event_id": "event-conflict",
                "event_type": "ownership.conflict",
                "stage": "review",
                "payload": {
                    "message": "人工 change set 違反 3D ITEM 單一歸屬",
                    "conflicts": ["item-a：LINE-A ↔ LINE-B"],
                    "conflict_items": [
                        {
                            "item_id": "item-a",
                            "line_3d": "3D-A",
                            "existing_family": "LINE-A",
                            "requested_family": "LINE-B",
                        }
                    ],
                },
            }
        )
        QTest.qWait(160)
        app.processEvents()

        buttons = [
            button
            for button in panel.findChildren(QPushButton)
            if button.objectName() == "findingAction"
        ]
        assert buttons
        assert buttons[-1].text() == "修正這 1 個衝突"
        buttons[-1].click()
        app.processEvents()

        assert actions[-1]["action"] == "ownership_conflict_guide"
        assert actions[-1]["conflict_items"][0]["item_id"] == "item-a"
        assert panel.state.ownership_conflicts == "1"
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_repeated_conflict_replaces_older_sidebox_card_and_hides_raw_hash_error():
    app = QApplication.instance() or QApplication([])
    panel = RunInspectorPanel()
    try:
        for event_id in ("event-old", "event-new"):
            panel.ingest_event(
                {
                    "run_id": "run-test",
                    "event_id": event_id,
                    "event_type": "ownership.conflict",
                    "payload": {
                        "conflict_items": [
                            {
                                "item_id": "fallback:sha256:test:item-a",
                                "existing_family": "LINE-A",
                                "requested_family": "LINE-B",
                            }
                        ]
                    },
                }
            )
        panel.ingest("✗ 配對工作檯套用失敗：單一歸屬鎖阻擋：fallback:sha256:test")
        conflict_findings = [
            item
            for item in panel._findings
            if str(item.get("group_key", "")).startswith("ownership:")
        ]
        assert len(conflict_findings) == 1
        assert conflict_findings[0]["action"]["event_id"] == "event-new"
        assert not any("fallback:sha256" in item.get("body", "") for item in panel._findings)
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
