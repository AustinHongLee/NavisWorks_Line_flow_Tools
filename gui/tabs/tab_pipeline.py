# -*- coding: utf-8 -*-
"""Tab1 — 管線抽取 / 群組整理 + ISO 比對 + Header 欄位。

以 Mixin 形式混入 MainWindow，提供 _build_page_project() / _build_page_iso()
與所有 Tab1 相關回呼。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import (
    CollapsibleSection,
    find_any_iso,
    make_field_label,
    make_note,
    make_panel,
    make_section_desc,
    make_section_header,
    make_separator,
    set_sidebar_badge,
)
from gui.dialogs.pipe_config_dialog import PipeCodeConfigDialog
from gui.dialogs.detect_progress_dialog import DetectProgressDialog
from gui.workers.detect_worker import LevelDetectWorker
from utils.pipe_parser import DEFAULT_CONFIG_FILENAME, load_pipe_pattern
from utils.help_texts import ISO_MINUS_HELP

if TYPE_CHECKING:
    from gui.main_window import MainWindow  # noqa: F401


class PipelineTabMixin:
    """Tab1 建構 + 檔案狀態偵測 + 所有 Tab1 / Header 回呼。

    混入 MainWindow 使用。
    """

    # ════════════════════════════════════════
    #  Page 0 — 專案設定
    # ════════════════════════════════════════

    def _build_page_project(self):
        """建立 Page 0：專案根目錄 + 抽取 / 群組參數。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(16)

        # ── 專案設定卡片 ──
        p_proj, pp = make_panel("panel-blue")
        pp.addWidget(make_section_header("專案設定"))
        pp.addWidget(make_section_desc("選擇專案根目錄與 First_try 來源"))

        pp.addWidget(make_field_label("專案根目錄"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.txt_base_dir = QLineEdit()
        self.txt_base_dir.setPlaceholderText("選擇包含 First_try.csv 的專案資料夾…")
        self.txt_base_dir.setMinimumHeight(38)
        self.txt_base_dir.textChanged.connect(self._update_file_status)
        dir_row.addWidget(self.txt_base_dir, stretch=1)
        btn_browse = QPushButton("瀏覽")
        btn_browse.setProperty("class", "btn-primary")
        btn_browse.setFixedHeight(38)
        btn_browse.setFixedWidth(80)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._browse_base_dir)
        dir_row.addWidget(btn_browse)
        pp.addLayout(dir_row)

        ft_row = QHBoxLayout()
        ft_row.setSpacing(16)
        ft_field = QVBoxLayout()
        ft_field.setSpacing(4)
        ft_field.addWidget(make_field_label("First_try 檔名"))
        self.txt_first_name = QLineEdit("First_try.csv")
        self.txt_first_name.setFixedWidth(200)
        self.txt_first_name.setMinimumHeight(36)
        self.txt_first_name.textChanged.connect(self._update_file_status)
        ft_field.addWidget(self.txt_first_name)
        ft_row.addLayout(ft_field)
        self.chk_file_log = QCheckBox("同時輸出 run_pipeline_log.txt")
        ft_row.addWidget(self.chk_file_log)
        ft_row.addStretch()
        pp.addLayout(ft_row)

        lay.addWidget(p_proj)

        # ── 抽取 / 群組參數卡片 ──
        p_params, pm = make_panel("panel-blue")
        pm.addWidget(make_section_header("抽取 / 群組參數"))
        pm.addWidget(make_section_desc(
            "控制管線抽取行為：掃描模式決定搜尋範圍"
        ))

        # ── 掃描模式 ──
        pm.addWidget(make_field_label("掃描模式"))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.radio_scan_full = QRadioButton("嚴謹（全掃）")
        self.radio_scan_full.setToolTip(
            "掃描所有列，純靠 PipelineId / Path regex\n"
            "辨識管線編號。最安全，不漏抓。"
        )
        self.radio_scan_full.setChecked(True)
        self.radio_scan_level = QRadioButton("加速（指定 Level）")
        self.radio_scan_level.setToolTip(
            "僅掃描指定 Level 的列，速度較快。\n"
            "需確保 Level 結構穩定且管線都在同一層。"
        )
        mode_row.addWidget(self.radio_scan_full)
        mode_row.addWidget(self.radio_scan_level)
        mode_row.addStretch()
        pm.addLayout(mode_row)
        pm.addWidget(make_note(
            "嚴謹模式：不限 Level，全面掃描所有列找管線編號（推薦）\n"
            "加速模式：僅掃描指定 Level，需先偵測或手動輸入正確 Level"
        ))

        # ── Level / 自動偵測（加速模式用） ──
        self._level_panel = QWidget()
        lp_lay = QHBoxLayout(self._level_panel)
        lp_lay.setContentsMargins(0, 4, 0, 0)
        lp_lay.setSpacing(12)

        lv_field = QVBoxLayout()
        lv_field.setSpacing(4)
        lv_field.addWidget(make_field_label("身分證 Level"))
        lv_input = QHBoxLayout()
        lv_input.setSpacing(6)
        self.txt_id_level = QLineEdit()
        self.txt_id_level.setFixedWidth(60)
        self.txt_id_level.setMinimumHeight(36)
        self.txt_id_level.setPlaceholderText("空")
        lv_input.addWidget(self.txt_id_level)
        self.btn_detect_level = QPushButton("自動偵測")
        self.btn_detect_level.setProperty("class", "btn-accent")
        self.btn_detect_level.setFixedHeight(36)
        self.btn_detect_level.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detect_level.setToolTip(
            "用 ISO 清單的管線編號到 First_try.csv 中搜尋，\n"
            "自動找出 3D 身分證所在的 Level 階層"
        )
        self.btn_detect_level.clicked.connect(self._on_detect_id_level)
        lv_input.addWidget(self.btn_detect_level)
        lv_field.addLayout(lv_input)
        lv_field.addWidget(make_note("指定 3D 身分證 Level（常見 1~4）"))
        lp_lay.addLayout(lv_field)
        lp_lay.addStretch()

        pm.addWidget(self._level_panel)
        self._level_panel.setVisible(False)

        # 連接 radio → 顯示/隱藏 level panel
        self.radio_scan_level.toggled.connect(self._on_scan_mode_changed)

        pm.addWidget(make_separator())

        # ── 分隔符 ──
        sep_row = QHBoxLayout()
        sep_row.setSpacing(12)
        sep_field = QVBoxLayout()
        sep_field.setSpacing(4)
        sep_field.addWidget(make_field_label("分隔符 (sep)"))
        self.txt_sep = QLineEdit("___")
        self.txt_sep.setFixedWidth(100)
        self.txt_sep.setMinimumHeight(36)
        sep_field.addWidget(self.txt_sep)
        sep_field.addWidget(make_note("拆解 Path 用，影響 minus 擷取"))
        sep_row.addLayout(sep_field)
        sep_row.addStretch()
        pm.addLayout(sep_row)

        # ── 進階抽取選項 (collapsible) — 含 filter_key ──
        adv_extract = CollapsibleSection(
            "進階抽取選項", initially_open=False,
        )
        fk_lay = QHBoxLayout()
        fk_lay.setSpacing(8)
        fk_lay.addWidget(make_field_label("篩選關鍵字"))
        self.txt_filter_key = QLineEdit("管線")
        self.txt_filter_key.setFixedWidth(130)
        self.txt_filter_key.setMinimumHeight(36)
        fk_lay.addWidget(self.txt_filter_key)
        fk_lay.addStretch()
        adv_extract.add_layout(fk_lay)
        adv_extract.add_widget(make_note(
            "僅在非 Level 模式、非全掃模式下生效：\n"
            "在 Level=2 中找含此關鍵字的 root，只抽取其子樹。\n"
            "⚠ 命名不含此關鍵字的子樹會被跳過（如「管架」不含「管線」）"
        ))
        pm.addWidget(adv_extract)

        pm.addWidget(make_separator())
        opt_row = QHBoxLayout()
        opt_row.setSpacing(16)
        btn_pipe_pattern = QPushButton("🔧 管線編號拆解設定…")
        btn_pipe_pattern.setProperty("class", "btn-accent")
        btn_pipe_pattern.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pipe_pattern.clicked.connect(self._open_pipe_pattern_dialog)
        opt_row.addWidget(btn_pipe_pattern)
        opt_row.addStretch()
        pm.addLayout(opt_row)

        lay.addWidget(p_params)
        lay.addStretch()

        scroll.setWidget(content)
        self.pages.addWidget(scroll)

    # ════════════════════════════════════════
    #  Page 1 — ISO 比對設定
    # ════════════════════════════════════════

    def _build_page_iso(self):
        """建立 Page 1：ISO 檔案 / 欄位、進階選項、Header 欄位。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(16)

        # ── ISO 比對設定卡片 ──
        p_iso, pi = make_panel("panel-green")
        pi.addWidget(make_section_header("ISO 比對設定"))
        pi.addWidget(make_section_desc("設定 ISO LIST 檔案、工作表與欄位對應"))

        pi.addWidget(make_field_label("ISO LIST 檔案"))
        iso_row = QHBoxLayout()
        iso_row.setSpacing(8)
        self.txt_iso_path = QLineEdit()
        self.txt_iso_path.setPlaceholderText("留空 = 自動搜尋")
        self.txt_iso_path.setMinimumHeight(36)
        self.txt_iso_path.textChanged.connect(
            lambda: self._update_file_status()
        )
        iso_row.addWidget(self.txt_iso_path, stretch=1)
        btn_iso = QPushButton("選檔")
        btn_iso.setProperty("class", "btn-primary")
        btn_iso.setFixedHeight(36)
        btn_iso.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_iso.clicked.connect(self._browse_iso_file)
        iso_row.addWidget(btn_iso)
        pi.addLayout(iso_row)

        # 2×2 combo grid
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        sheet_f = QVBoxLayout()
        sheet_f.setSpacing(4)
        sheet_f.addWidget(make_field_label("工作表"))
        self.cbo_iso_sheet = QComboBox()
        self.cbo_iso_sheet.setMinimumHeight(36)
        self.cbo_iso_sheet.setEditable(True)
        self.cbo_iso_sheet.currentTextChanged.connect(self._on_sheet_selected)
        self.cbo_iso_sheet.currentTextChanged.connect(
            lambda: self._update_file_status()
        )
        sheet_f.addWidget(self.cbo_iso_sheet)
        row1.addLayout(sheet_f, stretch=1)

        pipe_f = QVBoxLayout()
        pipe_f.setSpacing(4)
        pipe_f.addWidget(make_field_label("管線欄位"))
        self.cbo_pipe_col = QComboBox()
        self.cbo_pipe_col.setMinimumHeight(36)
        self.cbo_pipe_col.setEditable(True)
        self.cbo_pipe_col.currentTextChanged.connect(
            lambda: self._update_file_status()
        )
        pipe_f.addWidget(self.cbo_pipe_col)
        row1.addLayout(pipe_f, stretch=1)

        pi.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)

        spool_f = QVBoxLayout()
        spool_f.setSpacing(4)
        spool_f.addWidget(make_field_label("流水號欄位"))
        self.cbo_spool_col = QComboBox()
        self.cbo_spool_col.setMinimumHeight(36)
        self.cbo_spool_col.setEditable(True)
        self.cbo_spool_col.currentTextChanged.connect(
            lambda: self._update_file_status()
        )
        spool_f.addWidget(self.cbo_spool_col)
        row2.addLayout(spool_f, stretch=1)

        cat_f = QVBoxLayout()
        cat_f.setSpacing(4)
        cat_f.addWidget(make_field_label("分類欄位"))
        self.cbo_category_col = QComboBox()
        self.cbo_category_col.setMinimumHeight(36)
        self.cbo_category_col.setEditable(True)
        self.cbo_category_col.setEditText("發包分類")
        cat_f.addWidget(self.cbo_category_col)
        row2.addLayout(cat_f, stretch=1)

        pi.addLayout(row2)

        # ── 進階比對選項 (collapsible) ──
        adv_sec = CollapsibleSection("進階比對選項", initially_open=False)

        sr_lay = QVBoxLayout()
        sr_lay.setSpacing(4)
        sr_lay.addWidget(make_field_label("流水號分組規則"))
        self.txt_spool_rules = QLineEdit()
        self.txt_spool_rules.setMinimumHeight(36)
        self.txt_spool_rules.setPlaceholderText("可留空")
        sr_lay.addWidget(self.txt_spool_rules)
        adv_sec.add_layout(sr_lay)

        lr_lay = QVBoxLayout()
        lr_lay.setSpacing(4)
        lr_lay.addWidget(make_field_label("3D 寬鬆比對角色"))
        self.txt_loose_roles = QLineEdit("system,line_no")
        self.txt_loose_roles.setMinimumHeight(36)
        lr_lay.addWidget(self.txt_loose_roles)
        lr_lay.addWidget(make_note(
            "以逗號分隔角色名（如 system,line_no），"
            "角色來自 pipeline_config.json 的 segments.role"
        ))
        adv_sec.add_layout(lr_lay)

        prefix_lay = QHBoxLayout()
        prefix_lay.setSpacing(8)
        prefix_lay.addWidget(make_field_label("Raw_last 前導字元"))
        self.txt_raw_prefix = QLineEdit("/")
        self.txt_raw_prefix.setFixedWidth(60)
        self.txt_raw_prefix.setMinimumHeight(36)
        self.txt_raw_prefix.setPlaceholderText("如 / 或留空")
        prefix_lay.addWidget(self.txt_raw_prefix)
        self.lbl_prefix_hint = QLabel("")
        self.lbl_prefix_hint.setStyleSheet("color: #6B7280; font-size: 11px;")
        prefix_lay.addWidget(self.lbl_prefix_hint, stretch=1)
        adv_sec.add_layout(prefix_lay)
        adv_sec.add_widget(make_note(
            "選擇 ISO 工作表後會自動偵測最常見的前導字元，"
            "留空表示不加前導字元。可手動覆寫。"
        ))

        pi.addWidget(adv_sec)

        pi.addWidget(make_separator())
        help_row = QHBoxLayout()
        help_row.setSpacing(12)
        iso_note = make_note(
            "ISO 比對使用 123_minus_2 的 Line_combined 與 Raw_last 做對應。"
        )
        help_row.addWidget(iso_note, stretch=1)
        btn_help = QPushButton("❓ 操作說明")
        btn_help.setProperty("class", "btn-outline")
        btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_help.clicked.connect(self._show_minus_help)
        help_row.addWidget(btn_help)
        pi.addLayout(help_row)

        lay.addWidget(p_iso)

        # ── Header 欄位卡片 ──
        p_hdr, ph = make_panel("panel")
        hdr_sec = CollapsibleSection(
            "匯出 Header 欄位（控制 iso_match 欄位）",
            initially_open=False,
        )

        self.chk_export_headers = QCheckBox(
            "輸出 Header JSON（依欄位分組 Raw_last）"
        )
        self.chk_export_headers.setChecked(True)
        hdr_sec.add_widget(self.chk_export_headers)
        hdr_sec.add_widget(make_note(
            "預設匯出所有欄位。若下方選取了特定 Header，"
            "iso_match.xlsx 將僅保留基本欄位 + 所選欄位。"
        ))

        hdr_bar = QHBoxLayout()
        hdr_bar.setSpacing(6)
        hdr_bar.addWidget(QLabel("Header 候選："))
        self.cbo_header_available = QComboBox()
        self.cbo_header_available.setMinimumWidth(120)
        self.cbo_header_available.setMinimumHeight(32)
        hdr_bar.addWidget(self.cbo_header_available)
        btn_load_hdr = QPushButton("載入 ISO 欄位")
        btn_load_hdr.setProperty("class", "btn-accent")
        btn_load_hdr.clicked.connect(self._load_headers_from_iso)
        hdr_bar.addWidget(btn_load_hdr)
        btn_add = QPushButton("➕")
        btn_add.setFixedWidth(32)
        btn_add.setToolTip("匯入")
        btn_add.clicked.connect(self._add_header_choice)
        hdr_bar.addWidget(btn_add)
        btn_add_all = QPushButton("全部")
        btn_add_all.setToolTip("全部匯入")
        btn_add_all.clicked.connect(self._add_all_headers)
        hdr_bar.addWidget(btn_add_all)
        btn_remove = QPushButton("➖")
        btn_remove.setFixedWidth(32)
        btn_remove.setToolTip("移除")
        btn_remove.clicked.connect(self._remove_header_choice)
        hdr_bar.addWidget(btn_remove)
        hdr_bar.addStretch()
        hdr_sec.add_layout(hdr_bar)

        hdr_sec.add_widget(make_field_label("已選取的 Header 欄位："))
        self.list_header_selected = QListWidget()
        self.list_header_selected.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.list_header_selected.setFixedHeight(100)
        hdr_sec.add_widget(self.list_header_selected)

        ph.addWidget(hdr_sec)
        lay.addWidget(p_hdr)

        lay.addStretch()
        scroll.setWidget(content)
        self.pages.addWidget(scroll)

    # ════════════════════════════════════════
    #  檔案狀態偵測
    # ════════════════════════════════════════

    def _update_file_status(self):
        """偵測檔案並更新 sidebar 狀態標籤。"""
        base = self._get_base_dir()

        # 未選目錄 → 全部 neutral
        if not base:
            for lbl in (
                self.lbl_first_status,
                self.lbl_iso_status,
                self.lbl_config_status,
            ):
                set_sidebar_badge(lbl, "⬜ 請先選擇專案目錄", "neutral")
            self.lbl_iso_detail.setVisible(False)
            self.lbl_ready.setVisible(False)
            return

        # （ISO 自動載入已移至 Worker 背景線程處理）

        ready_count = 0
        total_required = 2  # First_try + ISO

        # ── First_try ──
        first = self.txt_first_name.text().strip() or "First_try.csv"
        first_path = os.path.join(base, first)
        if os.path.isfile(first_path):
            set_sidebar_badge(self.lbl_first_status, f"✅ {first}", "ok")
            ready_count += 1
        else:
            set_sidebar_badge(
                self.lbl_first_status, f"❌ {first} 不存在", "err"
            )

        # ── ISO ──
        iso_path = self.txt_iso_path.text().strip()
        if not iso_path:
            iso_found = find_any_iso(base)
        else:
            iso_found = iso_path if os.path.isfile(iso_path) else None

        has_sheet = bool(self.cbo_iso_sheet.currentText().strip())
        pipe_val = self.cbo_pipe_col.currentText().strip()
        spool_val = self.cbo_spool_col.currentText().strip()
        has_pipe = bool(pipe_val)
        has_spool = bool(spool_val)
        dup_cols = (has_pipe and has_spool and pipe_val == spool_val)

        if iso_found:
            iso_name = os.path.basename(iso_found)
            if has_sheet and has_pipe and has_spool and not dup_cols:
                set_sidebar_badge(
                    self.lbl_iso_status, f"✅ {iso_name}", "ok"
                )
                self.lbl_iso_detail.setVisible(False)
                ready_count += 1
            else:
                missing = []
                if not has_sheet:
                    missing.append("工作表")
                if not has_pipe:
                    missing.append("管線欄位")
                if not has_spool:
                    missing.append("流水號欄位")
                if dup_cols:
                    missing.append("管線 / 流水號不可相同")
                set_sidebar_badge(
                    self.lbl_iso_status,
                    f"⚠ {iso_name} — 設定未完成",
                    "err",
                )
                set_sidebar_badge(
                    self.lbl_iso_detail,
                    f"   缺少：{'、'.join(missing)}",
                    "err",
                )
                self.lbl_iso_detail.setVisible(True)
        else:
            set_sidebar_badge(
                self.lbl_iso_status,
                "⬜ 未偵測到 ISO 檔（可手動選）",
                "neutral",
            )
            self.lbl_iso_detail.setVisible(False)

        # ── Config ──
        cfg = os.path.join(base, DEFAULT_CONFIG_FILENAME)
        if os.path.isfile(cfg):
            set_sidebar_badge(
                self.lbl_config_status,
                f"✅ {DEFAULT_CONFIG_FILENAME}",
                "ok",
            )
        else:
            set_sidebar_badge(
                self.lbl_config_status,
                f"⬜ {DEFAULT_CONFIG_FILENAME}（可選）",
                "neutral",
            )

        # ── 就緒狀態 ──
        remaining = total_required - ready_count
        if remaining <= 0:
            set_sidebar_badge(self.lbl_ready, "🚀 可以執行！", "ready")
            self.lbl_ready.setVisible(True)
        elif remaining == 1:
            set_sidebar_badge(self.lbl_ready, "還差 1 個檔案", "neutral")
            self.lbl_ready.setVisible(True)
        else:
            self.lbl_ready.setVisible(False)

    # ════════════════════════════════════════
    #  瀏覽 / 偵測回呼
    # ════════════════════════════════════════

    # ── 智慧工作表選擇 ──

    @staticmethod
    def _score_sheet(xls: pd.ExcelFile, name: str) -> int:
        """為工作表評分：同時含管線 + 流水號欄位得最高分。"""
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
            "管線" in c or "line" in c or "pipe" in c
            for c in cols
        )
        has_spool = any(
            "流水" in c or "spool" in c or "series" in c
            for c in cols
        )
        score = int(has_pipe) * 2 + int(has_spool)
        # 偏好名稱含 DRAWING 的工作表
        if "drawing" in name.lower():
            score += 1
        return score

    def _pick_best_sheet(self, xls: pd.ExcelFile) -> str:
        """從 Excel 中擇優選擇同時含管線 + 流水號欄位的工作表。"""
        best_name = xls.sheet_names[0]
        best_score = -1
        for name in xls.sheet_names:
            s = self._score_sheet(xls, name)
            if s > best_score:
                best_score = s
                best_name = name
        return best_name

    def _load_sheets_and_select(self, xls: pd.ExcelFile):
        """填入工作表下拉並自動選擇最佳工作表。"""
        self.cbo_iso_sheet.clear()
        self.cbo_iso_sheet.addItems(xls.sheet_names)
        if xls.sheet_names:
            best = self._pick_best_sheet(xls)
            self.cbo_iso_sheet.setCurrentText(best)
            self._on_sheet_selected(best)

    def _try_auto_load_iso(self, base: str):
        """自動偵測 ISO 檔並載入工作表/欄位（僅當控制項尚為空時）。"""
        iso = self.txt_iso_path.text().strip()
        if not iso:
            # 尚未指定 → 自動搜尋
            iso = find_any_iso(base)
            if not iso:
                return
            self.txt_iso_path.setText(iso)

        # ISO 路徑已有，但工作表/欄位可能還沒載入 → 補載
        if self.cbo_iso_sheet.count() == 0:
            try:
                xls = pd.ExcelFile(iso, engine="openpyxl")
                self._load_sheets_and_select(xls)
            except Exception:
                pass

    def _browse_base_dir(self):
        d = QFileDialog.getExistingDirectory(self, "選擇專案根目錄")
        if not d:
            return
        self.txt_base_dir.setText(d)
        self._update_file_status()
        # 選定目錄後自動啟動完整偵測流程（含 ISO 搜尋 + Level 偵測）
        self._on_detect_id_level()

    def _browse_iso_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 ISO LIST 檔案",
            "",
            "Excel (*.xlsx *.xlsm *.xls);;All (*)",
        )
        if not path:
            return
        self.txt_iso_path.setText(path)
        try:
            xls = pd.ExcelFile(path, engine="openpyxl")
            self._load_sheets_and_select(xls)
        except Exception:
            pass
        self._update_file_status()

    def _on_detect_id_level(self):
        """一鍵偵測：ISO 搜尋 + 選表 + 欄位偵測 + Level 偵測。

        以背景線程執行，搭配 DetectProgressDialog 顯示讀條動畫。
        若 ISO 路徑尚未設定，Worker 會自動在專案目錄中搜尋。
        """
        try:
            base = self._get_base_dir()
        except Exception as e:
            QMessageBox.warning(self, "偵測失敗", str(e))
            return

        first = self.txt_first_name.text().strip() or "First_try.csv"
        iso_path = self.txt_iso_path.text().strip() or None
        sep = self.txt_sep.text().strip() or "___"
        sheet = self.cbo_iso_sheet.currentText().strip() or None
        pipe_col = self.cbo_pipe_col.currentText().strip() or None

        # ── 建立 Worker + Dialog ──
        dlg = DetectProgressDialog(self)
        worker = LevelDetectWorker(
            base_dir=base,
            first_name=first,
            iso_path=iso_path,
            sep=sep,
            sheet=sheet,
            pipe_col=pipe_col,
        )
        self._detect_worker = worker  # prevent GC
        self._detect_dlg = dlg

        # 連接 signal
        worker.progress.connect(dlg.on_progress)
        worker.log.connect(dlg.on_log)
        worker.finished.connect(
            lambda ok, result: self._on_detect_finished(ok, result)
        )

        # 啟動
        dlg.start_pulse()
        worker.start()
        dlg.exec()  # modal — 阻塞直到對話框關閉

        # 若使用者按取消而 worker 還在跑
        if dlg.cancelled and worker.isRunning():
            worker.terminate()
            worker.wait(2000)

    def _on_detect_finished(self, ok: bool, result: dict):
        """Worker 完成後回呼。"""
        dlg: DetectProgressDialog = self._detect_dlg
        worker: LevelDetectWorker = self._detect_worker

        if dlg.cancelled:
            return

        if not ok:
            dlg.show_result_fail(result.get("detail", "未知錯誤"))
            self._update_file_status()
            return

        level = result.get("level")
        confidence = result.get("confidence", 0.0)
        detail = result.get("detail", "")

        # ── 若 Worker 自動找到 ISO，回寫路徑 ──
        if worker.iso_path:
            cur = self.txt_iso_path.text().strip()
            if not cur or cur != worker.iso_path:
                self.txt_iso_path.setText(worker.iso_path)

        # ── 回寫工作表清單 + 最佳工作表 ──
        if worker.all_sheets:
            self.cbo_iso_sheet.blockSignals(True)
            self.cbo_iso_sheet.clear()
            self.cbo_iso_sheet.addItems(worker.all_sheets)
            if worker.best_sheet:
                self.cbo_iso_sheet.setCurrentText(worker.best_sheet)
            self.cbo_iso_sheet.blockSignals(False)
            # 觸發 _on_sheet_selected 填入欄位 combo
            if worker.best_sheet:
                self._on_sheet_selected(worker.best_sheet)

        # ── 回寫偵測到的欄位 ──
        if worker.detected_pipe_col:
            self.cbo_pipe_col.setCurrentText(worker.detected_pipe_col)
        if worker.detected_spool_col:
            self.cbo_spool_col.setCurrentText(worker.detected_spool_col)

        self._update_file_status()

        if level is not None:
            self.txt_id_level.setText(str(level))
            dlg.show_result_ok(level, confidence, detail)
        else:
            dlg.show_result_fail(detail)

    def _on_sheet_selected(self, sheet: str):
        """工作表變更 → 更新欄位下拉選單。"""
        iso_path = self.txt_iso_path.text().strip()
        if not iso_path or not sheet:
            return
        try:
            df = pd.read_excel(
                iso_path, sheet_name=sheet, nrows=5,
                dtype=str, engine="openpyxl",
            )
            cols = [str(c).strip() for c in df.columns if str(c).strip()]
        except Exception:
            return
        if not cols:
            return

        combos = (self.cbo_pipe_col, self.cbo_spool_col,
                  self.cbo_category_col)
        for cbo in combos:
            cbo.clear()
            cbo.addItems(cols)

        # ── 管線欄位自動偵測（精確匹配 > 模糊匹配）──
        pipe_col = None
        # 1) 精確名稱：常見 pipe 欄位名
        precise_pipe = {
            "line_no", "line no", "管線號", "管線編號",
            "line number", "pipe no",
        }
        for c in cols:
            if c.lower().strip() in precise_pipe:
                pipe_col = c
                break
        # 2) 寬鬆：含 line/管線 但排除「管線材質」等
        if not pipe_col:
            skip_pipe = {"管線材質", "管線等級"}
            for c in cols:
                if c in skip_pipe:
                    continue
                cl = c.lower()
                if "管線" in cl or "line" in cl or "pipe" in cl:
                    pipe_col = c
                    break
        if pipe_col:
            self.cbo_pipe_col.setCurrentText(pipe_col)

        # ── 流水號欄位自動偵測 ──
        spool_col = None
        precise_spool = {"流水號", "series no", "spool no"}
        for c in cols:
            if c.lower().strip() in precise_spool:
                spool_col = c
                break
        if not spool_col:
            for c in cols:
                cl = c.lower()
                if "流水" in cl or "spool" in cl or "series" in cl:
                    spool_col = c
                    break
        if spool_col:
            self.cbo_spool_col.setCurrentText(spool_col)

        # ── 分類欄位自動偵測 ──
        if "發包分類" in cols:
            self.cbo_category_col.setCurrentText("發包分類")
        else:
            found_cat = False
            for c in cols:
                if "分類" in c or "category" in c.lower():
                    self.cbo_category_col.setCurrentText(c)
                    found_cat = True
                    break
            if not found_cat:
                # 工作表無分類欄位 → 保留預設（editable combo）
                self.cbo_category_col.setEditText("發包分類")

        # 自動偵測 raw prefix
        self._auto_detect_raw_prefix(iso_path, sheet, pipe_col)
        self._update_file_status()

    def _auto_detect_raw_prefix(
        self,
        iso_path: Optional[str] = None,
        sheet: Optional[str] = None,
        pipe_col: Optional[str] = None,
    ):
        """讀取 ISO 數據，偵測管線值是否以 / 開頭。"""
        try:
            iso_path = iso_path or self.txt_iso_path.text().strip()
            sheet = sheet or self.cbo_iso_sheet.currentText().strip()
            pipe_col = pipe_col or self.cbo_pipe_col.currentText().strip()
            if not iso_path or not sheet or not pipe_col:
                return
            df = pd.read_excel(
                iso_path, sheet_name=sheet, dtype=str, engine="openpyxl"
            ).fillna("")
            if pipe_col not in df.columns:
                return
            vals = df[pipe_col].astype(str).str.strip()
            vals = vals[vals != ""]
            if vals.empty:
                return
            slash_count = vals.str.startswith("/").sum()
            ratio = slash_count / len(vals)
            if ratio > 0.5:
                self.txt_raw_prefix.setText("/")
                self.lbl_prefix_hint.setText(
                    f"偵測到 {slash_count}/{len(vals)} 筆以 / 開頭"
                )
            else:
                self.txt_raw_prefix.setText("")
                self.lbl_prefix_hint.setText(
                    f"偵測到 {slash_count}/{len(vals)} 筆以 / 開頭（少數，不加）"
                )
        except Exception:
            pass

    def _on_scan_mode_changed(self, level_checked: bool):
        """切換掃描模式時顯示/隱藏 Level 面板。"""
        self._level_panel.setVisible(level_checked)

    def _show_minus_help(self):
        QMessageBox.information(self, "ISO 比對操作說明", ISO_MINUS_HELP)

    def _open_pipe_pattern_dialog(self):
        try:
            base = self._get_base_dir()
        except ValueError:
            QMessageBox.warning(self, "提示", "請先設定專案根目錄。")
            return
        config_path = os.path.join(base, DEFAULT_CONFIG_FILENAME)
        initial = (load_pipe_pattern(config_path)
                   if os.path.isfile(config_path) else None)
        dlg = PipeCodeConfigDialog(self, config_path, initial)
        dlg.exec()

    # ════════════════════════════════════════
    #  Header 欄位回呼
    # ════════════════════════════════════════

    def _load_headers_from_iso(self):
        iso_path = self.txt_iso_path.text().strip()
        sheet = self.cbo_iso_sheet.currentText().strip()
        if not iso_path or not sheet:
            QMessageBox.warning(
                self, "提示", "請先選擇 ISO 檔案與工作表。"
            )
            return
        try:
            df = pd.read_excel(
                iso_path, sheet_name=sheet, nrows=0,
                dtype=str, engine="openpyxl",
            )
            cols = [
                str(c).strip()
                for c in df.columns
                if str(c).strip() and not str(c).strip().startswith("__")
            ]
        except Exception as e:
            QMessageBox.warning(self, "讀取失敗", str(e))
            return

        self.cbo_header_available.clear()
        self.cbo_header_available.addItems(cols)

    def _add_header_choice(self):
        text = self.cbo_header_available.currentText().strip()
        if not text:
            return
        # 避免重複
        for i in range(self.list_header_selected.count()):
            if self.list_header_selected.item(i).text() == text:
                return
        self.list_header_selected.addItem(text)

    def _add_all_headers(self):
        for i in range(self.cbo_header_available.count()):
            text = self.cbo_header_available.itemText(i).strip()
            if not text:
                continue
            exists = False
            for j in range(self.list_header_selected.count()):
                if self.list_header_selected.item(j).text() == text:
                    exists = True
                    break
            if not exists:
                self.list_header_selected.addItem(text)

    def _remove_header_choice(self):
        for item in self.list_header_selected.selectedItems():
            row = self.list_header_selected.row(item)
            self.list_header_selected.takeItem(row)
