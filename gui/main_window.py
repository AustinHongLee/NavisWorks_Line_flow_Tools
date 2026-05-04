# -*- coding: utf-8 -*-
"""MainWindow — 程式主視窗。

Modern Industrial Dashboard 佈局：
  左側 220px 暗色 sidebar（導航 + 狀態 + 動作）
  右側 content area（StepperBar + AnimatedStackedWidget + 進度 + 紀錄）
"""
from __future__ import annotations

import os

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.theme import (
    APP_TITLE, WINDOW_H, WINDOW_W, SIDEBAR_W,
    C_ERROR, C_SUCCESS,
)
from gui.widgets import AnimatedStackedWidget, CollapsibleSection, StepperBar
from gui.worker import PipelineWorker
from gui.dialogs.fuzzy_match_dialog import FuzzyMatchDialog
from gui.dialogs.project_setup_dialog import ProjectSetupDialog
from gui.dialogs.iso_setup_dialog import IsoSetupDialog
from gui.tabs.tab_pipeline import PipelineTabMixin
from gui.tabs.tab_json import JsonTabMixin


_NAV_ITEMS = [
    ("📁", "專案設定"),
    ("🔗", "ISO 比對"),
    ("📤", "JSON 匯出"),
]

_STEPPER_LABELS = ["專案設定", "ISO 比對", "JSON 匯出"]


class MainWindow(QMainWindow, PipelineTabMixin, JsonTabMixin):
    """管線流程工具 v4 主視窗。"""

    def __init__(
        self,
        dlldir: str | None = None,
        first_try_source: str | None = None,
    ):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1060, 680)
        self.resize(WINDOW_W, WINDOW_H)

        self._worker = None
        self._iso_match_df = None
        self._v2_iso_df = None
        self._v2_live_filters: dict = {}

        # Navis 模式參數（延遲到 show 之後處理）
        self._navis_dlldir = dlldir
        self._navis_first_try = first_try_source

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        root.addWidget(self._build_sidebar())

        # ── Content Area ──
        content_w = QWidget()
        content = QVBoxLayout(content_w)
        content.setContentsMargins(24, 16, 24, 16)
        content.setSpacing(16)

        self.stepper = StepperBar(_STEPPER_LABELS)
        self.stepper.step_clicked.connect(self._on_step_clicked)
        content.addWidget(self.stepper)

        self.pages = AnimatedStackedWidget(duration=150)
        self._build_page_project()   # Page 0
        self._build_page_iso()       # Page 1
        self._build_page_json()      # Page 2
        content.addWidget(self.pages, stretch=1)

        content.addWidget(self._build_progress_bar())
        content.addWidget(self._build_log_section())

        root.addWidget(content_w, stretch=1)

        # 初始狀態
        self._update_file_status()

        # Navis 模式：延遲啟動設定流程
        if self._navis_dlldir and self._navis_first_try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._run_navis_setup)

    # ════════════════════════════════════════
    #  Sidebar
    # ════════════════════════════════════════

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_W)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(8)

        # Title
        title = QLabel("管線流程工具")
        title.setObjectName("sidebarTitle")
        lay.addWidget(title)
        ver = QLabel("v4")
        ver.setObjectName("sidebarVersion")
        lay.addWidget(ver)
        lay.addSpacing(12)

        # Navigation
        self._nav_btns: list[QPushButton] = []
        for i, (icon, text) in enumerate(_NAV_ITEMS):
            btn = QPushButton(f"  {icon}  {text}")
            btn.setProperty("class", "sidebar-nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, idx=i: self._on_nav_clicked(idx)
            )
            lay.addWidget(btn)
            self._nav_btns.append(btn)
        self._nav_btns[0].setChecked(True)

        lay.addSpacing(8)
        div1 = QFrame()
        div1.setProperty("class", "sidebar-divider")
        div1.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(div1)
        lay.addSpacing(4)

        # Status section
        sec_lbl = QLabel("檔案狀態")
        sec_lbl.setObjectName("sidebarSection")
        lay.addWidget(sec_lbl)
        lay.addSpacing(2)

        self.lbl_first_status = QLabel("⬜ 請先選擇專案目錄")
        self.lbl_first_status.setProperty("class", "sb-neutral")
        lay.addWidget(self.lbl_first_status)

        self.lbl_iso_status = QLabel("⬜ 請先選擇專案目錄")
        self.lbl_iso_status.setProperty("class", "sb-neutral")
        lay.addWidget(self.lbl_iso_status)

        self.lbl_iso_detail = QLabel("")
        self.lbl_iso_detail.setProperty("class", "sb-neutral")
        self.lbl_iso_detail.setVisible(False)
        lay.addWidget(self.lbl_iso_detail)

        self.lbl_config_status = QLabel("⬜ 請先選擇專案目錄")
        self.lbl_config_status.setProperty("class", "sb-neutral")
        lay.addWidget(self.lbl_config_status)

        self.lbl_ready = QLabel("")
        self.lbl_ready.setProperty("class", "sb-ready")
        self.lbl_ready.setVisible(False)
        lay.addWidget(self.lbl_ready)

        lay.addStretch()

        # Divider
        div2 = QFrame()
        div2.setProperty("class", "sidebar-divider")
        div2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(div2)
        lay.addSpacing(8)

        # Action section
        self.btn_run_all = QPushButton("▶  執行全部")
        self.btn_run_all.setObjectName("sidebarRunAll")
        self.btn_run_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_all.clicked.connect(self._on_run_all)
        lay.addWidget(self.btn_run_all)

        btn_cleanup = QPushButton("🗑  清理中間檔")
        btn_cleanup.setObjectName("sidebarCleanup")
        btn_cleanup.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cleanup.clicked.connect(self._on_cleanup)
        lay.addWidget(btn_cleanup)

        self.chk_auto_cleanup = QCheckBox("Step3 後自動清理")
        self.chk_auto_cleanup.setObjectName("sidebarCheck")
        self.chk_auto_cleanup.setChecked(True)
        lay.addWidget(self.chk_auto_cleanup)

        return sidebar

    # ════════════════════════════════════════
    #  Bottom area
    # ════════════════════════════════════════

    def _build_progress_bar(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(4)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        vl.addWidget(self.progress_bar)
        self.lbl_progress = QLabel("尚未執行")
        self.lbl_progress.setStyleSheet("color: #94A3B8; font-size: 12px;")
        vl.addWidget(self.lbl_progress)
        return w

    def _build_log_section(self) -> CollapsibleSection:
        section = CollapsibleSection("執行紀錄")
        self.txt_log = QTextEdit()
        self.txt_log.setObjectName("logBox")
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(100)
        self.txt_log.setMaximumHeight(200)
        section.add_widget(self.txt_log)
        return section

    # ════════════════════════════════════════
    #  Navigation
    # ════════════════════════════════════════

    def _on_nav_clicked(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self.pages.fade_to(idx)
        self.stepper.set_current(idx)

    def _on_step_clicked(self, idx: int):
        self._on_nav_clicked(idx)

    # ════════════════════════════════════════
    #  Navis 啟動流程
    # ════════════════════════════════════════

    def _run_navis_setup(self):
        """Navis 模式啟動流程：專案設定 → ISO 欄位設定 → 自動執行。"""
        # Step 1: 專案初始化（建立工作區 + 複製檔案）
        setup_dlg = ProjectSetupDialog(
            self,
            dlldir=self._navis_dlldir,
            first_try_source=self._navis_first_try,
        )
        if setup_dlg.exec() != QDialog.DialogCode.Accepted:
            self._log("使用者取消專案初始化。")
            return

        project_dir = setup_dlg.project_dir
        iso_dest = setup_dlg.iso_list_dest

        # 回寫到 UI
        self.txt_base_dir.setText(project_dir)
        self.txt_first_name.setText("First_try.csv")
        self.txt_iso_path.setText(iso_dest)
        self._log(f"工作區已建立：{project_dir}")
        self._log("First_try.csv 已匯入")
        self._log(f"ISO LIST 已匯入：{os.path.basename(iso_dest)}")

        # Step 2: ISO 欄位設定
        iso_dlg = IsoSetupDialog(self, iso_dest)
        if iso_dlg.exec() != QDialog.DialogCode.Accepted:
            self._log("使用者取消 ISO 設定，可稍後手動設定後執行。")
            self._update_file_status()
            return

        # 回寫 ISO 設定到 UI
        self.cbo_iso_sheet.blockSignals(True)
        self.cbo_iso_sheet.clear()
        try:
            xls = pd.ExcelFile(iso_dest, engine="openpyxl")
            self.cbo_iso_sheet.addItems(xls.sheet_names)
        except Exception:
            pass
        self.cbo_iso_sheet.setCurrentText(iso_dlg.iso_sheet)
        self.cbo_iso_sheet.blockSignals(False)

        # 載入該工作表的欄位到 combo
        self._on_sheet_selected(iso_dlg.iso_sheet)

        # 覆寫為使用者選定的值
        self.cbo_pipe_col.setCurrentText(iso_dlg.pipe_col)
        self.cbo_spool_col.setCurrentText(iso_dlg.spool_col)
        self.cbo_category_col.setCurrentText(iso_dlg.category_col)

        self._update_file_status()
        self._log(f"ISO 設定完成：工作表={iso_dlg.iso_sheet}，"
                  f"管線={iso_dlg.pipe_col}，流水號={iso_dlg.spool_col}")
        self._log("──────────────────────────────────────")
        self._log("✓ 初始化完成，開始自動執行全部流程…")

        # Step 3: 自動執行
        self._on_run_all()

    # ════════════════════════════════════════
    #  Helper methods
    # ════════════════════════════════════════

    def _get_base_dir(self) -> str:
        return self.txt_base_dir.text().strip()

    def _get_paths(self) -> dict:
        base = self._get_base_dir()
        if not base:
            raise ValueError("請先設定『專案根目錄』。")
        first = self.txt_first_name.text().strip() or "First_try.csv"
        return {
            "base_dir": base,
            "first_csv": os.path.join(base, first),
            "minus1_csv": os.path.join(base, "123_minus_1.csv"),
            "minus2_csv": os.path.join(base, "123_minus_2.csv"),
            "minus2_xlsx": os.path.join(base, "123_minus_2.xlsx"),
            "iso_match_xlsx": os.path.join(base, "iso_match.xlsx"),
            "resolved_mapping_csv": os.path.join(base, "resolved_mapping.csv"),
        }

    def _log(self, msg: str):
        self.txt_log.append(msg)
        # 如果啟用檔案紀錄
        if self.chk_file_log.isChecked():
            base = self._get_base_dir()
            if base:
                from utils.utils_common import FileLogger
                FileLogger(base).append(msg)

    def _set_running(self, running: bool):
        self.btn_run_all.setEnabled(not running)
        if running:
            self._run_btn_orig_text = self.btn_run_all.text()
            self.btn_run_all.setText("⏳ 處理中…")
        else:
            self.btn_run_all.setText(
                getattr(self, "_run_btn_orig_text", "▶  執行全部")
            )

    def _get_extra_headers(self) -> list[str]:
        result = []
        for i in range(self.list_header_selected.count()):
            item = self.list_header_selected.item(i)
            text = item.text().strip()
            if text:
                result.append(text)
        return result

    def _build_worker_params(self) -> dict:
        base = self._get_base_dir()
        if not base:
            raise ValueError("請先設定『專案根目錄』。")
        id_str = self.txt_id_level.text().strip()
        # 掃描模式：full=全掃 / level=指定Level / filter_key=關鍵字
        if self.radio_scan_full.isChecked():
            scan_mode = "full"
        elif self.radio_scan_level.isChecked() and id_str:
            scan_mode = "level"
        else:
            scan_mode = "full"  # 選了加速但沒填 Level → 退回全掃
        return {
            "base_dir": base,
            "first_name": (
                self.txt_first_name.text().strip() or "First_try.csv"
            ),
            "sep": self.txt_sep.text().strip() or "___",
            "scan_mode": scan_mode,
            "id_level": int(id_str) if id_str else None,
            "filter_key": self.txt_filter_key.text().strip(),
            "raw_prefix": self.txt_raw_prefix.text().strip(),
            "iso_list_path": self.txt_iso_path.text().strip(),
            "iso_sheet": self.cbo_iso_sheet.currentText(),
            "pipe_col": self.cbo_pipe_col.currentText(),
            "spool_col": self.cbo_spool_col.currentText(),
            "category_col": (
                self.cbo_category_col.currentText().strip()
                or "發包分類"
            ),
            "spool_rules": self.txt_spool_rules.text().strip(),
            "loose_roles": self.txt_loose_roles.text().strip(),
            "extra_headers": self._get_extra_headers(),
            "limit_iso_cols": False,
        }

    # ════════════════════════════════════════
    #  Worker execution
    # ════════════════════════════════════════

    def _on_run_all(self):
        try:
            params = self._build_worker_params()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        self._start_worker(params)

    def _start_worker(self, params: dict):
        self._set_running(True)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("準備中...")
        self.lbl_progress.setStyleSheet("color: #999;")
        self._log("──────────────────────────────────────")
        self._worker = PipelineWorker(params)
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg)

    def _on_finished(self, success: bool, summary: str):
        self._set_running(False)
        if success:
            self.lbl_progress.setText(f"✅ {summary}")
            self.lbl_progress.setStyleSheet(
                f"color: {C_SUCCESS}; font-size: 12px;"
            )
            self._log(f"✓ {summary}")

            # 處理模糊比對
            fuzzy = getattr(self._worker, "fuzzy_unmatched", [])
            if len(fuzzy) > 0:
                self._log(
                    f"⚠ 發現 {len(fuzzy)} 條 ISO 行尚未配對，"
                    "開啟模糊比對對話框…"
                )
                dlg = FuzzyMatchDialog(self, fuzzy)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    sels = dlg.get_selections()
                    if sels:
                        try:
                            cfg = self._get_paths()
                            iso_path = cfg["iso_match_xlsx"]
                            from core.iso_matcher import IsoMatcher
                            matcher = IsoMatcher()
                            added = matcher.apply_fuzzy_selections(
                                iso_path, sels
                            )
                            self._log(f"✓ 模糊比對已追加 {added} 筆")
                            try:
                                from core.resolved_mapping import build_resolved_mapping
                                stats = build_resolved_mapping(
                                    iso_match_path=iso_path,
                                    output_path=cfg["resolved_mapping_csv"],
                                    log_fn=self._log,
                                )
                                self._log(
                                    "✓ resolved_mapping 已重建，"
                                    f"可匯出 {stats['resolved']} 筆"
                                )
                            except Exception as rebuild_exc:
                                self._log(
                                    f"⚠ 重建 resolved_mapping 失敗：{rebuild_exc}"
                                )
                            QMessageBox.information(
                                self,
                                "模糊比對完成",
                                f"已追加 {added} 筆手動配對至 iso_match.xlsx。",
                            )
                        except Exception as e:
                            self._log(f"✗ 模糊比對套用失敗：{e}")
                            QMessageBox.warning(
                                self, "提示", f"模糊比對套用失敗：{e}"
                            )
                    else:
                        self._log("模糊比對：使用者未選擇任何配對。")
                else:
                    self._log("模糊比對：使用者取消。")

            if self.chk_auto_cleanup.isChecked():
                self._do_cleanup(silent=True)

            self.lbl_progress.setText(
                "完成\n\n可至『JSON 匯出 (互動)』分頁輸出 JSON。"
            )
        else:
            self.lbl_progress.setText(f"❌ 失敗：{summary}")
            self.lbl_progress.setStyleSheet(
                f"color: {C_ERROR}; font-size: 12px;"
            )
            QMessageBox.critical(self, "執行失敗", summary)

    # ════════════════════════════════════════
    #  Cleanup
    # ════════════════════════════════════════

    def _on_cleanup(self):
        deleted, failed = self._do_cleanup()
        if not deleted and not failed:
            QMessageBox.information(
                self, "清理中間檔", "目前專案目錄中沒有找到可刪除的中間檔。"
            )
            return
        lines = []
        if deleted:
            lines.append("已刪除以下檔案：")
            for n in deleted:
                lines.append(f"  - {n}")
            lines.append("")
        if failed:
            lines.append("下列檔案刪除失敗：")
            for n in failed:
                lines.append(f"  - {n}")
        info = "\n".join(lines)
        QMessageBox.information(self, "清理中間檔結果", info)

    def _do_cleanup(self, silent: bool = False) -> tuple[list, list]:
        try:
            cfg = self._get_paths()
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "錯誤", str(e))
            return [], []

        base = cfg["base_dir"]
        targets = [
            cfg["minus1_csv"],
            cfg["minus2_csv"],
            cfg["minus2_xlsx"],
            os.path.join(base, "iso_line_coverage.xlsx"),
            os.path.join(base, "minus_line_coverage.xlsx"),
            cfg["resolved_mapping_csv"],
        ]
        deleted = []
        failed = []
        for p in targets:
            if os.path.exists(p):
                try:
                    os.remove(p)
                    deleted.append(os.path.basename(p))
                    self._log(f"  🗑 已刪除 {os.path.basename(p)}")
                except Exception as e:
                    failed.append(os.path.basename(p))
                    self._log(f"  ⚠ 刪除失敗 {os.path.basename(p)}：{e}")
        return deleted, failed
