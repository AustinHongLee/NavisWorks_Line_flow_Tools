# -*- coding: utf-8 -*-
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from gui.dialogs.ownership_conflict_dialog import OwnershipConflictDialog


def _item() -> dict:
    return {
        "source": "existing_ownership",
        "line_3d": 'E3302-3/4"DRAIN-S1P4-1/2',
        "existing_family": "E3302-3_4_DRAIN-S1P4-1/2",
        "existing_iso_spool": "243",
        "requested_family": "E3302-3_4_DRAIN-S1P4-2_2",
        "requested_iso_spool": "244",
    }


def test_conflict_dialog_hides_unavailable_replay_action():
    app = QApplication.instance() or QApplication([])
    dialog = OwnershipConflictDialog(
        conflict_items=[_item()],
        attempted_count=2,
        focused_case_count=1,
        safe_selection_count=0,
        recovery_available=False,
    )
    try:
        labels = [button.text() for button in dialog.findChildren(QPushButton)]
        assert "開啟 1 個相關 ISO" in labels
        assert not any("先提交其餘" in label for label in labels)
        visible_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        assert "E3302-3_4_DRAIN-S1P4-2_2" in visible_text
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_conflict_dialog_exposes_safe_replay_only_when_available():
    app = QApplication.instance() or QApplication([])
    dialog = OwnershipConflictDialog(
        conflict_items=[_item()],
        attempted_count=293,
        focused_case_count=4,
        safe_selection_count=289,
        recovery_available=True,
    )
    try:
        buttons = dialog.findChildren(QPushButton)
        safe = next(button for button in buttons if "先提交其餘" in button.text())
        safe.click()
        app.processEvents()
        assert dialog.selected_action == "apply_safe"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
