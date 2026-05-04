# -*- coding: utf-8 -*-
"""Collision 決策對話框。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.collision_resolver import build_common_decisions
from gui.dialogs.identity_inspector_dialog import IdentityInspectorDialog


class CollisionDecisionDialog(QDialog):
    """列出 ``NeedsDecision=1`` 的流水號，讓使用者選定 ParentArea。"""

    def __init__(self, parent, groups: list[dict[str, object]]):
        super().__init__(parent)
        self.setWindowTitle("Collision 決策")
        self.setMinimumSize(900, 540)
        self.resize(980, 620)
        self._groups = groups
        self._current_idx = 0
        self._decisions: dict[str, object] = {}
        self._build_ui()
        if groups:
            self._load_group(0)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QDialog { background: #FFFFFF; color: #1E293B; }"
            "QLabel { color: #1E293B; }"
            "QListWidget, QTableWidget { background: #FFFFFF; color: #1E293B;"
            " border: 1px solid #D1D5DB; border-radius: 8px; }"
            "QHeaderView::section { background: #F8FAFC; color: #475569;"
            " border: none; border-bottom: 1px solid #E2E8F0;"
            " padding: 6px 8px; font-weight: 600; }"
            "QPushButton { background: #FFFFFF; color: #2563EB;"
            " border: 1px solid #BFDBFE; border-radius: 6px;"
            " padding: 6px 14px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #EFF6FF; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel(f"共 {len(self._groups)} 個流水號需要決策")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("流水號"))
        self._spool_list = QListWidget()
        self._spool_list.setFixedWidth(260)
        for group in self._groups:
            self._spool_list.addItem(str(group.get("spool", "")))
        self._spool_list.currentRowChanged.connect(self._on_group_changed)
        left.addWidget(self._spool_list)
        mid.addLayout(left)

        right = QVBoxLayout()
        self._lbl_detail = QLabel("")
        self._lbl_detail.setStyleSheet("font-size: 12px; color: #64748B;")
        right.addWidget(self._lbl_detail)
        self._choice_table = QTableWidget()
        self._choice_table.setColumnCount(5)
        self._choice_table.setHorizontalHeaderLabels(
            ["決策點", "列數", "Raw 數", "Raw 範例", "操作"]
        )
        self._choice_table.verticalHeader().setVisible(False)
        self._choice_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._choice_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._choice_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._choice_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._choice_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._choice_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._choice_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Fixed
        )
        self._choice_table.horizontalHeader().resizeSection(4, 180)
        right.addWidget(self._choice_table)
        mid.addLayout(right, stretch=1)
        root.addLayout(mid, stretch=1)

        btn_row = QHBoxLayout()
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("font-size: 12px; color: #64748B;")
        btn_row.addWidget(self._lbl_status)
        btn_row.addStretch()
        btn_investigate = QPushButton("在調查頁查看")
        btn_investigate.clicked.connect(self._open_current_investigation)
        btn_row.addWidget(btn_investigate)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_apply = QPushButton("套用決策")
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _on_group_changed(self, row: int) -> None:
        if 0 <= row < len(self._groups):
            self._load_group(row)

    def _load_group(self, idx: int) -> None:
        self._current_idx = idx
        self._spool_list.blockSignals(True)
        self._spool_list.setCurrentRow(idx)
        self._spool_list.blockSignals(False)
        group = self._groups[idx]
        spool = str(group.get("spool", ""))
        area_col = str(group.get("area_col", "ParentArea"))
        choices = group.get("choices", [])
        self._lbl_detail.setText(
            f"流水號 {spool} 目前分散在 {len(choices)} 個 {area_col}"
        )
        self._choice_table.setRowCount(0)
        selected_decision = self._decisions.get(spool, "")
        if isinstance(selected_decision, dict):
            selected_area = str(selected_decision.get("area", ""))
        else:
            selected_area = str(selected_decision)
        for choice in choices:
            area = str(choice.get("area", ""))
            label = str(choice.get("label", "")) or area
            row = self._choice_table.rowCount()
            self._choice_table.insertRow(row)
            area_item = QTableWidgetItem(label)
            area_item.setToolTip(area)
            if area == selected_area:
                area_item.setForeground(QColor("#059669"))
                font = area_item.font()
                font.setBold(True)
                area_item.setFont(font)
            self._choice_table.setItem(row, 0, area_item)
            self._choice_table.setItem(row, 1, QTableWidgetItem(str(choice.get("row_count", 0))))
            self._choice_table.setItem(row, 2, QTableWidgetItem(str(choice.get("raw_count", 0))))
            self._choice_table.setItem(row, 3, QTableWidgetItem(str(choice.get("sample_raw", ""))))

            action_widget = QWidget()
            action_lay = QHBoxLayout(action_widget)
            action_lay.setContentsMargins(0, 0, 0, 0)
            action_lay.setSpacing(4)
            btn = QPushButton("選定")
            btn.setToolTip("只選定目前這個流水號")
            btn.clicked.connect(lambda checked, a=area: self._choose_area(a))
            action_lay.addWidget(btn)
            btn_all = QPushButton("同值全套")
            btn_all.setToolTip(f"套用 {area_col}={area} 到所有有此選項的流水號")
            btn_all.clicked.connect(
                lambda checked, col=area_col, a=area: self._choose_area_for_all(col, a)
            )
            action_lay.addWidget(btn_all)
            self._choice_table.setCellWidget(row, 4, action_widget)
        self._refresh_status()

    def _choose_area(self, area: str) -> None:
        group = self._groups[self._current_idx]
        spool = str(group.get("spool", ""))
        area_col = str(group.get("area_col", "ParentArea"))
        if spool and area:
            self._decisions[spool] = {
                "area_col": area_col,
                "area": area,
            }
            item = self._spool_list.item(self._current_idx)
            if item:
                item.setText(f"{spool}  ->  {area_col}={area}")
                item.setForeground(QColor("#059669"))
        self._load_group(self._current_idx)

    def _choose_area_for_all(self, area_col: str, area: str) -> None:
        updates = build_common_decisions(self._groups, area_col, area)
        if not updates:
            return
        reply = QMessageBox.question(
            self,
            "批次套用決策",
            (
                f"將 {area_col}={area} 套用到 {len(updates)} 個流水號。\n\n"
                "這只會先預選，按「套用決策」後才會寫回檔案。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._decisions.update(updates)
        for i, group in enumerate(self._groups):
            spool = str(group.get("spool", "")).strip()
            decision = self._decisions.get(spool, {})
            if isinstance(decision, dict) and str(decision.get("area", "")).strip():
                item = self._spool_list.item(i)
                if item:
                    item.setText(
                        f"{spool}  ->  {decision.get('area_col')}={decision.get('area')}"
                    )
                    item.setForeground(QColor("#059669"))
        self._load_group(self._current_idx)

    def _refresh_status(self) -> None:
        self._lbl_status.setText(
            f"已選 {len(self._decisions)} / {len(self._groups)}"
        )

    def _open_current_investigation(self) -> None:
        if not self._groups:
            return
        spool = str(self._groups[self._current_idx].get("spool", "")).strip()
        paths_getter = getattr(self.parent(), "_get_investigation_paths", None)
        if callable(paths_getter):
            dlg = IdentityInspectorDialog(self, paths_getter, spool)
            dlg.exec()
            return
        opener = getattr(self.parent(), "open_identity_inspector", None)
        if callable(opener):
            opener(spool)

    def get_decisions(self) -> dict[str, str]:
        return dict(self._decisions)
