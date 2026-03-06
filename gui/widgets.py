# -*- coding: utf-8 -*-
"""共用 GUI 元件與工具函式。

提供 AnimatedStackedWidget、StepperBar、CollapsibleSection
以及 UI 工廠函式與檔案工具。
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import pandas as pd
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


# ============================================================
#  AnimatedStackedWidget — fade transition
# ============================================================

class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget with cross-fade page transition."""

    page_changed = pyqtSignal(int)

    def __init__(self, parent=None, duration: int = 150):
        super().__init__(parent)
        self._duration = duration
        self._busy = False
        self._anim_ref = None  # prevent GC

    def fade_to(self, index: int):
        if index == self.currentIndex() or self._busy:
            return
        if index < 0 or index >= self.count():
            return
        self._busy = True
        cur = self.currentWidget()
        if cur is None:
            self.setCurrentIndex(index)
            self._busy = False
            self.page_changed.emit(index)
            return

        eff = QGraphicsOpacityEffect(cur)
        cur.setGraphicsEffect(eff)
        fade_out = QPropertyAnimation(eff, b"opacity")
        fade_out.setDuration(self._duration)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _finish():
            cur.setGraphicsEffect(None)
            self.setCurrentIndex(index)
            nw = self.currentWidget()
            if nw is None:
                self._busy = False
                self.page_changed.emit(index)
                return
            eff2 = QGraphicsOpacityEffect(nw)
            nw.setGraphicsEffect(eff2)
            fade_in = QPropertyAnimation(eff2, b"opacity")
            fade_in.setDuration(self._duration)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InCubic)

            def _done():
                nw.setGraphicsEffect(None)
                self._busy = False
                self.page_changed.emit(index)

            fade_in.finished.connect(_done)
            self._anim_ref = fade_in
            fade_in.start()

        fade_out.finished.connect(_finish)
        self._anim_ref = fade_out
        fade_out.start()


# ============================================================
#  StepperBar — clickable horizontal stepper
# ============================================================

class StepperBar(QWidget):
    """Horizontal step indicator. Emits *step_clicked(int)*."""

    step_clicked = pyqtSignal(int)

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = 0
        self._items: list[QPushButton] = []
        self._conns: list[QFrame] = []
        self.setProperty("class", "stepper-bar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(0)
        lay.addStretch()
        for i, label in enumerate(steps):
            btn = QPushButton(f"  {i + 1}   {label}  ")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("step-state", "upcoming")
            btn.clicked.connect(
                lambda checked, idx=i: self.step_clicked.emit(idx)
            )
            lay.addWidget(btn)
            self._items.append(btn)
            if i < len(steps) - 1:
                conn = QFrame()
                conn.setProperty("class", "stepper-conn")
                conn.setFixedHeight(2)
                conn.setMinimumWidth(32)
                lay.addWidget(conn, stretch=1)
                self._conns.append(conn)
        lay.addStretch()
        self._refresh()

    def set_current(self, index: int):
        self._current = max(0, min(index, len(self._steps) - 1))
        self._refresh()

    def _refresh(self):
        for i, btn in enumerate(self._items):
            state = (
                "completed" if i < self._current
                else "active" if i == self._current
                else "upcoming"
            )
            btn.setProperty("step-state", state)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        for i, conn in enumerate(self._conns):
            st = "done" if i < self._current else "todo"
            conn.setProperty("state", st)
            conn.style().unpolish(conn)
            conn.style().polish(conn)


# ============================================================
#  CollapsibleSection
# ============================================================

class CollapsibleSection(QWidget):
    """標題列可展開/收合的容器。"""

    def __init__(self, title: str, parent=None, initially_open: bool = False):
        super().__init__(parent)
        self._title = title
        arrow = "▾" if initially_open else "▸"
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(f" {arrow}  {title}")
        self.toggle_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(initially_open)
        self.toggle_btn.setProperty("class", "collapsible-toggle")
        self.toggle_btn.toggled.connect(self._on_toggle)

        self.content = QWidget()
        self.content.setVisible(initially_open)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 8, 8, 8)
        self.content_layout.setSpacing(6)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.toggle_btn)
        lay.addWidget(self.content)

    def _on_toggle(self, checked: bool):
        self.content.setVisible(checked)
        arrow = "▾" if checked else "▸"
        self.toggle_btn.setText(f" {arrow}  {self._title}")

    def add_widget(self, w: QWidget):
        self.content_layout.addWidget(w)

    def add_layout(self, layout):
        self.content_layout.addLayout(layout)


# ============================================================
#  UI 工廠函式
# ============================================================

def make_card(accent: str = "card") -> Tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("class", accent)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(12)
    return card, lay


def make_separator() -> QFrame:
    sep = QFrame()
    sep.setProperty("class", "separator")
    sep.setFrameShape(QFrame.Shape.HLine)
    return sep


def make_field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "field-label")
    return lbl


def make_note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "note")
    lbl.setWordWrap(True)
    return lbl


def make_panel(accent: str = "panel-blue") -> Tuple[QFrame, QVBoxLayout]:
    panel = QFrame()
    panel.setProperty("class", accent)
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(12)
    return panel, lay


def make_section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section-header")
    return lbl


def make_section_desc(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section-desc")
    return lbl


# ── Badge helpers ──

def set_badge(lbl: QLabel, text: str, kind: str):
    """Set badge style: kind = 'ok' | 'err' | 'neutral'."""
    lbl.setText(text)
    lbl.setProperty("class", f"badge-{kind}")
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


def set_sidebar_badge(lbl: QLabel, text: str, kind: str):
    """Set sidebar status label: kind = 'ok' | 'err' | 'neutral' | 'ready'."""
    lbl.setText(text)
    lbl.setProperty("class", f"sb-{kind}")
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


# ============================================================
#  檔案工具函式
# ============================================================

def find_any_iso(base_dir: str) -> Optional[str]:
    if not os.path.isdir(base_dir):
        return None
    for f in os.listdir(base_dir):
        lower = f.lower()
        if ("iso" in lower or "drawing" in lower) and lower.endswith(
            (".xlsx", ".xlsm", ".xls")
        ):
            return os.path.join(base_dir, f)
    return None


def read_iso_match(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet = "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    return df
