# -*- coding: utf-8 -*-
"""Tab3 — JSON 匯出（Excel 式篩選面板）。

以 Mixin 形式混入 MainWindow，提供 _build_page_json() 與所有回呼。

設計：模仿 Excel AutoFilter
  - 頂部工具列：資料來源 + 載入按鈕
  - 欄位篩選按鈕列：每個欄位一顆按鈕，點擊開啟勾選 Popup
  - 資料預覽表格：即時反映篩選結果
  - 底部匯出列：統計 + 檔名 + 匯出按鈕
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.collision_decision_dialog import CollisionDecisionDialog
from gui.dialogs.trace_viewer_dialog import TraceViewerDialog
from gui.theme import C_ERROR, C_PRIMARY, C_SUCCESS
from gui.widgets import read_iso_match

if TYPE_CHECKING:
    from gui.main_window import MainWindow  # noqa: F401

# 預覽表格最多顯示列數
_PREVIEW_MAX_ROWS = 200
# 篩選彈窗最多顯示值數量
_POPUP_MAX_VALUES = 5000


# ============================================================
#  FilterPopup — Excel 式欄位篩選彈窗
# ============================================================

class FilterPopup(QDialog):
    """模仿 Excel AutoFilter 的勾選彈窗。

    開啟後顯示該欄的所有唯一值（checkbox），使用者可搜尋、
    全選/取消全選、然後確定或清除篩選。
    """

    def __init__(
        self,
        parent,
        column_name: str,
        all_values: list[str],
        checked: set[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"篩選 — {column_name}")
        self.setMinimumSize(280, 360)
        self.resize(320, 440)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )

        self._all_values = all_values
        self.result_checked: set[str] | None = None

        # ── 強制設定對話框底色 & 文字色 ──
        self.setStyleSheet(
            "QDialog { background: #FFFFFF; color: #1E293B; }"
            " QLabel { color: #1E293B; }"
            " QListWidget { background: #FFFFFF; color: #1E293B;"
            "   border: 1px solid #E2E8F0; border-radius: 6px; }"
            " QListWidget::item { color: #1E293B; padding: 3px 6px; }"
            " QListWidget::item:hover { background: #F1F5F9; }"
            " QLineEdit { background: #F9FAFB; color: #1E293B;"
            "   border: 1px solid #D1D5DB; border-radius: 6px;"
            "   padding: 6px 10px; font-size: 12px; }"
            " QPushButton { background: #F8FAFC; color: #475569;"
            "   border: 1px solid #E2E8F0; border-radius: 6px;"
            "   padding: 4px 12px; font-size: 12px; }"
            " QPushButton:hover { background: #EFF6FF;"
            "   border-color: #93C5FD; color: #2563EB; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # ── 搜尋框 ──
        self._txt_search = QLineEdit()
        self._txt_search.setPlaceholderText("搜尋…")
        self._txt_search.setClearButtonEnabled(True)
        self._txt_search.textChanged.connect(self._on_search)
        lay.addWidget(self._txt_search)

        # ── 全選 / 取消全選 ──
        ctl_row = QHBoxLayout()
        ctl_row.setSpacing(6)
        btn_all = QPushButton("全選")
        btn_all.setFixedHeight(26)
        btn_all.clicked.connect(self._select_all)
        ctl_row.addWidget(btn_all)
        btn_none = QPushButton("取消全選")
        btn_none.setFixedHeight(26)
        btn_none.clicked.connect(self._select_none)
        ctl_row.addWidget(btn_none)
        ctl_row.addStretch()
        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        ctl_row.addWidget(self._lbl_count)
        lay.addLayout(ctl_row)

        # ── checkbox 列表 ──
        self._list = QListWidget()
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        lay.addWidget(self._list, stretch=1)

        # 填充項目（先阻塞信號避免 O(n²) 開銷）
        pre_checked = checked if checked is not None else set()
        is_first_open = checked is None  # 首次開啟 → 全勾
        self._list.blockSignals(True)
        for val in all_values[:_POPUP_MAX_VALUES]:
            item = QListWidgetItem(val)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            if is_first_open or val in pre_checked:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self._list.addItem(item)
        self._list.blockSignals(False)

        # 連接信號（在填充完成後）
        self._list.itemChanged.connect(
            lambda _: self._update_count()
        )
        self._update_count()

        # ── 底部按鈕 ──
        bot = QHBoxLayout()
        bot.setSpacing(8)
        bot.addStretch()
        btn_ok = QPushButton("確定")
        btn_ok.setFixedSize(80, 32)
        btn_ok.setStyleSheet(
            f"background: {C_PRIMARY}; color: white;"
            " border: none; border-radius: 6px;"
            " font-weight: 600;"
        )
        btn_ok.clicked.connect(self._on_ok)
        bot.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)
        btn_clear = QPushButton("清除篩選")
        btn_clear.setFixedSize(80, 32)
        btn_clear.setStyleSheet(
            f"color: {C_ERROR}; font-weight: 500;"
        )
        btn_clear.clicked.connect(self._on_clear)
        bot.addWidget(btn_clear)
        lay.addLayout(bot)

    # ── helpers ──

    def _on_search(self, text: str):
        text = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(
                bool(text) and text not in item.text().lower()
            )

    def _select_all(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def _select_none(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)

    def _update_count(self):
        total = self._list.count()
        checked = sum(
            1 for i in range(total)
            if self._list.item(i).checkState()
            == Qt.CheckState.Checked
        )
        self._lbl_count.setText(f"{checked} / {total}")

    def _on_ok(self):
        self.result_checked = set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.result_checked.add(item.text())
        self.accept()

    def _on_clear(self):
        """清除此欄篩選 → 回傳 None 表示不篩選。"""
        self.result_checked = None
        self.accept()


# ============================================================
#  JsonTabMixin
# ============================================================

class JsonTabMixin:
    """JSON 匯出頁（Excel 式篩選面板），混入 MainWindow。"""

    # ════════════════════════════════════════════════════════
    #  建立 UI
    # ════════════════════════════════════════════════════════

    def _build_page_json(self):
        """建立 Page 2：Excel 式篩選 → JSON 匯出。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)

        # ── 向後相容：保留隱藏欄位 ──
        self.chk_enable_v2 = QCheckBox("啟用")
        self.chk_enable_v2.setChecked(True)
        self.chk_enable_v2.setVisible(False)
        self.v2_chk_group = QCheckBox()
        self.v2_chk_group.setChecked(True)
        self.v2_chk_group.setVisible(False)
        # v2_cbo_group_key 在底部列建立（真正的 QComboBox）
        # 相容空列表
        self.v2_filter_field_cbos = []
        self.v2_filter_value_listboxes = []

        # ════════════════════════════════
        #  Row 1 — 工具列（來源 + 按鈕）
        # ════════════════════════════════
        toolbar = QFrame()
        toolbar.setObjectName("jsonToolbar")
        toolbar.setStyleSheet(
            "#jsonToolbar {"
            "  background: #EFF6FF;"
            "  border: 1px solid #BFDBFE;"
            "  border-radius: 8px;"
            "}"
            " #jsonToolbar QLabel { color: #1E293B; }"
            " #jsonToolbar QPushButton {"
            "   background: #FFFFFF; color: #2563EB;"
            "   border: 1px solid #BFDBFE; border-radius: 6px;"
            "   padding: 4px 12px; font-size: 12px; font-weight: 500;"
            " }"
            " #jsonToolbar QPushButton:hover {"
            "   background: #DBEAFE; border-color: #93C5FD;"
            " }"
        )
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(12, 6, 12, 6)
        tb_lay.setSpacing(8)

        source_col = QVBoxLayout()
        source_col.setContentsMargins(0, 0, 0, 0)
        source_col.setSpacing(1)

        self._v2_lbl_source = QLabel("尚未載入資料")
        self._v2_lbl_source.setStyleSheet(
            "color: #64748B; font-size: 12px;"
        )
        self._v2_lbl_source.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        source_col.addWidget(self._v2_lbl_source)

        self._v2_lbl_blocked = QLabel("攔截：尚未計算")
        self._v2_lbl_blocked.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        self._v2_lbl_blocked.setVisible(False)
        source_col.addWidget(self._v2_lbl_blocked)

        self._v2_lbl_scope = QLabel("範圍覆蓋：尚未計算")
        self._v2_lbl_scope.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        self._v2_lbl_scope.setVisible(False)
        source_col.addWidget(self._v2_lbl_scope)

        tb_lay.addLayout(source_col, stretch=1)

        btn_auto = QPushButton("自動載入")
        btn_auto.setToolTip("從專案目錄自動尋找 iso_match.xlsx")
        btn_auto.setFixedHeight(28)
        btn_auto.clicked.connect(self._v2_auto_load_source)
        tb_lay.addWidget(btn_auto)

        btn_browse = QPushButton("選擇檔案…")
        btn_browse.setFixedHeight(28)
        btn_browse.clicked.connect(self._v2_browse_source)
        tb_lay.addWidget(btn_browse)

        btn_collision = QPushButton("處理衝突")
        btn_collision.setToolTip("開啟 NeedsDecision=1 的 collision 決策視窗")
        btn_collision.setFixedHeight(28)
        btn_collision.clicked.connect(self._v2_open_collision_decisions)
        tb_lay.addWidget(btn_collision)

        self._v2_chk_diagnostics = QCheckBox("診斷")
        self._v2_chk_diagnostics.setToolTip(
            "顯示攔截原因、範圍覆蓋率、JSON 原文與更多明細欄位。"
        )
        self._v2_chk_diagnostics.setStyleSheet(
            "QCheckBox { color: #475569; font-size: 12px; }"
        )
        self._v2_chk_diagnostics.toggled.connect(
            self._on_diagnostics_toggled
        )
        tb_lay.addWidget(self._v2_chk_diagnostics)

        lay.addWidget(toolbar)
        lay.addSpacing(6)

        # ════════════════════════════════
        #  Row 2 — 控制面板（篩選 1/2/3 + 說明）
        # ════════════════════════════════

        # ── 左側：篩選控制 ──
        ctrl_panel = QFrame()
        ctrl_panel.setObjectName("jsonCtrlPanel")
        ctrl_panel.setStyleSheet(
            "#jsonCtrlPanel {"
            "  background: #F8FAFC;"
            "  border: 1px solid #E2E8F0;"
            "  border-radius: 8px;"
            "}"
            " #jsonCtrlPanel QLabel { color: #475569; }"
            " #jsonCtrlPanel QComboBox {"
            "   background: #FFFFFF; color: #1E293B;"
            "   border: 1px solid #D1D5DB; border-radius: 6px;"
            "   padding: 3px 8px; font-size: 12px;"
            " }"
            " #jsonCtrlPanel QLineEdit {"
            "   background: #FFFFFF; color: #1E293B;"
            "   border: 1px solid #D1D5DB; border-radius: 6px;"
            "   padding: 3px 8px; font-size: 12px;"
            " }"
            " #jsonCtrlPanel QPushButton {"
            "   font-size: 11px; font-weight: 500;"
            "   background: #F8FAFC; color: #475569;"
            "   border: 1px solid #E2E8F0; border-radius: 6px;"
            "   padding: 3px 12px;"
            " }"
            " #jsonCtrlPanel QPushButton:hover {"
            "   background: #EFF6FF; border-color: #93C5FD;"
            "   color: #2563EB;"
            " }"
        )
        ctrl_lay = QVBoxLayout(ctrl_panel)
        ctrl_lay.setContentsMargins(10, 8, 10, 8)
        ctrl_lay.setSpacing(5)

        select_box = QGroupBox("1. 選列 - 哪些列要進入候選？")
        select_box.setStyleSheet(
            "QGroupBox { font-size: 12px; font-weight: 700;"
            " color: #334155; border: 1px solid #E2E8F0;"
            " border-radius: 6px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px;"
            " padding: 0 4px; }"
        )
        select_lay = QVBoxLayout(select_box)
        select_lay.setContentsMargins(8, 8, 8, 8)
        select_lay.setSpacing(5)

        # ── 篩選列 1/2/3 ──
        _FILTER_LABELS = ["條件 1", "條件 2", "條件 3"]
        self._v2_filter_row_widgets: list[dict] = []

        for i, label_text in enumerate(_FILTER_LABELS):
            frow = QHBoxLayout()
            frow.setSpacing(6)

            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                " color: #475569;"
            )
            lbl.setFixedWidth(56)
            frow.addWidget(lbl)

            cbo_col = QComboBox()
            cbo_col.setFixedWidth(150)
            cbo_col.addItem("（不篩選）")
            frow.addWidget(cbo_col)

            btn_val = QPushButton("▼ 選擇值")
            btn_val.setFixedHeight(28)
            btn_val.setFixedWidth(130)
            btn_val.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_val.setVisible(False)
            frow.addWidget(btn_val)

            frow.addStretch()

            # 第一列右側加「✕ 重設全部」
            if i == 0:
                btn_reset = QPushButton("清除全部")
                btn_reset.setFixedHeight(26)
                btn_reset.setCursor(
                    Qt.CursorShape.PointingHandCursor
                )
                btn_reset.setStyleSheet(
                    f"font-size: 11px; font-weight: 500;"
                    f" color: {C_ERROR};"
                    " background: transparent;"
                    " border: none;"
                    " padding: 2px 8px;"
                )
                btn_reset.clicked.connect(
                    self._v2_clear_all_filters
                )
                frow.addWidget(btn_reset)

            select_lay.addLayout(frow)

            widget_info = {
                "cbo_col": cbo_col,
                "btn_val": btn_val,
                "label": lbl,
                "active_col": None,
            }
            self._v2_filter_row_widgets.append(widget_info)

            cbo_col.currentTextChanged.connect(
                lambda text, idx=i: self._on_filter_col_changed(
                    idx, text
                )
            )
            btn_val.clicked.connect(
                lambda checked, idx=i: self._on_filter_val_clicked(
                    idx
                )
            )

        ctrl_lay.addWidget(select_box)

        package_box = QGroupBox("2. 包裝 - 母資訊要包誰？")
        package_box.setStyleSheet(select_box.styleSheet())
        package_lay = QVBoxLayout(package_box)
        package_lay.setContentsMargins(8, 8, 8, 8)
        package_lay.setSpacing(6)

        # ── 輸出模式 ──
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        lbl_mode = QLabel("輸出模式")
        lbl_mode.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569;"
        )
        lbl_mode.setFixedWidth(56)
        mode_row.addWidget(lbl_mode)
        self._v2_radio_grouped = QRadioButton("依欄位分組（單一檔）")
        self._v2_radio_flat = QRadioButton("平面清單")
        self._v2_radio_split = QRadioButton("依欄位分組（每組一檔）")
        self._v2_radio_grouped.setChecked(True)
        self._v2_mode_group = QButtonGroup(page)
        self._v2_mode_group.addButton(self._v2_radio_grouped)
        self._v2_mode_group.addButton(self._v2_radio_flat)
        self._v2_mode_group.addButton(self._v2_radio_split)
        for rb in (
            self._v2_radio_grouped,
            self._v2_radio_flat,
            self._v2_radio_split,
        ):
            rb.setStyleSheet("font-size: 12px; color: #334155;")
            rb.toggled.connect(self._on_output_mode_changed)
            mode_row.addWidget(rb)
        mode_row.addStretch()
        package_lay.addLayout(mode_row)

        # ── 分組欄位 ──
        gk_row = QHBoxLayout()
        gk_row.setSpacing(6)
        lbl_gk = QLabel("母資訊")
        lbl_gk.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569;"
        )
        lbl_gk.setFixedWidth(56)
        gk_row.addWidget(lbl_gk)
        self._v2_cbo_group_key = QComboBox()
        self._v2_cbo_group_key.setFixedWidth(150)
        self._v2_cbo_group_key.setToolTip(
            "用這個欄位當母資訊；每個值會包住底下的 3D 身分證。"
        )
        self._v2_cbo_group_key.currentIndexChanged.connect(
            lambda: (
                self._refresh_preview_table(),
                self._v2_update_live_count(),
                self._v2_update_filename(),
            )
        )
        gk_row.addWidget(self._v2_cbo_group_key)
        gk_row.addStretch()
        package_lay.addLayout(gk_row)

        # ── 檔名 ──
        fn_row = QHBoxLayout()
        fn_row.setSpacing(6)
        lbl_fn = QLabel("檔名")
        lbl_fn.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569;"
        )
        lbl_fn.setFixedWidth(56)
        fn_row.addWidget(lbl_fn)
        self.v2_txt_filename = QLineEdit("live_selection")
        self.v2_txt_filename.setFixedWidth(220)
        fn_row.addWidget(self.v2_txt_filename)
        fn_row.addStretch()
        package_lay.addLayout(fn_row)

        ctrl_lay.addWidget(package_box)

        # ── 右側：操作說明 ──
        help_browser = QTextBrowser()
        help_browser.setObjectName("jsonHelpGuide")
        help_browser.setOpenExternalLinks(False)
        help_browser.setStyleSheet(
            "#jsonHelpGuide {"
            "  background: #FFFBEB;"
            "  border: 1px solid #FDE68A;"
            "  border-radius: 8px;"
            "  font-size: 12px;"
            "  color: #1E293B;"
            "  padding: 6px;"
            "}"
        )
        help_browser.setHtml(
            '<div style="font-family: Microsoft JhengHei, sans-serif;'
            ' line-height:1.58; font-size:12px; color:#1E293B;">'
            '<p style="margin:0 0 6px; font-size:13px;'
            ' font-weight:700; color:#92400E;">輸出規則</p>'
            "<p style='margin:0 0 5px;'>"
            "<b>1. 篩選</b><br>"
            "只決定哪些列進入匯出候選。</p>"
            "<p style='margin:0 0 5px;'>"
            "<b>2. 安全檢查</b><br>"
            "未 resolved 或仍需 collision 決策的列會被擋下；"
            "下方統計會顯示被擋數量。</p>"
            "<p style='margin:0 0 5px;'>"
            "<b>3. 分組依據</b><br>"
            "可選 <b>系統</b>、保溫、材質、群組、流水號等任一欄位。"
            "選分類欄位時，下方會顯示每組挾帶幾個 3D 身分證。</p>"
            "<p style='margin:0;'>"
            "<b>4. 搜尋範圍</b><br>"
            "若資料有 PipeNodePath / ParentArea，JSON 會逐管線輸出 scope，"
            "供 Navisworks 匯入端限制搜尋範圍。</p>"
            "</div>"
        )
        help_browser.setFixedWidth(0)

        # ── 組合：左控制 + 右說明 ──
        ctrl_and_help = QHBoxLayout()
        ctrl_and_help.setSpacing(8)
        ctrl_and_help.addWidget(ctrl_panel, stretch=1)
        # 舊說明框保留為物件但預設不顯示；規則已拆進各區副標與 tooltip。

        # 未載入提示（載入後隱藏）
        self._lbl_filter_hint = QLabel(
            "載入資料後，這裡會顯示篩選與分組控制面板"
        )
        self._lbl_filter_hint.setStyleSheet(
            "color: #94A3B8; font-size: 12px;"
        )
        self._lbl_filter_hint.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        ctrl_area = QWidget()
        ca_lay = QVBoxLayout(ctrl_area)
        ca_lay.setContentsMargins(0, 0, 0, 0)
        ca_lay.addWidget(self._lbl_filter_hint)
        ca_lay.addLayout(ctrl_and_help)
        ctrl_panel.setVisible(False)
        help_browser.setVisible(False)
        self._ctrl_panel = ctrl_panel
        self._help_browser = help_browser

        lay.addWidget(ctrl_area)
        lay.addSpacing(4)

        # ════════════════════════════════
        #  Row 3 — 資料預覽表格
        # ════════════════════════════════
        self._v2_preview_caption = QLabel("資料預覽")
        self._v2_preview_caption.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #475569;"
        )
        lay.addWidget(self._v2_preview_caption)
        lay.addSpacing(2)

        table_style = (
            "QTableWidget {"
            "  font-size: 12px;"
            "  color: #1E293B;"
            "  gridline-color: #E2E8F0;"
            "  background: #FFFFFF;"
            "  alternate-background-color: #F8FAFC;"
            "}"
            "QTableWidget::item {"
            "  color: #1E293B;"
            "  padding: 1px 4px;"
            "}"
            "QTableWidget::item:selected {"
            "  background: #DBEAFE;"
            f"  color: {C_PRIMARY};"
            "}"
            "QHeaderView::section {"
            "  background: #F1F5F9;"
            "  color: #1E293B;"
            "  font-weight: 600;"
            "  font-size: 11px;"
            "  padding: 4px 6px;"
            "  border: none;"
            "  border-bottom: 2px solid #CBD5E1;"
            "  border-right: 1px solid #E2E8F0;"
            "}"
        )

        self._v2_summary_table = QTableWidget()
        self._v2_summary_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._v2_summary_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._v2_summary_table.setAlternatingRowColors(True)
        self._v2_summary_table.horizontalHeader().setStretchLastSection(True)
        self._v2_summary_table.verticalHeader().setDefaultSectionSize(24)
        self._v2_summary_table.setStyleSheet(table_style)
        self._v2_summary_table.itemSelectionChanged.connect(
            self._on_summary_selection_changed
        )

        self._v2_json_preview = QPlainTextEdit()
        self._v2_json_preview.setReadOnly(True)
        self._v2_json_preview.setStyleSheet(
            "QPlainTextEdit {"
            "  font-family: Consolas, 'Cascadia Mono', monospace;"
            "  font-size: 12px;"
            "  color: #0F172A;"
            "  background: #FFFFFF;"
            "  border: 1px solid #E2E8F0;"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "}"
        )

        self._v2_table = QTableWidget()
        self._v2_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._v2_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._v2_table.setAlternatingRowColors(True)
        self._v2_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._v2_table.customContextMenuRequested.connect(
            self._on_preview_context_menu
        )
        self._v2_table.horizontalHeader().setStretchLastSection(True)
        self._v2_table.verticalHeader().setDefaultSectionSize(24)
        self._v2_table.setStyleSheet(table_style)

        self._v2_preview_tabs = QTabWidget()
        self._v2_preview_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #E2E8F0;"
            " border-radius: 6px; background: #FFFFFF; }"
            "QTabBar::tab { background: #F8FAFC; color: #475569;"
            " border: 1px solid #E2E8F0; padding: 6px 14px;"
            " margin-right: 2px; border-top-left-radius: 6px;"
            " border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: #FFFFFF;"
            f" color: {C_PRIMARY}; font-weight: 700; }}"
        )
        self._v2_preview_tabs.addTab(self._v2_summary_table, "包裹摘要")
        self._v2_preview_tabs.addTab(self._v2_json_preview, "JSON 診斷")
        self._v2_preview_tabs.addTab(self._v2_table, "包裹明細")
        self._set_tab_visible(1, False)

        lay.addWidget(self._v2_preview_tabs, stretch=1)
        lay.addSpacing(6)

        # ════════════════════════════════
        #  Row 4 — 底部匯出列
        # ════════════════════════════════
        bot_frame = QFrame()
        bot_frame.setObjectName("jsonBotBar")
        bot_frame.setStyleSheet(
            "#jsonBotBar {"
            "  background: #F0FDF4;"
            "  border: 1px solid #BBF7D0;"
            "  border-radius: 8px;"
            "}"
            " #jsonBotBar QLabel { color: #475569; }"
        )
        bot_lay = QHBoxLayout(bot_frame)
        bot_lay.setContentsMargins(12, 8, 12, 8)
        bot_lay.setSpacing(10)

        self._v2_lbl_count = QLabel("尚未載入")
        self._v2_lbl_count.setStyleSheet(
            "font-size: 12px; font-weight: 600;"
            " color: #64748B;"
        )
        bot_lay.addWidget(self._v2_lbl_count)

        bot_lay.addStretch()

        self.v2_status_label = QLabel("")
        self.v2_status_label.setStyleSheet(
            "font-size: 11px; color: #475569;"
        )
        bot_lay.addWidget(self.v2_status_label)

        self._v2_btn_export = QPushButton("  匯出單一檔  ")
        self._v2_btn_export.setObjectName("btnExport")
        self._v2_btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._v2_btn_export.setFixedHeight(34)
        self._v2_btn_export.clicked.connect(self._v2_live_export)
        bot_lay.addWidget(self._v2_btn_export)

        lay.addWidget(bot_frame)

        self.pages.addWidget(page)

        # ── 內部狀態 ──
        self._v2_col_checked: dict[str, set[str] | None] = {}
        self._v2_cat_cols: list[str] = []  # 可篩選的分類欄位
        self._v2_last_result = None
        # 向後相容別名 / 空列表
        self.v2_cbo_group_key = self._v2_cbo_group_key
        self.v2_filter_field_cbos = []
        self.v2_filter_value_listboxes = []

    # ════════════════════════════════════════════════════════
    #  資料來源
    # ════════════════════════════════════════════════════════

    def _v2_auto_load_source(self):
        """自動從專案目錄載入 resolved_mapping.csv，退回 iso_match.xlsx。"""
        try:
            cfg = self._get_paths()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return

        source_path = cfg.get("resolved_mapping_csv")
        if not source_path or not os.path.exists(source_path):
            source_path = cfg["iso_match_xlsx"]

        if not os.path.exists(source_path):
            QMessageBox.warning(
                self,
                "找不到檔案",
                "resolved_mapping.csv / iso_match.xlsx 不存在。\n"
                "請先執行全部流程產出比對結果，"
                "或點擊「選擇檔案」手動指定。",
            )
            return
        self._v2_load_source(source_path)

    def _v2_browse_source(self):
        """手動選擇 Excel 檔案。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇資料來源",
            "",
            "Excel (*.xlsx *.xlsm *.xls);;"
            "CSV (*.csv);;All (*)",
        )
        if path:
            self._v2_load_source(path)

    def _v2_open_collision_decisions(self):
        """開啟 resolved_mapping collision 決策流程。"""
        try:
            cfg = self._get_paths()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        mapping_path = getattr(self, "_v2_source_path", "") or cfg.get(
            "resolved_mapping_csv", ""
        )
        if not mapping_path or not os.path.exists(mapping_path):
            mapping_path = cfg.get("resolved_mapping_csv", "")
        if not mapping_path or not os.path.exists(mapping_path):
            QMessageBox.warning(
                self,
                "找不到 resolved_mapping",
                "請先執行流程產生 resolved_mapping.csv，或在 JSON 匯出頁載入該檔。",
            )
            return
        if not str(mapping_path).lower().endswith(".csv"):
            QMessageBox.warning(
                self,
                "資料來源不支援",
                "Collision 決策目前只回寫 resolved_mapping.csv。",
            )
            return

        try:
            from core.collision_resolver import (
                apply_collision_decisions,
                load_collision_groups,
            )
            groups = load_collision_groups(mapping_path)
        except Exception as e:
            QMessageBox.critical(self, "讀取 collision 失敗", str(e))
            return

        if not groups:
            QMessageBox.information(self, "Collision 決策", "目前沒有需要人工決策的流水號。")
            return

        dlg = CollisionDecisionDialog(self, groups)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        decisions = dlg.get_decisions()
        if not decisions:
            QMessageBox.information(self, "Collision 決策", "沒有套用任何決策。")
            return
        try:
            stats = apply_collision_decisions(mapping_path, decisions)
        except Exception as e:
            QMessageBox.critical(self, "套用失敗", str(e))
            return

        QMessageBox.information(
            self,
            "Collision 決策完成",
            f"已選定 {stats['selected']} 列，排除 {stats['rejected']} 列。",
        )
        self._v2_load_source(mapping_path)

    def _v2_load_source(self, path: str):
        """載入資料並建立 Excel 式篩選面板。"""
        try:
            df = read_iso_match(path)
        except Exception as e:
            QMessageBox.critical(self, "讀取失敗", str(e))
            return

        self._v2_iso_df = df
        self._v2_source_path = path
        fname = os.path.basename(path)
        cols = [
            c
            for c in df.columns
            if not str(c).startswith("__") and str(c).strip()
        ]
        self._v2_available_cols = cols

        # 清除舊篩選
        self._v2_live_filters = {}
        self._v2_col_checked = {}

        # 更新來源標籤
        row_count = len(df)
        col_count = len(cols)
        raw_info = ""
        if "Raw_3D_PipeCode" in df.columns:
            raw_n = df["Raw_3D_PipeCode"].nunique()
            raw_info = f"  |  {raw_n} 筆管線"
        if "Resolved" in df.columns:
            resolved_n = int((df["Resolved"].astype(str).str.strip() == "1").sum())
            pending_n = row_count - resolved_n
            raw_info += f"  |  可匯出 {resolved_n} 筆 / 待決定 {pending_n} 筆"
        self._v2_lbl_source.setText(
            f"📄 {fname}    {row_count} 列 × {col_count} 欄{raw_info}"
        )
        self._v2_lbl_source.setStyleSheet(
            f"color: {C_PRIMARY}; font-weight: 600;"
            " font-size: 12px;"
        )
        self._v2_lbl_blocked.setText("攔截：載入後依目前篩選計算")
        self._v2_lbl_blocked.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        self._v2_lbl_blocked.setVisible(False)
        self._v2_lbl_scope.setText("範圍覆蓋：載入後依目前篩選計算")
        self._v2_lbl_scope.setStyleSheet(
            "color: #64748B; font-size: 11px;"
        )
        self._v2_lbl_scope.setVisible(False)

        # 群組 toggle
        has_group = "群組" in cols
        self.v2_chk_group.setEnabled(has_group)
        self.v2_chk_group.setChecked(has_group)

        # 建立可篩選的分類欄位清單（唯一值 < 50）
        _CAT_THRESHOLD = 50
        # 固定欄位一定要出現在選單中
        _PINNED = [
            "流水號",
            "群組",
            "系統",
            "保溫",
            "材質",
            "試壓媒介",
            "發包分類",
            "預製圖",
            "Class",
            "Size",
            "ParentArea",
            "ScopeRoot",
            "ResolutionStatus",
            "Resolved",
            "NeedsDecision",
        ]
        base_cat_cols = [
            c for c in cols
            if df[c].nunique() < _CAT_THRESHOLD or c in _PINNED
        ]
        cat_cols: list[str] = []
        for c in _PINNED:
            if c in base_cat_cols and c not in cat_cols:
                cat_cols.append(c)
        for c in base_cat_cols:
            if c not in cat_cols:
                cat_cols.append(c)
        if not cat_cols:
            cat_cols = cols[:8]
        self._v2_cat_cols = cat_cols

        # 填充分組依據下拉
        self._v2_cbo_group_key.blockSignals(True)
        self._v2_cbo_group_key.clear()
        self._v2_cbo_group_key.addItems(cat_cols)
        # 群組只是 resolved_mapping 中的普通欄位；有值時代表多個流水號要合併輸出。
        has_group_values = (
            "群組" in df.columns
            and df["群組"].fillna("").astype(str).str.strip().ne("").any()
        )
        if has_group_values and "群組" in cat_cols:
            self._v2_cbo_group_key.setCurrentText("群組")
        elif "流水號" in cat_cols:
            self._v2_cbo_group_key.setCurrentText("流水號")
        self._v2_cbo_group_key.blockSignals(False)
        self._on_output_mode_changed()

        # 填充篩選列下拉選單
        for info in self._v2_filter_row_widgets:
            info["cbo_col"].blockSignals(True)
            info["cbo_col"].clear()
            info["cbo_col"].addItem("（不篩選）")
            info["cbo_col"].addItems(cat_cols)
            info["cbo_col"].setCurrentIndex(0)
            info["cbo_col"].blockSignals(False)
            info["active_col"] = None
            info["btn_val"].setVisible(False)
            info["btn_val"].setText("▼ 選擇值")

        # 顯示控制面板
        self._lbl_filter_hint.setVisible(False)
        self._ctrl_panel.setVisible(True)
        self._help_browser.setVisible(False)

        # 填充表格 & 統計
        self._refresh_preview_table()
        self._v2_update_live_count()
        self._v2_update_filename()

        self.v2_status_label.setText("✓ 已載入，預覽表格只顯示實際可匯出的列")
        self.v2_status_label.setStyleSheet(
            f"color: {C_SUCCESS}; font-size: 11px;"
        )

    # ════════════════════════════════════════════════════════
    #  篩選列互動（母篩選 / 篩選 2 / 篩選 3）
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _chip_style(active: bool) -> str:
        """值按鈕的 CSS 樣式（啟用/未啟用）。"""
        if active:
            return (
                "font-size: 11px; font-weight: 600;"
                f" background: #DBEAFE; color: {C_PRIMARY};"
                " border: 1.5px solid #93C5FD;"
                " border-radius: 6px;"
                " padding: 3px 12px;"
            )
        return (
            "font-size: 11px; font-weight: 500;"
            " background: #F8FAFC; color: #475569;"
            " border: 1px solid #E2E8F0;"
            " border-radius: 6px;"
            " padding: 3px 12px;"
        )

    def _on_filter_col_changed(self, row_idx: int, text: str):
        """篩選列的欄位下拉變更 → 重設該列的值篩選。"""
        info = self._v2_filter_row_widgets[row_idx]
        old_col = info.get("active_col")
        if old_col:
            self._v2_live_filters.pop(old_col, None)
            self._v2_col_checked.pop(old_col, None)

        if text == "（不篩選）" or not text:
            info["active_col"] = None
            info["btn_val"].setVisible(False)
            info["btn_val"].setText("▼ 選擇值")
        else:
            info["active_col"] = text
            info["btn_val"].setVisible(True)
            info["btn_val"].setText("▼ 全部")
            info["btn_val"].setStyleSheet(
                self._chip_style(False)
            )

        self._refresh_preview_table()
        self._v2_update_live_count()
        self._v2_update_filename()

    def _on_filter_val_clicked(self, row_idx: int):
        """點擊值按鈕 → 開啟 FilterPopup。"""
        info = self._v2_filter_row_widgets[row_idx]
        col = info.get("active_col")
        if not col or self._v2_iso_df is None:
            return

        # 取得該欄可選值（套用其他欄篩選）
        sub = self._v2_iso_df
        for f_col, f_vals in self._v2_live_filters.items():
            if f_col == col or f_col not in sub.columns:
                continue
            clean = [str(v).strip() for v in f_vals]
            sub = sub[
                sub[f_col].astype(str).str.strip().isin(clean)
            ]

        values = sorted(
            sub[col].astype(str).str.strip().unique().tolist()
        )
        values = [v for v in values if v]

        existing = self._v2_col_checked.get(col)

        popup = FilterPopup(self, col, values, checked=existing)
        if popup.exec() == QDialog.DialogCode.Accepted:
            result = popup.result_checked
            if result is None or len(result) == len(values):
                self._v2_col_checked.pop(col, None)
                self._v2_live_filters.pop(col, None)
                info["btn_val"].setText("▼ 全部")
                info["btn_val"].setStyleSheet(
                    self._chip_style(False)
                )
            else:
                self._v2_col_checked[col] = result
                self._v2_live_filters[col] = list(result)
                info["btn_val"].setText(
                    f"✓ 已選 {len(result)} 項"
                )
                info["btn_val"].setStyleSheet(
                    self._chip_style(True)
                )

            self._refresh_preview_table()
            self._v2_update_live_count()
            self._v2_update_filename()

    # 固定顯示欄位（Raw_3D_PipeCode 在最後）
    _PINNED_TAIL = ["Raw_3D_PipeCode"]

    def _diagnostics_visible(self) -> bool:
        return bool(
            getattr(self, "_v2_chk_diagnostics", None)
            and self._v2_chk_diagnostics.isChecked()
        )

    def _set_tab_visible(self, index: int, visible: bool):
        if not hasattr(self, "_v2_preview_tabs"):
            return
        if hasattr(self._v2_preview_tabs, "setTabVisible"):
            self._v2_preview_tabs.setTabVisible(index, visible)
        else:
            self._v2_preview_tabs.setTabEnabled(index, visible)

    def _on_diagnostics_toggled(self):
        self._refresh_preview_table()
        self._v2_update_live_count()

    def _current_output_mode(self) -> str:
        """Return the user-facing output strategy as an internal label."""
        if getattr(self, "_v2_radio_flat", None) and self._v2_radio_flat.isChecked():
            return "flat"
        if getattr(self, "_v2_radio_split", None) and self._v2_radio_split.isChecked():
            return "grouped_split"
        return "grouped_single"

    def _on_output_mode_changed(self):
        """Radio changed: enable the right controls and refresh the planner."""
        mode = self._current_output_mode()
        is_flat = mode == "flat"
        if hasattr(self, "_v2_cbo_group_key"):
            self._v2_cbo_group_key.setEnabled(not is_flat)
        if hasattr(self, "_v2_btn_export"):
            label = "  匯出單一檔  "
            if mode == "grouped_split":
                label = "  匯出多個檔  "
            self._v2_btn_export.setText(label)
        if getattr(self, "_v2_iso_df", None) is not None:
            self._refresh_preview_table()
            self._v2_update_live_count()
            self._v2_update_filename()

    def _get_pinned_head(self) -> list[str]:
        """動態產生表格前端固定欄：流水號 + 分組依據選的欄位。"""
        head = ["流水號"]
        gk = self._current_group_key()
        if gk not in ("__FLAT__", "__ALL__") and gk:
            head.append(gk)
        return head

    def _get_display_columns(self) -> list[str]:
        """取得目前表格要顯示的欄位：固定欄 + 篩選欄 + Raw_3D_PipeCode。

        排列順序：流水號, [分組欄位], [篩選欄位…], Raw_3D_PipeCode
        （若尚未選任何篩選，則顯示全部欄位。）
        """
        avail = getattr(self, "_v2_available_cols", [])
        if not avail:
            return avail

        # 收集使用者選的篩選欄位
        filter_cols: list[str] = []
        for info in self._v2_filter_row_widgets:
            c = info.get("active_col")
            if c and c not in filter_cols:
                filter_cols.append(c)

        if not filter_cols:
            if self._diagnostics_visible():
                return avail
            compact = [
                c
                for c in self._get_pinned_head()
                + ["流水號", "Raw_3D_PipeCode"]
                if c in avail
            ]
            seen: set[str] = set()
            out: list[str] = []
            for c in compact:
                if c not in seen:
                    out.append(c)
                    seen.add(c)
            return out

        # 組合：動態頭 + 篩選欄（去重）+ 固定尾
        seen: set[str] = set()
        cols: list[str] = []
        for c in self._get_pinned_head():
            if c in avail and c not in seen:
                cols.append(c)
                seen.add(c)
        for c in filter_cols:
            if c in avail and c not in seen:
                cols.append(c)
                seen.add(c)
        for c in self._PINNED_TAIL:
            if c in avail and c not in seen:
                cols.append(c)
                seen.add(c)
        return cols

    # ════════════════════════════════════════════════════════
    #  資料預覽表格
    # ════════════════════════════════════════════════════════

    def _get_filtered_df(self):
        """套用全部篩選條件，回傳篩選後 DataFrame。"""
        if self._v2_iso_df is None:
            return None
        sub = self._v2_iso_df
        for col, vals in self._v2_live_filters.items():
            if col not in sub.columns:
                continue
            clean = [str(v).strip() for v in vals]
            sub = sub[sub[col].astype(str).str.strip().isin(clean)]
        return sub

    def _current_group_key(self) -> str:
        """Return the exporter group key sentinel/column for the current UI."""
        if self._current_output_mode() == "flat":
            return "__FLAT__"
        gk_text = self._v2_cbo_group_key.currentText().strip()
        if not gk_text:
            return "流水號"
        return gk_text

    def _build_current_export_result(self, name: str = "preview"):
        """Run the same planner used by file export without writing a file."""
        if self._v2_iso_df is None:
            return None
        from core.json_exporter import JsonExporter

        return JsonExporter().build_case_result(
            self._v2_iso_df,
            {
                "name": name,
                "group_key": self._current_group_key(),
                "filters": dict(self._v2_live_filters),
            },
        )

    def _refresh_preview_table(self):
        """刷新三段預覽：分組摘要、JSON 樣本、明細。"""
        result = self._build_current_export_result()
        self._v2_last_result = result
        if result is None:
            self._clear_preview_tables()
            self._v2_json_preview.setPlainText("")
            self._v2_preview_caption.setText("資料預覽")
            return

        if result.export_rows == 0:
            self._clear_preview_tables()
            self._v2_json_preview.setPlainText(
                "目前沒有可安全匯出的 JSON entry。\n"
                "請調整篩選條件，或先處理 collision / unresolved 列。"
            )
            self._v2_preview_caption.setText("預覽與匯出：沒有可匯出的資料")
            self._v2_preview_tabs.setTabEnabled(0, False)
            self._set_tab_visible(1, self._diagnostics_visible())
            self._v2_preview_tabs.setCurrentIndex(2)
            return

        self._fill_group_summary_table(result)
        self._fill_json_preview(result)
        self._fill_detail_table(result)
        self._set_tab_visible(1, self._diagnostics_visible())

        if result.group_summaries:
            self._v2_preview_caption.setText(
                f"包裹摘要：母資訊 =「{result.group_key}」，"
                f"{result.group_count} 包 / {result.pipe_count} 筆 3D 身分證"
            )
            self._v2_preview_tabs.setTabEnabled(0, True)
            self._v2_preview_tabs.setCurrentIndex(0)
        else:
            self._v2_preview_caption.setText(
                f"包裹明細：{result.pipe_count} 筆 3D 身分證"
            )
            self._v2_preview_tabs.setTabEnabled(0, False)
            self._v2_preview_tabs.setCurrentIndex(2)

    def _clear_preview_tables(self):
        for table in (self._v2_summary_table, self._v2_table):
            table.setRowCount(0)
            table.setColumnCount(0)

    def _fill_detail_table(self, result, subset_df=None):
        """顯示實際會進 JSON 的明細列；摘要點選後也共用這張表。"""
        sub = result.export_df if subset_df is None else subset_df
        cols = [c for c in self._get_display_columns() if c in sub.columns]
        if not cols and len(sub.columns):
            cols = list(sub.columns[:8])
        preview = sub.head(_PREVIEW_MAX_ROWS)
        source_indices = preview.index.tolist()
        display = preview[cols].reset_index(drop=True) if cols else preview
        n_rows = len(display)
        n_cols = len(cols)

        self._v2_table.setRowCount(n_rows)
        self._v2_table.setColumnCount(n_cols)
        self._v2_table.setHorizontalHeaderLabels(cols)

        for r_idx in range(n_rows):
            for c_idx in range(n_cols):
                raw = display.iat[r_idx, c_idx]
                val = "" if (raw is None or str(raw) == "nan") else str(raw)
                item = QTableWidgetItem(val)
                item.setData(Qt.ItemDataRole.UserRole, source_indices[r_idx])
                item.setForeground(Qt.GlobalColor.black)
                if cols[c_idx] in self._v2_live_filters:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._v2_table.setItem(r_idx, c_idx, item)

        self._v2_table.resizeColumnsToContents()
        total = len(sub)
        if total > _PREVIEW_MAX_ROWS:
            self.v2_status_label.setText(
                f"（明細顯示前 {_PREVIEW_MAX_ROWS} 列 / 共 {total} 列）"
            )

    def _fill_json_preview(self, result):
        if not result.entries:
            self._v2_json_preview.setPlainText("[]")
            return
        shown = result.entries[:1]
        text = json.dumps(shown, ensure_ascii=False, indent=2)
        if len(result.entries) > 1:
            text += (
                f"\n\n（僅預覽第一組；實際會輸出 {len(result.entries)} 組）"
            )
        self._v2_json_preview.setPlainText(text)

    def _fill_group_summary_table(self, result):
        """顯示分組後的 JSON 摘要，而不是讓使用者在明細列海裡找答案。"""
        rows = result.group_summaries[:_PREVIEW_MAX_ROWS]
        col_defs = [
            ("母資訊", result.group_key),
            ("包幾個 3D", "3D身分證數"),
            ("包幾個流水號", "流水號數"),
            ("包裹內容（範例）", "範例管線號"),
        ]
        if self._diagnostics_visible():
            col_defs = [
                ("母資訊", result.group_key),
                ("3D身分證數", "3D身分證數"),
                ("流水號數", "流水號數"),
                ("資料列數", "資料列數"),
                ("Path覆蓋率", "Path覆蓋率"),
                ("Root數", "Root數"),
                ("Area覆蓋率", "Area覆蓋率"),
                ("範例管線號", "範例管線號"),
            ]
        col_defs = [
            (label, key)
            for label, key in col_defs
            if any(key in row for row in rows)
        ]
        headers = [label for label, _ in col_defs]

        self._v2_summary_table.blockSignals(True)
        self._v2_summary_table.setRowCount(len(rows))
        self._v2_summary_table.setColumnCount(len(headers))
        self._v2_summary_table.setHorizontalHeaderLabels(headers)

        for r_idx, row in enumerate(rows):
            group_value = str(row.get(result.group_key, "")).strip()
            for c_idx, (label, key) in enumerate(col_defs):
                val = str(row.get(key, "")).strip()
                item = QTableWidgetItem(val)
                item.setForeground(Qt.GlobalColor.black)
                item.setData(Qt.ItemDataRole.UserRole, group_value)
                if key == result.group_key:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._v2_summary_table.setItem(r_idx, c_idx, item)

        self._v2_summary_table.resizeColumnsToContents()
        self._v2_summary_table.blockSignals(False)

    def _on_summary_selection_changed(self):
        result = getattr(self, "_v2_last_result", None)
        if result is None or not result.group_summaries:
            return
        selected = self._v2_summary_table.selectedItems()
        if not selected:
            return
        row_idx = selected[0].row()
        first_item = self._v2_summary_table.item(row_idx, 0)
        if first_item is None:
            return
        group_value = str(first_item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not group_value or result.group_key not in result.export_df.columns:
            return
        sub = result.export_df[
            result.export_df[result.group_key].astype(str).str.strip().eq(group_value)
        ]
        self._fill_detail_table(result, subset_df=sub)
        self._v2_preview_tabs.setCurrentIndex(2)
        self._v2_preview_caption.setText(
            f"包裹明細：母資訊「{group_value}」包了 "
            f"{len(sub)} 列資料"
        )

    def _on_preview_context_menu(self, pos):
        item = self._v2_table.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._v2_table)
        act_trace = menu.addAction("追蹤這條")
        chosen = menu.exec(self._v2_table.viewport().mapToGlobal(pos))
        if chosen == act_trace:
            self._open_preview_trace(item.row())

    def _open_preview_trace(self, row: int):
        if self._v2_iso_df is None or row < 0:
            return
        item = self._v2_table.item(row, 0)
        if item is None:
            return
        source_idx = item.data(Qt.ItemDataRole.UserRole)
        try:
            record = self._v2_iso_df.loc[source_idx]
        except Exception:
            return
        trace = str(record.get("IdentityReason", "")).strip()
        if not trace:
            QMessageBox.information(self, "Trace", "這筆資料沒有 IdentityReason trace。")
            return
        pipe_code = (
            str(record.get("管線編號", "")).strip()
            or str(record.get("ISO_Match_Key", "")).strip()
            or str(record.get("Raw_3D_PipeCode", "")).strip()
        )
        dlg = TraceViewerDialog(
            self,
            spool_no=str(record.get("流水號", "")).strip(),
            pipe_code=pipe_code,
            trace_str=trace,
        )
        dlg.exec()

    # ════════════════════════════════════════════════════════
    #  統計 & 檔名
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _coverage_piece(label: str, coverage: dict) -> str:
        total = int(coverage.get("total", 0) or 0)
        with_value = int(coverage.get("with", 0) or 0)
        percent = float(coverage.get("percent", 0) or 0)
        return f"{label} {with_value}/{total} ({percent:g}%)"

    def _update_source_health(self, result=None):
        """來源健康狀態：攔截原因與 scope 覆蓋率。"""
        if result is None:
            result = getattr(self, "_v2_last_result", None)
        if result is None:
            return

        diagnostics = self._diagnostics_visible()
        bb = result.blocked_breakdown or {}
        blocked = result.blocked_rows
        if not diagnostics:
            self._v2_lbl_scope.setVisible(False)
            if blocked:
                self._v2_lbl_blocked.setText(
                    f"有 {blocked} 列未進 JSON；勾「診斷」可看原因。"
                )
                self._v2_lbl_blocked.setStyleSheet(
                    "color: #D97706; font-size: 11px; font-weight: 600;"
                )
                self._v2_lbl_blocked.setVisible(True)
            else:
                self._v2_lbl_blocked.setVisible(False)
            return

        self._v2_lbl_blocked.setVisible(True)
        self._v2_lbl_scope.setVisible(True)
        if blocked:
            bits = [
                f"未解析 {int(bb.get('unresolved', 0))}",
                f"待決策 {int(bb.get('needs_decision', 0))}",
                f"缺 raw {int(bb.get('missing_raw', 0))}",
            ]
            other = int(bb.get("other", 0))
            if other:
                bits.append(f"其他 {other}")
            narrowed = int(bb.get("narrowed_collision", 0))
            if narrowed:
                bits.append(f"範圍已縮小 collision {narrowed}")
            self._v2_lbl_blocked.setText(
                f"攔截 {blocked}：{' / '.join(bits)}"
            )
            self._v2_lbl_blocked.setStyleSheet(
                "color: #D97706; font-size: 11px; font-weight: 600;"
            )
        else:
            narrowed = int(bb.get("narrowed_collision", 0))
            suffix = f"（含範圍已縮小 collision {narrowed}）" if narrowed else ""
            self._v2_lbl_blocked.setText(f"攔截 0：目前篩選可安全匯出{suffix}")
            self._v2_lbl_blocked.setStyleSheet(
                f"color: {C_SUCCESS}; font-size: 11px; font-weight: 600;"
            )

        sc = result.scope_coverage or {}
        self._v2_lbl_scope.setText(
            "範圍覆蓋："
            + " · ".join(
                [
                    self._coverage_piece("Path", sc.get("PipeNodePath", {})),
                    self._coverage_piece("Root", sc.get("ScopeRoot", {})),
                    self._coverage_piece("Area", sc.get("ParentArea", {})),
                ]
            )
        )
        self._v2_lbl_scope.setStyleSheet(
            "color: #475569; font-size: 11px;"
        )

    def _v2_update_live_count(self):
        """即時計算篩選後的列數並更新底部標籤。"""
        if self._v2_iso_df is None:
            self._v2_lbl_count.setText("尚未載入")
            return

        result = self._build_current_export_result()
        if result is None:
            self._v2_lbl_count.setText("尚未載入")
            return

        self._update_source_health(result)

        if result.filtered_rows == 0:
            self._v2_lbl_count.setText(f"⚠ 0 / {result.source_rows} 列符合")
            self._v2_lbl_count.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                f" color: {C_ERROR};"
            )
            if hasattr(self, "_v2_btn_export"):
                self._v2_btn_export.setText("  匯出單一檔  ")
            return

        if result.export_rows == 0:
            self._v2_lbl_count.setText(
                f"⚠ 0 列可匯出（已擋 {result.blocked_rows} 列）"
            )
            self._v2_lbl_count.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                f" color: {C_ERROR};"
            )
            if hasattr(self, "_v2_btn_export"):
                self._v2_btn_export.setText("  匯出單一檔  ")
            return

        diagnostics = self._diagnostics_visible()
        package_word = "包" if result.group_summaries else "筆"
        parts = [
            f"✓ {result.group_count} {package_word}",
            f"包住 {result.pipe_count} 筆 3D 身分證",
        ]
        if diagnostics:
            parts.insert(0, f"可匯出 {result.export_rows} / {result.source_rows} 列")
            if result.scope_count:
                parts.append(f"{result.scope_count} 筆 scope")
        elif result.blocked_rows:
            parts.append(f"{result.blocked_rows} 列未匯出")

        self._v2_lbl_count.setText("  |  ".join(parts))
        self._v2_lbl_count.setStyleSheet(
            "font-size: 12px; font-weight: 600;"
            f" color: {C_SUCCESS};"
        )
        if hasattr(self, "_v2_btn_export"):
            if self._current_output_mode() == "grouped_split":
                self._v2_btn_export.setText(
                    f"  匯出 {result.group_count} 個檔  "
                )
            else:
                self._v2_btn_export.setText("  匯出單一檔  ")
        if result.blocked_rows:
            bb = result.blocked_breakdown or {}
            if diagnostics:
                self.v2_status_label.setText(
                    "預覽已套用安全檢查："
                    f"未解析 {int(bb.get('unresolved', 0))} / "
                    f"待決策 {int(bb.get('needs_decision', 0))} / "
                    f"缺 raw {int(bb.get('missing_raw', 0))}"
                )
            else:
                self.v2_status_label.setText(
                    f"有 {result.blocked_rows} 列不會匯出；目前摘要只顯示會進 JSON 的包裹。"
                )
            self.v2_status_label.setStyleSheet(
                "color: #D97706; font-size: 11px; font-weight: 600;"
            )
        else:
            if result.group_summaries:
                preview = "、".join(
                    f"{row.get(result.group_key, '')}={row.get('3D身分證數', 0)}"
                    for row in result.group_summaries[:6]
                )
                suffix = (
                    ""
                    if len(result.group_summaries) <= 6
                    else f"、... 共 {len(result.group_summaries)} 組"
                )
                self.v2_status_label.setText(
                    f"母資訊：{result.group_key}；包裹數：{preview}{suffix}"
                )
                self.v2_status_label.setStyleSheet(
                    "color: #475569; font-size: 11px;"
                )
                return
            self.v2_status_label.setText(
                f"輸出模式：{result.output_mode}，母資訊：{result.group_key}"
            )
            self.v2_status_label.setStyleSheet(
                "color: #475569; font-size: 11px;"
            )

    def _v2_update_filename(self):
        """依篩選值、分組欄位與輸出模式產生較可稽核的檔名。"""
        from utils.utils_common import CommonUtils

        parts: list[str] = []
        for info in self._v2_filter_row_widgets:
            col = info.get("active_col")
            if col and col in self._v2_live_filters:
                vals = [
                    str(v).strip()
                    for v in self._v2_live_filters.get(col, [])
                    if str(v).strip()
                ]
                if vals:
                    shown = "_".join(vals[:3]) if len(vals) <= 3 else f"{len(vals)}values"
                    parts.append(f"{col}-{shown}")

        mode = self._current_output_mode()
        gk = self._current_group_key()
        if not parts:
            parts.append("live_selection")
        if mode != "flat" and gk not in ("__FLAT__", "__ALL__"):
            parts.append(f"by-{gk}")
        if mode == "flat":
            parts.append("flat")
        elif mode == "grouped_split":
            parts.append("split")

        self.v2_txt_filename.setText(
            CommonUtils.sanitize_filename("__".join(parts))
        )

    # ════════════════════════════════════════════════════════
    #  匯出 JSON
    # ════════════════════════════════════════════════════════

    def _v2_live_preview(self):
        """相容舊呼叫。"""
        self._v2_update_live_count()

    def _v2_live_export(self):
        """以目前篩選條件匯出 JSON 檔。"""
        if self._v2_iso_df is None:
            QMessageBox.warning(
                self,
                "提示",
                "請先載入資料來源\n"
                "（點擊「自動載入」或「選擇檔案」）。",
            )
            return

        # 確認至少有可匯出的結果；這裡和預覽表格使用同一套規則。
        result = self._build_current_export_result(
            self.v2_txt_filename.text().strip() or "live_selection"
        )
        if result is None or result.filtered_rows == 0:
            QMessageBox.warning(
                self,
                "篩選結果為空",
                "目前篩選條件沒有任何資料。\n"
                "請調整篩選欄位後再匯出。",
            )
            return
        if result.export_rows == 0:
            QMessageBox.warning(
                self,
                "沒有可安全匯出的資料",
                "目前符合篩選的資料都尚未 resolved 或仍需 collision 決策。\n"
                "請先處理衝突，或調整篩選範圍。",
            )
            return

        # 取得輸出目錄
        try:
            cfg = self._get_paths()
            base_dir = cfg["base_dir"]
        except Exception:
            base_dir = (
                os.path.dirname(
                    getattr(self, "_v2_source_path", "")
                )
                or os.getcwd()
            )

        name = self.v2_txt_filename.text().strip() or "live_selection"
        filters = dict(self._v2_live_filters)

        group_key = self._current_group_key()
        output_mode = self._current_output_mode()

        from utils.utils_common import FileLogger
        from utils.utils_common import CommonUtils

        logger = (
            FileLogger(base_dir)
            if self.chk_file_log.isChecked()
            else None
        )

        from core.json_exporter import JsonExporter

        exporter = JsonExporter(logger=logger)

        iso_path = getattr(self, "_v2_source_path", None)
        if not iso_path:
            QMessageBox.warning(self, "提示", "尚未載入資料來源。")
            return

        try:
            cases = [
                {
                    "name": name,
                    "group_key": group_key,
                    "filters": filters,
                }
            ]
            if output_mode == "grouped_split":
                if group_key in ("__FLAT__", "__ALL__") or not result.group_summaries:
                    QMessageBox.warning(
                        self,
                        "無法分檔匯出",
                        "請選擇分組欄位，並確認目前篩選後有分組摘要。",
                    )
                    return
                cases = []
                for row in result.group_summaries:
                    group_value = str(row.get(group_key, "")).strip()
                    if not group_value:
                        continue
                    case_filters = dict(filters)
                    case_filters[group_key] = [group_value]
                    cases.append(
                        {
                            "name": CommonUtils.sanitize_filename(
                                f"{name}__{group_key}-{group_value}"
                            ),
                            "group_key": group_key,
                            "filters": case_filters,
                        }
                    )
                if not cases:
                    QMessageBox.warning(
                        self,
                        "無法分檔匯出",
                        "目前分組摘要沒有任何有效分組值。",
                    )
                    return

            n = exporter.export_json_v2(
                iso_match_path=iso_path,
                cases=cases,
                out_dir=base_dir,
            )
            if n > 0:
                if output_mode == "grouped_split":
                    msg = f"✅ 已匯出 {n} 個 JSON 檔"
                else:
                    msg = f"✅ 已匯出 → {name}.json"
                self.v2_status_label.setText(msg)
                self.v2_status_label.setStyleSheet(
                    f"color: {C_SUCCESS}; font-size: 12px;"
                    " font-weight: 600;"
                )
            else:
                self.v2_status_label.setText("⚠ 沒有符合的資料，未匯出。")
                self.v2_status_label.setStyleSheet(
                    f"color: {C_ERROR}; font-size: 11px;"
                )
        except Exception as e:
            self.v2_status_label.setText(f"❌ 匯出失敗：{e}")
            self.v2_status_label.setStyleSheet(
                f"color: {C_ERROR}; font-size: 11px;"
            )

    # ════════════════════════════════════════════════════════
    #  清除全部篩選
    # ════════════════════════════════════════════════════════

    def _v2_clear_all_filters(self):
        """重設所有篩選列。"""
        self._v2_live_filters = {}
        self._v2_col_checked = {}
        for info in self._v2_filter_row_widgets:
            info["cbo_col"].blockSignals(True)
            info["cbo_col"].setCurrentIndex(0)
            info["cbo_col"].blockSignals(False)
            info["active_col"] = None
            info["btn_val"].setVisible(False)
            info["btn_val"].setText("▼ 選擇值")
        if self._v2_iso_df is not None:
            self._refresh_preview_table()
        self._v2_update_live_count()
        self._v2_update_filename()
        self.v2_status_label.setText("")

    # ════════════════════════════════════════════════════════
    #  相容舊 API
    # ════════════════════════════════════════════════════════

    def _v2_load_fields_from_iso_match(self):
        """（相容舊呼叫）等同 _v2_auto_load_source。"""
        self._v2_auto_load_source()
