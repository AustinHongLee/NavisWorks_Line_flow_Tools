# -*- coding: utf-8 -*-
"""Focused recovery UI for 3D ITEM ownership conflicts."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.iconography import app_icon


class OwnershipConflictDialog(QDialog):
    """Explain a rejected change set and expose only valid recovery actions."""

    def __init__(
        self,
        parent=None,
        *,
        conflict_items: list[dict] | None = None,
        attempted_count: int = 0,
        focused_case_count: int = 0,
        safe_selection_count: int = 0,
        recovery_available: bool = False,
    ) -> None:
        super().__init__(parent)
        self.selected_action = ""
        self._conflict_items = [
            dict(item) for item in (conflict_items or []) if isinstance(item, dict)
        ]
        self.setWindowTitle("Ownership 衝突修復")
        self.setModal(True)
        self.resize(820, 620)
        self.setMinimumSize(700, 500)
        self.setStyleSheet(self._style())

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        eyebrow = QLabel("REVIEW BLOCKER · NO DATA WRITTEN")
        eyebrow.setObjectName("eyebrow")
        root.addWidget(eyebrow)
        title = QLabel("同一個 3D ITEM 被兩個 ISO 家族競爭")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "安全鎖已攔下整批。修復不是合併名稱，而是決定哪個 ISO 可以使用這個 ITEM，"
            "另一個 ISO 再改選其他 3D 候選。"
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        metrics.addWidget(self._metric("衝突 ITEM", len(self._conflict_items), "danger"))
        metrics.addWidget(self._metric("相關待判讀 ISO", focused_case_count, "warn"))
        metrics.addWidget(self._metric("原批次判斷", attempted_count, "neutral"))
        if recovery_available:
            metrics.addWidget(self._metric("可先安全提交", safe_selection_count, "ok"))
        metrics.addStretch(1)
        root.addLayout(metrics)

        guide = QFrame()
        guide.setObjectName("guide")
        guide_lay = QVBoxLayout(guide)
        guide_lay.setContentsMargins(12, 10, 12, 10)
        guide_lay.setSpacing(3)
        guide_title = QLabel("建議修復順序")
        guide_title.setObjectName("guideTitle")
        guide_lay.addWidget(guide_title)
        guide_text = QLabel(
            "1. 開啟相關 ISO，只比較這些衝突案例。\n"
            "2. 每個 3D ITEM 只保留一個 ISO owner；競爭端改選其他候選或暫緩。\n"
            "3. 回到 Sidebox 確認 ownership 衝突已不再出現。"
        )
        guide_text.setObjectName("guideText")
        guide_text.setWordWrap(True)
        guide_lay.addWidget(guide_text)
        root.addWidget(guide)

        section = QLabel("衝突明細")
        section.setObjectName("section")
        root.addWidget(section)
        scroll = QScrollArea()
        scroll.setObjectName("conflictScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        cards = QVBoxLayout(content)
        cards.setContentsMargins(0, 0, 4, 0)
        cards.setSpacing(8)
        for index, item in enumerate(self._conflict_items, 1):
            cards.addWidget(self._conflict_card(index, item))
        cards.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        if not recovery_available and safe_selection_count <= 0:
            stale = QLabel(
                "這張事件卡沒有可重播的非衝突批次；因此不顯示無效的「先套用其餘」按鈕。"
            )
            stale.setObjectName("staleNote")
            stale.setWordWrap(True)
            root.addWidget(stale)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        close_button = QPushButton("稍後處理")
        close_button.setObjectName("secondaryButton")
        close_button.setProperty("motion-role", "secondary")
        close_button.clicked.connect(self.reject)
        actions.addWidget(close_button)
        actions.addStretch(1)
        if recovery_available and safe_selection_count > 0:
            safe_button = QPushButton(f"先提交其餘 {safe_selection_count} 筆")
            safe_button.setObjectName("secondaryButton")
            safe_button.setIcon(app_icon("result"))
            safe_button.setIconSize(QSize(17, 17))
            safe_button.setProperty("motion-role", "secondary")
            safe_button.clicked.connect(lambda: self._choose("apply_safe"))
            actions.addWidget(safe_button)
        focus_button = QPushButton(f"開啟 {focused_case_count} 個相關 ISO")
        focus_button.setObjectName("primaryButton")
        focus_button.setIcon(
            app_icon("search", normal="#FFFFFF", active="#FFFFFF")
        )
        focus_button.setIconSize(QSize(17, 17))
        focus_button.setProperty("motion-role", "primary")
        focus_button.setEnabled(focused_case_count > 0)
        focus_button.clicked.connect(lambda: self._choose("focus"))
        actions.addWidget(focus_button)
        root.addLayout(actions)

    def _choose(self, action: str) -> None:
        self.selected_action = action
        self.accept()

    @staticmethod
    def _metric(label: str, value: int, kind: str) -> QFrame:
        card = QFrame()
        card.setObjectName(f"metric_{kind}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(0)
        number = QLabel(f"{int(value):,}")
        number.setObjectName("metricNumber")
        name = QLabel(label)
        name.setObjectName("metricLabel")
        lay.addWidget(number)
        lay.addWidget(name)
        return card

    @staticmethod
    def _conflict_card(index: int, item: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("conflictCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)
        line_3d = str(item.get("line_3d", "")).strip() or "3D ITEM"
        heading = QLabel(f"{index:02d}  ·  {line_3d}")
        heading.setObjectName("itemTitle")
        heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(heading)

        source = str(item.get("source", "")).strip()
        existing_label = "目前已歸屬" if source == "existing_ownership" else "批次選擇 A"
        requested_label = "這次要求" if source == "existing_ownership" else "批次選擇 B"
        owners = QHBoxLayout()
        owners.setSpacing(8)
        owners.addWidget(
            OwnershipConflictDialog._owner_box(
                existing_label,
                str(item.get("existing_family", "")).strip() or "—",
                str(item.get("existing_iso_spool", "")).strip(),
                "existing",
            )
        )
        arrow = QLabel("↔")
        arrow.setObjectName("arrow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        owners.addWidget(arrow)
        owners.addWidget(
            OwnershipConflictDialog._owner_box(
                requested_label,
                str(item.get("requested_family", "")).strip() or "—",
                str(item.get("requested_iso_spool", "")).strip(),
                "requested",
            )
        )
        lay.addLayout(owners)
        return card

    @staticmethod
    def _owner_box(label: str, family: str, spool: str, kind: str) -> QFrame:
        box = QFrame()
        box.setObjectName(f"owner_{kind}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(2)
        caption = QLabel(label + (f" · 流水號 {spool}" if spool else ""))
        caption.setObjectName("ownerCaption")
        value = QLabel(family)
        value.setObjectName("ownerValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(caption)
        lay.addWidget(value)
        return box

    @staticmethod
    def _style() -> str:
        return """
        QDialog { background: #F8FAFC; color: #0F172A; }
        #eyebrow { color:#DC2626; font-size:10px; font-weight:800; }
        #title { color:#0F172A; font-size:20px; font-weight:850; }
        #subtitle { color:#475569; font-size:12px; }
        #metric_danger, #metric_warn, #metric_neutral, #metric_ok {
            border-radius:8px; min-width:105px;
        }
        #metric_danger { background:#FEE2E2; border:1px solid #FECACA; }
        #metric_warn { background:#FEF3C7; border:1px solid #FDE68A; }
        #metric_neutral { background:#E2E8F0; border:1px solid #CBD5E1; }
        #metric_ok { background:#DCFCE7; border:1px solid #BBF7D0; }
        #metricNumber { font-size:17px; font-weight:850; }
        #metricLabel { color:#64748B; font-size:10px; }
        #guide { background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; }
        #guideTitle { color:#1D4ED8; font-weight:800; }
        #guideText { color:#334155; font-size:11px; }
        #section { font-size:12px; font-weight:800; color:#334155; }
        #conflictScroll { background:transparent; }
        #conflictCard { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:9px; }
        #itemTitle { color:#0F172A; font-weight:800; font-size:12px; }
        #owner_existing { background:#F0FDF4; border:1px solid #BBF7D0; border-radius:7px; }
        #owner_requested { background:#FFF7ED; border:1px solid #FED7AA; border-radius:7px; }
        #ownerCaption { color:#64748B; font-size:10px; }
        #ownerValue { color:#0F172A; font-weight:700; font-size:11px; }
        #arrow { color:#DC2626; font-size:18px; font-weight:900; max-width:28px; }
        #staleNote { color:#92400E; background:#FFFBEB; border:1px solid #FDE68A;
                     border-radius:7px; padding:8px; font-size:11px; }
        #primaryButton { color:#FFFFFF; background:#2563EB; border:2px solid transparent;
                         border-radius:7px; padding:7px 12px; font-weight:800; }
        #primaryButton:hover { background:#1D4ED8; }
        #primaryButton:pressed { background:#1E40AF; padding:8px 11px 6px 13px; }
        #primaryButton:focus { border-color:#BFDBFE; }
        #primaryButton:disabled { color:#94A3B8; background:#E2E8F0; }
        #secondaryButton { color:#334155; background:#FFFFFF; border:2px solid #CBD5E1;
                           border-radius:7px; padding:8px 12px; font-weight:700; }
        #secondaryButton:hover { background:#F1F5F9; }
        #secondaryButton:pressed { background:#E2E8F0; padding:9px 11px 7px 13px; }
        #secondaryButton:focus { border-color:#60A5FA; }
        """
