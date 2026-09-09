# -*- coding: utf-8 -*-
"""企業級 ISO / 3D 配對工作檯。

這個 dialog 刻意不修改既有 fuzzy 流程，先提供一個可獨立整合的工作檯：

* 以 evidence 將待辦分成安全批次、符號模式、逐筆判讀、阻擋與無候選。
* 所有人工操作先暫存；只有最後確認後才會由 ``get_selections`` 回傳。
* 安全批次必須有明確 ``candidate.auto_safe`` 與結構化 evidence，絕不以
  score 門檻推定安全。
* 舊版候選沒有 evidence 時仍可逐筆判讀，但永遠不會進安全批次。

輸入與舊 ``FuzzyMatchDialog`` 相同：``parent`` 加上 ``fuzzy_unmatched``；
輸出的 selection 亦保留舊流程使用的主要欄位。
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest
from typing import Any, Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.match_safety import (
    annotate_family_aware_safety,
    PatternSignature,
    SymbolBatchPreview,
    pattern_signature,
    pattern_signature_label,
    preview_symbol_batch,
)
from core.candidate_family import annotate_candidate_families
from gui.iconography import app_icon


_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")
_SYMBOL_RE = re.compile(r"[^A-Za-z0-9]+")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _alnum_tokens(value: Any) -> list[str]:
    return [token.upper() for token in _ALNUM_RE.findall(_as_text(value))]


def _alnum_skeleton(value: Any) -> str:
    tokens = _alnum_tokens(value)
    return " | ".join(tokens) if tokens else "—"


def _symbol_runs(value: Any) -> list[str]:
    return _SYMBOL_RE.findall(_as_text(value))


def _visible_symbol(value: str) -> str:
    if not value:
        return "∅"
    return value.replace(" ", "␠")


def describe_symbol_difference(iso_value: Any, three_d_value: Any) -> str:
    """描述兩個值的符號差異；英數骨架不同時不宣稱符號等價。"""

    iso_tokens = _alnum_tokens(iso_value)
    three_d_tokens = _alnum_tokens(three_d_value)
    if iso_tokens != three_d_tokens:
        return "英數骨架不同（不屬於純符號差異）"

    differences: list[str] = []
    for left, right in zip_longest(
        _symbol_runs(iso_value),
        _symbol_runs(three_d_value),
        fillvalue="",
    ):
        if left == right:
            continue
        text = f"{_visible_symbol(left)} ↔ {_visible_symbol(right)}"
        if text not in differences:
            differences.append(text)
    return "；".join(differences) if differences else "無符號差異"


def _first_value(*values: Any) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


def _mapping_text(value: Any) -> str:
    if isinstance(value, dict):
        if not value:
            return "—"
        parts = []
        for key, state in value.items():
            if isinstance(state, bool):
                parts.append(f"{'✓' if state else '✕'} {key}")
            else:
                parts.append(f"{key}: {state}")
        return "\n".join(parts)
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_as_text(item) for item in value) or "—"
    return _as_text(value) or "—"


def _safety_text(value: Any) -> str:
    if not isinstance(value, dict):
        return _mapping_text(value)
    labels = {
        "evidence_authorized": "差異規則已確認",
        "no_identity_mutation": "身份字元未改變",
        "unique_independent_family": "3D 家族唯一",
        "reciprocal_best": "同 ITEM 無其他 ISO 家族競爭",
        "ownership_passes": "ITEM 可使用",
        "auto_safe": "可安全批次",
        "alnum_equal": "英數骨架一致",
        "unique_family": "3D 家族唯一",
        "ownership_clear": "ITEM 可使用",
    }
    return "\n".join(
        f"{'✓' if state is True else '✕'} {labels.get(str(key), str(key))}"
        for key, state in value.items()
    ) or "—"


@dataclass
class _Decision:
    status: str
    candidate_idx: int | None = None
    origin: str = "manual"


class MatchWorkbenchDialog(QDialog):
    """以 master-detail 方式處理 fuzzy candidates 的配對工作檯。"""

    CATEGORY_ORDER = (
        "safe_batch",
        "symbol_pattern",
        "item_review",
        "blocked",
        "no_candidate",
    )
    CATEGORY_LABELS = {
        "safe_batch": "安全批次",
        "symbol_pattern": "符號模式",
        "item_review": "逐筆判讀",
        "blocked": "阻擋",
        "no_candidate": "無候選",
    }
    _BLOCKING_OWNERSHIP_MARKERS = {
        "conflict",
        "claimed_by_other",
        "multiple_owner",
        "ownership_conflict",
        "blocked",
        "歸屬衝突",
        "已被其他家族認領",
    }

    def __init__(
        self,
        parent: QWidget | None,
        fuzzy_unmatched: list[dict[str, Any]] | None,
        project_dir: str | None = None,
        candidate_rescuer: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ISO / 3D 配對工作檯")
        self.setModal(True)
        self.setMinimumSize(1120, 680)
        self.resize(1380, 820)

        self._unmatched = list(fuzzy_unmatched or [])
        self._project_dir = _as_text(project_dir)
        self._candidate_rescuer = candidate_rescuer
        self._categories = {
            idx: self._classify_case(item)
            for idx, item in enumerate(self._unmatched)
        }
        self._decisions: dict[int, _Decision] = {}
        self._accepted_selections: list[dict[str, Any]] = []
        self._pending_rules: list[dict[str, str]] = []
        self._decision_events: list[tuple[int, str]] = []
        self._current_case_idx: int | None = None
        self._active_pattern_preview: SymbolBatchPreview | None = None
        self._expanded_cases: set[int] = set()
        self._queue_items: dict[int, QTreeWidgetItem] = {}
        self._shortcuts: list[QShortcut] = []

        self._apply_style()
        self._build_ui()
        self._configure_action_surfaces()
        self._install_shortcuts()
        self._populate_queue()
        self._select_first_case()
        self._refresh_summary()

    def _configure_action_surfaces(self) -> None:
        prominent_actions = (
            (self.finish_button, "result", "primary"),
            (self.safe_batch_button, "play", "secondary"),
            (self.pattern_batch_button, "tune", "secondary"),
            (self.stage_button, "link", "secondary"),
        )
        for button, icon_name, motion_role in prominent_actions:
            button.setIcon(
                app_icon(icon_name, normal="#FFFFFF", active="#FFFFFF")
            )
            button.setIconSize(QSize(17, 17))
            button.setProperty("motion-role", motion_role)

        secondary_actions = (
            (self.expand_candidates_button, "eye"),
            (self.rescue_candidates_button, "refresh"),
            (self.undo_button, "history"),
        )
        for button, icon_name in secondary_actions:
            button.setIcon(app_icon(icon_name))
            button.setIconSize(QSize(17, 17))
            button.setProperty("motion-role", "secondary")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selections(self) -> list[dict[str, Any]]:
        """回傳最終確認的 selections；staged 決策不會提前外洩。"""

        return [dict(item) for item in self._accepted_selections]

    def get_pending_rules(self) -> list[dict[str, str]]:
        """Return project rules staged in the same final change set."""

        return [dict(rule) for rule in self._pending_rules]

    @property
    def selections(self) -> list[dict[str, Any]]:
        return self.get_selections()

    def get_staged_decisions(self) -> list[dict[str, Any]]:
        """提供預覽／測試使用，不代表已接受。"""

        result: list[dict[str, Any]] = []
        for case_idx, decision in sorted(self._decisions.items()):
            result.append(
                {
                    "case_index": case_idx,
                    "status": decision.status,
                    "candidate_index": decision.candidate_idx,
                    "origin": decision.origin,
                }
            )
        return result

    def category_counts(self) -> dict[str, int]:
        return {
            key: sum(1 for value in self._categories.values() if value == key)
            for key in self.CATEGORY_ORDER
        }

    def select_case(self, case_idx: int) -> bool:
        item = self._queue_items.get(case_idx)
        if item is None:
            return False
        self.queue_tree.setCurrentItem(item)
        return True

    def stage_candidate(
        self,
        case_idx: int,
        candidate_idx: int,
        *,
        origin: str = "manual",
    ) -> bool:
        """暫存一筆人工決策；hard-blocked 候選不可在本工作檯覆寫。"""

        candidate = self._candidate_at(case_idx, candidate_idx)
        if candidate is None or self._candidate_is_blocked(candidate):
            return False
        self._decisions[case_idx] = _Decision(
            status="staged",
            candidate_idx=candidate_idx,
            origin=origin,
        )
        self._record_event(
            case_idx,
            f"暫存候選：{_first_value(candidate.get('line_3d'), candidate.get('raw_3d'))}",
        )
        self._refresh_case(case_idx)
        return True

    def stage_all_auto_safe(self) -> int:
        """只暫存唯一且明確 auto_safe 的候選，不參考 score 門檻。"""

        staged: list[tuple[int, int]] = []
        for case_idx in range(len(self._unmatched)):
            if case_idx in self._decisions:
                continue
            safe_idx = self._unique_safe_candidate_index(case_idx)
            if safe_idx is None:
                continue
            staged.append((case_idx, safe_idx))
        for case_idx, safe_idx in staged:
            self._decisions[case_idx] = _Decision(
                status="staged",
                candidate_idx=safe_idx,
                origin="safe_batch",
            )
            self._decision_events.append((case_idx, "暫存安全唯一候選"))
            queue_item = self._queue_items.get(case_idx)
            if queue_item is not None:
                queue_item.setText(0, self._queue_case_text(case_idx))
        if self._current_case_idx in {case_idx for case_idx, _ in staged}:
            self._load_case(self._current_case_idx)
        self._refresh_summary()
        self._refresh_log()
        return len(staged)

    def stage_symbol_batch(
        self,
        signature: PatternSignature,
        *,
        remember_rule: bool = False,
    ) -> SymbolBatchPreview:
        """Stage the independently safe members of one exact symbol pattern."""

        preview = preview_symbol_batch(
            self._unmatched,
            signature,
            skip_cases=self._decisions,
        )
        origin = "symbol_batch:" + pattern_signature_label(signature)
        for case_idx, candidate_idx in preview.eligible:
            self._decisions[case_idx] = _Decision(
                status="staged",
                candidate_idx=candidate_idx,
                origin=origin,
            )
            self._decision_events.append((
                case_idx,
                f"依符號模式暫存：{pattern_signature_label(signature)}",
            ))
            queue_item = self._queue_items.get(case_idx)
            if queue_item is not None:
                queue_item.setText(0, self._queue_case_text(case_idx))

        if remember_rule and len(signature) == 1:
            _gap, left, right = signature[0]
            if left and right and not any(ch in "-|" for ch in left + right):
                rule = {
                    "iso_symbol": left,
                    "candidate_symbol": right,
                    "pattern": pattern_signature_label(signature),
                }
                if rule not in self._pending_rules:
                    self._pending_rules.append(rule)

        if self._current_case_idx in {idx for idx, _candidate in preview.eligible}:
            self._load_case(self._current_case_idx)
        self._refresh_summary()
        self._refresh_pattern_bar()
        self._refresh_log()
        return preview

    def reject_case(self, case_idx: int) -> bool:
        if not self._valid_case_index(case_idx):
            return False
        self._decisions[case_idx] = _Decision(status="rejected")
        self._record_event(case_idx, "人工標記：本輪略過目前候選")
        self._refresh_case(case_idx)
        return True

    def defer_case(self, case_idx: int) -> bool:
        if not self._valid_case_index(case_idx):
            return False
        self._decisions[case_idx] = _Decision(status="deferred")
        self._record_event(case_idx, "人工標記：本輪稍後處理")
        self._refresh_case(case_idx)
        return True

    def undo_case(self, case_idx: int) -> bool:
        if case_idx not in self._decisions:
            return False
        del self._decisions[case_idx]
        self._record_event(case_idx, "復原暫存決策")
        self._refresh_case(case_idx)
        return True

    # ------------------------------------------------------------------
    # Classification and safety
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence(candidate: dict[str, Any]) -> dict[str, Any]:
        evidence = candidate.get("evidence")
        return evidence if isinstance(evidence, dict) else {}

    def _classify_case(self, item: dict[str, Any]) -> str:
        candidates = item.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return "no_candidate"
        valid_candidates = [
            candidate for candidate in candidates if isinstance(candidate, dict)
        ]
        if not valid_candidates:
            return "no_candidate"
        if bool(item.get("blocked")) or all(
            self._candidate_is_blocked(candidate)
            for candidate in valid_candidates
        ):
            return "blocked"
        safe_count = sum(
            1
            for candidate in candidates
            if isinstance(candidate, dict) and self._candidate_is_auto_safe(candidate)
        )
        if safe_count == 1:
            return "safe_batch"
        if any(
            isinstance(candidate, dict) and self._candidate_has_symbol_pattern(candidate, item)
            for candidate in candidates
        ):
            return "symbol_pattern"
        return "item_review"

    def _candidate_is_auto_safe(self, candidate: dict[str, Any]) -> bool:
        # Legacy candidates have no evidence and must never silently become safe.
        evidence = self._evidence(candidate)
        if not evidence or candidate.get("auto_safe") is not True:
            return False
        if self._candidate_is_blocked(candidate):
            return False

        checks = candidate.get(
            "safety_checks",
            evidence.get("safety_checks", evidence.get("safe_conditions")),
        )
        if isinstance(checks, dict) and any(value is not True for value in checks.values()):
            return False
        if isinstance(checks, bool) and not checks:
            return False
        if isinstance(checks, (list, tuple)):
            for check in checks:
                if isinstance(check, dict) and check.get("passed") is not True:
                    return False
                if isinstance(check, bool) and not check:
                    return False
        return True

    def _candidate_is_blocked(self, candidate: dict[str, Any]) -> bool:
        evidence = self._evidence(candidate)
        if bool(candidate.get("blocked")) or bool(candidate.get("hard_block")):
            return True
        if bool(evidence.get("blocked")) or bool(evidence.get("hard_block")):
            return True
        reasons = candidate.get("blocking_reasons", evidence.get("blocking_reasons"))
        if isinstance(reasons, (list, tuple, set)) and bool(reasons):
            return True
        if _as_text(reasons):
            return True
        ownership = _first_value(
            candidate.get("ownership_status"),
            evidence.get("ownership_status"),
            evidence.get("ownership"),
        ).lower()
        if ownership in self._BLOCKING_OWNERSHIP_MARKERS:
            return True
        return ownership.startswith(
            ("conflict:", "blocked:", "claimed_by_other:", "multiple_owner:")
        ) or "歸屬衝突" in ownership

    def _candidate_has_symbol_pattern(
        self,
        candidate: dict[str, Any],
        item: dict[str, Any],
    ) -> bool:
        evidence = self._evidence(candidate)
        if not evidence:
            return False
        kind = _first_value(
            evidence.get("difference_type"),
            evidence.get("evidence_type"),
        ).lower()
        if kind in {"symbol_only", "symbol_pattern", "symbol_difference", "符號差異"}:
            return True
        if evidence.get("symbol_only") is True or _as_text(evidence.get("symbol_diff")):
            return True

        iso_raw = self._iso_raw(item)
        three_d_raw = self._three_d_raw(candidate)
        return (
            bool(iso_raw and three_d_raw)
            and _alnum_tokens(iso_raw) == _alnum_tokens(three_d_raw)
            and _symbol_runs(iso_raw) != _symbol_runs(three_d_raw)
        )

    def _unique_safe_candidate_index(self, case_idx: int) -> int | None:
        if not self._valid_case_index(case_idx):
            return None
        candidates = self._unmatched[case_idx].get("candidates", [])
        safe = [
            idx
            for idx, candidate in enumerate(candidates)
            if isinstance(candidate, dict) and self._candidate_is_auto_safe(candidate)
        ]
        return safe[0] if len(safe) == 1 else None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("ISO / 3D 配對工作檯")
        title.setObjectName("workbenchTitle")
        title_col.addWidget(title)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("workbenchSummary")
        title_col.addWidget(self.summary_label)
        title_row.addLayout(title_col)
        title_row.addStretch()
        warning = QLabel("分數只用於排序；安全條件才有權批次套用")
        warning.setObjectName("safetyBanner")
        title_row.addWidget(warning)
        root.addLayout(title_row)

        legend_row = QHBoxLayout()
        legend_row.setSpacing(6)
        legend_row.addWidget(QLabel("差異圖例"))
        for text, background, foreground in [
            ("完全一致", "#DCFCE7", "#166534"),
            ("符號差異", "#DBEAFE", "#1D4ED8"),
            ("多出／缺少 token", "#FFEDD5", "#C2410C"),
            ("身份內容改變", "#FEE2E2", "#B91C1C"),
            ("衝突／阻擋", "#F3E8FF", "#7E22CE"),
        ]:
            badge = QLabel(text)
            badge.setStyleSheet(
                f"background:{background};color:{foreground};"
                "border-radius:6px;padding:3px 7px;font-size:11px;font-weight:700;"
            )
            legend_row.addWidget(badge)
        legend_row.addStretch()
        shortcut_note = QLabel(
            "快捷鍵：1/2/3 選候選｜Enter 使用｜X 本輪略過｜S 本輪稍後｜Ctrl+Z 復原"
        )
        shortcut_note.setObjectName("mutedText")
        legend_row.addWidget(shortcut_note)
        root.addLayout(legend_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_queue_panel())
        splitter.addWidget(self._build_candidate_panel())
        splitter.addWidget(self._build_context_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 690, 370])
        root.addWidget(splitter, stretch=1)

        footer = QHBoxLayout()
        self.staged_status_label = QLabel()
        self.staged_status_label.setObjectName("stagedStatus")
        footer.addWidget(self.staged_status_label)
        footer.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.finish_button = QPushButton("確認並套用")
        self.finish_button.setObjectName("finishButton")
        self.finish_button.clicked.connect(self._finish)
        footer.addWidget(self.finish_button)
        root.addLayout(footer)

    def _build_queue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("queuePanel")
        panel.setMinimumWidth(235)
        panel.setMaximumWidth(330)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        heading = QLabel("判讀佇列")
        heading.setObjectName("panelHeading")
        lay.addWidget(heading)
        note = QLabel("先處理重複模式，再看少量例外。")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.queue_tree = QTreeWidget()
        self.queue_tree.setObjectName("evidenceQueue")
        self.queue_tree.setHeaderHidden(True)
        self.queue_tree.currentItemChanged.connect(self._on_queue_item_changed)
        lay.addWidget(self.queue_tree, stretch=1)

        self.safe_batch_button = QPushButton("套用全部安全配對")
        self.safe_batch_button.setObjectName("safeBatchButton")
        self.safe_batch_button.clicked.connect(self._on_stage_all_auto_safe)
        lay.addWidget(self.safe_batch_button)
        batch_note = QLabel("只處理候選唯一且所有安全條件通過的案例。")
        batch_note.setObjectName("mutedText")
        batch_note.setWordWrap(True)
        lay.addWidget(batch_note)
        return panel

    def _build_candidate_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("candidatePanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        self.case_title = QLabel("尚未選擇案例")
        self.case_title.setObjectName("caseTitle")
        self.case_title.setWordWrap(True)
        lay.addWidget(self.case_title)
        self.case_meta = QLabel()
        self.case_meta.setObjectName("mutedText")
        self.case_meta.setWordWrap(True)
        lay.addWidget(self.case_meta)

        self.pattern_frame = QFrame()
        self.pattern_frame.setObjectName("patternBatchFrame")
        pattern_lay = QHBoxLayout(self.pattern_frame)
        pattern_lay.setContentsMargins(10, 8, 10, 8)
        pattern_lay.setSpacing(8)
        self.pattern_summary = QLabel()
        self.pattern_summary.setObjectName("patternSummary")
        self.pattern_summary.setWordWrap(True)
        pattern_lay.addWidget(self.pattern_summary, stretch=1)
        self.remember_pattern_checkbox = QCheckBox("記住此符號對")
        self.remember_pattern_checkbox.setToolTip(
            "目前批次立即套用；勾選後才會在最後確認時一併保存為本專案規則。"
        )
        pattern_lay.addWidget(self.remember_pattern_checkbox)
        self.pattern_batch_button = QPushButton("預覽並套用此模式")
        self.pattern_batch_button.setObjectName("patternBatchButton")
        self.pattern_batch_button.clicked.connect(self._on_stage_symbol_batch)
        pattern_lay.addWidget(self.pattern_batch_button)
        self.pattern_frame.setVisible(False)
        lay.addWidget(self.pattern_frame)

        table_label = QLabel("3D 候選（依證據分數排序）")
        table_label.setObjectName("panelHeading")
        lay.addWidget(table_label)

        self.diff_frame = QFrame()
        self.diff_frame.setObjectName("inlineDiffFrame")
        diff_lay = QGridLayout(self.diff_frame)
        diff_lay.setContentsMargins(10, 7, 10, 7)
        diff_lay.setHorizontalSpacing(8)
        diff_lay.setVerticalSpacing(3)
        self.diff_kind_label = QLabel("尚未選擇候選")
        self.diff_kind_label.setObjectName("diffKind")
        diff_lay.addWidget(self.diff_kind_label, 0, 0, 1, 2)
        diff_lay.addWidget(QLabel("ISO"), 1, 0)
        self.diff_iso_label = QLabel("—")
        self.diff_iso_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        diff_lay.addWidget(self.diff_iso_label, 1, 1)
        diff_lay.addWidget(QLabel("3D"), 2, 0)
        self.diff_3d_label = QLabel("—")
        self.diff_3d_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        diff_lay.addWidget(self.diff_3d_label, 2, 1)
        diff_lay.setColumnStretch(1, 1)
        lay.addWidget(self.diff_frame)

        self.candidate_table = QTableWidget()
        self.candidate_table.setObjectName("candidateTable")
        self.candidate_table.setColumnCount(5)
        self.candidate_table.setHorizontalHeaderLabels(
            ["3D 候選", "證據分數", "來源", "證據摘要", "狀態"]
        )
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.candidate_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.candidate_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.candidate_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.itemSelectionChanged.connect(
            self._on_candidate_selection_changed
        )
        lay.addWidget(self.candidate_table, stretch=1)

        self.expand_candidates_button = QPushButton("顯示全部候選")
        self.expand_candidates_button.clicked.connect(self._toggle_candidate_expansion)
        self.expand_candidates_button.setVisible(False)
        candidate_tools = QHBoxLayout()
        candidate_tools.addWidget(self.expand_candidates_button)
        self.rescue_candidates_button = QPushButton("從 First_try 補找")
        self.rescue_candidates_button.setToolTip(
            "重新讀取 3D 原始匯出，只加入確實存在且帶 Path / Level 證據的候選"
        )
        self.rescue_candidates_button.setEnabled(self._candidate_rescuer is not None)
        self.rescue_candidates_button.clicked.connect(
            self._rescue_current_candidates
        )
        candidate_tools.addWidget(self.rescue_candidates_button)
        candidate_tools.addStretch(1)
        lay.addLayout(candidate_tools)

        self.no_candidate_label = QLabel("此 ISO 目前沒有候選；保持未配對，不猜。")
        self.no_candidate_label.setObjectName("blockingText")
        self.no_candidate_label.setVisible(False)
        lay.addWidget(self.no_candidate_label)

        actions = QHBoxLayout()
        self.stage_button = QPushButton("使用這個配對")
        self.stage_button.setObjectName("stageButton")
        self.stage_button.clicked.connect(self._stage_selected_candidate)
        actions.addWidget(self.stage_button)
        self.reject_button = QPushButton("本輪略過")
        self.reject_button.setToolTip("只在本次視窗略過；未提交為永久決策")
        self.reject_button.clicked.connect(self._reject_current_case)
        actions.addWidget(self.reject_button)
        self.defer_button = QPushButton("本輪稍後")
        self.defer_button.setToolTip("保留在待判讀清單，下次仍會出現")
        self.defer_button.clicked.connect(self._defer_current_case)
        actions.addWidget(self.defer_button)
        self.undo_button = QPushButton("復原")
        self.undo_button.clicked.connect(self._undo_current_case)
        actions.addWidget(self.undo_button)
        actions.addStretch()
        lay.addLayout(actions)
        return panel

    def _build_context_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("contextPanel")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(480)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        heading = QLabel("判斷依據與資料脈絡")
        heading.setObjectName("panelHeading")
        lay.addWidget(heading)

        self.context_tabs = QTabWidget()
        self.context_tabs.setObjectName("contextTabs")
        self.context_tabs.addTab(self._build_evidence_tab(), "判斷依據")
        self.context_tabs.addTab(self._build_agent_tab(), "AI 建議")
        self.context_tabs.addTab(self._build_log_tab(), "技術紀錄")
        lay.addWidget(self.context_tabs, stretch=1)
        return panel

    def _build_evidence_tab(self) -> QWidget:
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(8, 10, 8, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(9)
        self._evidence_labels: dict[str, QLabel] = {}
        fields = [
            ("ISO 原始值", "iso_raw"),
            ("3D 原始值", "three_d_raw"),
            ("ISO 英數骨架", "iso_skeleton"),
            ("3D 英數骨架", "three_d_skeleton"),
            ("符號差異", "symbol_diff"),
            ("Path", "path"),
            ("3D 家族", "family"),
            ("ITEM 使用狀態", "ownership"),
            ("安全條件", "safety"),
            ("判讀原因", "reason"),
        ]
        for row, (title, key) in enumerate(fields):
            title_label = QLabel(title)
            title_label.setObjectName("evidenceFieldTitle")
            title_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            value_label = QLabel("—")
            value_label.setObjectName(f"evidence_{key}")
            value_label.setWordWrap(True)
            value_label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(title_label, row, 0)
            grid.addWidget(value_label, row, 1)
            self._evidence_labels[key] = value_label
        rule_note = QLabel(
            "符號規則由中間的『預覽並套用此模式』處理：本次立即使用，"
            "勾選後才會在最終確認時記住。"
        )
        rule_note.setObjectName("mutedText")
        rule_note.setWordWrap(True)
        grid.addWidget(rule_note, len(fields), 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(fields) + 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(content)
        return scroll

    def _build_agent_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        note = QLabel("Agent 可閱讀證據並提出建議；建議不會直接成為配對決策。")
        note.setObjectName("agentNotice")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.agent_text = QPlainTextEdit()
        self.agent_text.setObjectName("agentProposal")
        self.agent_text.setReadOnly(True)
        lay.addWidget(self.agent_text, stretch=1)
        return tab

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("decisionLog")
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.log_text)
        return tab

    # ------------------------------------------------------------------
    # Queue and detail rendering
    # ------------------------------------------------------------------

    def _populate_queue(self) -> None:
        self.queue_tree.clear()
        self._queue_items.clear()
        grouped = {key: [] for key in self.CATEGORY_ORDER}
        for case_idx, category in self._categories.items():
            grouped[category].append(case_idx)

        for category in self.CATEGORY_ORDER:
            indexes = grouped[category]
            if not indexes:
                continue
            top = QTreeWidgetItem(
                [f"{self.CATEGORY_LABELS[category]}  {len(indexes)}"]
            )
            top.setData(0, Qt.ItemDataRole.UserRole, None)
            self.queue_tree.addTopLevelItem(top)
            if category == "symbol_pattern":
                pattern_groups: dict[PatternSignature, list[int]] = {}
                ungrouped: list[int] = []
                for case_idx in indexes:
                    signature = self._case_pattern_signature(case_idx)
                    if signature:
                        pattern_groups.setdefault(signature, []).append(case_idx)
                    else:
                        ungrouped.append(case_idx)
                for signature, case_indexes in sorted(
                    pattern_groups.items(),
                    key=lambda pair: (-len(pair[1]), pattern_signature_label(pair[0])),
                ):
                    pattern_item = QTreeWidgetItem([
                        f"{pattern_signature_label(signature)}  ·  {len(case_indexes)}"
                    ])
                    pattern_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        ("pattern", signature),
                    )
                    top.addChild(pattern_item)
                    for case_idx in case_indexes:
                        child = QTreeWidgetItem([self._queue_case_text(case_idx)])
                        child.setData(0, Qt.ItemDataRole.UserRole, case_idx)
                        pattern_item.addChild(child)
                        self._queue_items[case_idx] = child
                    pattern_item.setExpanded(False)
                indexes = ungrouped
            for case_idx in indexes:
                child = QTreeWidgetItem([self._queue_case_text(case_idx)])
                child.setData(0, Qt.ItemDataRole.UserRole, case_idx)
                top.addChild(child)
                self._queue_items[case_idx] = child
            top.setExpanded(True)

    def _select_first_case(self) -> None:
        for category in self.CATEGORY_ORDER:
            for case_idx, actual in self._categories.items():
                if actual == category:
                    self.select_case(case_idx)
                    return
        self._clear_case()

    def _on_queue_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        value = current.data(0, Qt.ItemDataRole.UserRole)
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and value[0] == "pattern"
        ):
            signature = value[1]
            if isinstance(signature, tuple):
                for case_idx in range(len(self._unmatched)):
                    if (
                        case_idx not in self._decisions
                        and self._case_pattern_signature(case_idx) == signature
                    ):
                        self.select_case(case_idx)
                        return
            return
        if not isinstance(value, int):
            return
        self._load_case(value)

    def _load_case(self, case_idx: int) -> None:
        if not self._valid_case_index(case_idx):
            return
        self._current_case_idx = case_idx
        item = self._unmatched[case_idx]
        iso_line = _first_value(item.get("iso_line"), item.get("iso_raw")) or "—"
        spool = _as_text(item.get("iso_spool"))
        category = self.CATEGORY_LABELS[self._categories[case_idx]]
        self.case_title.setText(iso_line)
        self.case_meta.setText(
            f"流水號：{spool or '—'}　｜　處理通道：{category}　｜　"
            f"候選：{len(item.get('candidates', []))}"
        )

        candidates = item.get("candidates", [])
        decision = self._decisions.get(case_idx)
        wanted_idx = decision.candidate_idx if decision else 0
        candidate_indexes = [
            idx for idx, candidate in enumerate(candidates)
            if isinstance(candidate, dict)
        ]
        is_expanded = case_idx in self._expanded_cases
        visible_indexes = candidate_indexes if is_expanded else candidate_indexes[:3]
        if wanted_idx in candidate_indexes and wanted_idx not in visible_indexes:
            visible_indexes.append(wanted_idx)
        self.candidate_table.blockSignals(True)
        self.candidate_table.setRowCount(0)
        for candidate_idx in visible_indexes:
            candidate = candidates[candidate_idx]
            row = self.candidate_table.rowCount()
            self.candidate_table.insertRow(row)
            line_item = QTableWidgetItem(
                _first_value(candidate.get("line_3d"), candidate.get("raw_3d")) or "—"
            )
            line_item.setData(Qt.ItemDataRole.UserRole, candidate_idx)
            self.candidate_table.setItem(row, 0, line_item)
            score_item = QTableWidgetItem(
                self._format_evidence_score(candidate.get("score"))
            )
            source_item = QTableWidgetItem(self._candidate_source(candidate))
            summary_item = QTableWidgetItem(
                self._candidate_summary(candidate, item)
            )
            state_item = QTableWidgetItem(
                self._candidate_state_text(case_idx, candidate_idx)
            )
            self.candidate_table.setItem(row, 1, score_item)
            self.candidate_table.setItem(row, 2, source_item)
            self.candidate_table.setItem(row, 3, summary_item)
            self.candidate_table.setItem(row, 4, state_item)
            self._apply_candidate_row_style(
                row,
                candidate,
                item,
                [line_item, score_item, source_item, summary_item, state_item],
            )
            self.candidate_table.setRowHeight(row, 42)

        self.candidate_table.blockSignals(False)
        hidden_count = max(0, len(candidate_indexes) - len(visible_indexes))
        self.expand_candidates_button.setVisible(len(candidate_indexes) > 3)
        self.expand_candidates_button.setText(
            "只顯示 Top 3"
            if is_expanded
            else f"展開其餘 {hidden_count} 個候選"
        )
        self.no_candidate_label.setVisible(self.candidate_table.rowCount() == 0)
        if self.candidate_table.rowCount():
            wanted_row = self._table_row_for_candidate(wanted_idx)
            self.candidate_table.selectRow(wanted_row if wanted_row is not None else 0)
        else:
            self._render_evidence(None)
        self._refresh_pattern_bar()
        self._sync_action_state()
        self._refresh_log()

    def _clear_case(self) -> None:
        self._current_case_idx = None
        self.case_title.setText("目前沒有待判讀案例")
        self.case_meta.clear()
        self.candidate_table.setRowCount(0)
        self.pattern_frame.setVisible(False)
        self.expand_candidates_button.setVisible(False)
        self.no_candidate_label.setVisible(True)
        self._render_evidence(None)
        self._sync_action_state()

    def _on_candidate_selection_changed(self) -> None:
        self._render_evidence(self._selected_candidate())
        self._render_inline_diff(self._selected_candidate())
        self._refresh_pattern_bar()
        self._sync_action_state()
        self._refresh_log()

    def _rescue_current_candidates(self) -> None:
        case_idx = self._current_case_idx
        if case_idx is None or self._candidate_rescuer is None:
            return
        case = self._unmatched[case_idx]
        self.rescue_candidates_button.setEnabled(False)
        self.rescue_candidates_button.setText("正在讀取 First_try…")
        try:
            recovered = self._candidate_rescuer(dict(case))
        except Exception as exc:
            QMessageBox.warning(
                self,
                "補找失敗",
                f"無法從 First_try 補找候選：{exc}",
            )
            return
        finally:
            self.rescue_candidates_button.setText("從 First_try 補找")
            self.rescue_candidates_button.setEnabled(True)

        candidates = case.get("candidates", [])
        candidates = list(candidates) if isinstance(candidates, list) else []
        existing = {
            (
                _as_text(candidate.get("item_id")),
                _as_text(candidate.get("line_3d")).upper(),
                _as_text(candidate.get("raw_3d")).upper(),
            )
            for candidate in candidates
            if isinstance(candidate, dict)
        }
        added = 0
        for candidate in recovered or []:
            if not isinstance(candidate, dict):
                continue
            key = (
                _as_text(candidate.get("item_id")),
                _as_text(candidate.get("line_3d")).upper(),
                _as_text(candidate.get("raw_3d")).upper(),
            )
            if key in existing:
                continue
            existing.add(key)
            candidates.append(dict(candidate))
            added += 1

        if added:
            candidates.sort(key=lambda item: -float(item.get("score", 0.0)))
            case["candidates"] = annotate_candidate_families(candidates[:50])
            annotate_family_aware_safety(self._unmatched)
            self._categories = {
                idx: self._classify_case(item)
                for idx, item in enumerate(self._unmatched)
            }
            self._expanded_cases.add(case_idx)
            self._populate_queue()
            self.select_case(case_idx)
            self._record_event(case_idx, f"從 First_try 補回 {added} 個候選")
            QMessageBox.information(
                self,
                "已補回候選",
                f"從 First_try 找到並加入 {added} 個有原始列證據的候選。\n"
                "請確認 3D 原始值、Path 與 ITEM 使用狀態後再暫存。",
            )
        else:
            QMessageBox.information(
                self,
                "沒有新增候選",
                "First_try 中沒有找到新的相符 3D 身分，或找到的項目已在清單內。",
            )

    def _render_evidence(self, candidate: dict[str, Any] | None) -> None:
        if self._current_case_idx is None or candidate is None:
            for label in self._evidence_labels.values():
                label.setText("—")
            self._render_inline_diff(None)
            self.agent_text.setPlainText("尚無可顯示的 Agent 提案。")
            return

        item = self._unmatched[self._current_case_idx]
        evidence = self._evidence(candidate)
        iso_raw = self._iso_raw(item)
        three_d_raw = self._three_d_raw(candidate)

        skeletons = evidence.get("alnum_skeleton")
        skeleton_iso = ""
        skeleton_3d = ""
        if isinstance(skeletons, dict):
            skeleton_iso = _first_value(skeletons.get("iso"), skeletons.get("left"))
            skeleton_3d = _first_value(skeletons.get("3d"), skeletons.get("right"))

        values = {
            "iso_raw": iso_raw or "—",
            "three_d_raw": three_d_raw or "—",
            "iso_skeleton": _first_value(
                evidence.get("iso_skeleton"), skeleton_iso
            ) or _alnum_skeleton(iso_raw),
            "three_d_skeleton": _first_value(
                evidence.get("three_d_skeleton"),
                evidence.get("3d_skeleton"),
                skeleton_3d,
            ) or _alnum_skeleton(three_d_raw),
            "symbol_diff": _mapping_text(
                evidence.get("symbol_diff")
                or describe_symbol_difference(iso_raw, three_d_raw)
            ),
            "path": _first_value(
                candidate.get("PipeNodePath"),
                candidate.get("pipe_node_path"),
                candidate.get("path"),
                evidence.get("PipeNodePath"),
                evidence.get("pipe_node_path"),
                evidence.get("path"),
            ) or "—",
            "family": _first_value(
                candidate.get("family"),
                candidate.get("family_id"),
                evidence.get("family"),
                evidence.get("family_id"),
            ) or "—",
            "ownership": {
                "available": "可使用",
                "same_family": "同一 ISO 家族已使用",
                "claimed_by_other": "已被其他 ISO 家族使用",
                "unverifiable": "ITEM 身分無法穩定確認",
            }.get(_first_value(
                candidate.get("ownership_status"),
                evidence.get("ownership_status"),
                evidence.get("ownership"),
            ), _first_value(
                candidate.get("ownership_status"),
                evidence.get("ownership_status"),
                evidence.get("ownership"),
            ) or "未提供（不可據此自動推定安全）"),
            "safety": _safety_text(
                candidate.get("safety_checks")
                or evidence.get("safety_checks")
                or evidence.get("safe_conditions")
                or (
                    {"auto_safe": True}
                    if candidate.get("auto_safe") is True
                    else {"auto_safe": False}
                )
            ),
            "reason": _first_value(
                candidate.get("reason"), evidence.get("reason")
            ) or "—",
        }
        for key, text in values.items():
            self._evidence_labels[key].setText(text)

        proposal = (
            candidate.get("agent_proposal")
            or candidate.get("agent")
            or evidence.get("agent_proposal")
            or item.get("agent_proposal")
        )
        if proposal:
            if isinstance(proposal, str):
                proposal_text = proposal
            else:
                proposal_text = json.dumps(proposal, ensure_ascii=False, indent=2)
            self.agent_text.setPlainText(proposal_text)
        else:
            self.agent_text.setPlainText(
                "尚無 Agent 提案。\n\nAgent 建議只供參考；仍需由使用者暫存並最終確認。"
            )

    def _case_pattern_signature(self, case_idx: int) -> PatternSignature:
        if not self._valid_case_index(case_idx):
            return ()
        item = self._unmatched[case_idx]
        iso_raw = self._iso_raw(item)
        candidates = item.get("candidates", [])
        if not isinstance(candidates, list):
            return ()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            signature = pattern_signature(iso_raw, candidate)
            if signature:
                return signature
        return ()

    def _selected_pattern_signature(self) -> PatternSignature:
        if self._current_case_idx is None:
            return ()
        candidate = self._selected_candidate()
        if candidate is None:
            return ()
        return pattern_signature(
            self._iso_raw(self._unmatched[self._current_case_idx]),
            candidate,
        )

    def _refresh_pattern_bar(self) -> None:
        signature = self._selected_pattern_signature()
        if not signature:
            self._active_pattern_preview = None
            self.pattern_frame.setVisible(False)
            return
        preview = preview_symbol_batch(
            self._unmatched,
            signature,
            skip_cases=self._decisions,
        )
        self._active_pattern_preview = preview
        self.pattern_summary.setText(
            f"符號模式：{pattern_signature_label(signature)}\n"
            f"剩餘同型 {len(preview.member_cases)} 筆｜"
            f"可安全套用 {preview.eligible_count}｜"
            f"例外保留 {preview.excluded_count}"
        )
        rememberable = (
            bool(self._project_dir)
            and len(signature) == 1
            and bool(signature[0][1])
            and bool(signature[0][2])
            and not any(ch in "-|" for ch in signature[0][1] + signature[0][2])
        )
        self.remember_pattern_checkbox.setEnabled(rememberable)
        if not rememberable:
            self.remember_pattern_checkbox.setChecked(False)
        self.pattern_batch_button.setText(
            f"套用安全的 {preview.eligible_count} 筆"
        )
        self.pattern_batch_button.setEnabled(preview.eligible_count > 0)
        self.pattern_frame.setVisible(True)

    def _toggle_candidate_expansion(self) -> None:
        if self._current_case_idx is None:
            return
        if self._current_case_idx in self._expanded_cases:
            self._expanded_cases.remove(self._current_case_idx)
        else:
            self._expanded_cases.add(self._current_case_idx)
        self._load_case(self._current_case_idx)

    @staticmethod
    def _candidate_classification(candidate: dict[str, Any]) -> str:
        evidence = MatchWorkbenchDialog._evidence(candidate)
        classification = _as_text(evidence.get("classification"))
        if classification:
            return classification
        reason_codes = candidate.get("reason_codes", []) or []
        if isinstance(reason_codes, str):
            reason_codes = reason_codes.split(",")
        for value in (
            "identity_mutation",
            "extra_token",
            "punctuation_only",
            "exact",
        ):
            if value in reason_codes:
                return value
        return "unknown"

    @staticmethod
    def _classification_style(classification: str) -> tuple[str, str, str]:
        styles = {
            "exact": ("完全一致", "#ECFDF5", "#047857"),
            "punctuation_only": ("符號差異", "#EFF6FF", "#1D4ED8"),
            "extra_token": ("多出／缺少 token", "#FFF7ED", "#C2410C"),
            "identity_mutation": ("身份內容改變", "#FEF2F2", "#B91C1C"),
            "token_mismatch": ("身份不一致", "#FEF2F2", "#B91C1C"),
        }
        return styles.get(classification, ("弱相關候選", "#F8FAFC", "#64748B"))

    def _apply_candidate_row_style(
        self,
        row: int,
        candidate: dict[str, Any],
        item: dict[str, Any],
        cells: list[QTableWidgetItem],
    ) -> None:
        classification = self._candidate_classification(candidate)
        _label, background, foreground = self._classification_style(classification)
        for cell in cells:
            cell.setBackground(QBrush(QColor(background)))
        cells[0].setForeground(QBrush(QColor(foreground)))
        cells[0].setToolTip(self._candidate_summary(candidate, item))

        state = cells[-1].text()
        state_colors = {
            "安全": ("#DCFCE7", "#166534"),
            "已暫存": ("#DBEAFE", "#1E40AF"),
            "需人工": ("#FEF3C7", "#92400E"),
            "阻擋": ("#FEE2E2", "#991B1B"),
        }
        if state in state_colors:
            bg, fg = state_colors[state]
            cells[-1].setBackground(QBrush(QColor(bg)))
            cells[-1].setForeground(QBrush(QColor(fg)))

    @staticmethod
    def _diff_pair_html(left: str, right: str, color: str) -> tuple[str, str]:
        left_parts: list[str] = []
        right_parts: list[str] = []
        matcher = SequenceMatcher(None, left, right, autojunk=False)
        marker = (
            f"background:{color}22;color:{color};font-weight:700;"
            "border-radius:3px;padding:1px 2px;"
        )
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            left_text = html.escape(left[i1:i2])
            right_text = html.escape(right[j1:j2])
            if opcode == "equal":
                left_parts.append(left_text)
                right_parts.append(right_text)
                continue
            left_parts.append(
                f'<span style="{marker}">{left_text or "∅"}</span>'
            )
            right_parts.append(
                f'<span style="{marker}">{right_text or "∅"}</span>'
            )
        return "".join(left_parts), "".join(right_parts)

    def _render_inline_diff(self, candidate: dict[str, Any] | None) -> None:
        if self._current_case_idx is None or candidate is None:
            self.diff_kind_label.setText("尚未選擇候選")
            self.diff_kind_label.setStyleSheet("")
            self.diff_iso_label.setText("—")
            self.diff_3d_label.setText("—")
            return
        item = self._unmatched[self._current_case_idx]
        iso_raw = self._iso_raw(item)
        three_d_raw = self._three_d_raw(candidate)
        classification = self._candidate_classification(candidate)
        label, _background, foreground = self._classification_style(classification)
        iso_html, three_d_html = self._diff_pair_html(
            iso_raw,
            three_d_raw,
            foreground,
        )
        self.diff_kind_label.setText(label)
        self.diff_kind_label.setStyleSheet(
            f"color:{foreground};font-weight:800;"
        )
        self.diff_iso_label.setText(iso_html)
        self.diff_3d_label.setText(three_d_html)

    def _install_shortcuts(self) -> None:
        bindings = [
            ("1", lambda: self._select_candidate_rank(0)),
            ("2", lambda: self._select_candidate_rank(1)),
            ("3", lambda: self._select_candidate_rank(2)),
            ("Return", self._stage_selected_candidate),
            ("X", self._reject_current_case),
            ("S", self._defer_current_case),
            ("Ctrl+Z", self._undo_current_case),
        ]
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _select_candidate_rank(self, rank: int) -> None:
        if 0 <= rank < self.candidate_table.rowCount():
            self.candidate_table.selectRow(rank)

    def _select_next_pending_case(self) -> None:
        if not self._unmatched:
            return
        start = (self._current_case_idx or 0) + 1
        order = list(range(start, len(self._unmatched))) + list(range(0, start))
        for case_idx in order:
            if case_idx not in self._decisions:
                self.select_case(case_idx)
                return

    def _refresh_case(self, case_idx: int) -> None:
        queue_item = self._queue_items.get(case_idx)
        if queue_item is not None:
            queue_item.setText(0, self._queue_case_text(case_idx))
        if self._current_case_idx == case_idx:
            self._load_case(case_idx)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        counts = self.category_counts()
        self.summary_label.setText(
            "　".join(
                f"{self.CATEGORY_LABELS[key]} {counts[key]}"
                for key in self.CATEGORY_ORDER
            )
        )
        staged = sum(1 for d in self._decisions.values() if d.status == "staged")
        rejected = sum(1 for d in self._decisions.values() if d.status == "rejected")
        deferred = sum(1 for d in self._decisions.values() if d.status == "deferred")
        self.staged_status_label.setText(
            f"已暫存 {staged}　｜　本輪略過 {rejected}　｜　本輪稍後 {deferred}"
        )
        self.finish_button.setText(f"確認並套用 {staged} 筆")
        self.finish_button.setEnabled(staged > 0)
        eligible = sum(
            1
            for idx in range(len(self._unmatched))
            if idx not in self._decisions
            and self._unique_safe_candidate_index(idx) is not None
        )
        self.safe_batch_button.setText(f"套用全部安全配對（{eligible}）")
        self.safe_batch_button.setEnabled(eligible > 0)

    def _sync_action_state(self) -> None:
        has_case = self._current_case_idx is not None
        candidate = self._selected_candidate()
        can_stage = candidate is not None and not self._candidate_is_blocked(candidate)
        self.stage_button.setEnabled(can_stage)
        self.reject_button.setEnabled(has_case and candidate is not None)
        self.defer_button.setEnabled(has_case)
        self.undo_button.setEnabled(
            has_case and self._current_case_idx in self._decisions
        )

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _stage_selected_candidate(self) -> None:
        if self._current_case_idx is None:
            return
        candidate_idx = self._selected_candidate_index()
        if candidate_idx is None:
            return
        if not self.stage_candidate(self._current_case_idx, candidate_idx):
            QMessageBox.warning(
                self,
                "無法暫存",
                "此候選有 ownership 或其他 hard block，請先到專門的衝突流程處理。",
            )
            return
        self._select_next_pending_case()

    def _on_stage_all_auto_safe(self) -> None:
        count = self.stage_all_auto_safe()
        QMessageBox.information(
            self,
            "安全批次",
            f"已暫存 {count} 筆具明確安全證據的唯一候選；尚未寫入結果。",
        )
        self._select_next_pending_case()

    def _on_stage_symbol_batch(self) -> None:
        preview = self._active_pattern_preview
        if preview is None or not preview.signature:
            return
        remember = (
            self.remember_pattern_checkbox.isEnabled()
            and self.remember_pattern_checkbox.isChecked()
        )
        reply = QMessageBox.question(
            self,
            "套用符號模式",
            (
                f"模式：{pattern_signature_label(preview.signature)}\n\n"
                f"可安全套用 {preview.eligible_count} 筆；"
                f"另有 {preview.excluded_count} 筆例外會保留人工判讀。\n"
                + (
                    "本次立即使用，並在最後確認時記住為本專案規則。"
                    if remember
                    else "本次立即使用，不會建立未來規則。"
                )
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        applied = self.stage_symbol_batch(
            preview.signature,
            remember_rule=remember,
        )
        QMessageBox.information(
            self,
            "符號模式已暫存",
            (
                f"已暫存 {applied.eligible_count} 筆；"
                f"{applied.excluded_count} 筆例外沒有被套用。"
            ),
        )
        self._select_next_pending_case()

    def _reject_current_case(self) -> None:
        if self._current_case_idx is not None:
            if self.reject_case(self._current_case_idx):
                self._select_next_pending_case()

    def _defer_current_case(self) -> None:
        if self._current_case_idx is not None:
            if self.defer_case(self._current_case_idx):
                self._select_next_pending_case()

    def _undo_current_case(self) -> None:
        if self._current_case_idx is not None:
            self.undo_case(self._current_case_idx)

    def _finish(self) -> None:
        staged = [
            (idx, decision)
            for idx, decision in sorted(self._decisions.items())
            if decision.status == "staged" and decision.candidate_idx is not None
        ]
        if not staged:
            QMessageBox.information(self, "尚無配對", "目前沒有已暫存的配對可套用。")
            return
        reply = QMessageBox.question(
            self,
            "確認套用配對",
            (
                f"即將接受 {len(staged)} 筆配對。\n\n"
                f"同時保存 {len(self._pending_rules)} 條本專案符號規則。\n"
                "只有這些已暫存決策會輸出；本輪略過、稍後與阻擋案例不會寫入。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        accepted: list[dict[str, Any]] = []
        for case_idx, decision in staged:
            candidate = self._candidate_at(case_idx, decision.candidate_idx)
            if candidate is None or self._candidate_is_blocked(candidate):
                continue
            accepted.append(
                self._selection_from_candidate(case_idx, candidate, decision.origin)
            )
        self._accepted_selections = accepted
        self.accept()

    def reject(self) -> None:  # noqa: D401 - Qt override
        """取消 dialog 時不輸出任何 staged selection。"""

        self._accepted_selections = []
        self._pending_rules = []
        super().reject()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _selection_from_candidate(
        self,
        case_idx: int,
        candidate: dict[str, Any],
        origin: str,
    ) -> dict[str, Any]:
        item = self._unmatched[case_idx]
        iso_metadata = item.get("iso_metadata", {})
        if not isinstance(iso_metadata, dict):
            iso_metadata = {}
        reason_codes = candidate.get("reason_codes", []) or []
        if isinstance(reason_codes, str):
            reason_codes = [
                value.strip() for value in reason_codes.split(",") if value.strip()
            ]
        return {
            "iso_line": _as_text(item.get("iso_line")),
            "iso_spool": _as_text(item.get("iso_spool")),
            "iso_metadata": dict(iso_metadata),
            "line_3d": _as_text(candidate.get("line_3d")),
            "raw_3d": _first_value(
                candidate.get("raw_3d"), candidate.get("line_3d")
            ),
            "score": candidate.get("score", ""),
            "reason": _as_text(candidate.get("reason")),
            "trace": _as_text(candidate.get("trace")),
            "source": self._candidate_source(candidate),
            "evidence": dict(self._evidence(candidate)),
            "reason_codes": list(reason_codes),
            "path": _first_value(
                candidate.get("path"), candidate.get("PipeNodePath")
            ),
            "scope": _first_value(
                candidate.get("scope"), candidate.get("ScopeRoot")
            ),
            "parent_area": _first_value(
                candidate.get("parent_area"), candidate.get("ParentArea")
            ),
            "level": _first_value(
                candidate.get("level"), candidate.get("PipeNodeLevel")
            ),
            "item_id": _as_text(candidate.get("item_id")),
            "family_id": _as_text(candidate.get("family_id")),
            "family_role": _as_text(candidate.get("family_role")),
            "ownership_status": _as_text(candidate.get("ownership_status")),
            "safety_checks": dict(candidate.get("safety_checks", {}) or {}),
            "auto_safe": candidate.get("auto_safe") is True,
            "decision_status": "accepted",
            "decision_origin": origin,
            "decision_source": f"human_workbench:{origin}",
        }

    @staticmethod
    def _candidate_source(candidate: dict[str, Any]) -> str:
        source = _as_text(candidate.get("source"))
        if source:
            return source
        reason = _as_text(candidate.get("reason"))
        trace = _as_text(candidate.get("trace"))
        if "ISO 反向召回" in reason or "iso_reverse_recall" in trace:
            return "ISO 反查"
        if "語意索引" in reason:
            return "語意索引"
        if "編號主體" in reason:
            return "編號主體"
        if "同系統" in reason:
            return "同系統"
        if "全文" in reason:
            return "全文相似"
        return "fuzzy"

    def _candidate_summary(
        self,
        candidate: dict[str, Any],
        item: dict[str, Any],
    ) -> str:
        evidence = self._evidence(candidate)
        if not evidence:
            return "舊候選：無結構化 evidence，僅供逐筆判讀"
        if self._candidate_is_blocked(candidate):
            return "hard block：ownership 或安全條件衝突"
        if self._candidate_is_auto_safe(candidate):
            return "具明確安全條件，可進安全批次"
        if self._candidate_has_symbol_pattern(candidate, item):
            return "符號差異｜" + _mapping_text(
                evidence.get("symbol_diff")
                or describe_symbol_difference(
                    self._iso_raw(item), self._three_d_raw(candidate)
                )
            )
        classification = self._candidate_classification(candidate)
        label, _background, _foreground = self._classification_style(classification)
        if classification in {"extra_token", "identity_mutation", "token_mismatch"}:
            return f"{label}｜" + (
                _first_value(evidence.get("summary"), candidate.get("reason"))
                or "需人工判讀"
            )
        return _first_value(evidence.get("summary"), candidate.get("reason")) or "需人工判讀"

    def _candidate_state_text(self, case_idx: int, candidate_idx: int) -> str:
        decision = self._decisions.get(case_idx)
        if decision:
            if decision.status == "staged" and decision.candidate_idx == candidate_idx:
                return "已暫存"
            if decision.status == "rejected":
                return "本輪略過"
            if decision.status == "deferred":
                return "本輪稍後"
        candidate = self._candidate_at(case_idx, candidate_idx)
        if candidate is None:
            return "—"
        if self._candidate_is_blocked(candidate):
            return "阻擋"
        if self._candidate_is_auto_safe(candidate):
            return "安全"
        return "需人工"

    def _queue_case_text(self, case_idx: int) -> str:
        item = self._unmatched[case_idx]
        iso = _first_value(item.get("iso_line"), item.get("iso_raw")) or "（空白 ISO）"
        spool = _as_text(item.get("iso_spool"))
        base = iso if not spool else f"{iso}  ·  {spool}"
        decision = self._decisions.get(case_idx)
        if decision is None:
            return base
        labels = {
            "staged": "[已暫存]",
            "rejected": "[本輪略過]",
            "deferred": "[本輪稍後]",
        }
        return f"{base}  {labels.get(decision.status, '')}".rstrip()

    def _selected_candidate_index(self) -> int | None:
        row = self.candidate_table.currentRow()
        if row < 0:
            return None
        item = self.candidate_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else None

    def _selected_candidate(self) -> dict[str, Any] | None:
        if self._current_case_idx is None:
            return None
        candidate_idx = self._selected_candidate_index()
        if candidate_idx is None:
            return None
        return self._candidate_at(self._current_case_idx, candidate_idx)

    def _candidate_at(
        self,
        case_idx: int,
        candidate_idx: int | None,
    ) -> dict[str, Any] | None:
        if not self._valid_case_index(case_idx) or candidate_idx is None:
            return None
        candidates = self._unmatched[case_idx].get("candidates", [])
        if not isinstance(candidates, list) or not 0 <= candidate_idx < len(candidates):
            return None
        candidate = candidates[candidate_idx]
        return candidate if isinstance(candidate, dict) else None

    def _table_row_for_candidate(self, candidate_idx: int | None) -> int | None:
        if candidate_idx is None:
            return None
        for row in range(self.candidate_table.rowCount()):
            item = self.candidate_table.item(row, 0)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole) == candidate_idx
            ):
                return row
        return None

    def _valid_case_index(self, case_idx: int) -> bool:
        return isinstance(case_idx, int) and 0 <= case_idx < len(self._unmatched)

    @staticmethod
    def _iso_raw(item: dict[str, Any]) -> str:
        return _first_value(
            item.get("iso_raw"), item.get("raw_iso"), item.get("iso_line")
        )

    @staticmethod
    def _three_d_raw(candidate: dict[str, Any]) -> str:
        return _first_value(candidate.get("raw_3d"), candidate.get("line_3d"))

    @staticmethod
    def _format_evidence_score(value: Any) -> str:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return "—"
        if 0.0 <= score <= 1.0:
            score *= 100.0
        return f"{score:.0f} / 100"

    def _record_event(self, case_idx: int, message: str) -> None:
        self._decision_events.append((case_idx, message))
        self._refresh_log()

    def _refresh_log(self) -> None:
        if self._current_case_idx is None:
            self.log_text.setPlainText("尚未選擇案例。")
            return
        candidate = self._selected_candidate()
        trace = _as_text(candidate.get("trace")) if candidate else ""
        lines = ["候選 trace", trace or "—", "", "本次暫存操作"]
        events = [
            text
            for case_idx, text in self._decision_events
            if case_idx == self._current_case_idx
        ]
        lines.extend(f"- {event}" for event in events)
        if not events:
            lines.append("—")
        self.log_text.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Local style
    # ------------------------------------------------------------------

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            MatchWorkbenchDialog {
                background: #F1F5F9;
                color: #1E293B;
            }
            QLabel { color: #1E293B; }
            #workbenchTitle { font-size: 18px; font-weight: 800; color: #0F172A; }
            #workbenchSummary, #mutedText, #stagedStatus {
                color: #64748B; font-size: 12px;
            }
            #safetyBanner {
                color: #92400E; background: #FFFBEB; border: 1px solid #FDE68A;
                border-radius: 8px; padding: 7px 10px; font-weight: 600;
            }
            #queuePanel, #candidatePanel, #contextPanel {
                background: #FFFFFF; border: 1px solid #DDE4EE; border-radius: 9px;
            }
            #panelHeading { color: #334155; font-size: 13px; font-weight: 800; }
            #caseTitle { color: #0F172A; font-size: 16px; font-weight: 750; }
            #patternBatchFrame {
                background: #EFF6FF; border: 1px solid #BFDBFE;
                border-radius: 8px;
            }
            #patternSummary { color: #1E3A8A; font-size: 12px; font-weight: 650; }
            #inlineDiffFrame {
                background: #F8FAFC; border: 1px solid #E2E8F0;
                border-radius: 7px;
            }
            #diffKind { font-size: 12px; font-weight: 800; }
            QTreeWidget, QTableWidget, QPlainTextEdit {
                background: #FFFFFF; color: #1E293B; border: 1px solid #D6DEE9;
                border-radius: 7px; selection-background-color: #DBEAFE;
                selection-color: #1E3A8A;
            }
            QTreeWidget::item { padding: 5px 3px; }
            QHeaderView::section {
                background: #F8FAFC; color: #475569; border: none;
                border-bottom: 1px solid #DDE4EE; padding: 7px 8px;
                font-size: 12px; font-weight: 700;
            }
            QPushButton {
                background: #FFFFFF; color: #334155; border: 2px solid #CBD5E1;
                border-radius: 7px; padding: 6px 11px; font-weight: 600;
            }
            QPushButton:hover { background: #F8FAFC; border-color: #94A3B8; }
            QPushButton:pressed {
                background: #E2E8F0; padding: 7px 10px 5px 12px;
            }
            QPushButton:focus { border-color: #60A5FA; }
            QPushButton:disabled { color: #94A3B8; background: #F8FAFC; }
            #safeBatchButton, #stageButton, #finishButton, #patternBatchButton {
                background: #2563EB; color: #FFFFFF; border-color: #2563EB;
            }
            #safeBatchButton:hover, #stageButton:hover, #finishButton:hover,
            #patternBatchButton:hover {
                background: #1D4ED8;
            }
            #safeBatchButton:pressed, #stageButton:pressed, #finishButton:pressed,
            #patternBatchButton:pressed {
                background: #1E40AF;
            }
            #safeBatchButton:focus, #stageButton:focus, #finishButton:focus,
            #patternBatchButton:focus {
                border-color: #BFDBFE;
            }
            #safeBatchButton:disabled, #stageButton:disabled, #finishButton:disabled,
            #patternBatchButton:disabled {
                background: #CBD5E1; color: #F8FAFC; border-color: #CBD5E1;
            }
            #blockingText {
                color: #991B1B; background: #FEF2F2; border: 1px solid #FECACA;
                border-radius: 7px; padding: 8px;
            }
            #contextTabs::pane { border: 1px solid #E2E8F0; background: #FFFFFF; }
            #contextTabs QTabBar::tab {
                background: #F1F5F9; color: #64748B; padding: 7px 10px;
                border: 1px solid #E2E8F0;
            }
            #contextTabs QTabBar::tab:selected {
                background: #FFFFFF; color: #2563EB; font-weight: 700;
            }
            #evidenceFieldTitle { color: #64748B; font-size: 11px; font-weight: 700; }
            #agentNotice {
                color: #5B21B6; background: #F5F3FF; border: 1px solid #DDD6FE;
                border-radius: 7px; padding: 8px;
            }
            """
        )


__all__ = ["MatchWorkbenchDialog", "describe_symbol_difference"]
