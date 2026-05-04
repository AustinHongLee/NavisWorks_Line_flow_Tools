# -*- coding: utf-8 -*-
"""模糊比對互動對話框。

當 Step3 嚴謹/去尺寸比對仍有未配對的 ISO 行時，
顯示此對話框讓使用者手動選擇 3D 候選。
"""
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
)


class FuzzyMatchDialog(QDialog):
    """每條 ISO 行列出候選 3D 線（依命中機率排序），
    使用者可選擇配對或跳過。完成後回傳 selections。
    """

    def __init__(self, parent, unmatched: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("模糊比對 — 手動確認")
        self.setMinimumSize(950, 550)
        self.resize(1050, 620)
        self.setModal(True)

        self._unmatched = unmatched
        self._selections: list[dict] = []
        self._current_idx = 0

        self._apply_dialog_style()
        self._build_ui()
        self._load_item(0)

    def _apply_dialog_style(self):
        """設定對話框局部樣式，確保白底深字在所有子元件正確顯示。"""
        self.setStyleSheet("""
            FuzzyMatchDialog {
                background: #FFFFFF;
                color: #1E293B;
            }
            QLabel {
                color: #1E293B;
            }
            QListWidget {
                background: #F9FAFB;
                color: #1E293B;
                border: 1.5px solid #D1D5DB;
                border-radius: 8px;
                padding: 4px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 5px 8px;
                border-radius: 4px;
                color: #1E293B;
            }
            QListWidget::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
            QListWidget::item:hover:!selected {
                background: #F8FAFC;
            }
            QTableWidget {
                background: #FFFFFF;
                color: #1E293B;
                border: 1.5px solid #D1D5DB;
                border-radius: 8px;
                gridline-color: #E2E8F0;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 4px 8px;
                color: #1E293B;
            }
            QTableWidget::item:selected {
                background: #EFF6FF;
                color: #1D4ED8;
            }
            QHeaderView::section {
                background: #F8FAFC;
                color: #475569;
                border: none;
                border-bottom: 1.5px solid #E2E8F0;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton {
                background: #FFFFFF;
                color: #475569;
                border: 1.5px solid #D1D5DB;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #F8FAFC;
                border-color: #94A3B8;
                color: #1E293B;
            }
            QPushButton[class="btn-select"] {
                background: #2563EB;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
                min-width: 56px;
            }
            QPushButton[class="btn-select"]:hover {
                background: #1D4ED8;
            }
            QPushButton[class="btn-select"]:pressed {
                background: #1E40AF;
            }
        """)

    # ── UI ──

    def _build_ui(self):
        root = QVBoxLayout(self)

        header = QLabel(
            f"共 <b>{len(self._unmatched)}</b> 條 ISO 管線尚未配對。"
            "請依序選擇最合適的 3D 候選線，或按「跳過」略過此行。"
        )
        header.setWordWrap(True)
        header.setStyleSheet(
            "font-size: 13px; margin-bottom: 6px; color: #1E293B;"
        )
        root.addWidget(header)

        self._lbl_progress = QLabel()
        self._lbl_progress.setStyleSheet(
            "font-size: 11px; color: #475569;"
        )
        root.addWidget(self._lbl_progress)

        mid = QHBoxLayout()

        # 左側：ISO 行列表
        left = QVBoxLayout()
        left.addWidget(QLabel("ISO 管線（未配對）："))
        self._iso_list = QListWidget()
        self._iso_list.setFixedWidth(280)
        for item in self._unmatched:
            text = f"{item['iso_line']}"
            if item["iso_spool"]:
                text += f"  (流水號 {item['iso_spool']})"
            self._iso_list.addItem(text)
        self._iso_list.currentRowChanged.connect(self._on_iso_row_changed)
        left.addWidget(self._iso_list)
        mid.addLayout(left)

        # 右側：候選 3D 線表格
        right = QVBoxLayout()
        right.addWidget(QLabel("3D 候選線（命中機率高→低）："))
        self._cand_table = QTableWidget()
        self._cand_table.setColumnCount(4)
        self._cand_table.verticalHeader().setVisible(False)
        self._cand_table.setHorizontalHeaderLabels(
            ["3D Line", "機率", "原因", "操作"]
        )
        self._cand_table.horizontalHeader().setStretchLastSection(False)
        self._cand_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._cand_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._cand_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._cand_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Fixed
        )
        self._cand_table.horizontalHeader().resizeSection(3, 80)
        self._cand_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._cand_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        right.addWidget(self._cand_table)

        self._lbl_no_cand = QLabel("此 ISO 行在 3D 端找不到任何候選。")
        self._lbl_no_cand.setStyleSheet("color: #DC2626; font-size: 11px;")
        self._lbl_no_cand.setVisible(False)
        right.addWidget(self._lbl_no_cand)

        mid.addLayout(right, stretch=1)
        root.addLayout(mid, stretch=1)

        # 底部按鈕列
        btn_row = QHBoxLayout()
        self._btn_accept_all = QPushButton("全部接受高信賴 (≥90%)")
        self._btn_accept_all.setStyleSheet(
            "background-color: #16A34A; color: white; padding: 6px 14px;"
            " border: none; border-radius: 6px; font-weight: 600;"
        )
        self._btn_accept_all.clicked.connect(self._accept_all_high)
        btn_row.addWidget(self._btn_accept_all)

        btn_row.addStretch()

        self._btn_skip = QPushButton("跳過此行")
        self._btn_skip.clicked.connect(self._skip_current)
        btn_row.addWidget(self._btn_skip)

        self._btn_finish = QPushButton("完成（套用已選）")
        self._btn_finish.setStyleSheet(
            "background-color: #2563EB; color: white; padding: 6px 14px;"
            " border: none; border-radius: 6px; font-weight: 600;"
        )
        self._btn_finish.clicked.connect(self._finish)
        btn_row.addWidget(self._btn_finish)

        root.addLayout(btn_row)

    # ── 載入 ──

    def _load_item(self, idx: int):
        if idx < 0 or idx >= len(self._unmatched):
            return
        self._current_idx = idx
        self._iso_list.blockSignals(True)
        self._iso_list.setCurrentRow(idx)
        self._iso_list.blockSignals(False)

        item = self._unmatched[idx]
        cands = item.get("candidates", [])
        self._lbl_progress.setText(
            f"目前：第 {idx + 1} / {len(self._unmatched)} 條　"
            f"ISO = {item['iso_line']}"
        )

        self._cand_table.setRowCount(0)
        self._lbl_no_cand.setVisible(len(cands) == 0)

        for i, cand in enumerate(cands):
            row_idx = self._cand_table.rowCount()
            self._cand_table.insertRow(row_idx)
            self._cand_table.setItem(
                row_idx, 0, QTableWidgetItem(cand["line_3d"])
            )
            score_pct = f"{cand['score']:.0%}"
            score_item = QTableWidgetItem(score_pct)
            if cand["score"] >= 0.9:
                score_item.setForeground(QColor("#16A34A"))
            elif cand["score"] >= 0.6:
                score_item.setForeground(QColor("#CA8A04"))
            else:
                score_item.setForeground(QColor("#DC2626"))
            self._cand_table.setItem(row_idx, 1, score_item)
            self._cand_table.setItem(
                row_idx, 2, QTableWidgetItem(cand.get("reason", ""))
            )
            btn = QPushButton("選擇")
            btn.setProperty("class", "btn-select")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, ii=i: self._select_candidate(ii)
            )
            self._cand_table.setCellWidget(row_idx, 3, btn)
            self._cand_table.setRowHeight(row_idx, 38)

    def _on_iso_row_changed(self, row: int):
        if 0 <= row < len(self._unmatched):
            self._load_item(row)

    # ── 操作 ──

    def _select_candidate(self, cand_idx: int):
        item = self._unmatched[self._current_idx]
        cands = item.get("candidates", [])
        if cand_idx < 0 or cand_idx >= len(cands):
            return
        cand = cands[cand_idx]
        self._selections.append({
            "iso_line": item["iso_line"],
            "iso_spool": item["iso_spool"],
            "line_3d": cand["line_3d"],
            "raw_3d": cand.get("raw_3d", cand["line_3d"]),
        })
        list_item = self._iso_list.item(self._current_idx)
        if list_item:
            list_item.setText(list_item.text() + "  ✓ " + cand["line_3d"])
            list_item.setForeground(QColor("#16A34A"))
        self._advance()

    def _skip_current(self):
        list_item = self._iso_list.item(self._current_idx)
        if list_item:
            list_item.setText(list_item.text() + "  ⊘ 已跳過")
            list_item.setForeground(QColor("#94A3B8"))
        self._advance()

    def _advance(self):
        nxt = self._current_idx + 1
        if nxt < len(self._unmatched):
            self._load_item(nxt)
        else:
            self._lbl_progress.setText(
                f"已完成全部 {len(self._unmatched)} 條，"
                f"已選定 {len(self._selections)} 對配對。"
            )

    def _accept_all_high(self):
        """自動接受所有 ≥90% 信賴度的第一候選。"""
        count = 0
        already = {s["iso_line"] for s in self._selections}
        for idx, item in enumerate(self._unmatched):
            if item["iso_line"] in already:
                continue
            cands = item.get("candidates", [])
            if cands and cands[0]["score"] >= 0.9:
                self._selections.append({
                    "iso_line": item["iso_line"],
                    "iso_spool": item["iso_spool"],
                    "line_3d": cands[0]["line_3d"],
                    "raw_3d": cands[0].get("raw_3d", cands[0]["line_3d"]),
                })
                list_item = self._iso_list.item(idx)
                if list_item:
                    list_item.setText(
                        list_item.text() + "  ✓ " + cands[0]["line_3d"]
                    )
                    list_item.setForeground(QColor("#16A34A"))
                count += 1
        QMessageBox.information(
            self, "批次接受",
            f"已自動選定 {count} 對高信賴配對。",
        )

    def _finish(self):
        self.accept()

    def get_selections(self) -> list[dict]:
        return self._selections
