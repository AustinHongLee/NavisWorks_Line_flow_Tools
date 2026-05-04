# -*- coding: utf-8 -*-
"""Trace 視覺化彈窗。"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from utils.trace_builder import parse_trace


def _group_name(key: str) -> str:
    key_l = key.lower()
    if key_l in {"raw", "source", "path", "level", "pattern_check"}:
        return "來源"
    if key_l in {"normalized", "strip_prefix", "slash_truncate"} or "size_norm" in key_l:
        return "規範化"
    if key_l in {"match", "iso_key", "attempts"}:
        return "比對"
    if key_l in {"score", "reason", "candidate", "candidate_count"}:
        return "評分"
    return "其他"


class TraceViewerDialog(QDialog):
    """把 ``IdentityReason`` 的 trace 字串顯示成分段時間軸。"""

    def __init__(
        self,
        parent,
        spool_no: str = "",
        pipe_code: str = "",
        trace_str: str = "",
        on_copy: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self._trace_str = "" if trace_str is None else str(trace_str)
        self._on_copy = on_copy
        self.setWindowTitle("Trace 追蹤")
        self.setMinimumSize(620, 460)
        self.resize(760, 560)
        self._build_ui(str(spool_no or ""), str(pipe_code or ""))

    def _build_ui(self, spool_no: str, pipe_code: str) -> None:
        self.setStyleSheet(
            "QDialog { background: #FFFFFF; color: #1E293B; }"
            "QLabel { color: #1E293B; }"
            "QPushButton { background: #FFFFFF; color: #2563EB;"
            " border: 1px solid #BFDBFE; border-radius: 6px;"
            " padding: 6px 14px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #EFF6FF; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("Trace 追蹤")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")
        root.addWidget(title)

        subtitle = QLabel(
            f"流水號：{spool_no or '-'}    管線：{pipe_code or '-'}"
        )
        subtitle.setStyleSheet("font-size: 12px; color: #64748B;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        parts = parse_trace(self._trace_str)
        if not parts:
            empty = QLabel("這筆資料沒有 trace。")
            empty.setStyleSheet("color: #94A3B8; font-size: 13px;")
            lay.addWidget(empty)
        else:
            groups: dict[str, list[tuple[str, str, str]]] = {}
            for kind, key, value in parts:
                groups.setdefault(_group_name(key), []).append((kind, key, value))
            for group in ["來源", "規範化", "比對", "評分", "其他"]:
                entries = groups.get(group, [])
                if entries:
                    lay.addWidget(self._make_group(group, entries))
        lay.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy = QPushButton("複製 trace")
        btn_copy.clicked.connect(self._copy_trace)
        btn_row.addWidget(btn_copy)
        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _make_group(
        self,
        title: str,
        entries: list[tuple[str, str, str]],
    ) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #F8FAFC; border: 1px solid #E2E8F0;"
            " border-radius: 8px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #1E293B;")
        lay.addWidget(lbl)
        for kind, key, value in entries:
            text = f"{key} = {value}" if kind == "kv" else f"{key}: {value}"
            row = QLabel(text)
            row.setWordWrap(True)
            row.setTextInteractionFlags(
                row.textInteractionFlags()
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            row.setStyleSheet(
                "font-size: 12px; color: #334155; padding: 2px 0;"
            )
            lay.addWidget(row)
        return frame

    def _copy_trace(self) -> None:
        QApplication.clipboard().setText(self._trace_str)
        if self._on_copy:
            self._on_copy(self._trace_str)
