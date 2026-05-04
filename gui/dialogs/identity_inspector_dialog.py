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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.identity_investigator import InvestigationPaths, investigate_identity
from gui.dialogs.trace_viewer_dialog import TraceViewerDialog


ROLE_RECORD = int(Qt.ItemDataRole.UserRole) + 10


def _style_for_table() -> str:
    return (
        "QTableWidget { background: #FFFFFF; color: #0F172A;"
        " border: 1px solid #E2E8F0; border-radius: 8px;"
        " gridline-color: #F1F5F9; alternate-background-color: #F8FAFC;"
        " selection-background-color: #DBEAFE; selection-color: #0F172A; }"
        "QHeaderView::section { background: #F8FAFC; color: #334155;"
        " border: 0; border-bottom: 1px solid #E2E8F0; padding: 7px 8px;"
        " font-weight: 700; font-size: 12px; }"
        "QTableWidget::item { padding: 5px 8px; border: 0; }"
        "QTableCornerButton::section { background: #F8FAFC; border: 0; }"
    )


def _make_table(columns: list[str], stretch_last: bool = True) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setStretchLastSection(stretch_last)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch_last and columns:
        table.horizontalHeader().setSectionResizeMode(
            len(columns) - 1,
            QHeaderView.ResizeMode.Stretch,
        )
    table.setStyleSheet(_style_for_table())
    return table


def _fill_table(table: QTableWidget, rows: list[dict[str, str]]) -> None:
    columns = [
        table.horizontalHeaderItem(i).text()
        for i in range(table.columnCount())
    ]
    table.setRowCount(len(rows))
    for r, record in enumerate(rows):
        for c, col in enumerate(columns):
            value = str(record.get(col, ""))
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            if c == 0:
                item.setData(ROLE_RECORD, record)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    if columns:
        table.horizontalHeader().setSectionResizeMode(
            len(columns) - 1,
            QHeaderView.ResizeMode.Stretch,
        )


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


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
        self._metric_labels: dict[str, QLabel] = {}
        self._family_labels: dict[str, QLabel] = {}
        self._build_ui()
        if initial_query:
            self.set_query(initial_query)

    def _build_ui(self) -> None:
        self.setObjectName("identityInspector")
        self.setStyleSheet(
            "#identityInspector { background: #F1F5F9; color: #0F172A; }"
            "#identityInspector QLabel { color: #0F172A; }"
            "#identityInspector QLineEdit { background: #FFFFFF; color: #0F172A;"
            " border: 1px solid #CBD5E1; border-radius: 7px;"
            " padding: 8px 11px; font-size: 13px; }"
            "#identityInspector QLineEdit:focus { border-color: #2563EB; }"
            "#identityInspector QPushButton { background: #2563EB; color: #FFFFFF;"
            " border: 1px solid #1D4ED8; border-radius: 7px;"
            " padding: 8px 16px; font-size: 13px; font-weight: 700; }"
            "#identityInspector QPushButton:hover { background: #1D4ED8; }"
            "#identityInspector QSplitter::handle { background: #E2E8F0; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        root.addWidget(self._build_command_bar())
        root.addWidget(self._build_metrics_row())

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setChildrenCollapsible(False)
        workbench.addWidget(self._build_left_column())
        workbench.addWidget(self._build_right_column())
        workbench.setSizes([390, 910])
        root.addWidget(workbench, stretch=1)

    def _build_command_bar(self) -> QWidget:
        frame = self._card("commandBar")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("身份調查")
        title.setStyleSheet("font-size: 21px; font-weight: 900; color: #0F172A;")
        title_box.addWidget(title)
        desc = QLabel("從一條 ISO、流水號或 3D Raw 回看 First_try / minus_1 / resolved_mapping 的證據鏈。")
        desc.setStyleSheet("font-size: 12px; color: #64748B;")
        desc.setWordWrap(True)
        title_box.addWidget(desc)
        lay.addLayout(title_box)

        self.txt_query = QLineEdit()
        self.txt_query.setPlaceholderText("例如 TRIM-6FL216Q-N3-001、流水號、/TRIM-6FL216Q-N3")
        self.txt_query.returnPressed.connect(self.search)
        lay.addWidget(self.txt_query, stretch=1)

        btn = QPushButton("搜尋")
        btn.setFixedWidth(96)
        btn.clicked.connect(self.search)
        lay.addWidget(btn)
        return frame

    def _build_metrics_row(self) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        for key, title, value, accent in [
            ("iso_hit_count", "ISO 命中", "0", "#2563EB"),
            ("minus1_hit_count", "minus_1 線索", "0", "#059669"),
            ("candidate_hit_count", "候選召回", "0", "#EA580C"),
            ("first_try_hit_count", "First_try 原始列", "0", "#7C3AED"),
            ("drop_last_3d_count", "去末段 3D 命中", "0", "#D97706"),
        ]:
            card = self._metric_card(title, value, accent)
            lay.addWidget(card, stretch=1)
            self._metric_labels[key] = card.findChild(QLabel, "metricValue")
        return row

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        lay = QVBoxLayout(column)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(self._build_family_card())
        lay.addWidget(self._build_level_card(), stretch=1)
        return column

    def _build_right_column(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        self.tbl_iso = _make_table([
            "流水號",
            "管線編號",
            "ResolutionStatus",
            "MatchType",
            "Raw_3D_PipeCode",
            "NeedsDecision",
        ])
        splitter.addWidget(self._section("ISO / resolved_mapping", self.tbl_iso))

        self.tbl_candidates = _make_table([
            "類型",
            "分數",
            "ISO候選",
            "3D Raw",
            "命中詞",
            "原因",
        ])
        splitter.addWidget(self._section("候選召回（candidates.csv）", self.tbl_candidates))

        self.tbl_minus = _make_table([
            "Level",
            "Raw_3D_PipeCode",
            "ISO_Match_Key",
            "DisplayName",
            "PipelineId",
            "ParentArea",
            "MatchSource",
            "ConfidencePrimary",
        ])
        self.tbl_minus.itemDoubleClicked.connect(self._open_trace_from_minus)
        splitter.addWidget(self._section("3D 證據列（雙擊看 trace）", self.tbl_minus))

        self.tbl_first = _make_table([
            "Level",
            "進 minus_1",
            "排除原因",
            "召回數",
            "最佳召回",
            "DisplayName",
            "PipelineId",
            "最佳候選",
            "Path",
        ])
        splitter.addWidget(self._section("First_try / trace 原始命中列", self.tbl_first))
        splitter.setSizes([130, 190, 260, 230])
        return splitter

    def _build_family_card(self) -> QWidget:
        frame = self._card("familyCard")
        lay = QGridLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(8)

        title = QLabel("身份家族")
        title.setStyleSheet("font-size: 15px; font-weight: 900; color: #0F172A;")
        lay.addWidget(title, 0, 0, 1, 2)

        rows = [
            ("normalized", "標準化"),
            ("drop_last", "去末段"),
            ("series_prefix", "系列前綴"),
            ("strict_3d_count", "strict 命中"),
            ("series_3d_count", "系列命中"),
            ("identity_index_hit_count", "索引命中"),
            ("first_try_source", "原始列來源"),
            ("normalize_events", "正規化事件"),
        ]
        for i, (key, label) in enumerate(rows, start=1):
            name = QLabel(label)
            name.setStyleSheet("color: #64748B; font-size: 12px; font-weight: 700;")
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

    def _build_level_card(self) -> QWidget:
        frame = self._card("levelCard")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("3D Level 摘要")
        title.setStyleSheet("font-size: 15px; font-weight: 900; color: #0F172A;")
        title_row.addWidget(title)
        title_row.addStretch()
        self.lbl_level_hint = QLabel("尚未搜尋")
        self.lbl_level_hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        title_row.addWidget(self.lbl_level_hint)
        lay.addLayout(title_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.level_list = QVBoxLayout(holder)
        self.level_list.setContentsMargins(0, 0, 0, 0)
        self.level_list.setSpacing(8)
        self.level_list.addWidget(self._empty_label("搜尋後會在這裡列出 Level 命中。"))
        self.level_list.addStretch()
        scroll.setWidget(holder)
        lay.addWidget(scroll)
        return frame

    def _section(self, title: str, table: QTableWidget) -> QWidget:
        frame = self._card("section")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 900; color: #1E293B;")
        lay.addWidget(label)
        lay.addWidget(table)
        return frame

    def _metric_card(self, title: str, value: str, accent: str) -> QFrame:
        card = self._card("metric")
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #E2E8F0;"
            " border-left: 4px solid " + accent + "; border-radius: 8px; }"
            "QLabel { background: transparent; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("font-size: 11px; font-weight: 800; color: #64748B;")
        lay.addWidget(t)
        v = QLabel(value)
        v.setObjectName("metricValue")
        v.setStyleSheet("font-size: 24px; font-weight: 900; color: #0F172A;")
        lay.addWidget(v)
        return card

    @staticmethod
    def _card(name: str) -> QFrame:
        card = QFrame()
        card.setObjectName(name)
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #E2E8F0;"
            " border-radius: 8px; }"
            "QLabel { background: transparent; border: 0; }"
        )
        return card

    @staticmethod
    def _empty_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            "color: #94A3B8; font-size: 12px; padding: 18px;"
            " border: 1px dashed #CBD5E1; border-radius: 8px; background: #F8FAFC;"
        )
        return label

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
        for key, lbl in self._metric_labels.items():
            lbl.setText(str(family.get(key, "0") or "0"))
        _fill_table(self.tbl_iso, self._compact_iso_rows(result.get("iso_rows", [])))
        _fill_table(
            self.tbl_candidates,
            self._compact_candidate_rows(result.get("candidate_rows", [])),
        )
        _fill_table(self.tbl_minus, self._compact_minus_rows(result.get("minus1_rows", [])))
        _fill_table(self.tbl_first, self._compact_first_rows(result.get("first_try_rows", [])))
        self._fill_level_cards(result.get("level_summary", []))

    def _fill_level_cards(self, rows: list[dict[str, str]]) -> None:
        _clear_layout(self.level_list)
        if not rows:
            self.lbl_level_hint.setText("0 筆")
            self.level_list.addWidget(self._empty_label("這次查詢沒有在 123_minus_1.csv 找到 3D Level 線索。"))
            self.level_list.addStretch()
            return
        self.lbl_level_hint.setText(f"{len(rows)} 個 Level")
        for record in rows:
            self.level_list.addWidget(self._level_chip(record))
        self.level_list.addStretch()

    def _level_chip(self, record: dict[str, str]) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #F8FAFC; border: 1px solid #E2E8F0;"
            " border-radius: 8px; }"
            "QLabel { background: transparent; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)

        head = QHBoxLayout()
        level = QLabel(f"Level {record.get('Level', '-')}")
        level.setStyleSheet("font-size: 14px; font-weight: 900; color: #2563EB;")
        head.addWidget(level)
        head.addStretch()
        count = QLabel(f"{record.get('筆數', '0')} 列")
        count.setStyleSheet(
            "background: #EFF6FF; color: #1D4ED8; border-radius: 10px;"
            " padding: 2px 8px; font-size: 11px; font-weight: 800;"
        )
        head.addWidget(count)
        lay.addLayout(head)

        raw = QLabel(record.get("Raw_3D_PipeCode", ""))
        raw.setWordWrap(True)
        raw.setTextInteractionFlags(raw.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        raw.setStyleSheet("font-size: 12px; color: #0F172A; font-weight: 700;")
        lay.addWidget(raw)

        meta = QLabel(
            f"{record.get('MatchSource', '-')}"
            f" · {record.get('ParentArea', '-') or record.get('ScopeRoot', '-')}"
        )
        meta.setWordWrap(True)
        meta.setStyleSheet("font-size: 11px; color: #64748B;")
        lay.addWidget(meta)
        return frame

    @staticmethod
    def _compact_iso_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        keys = ["流水號", "管線編號", "ResolutionStatus", "MatchType", "Raw_3D_PipeCode", "NeedsDecision"]
        return [{key: row.get(key, "") for key in keys} for row in rows]

    @staticmethod
    def _compact_minus_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        keys = [
            "Level",
            "Raw_3D_PipeCode",
            "ISO_Match_Key",
            "DisplayName",
            "PipelineId",
            "ParentArea",
            "MatchSource",
            "ConfidencePrimary",
        ]
        return [{**{key: row.get(key, "") for key in keys}, "_record": row} for row in rows]

    @staticmethod
    def _compact_candidate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {
                "類型": row.get("candidate_kind", ""),
                "分數": row.get("score", ""),
                "ISO候選": row.get("iso_candidate", ""),
                "3D Raw": row.get("raw", ""),
                "命中詞": row.get("matched_terms", ""),
                "原因": row.get("reason", ""),
            }
            for row in rows
        ]

    @staticmethod
    def _compact_first_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {
                "Level": row.get("Level", ""),
                "進 minus_1": row.get("included_in_minus_1", ""),
                "排除原因": row.get("exclude_reason", ""),
                "召回數": row.get("recall_candidate_count", ""),
                "最佳召回": row.get("best_recall_iso", ""),
                "DisplayName": row.get("DisplayName", ""),
                "PipelineId": row.get("PipelineId", ""),
                "最佳候選": row.get("best_candidate_normalized", ""),
                "Path": row.get("Path", ""),
            }
            for row in rows
        ]

    def _open_trace_from_minus(self, item: QTableWidgetItem) -> None:
        row = item.row()
        record = None
        first_item = self.tbl_minus.item(row, 0)
        if first_item is not None:
            record = first_item.data(ROLE_RECORD)
        record = record if isinstance(record, dict) else {}
        source = record.get("_record", record)
        trace = str(source.get("IdentityReason", ""))
        raw = str(source.get("Raw_3D_PipeCode", ""))
        key = str(source.get("ISO_Match_Key", ""))
        dlg = TraceViewerDialog(self, spool_no="", pipe_code=key or raw, trace_str=trace)
        dlg.exec()


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
        self.setMinimumSize(1180, 760)
        self.resize(1360, 880)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inspector = IdentityInspectorWidget(self, paths_getter, initial_query)
        lay.addWidget(self.inspector)
