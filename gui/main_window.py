# -*- coding: utf-8 -*-
"""MainWindow — 程式主視窗。

Modern Industrial Dashboard 佈局：
  左側 220px 暗色 sidebar（導航 + 狀態 + 動作）
  中間 content area（StepperBar + AnimatedStackedWidget + 進度）
  右側 Run Inspector（重點標記 + 比對樣本 + 原始紀錄）
"""
from __future__ import annotations

import os
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QCoreApplication, QSettings, QSize, Qt
from PyQt6.QtGui import QKeySequence, QPixmap, QShortcut
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
    QVBoxLayout,
    QWidget,
)

from gui.theme import (
    APP_TITLE, WINDOW_H, WINDOW_W, SIDEBAR_W,
    C_ERROR, C_SUCCESS,
)
from gui.widgets import AnimatedStackedWidget, StepperBar, find_any_iso
from gui.run_inspector import RunInspectorPanel
from gui.button_motion import ButtonMotionController
from gui.iconography import app_icon
from gui.worker import PipelineWorker
from gui.dialogs.match_workbench_dialog import MatchWorkbenchDialog
from gui.dialogs.ownership_conflict_dialog import OwnershipConflictDialog
from gui.dialogs.project_setup_dialog import ProjectSetupDialog
from gui.dialogs.iso_setup_dialog import IsoSetupDialog
from gui.tabs.tab_pipeline import PipelineTabMixin
from gui.tabs.tab_json import JsonTabMixin
from gui.tabs.tab_investigation import InvestigationTabMixin


_NAV_ITEMS = [
    "專案設定",
    "ISO 比對",
    "JSON 輸出",
    "稽核調查",
]

_STEPPER_LABELS = ["專案設定", "ISO 比對", "JSON 匯出", "調查"]

_PAGE_CONTEXT = [
    ("01 · 專案設定", "選擇 First_try 來源並確認抽取範圍"),
    ("02 · ISO 比對", "設定 ISO LIST、工作表與欄位對應"),
    ("03 · JSON 輸出", "預覽安全篩選結果後再匯出"),
    ("04 · 稽核調查", "沿著 ISO、3D 與中間檔回看證據鏈"),
]

_NAV_ICONS = ("folder", "link", "export", "search")

_HEADER_ACTION_ICONS = {
    "open_recent_project": "history",
    "browse_project": "folder",
    "go_project": "arrow-right",
    "go_iso": "arrow-right",
    "browse_iso": "folder",
    "run_all": "play",
    "continue_live_review": "history",
    "revalidate_project": "refresh",
    "go_last_result": "result",
    "load_export": "result",
    "export_json": "export",
    "focus_investigation": "search",
}


class MainWindow(QMainWindow, PipelineTabMixin, JsonTabMixin, InvestigationTabMixin):
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
        self._last_conflict_context: dict = {}
        self._conflict_contexts: dict[str, dict] = {}
        self._is_running = False
        self._run_ready = False
        self._run_block_reason = "請先完成專案與 ISO 設定"
        self._current_run_state = "DRAFT"
        self._active_run_id = ""
        self._header_action_id = "browse_project"
        self._active_page_index = 0
        self._last_project_dir = ""
        self._last_project_display_dir = ""
        self._pending_collision_groups = 0
        self._project_continuity = None
        self._settings = (
            QSettings()
            if QCoreApplication.applicationName() == "PipelineOps"
            else None
        )
        self._recent_project_dir = ""
        if self._settings is not None:
            self._recent_project_dir = str(
                self._settings.value("recentProjects/lastPath", "") or ""
            ).strip()

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

        content.addWidget(self._build_workbench_header())

        self.stepper = StepperBar(_STEPPER_LABELS)
        self.stepper.step_clicked.connect(self._on_step_clicked)
        # Sidebar 已是唯一導覽；保留 stepper 物件供既有 navigation API 使用，
        # 但不再重複佔用主工作區。
        self.stepper.setVisible(False)
        content.addWidget(self.stepper)

        self.pages = AnimatedStackedWidget(duration=150)
        self._build_page_project()   # Page 0
        self._build_page_iso()       # Page 1
        self._build_page_json()      # Page 2
        self._build_page_investigation()  # Page 3
        if hasattr(self, "txt_base_dir"):
            self.txt_base_dir.textChanged.connect(
                self._on_project_path_changed
            )
        content.addWidget(self.pages, stretch=1)

        self.progress_widget = self._build_progress_bar()
        self.progress_widget.setVisible(False)
        content.addWidget(self.progress_widget)

        root.addWidget(content_w, stretch=1)
        self.run_inspector = RunInspectorPanel()
        self.run_inspector.action_requested.connect(self._on_inspector_action)
        self.txt_log = self.run_inspector.raw_log
        root.addWidget(self.run_inspector)
        self._set_inspector_visible(False)
        self._install_shortcuts()
        self._configure_action_surfaces()
        self._button_motion = ButtonMotionController(self)

        # 初始狀態
        self._update_file_status()
        self._refresh_workbench_header()

        # Navis 模式：延遲啟動設定流程
        if self._navis_dlldir and self._navis_first_try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._run_navis_setup)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Release the application event filter before the window closes."""

        worker = getattr(self, "_worker", None)
        worker_running = bool(
            worker is not None
            and hasattr(worker, "isRunning")
            and worker.isRunning()
        )
        if worker_running:
            event.ignore()
            if self.isVisible():
                QMessageBox.information(
                    self,
                    "作業仍在執行",
                    "目前流程仍在執行中。完成後即可安全關閉工具。",
                )
            return
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Idempotently release Qt effects before QApplication teardown."""

        motion = getattr(self, "_button_motion", None)
        if motion is not None:
            motion.stop()

    def _build_workbench_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("workbenchHeader")
        header.setStyleSheet(
            "#workbenchHeader { background: #FFFFFF; border: 1px solid #E2E8F0; "
            "border-radius: 10px; }"
            "#workbenchEyebrow { color: #2563EB; font-size: 10px; font-weight: 800; }"
            "#workbenchProject { color: #0F172A; font-size: 17px; font-weight: 850; }"
            "#workbenchMemory { color: #334155; font-size: 11px; font-weight: 650; }"
            "#workbenchNext { color: #64748B; font-size: 11px; }"
            "#workbenchState { border-radius: 9px; padding: 6px 10px; "
            "font-size: 11px; font-weight: 800; }"
            "#workbenchState[state-kind='neutral'] { color:#475569; background:#F1F5F9; "
            "border:1px solid #E2E8F0; }"
            "#workbenchState[state-kind='running'] { color:#1D4ED8; background:#EFF6FF; "
            "border:1px solid #BFDBFE; }"
            "#workbenchState[state-kind='review'] { color:#92400E; background:#FFFBEB; "
            "border:1px solid #FDE68A; }"
            "#workbenchState[state-kind='failed'] { color:#991B1B; background:#FEF2F2; "
            "border:1px solid #FECACA; }"
            "#headerAction { background:#2563EB; color:#FFFFFF; border:none; "
            "border:2px solid transparent; border-radius:8px; padding:6px 10px; "
            "font-weight:750; }"
            "#headerAction:hover { background:#1D4ED8; }"
            "#headerAction:pressed { background:#1E40AF; padding:7px 9px 5px 11px; }"
            "#headerAction:focus { border-color:#BFDBFE; }"
            "#inspectorToggle { background:#FFFFFF; color:#475569; "
            "border:2px solid #CBD5E1; border-radius:8px; padding:6px 9px; "
            "font-weight:650; }"
            "#inspectorToggle:hover { color:#1D4ED8; background:#F8FAFC; "
            "border-color:#93C5FD; }"
            "#inspectorToggle:pressed { background:#DBEAFE; padding:7px 8px 5px 10px; }"
            "#inspectorToggle:focus { border-color:#60A5FA; }"
            "#inspectorToggle:checked { color:#1D4ED8; background:#EFF6FF; "
            "border-color:#93C5FD; }"
            "#resumeReview { background:#2563EB; color:#FFFFFF; border:none; "
            "border:2px solid transparent; border-radius:8px; padding:6px 10px; "
            "font-weight:750; }"
            "#resumeReview:hover { background:#1D4ED8; }"
            "#resumeReview:pressed { background:#1E40AF; padding:7px 9px 5px 11px; }"
            "#resumeReview:focus { border-color:#BFDBFE; }"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.lbl_header_page = QLabel(_PAGE_CONTEXT[0][0])
        self.lbl_header_page.setObjectName("workbenchEyebrow")
        self.lbl_header_project = QLabel("尚未選擇專案")
        self.lbl_header_project.setObjectName("workbenchProject")
        self.lbl_header_run = QLabel("尚無執行紀錄")
        self.lbl_header_run.setObjectName("workbenchMemory")
        self.lbl_header_run.setWordWrap(True)
        self.lbl_header_next = QLabel("下一步：選擇專案資料夾")
        self.lbl_header_next.setObjectName("workbenchNext")
        self.lbl_header_next.setWordWrap(True)
        title_col.addWidget(self.lbl_header_page)
        title_col.addWidget(self.lbl_header_project)
        title_col.addWidget(self.lbl_header_run)
        title_col.addWidget(self.lbl_header_next)
        lay.addLayout(title_col, stretch=1)
        self.btn_header_action = QPushButton("選擇專案")
        self.btn_header_action.setObjectName("headerAction")
        self.btn_header_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_header_action.clicked.connect(self._on_header_action)
        lay.addWidget(self.btn_header_action)
        self.btn_resume_review = QPushButton("繼續判讀")
        self.btn_resume_review.setObjectName("resumeReview")
        self.btn_resume_review.clicked.connect(self._open_active_match_workbench)
        self.btn_resume_review.setVisible(False)
        lay.addWidget(self.btn_resume_review)
        self.btn_toggle_inspector = QPushButton("執行透視")
        self.btn_toggle_inspector.setObjectName("inspectorToggle")
        self.btn_toggle_inspector.setCheckable(True)
        self.btn_toggle_inspector.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_inspector.setToolTip("顯示執行狀態、證據與完整紀錄（Ctrl+I）")
        self.btn_toggle_inspector.clicked.connect(self._toggle_inspector)
        lay.addWidget(self.btn_toggle_inspector)
        self.lbl_header_state = QLabel("待設定")
        self.lbl_header_state.setObjectName("workbenchState")
        self.lbl_header_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_header_state)
        return header

    def _refresh_workbench_header(
        self,
        *,
        state: str | None = None,
        run_id: str | None = None,
    ) -> None:
        if not hasattr(self, "lbl_header_project"):
            return
        page_index = getattr(self, "_active_page_index", 0)
        if not 0 <= page_index < len(_PAGE_CONTEXT):
            page_index = 0
        page_title, page_desc = _PAGE_CONTEXT[page_index]
        self.lbl_header_page.setText(page_title)

        base = self._get_base_dir() if hasattr(self, "txt_base_dir") else ""
        self.lbl_header_project.setText(
            os.path.basename(os.path.normpath(base)) if base else "尚未選擇專案"
        )
        if run_id:
            self._active_run_id = run_id
        if state:
            self._current_run_state = state.upper()

        snapshot = self._workflow_snapshot()
        action_id, action_text, next_text = self._header_action_for_page(
            page_index,
            snapshot,
        )
        self._header_action_id = action_id
        self.btn_header_action.setText(action_text)
        self._refresh_header_action_icon(action_id)
        self.btn_header_action.setVisible(bool(action_text))
        memory_text, memory_tip = self._continuity_memory_text(base)
        self.lbl_header_run.setText(memory_text)
        self.lbl_header_run.setToolTip(memory_tip)
        self.lbl_header_next.setText(next_text or page_desc)

        state_text = self._current_run_state or "DRAFT"
        state_kind = {
            "RUNNING": "running",
            "PREFLIGHT": "running",
            "REVIEW": "review",
            "FAILED": "failed",
            "INTERRUPTED": "failed",
        }.get(state_text, "neutral")
        self.lbl_header_state.setText(
            {
                "DRAFT": "待設定",
                "PREFLIGHT": "準備中",
                "RUNNING": "執行中",
                "REVIEW": "待判讀",
                "FAILED": "失敗",
                "INTERRUPTED": "上次中斷",
                "COMPLETED": "已完成",
            }.get(state_text, state_text)
        )
        self.lbl_header_state.setProperty("state-kind", state_kind)
        self.lbl_header_state.style().unpolish(self.lbl_header_state)
        self.lbl_header_state.style().polish(self.lbl_header_state)
        self._refresh_nav_states(snapshot)

    def _configure_action_surfaces(self) -> None:
        """Apply one icon language and restrained motion to key actions."""

        for button, icon_name in zip(self._nav_btns, _NAV_ICONS):
            button.setIcon(
                app_icon(
                    icon_name,
                    normal="#A7B4C4",
                    active="#FFFFFF",
                    disabled="#64748B",
                )
            )
            button.setIconSize(QSize(18, 18))
            button.setProperty("motion-role", "quiet")

        self.btn_run_all.setIcon(
            app_icon("play", normal="#FFFFFF", active="#FFFFFF")
        )
        self.btn_run_all.setIconSize(QSize(18, 18))
        self.btn_run_all.setProperty("motion-role", "primary")

        self.btn_cleanup.setIcon(
            app_icon(
                "trash",
                normal="#CBD5E1",
                active="#FFFFFF",
                disabled="#64748B",
            )
        )
        self.btn_cleanup.setIconSize(QSize(17, 17))
        self.btn_cleanup.setProperty("motion-role", "secondary")

        self.btn_header_action.setIconSize(QSize(17, 17))
        self.btn_header_action.setProperty("motion-role", "primary")
        self._refresh_header_action_icon(self._header_action_id)

        self.btn_resume_review.setIcon(
            app_icon("history", normal="#FFFFFF", active="#FFFFFF")
        )
        self.btn_resume_review.setIconSize(QSize(17, 17))
        self.btn_resume_review.setProperty("motion-role", "secondary")

        self.btn_toggle_inspector.setIcon(
            app_icon(
                "inspect",
                normal="#52697F",
                active="#2563EB",
                disabled="#AAB6C2",
            )
        )
        self.btn_toggle_inspector.setIconSize(QSize(17, 17))
        self.btn_toggle_inspector.setProperty("motion-role", "secondary")

        action_specs = (
            ("btn_browse_base_dir", "folder", "secondary", True),
            ("btn_detect_level", "refresh", "secondary", False),
            ("btn_browse_iso", "folder", "secondary", True),
            ("_v2_btn_export", "export", "secondary", True),
        )
        for attribute, icon_name, role, light_icon in action_specs:
            button = getattr(self, attribute, None)
            if button is None:
                continue
            button.setIcon(
                app_icon(
                    icon_name,
                    normal="#FFFFFF" if light_icon else "#2563EB",
                    active="#FFFFFF" if light_icon else "#1D4ED8",
                    disabled="#CBD5E1" if light_icon else "#94A3B8",
                )
            )
            button.setIconSize(QSize(17, 17))
            button.setProperty("motion-role", role)

    def _refresh_header_action_icon(self, action_id: str) -> None:
        if not hasattr(self, "btn_header_action"):
            return
        icon_name = _HEADER_ACTION_ICONS.get(action_id, "arrow-right")
        if getattr(self, "_header_action_icon_id", "") == icon_name:
            return
        self.btn_header_action.setIcon(
            app_icon(icon_name, normal="#FFFFFF", active="#FFFFFF")
        )
        self._header_action_icon_id = icon_name

    def _continuity_memory_text(self, base: str) -> tuple[str, str]:
        """Render a compact visual memory without exposing opaque Run IDs."""

        continuity = getattr(self, "_project_continuity", None)
        if base and continuity is not None:
            operator_state = str(
                getattr(continuity, "operator_state", "no_history")
            )
            if operator_state != "no_history":
                exact = str(getattr(continuity, "exact_display", "")).strip()
                age = str(getattr(continuity, "age_label", "")).strip()
                stage = str(getattr(continuity, "stage_label", "")).strip()
                parts = [value for value in (exact, age, stage) if value]
                text = "上次活動：" + " · ".join(parts)
                remaining = int(
                    getattr(continuity, "review_remaining", 0) or 0
                )
                if remaining:
                    text += f" · 尚待判讀 {remaining} 筆"
                tip = str(getattr(continuity, "detail", "")).strip()
                run_id = str(getattr(continuity, "run_id", "")).strip()
                if run_id:
                    tip = f"{tip}\nRun ID：{run_id}".strip()
                return text, tip or base
            return "這個專案尚無執行紀錄", base
        recent = str(getattr(self, "_recent_project_dir", "") or "").strip()
        if not base and recent:
            # ``ntpath.basename`` treats ``\\server\share`` as a UNC root and
            # returns an empty name.  Split the already-known string instead;
            # this keeps the first frame network-I/O free while still showing
            # the human-friendly share/project name.
            trimmed = recent.rstrip("\\/")
            name = trimmed.replace("/", "\\").rsplit("\\", 1)[-1] or recent
            # Do not touch a potentially disconnected UNC/NAS path while the
            # first frame is still being built.  Validate only after the user
            # explicitly chooses to reopen it.
            return f"最近專案：{name}", recent
        return "尚無執行紀錄", "選擇專案後會在這裡顯示上次做到哪裡。"

    def _workflow_snapshot(self) -> dict[str, object]:
        """Return the minimum operator-facing readiness state."""

        base = self._get_base_dir() if hasattr(self, "txt_base_dir") else ""
        first_name = (
            self.txt_first_name.text().strip() or "First_try.csv"
            if hasattr(self, "txt_first_name")
            else "First_try.csv"
        )
        first_ready = bool(base and os.path.isfile(os.path.join(base, first_name)))
        iso_text = self.txt_iso_path.text().strip() if hasattr(self, "txt_iso_path") else ""
        iso_path = iso_text if iso_text and os.path.isfile(iso_text) else find_any_iso(base)
        iso_fields_ready = all(
            bool(getattr(self, name, None) and getattr(self, name).currentText().strip())
            for name in ("cbo_iso_sheet", "cbo_pipe_col", "cbo_spool_col")
        )
        if iso_fields_ready:
            iso_fields_ready = (
                self.cbo_pipe_col.currentText().strip()
                != self.cbo_spool_col.currentText().strip()
            )
        continuity = getattr(self, "_project_continuity", None)
        return {
            "base": bool(base and os.path.isdir(base)),
            "first": first_ready,
            "iso_file": bool(iso_path),
            "iso_fields": iso_fields_ready,
            "run_ready": bool(first_ready and iso_path and iso_fields_ready),
            "export_loaded": getattr(self, "_v2_iso_df", None) is not None,
            "recent_project_exists": bool(self._recent_project_dir),
            "continuity_state": str(
                getattr(continuity, "operator_state", "no_history")
            ),
            "continuity_remaining": int(
                getattr(continuity, "review_remaining", 0) or 0
            ),
            "live_review_remaining": len(self._remaining_review_cases()),
        }

    def _refresh_nav_states(self, snapshot: dict | None = None) -> None:
        """Let the sidebar double as a small, non-colour-only workflow map."""

        if not hasattr(self, "_nav_state_labels"):
            return
        snapshot = snapshot or self._workflow_snapshot()
        continuity = getattr(self, "_project_continuity", None)
        continuity_state = str(
            getattr(continuity, "operator_state", "no_history")
        )
        review_remaining = int(
            getattr(continuity, "review_remaining", 0) or 0
        )
        states = [
            "done" if snapshot["first"] else (
                "attention" if snapshot["base"] else "pending"
            ),
            "done" if snapshot["iso_file"] and snapshot["iso_fields"] else (
                "attention" if snapshot["base"] else "pending"
            ),
            "attention" if (
                review_remaining > 0 or self._pending_collision_groups > 0
            ) else (
                "done" if snapshot["export_loaded"] or continuity_state == "completed"
                else "pending"
            ),
            "available" if continuity_state != "no_history" else "pending",
        ]
        glyphs = {
            "current": ("●", "目前步驟"),
            "done": ("✓", "已完成"),
            "attention": ("!", "需要處理"),
            "available": ("•", "可使用"),
            "pending": ("○", "尚未開始"),
        }
        current = int(getattr(self, "_active_page_index", 0))
        for index, (label, state) in enumerate(
            zip(self._nav_state_labels, states)
        ):
            display_state = "current" if index == current else state
            glyph, description = glyphs[display_state]
            label.setText(glyph)
            label.setToolTip(description)
            label.setAccessibleName(f"{_NAV_ITEMS[index]}：{description}")
            label.setProperty("nav-state", display_state)
            label.style().unpolish(label)
            label.style().polish(label)

    def _on_project_path_changed(self, text: str) -> None:
        """Keep project, run, review draft, and loaded export data bound together."""

        raw = str(text or "").strip()
        normalized = (
            os.path.normcase(os.path.abspath(raw))
            if raw
            else ""
        )
        if (
            self._is_running
            and self._last_project_dir
            and normalized != self._last_project_dir
        ):
            self.txt_base_dir.blockSignals(True)
            self.txt_base_dir.setText(self._last_project_display_dir)
            self.txt_base_dir.blockSignals(False)
            return
        if self._last_project_dir and normalized != self._last_project_dir:
            self._reset_bound_project_session()
        self._last_project_dir = normalized
        self._last_project_display_dir = os.path.abspath(raw) if raw else ""
        self._load_project_continuity(raw)
        if raw and os.path.isdir(raw):
            first_name = self.txt_first_name.text().strip() or "First_try.csv"
            looks_like_project = (
                os.path.isfile(os.path.join(raw, first_name))
                or os.path.isdir(os.path.join(raw, ".flowdesk"))
            )
            if looks_like_project:
                self._recent_project_dir = os.path.abspath(raw)
                if self._settings is not None:
                    self._settings.setValue(
                        "recentProjects/lastPath",
                        self._recent_project_dir,
                    )
                    self._settings.sync()
        self._refresh_workbench_header()

    def _load_project_continuity(self, project_dir: str) -> None:
        """Hydrate visual memory from capsules without creating project state."""

        self._project_continuity = None
        if not project_dir or not os.path.isdir(project_dir):
            return
        from core.project_continuity import load_project_continuity

        snapshot = load_project_continuity(
            project_dir,
            now=datetime.now().astimezone(),
        )
        self._project_continuity = snapshot
        if self._worker is None:
            self._active_run_id = snapshot.run_id
            self._current_run_state = {
                "failed": "FAILED",
                "interrupted": "INTERRUPTED",
                "awaiting_review": "REVIEW",
                "completed": "COMPLETED",
                "no_history": "DRAFT",
            }.get(snapshot.operator_state, "DRAFT")

    def _reset_bound_project_session(self) -> None:
        if self._is_running:
            return
        self._worker = None
        self._iso_match_df = None
        self._v2_iso_df = None
        self._v2_live_filters = {}
        self._project_continuity = None
        self._active_run_id = ""
        self._current_run_state = "DRAFT"
        self._pending_collision_groups = 0
        self._last_conflict_context = {}
        self._conflict_contexts = {}
        if hasattr(self, "btn_resume_review"):
            self.btn_resume_review.setVisible(False)
        if hasattr(self, "run_inspector"):
            self.run_inspector.reset(clear_raw=True)
            self._set_inspector_visible(False)
        if hasattr(self, "progress_widget"):
            self.progress_bar.setValue(0)
            self.lbl_progress.setText("尚未執行")
            self.progress_widget.setVisible(False)
        if hasattr(self, "_v2_lbl_source"):
            self._v2_lbl_source.setText("尚未載入資料")
            self._v2_lbl_count.setText("尚未載入")
            self._v2_btn_export.setEnabled(False)
            self._v2_source_path = ""
            if hasattr(self, "_clear_preview_tables"):
                self._clear_preview_tables()

    @staticmethod
    def _header_action_for_page(
        page_index: int,
        snapshot: dict[str, object],
    ) -> tuple[str, str, str]:
        if not snapshot["base"] and snapshot.get("recent_project_exists"):
            if page_index == 0:
                return (
                    "open_recent_project",
                    "繼續上次專案",
                    "載入最近專案，先看上次做到哪裡，再決定是否重跑",
                )
        live_remaining = int(snapshot.get("live_review_remaining", 0) or 0)
        if live_remaining > 0:
            return (
                "continue_live_review",
                f"繼續判讀 {live_remaining} 筆",
                "目前工作階段仍有效，可從尚未確認的項目繼續",
            )
        continuity_state = str(snapshot.get("continuity_state", "no_history"))
        continuity_remaining = int(
            snapshot.get("continuity_remaining", 0) or 0
        )
        if (
            snapshot["base"]
            and snapshot["run_ready"]
            and continuity_state in {"failed", "interrupted", "awaiting_review"}
        ):
            return (
                "run_all",
                "重新執行",
                "來源與 ISO 設定已就緒；重新建立可驗證的工作階段",
            )
        if snapshot["base"] and continuity_state == "failed":
            return (
                "revalidate_project",
                "修正專案",
                "上次執行失敗；先確認來源檔與設定，再重新執行",
            )
        if snapshot["base"] and continuity_state == "interrupted":
            return (
                "revalidate_project",
                "重新驗證設定",
                "上次執行未正常結束；確認輸入後重新執行",
            )
        if snapshot["base"] and continuity_state == "awaiting_review":
            return (
                "revalidate_project",
                "重新驗證設定",
                f"上次尚待判讀 {continuity_remaining} 筆；先確認來源未變再續作",
            )
        if (
            snapshot["base"]
            and continuity_state == "completed"
            and not snapshot["export_loaded"]
        ):
            return (
                "go_last_result",
                "檢視上次成果",
                "上次流程已完成；先檢視成果與來源日期，再決定是否重跑",
            )
        if page_index == 0:
            if not snapshot["base"] or not snapshot["first"]:
                return "browse_project", "選擇專案", "下一步：選擇含 First_try.csv 的專案資料夾"
            if not snapshot["run_ready"]:
                return "go_iso", "設定 ISO", "下一步：完成 ISO 檔案與欄位設定"
            return "run_all", "執行全部", "資料已就緒；可開始抽取、配對與建立輸出"
        if page_index == 1:
            if not snapshot["base"]:
                return "go_project", "返回專案設定", "先選擇專案資料夾，再設定 ISO"
            if not snapshot["iso_file"] or not snapshot["iso_fields"]:
                return "browse_iso", "選擇 ISO", "下一步：選擇 ISO LIST 並確認欄位對應"
            return "run_all", "執行全部", "ISO 設定已完成；可開始完整流程"
        if page_index == 2:
            if not snapshot["export_loaded"]:
                return "load_export", "載入輸出資料", "下一步：載入 iso_match 或 resolved_mapping"
            return "export_json", "匯出 JSON", "先確認分組摘要與未匯出原因，再產生檔案"
        return "focus_investigation", "開始調查", "輸入 ISO、流水號或 3D Raw 追查證據"

    def _on_header_action(self) -> None:
        action = self._header_action_id
        if action == "open_recent_project":
            recent = str(self._recent_project_dir or "").strip()
            if not recent or not os.path.isdir(recent):
                self._recent_project_dir = ""
                if self._settings is not None:
                    self._settings.remove("recentProjects/lastPath")
                self._refresh_workbench_header()
                return
            self._on_nav_clicked(0)
            self.txt_base_dir.setText(recent)
            self._update_file_status()
        elif action == "browse_project":
            self._on_nav_clicked(0)
            self._browse_base_dir()
        elif action == "go_project":
            self._on_nav_clicked(0)
            self.txt_base_dir.setFocus()
        elif action == "go_iso":
            self._on_nav_clicked(1)
        elif action == "browse_iso":
            self._browse_iso_file()
        elif action == "run_all":
            self._on_run_all()
        elif action == "continue_live_review":
            self._open_active_match_workbench()
        elif action == "revalidate_project":
            self._on_nav_clicked(0)
            self.txt_base_dir.setFocus()
        elif action == "go_last_result":
            self._on_nav_clicked(2)
            self._v2_auto_load_source()
            self._refresh_workbench_header()
        elif action == "load_export":
            self._v2_auto_load_source()
            self._refresh_workbench_header()
        elif action == "export_json":
            self._v2_live_export()
        elif action == "focus_investigation":
            self.identity_inspector.txt_query.setFocus()

    def _install_shortcuts(self) -> None:
        self._shortcut_inspector = QShortcut(QKeySequence("Ctrl+I"), self)
        self._shortcut_inspector.activated.connect(self._toggle_inspector)
        self._shortcut_run = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._shortcut_run.activated.connect(self._on_run_all)
        self._nav_shortcuts: list[QShortcut] = []
        for idx in range(len(_NAV_ITEMS)):
            shortcut = QShortcut(QKeySequence(f"Alt+{idx + 1}"), self)
            shortcut.activated.connect(
                lambda page_index=idx: self._on_nav_clicked(page_index)
            )
            self._nav_shortcuts.append(shortcut)

    def _toggle_inspector(self) -> None:
        self._set_inspector_visible(self.run_inspector.isHidden())

    def _set_inspector_visible(self, visible: bool) -> None:
        if not hasattr(self, "run_inspector"):
            return
        self.run_inspector.setVisible(visible)
        if hasattr(self, "btn_toggle_inspector"):
            self.btn_toggle_inspector.blockSignals(True)
            self.btn_toggle_inspector.setChecked(visible)
            self.btn_toggle_inspector.setText(
                "隱藏透視" if visible else "執行透視"
            )
            self.btn_toggle_inspector.blockSignals(False)

    def _set_run_readiness(self, ready: bool, reason: str = "") -> None:
        self._run_ready = bool(ready)
        self._run_block_reason = (
            reason.strip() if reason else "請先完成專案與 ISO 設定"
        )
        self._sync_run_controls()
        self._refresh_workbench_header()

    def _sync_run_controls(self) -> None:
        if not hasattr(self, "btn_run_all"):
            return
        can_run = self._run_ready and not self._is_running
        self.btn_run_all.setEnabled(can_run)
        self.btn_run_all.setToolTip(
            "開始抽取、ISO 比對與輸出準備（Ctrl+Enter）"
            if can_run
            else (
                "流程執行中"
                if self._is_running
                else self._run_block_reason
            )
        )
        if hasattr(self, "btn_cleanup"):
            self.btn_cleanup.setEnabled(not self._is_running)
            self.btn_cleanup.setToolTip(
                "流程執行中不可清理中間檔"
                if self._is_running
                else "刪除可重新產生的中間檔；調查線索可能會減少"
            )
        if hasattr(self, "btn_header_action"):
            self.btn_header_action.setEnabled(not self._is_running)
            self.btn_header_action.setToolTip(
                "流程執行中，完成後才能執行下一個動作"
                if self._is_running
                else ""
            )
        if hasattr(self, "btn_resume_review"):
            self.btn_resume_review.setEnabled(not self._is_running)

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

        # Brand anchor — the compact mark is easier to recognise after a long
        # gap than another line of navigation text.
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)
        self.lbl_brand_icon = QLabel("IE")
        self.lbl_brand_icon.setObjectName("sidebarBrandIcon")
        self.lbl_brand_icon.setFixedSize(50, 50)
        self.lbl_brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_brand_icon.setToolTip("Intelligent Engineering Co., Ltd.")
        mark_path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "branding"
            / "ie_mark_v2.png"
        )
        mark = QPixmap(str(mark_path))
        if not mark.isNull():
            self.lbl_brand_icon.setText("")
            self.lbl_brand_icon.setPixmap(
                mark.scaled(
                    48,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        brand_row.addWidget(
            self.lbl_brand_icon,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        brand_copy = QVBoxLayout()
        brand_copy.setContentsMargins(0, 3, 0, 2)
        brand_copy.setSpacing(2)
        title = QLabel("管線流程工具")
        title.setObjectName("sidebarTitle")
        brand_copy.addWidget(title)
        ver = QLabel("Intelligent Engineering")
        ver.setObjectName("sidebarVersion")
        brand_copy.addWidget(ver)
        brand_row.addLayout(brand_copy, stretch=1)
        lay.addLayout(brand_row)
        lay.addSpacing(12)

        # Navigation
        self._nav_btns: list[QPushButton] = []
        self._nav_state_labels: list[QLabel] = []
        for i, text in enumerate(_NAV_ITEMS):
            nav_row = QWidget()
            nav_lay = QHBoxLayout(nav_row)
            nav_lay.setContentsMargins(0, 0, 0, 0)
            nav_lay.setSpacing(5)
            btn = QPushButton(text)
            btn.setProperty("class", "sidebar-nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"前往{text}（Alt+{i + 1}）")
            btn.clicked.connect(
                lambda checked, idx=i: self._on_nav_clicked(idx)
            )
            nav_lay.addWidget(btn, stretch=1)
            state_label = QLabel("○")
            state_label.setObjectName("sidebarNavState")
            state_label.setFixedWidth(16)
            state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nav_lay.addWidget(state_label)
            lay.addWidget(nav_row)
            self._nav_btns.append(btn)
            self._nav_state_labels.append(state_label)
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
        self.lbl_first_status.setWordWrap(True)
        lay.addWidget(self.lbl_first_status)

        self.lbl_iso_status = QLabel("⬜ 請先選擇專案目錄")
        self.lbl_iso_status.setProperty("class", "sb-neutral")
        self.lbl_iso_status.setWordWrap(True)
        lay.addWidget(self.lbl_iso_status)

        self.lbl_iso_detail = QLabel("")
        self.lbl_iso_detail.setProperty("class", "sb-neutral")
        self.lbl_iso_detail.setWordWrap(True)
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
        self.btn_run_all = QPushButton("執行全部")
        self.btn_run_all.setObjectName("sidebarRunAll")
        self.btn_run_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_all.clicked.connect(self._on_run_all)
        lay.addWidget(self.btn_run_all)

        self.btn_cleanup = QPushButton("清理中間檔")
        self.btn_cleanup.setObjectName("sidebarCleanup")
        self.btn_cleanup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cleanup.setToolTip("刪除可重新產生的中間檔；調查線索可能會減少")
        self.btn_cleanup.clicked.connect(self._on_cleanup)
        lay.addWidget(self.btn_cleanup)

        self.chk_auto_cleanup = QCheckBox("完成後自動清理中間檔")
        self.chk_auto_cleanup.setObjectName("sidebarCheck")
        self.chk_auto_cleanup.setChecked(False)
        self.chk_auto_cleanup.setToolTip(
            "預設關閉，以保留稽核與調查所需的中間證據。"
        )
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

    # ════════════════════════════════════════
    #  Navigation
    # ════════════════════════════════════════

    def _on_nav_clicked(self, idx: int):
        self._active_page_index = idx
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self.pages.fade_to(idx)
        self.stepper.set_current(idx)
        self._refresh_workbench_header()

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
            "first_try_trace_csv": os.path.join(base, "first_try_trace.csv"),
            "candidates_csv": os.path.join(base, "candidates.csv"),
            "identity_index_csv": os.path.join(base, "identity_index.csv"),
        }

    def _log(self, msg: str):
        if hasattr(self, "run_inspector"):
            self.run_inspector.append_raw(msg)
            self.run_inspector.ingest(msg)
        elif hasattr(self, "txt_log"):
            self.txt_log.append(msg)
        # 如果啟用檔案紀錄
        if self.chk_file_log.isChecked():
            base = self._get_base_dir()
            if base:
                from utils.utils_common import FileLogger
                FileLogger(base).append(msg)

    def _set_running(self, running: bool):
        self._is_running = running
        self._sync_run_controls()
        for name in (
            "txt_base_dir",
            "txt_first_name",
            "txt_iso_path",
            "btn_browse_base_dir",
            "btn_browse_iso",
            "btn_detect_level",
        ):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(not running)
        if running:
            self.progress_widget.setVisible(True)
            self._set_inspector_visible(True)
            self._run_btn_orig_text = self.btn_run_all.text()
            self.btn_run_all.setText("⏳ 處理中…")
            self._refresh_workbench_header(state="PREFLIGHT")
        else:
            self.btn_run_all.setText(
                getattr(self, "_run_btn_orig_text", "執行全部")
            )
            self._refresh_workbench_header()

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
            "write_first_try_trace": self.chk_first_try_trace.isChecked(),
            "write_candidates": self.chk_candidates_trace.isChecked(),
        }

    # ════════════════════════════════════════
    #  Worker execution
    # ════════════════════════════════════════

    def _on_run_all(self):
        if self._is_running:
            return
        if not self._run_ready:
            snapshot = self._workflow_snapshot()
            self._on_nav_clicked(0 if not snapshot["first"] else 1)
            QMessageBox.information(
                self,
                "尚未就緒",
                self._run_block_reason,
            )
            return
        try:
            params = self._build_worker_params()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        self._start_worker(params)

    def _start_worker(self, params: dict):
        self._set_running(True)
        if hasattr(self, "btn_resume_review"):
            self.btn_resume_review.setVisible(False)
        if hasattr(self, "run_inspector"):
            self.run_inspector.reset(clear_raw=False)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("準備中...")
        self.lbl_progress.setStyleSheet("color: #999;")
        self._log("──────────────────────────────────────")
        self._worker = PipelineWorker(params)
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.event_signal.connect(self._on_structured_event)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_widget.setVisible(True)
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg)
        if hasattr(self, "run_inspector"):
            self.run_inspector.ingest(msg)

    def _on_structured_event(self, event: dict) -> None:
        self.run_inspector.ingest_event(event)
        run_id = str(event.get("run_id", "")).strip()
        event_type = str(event.get("event_type", "")).strip()
        states = {
            "run.started": "RUNNING",
            "review.requested": "REVIEW",
            "run.completed": "COMPLETED",
            "run.failed": "FAILED",
            "decision.applied": "REVIEW",
            "rollback.applied": "REVIEW",
        }
        self._refresh_workbench_header(
            state=states.get(event_type),
            run_id=run_id or None,
        )

    def _on_inspector_action(self, request: dict) -> None:
        """Route an actionable Sidebox finding to its focused repair flow."""

        action = str(request.get("action", "")).strip()
        if action == "continue_review":
            self._on_nav_clicked(1)
            self._open_active_match_workbench()
        elif action == "ownership_conflict_guide":
            self._show_ownership_conflict_guide(request)

    @staticmethod
    def _conflict_item_ids(request: dict) -> set[str]:
        item_ids = {
            str(item.get("item_id", "")).strip()
            for item in request.get("conflict_items", [])
            if isinstance(item, dict)
        }
        for raw in request.get("conflicts", []):
            text = str(raw)
            if "：" in text:
                item_ids.add(text.split("：", 1)[0].strip())
        item_ids.discard("")
        return item_ids

    @staticmethod
    def _recovery_selection(selection: dict) -> dict:
        """Keep a JSON-safe, replayable subset of a rejected selection."""

        text_fields = (
            "iso_line",
            "iso_spool",
            "line_3d",
            "raw_3d",
            "path",
            "scope",
            "parent_area",
            "level",
            "item_id",
            "family_id",
            "reason",
            "trace",
            "source",
            "decision_origin",
            "decision_source",
        )
        compact = {key: str(selection.get(key, "")) for key in text_fields}
        compact["score"] = str(selection.get("score", ""))
        reason_codes = selection.get("reason_codes", []) or []
        if isinstance(reason_codes, str):
            reason_codes = [reason_codes]
        compact["reason_codes"] = [str(value) for value in reason_codes]
        evidence = selection.get("evidence", {})
        if isinstance(evidence, dict):
            compact["evidence"] = {
                "classification": str(evidence.get("classification", "")),
            }
        iso_metadata = selection.get("iso_metadata", {})
        if isinstance(iso_metadata, dict):
            compact["iso_metadata"] = dict(iso_metadata)
        return compact

    def _review_cases_for_conflicts(self, request: dict) -> list[dict]:
        """Find still-pending cases by ISO identity first, ITEM identity second."""

        item_ids = self._conflict_item_ids(request)
        iso_keys: set[tuple[str, str]] = set()
        for item in request.get("conflict_items", []):
            if not isinstance(item, dict):
                continue
            for prefix in ("existing", "requested"):
                line = str(item.get(f"{prefix}_iso_line", "")).strip()
                if not line:
                    line = str(item.get(f"{prefix}_family", "")).strip()
                spool = str(item.get(f"{prefix}_iso_spool", "")).strip()
                if line:
                    iso_keys.add((line, spool))

        from core.candidate_family import candidate_item_id

        dataset_revision = str(
            getattr(self._worker, "input_fingerprint", "")
        ).strip()
        focused: list[dict] = []
        for case in self._remaining_review_cases():
            case_key = (
                str(case.get("iso_line", "")).strip(),
                str(case.get("iso_spool", "")).strip(),
            )
            candidates = case.get("candidates", [])
            item_match = any(
                candidate_item_id(candidate, dataset_revision) in item_ids
                for candidate in candidates
                if isinstance(candidate, dict)
            )
            if case_key in iso_keys or item_match:
                focused.append(case)
        return focused

    def _conflict_context_for_request(self, request: dict) -> dict:
        event_id = str(request.get("event_id", "")).strip()
        context = dict(self._conflict_contexts.get(event_id, {}) or {})
        if not context and request.get("recovery_selections"):
            context = {
                "run_id": str(request.get("run_id", "")),
                "event_id": event_id,
                "selections": [
                    dict(item)
                    for item in request.get("recovery_selections", [])
                    if isinstance(item, dict)
                ],
                "pending_rules": [
                    dict(item)
                    for item in request.get("pending_rules", [])
                    if isinstance(item, dict)
                ],
                "conflict_items": [
                    dict(item)
                    for item in request.get("conflict_items", [])
                    if isinstance(item, dict)
                ],
            }
        if not context:
            last = dict(getattr(self, "_last_conflict_context", {}) or {})
            if str(last.get("event_id", "")) == event_id:
                context = last
        return context

    def _decorate_conflict_cases(
        self,
        cases: list[dict],
        item_ids: set[str],
    ) -> list[dict]:
        """Refresh ownership state so the focused workbench visibly blocks losers."""

        from core.candidate_family import candidate_item_id
        from utils.utils_common import normalize_line_v2

        ledger = getattr(self._worker, "ledger", None)
        dataset_revision = str(
            getattr(self._worker, "input_fingerprint", "")
        ).strip()
        decorated: list[dict] = []
        for raw_case in cases:
            case = dict(raw_case)
            family, _events = normalize_line_v2(case.get("iso_line", ""))
            family = family.strip().upper()
            candidates: list[dict] = []
            for raw_candidate in case.get("candidates", []):
                if not isinstance(raw_candidate, dict):
                    continue
                candidate = dict(raw_candidate)
                item_id = candidate_item_id(candidate, dataset_revision)
                candidate["item_id"] = item_id
                if item_id in item_ids:
                    candidate["repair_conflict"] = True
                    current = ledger.get_ownership(item_id) if ledger is not None else {}
                    owner = str(current.get("family_id", "")).strip()
                    if owner and owner != family:
                        candidate["ownership_status"] = "claimed_by_other"
                        evidence = dict(candidate.get("evidence", {}) or {})
                        evidence["ownership_status"] = "claimed_by_other"
                        evidence["ownership_family"] = owner
                        candidate["evidence"] = evidence
                candidates.append(candidate)
            case["candidates"] = candidates
            decorated.append(case)
        return decorated

    @staticmethod
    def _conflict_summary(request: dict) -> str:
        lines: list[str] = []
        for item in request.get("conflict_items", []):
            if not isinstance(item, dict):
                continue
            identity = str(item.get("line_3d", "")).strip() or "3D ITEM"
            existing = str(item.get("existing_family", "")).strip() or "既有家族"
            requested = str(item.get("requested_family", "")).strip() or "新家族"
            lines.append(f"• {identity}\n  {existing}  ↔  {requested}")
        if not lines:
            for raw in request.get("conflicts", []):
                detail = str(raw).split("：", 1)[-1].strip()
                if detail:
                    lines.append(f"• {detail}")
        return "\n".join(lines[:6])

    def _show_ownership_conflict_guide(self, request: dict) -> None:
        """Explain an ownership rejection and offer scoped recovery actions."""

        item_ids = self._conflict_item_ids(request)
        focused_cases = self._review_cases_for_conflicts(request)
        focused_cases = self._decorate_conflict_cases(focused_cases, item_ids)
        context = self._conflict_context_for_request(request)
        attempted = [
            dict(selection)
            for selection in context.get("selections", [])
            if isinstance(selection, dict)
        ]
        applied_keys = set(
            getattr(self._worker, "applied_review_keys", set()) or set()
        )
        safe_selections = [
            selection
            for selection in attempted
            if str(selection.get("item_id", "")).strip() not in item_ids
            and (
                str(selection.get("iso_line", "")),
                str(selection.get("iso_spool", "")),
            ) not in applied_keys
        ]

        dialog = OwnershipConflictDialog(
            self,
            conflict_items=[
                item
                for item in request.get("conflict_items", [])
                if isinstance(item, dict)
            ],
            attempted_count=int(request.get("attempted_count", 0) or 0),
            focused_case_count=len(focused_cases),
            safe_selection_count=len(safe_selections),
            recovery_available=bool(context),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if dialog.selected_action == "focus":
            self._on_nav_clicked(1)
            self._open_match_workbench_cases(
                focused_cases,
                entry_label=f"衝突修正（{len(focused_cases)} 個相關案例）",
            )
        elif dialog.selected_action == "apply_safe":
            try:
                added, stats = self._apply_workbench_selections(
                    safe_selections,
                    [],
                )
                self._log(
                    f"✓ 已略過 {len(item_ids)} 個 ownership 衝突；"
                    f"先提交其餘 {added} 筆"
                )
                QMessageBox.information(
                    self,
                    "其餘判斷已提交",
                    (
                        f"已提交 {added} 筆非衝突判斷，"
                        f"可匯出 {stats.get('resolved', 0)} 筆。\n"
                        "為避免把衝突擴散到下次執行，本次暫存的符號規則沒有一併啟用。\n"
                        "衝突案例仍保留在待確認佇列。"
                    ),
                )
            except Exception as exc:
                self._log(f"✗ 略過衝突後仍無法提交：{exc}")
                QMessageBox.warning(self, "仍未提交", str(exc))
            self._update_resume_review_button()

    @staticmethod
    def _sha256_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    def _ingest_ledger_event(self, event: dict) -> None:
        if hasattr(self, "run_inspector") and isinstance(event, dict):
            self._on_structured_event(event)

    def _ledger_event_by_id(self, ledger, run_id: str, event_id: str) -> None:
        if not event_id:
            return
        for event in reversed(ledger.list_events(run_id)):
            if str(event.get("event_id", "")) == str(event_id):
                self._ingest_ledger_event(event)
                return

    @staticmethod
    def _ownership_conflict_count(mapping_path: str) -> int:
        if not os.path.isfile(mapping_path):
            return 0
        try:
            data = pd.read_csv(
                mapping_path,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")
            if "ResolutionStatus" not in data.columns:
                return 0
            return int(data["ResolutionStatus"].eq("ownership_conflict").sum())
        except Exception:
            return 0

    def _apply_workbench_selections(
        self,
        selections: list[dict],
        pending_rules: list[dict] | None = None,
    ) -> tuple[int, dict]:
        """Apply one frozen human change set with ownership and rollback guards."""

        if not selections:
            return 0, {}
        pending_rules = [dict(rule) for rule in (pending_rules or [])]
        worker = self._worker
        ledger = getattr(worker, "ledger", None)
        run_id = str(getattr(worker, "run_id", "")).strip()
        dataset_revision = str(
            getattr(worker, "input_fingerprint", "")
        ).strip()
        if ledger is None or not run_id or not dataset_revision:
            raise RuntimeError("本次執行缺少 Run Capsule，拒絕無稽核地套用決策")

        worker_base = os.path.normcase(os.path.abspath(str(
            getattr(worker, "p", {}).get("base_dir", self._get_base_dir())
        )))
        current_base = os.path.normcase(os.path.abspath(self._get_base_dir()))
        if worker_base != current_base:
            raise RuntimeError(
                "目前畫面已切換到另一個專案；請回到本次 Run 的根目錄後再套用決策"
            )

        from core.iso_matcher import IsoMatcher
        from core.resolved_mapping import build_resolved_mapping
        from utils.utils_common import normalize_line_v2

        cfg = self._get_paths()
        iso_path = cfg["iso_match_xlsx"]
        mapping_path = cfg["resolved_mapping_csv"]
        if not os.path.isfile(iso_path):
            raise FileNotFoundError(f"找不到 iso_match.xlsx：{iso_path}")

        claims: list[tuple[str, str, dict]] = []
        unverifiable: list[dict] = []
        batch_owners: dict[str, str] = {}
        batch_owner_selections: dict[str, dict] = {}
        conflicts: list[str] = []
        conflict_items: list[dict] = []
        for selection in selections:
            iso_family, _events = normalize_line_v2(selection.get("iso_line", ""))
            iso_family = iso_family.strip().upper()
            if not iso_family:
                raise ValueError("人工決策缺少可驗證的 ISO family")
            item_id = str(selection.get("item_id", "")).strip()
            if not item_id or item_id.startswith("ephemeral:"):
                unverifiable.append(selection)
                continue
            batch_owner = batch_owners.get(item_id)
            if batch_owner and batch_owner != iso_family:
                conflicts.append(f"{item_id}：{batch_owner} ↔ {iso_family}")
                original = batch_owner_selections.get(item_id, {})
                conflict_items.append(
                    {
                        "item_id": item_id,
                        "source": "same_change_set",
                        "existing_family": batch_owner,
                        "requested_family": iso_family,
                        "existing_iso_line": str(original.get("iso_line", "")),
                        "existing_iso_spool": str(original.get("iso_spool", "")),
                        "requested_iso_line": str(selection.get("iso_line", "")),
                        "requested_iso_spool": str(selection.get("iso_spool", "")),
                        "line_3d": str(selection.get("line_3d", "")),
                        "path": str(selection.get("path", "")),
                    }
                )
                continue
            batch_owners[item_id] = iso_family
            batch_owner_selections[item_id] = selection
            current = ledger.get_ownership(item_id)
            current_family = str(current.get("family_id", "")).strip()
            if current_family and current_family != iso_family:
                conflicts.append(f"{item_id}：既有 {current_family}，要求 {iso_family}")
                conflict_items.append(
                    {
                        "item_id": item_id,
                        "source": "existing_ownership",
                        "existing_family": current_family,
                        "requested_family": iso_family,
                        "requested_iso_line": str(selection.get("iso_line", "")),
                        "requested_iso_spool": str(selection.get("iso_spool", "")),
                        "line_3d": str(selection.get("line_3d", "")),
                        "path": str(selection.get("path", "")),
                    }
                )
                continue
            claims.append((item_id, iso_family, selection))

        if conflicts:
            conflict_item_ids = {
                str(item.get("item_id", "")) for item in conflict_items
            }
            safe_count = sum(
                str(selection.get("item_id", "")) not in conflict_item_ids
                for selection in selections
            )
            recovery_selections = [
                self._recovery_selection(selection) for selection in selections
            ]
            context = {
                "run_id": run_id,
                "selections": recovery_selections,
                "pending_rules": pending_rules,
                "conflict_items": conflict_items,
            }
            event = ledger.emit(
                run_id,
                "ownership.conflict",
                stage="review",
                actor={"kind": "human", "id": "local_user"},
                payload={
                    "message": "人工 change set 違反 3D ITEM 單一歸屬",
                    "conflicts": conflicts,
                    "conflict_items": conflict_items,
                    "attempted_count": len(selections),
                    "safe_count": safe_count,
                    "recovery_selections": recovery_selections,
                    "pending_rules": pending_rules,
                },
            )
            event_id = str(event.get("event_id", "")).strip()
            context["event_id"] = event_id
            self._last_conflict_context = context
            if event_id:
                self._conflict_contexts[event_id] = context
            self._ingest_ledger_event(event)
            raise RuntimeError("單一歸屬鎖阻擋：" + "；".join(conflicts[:3]))

        compact_selections = [
            {
                "iso_line": str(item.get("iso_line", "")),
                "iso_spool": str(item.get("iso_spool", "")),
                "line_3d": str(item.get("line_3d", "")),
                "item_id": str(item.get("item_id", "")),
                "decision_origin": str(item.get("decision_origin", "manual")),
                "reason_codes": item.get("reason_codes", []),
            }
            for item in selections
        ]
        approved_event = ledger.emit(
            run_id,
            "decision.approved",
            stage="review",
            actor={"kind": "human", "id": "local_user"},
            subject={"kind": "change_set", "id": f"manual-{run_id}"},
            payload={
                "action": "apply_match_workbench_selections",
                "selection_count": len(selections),
                "selections": compact_selections,
                "project_rules": pending_rules,
                "input_fingerprint": dataset_revision,
                "base_state_hash": ledger.get_run(run_id)["base_state_hash"],
            },
        )
        self._ingest_ledger_event(approved_event)

        version_dir = os.path.join(
            cfg["base_dir"],
            ".flowdesk",
            "versions",
            run_id,
            str(approved_event["event_id"]),
        )
        os.makedirs(version_dir, exist_ok=True)
        backups: list[tuple[str, str]] = []
        for source in (iso_path, mapping_path):
            if os.path.isfile(source):
                backup = os.path.join(version_dir, "before_" + os.path.basename(source))
                shutil.copy2(source, backup)
                backups.append((source, backup))
        from core.project_rules import ProjectRuleStore

        rule_store = ProjectRuleStore(cfg["base_dir"])
        rules_existed_before = os.path.isfile(rule_store.path)
        if rules_existed_before:
            backup = os.path.join(version_dir, "before_project_rules.json")
            shutil.copy2(rule_store.path, backup)
            backups.append((rule_store.path, backup))

        before_conflicts = self._ownership_conflict_count(mapping_path)
        newly_claimed: list[tuple[str, str]] = []
        state_advanced = False
        before_hash = ""
        after_hash = ""
        try:
            for item_id, family_id, selection in claims:
                claim = ledger.claim_ownership(
                    run_id,
                    item_id,
                    family_id,
                    claimed_by="human_workbench_executor",
                    metadata={
                        "iso_line": selection.get("iso_line", ""),
                        "line_3d": selection.get("line_3d", ""),
                        "path": selection.get("path", ""),
                        "dataset_revision": dataset_revision,
                    },
                )
                if claim.get("status") == "claimed":
                    newly_claimed.append((item_id, family_id))
                self._ledger_event_by_id(
                    ledger,
                    run_id,
                    str(claim.get("event_id", "")),
                )

            if unverifiable:
                event = ledger.emit(
                    run_id,
                    "anomaly.detected",
                    stage="review",
                    actor={"kind": "executor", "id": "human_workbench_executor"},
                    payload={
                        "message": "部分人工決策沒有可建立 ownership lock 的穩定 ITEM ID",
                        "count": len(unverifiable),
                        "unit": "decisions",
                    },
                )
                self._ingest_ledger_event(event)

            activated_rules: list[dict] = []
            for rule_request in pending_rules:
                proposed = rule_store.propose_punctuation_alias(
                    rule_request.get("iso_symbol", ""),
                    rule_request.get("candidate_symbol", ""),
                    actor="local_user",
                    sample_iso=str(rule_request.get("sample_iso", "")),
                    sample_candidate=str(
                        rule_request.get("sample_candidate", "")
                    ),
                )
                approved = rule_store.approve_rule(
                    proposed["rule_id"],
                    actor="local_user",
                )
                activated_rules.append(approved)
                event = ledger.emit(
                    run_id,
                    "rule.activated",
                    stage="review",
                    actor={"kind": "human", "id": "local_user"},
                    subject={"kind": "project_rule", "id": approved["rule_id"]},
                    payload={
                        "template_id": approved.get("template_id", ""),
                        "parameters": approved.get("parameters", {}),
                        "pattern": rule_request.get("pattern", ""),
                        "input_fingerprint": dataset_revision,
                    },
                )
                self._ingest_ledger_event(event)

            matcher = IsoMatcher()
            added = matcher.apply_fuzzy_selections(
                iso_path,
                selections,
                log_fn=self._log,
            )
            worker_params = getattr(worker, "p", {}) or {}
            stats = build_resolved_mapping(
                iso_match_path=iso_path,
                output_path=mapping_path,
                log_fn=self._log,
                dataset_revision=dataset_revision,
                iso_source_path=worker_params.get("iso_list_path") or None,
                iso_source_sheet=worker_params.get("iso_sheet") or None,
                iso_source_spool_col=worker_params.get("spool_col") or None,
            )
            after_conflicts = int(stats.get("ownership_conflicts", 0))
            if after_conflicts > before_conflicts:
                raise RuntimeError(
                    "套用後新增 ownership conflict，change set 已拒絕並準備回復"
                )

            before_hash = str(ledger.get_run(run_id)["base_state_hash"])
            after_hash = self._sha256_file(mapping_path)
            state_event = ledger.advance_base_state(
                run_id,
                expected_base_state_hash=before_hash,
                new_base_state_hash=after_hash,
                actor="human_workbench_executor",
                reason=f"applied {added} staged match decisions",
            )
            state_advanced = True
            self._ingest_ledger_event(state_event)
            applied_review_keys = set(
                getattr(worker, "applied_review_keys", set())
            )
            applied_review_keys.update(
                (
                    str(selection.get("iso_line", "")),
                    str(selection.get("iso_spool", "")),
                )
                for selection in selections
            )
            worker.applied_review_keys = applied_review_keys
            review_total = len(getattr(worker, "fuzzy_unmatched", []) or [])
            remaining_review_cases = max(
                0,
                review_total - len(applied_review_keys),
            )
            applied_event = ledger.emit(
                run_id,
                "decision.applied",
                stage="review",
                actor={"kind": "executor", "id": "human_workbench_executor"},
                correlation_id=str(approved_event["event_id"]),
                payload={
                    "selection_count": added,
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "backup_dir": version_dir,
                    "ownership_claims": len(claims),
                    "ownership_unverifiable": len(unverifiable),
                    "project_rules_activated": len(activated_rules),
                    "resolved_rows": int(stats.get("resolved", 0)),
                    "remaining_review_cases": remaining_review_cases,
                },
            )
            self._ingest_ledger_event(applied_event)

            for artifact_path, kind in (
                (iso_path, "match_workbook_manual_version"),
                (mapping_path, "resolved_mapping_manual_version"),
            ):
                try:
                    artifact = ledger.register_artifact(
                        run_id,
                        artifact_path,
                        kind=kind,
                        metadata={"decision_event_id": approved_event["event_id"]},
                    )
                    self._ledger_event_by_id(
                        ledger,
                        run_id,
                        str(artifact.get("event_id", "")),
                    )
                except Exception as artifact_exc:
                    self._log(f"⚠ 決策產物登記失敗：{artifact_exc}")
            try:
                context_path = ledger.export_agent_context(run_id)
                self._log(f"✓ Agent context 已更新：{context_path}")
            except Exception as context_exc:
                self._log(f"⚠ Agent context 更新失敗：{context_exc}")
            return added, stats
        except Exception as exc:
            if state_advanced and before_hash and after_hash:
                try:
                    reverted_state = ledger.advance_base_state(
                        run_id,
                        expected_base_state_hash=after_hash,
                        new_base_state_hash=before_hash,
                        actor="human_workbench_executor",
                        reason=f"compensating rollback: {exc}",
                    )
                    self._ingest_ledger_event(reverted_state)
                except Exception as state_exc:
                    self._log(f"⚠ ledger base-state 補償失敗：{state_exc}")
            for original, backup in backups:
                if os.path.isfile(backup):
                    shutil.copy2(backup, original)
            if (
                pending_rules
                and not rules_existed_before
                and os.path.isfile(rule_store.path)
            ):
                os.remove(rule_store.path)
            for item_id, family_id in reversed(newly_claimed):
                try:
                    released = ledger.release_ownership(
                        run_id,
                        item_id,
                        family_id,
                        released_by="human_workbench_executor",
                        reason=f"compensating rollback: {exc}",
                    )
                    self._ledger_event_by_id(
                        ledger,
                        run_id,
                        str(released.get("event_id", "")),
                    )
                except Exception as release_exc:
                    self._log(f"⚠ ownership 補償釋放失敗：{release_exc}")
            rollback_event = ledger.emit(
                run_id,
                "rollback.applied",
                stage="review",
                actor={"kind": "executor", "id": "human_workbench_executor"},
                correlation_id=str(approved_event["event_id"]),
                payload={
                    "reason": str(exc),
                    "restored_files": [path for path, _backup in backups],
                },
            )
            self._ingest_ledger_event(rollback_event)
            raise

    def _remaining_review_cases(self) -> list[dict]:
        worker = self._worker
        cases = list(getattr(worker, "fuzzy_unmatched", []) or [])
        applied = set(getattr(worker, "applied_review_keys", set()) or set())
        return [
            case
            for case in cases
            if (
                str(case.get("iso_line", "")),
                str(case.get("iso_spool", "")),
            ) not in applied
        ]

    def _update_resume_review_button(self) -> None:
        if not hasattr(self, "btn_resume_review"):
            return
        remaining = len(self._remaining_review_cases())
        self.btn_resume_review.setText(f"繼續判讀 {remaining} 筆")
        # The header owns the single primary action; keep this legacy control
        # available for compatibility without showing two competing blue CTAs.
        self.btn_resume_review.setVisible(False)
        if not self._is_running:
            self._current_run_state = "REVIEW" if remaining else "COMPLETED"
            self._refresh_workbench_header()

    def _open_active_match_workbench(self) -> None:
        fuzzy = self._remaining_review_cases()
        if not fuzzy:
            self._update_resume_review_button()
            return
        self._open_match_workbench_cases(fuzzy)

    def _open_match_workbench_cases(
        self,
        fuzzy: list[dict],
        *,
        entry_label: str = "配對工作檯",
    ) -> None:
        if not fuzzy:
            return
        self._log(f"開啟{entry_label}：待處理 {len(fuzzy)} 筆")
        dlg = MatchWorkbenchDialog(
            self,
            fuzzy,
            project_dir=str(
                getattr(self._worker, "p", {}).get(
                    "base_dir",
                    self._get_base_dir(),
                )
            ),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._log(f"{entry_label}：本次未提交；可由上方『繼續判讀』恢復。")
            self._update_resume_review_button()
            return
        sels = dlg.get_selections()
        pending_rules = dlg.get_pending_rules()
        if not sels:
            self._log("配對工作檯：沒有已確認的配對。")
            self._update_resume_review_button()
            return
        try:
            added, stats = self._apply_workbench_selections(
                sels,
                pending_rules,
            )
            self._log(
                f"✓ 配對工作檯已提交 {added} 筆；"
                f"規則 {len(pending_rules)} 條；"
                f"可匯出 {stats['resolved']} 筆"
            )
            QMessageBox.information(
                self,
                "配對決策已提交",
                (
                    f"已提交 {added} 筆人工決策。\n"
                    f"已保存 {len(pending_rules)} 條專案規則。\n"
                    f"尚待處理 {len(self._remaining_review_cases())} 筆。"
                ),
            )
        except Exception as e:
            self._log(f"✗ 配對工作檯套用失敗：{e}")
            QMessageBox.warning(self, "提示", f"配對決策未提交：{e}")
        self._update_resume_review_button()

    def _on_finished(self, success: bool, summary: str):
        self._set_running(False)
        if success:
            self.lbl_progress.setText(f"✅ {summary}")
            self.lbl_progress.setStyleSheet(
                f"color: {C_SUCCESS}; font-size: 12px;"
            )
            self._log(f"✓ {summary}")

            # 進入 staged 配對工作檯；不再以分數門檻直接批次寫入。
            fuzzy = getattr(self._worker, "fuzzy_unmatched", [])
            if len(fuzzy) > 0:
                self._log(
                    f"⚠ 發現 {len(fuzzy)} 條 ISO 行尚未配對，"
                    "已加入待判讀清單；可按『繼續判讀』處理。"
                )
                self._update_resume_review_button()

            self._maybe_prompt_collision_decisions()

            if self.chk_auto_cleanup.isChecked():
                preserve_investigation = (
                    self.chk_first_try_trace.isChecked()
                    or self.chk_candidates_trace.isChecked()
                )
                self._do_cleanup(
                    silent=True,
                    preserve_investigation=preserve_investigation,
                )

            self.lbl_progress.setText(
                "完成；可前往『JSON 輸出』預覽並匯出。"
            )
        else:
            self.lbl_progress.setText(f"❌ 失敗：{summary}")
            self.lbl_progress.setStyleSheet(
                f"color: {C_ERROR}; font-size: 12px;"
            )
            QMessageBox.critical(self, "執行失敗", summary)

    def _maybe_prompt_collision_decisions(self):
        try:
            cfg = self._get_paths()
            mapping_path = cfg["resolved_mapping_csv"]
            if not os.path.exists(mapping_path):
                return
            from core.collision_resolver import load_collision_groups
            groups = load_collision_groups(mapping_path)
        except Exception as exc:
            self._log(f"⚠ 讀取 collision 決策資料失敗：{exc}")
            return

        if not groups:
            return

        rows = sum(int(g.get("row_count", 0)) for g in groups)
        self._log(
            f"⚠ 發現 {len(groups)} 個流水號需要 collision 決策，"
            f"共 {rows} 列候選。"
        )
        self._pending_collision_groups = len(groups)
        self._log(
            "  → 不會自動開啟視窗；請到『JSON 輸出』按『處理衝突』。"
        )

    # ════════════════════════════════════════
    #  Cleanup
    # ════════════════════════════════════════

    def _on_cleanup(self):
        if self._is_running:
            QMessageBox.warning(
                self,
                "流程執行中",
                "執行期間不能清理中間檔。",
            )
            return
        try:
            cfg = self._get_paths()
        except Exception as exc:
            QMessageBox.warning(self, "無法清理", str(exc))
            return
        base = cfg["base_dir"]
        candidates = [
            cfg["minus2_csv"],
            cfg["minus2_xlsx"],
            os.path.join(base, "iso_line_coverage.xlsx"),
            os.path.join(base, "minus_line_coverage.xlsx"),
            cfg["minus1_csv"],
            cfg["first_try_trace_csv"],
            cfg["candidates_csv"],
            cfg["identity_index_csv"],
        ]
        existing = [path for path in candidates if os.path.isfile(path)]
        if not existing:
            QMessageBox.information(
                self, "清理中間檔", "目前專案目錄中沒有找到可刪除的中間檔。"
            )
            return
        names = "\n".join(f"• {os.path.basename(path)}" for path in existing)
        reply = QMessageBox.question(
            self,
            "確認清理中間檔",
            (
                "將刪除以下可重新產生的檔案：\n\n"
                f"{names}\n\n"
                "刪除後，稽核與調查可用的證據會減少。是否繼續？"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
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

    def _do_cleanup(
        self,
        silent: bool = False,
        preserve_investigation: bool = False,
    ) -> tuple[list, list]:
        try:
            cfg = self._get_paths()
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "錯誤", str(e))
            return [], []

        base = cfg["base_dir"]
        targets = [
            cfg["minus2_csv"],
            cfg["minus2_xlsx"],
            os.path.join(base, "iso_line_coverage.xlsx"),
            os.path.join(base, "minus_line_coverage.xlsx"),
        ]
        if preserve_investigation:
            self._log(
                "  🔎 已啟用排查輸出，自動清理保留 "
                "123_minus_1.csv / first_try_trace.csv / candidates.csv / "
                "identity_index.csv / resolved_mapping.csv"
            )
        else:
            targets.extend(
                [
                    cfg["minus1_csv"],
                    cfg["first_try_trace_csv"],
                    cfg["candidates_csv"],
                    cfg["identity_index_csv"],
                ]
            )
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
