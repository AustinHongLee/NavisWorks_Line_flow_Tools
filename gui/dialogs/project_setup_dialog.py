# -*- coding: utf-8 -*-
"""ProjectSetupDialog — Navisworks 啟動模式的專案初始化對話框。

流程：
  1. 顯示自動建立的專案工作區路徑
  2. 顯示 First_try 來源路徑（由 Navisworks 傳入）
  3. 使用者瀏覽選擇 ISO LIST 檔案
  4. 確定後：建立工作區、複製並更名兩個檔案
"""
from __future__ import annotations

import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


_PROJECT_FOLDER_NAME = "Pipeline_Workspace"


class ProjectSetupDialog(QDialog):
    """Navisworks 啟動模式：建立工作區並匯入 First_try / ISO LIST。"""

    def __init__(
        self,
        parent,
        dlldir: str,
        first_try_source: str,
    ):
        super().__init__(parent)
        self.setWindowTitle("專案初始化")
        self.setMinimumWidth(620)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._dlldir = dlldir
        self._first_try_source = first_try_source
        self._project_dir = os.path.join(dlldir, _PROJECT_FOLDER_NAME)

        # ── 結果（accept 後可讀取） ──
        self.project_dir: str = ""
        self.iso_list_dest: str = ""

        self._build_ui()

    # ────────────────────────────────────────
    #  UI
    # ────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(20, 20, 20, 20)

        # 標題
        title = QLabel("📁 專案初始化設定")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        lay.addWidget(title)

        desc = QLabel(
            "系統將在 DLL 目錄下建立工作區資料夾，\n"
            "並將 First_try 與 ISO LIST 複製到工作區中。"
        )
        desc.setStyleSheet("color: #6B7280; font-size: 12px;")
        lay.addWidget(desc)

        lay.addSpacing(4)

        # 專案工作區
        lay.addWidget(self._make_label("專案工作區（自動建立）"))
        self.lbl_project_dir = QLineEdit(self._project_dir)
        self.lbl_project_dir.setReadOnly(True)
        self.lbl_project_dir.setMinimumHeight(36)
        self.lbl_project_dir.setStyleSheet("background: #F3F4F6;")
        lay.addWidget(self.lbl_project_dir)

        # First_try 來源
        lay.addWidget(self._make_label("First_try 來源（Navisworks 提供）"))
        self.lbl_first_try = QLineEdit(self._first_try_source)
        self.lbl_first_try.setReadOnly(True)
        self.lbl_first_try.setMinimumHeight(36)
        self.lbl_first_try.setStyleSheet("background: #F3F4F6;")
        lay.addWidget(self.lbl_first_try)

        # ISO LIST 選擇
        lay.addWidget(self._make_label("ISO LIST 檔案（請瀏覽選擇）"))
        iso_row = QHBoxLayout()
        iso_row.setSpacing(8)
        self.txt_iso_source = QLineEdit()
        self.txt_iso_source.setPlaceholderText("請選擇 ISO LIST Excel 檔案…")
        self.txt_iso_source.setMinimumHeight(36)
        iso_row.addWidget(self.txt_iso_source, stretch=1)
        btn_browse = QPushButton("瀏覽")
        btn_browse.setProperty("class", "btn-primary")
        btn_browse.setFixedHeight(36)
        btn_browse.setFixedWidth(80)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._browse_iso)
        iso_row.addWidget(btn_browse)
        lay.addLayout(iso_row)

        lay.addSpacing(10)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("確定並建立工作區")
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
    #  Callbacks
    # ────────────────────────────────────────

    def _browse_iso(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 ISO LIST 檔案",
            "",
            "Excel (*.xlsx *.xlsm *.xls);;All (*)",
        )
        if path:
            self.txt_iso_source.setText(path)

    def _on_confirm(self):
        iso_src = self.txt_iso_source.text().strip()

        # 驗證 First_try
        if not os.path.isfile(self._first_try_source):
            QMessageBox.warning(
                self, "錯誤",
                f"First_try 檔案不存在：\n{self._first_try_source}",
            )
            return

        # 驗證 ISO LIST
        if not iso_src or not os.path.isfile(iso_src):
            QMessageBox.warning(self, "錯誤", "請選擇有效的 ISO LIST 檔案。")
            return

        # 建立工作區
        try:
            os.makedirs(self._project_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(
                self, "建立失敗",
                f"無法建立工作區資料夾：\n{e}",
            )
            return

        # 複製 First_try → First_try.csv
        dst_first = os.path.join(self._project_dir, "First_try.csv")
        try:
            shutil.copy2(self._first_try_source, dst_first)
        except OSError as e:
            QMessageBox.critical(
                self, "複製失敗",
                f"無法複製 First_try：\n{e}",
            )
            return

        # 複製 ISO LIST → ISO_LIST.xlsx（保留原副檔名）
        iso_ext = os.path.splitext(iso_src)[1] or ".xlsx"
        dst_iso = os.path.join(self._project_dir, f"ISO_LIST{iso_ext}")
        try:
            shutil.copy2(iso_src, dst_iso)
        except OSError as e:
            QMessageBox.critical(
                self, "複製失敗",
                f"無法複製 ISO LIST：\n{e}",
            )
            return

        # 設定結果
        self.project_dir = self._project_dir
        self.iso_list_dest = dst_iso
        self.accept()
