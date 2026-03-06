# -*- coding: utf-8 -*-
"""IsoSetupDialog — ISO LIST 欄位設定對話框。

在 Navisworks 啟動模式中，於工作區建立後彈出，
讓使用者選擇工作表與對應欄位（管線、流水號、分類）。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class IsoSetupDialog(QDialog):
    """ISO LIST 工作表 / 欄位設定。"""

    def __init__(self, parent, iso_path: str):
        super().__init__(parent)
        self.setWindowTitle("ISO LIST 設定")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._iso_path = iso_path

        # ── 結果 ──
        self.iso_sheet: str = ""
        self.pipe_col: str = ""
        self.spool_col: str = ""
        self.category_col: str = "發包分類"

        self._build_ui()
        self._load_sheets()

    # ────────────────────────────────────────
    #  UI
    # ────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        title = QLabel("🔗 ISO LIST 欄位設定")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        lay.addWidget(title)

        desc = QLabel(
            "請確認工作表與欄位對應是否正確，\n"
            "系統已自動偵測最可能的選項。"
        )
        desc.setStyleSheet("color: #6B7280; font-size: 12px;")
        lay.addWidget(desc)
        lay.addSpacing(4)

        # 工作表
        lay.addWidget(self._make_label("工作表"))
        self.cbo_sheet = QComboBox()
        self.cbo_sheet.setMinimumHeight(36)
        self.cbo_sheet.setEditable(True)
        self.cbo_sheet.currentTextChanged.connect(self._on_sheet_changed)
        lay.addWidget(self.cbo_sheet)

        # 管線欄位
        lay.addWidget(self._make_label("管線欄位"))
        self.cbo_pipe = QComboBox()
        self.cbo_pipe.setMinimumHeight(36)
        self.cbo_pipe.setEditable(True)
        lay.addWidget(self.cbo_pipe)

        # 流水號欄位
        lay.addWidget(self._make_label("流水號欄位"))
        self.cbo_spool = QComboBox()
        self.cbo_spool.setMinimumHeight(36)
        self.cbo_spool.setEditable(True)
        lay.addWidget(self.cbo_spool)

        # 分類欄位
        lay.addWidget(self._make_label("分類欄位"))
        self.cbo_category = QComboBox()
        self.cbo_category.setMinimumHeight(36)
        self.cbo_category.setEditable(True)
        self.cbo_category.setEditText("發包分類")
        lay.addWidget(self.cbo_category)

        lay.addSpacing(10)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("確定")
        btn_ok.setProperty("class", "btn-primary")
        btn_ok.setFixedHeight(36)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    @staticmethod
    def _make_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #374151;"
        )
        return lbl

    # ────────────────────────────────────────
    #  Sheet loading & scoring
    # ────────────────────────────────────────

    def _load_sheets(self):
        try:
            self._xls = pd.ExcelFile(self._iso_path, engine="openpyxl")
            self.cbo_sheet.addItems(self._xls.sheet_names)
            if self._xls.sheet_names:
                best = self._pick_best_sheet(self._xls)
                self.cbo_sheet.setCurrentText(best)
        except Exception as e:
            QMessageBox.warning(self, "讀取失敗", f"無法讀取 ISO LIST：\n{e}")

    @staticmethod
    def _score_sheet(xls: pd.ExcelFile, name: str) -> int:
        try:
            df = pd.read_excel(
                xls, sheet_name=name, nrows=0,
                dtype=str, engine="openpyxl",
            )
            cols = [
                str(c).strip().lower()
                for c in df.columns if str(c).strip()
            ]
        except Exception:
            return -1

        has_pipe = any(
            "管線" in c or "line" in c or "pipe" in c for c in cols
        )
        has_spool = any(
            "流水" in c or "spool" in c or "series" in c for c in cols
        )
        score = int(has_pipe) * 2 + int(has_spool)
        if "drawing" in name.lower():
            score += 1
        return score

    def _pick_best_sheet(self, xls: pd.ExcelFile) -> str:
        best_name = xls.sheet_names[0]
        best_score = -1
        for name in xls.sheet_names:
            s = self._score_sheet(xls, name)
            if s > best_score:
                best_score = s
                best_name = name
        return best_name

    # ────────────────────────────────────────
    #  Column auto-detection
    # ────────────────────────────────────────

    def _on_sheet_changed(self, sheet: str):
        if not sheet:
            return
        try:
            df = pd.read_excel(
                self._iso_path, sheet_name=sheet, nrows=5,
                dtype=str, engine="openpyxl",
            )
            cols = [str(c).strip() for c in df.columns if str(c).strip()]
        except Exception:
            return
        if not cols:
            return

        for cbo in (self.cbo_pipe, self.cbo_spool, self.cbo_category):
            cbo.clear()
            cbo.addItems(cols)

        # ── 管線欄位偵測 ──
        pipe_col = self._detect_pipe_col(cols)
        if pipe_col:
            self.cbo_pipe.setCurrentText(pipe_col)

        # ── 流水號欄位偵測 ──
        spool_col = self._detect_spool_col(cols)
        if spool_col:
            self.cbo_spool.setCurrentText(spool_col)

        # ── 分類欄位偵測 ──
        if "發包分類" in cols:
            self.cbo_category.setCurrentText("發包分類")
        else:
            cat = next(
                (c for c in cols
                 if "分類" in c or "category" in c.lower()),
                None,
            )
            if cat:
                self.cbo_category.setCurrentText(cat)
            else:
                self.cbo_category.setEditText("發包分類")

    @staticmethod
    def _detect_pipe_col(cols: list[str]) -> Optional[str]:
        precise = {"line_no", "line no", "管線號", "管線編號",
                   "line number", "pipe no"}
        for c in cols:
            if c.lower().strip() in precise:
                return c
        skip = {"管線材質", "管線等級"}
        for c in cols:
            if c in skip:
                continue
            cl = c.lower()
            if "管線" in cl or "line" in cl or "pipe" in cl:
                return c
        return None

    @staticmethod
    def _detect_spool_col(cols: list[str]) -> Optional[str]:
        precise = {"流水號", "series no", "spool no"}
        for c in cols:
            if c.lower().strip() in precise:
                return c
        for c in cols:
            cl = c.lower()
            if "流水" in cl or "spool" in cl or "series" in cl:
                return c
        return None

    # ────────────────────────────────────────
    #  Confirm
    # ────────────────────────────────────────

    def _on_confirm(self):
        sheet = self.cbo_sheet.currentText().strip()
        pipe = self.cbo_pipe.currentText().strip()
        spool = self.cbo_spool.currentText().strip()

        if not sheet:
            QMessageBox.warning(self, "提示", "請選擇工作表。")
            return
        if not pipe:
            QMessageBox.warning(self, "提示", "請選擇管線欄位。")
            return
        if not spool:
            QMessageBox.warning(self, "提示", "請選擇流水號欄位。")
            return
        if pipe == spool:
            QMessageBox.warning(self, "提示", "管線欄位與流水號欄位不可相同。")
            return

        self.iso_sheet = sheet
        self.pipe_col = pipe
        self.spool_col = spool
        self.category_col = (
            self.cbo_category.currentText().strip() or "發包分類"
        )
        self.accept()
