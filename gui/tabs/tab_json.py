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

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

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

        self._v2_lbl_source = QLabel("尚未載入資料")
        self._v2_lbl_source.setStyleSheet(
            "color: #64748B; font-size: 12px;"
        )
        self._v2_lbl_source.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        tb_lay.addWidget(self._v2_lbl_source)

        btn_auto = QPushButton("自動載入")
        btn_auto.setToolTip("從專案目錄自動尋找 iso_match.xlsx")
        btn_auto.setFixedHeight(28)
        btn_auto.clicked.connect(self._v2_auto_load_source)
        tb_lay.addWidget(btn_auto)

        btn_browse = QPushButton("選擇檔案…")
        btn_browse.setFixedHeight(28)
        btn_browse.clicked.connect(self._v2_browse_source)
        tb_lay.addWidget(btn_browse)

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

        # ── 篩選列 1/2/3 ──
        _FILTER_LABELS = ["母篩選", "篩選 2", "篩選 3"]
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
                btn_reset = QPushButton("✕ 重設全部")
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

            ctrl_lay.addLayout(frow)

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

        # ── 分隔線 ──
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.Shape.HLine)
        sep_line.setFixedHeight(1)
        sep_line.setStyleSheet("background: #E2E8F0;")
        ctrl_lay.addWidget(sep_line)

        # ── 分組依據 ──
        gk_row = QHBoxLayout()
        gk_row.setSpacing(6)
        lbl_gk = QLabel("分組依據")
        lbl_gk.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #475569;"
        )
        lbl_gk.setFixedWidth(56)
        gk_row.addWidget(lbl_gk)
        self._v2_cbo_group_key = QComboBox()
        self._v2_cbo_group_key.setFixedWidth(150)
        self._v2_cbo_group_key.setToolTip(
            "JSON 輸出時依此欄位分組\n"
            "預設「群組」，可改為尺寸、系統等\n"
            "選「— 不分組（平面清單）」則純列出 Raw_3D_PipeCode"
        )
        self._v2_cbo_group_key.currentIndexChanged.connect(
            lambda: (
                self._refresh_preview_table(),
                self._v2_update_live_count(),
            )
        )
        gk_row.addWidget(self._v2_cbo_group_key)
        gk_row.addStretch()
        ctrl_lay.addLayout(gk_row)

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
        ctrl_lay.addLayout(fn_row)

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
            ' line-height: 1.6; font-size: 12px; color: #1E293B;">'
            #
            '<p style="margin:0 0 6px; font-size:13px;'
            ' font-weight:700; color:#92400E;">'
            "📖 操作說明</p>"
            #
            "<p style='margin:0 0 4px;'>"
            "<b>① 母篩選</b>（＝分組依據 / 資料夾名稱）<br>"
            "&nbsp;&nbsp;選擇欄位 → 點『選擇值』→ "
            "勾選要保留的值。<br>"
            "&nbsp;&nbsp;範例：母篩選＝<b>群組</b>，"
            "勾 AC、AD → 只留這 2 組。<br>"
            "&nbsp;&nbsp;匯出時會以<b>母篩選欄位</b>"
            "做為 JSON 分組 key。</p>"
            #
            "<p style='margin:0 0 4px;'>"
            "<b>② 篩選 2 / 篩選 3</b>（加碼條件）<br>"
            "&nbsp;&nbsp;在母篩選基礎上再交叉篩選。<br>"
            "&nbsp;&nbsp;範例：篩選 2＝<b>系統</b>，"
            "勾「一次側」→ 只要 AC+AD 且是一次側。</p>"
            #
            "<p style='margin:0 0 4px;'>"
            "<b>③ 表格預覽</b><br>"
            "┌──────┬──────┬─────┬──────────┐<br>"
            "│ 流水號 │ 群組 │ 篩選欄 │ Raw_3D_PipeCode │<br>"
            "└──────┴──────┴─────┴──────────┘<br>"
            "&nbsp;&nbsp;固定顯示：流水號、群組 → "
            "中間放篩選欄 → 最右是 Raw_3D_PipeCode</p>"
            #
            "<p style='margin:0 0 4px;'>"
            "<b>④ 匯出 JSON</b><br>"
            "&nbsp;&nbsp;檔名可自訂（預設依篩選欄自動命名）。<br>"
            "&nbsp;&nbsp;輸出格式：<br>"
            '<span style="font-family: Consolas, monospace;'
            ' font-size: 11px; color: #0369A1;">'
            "&nbsp;&nbsp;[{&quot;群組&quot;:&quot;AC&quot;,"
            " &quot;管線號&quot;:[&quot;/AC-001&quot;,...]}]"
            "</span></p>"
            #
            "<p style='margin:0 0 0; color:#6B7280;'>"
            "💡 母篩選未選時，預設以「群組」分組。<br>"
            "💡 點「✕ 重設全部」可一鍵清空所有篩選。</p>"
            "</div>"
        )
        help_browser.setFixedWidth(310)

        # ── 組合：左控制 + 右說明 ──
        ctrl_and_help = QHBoxLayout()
        ctrl_and_help.setSpacing(8)
        ctrl_and_help.addWidget(ctrl_panel, stretch=1)
        ctrl_and_help.addWidget(help_browser)

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
        self._v2_table = QTableWidget()
        self._v2_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._v2_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._v2_table.setAlternatingRowColors(True)
        self._v2_table.horizontalHeader().setStretchLastSection(
            True
        )
        self._v2_table.verticalHeader().setDefaultSectionSize(24)
        self._v2_table.setStyleSheet(
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
        lay.addWidget(self._v2_table, stretch=1)
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

        btn_export = QPushButton("  匯出 JSON  ")
        btn_export.setObjectName("btnExport")
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setFixedHeight(34)
        btn_export.clicked.connect(self._v2_live_export)
        bot_lay.addWidget(btn_export)

        lay.addWidget(bot_frame)

        self.pages.addWidget(page)

        # ── 內部狀態 ──
        self._v2_col_checked: dict[str, set[str] | None] = {}
        self._v2_cat_cols: list[str] = []  # 可篩選的分類欄位
        # 向後相容別名 / 空列表
        self.v2_cbo_group_key = self._v2_cbo_group_key
        self.v2_filter_field_cbos = []
        self.v2_filter_value_listboxes = []

    # ════════════════════════════════════════════════════════
    #  資料來源
    # ════════════════════════════════════════════════════════

    def _v2_auto_load_source(self):
        """自動從專案目錄載入 iso_match.xlsx。"""
        try:
            cfg = self._get_paths()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return

        iso_path = cfg["iso_match_xlsx"]
        if not os.path.exists(iso_path):
            QMessageBox.warning(
                self,
                "找不到檔案",
                "iso_match.xlsx 不存在。\n"
                "請先執行 Step3 產出比對結果，"
                "或點擊「選擇檔案」手動指定。",
            )
            return
        self._v2_load_source(iso_path)

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
        self._v2_lbl_source.setText(
            f"📄 {fname}    {row_count} 列 × {col_count} 欄{raw_info}"
        )
        self._v2_lbl_source.setStyleSheet(
            f"color: {C_PRIMARY}; font-weight: 600;"
            " font-size: 12px;"
        )

        # 群組 toggle
        has_group = "群組" in cols
        self.v2_chk_group.setEnabled(has_group)
        self.v2_chk_group.setChecked(has_group)

        # 建立可篩選的分類欄位清單（唯一值 < 50）
        _CAT_THRESHOLD = 50
        # 固定欄位一定要出現在選單中
        _PINNED = ["流水號", "群組"]
        cat_cols = [
            c for c in cols
            if df[c].nunique() < _CAT_THRESHOLD or c in _PINNED
        ]
        if not cat_cols:
            cat_cols = cols[:8]
        self._v2_cat_cols = cat_cols

        # 填充分組依據下拉
        self._v2_cbo_group_key.blockSignals(True)
        self._v2_cbo_group_key.clear()
        self._v2_cbo_group_key.addItem("— 不分組（平面清單）")
        self._v2_cbo_group_key.addItems(cat_cols)
        # 預設選「群組」
        if "群組" in cat_cols:
            self._v2_cbo_group_key.setCurrentText("群組")
        self._v2_cbo_group_key.blockSignals(False)

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
        self._help_browser.setVisible(True)

        # 填充表格 & 統計
        self._refresh_preview_table()
        self._v2_update_live_count()

        self.v2_status_label.setText(
            "✓ 已載入，選擇篩選欄位後點擊『選擇值』"
        )
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

    def _get_pinned_head(self) -> list[str]:
        """動態產生表格前端固定欄：流水號 + 分組依據選的欄位。"""
        head = ["流水號"]
        gk = self._v2_cbo_group_key.currentText().strip()
        if not gk.startswith("—") and gk:
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
            return avail  # 無篩選 → 顯示全部

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

    def _refresh_preview_table(self):
        """刷新資料預覽表格內容。"""
        sub = self._get_filtered_df()
        if sub is None or len(sub) == 0:
            self._v2_table.setRowCount(0)
            self._v2_table.setColumnCount(0)
            return

        cols = [
            c for c in self._get_display_columns()
            if c in sub.columns
        ]
        display = sub[cols].head(_PREVIEW_MAX_ROWS).reset_index(drop=True)
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
                item.setForeground(Qt.GlobalColor.black)
                # 被篩選的欄位 → 粗體標記
                if cols[c_idx] in self._v2_live_filters:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._v2_table.setItem(r_idx, c_idx, item)

        self._v2_table.resizeColumnsToContents()

        # 超過預覽上限提示
        total = len(sub)
        if total > _PREVIEW_MAX_ROWS:
            self.v2_status_label.setText(
                f"（顯示前 {_PREVIEW_MAX_ROWS} 列 / 共 {total} 列）"
            )

    # ════════════════════════════════════════════════════════
    #  統計 & 檔名
    # ════════════════════════════════════════════════════════

    def _v2_update_live_count(self):
        """即時計算篩選後的列數並更新底部標籤。"""
        if self._v2_iso_df is None:
            self._v2_lbl_count.setText("尚未載入")
            return

        total = len(self._v2_iso_df)
        sub = self._get_filtered_df()
        filtered = len(sub) if sub is not None else total

        if not self._v2_live_filters:
            self._v2_lbl_count.setText(f"全部 {total} 列")
            self._v2_lbl_count.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                " color: #64748B;"
            )
        elif filtered == 0:
            self._v2_lbl_count.setText("⚠ 0 列符合")
            self._v2_lbl_count.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                f" color: {C_ERROR};"
            )
        else:
            raw_info = ""
            if sub is not None and "Raw_3D_PipeCode" in sub.columns:
                raw_n = sub["Raw_3D_PipeCode"].nunique()
                raw_info = f"（{raw_n} 筆管線）"
            self._v2_lbl_count.setText(
                f"✓ {filtered} / {total} 列{raw_info}"
            )
            self._v2_lbl_count.setStyleSheet(
                "font-size: 12px; font-weight: 600;"
                f" color: {C_SUCCESS};"
            )

    def _v2_update_filename(self):
        """依篩選欄位名稱自動更新檔名，例如「系統_材質」。"""
        parts = []
        for info in self._v2_filter_row_widgets:
            col = info.get("active_col")
            if col and col in self._v2_live_filters:
                parts.append(col)
        if parts:
            self.v2_txt_filename.setText("_".join(parts))
        else:
            self.v2_txt_filename.setText("live_selection")

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

        # 確認至少有結果
        sub = self._get_filtered_df()
        if sub is None or len(sub) == 0:
            QMessageBox.warning(
                self,
                "篩選結果為空",
                "目前篩選條件沒有任何資料。\n"
                "請調整篩選欄位後再匯出。",
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

        # group_key 從「分組依據」下拉取得
        gk_text = self._v2_cbo_group_key.currentText().strip()
        if gk_text.startswith("—") or not gk_text:
            group_key = "__FLAT__"  # 不分組
        else:
            group_key = gk_text

        from utils.utils_common import FileLogger

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
            n = exporter.export_json_v2(
                iso_match_path=iso_path,
                cases=[
                    {
                        "name": name,
                        "group_key": group_key,
                        "filters": filters,
                    }
                ],
                out_dir=base_dir,
            )
            if n > 0:
                self.v2_status_label.setText(
                    f"✅ 已匯出 → {name}.json"
                )
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
