# -*- coding: utf-8 -*-
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

    from gui.dialogs.match_workbench_dialog import (
        MatchWorkbenchDialog,
        describe_symbol_difference,
    )
except ModuleNotFoundError:  # pragma: no cover - depends on local GUI runtime
    QApplication = None
    QDialog = None
    QMessageBox = None
    MatchWorkbenchDialog = None
    describe_symbol_difference = None


def _workbench_data():
    return [
        {
            "iso_line": 'CHWR-32145-2_-S1P4-C30',
            "iso_spool": "4",
            "candidates": [
                {
                    "line_3d": 'CHWR-32145-2"-S1P4-C30',
                    "raw_3d": '/CHWR-32145-2"-S1P4-C30',
                    "score": 0.74,
                    "source": "ISO 反查",
                    "reason": "英數骨架一致，只有符號差異",
                    "auto_safe": True,
                    "evidence": {
                        "difference_type": "symbol_only",
                        "symbol_diff": '_ ↔ "',
                        "path": "Plant___CHWR___32145",
                        "family_id": "CHWR-32145",
                        "ownership_status": "available",
                        "safety_checks": {
                            "alnum_equal": True,
                            "unique_family": True,
                            "ownership_clear": True,
                        },
                    },
                }
            ],
        },
        {
            "iso_line": "P-200_A",
            "iso_spool": "5",
            "candidates": [
                {
                    "line_3d": 'P-200"A',
                    "score": 0.82,
                    "auto_safe": False,
                    "reason": "符號模式需專案確認",
                    "evidence": {
                        "symbol_only": True,
                        "symbol_diff": '_ ↔ "',
                        "ownership_status": "available",
                    },
                }
            ],
        },
        {
            "iso_line": "LEGACY-900",
            "iso_spool": "6",
            "iso_metadata": {
                "系統": "LEGACY",
                "Class": "N3",
                "drawing_group2": "/LEGACY-900",
            },
            "candidates": [
                {
                    "line_3d": "LEGACY-900",
                    "score": 0.99,
                    "auto_safe": True,
                    "reason": "舊格式高分候選，但沒有 evidence",
                }
            ],
        },
        {
            "iso_line": "CONFLICT-1",
            "iso_spool": "7",
            "candidates": [
                {
                    "line_3d": "CONFLICT-1",
                    "score": 1.0,
                    "auto_safe": True,
                    "evidence": {
                        "ownership_status": "conflict",
                        "safety_checks": {"ownership_clear": False},
                    },
                }
            ],
        },
        {
            "iso_line": "NO-CANDIDATE",
            "iso_spool": "8",
            "candidates": [],
        },
        {
            "iso_line": "FAILED-CHECK",
            "iso_spool": "9",
            "candidates": [
                {
                    "line_3d": "FAILED-CHECK",
                    "score": 1.0,
                    "auto_safe": True,
                    "evidence": {
                        "ownership_status": "available",
                        "safety_checks": {"unique_family": False},
                    },
                }
            ],
        },
    ]


class MatchWorkbenchDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest("PyQt6 不在目前測試 runtime 中")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = MatchWorkbenchDialog(None, _workbench_data())

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self._app.processEvents()

    def test_constructs_master_detail_and_groups_by_evidence(self):
        counts = self.dialog.category_counts()
        self.assertEqual(counts["safe_batch"], 1)
        self.assertEqual(counts["symbol_pattern"], 1)
        self.assertEqual(counts["item_review"], 2)
        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["no_candidate"], 1)

        headers = [
            self.dialog.candidate_table.horizontalHeaderItem(i).text()
            for i in range(self.dialog.candidate_table.columnCount())
        ]
        self.assertIn("證據分數", headers)
        self.assertNotIn("機率", headers)
        self.assertEqual(
            [self.dialog.context_tabs.tabText(i) for i in range(3)],
            ["判斷依據", "AI 建議", "技術紀錄"],
        )

        self.assertTrue(self.dialog.select_case(0))
        self._app.processEvents()
        self.assertIn(
            "CHWR | 32145 | 2 | S1P4 | C30",
            self.dialog._evidence_labels["iso_skeleton"].text(),
        )
        self.assertIn("_ ↔", self.dialog._evidence_labels["symbol_diff"].text())
        self.assertEqual(
            self.dialog._evidence_labels["family"].text(),
            "CHWR-32145",
        )

    def test_decision_is_staged_reversible_and_only_returned_after_confirm(self):
        self.assertTrue(self.dialog.stage_candidate(2, 0))
        self.assertEqual(self.dialog.get_selections(), [])
        staged = self.dialog.get_staged_decisions()
        self.assertEqual(staged[0]["status"], "staged")
        self.assertEqual(staged[0]["case_index"], 2)

        self.assertTrue(self.dialog.undo_case(2))
        self.assertEqual(self.dialog.get_staged_decisions(), [])

        self.assertTrue(self.dialog.stage_candidate(2, 0))
        with patch(
            "gui.dialogs.match_workbench_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.dialog._finish()

        selections = self.dialog.get_selections()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]["iso_line"], "LEGACY-900")
        self.assertEqual(
            selections[0]["iso_metadata"],
            {
                "系統": "LEGACY",
                "Class": "N3",
                "drawing_group2": "/LEGACY-900",
            },
        )
        self.assertEqual(selections[0]["decision_status"], "accepted")
        self.assertEqual(selections[0]["decision_origin"], "manual")

    def test_safe_batch_uses_explicit_evidence_not_score(self):
        count = self.dialog.stage_all_auto_safe()
        self.assertEqual(count, 1)
        staged = self.dialog.get_staged_decisions()
        self.assertEqual([decision["case_index"] for decision in staged], [0])
        self.assertEqual(staged[0]["origin"], "safe_batch")

        # 99% legacy candidate has auto_safe but no evidence: never auto-stage.
        self.assertNotIn(2, {decision["case_index"] for decision in staged})
        # 100% candidate with a failed safety check also stays out.
        self.assertNotIn(5, {decision["case_index"] for decision in staged})

    def test_blocked_candidate_cannot_be_staged(self):
        self.assertFalse(self.dialog.stage_candidate(3, 0))
        self.assertEqual(self.dialog.get_staged_decisions(), [])

    def test_symbol_diff_refuses_to_hide_alnum_identity_change(self):
        self.assertEqual(
            describe_symbol_difference("CHWR-32145", "CHWR-32145A"),
            "英數骨架不同（不屬於純符號差異）",
        )
        self.assertIn(
            "_ ↔",
            describe_symbol_difference('CHWR-32145-2_', 'CHWR-32145-2"'),
        )

    def test_symbol_pattern_can_stage_safe_members_now_and_stage_rule_together(self):
        def candidate():
            return {
                "line_3d": 'CHWR-32118-2"-S1P4-C30',
                "raw_3d": 'CHWR-32118-2"-S1P4-C30',
                "item_id": "stable-item-a",
                "family_id": "3d-family-a",
                "ownership_status": "available",
                "score": 0.86,
                "auto_safe": False,
                "evidence": {
                    "classification": "punctuation_only",
                    "punctuation_changes": [
                        {
                            "gap_index": 3,
                            "iso_symbol": "_",
                            "candidate_symbol": '"',
                        }
                    ],
                },
            }

        data = [
            {
                "iso_line": "CHWR-32118-2_-S1P4-C30",
                "iso_spool": "1",
                "candidates": [candidate()],
            },
            {
                "iso_line": "CHWR-32118-2_-S1P4-C30",
                "iso_spool": "2",
                "candidates": [candidate()],
            },
        ]
        dialog = MatchWorkbenchDialog(None, data, project_dir="C:/project")
        try:
            signature = dialog._case_pattern_signature(0)
            preview = dialog.stage_symbol_batch(signature, remember_rule=True)
            self.assertEqual(preview.eligible_count, 2)
            self.assertEqual(
                [item["case_index"] for item in dialog.get_staged_decisions()],
                [0, 1],
            )
            self.assertEqual(
                dialog.get_pending_rules(),
                [
                    {
                        "iso_symbol": "_",
                        "candidate_symbol": '"',
                        "pattern": '_ → "（位置 3）',
                    }
                ],
            )
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_candidate_table_defaults_to_top_three_and_renders_inline_diff(self):
        item = _workbench_data()[0]
        item["candidates"][0]["evidence"]["classification"] = "punctuation_only"
        item["candidates"] = [dict(item["candidates"][0]) for _ in range(5)]
        dialog = MatchWorkbenchDialog(None, [item])
        try:
            self.assertEqual(dialog.candidate_table.rowCount(), 3)
            self.assertTrue(dialog.expand_candidates_button.isVisibleTo(dialog))
            dialog._toggle_candidate_expansion()
            self.assertEqual(dialog.candidate_table.rowCount(), 5)
            dialog.candidate_table.selectRow(0)
            self._app.processEvents()
            self.assertIn("span", dialog.diff_iso_label.text())
            self.assertIn("符號差異", dialog.diff_kind_label.text())
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
