# -*- coding: utf-8 -*-
"""Run Inspector side panel.

This panel translates noisy pipeline logs into a small set of operator-facing
signals: where the run is, what looks suspicious, and which samples explain the
matching state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.theme import C_ERROR, C_PRIMARY, C_SUCCESS, C_WARN
from gui.iconography import app_icon


@dataclass
class RunInspectorState:
    run_id: str = "-"
    current_phase: str = "尚未執行"
    current_detail: str = "等待執行流程"
    last_update: str = "-"
    first_try_rows: str = "-"
    step1_scanned: str = "-"
    step1_matched: str = "-"
    iso_rows: str = "-"
    strict_matches: str = "-"
    strip_matches: str = "-"
    drop_last_matches: str = "-"
    fallback_matches: str = "-"
    unmatched_iso: str = "-"
    three_d_keys: str = "-"
    recall_scanned_rows: str = "-"
    recall_candidates: str = "-"
    fuzzy_total: str = "-"
    fuzzy_empty: str = "-"
    resolved_rows: str = "-"
    review_rows: str = "-"
    ownership_conflicts: str = "-"
    display_samples: list[str] = field(default_factory=list)
    pipeline_samples: list[str] = field(default_factory=list)
    three_d_raw_samples: list[str] = field(default_factory=list)
    three_d_norm_samples: list[str] = field(default_factory=list)
    iso_samples: list[str] = field(default_factory=list)
    norm_samples: list[str] = field(default_factory=list)


class RunInspectorPanel(QFrame):
    """Right-side transparent box for pipeline execution."""

    action_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = RunInspectorState()
        self._findings: list[dict] = []
        self._guesses: list[str] = []
        self._structured_events: list[dict] = []
        self._agent_proposals: list[dict] = []
        self._raw_line_count = 0
        self._raw_buffer: list[str] = []
        self.setObjectName("runInspector")
        self.setFixedWidth(330)
        self.setStyleSheet(self._style())

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        title = QLabel("執行透視")
        title.setObjectName("inspectorTitle")
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.addTab(self._build_focus_tab(), "Live")
        self.tabs.addTab(self._build_match_tab(), "Evidence")
        self.tabs.addTab(self._build_agent_tab(), "Agent")
        self.tabs.addTab(self._build_log_tab(), "Log")
        root.addWidget(self.tabs, stretch=1)

        # Logs/events can arrive in bursts.  Coalesce them so the GUI thread
        # repaints at a human-visible cadence instead of rebuilding every card
        # for every line.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render_now)
        self._raw_flush_timer = QTimer(self)
        self._raw_flush_timer.setSingleShot(True)
        self._raw_flush_timer.setInterval(180)
        self._raw_flush_timer.timeout.connect(self._flush_raw_buffer)

        self.reset()

    def reset(self, clear_raw: bool = True) -> None:
        self.state = RunInspectorState(
            current_phase="準備中",
            current_detail="等待 Step1 開始",
            last_update=self._now(),
        )
        self._findings = [
            {"tag": "INFO", "body": "流程已啟動，等待第一批診斷訊息。"}
        ]
        self._guesses = []
        self._structured_events = []
        self._agent_proposals = []
        if clear_raw:
            self._raw_buffer = []
            self._raw_flush_timer.stop()
            self.raw_log.clear()
            self._raw_line_count = 0
            self.raw_count_label.setText("0 行")
        self._render(immediate=True)

    def append_raw(self, msg: str) -> None:
        self._raw_buffer.append(str(msg))
        self._raw_line_count += 1
        self.raw_count_label.setText(f"{self._raw_line_count:,} 行")
        if not self._raw_flush_timer.isActive():
            self._raw_flush_timer.start()

    def _flush_raw_buffer(self) -> None:
        if not self._raw_buffer:
            return
        text = "\n".join(self._raw_buffer)
        self._raw_buffer = []
        self.raw_log.appendPlainText(text)
        sb = self.raw_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def ingest(self, msg: str) -> None:
        text = str(msg).strip()
        if not text:
            return
        self.state.last_update = self._now()
        self._parse_message(text)
        self._render()

    def ingest_event(self, event: dict) -> None:
        """Consume a structured Run Capsule event.

        Human-readable log parsing remains as a backwards-compatible fallback,
        but the workbench can now render stable event fields directly.
        """

        if not isinstance(event, dict):
            return
        self._structured_events.append(dict(event))
        del self._structured_events[:-200]
        self.state.last_update = self._now()
        run_id = str(event.get("run_id", "")).strip()
        if run_id:
            self.state.run_id = run_id

        event_type = str(
            event.get("event_type") or event.get("type") or ""
        ).strip()
        stage = str(event.get("stage", "")).strip()
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"value": payload}

        if event_type == "run.started":
            self.state.current_phase = "Preflight / 執行膠囊已建立"
            self.state.current_detail = "輸入指紋、設定與事件帳本已凍結"
        elif event_type == "stage.started":
            self.state.current_phase = self._stage_title(stage)
            self.state.current_detail = str(
                payload.get("message") or payload.get("detail") or "階段執行中"
            )
        elif event_type == "stage.completed":
            self.state.current_phase = self._stage_title(stage)
            self.state.current_detail = "階段完成；證據與產物已登記"
        elif event_type == "run.completed":
            self.state.current_phase = "Review / 等待確認"
            self.state.current_detail = "本次 Run 已完成，待確認項目不會自動提交"
            self._add_finding("OK", "Run Capsule 已完成並可供稽核。")
        elif event_type == "run.failed":
            self.state.current_phase = "Failed / 執行失敗"
            self.state.current_detail = str(payload.get("error") or "請查看 Log")
            self._add_finding("ERROR", self.state.current_detail[:90])
        elif event_type == "metric.recorded":
            self._ingest_metric(payload)
        elif event_type == "anomaly.detected":
            message = str(payload.get("message") or payload.get("reason") or stage)
            self._add_finding("WARN", message[:100] or "偵測到資料異常")
        elif event_type == "review.requested":
            message = str(payload.get("message") or payload.get("reason") or event_type)
            self._add_finding(
                "WARN",
                message[:100],
                action_label="前往判讀",
                action={
                    "action": "continue_review",
                    "run_id": run_id,
                    "event_id": event.get("event_id", ""),
                },
            )
        elif event_type == "ownership.conflict":
            conflicts = payload.get("conflict_items") or payload.get("conflicts") or []
            count = len(conflicts) if isinstance(conflicts, list) else 1
            item_ids = sorted(
                str(item.get("item_id", "")).strip()
                for item in payload.get("conflict_items", [])
                if isinstance(item, dict) and str(item.get("item_id", "")).strip()
            )
            self.state.ownership_conflicts = self._fmt_int(str(count))
            self._add_finding(
                "ERROR",
                (
                    f"{count} 個 3D ITEM 被指向不同 ISO 家族；"
                    "本批次尚未寫入。"
                ),
                action_label=f"修正這 {count} 個衝突",
                action={
                    "action": "ownership_conflict_guide",
                    "run_id": run_id,
                    "event_id": event.get("event_id", ""),
                    "conflicts": payload.get("conflicts", []),
                    "conflict_items": payload.get("conflict_items", []),
                    "attempted_count": payload.get("attempted_count", 0),
                    "safe_count": payload.get("safe_count", 0),
                    "recovery_selections": payload.get("recovery_selections", []),
                    "pending_rules": payload.get("pending_rules", []),
                },
                group_key="ownership:" + "|".join(item_ids),
            )
        elif event_type == "decision.proposed":
            proposal = dict(payload)
            proposal.setdefault("proposal_id", event.get("subject_id", ""))
            self._agent_proposals.append(proposal)
            del self._agent_proposals[:-20]
        elif event_type == "decision.applied":
            applied = self._fmt_int(str(payload.get("selection_count", 0)))
            remaining = payload.get("remaining_review_cases")
            resolved = payload.get("resolved_rows")
            if remaining is not None:
                self.state.unmatched_iso = self._fmt_int(str(remaining))
            if resolved is not None:
                self.state.resolved_rows = self._fmt_int(str(resolved))
            self.state.current_phase = "Review / 人工判讀進行中"
            self.state.current_detail = (
                f"已套用 {applied} 筆；"
                f"尚待確認 {self._state_text(self.state.unmatched_iso)} 筆"
            )

        self._render(
            immediate=event_type in {"run.completed", "run.failed"}
        )

    # ─────────────────────────────────────────────────────
    # UI build
    # ─────────────────────────────────────────────────────

    def _build_focus_tab(self) -> QWidget:
        content, tab = self._scroll_tab()
        layout = content.layout()

        self.lbl_phase = QLabel()
        self.lbl_phase.setObjectName("phaseLabel")
        self.lbl_phase.setWordWrap(True)
        layout.addWidget(self.lbl_phase)

        self.lbl_update = QLabel()
        self.lbl_update.setObjectName("muted")
        layout.addWidget(self.lbl_update)

        layout.addWidget(self._section_label("重點標記"))
        self.findings_box = QVBoxLayout()
        self.findings_box.setSpacing(6)
        layout.addLayout(self.findings_box)

        layout.addWidget(self._section_label("這次資料流到哪裡？"))
        self.funnel_box = QVBoxLayout()
        self.funnel_box.setSpacing(7)
        layout.addLayout(self.funnel_box)

        layout.addWidget(self._section_label("自動配對路徑"))
        self.route_box = QGridLayout()
        self.route_box.setHorizontalSpacing(6)
        self.route_box.setVerticalSpacing(6)
        layout.addLayout(self.route_box)

        layout.addWidget(self._section_label("猜測 / 下一步"))
        self.guess_box = QLabel()
        self.guess_box.setWordWrap(True)
        self.guess_box.setObjectName("guessBox")
        layout.addWidget(self.guess_box)
        layout.addStretch()
        return tab

    def _build_match_tab(self) -> QWidget:
        content, tab = self._scroll_tab()
        layout = content.layout()

        layout.addWidget(self._section_label("一眼判斷"))
        self.match_shape = QLabel()
        self.match_shape.setObjectName("diagnosisCard")
        self.match_shape.setWordWrap(True)
        layout.addWidget(self.match_shape)

        self.three_d_sample_box = self._sample_block(
            layout,
            "3D 端拿來找身份",
        )
        self.iso_sample_box = self._sample_block(
            layout,
            "ISO 端目前拿來比對",
        )

        layout.addStretch()
        return tab

    def _build_agent_tab(self) -> QWidget:
        content, tab = self._scroll_tab()
        layout = content.layout()

        boundary = QLabel(
            "Agent 可讀取本次 Run 的結構化證據並提出 Proposal；"
            "不能直接改 mapping、建立歸屬鎖或核准自己的提案。"
        )
        boundary.setWordWrap(True)
        boundary.setObjectName("agentBoundary")
        layout.addWidget(boundary)

        self.agent_status = QLabel("目前沒有 Agent 提案")
        self.agent_status.setObjectName("muted")
        layout.addWidget(self.agent_status)

        self.proposal_box = QVBoxLayout()
        self.proposal_box.setSpacing(7)
        layout.addLayout(self.proposal_box)
        layout.addStretch()
        return tab

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel("完整流水紀錄")
        title.setObjectName("sectionLabel")
        self.raw_count_label = QLabel("0 行")
        self.raw_count_label.setObjectName("muted")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.raw_count_label)
        lay.addLayout(header)
        self.raw_log = QPlainTextEdit()
        self.raw_log.setReadOnly(True)
        self.raw_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw_log.document().setMaximumBlockCount(2000)
        self.raw_log.setObjectName("rawLog")
        lay.addWidget(self.raw_log)
        return tab

    def _scroll_tab(self) -> tuple[QWidget, QWidget]:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return content, scroll

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _sample_block(self, layout: QVBoxLayout, title: str) -> QLabel:
        layout.addWidget(self._section_label(title))
        label = QLabel("尚未取得樣本")
        label.setObjectName("sampleBox")
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    # ─────────────────────────────────────────────────────
    # Log parsing
    # ─────────────────────────────────────────────────────

    def _parse_message(self, text: str) -> None:
        if "Step1：管線抽取" in text:
            self.state.current_phase = "Step1 / 3D 身份抽取"
            self.state.current_detail = "讀取 First_try 並辨識管線身份"
            self._add_finding("INFO", "開始抽取 3D 管線身份。")
        elif "Step2：群組整理" in text:
            self.state.current_phase = "Step2 / 群組整理"
            self.state.current_detail = "整理 Step1 產出的 3D 管線"
        elif "Step3：ISO 比對" in text:
            self.state.current_phase = "Step3 / ISO 比對"
            self.state.current_detail = "用 ISO 清單與 3D key 做多路配對"
        elif "Phase4:" in text:
            self.state.current_phase = "Step3 / Phase4 補救召回"
            self.state.current_detail = "正常配對不足，正在建立模糊候選"

        self._parse_numbers(text)
        self._parse_samples(text)
        self._derive_findings(text)

    def _ingest_metric(self, payload: dict) -> None:
        name = str(payload.get("name") or payload.get("metric") or "").strip()
        value = payload.get("value", "")
        field_map = {
            "input.first_try_rows": "first_try_rows",
            "extract.scanned_rows": "step1_scanned",
            "extract.matched_items": "step1_matched",
            "iso.rows": "iso_rows",
            "match.strict_rows": "strict_matches",
            "match.strip_size_rows": "strip_matches",
            "match.drop_last_rows": "drop_last_matches",
            "match.fallback_rows": "fallback_matches",
            "match.unmatched_iso": "unmatched_iso",
            "recall.scanned_rows": "recall_scanned_rows",
            "recall.candidates": "recall_candidates",
            "mapping.resolved_rows": "resolved_rows",
            "mapping.review_rows": "review_rows",
            "mapping.ownership_conflicts": "ownership_conflicts",
        }
        field_name = field_map.get(name)
        if field_name:
            setattr(self.state, field_name, self._fmt_int(str(value)))
        if name == "mapping.ownership_conflicts" and self._as_int(value) > 0:
            self._add_finding(
                "ERROR",
                f"單一歸屬鎖阻擋 {self._fmt_int(str(value))} 個 mapping 列。",
            )

    @staticmethod
    def _stage_title(stage: str) -> str:
        labels = {
            "extract": "Extract / 3D 身份抽取",
            "group": "Group / 群組整理",
            "match": "Match / ISO 配對",
            "match.recall": "Recall / 候選召回",
            "mapping": "Resolve / 單一歸屬與輸出閘門",
            "review": "Review / 人工工作檯",
        }
        return labels.get(stage, stage or "Run / 資料運轉")

    def _parse_numbers(self, text: str) -> None:
        patterns = [
            (r"First_try 讀取完成：rows=(\d+)", "first_try_rows"),
            (r"(?:full|level|filter_key) 掃描結果：掃描 (\d+) 列", "step1_scanned"),
            (r"(?:full|level|filter_key) 掃描結果：掃描 \d+ 列，抓到 (\d+) 列", "step1_matched"),
            (r"身份解析進度：已處理 (\d+)/(\d+) 列", "step1_progress"),
            (r"iso_df rows = (\d+)", "iso_rows"),
            (r"Phase1 strict merged rows = (\d+)", "strict_matches"),
            (r"Phase2 strip-size matched rows = (\d+)", "strip_matches"),
            (r"Phase2b drop-last matched rows = (\d+)", "drop_last_matches"),
            (r"Phase3 fallback base match rows = (\d+)", "fallback_matches"),
            (r"Phase4: 尚未配對的 ISO 行 = (\d+)", "unmatched_iso"),
            (r"Phase4: 可用 3D line_norm 數 = (\d+)", "three_d_keys"),
            (r"已掃 (\d+) 列，候選 (\d+) 筆", "recall_progress"),
            (r"First_try 反向召回完成：掃描 (\d+) 列，候選 (\d+) 筆", "recall_done"),
            (r"Phase4: 模糊比對清單完成：(\d+) 條，其中 (\d+) 條沒有任何候選", "fuzzy_done"),
        ]
        for pattern, key in patterns:
            m = re.search(pattern, text)
            if not m:
                continue
            if key == "recall_progress" or key == "recall_done":
                self.state.recall_scanned_rows = self._fmt_int(m.group(1))
                self.state.recall_candidates = self._fmt_int(m.group(2))
            elif key == "step1_progress":
                self.state.step1_scanned = self._fmt_int(m.group(1))
                if not self._is_known(self.state.first_try_rows):
                    self.state.first_try_rows = self._fmt_int(m.group(2))
            elif key == "fuzzy_done":
                self.state.fuzzy_total = self._fmt_int(m.group(1))
                self.state.fuzzy_empty = self._fmt_int(m.group(2))
            else:
                setattr(self.state, key, self._fmt_int(m.group(1)))

    def _parse_samples(self, text: str) -> None:
        sample_patterns = [
            (r"DisplayName sample：(\[.*\])", "display_samples"),
            (r"PipelineId sample：(\[.*\])", "pipeline_samples"),
            (r"ISO_Match_Key sample \(前 5 筆標準化前\): (.*)", "three_d_raw_samples"),
            (r"^line_norm sample \(前 5 筆\): (.*)", "three_d_norm_samples"),
            (r"iso pipe_raw sample \(前 5 筆\): (.*)", "iso_samples"),
            (r"iso line_norm sample \(前 5 筆\): (.*)", "norm_samples"),
        ]
        for pattern, key in sample_patterns:
            m = re.search(pattern, text)
            if not m:
                continue
            setattr(self.state, key, self._split_sample(m.group(1)))

    def _derive_findings(self, text: str) -> None:
        if "本次沒有抓到任何 3D 管線身份" in text:
            self._add_finding("WARN", "Step1 抓到 0 筆 3D 管線身份。")
            self._add_guess("Step1 沒有 3D key，Step3 會進補救掃描；優先檢查 PipelineId / Level / ISO 欄位。")
        if "minus 檔沒有可用 3D key" in text:
            self._add_finding("WARN", "Step3 沒有 3D key 可比對。")
            self._add_guess("目前不是單純 ISO 沒配到，而是 3D 端輸入為空。")
        if "ISO 白名單載入失敗" in text:
            self._add_finding("WARN", "ISO 白名單載入失敗，Step1 只靠 3D 規則辨識。")
        if "讀取失敗" in text or "錯誤" in text or "失敗" in text:
            if (
                "載入失敗，改用" not in text
                and "略過" not in text
                and "單一歸屬鎖阻擋" not in text
            ):
                self._add_finding("ERROR", text[:90])
        if "First_try 反向召回進度" in text:
            self._add_finding("INFO", "First_try 反向召回仍在掃描中。")
        if self.state.iso_samples and self.state.display_samples:
            self._derive_match_guess()

    def _derive_match_guess(self) -> None:
        iso = " ".join(self.state.iso_samples[:3]).lower()
        d3_values = (
            self.state.three_d_norm_samples
            or self.state.three_d_raw_samples
            or self.state.display_samples
        )
        d3 = " ".join(d3_values[:3]).lower()
        if any(mark in iso for mark in [".pdf", ".xlsx", ".dwg"]):
            self._add_guess("ISO 管線欄位 sample 像檔名，可能選錯欄位。")
        if re.search(r"-\d{3}\b", iso) and not re.search(r"-\d{3}\b", d3):
            self._add_guess("ISO sample 可能多了流水號尾段，3D sample 不一定有同一尾段。")

    # ─────────────────────────────────────────────────────
    # Render helpers
    # ─────────────────────────────────────────────────────

    def _render(self, *, immediate: bool = False) -> None:
        if immediate:
            self._render_timer.stop()
            self._render_now()
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _render_now(self) -> None:
        self.lbl_phase.setText(
            f"● {self.state.current_phase}\n{self.state.current_detail}"
            + (
                f"\nRun：{self.state.run_id}"
                if self.state.run_id not in {"", "-"}
                else ""
            )
        )
        self.lbl_update.setText(f"最後更新：{self.state.last_update}")
        self._render_findings()
        self._render_funnel()
        self._render_routes()
        self._render_guesses()
        self._render_samples()
        self._render_agent()

    def _render_findings(self) -> None:
        while self.findings_box.count():
            item = self.findings_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for finding in self._findings[-6:]:
            tag = str(finding.get("tag", "INFO"))
            body = str(finding.get("body", ""))
            card = QFrame()
            card.setObjectName(f"tag{tag}")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(8, 7, 8, 7)
            card_lay.setSpacing(6)
            label = QLabel(f"{tag}  {body}")
            label.setWordWrap(True)
            label.setObjectName("findingText")
            card_lay.addWidget(label)
            action = finding.get("action")
            if isinstance(action, dict) and action:
                button = QPushButton(str(finding.get("action_label") or "處理"))
                button.setObjectName("findingAction")
                button.setIcon(
                    app_icon(
                        "arrow-right",
                        normal="#FFFFFF",
                        active="#FFFFFF",
                    )
                )
                button.setIconSize(QSize(16, 16))
                button.setProperty("motion-role", "primary")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, payload=dict(action):
                    self.action_requested.emit(payload)
                )
                card_lay.addWidget(button)
            self.findings_box.addWidget(card)

    def _render_funnel(self) -> None:
        self._clear_layout(self.funnel_box)

        first_try = self._as_int(self.state.first_try_rows)
        scanned = self._as_int(self.state.step1_scanned)
        step1 = self._as_int(self.state.step1_matched)
        iso_rows = self._as_int(self.state.iso_rows)
        matched_auto = self._auto_match_total()
        unmatched = self._as_int(self.state.unmatched_iso)
        recall_candidates = self._as_int(self.state.recall_candidates)
        recall_scanned = self._as_int(self.state.recall_scanned_rows)

        self.funnel_box.addWidget(
            self._flow_card(
                "輸入資料",
                self._state_text(self.state.first_try_rows),
                "C# 匯出的 First_try item 列數",
                "neutral",
            )
        )
        rate = self._percent_text(step1, scanned)
        step_kind = "error" if step1 == 0 and scanned > 0 else "ok" if step1 > 0 else "neutral"
        self.funnel_box.addWidget(
            self._flow_card(
                "3D 身份抽取",
                self._state_text(self.state.step1_matched),
                f"從 {self._state_text(self.state.step1_scanned)} 列中抓到可比對管線；抓到率 {rate}",
                step_kind,
            )
        )
        self.funnel_box.addWidget(
            self._flow_card(
                "ISO 清單",
                self._state_text(self.state.iso_rows),
                "目前工作表中參與比對的 ISO 列數",
                "neutral",
            )
        )
        match_kind = "ok" if matched_auto > 0 else "warn" if iso_rows > 0 else "neutral"
        route_known = any(
            self._is_known(v)
            for v in [
                self.state.strict_matches,
                self.state.strip_matches,
                self.state.drop_last_matches,
                self.state.fallback_matches,
            ]
        )
        auto_sub = "strict / 去尺寸 / 去末段 / fallback 命中的結果列數"
        if matched_auto > iso_rows > 0:
            auto_sub = "結果列數；同一 ISO 可能對到多個 3D 範圍，所以會大於 ISO 列數"
        self.funnel_box.addWidget(
            self._flow_card(
                "自動配對",
                self._computed_text(matched_auto, route_known),
                auto_sub,
                match_kind,
            )
        )
        unmatched_kind = "warn" if unmatched > 0 else "ok" if iso_rows > 0 else "neutral"
        unmatched_sub = "沒有被自動配對的 ISO，會進入反向召回或 fuzzy"
        if iso_rows > 0 and self._is_known(self.state.unmatched_iso):
            unmatched_sub = (
                f"ISO 未配對率 {self._percent_text(unmatched, iso_rows)}，"
                "會進入反向召回或 fuzzy"
            )
        self.funnel_box.addWidget(
            self._flow_card(
                "待補救或人工確認",
                self._state_text(self.state.unmatched_iso),
                unmatched_sub,
                unmatched_kind,
            )
        )
        recall_sub = (
            f"已掃 First_try {self._state_text(self.state.recall_scanned_rows)} 列"
            if recall_scanned > 0
            else "尚未進入 First_try 反向掃描"
        )
        self.funnel_box.addWidget(
            self._flow_card(
                "反向召回候選",
                self._state_text(self.state.recall_candidates),
                recall_sub,
                "warn" if recall_candidates > 0 else "neutral",
            )
        )
        if any(
            self._is_known(value)
            for value in (
                self.state.resolved_rows,
                self.state.review_rows,
                self.state.ownership_conflicts,
            )
        ):
            review_count = self._as_int(self.state.review_rows)
            conflict_count = self._as_int(self.state.ownership_conflicts)
            self.funnel_box.addWidget(
                self._flow_card(
                    "輸出閘門",
                    self._state_text(self.state.resolved_rows),
                    "單位：可匯出 mapping 列；"
                    f"待人工 {self._state_text(self.state.review_rows)}，"
                    f"歸屬衝突 {self._state_text(self.state.ownership_conflicts)}",
                    "error" if conflict_count else "warn" if review_count else "ok",
                )
            )

    def _render_routes(self) -> None:
        self._clear_layout(self.route_box)
        routes = [
            ("strict", self.state.strict_matches),
            ("strip", self.state.strip_matches),
            ("drop", self.state.drop_last_matches),
            ("fallback", self.state.fallback_matches),
        ]
        for idx, (label, value) in enumerate(routes):
            chip = QLabel(f"{label}\n{value}")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setObjectName("routeChip")
            chip.setProperty("active", self._as_int(value) > 0)
            self.route_box.addWidget(chip, idx // 2, idx % 2)

    def _render_guesses(self) -> None:
        if self._guesses:
            self.guess_box.setText("\n".join(f"猜測  {g}" for g in self._guesses[-4:]))
        else:
            self.guess_box.setText("目前沒有明顯異常猜測。")

    def _render_samples(self) -> None:
        self.three_d_sample_box.setText(
            "DisplayName\n"
            + self._format_samples(self.state.display_samples)
            + "\n\nPipelineId\n"
            + self._format_samples(self.state.pipeline_samples)
            + "\n\n3D 比對 key\n"
            + self._format_samples(self.state.three_d_raw_samples)
            + "\n\n3D normalize 後\n"
            + self._format_samples(self.state.three_d_norm_samples)
        )
        self.iso_sample_box.setText(
            "原始欄位值\n"
            + self._format_samples(self.state.iso_samples)
            + "\n\nnormalize 後\n"
            + self._format_samples(self.state.norm_samples)
        )
        self.match_shape.setText(
            self._match_diagnosis_text()
        )

    def _render_agent(self) -> None:
        if not hasattr(self, "proposal_box"):
            return
        self._clear_layout(self.proposal_box)
        if not self._agent_proposals:
            self.agent_status.setText(
                f"Run {self.state.run_id}｜目前沒有 Agent Proposal"
            )
            empty = QLabel(
                "Agent context 由 Run Capsule 產生；沒有提案時，資料仍保持唯讀。"
            )
            empty.setWordWrap(True)
            empty.setObjectName("sampleBox")
            self.proposal_box.addWidget(empty)
            return

        self.agent_status.setText(
            f"Run {self.state.run_id}｜{len(self._agent_proposals)} 個待審提案"
        )
        for proposal in reversed(self._agent_proposals[-8:]):
            action = str(proposal.get("action") or "分析建議")
            impact = proposal.get("expected_impact", {})
            if not isinstance(impact, dict):
                impact = {}
            risk_flags = proposal.get("risk_flags", [])
            if not isinstance(risk_flags, list):
                risk_flags = [str(risk_flags)]
            body = [action]
            if impact:
                body.append(
                    "影響：" + "、".join(f"{k}={v}" for k, v in impact.items())
                )
            if risk_flags:
                body.append("風險：" + "、".join(str(v) for v in risk_flags))
            body.append("狀態：只讀提案，需人工預覽與核准")
            label = QLabel("\n".join(body))
            label.setWordWrap(True)
            label.setObjectName("agentProposal")
            self.proposal_box.addWidget(label)

    @staticmethod
    def _format_samples(values: list[str]) -> str:
        if not values:
            return "尚未取得樣本"
        return "\n".join(f"- {v}" for v in values[:5])

    def _flow_card(
        self,
        title: str,
        value: str,
        subtitle: str,
        kind: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("flowCard")
        card.setProperty("kind", kind)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(8, 7, 8, 7)
        lay.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("flowTitle")
        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setObjectName("flowSub")
        text_col.addWidget(title_lbl)
        text_col.addWidget(subtitle_lbl)
        lay.addLayout(text_col, stretch=1)

        value_lbl = QLabel(value)
        value_lbl.setObjectName("flowValue")
        value_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        lay.addWidget(value_lbl)
        return card

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                RunInspectorPanel._clear_layout(child_layout)

    def _auto_match_total(self) -> int:
        return sum(
            self._as_int(v)
            for v in [
                self.state.strict_matches,
                self.state.strip_matches,
                self.state.drop_last_matches,
                self.state.fallback_matches,
            ]
        )

    @staticmethod
    def _as_int(value: object) -> int:
        text = str(value).strip().replace(",", "")
        if not text or text == "-":
            return 0
        try:
            return int(float(text))
        except ValueError:
            return 0

    @staticmethod
    def _state_text(value: object) -> str:
        text = str(value).strip()
        return text if text else "-"

    @staticmethod
    def _computed_text(value: int, known: bool) -> str:
        return f"{value:,}" if known else "-"

    @staticmethod
    def _is_known(value: object) -> bool:
        return str(value).strip() not in {"", "-"}

    @staticmethod
    def _percent_text(part: int, total: int) -> str:
        if total <= 0:
            return "-"
        return f"{(part / total) * 100:.1f}%"

    def _match_diagnosis_text(self) -> str:
        three_d = self._as_int(self.state.three_d_keys)
        unmatched = self._as_int(self.state.unmatched_iso)
        auto = self._auto_match_total()
        lines: list[str] = []
        if three_d == 0 and unmatched > 0:
            lines.append("3D 端沒有形成可比對 key，ISO 會全部掉進補救流程。")
        elif auto == 0 and unmatched > 0:
            lines.append("目前自動配對路徑都是 0，優先看欄位或格式是否拿錯。")
        elif unmatched > 0:
            lines.append("已有自動配對，但仍有 ISO 需要補救或人工確認。")
        elif auto > 0:
            lines.append("自動配對已有命中，主要比對形狀看起來可用。")
        else:
            lines.append("等待 Step3 樣本與配對統計。")

        if self._guesses:
            lines.append("")
            lines.extend(f"猜測：{g}" for g in self._guesses[-2:])
        return "\n".join(lines)

    @staticmethod
    def _split_sample(text: str) -> list[str]:
        text = text.strip()
        if text.startswith("[") and text.endswith("]"):
            items = re.findall(r"'([^']*)'|\"([^\"]*)\"", text)
            result = [(a or b).strip() for a, b in items if (a or b).strip()]
            if result:
                return result[:5]
        return [part.strip() for part in text.split(",") if part.strip()][:5]

    def _add_finding(
        self,
        tag: str,
        body: str,
        *,
        action_label: str = "",
        action: dict | None = None,
        group_key: str = "",
    ) -> None:
        item = {
            "tag": tag,
            "body": body,
            "action_label": action_label,
            "action": dict(action or {}),
            "group_key": group_key,
        }
        if group_key:
            self._findings = [
                existing
                for existing in self._findings
                if existing.get("group_key") != group_key
            ]
        key = (tag, body, str(item["action"].get("event_id", "")))
        if not any(
            (
                existing.get("tag"),
                existing.get("body"),
                str(existing.get("action", {}).get("event_id", "")),
            ) == key
            for existing in self._findings
        ):
            self._findings.append(item)
        del self._findings[:-12]

    def _add_guess(self, body: str) -> None:
        if body not in self._guesses:
            self._guesses.append(body)
        del self._guesses[:-8]

    @staticmethod
    def _fmt_int(value: str) -> str:
        try:
            return f"{int(value):,}"
        except ValueError:
            return value

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _style() -> str:
        return f"""
        #runInspector {{
            background: #F8FAFC;
            border-left: 1px solid #CBD5E1;
        }}
        #inspectorTitle {{
            color: #0F172A;
            font-size: 15px;
            font-weight: 800;
        }}
        #inspectorTabs::pane {{
            border: 1px solid #E2E8F0;
            background: #FFFFFF;
            border-radius: 8px;
        }}
        #inspectorTabs QTabBar::tab {{
            background: #F1F5F9;
            color: #475569;
            border: 1px solid #E2E8F0;
            padding: 6px 9px;
            font-size: 12px;
        }}
        #inspectorTabs QTabBar::tab:selected {{
            background: #FFFFFF;
            color: {C_PRIMARY};
            font-weight: 700;
        }}
        #phaseLabel {{
            color: #0F172A;
            font-size: 13px;
            font-weight: 700;
            padding: 8px;
            border: 1px solid #BFDBFE;
            border-radius: 8px;
            background: #EFF6FF;
        }}
        #muted {{
            color: #64748B;
            font-size: 11px;
        }}
        #sectionLabel {{
            color: #334155;
            font-size: 12px;
            font-weight: 800;
            padding-top: 4px;
        }}
        #flowCard {{
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
        }}
        #flowCard[kind="ok"] {{
            background: #F0FDF4;
            border-color: #BBF7D0;
        }}
        #flowCard[kind="warn"] {{
            background: #FFFBEB;
            border-color: #FDE68A;
        }}
        #flowCard[kind="error"] {{
            background: #FEF2F2;
            border-color: #FECACA;
        }}
        #flowTitle {{
            color: #1E293B;
            font-size: 11px;
            font-weight: 800;
        }}
        #flowSub {{
            color: #64748B;
            font-size: 10px;
        }}
        #flowValue {{
            color: #0F172A;
            font-size: 14px;
            font-weight: 900;
            min-width: 74px;
        }}
        #routeChip {{
            color: #64748B;
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 6px;
            font-size: 11px;
            font-weight: 700;
        }}
        #routeChip[active="true"] {{
            color: #1D4ED8;
            background: #EFF6FF;
            border-color: #BFDBFE;
        }}
        #metricName {{
            color: #64748B;
            font-size: 11px;
        }}
        #metricValue {{
            color: #0F172A;
            font-size: 12px;
            font-weight: 700;
        }}
        #guessBox, #sampleBox, #diagnosisCard {{
            color: #1E293B;
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 8px;
            font-size: 11px;
            line-height: 1.45;
        }}
        #diagnosisCard {{
            background: #F8FAFC;
            border-color: #CBD5E1;
            font-weight: 650;
        }}
        #agentBoundary {{
            color: #1E3A8A;
            background: #EFF6FF;
            border: 1px solid #BFDBFE;
            border-radius: 8px;
            padding: 9px;
            font-size: 11px;
            font-weight: 650;
        }}
        #agentProposal {{
            color: #1E293B;
            background: #FFFBEB;
            border: 1px solid #FDE68A;
            border-radius: 8px;
            padding: 9px;
            font-size: 11px;
        }}
        #tagINFO, #tagOK, #tagWARN, #tagERROR {{
            border-radius: 7px;
            font-size: 11px;
            font-weight: 650;
        }}
        #findingText {{
            background: transparent;
            border: none;
        }}
        #findingAction {{
            color: #FFFFFF;
            background: #2563EB;
            border: 2px solid transparent;
            border-radius: 6px;
            padding: 4px 7px;
            font-size: 11px;
            font-weight: 750;
            text-align: left;
        }}
        #findingAction:hover {{ background: #1D4ED8; }}
        #findingAction:pressed {{
            background: #1E40AF; padding: 5px 6px 3px 8px;
        }}
        #findingAction:focus {{ border-color: #BFDBFE; }}
        #tagINFO {{
            color: #1D4ED8;
            background: #EFF6FF;
            border: 1px solid #BFDBFE;
        }}
        #tagOK {{
            color: {C_SUCCESS};
            background: #DCFCE7;
            border: 1px solid #BBF7D0;
        }}
        #tagWARN {{
            color: {C_WARN};
            background: #FFFBEB;
            border: 1px solid #FDE68A;
        }}
        #tagERROR {{
            color: {C_ERROR};
            background: #FEE2E2;
            border: 1px solid #FECACA;
        }}
        #rawLog {{
            font-family: Consolas, "Cascadia Mono", monospace;
            font-size: 11px;
            color: #E2E8F0;
            background: #0F172A;
            border: 1px solid #1E293B;
            border-radius: 8px;
            padding: 8px;
        }}
        """
