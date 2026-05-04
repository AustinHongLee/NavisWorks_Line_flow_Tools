# -*- coding: utf-8 -*-
"""身份調查器：跨中間檔查看 ISO/3D 線索。"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.identity_investigator import InvestigationPaths, investigate_identity
from gui.dialogs.trace_viewer_dialog import TraceViewerDialog


def _make_table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(
        "QTableWidget { background: #FFFFFF; color: #0F172A;"
        " border: 1px solid #CBD5E1; border-radius: 6px; gridline-color: #E2E8F0; }"
        "QHeaderView::section { background: #F8FAFC; color: #334155;"
        " border: 0; border-bottom: 1px solid #CBD5E1; padding: 6px;"
        " font-weight: 700; }"
        "QTableWidget::item { padding: 4px; }"
        "QTableWidget::item:selected { background: #DBEAFE; color: #0F172A; }"
    )
    return table


def _fill_table(table: QTableWidget, rows: list[dict[str, str]]) -> None:
    columns = [
        table.horizontalHeaderItem(i).text()
        for i in range(table.columnCount())
    ]
    table.setRowCount(len(rows))
    for r, record in enumerate(rows):
        for c, col in enumerate(columns):
            item = QTableWidgetItem(str(record.get(col, "")))
            item.setToolTip(str(record.get(col, "")))
            table.setItem(r, c, item)
    table.resizeColumnsToContents()


class IdentityInspectorWidget(QWidget):
    """可嵌入 tab 或 dialog 的 read-only 調查器。"""

    def __init__(
        self,
        parent,
        paths_getter: Callable[[], InvestigationPaths],
        initial_query: str = "",
    ):
        super().__init__(parent)
        self._paths_getter = paths_getter
        self._last_result: dict[str, Any] = {}
        self._build_ui()
        if initial_query:
            self.set_query(initial_query)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            "QWidget { background: #FFFFFF; color: #0F172A; }"
            "QLabel { color: #0F172A; }"
            "QLineEdit { background: #FFFFFF; color: #0F172A;"
            " border: 1px solid #CBD5E1; border-radius: 6px;"
            " padding: 7px 10px; font-size: 13px; }"
            "QPushButton { background: #2563EB; color: #FFFFFF;"
            " border: 1px solid #1D4ED8; border-radius: 6px;"
            " padding: 7px 14px; font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background: #1D4ED8; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("調查")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        header.addWidget(title)
        self.txt_query = QLineEdit()
        self.txt_query.setPlaceholderText("輸入 ISO 管線、流水號、3D Raw、PipelineId，例如 TRIM-6FL216Q-N3-001")
        self.txt_query.returnPressed.connect(self.search)
        header.addWidget(self.txt_query, stretch=1)
        btn = QPushButton("搜尋")
        btn.clicked.connect(self.search)
        header.addWidget(btn)
        root.addLayout(header)

        self.lbl_status = QLabel("輸入關鍵字後搜尋。")
        self.lbl_status.setStyleSheet("color: #64748B; font-size: 12px;")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(self._build_family_panel())
        self.tbl_iso = _make_table([
            "流水號",
            "管線編號",
            "ISO_Match_Key",
            "Raw_3D_PipeCode",
            "Resolved",
            "ResolutionStatus",
            "MatchType",
            "MatchScore",
            "NeedsDecision",
        ])
        top_splitter.addWidget(self._wrap_table("ISO / resolved_mapping", self.tbl_iso))
        top_splitter.setSizes([360, 720])
        root.addWidget(top_splitter, stretch=2)

        bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        self.tbl_level = _make_table([
            "Level",
            "筆數",
            "Raw_3D_PipeCode",
            "ISO_Match_Key",
            "ScopeRoot",
            "ParentArea",
            "MatchSource",
        ])
        bottom_splitter.addWidget(self._wrap_table("3D Level 命中摘要", self.tbl_level))

        self.tbl_minus = _make_table([
            "Level",
            "Raw_3D_PipeCode",
            "ISO_Match_Key",
            "DisplayName",
            "PipelineId",
            "ScopeRoot",
            "ParentArea",
            "MatchSource",
            "ConfidencePrimary",
            "IdentityReason",
        ])
        self.tbl_minus.itemDoubleClicked.connect(self._open_trace_from_minus)
        bottom_splitter.addWidget(self._wrap_table("123_minus_1.csv 命中列（雙擊看 trace）", self.tbl_minus))

        self.tbl_first = _make_table(["Path", "DisplayName", "Class", "Level", "PipelineId"])
        bottom_splitter.addWidget(self._wrap_table("First_try.csv 原始命中列", self.tbl_first))
        bottom_splitter.setSizes([120, 260, 220])
        root.addWidget(bottom_splitter, stretch=5)

    def _build_family_panel(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #F8FAFC; border: 1px solid #CBD5E1;"
            " border-radius: 8px; }"
            "QLabel { background: transparent; }"
        )
        lay = QGridLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(6)
        self._family_labels: dict[str, QLabel] = {}
        rows = [
            ("query", "查詢"),
            ("normalized", "normalize_line_v2"),
            ("normalize_events", "正規化事件"),
            ("drop_last", "去末段"),
            ("series_prefix", "系列前綴"),
            ("strict_3d_count", "strict 3D 命中"),
            ("drop_last_3d_count", "去末段命中"),
            ("series_3d_count", "系列命中"),
            ("iso_hit_count", "ISO 命中列"),
            ("minus1_hit_count", "minus_1 命中列"),
            ("first_try_hit_count", "First_try 命中列"),
        ]
        title = QLabel("身份家族")
        title.setStyleSheet("font-size: 15px; font-weight: 800; color: #0F172A;")
        lay.addWidget(title, 0, 0, 1, 2)
        for i, (key, label) in enumerate(rows, start=1):
            name = QLabel(label)
            name.setStyleSheet("color: #475569; font-size: 12px; font-weight: 700;")
            lay.addWidget(name, i, 0)
            value = QLabel("-")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                value.textInteractionFlags()
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value.setStyleSheet("color: #0F172A; font-size: 12px;")
            lay.addWidget(value, i, 1)
            self._family_labels[key] = value
        return frame

    def _wrap_table(self, title: str, table: QTableWidget) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #FFFFFF; border: 0; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #1E293B;")
        lay.addWidget(lbl)
        lay.addWidget(table)
        return frame

    def set_query(self, query: str) -> None:
        self.txt_query.setText(str(query or ""))
        self.search()

    def search(self) -> None:
        query = self.txt_query.text().strip()
        if not query:
            return
        try:
            result = investigate_identity(query, self._paths_getter())
        except Exception as exc:
            QMessageBox.warning(self, "調查失敗", str(exc))
            return
        self._last_result = result
        family = result.get("family", {})
        for key, lbl in self._family_labels.items():
            lbl.setText(str(family.get(key, "-") or "-"))
        _fill_table(self.tbl_iso, result.get("iso_rows", []))
        _fill_table(self.tbl_level, result.get("level_summary", []))
        _fill_table(self.tbl_minus, result.get("minus1_rows", []))
        _fill_table(self.tbl_first, result.get("first_try_rows", []))
        self.lbl_status.setText(
            "結果："
            f"ISO {family.get('iso_hit_count', '0')} 列，"
            f"minus_1 {family.get('minus1_hit_count', '0')} 列，"
            f"First_try {family.get('first_try_hit_count', '0')} 列。"
        )

    def _open_trace_from_minus(self, item: QTableWidgetItem) -> None:
        row = item.row()
        trace_col = self._column_index(self.tbl_minus, "IdentityReason")
        raw_col = self._column_index(self.tbl_minus, "Raw_3D_PipeCode")
        key_col = self._column_index(self.tbl_minus, "ISO_Match_Key")
        trace = self.tbl_minus.item(row, trace_col).text() if trace_col >= 0 and self.tbl_minus.item(row, trace_col) else ""
        raw = self.tbl_minus.item(row, raw_col).text() if raw_col >= 0 and self.tbl_minus.item(row, raw_col) else ""
        key = self.tbl_minus.item(row, key_col).text() if key_col >= 0 and self.tbl_minus.item(row, key_col) else ""
        dlg = TraceViewerDialog(self, spool_no="", pipe_code=key or raw, trace_str=trace)
        dlg.exec()

    @staticmethod
    def _column_index(table: QTableWidget, name: str) -> int:
        for i in range(table.columnCount()):
            if table.horizontalHeaderItem(i).text() == name:
                return i
        return -1


class IdentityInspectorDialog(QDialog):
    """獨立彈窗版本，供 fuzzy/collision 等視窗跳轉使用。"""

    def __init__(
        self,
        parent,
        paths_getter: Callable[[], InvestigationPaths],
        initial_query: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("身份調查")
        self.setMinimumSize(1100, 760)
        self.resize(1320, 860)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inspector = IdentityInspectorWidget(self, paths_getter, initial_query)
        lay.addWidget(self.inspector)
