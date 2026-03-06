# -*- coding: utf-8 -*-
"""偵測進度對話框 — 顯示讀條動畫 + 即時 Log。

用於「自動偵測 Level」按下後，以 QDialog(modal) 顯示：
  ┌────────────────────────────────────────┐
  │  🔍 自動偵測 — ISO 載入 + Level 偵測    │
  │                                        │
  │  Phase 2/3：讀取 First_try.csv…        │
  │  ████████████░░░░░░░░░  42%            │
  │                                        │
  │  ─── 偵測紀錄 ───                       │
  │  ═══ Phase 1：載入 ISO 清單 ═══         │
  │    共 23 個工作表                        │
  │    自動選擇工作表：DRAWING LIST          │
  │  ...                                   │
  │                                        │
  │                        [ 取消 ]         │
  └────────────────────────────────────────┘
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from gui.theme import DEFAULT_THEME

_T = DEFAULT_THEME
_G = _T.g
_M = _T.m


class DetectProgressDialog(QDialog):
    """Modal 偵測進度對話框，帶動畫讀條 + Live Log。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自動偵測")
        self.setMinimumSize(520, 420)
        self.setMaximumSize(640, 560)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._cancelled = False
        self._build_ui()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ────────────────────────────────────────
    #  UI 建構
    # ────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── 標題 ──
        title = QLabel("🔍 自動偵測 — ISO 載入 + Level 偵測")
        title.setFont(QFont(_G.font_family, 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_G.text_heading};")
        lay.addWidget(title)

        # ── 階段標籤 ──
        self.lbl_step = QLabel("準備中…")
        self.lbl_step.setStyleSheet(
            f"color: {_G.text_secondary}; font-size: 12px;"
        )
        lay.addWidget(self.lbl_step)

        # ── 進度條 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(self._progress_bar_qss())
        lay.addWidget(self.progress_bar)

        # ── 分隔 ──
        sep_label = QLabel("── 偵測紀錄 ──")
        sep_label.setStyleSheet(
            f"color: {_G.text_muted}; font-size: 11px;"
        )
        sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sep_label)

        # ── Log 區 ──
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont(
            _G.font_mono.split(",")[0].strip().strip('"'), 10
        ))
        self.txt_log.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {_G.bg_input};"
            f"  border: 1px solid {_G.border};"
            f"  border-radius: {_G.radius_sm};"
            f"  color: {_G.text_primary};"
            f"  padding: 8px;"
            f"}}"
        )
        lay.addWidget(self.txt_log, stretch=1)

        # ── 底部按鈕列 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedWidth(90)
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_G.bg_card};"
            f"  border: 1px solid {_G.border};"
            f"  border-radius: {_G.radius_sm};"
            f"  color: {_G.text_secondary};"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {_M.error_bg};"
            f"  color: {_M.error_text};"
            f"  border-color: {_G.danger};"
            f"}}"
        )
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        lay.addLayout(btn_row)

        # ── 脈衝動畫 timer ──
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(35)
        self._pulse_dir = 1
        self._pulse_val = 0
        self._pulse_timer.timeout.connect(self._pulse_tick)

    # ────────────────────────────────────────
    #  Public API（由 host 連接 worker signal）
    # ────────────────────────────────────────

    def on_progress(self, percent: int, label: str):
        """接收 worker 進度。"""
        self.progress_bar.setValue(percent)
        self.lbl_step.setText(label)
        # 進度條完成後停脈衝
        if percent >= 100:
            self._stop_pulse()

    def on_log(self, line: str):
        """接收 worker log。"""
        self.txt_log.append(line)
        # 自動捲到底
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_pulse(self):
        """啟動脈衝動畫（在 worker 啟動前呼叫）。"""
        self._pulse_timer.start()

    def show_result_ok(self, level: int, confidence: float, detail: str):
        """偵測成功 → 切換成結果畫面。"""
        self._stop_pulse()
        self.progress_bar.setValue(100)
        self.lbl_step.setText(
            f"✅ 偵測完成 — Level = {level}，"
            f"信心度 {confidence:.0%}"
        )
        self.lbl_step.setStyleSheet(
            f"color: {_M.success}; font-size: 13px; font-weight: bold;"
        )
        self.btn_cancel.setText("確定")
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_M.primary};"
            f"  border: none;"
            f"  border-radius: {_G.radius_sm};"
            f"  color: #FFFFFF;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {_M.primary_hover};"
            f"}}"
        )
        self.btn_cancel.clicked.disconnect()
        self.btn_cancel.clicked.connect(self.accept)

    def show_result_fail(self, detail: str):
        """偵測失敗 → 顯示錯誤。"""
        self._stop_pulse()
        self.progress_bar.setValue(0)
        self.lbl_step.setText("❌ 偵測失敗")
        self.lbl_step.setStyleSheet(
            f"color: {_G.danger}; font-size: 13px; font-weight: bold;"
        )
        self.txt_log.append(f"\n⚠ {detail}")
        self.btn_cancel.setText("關閉")
        self.btn_cancel.clicked.disconnect()
        self.btn_cancel.clicked.connect(self.reject)

    # ────────────────────────────────────────
    #  內部
    # ────────────────────────────────────────

    def _on_cancel(self):
        self._cancelled = True
        self.reject()

    def _pulse_tick(self):
        """模擬微幅脈衝讓使用者知道系統仍在運作。"""
        cur = self.progress_bar.value()
        # 只在 worker 還沒送真正進度時微幅跳動
        if cur < 2:
            self._pulse_val += self._pulse_dir
            if self._pulse_val >= 3:
                self._pulse_dir = -1
            elif self._pulse_val <= 0:
                self._pulse_dir = 1
            self.progress_bar.setValue(self._pulse_val)

    def _stop_pulse(self):
        if self._pulse_timer.isActive():
            self._pulse_timer.stop()

    def closeEvent(self, event):
        self._cancelled = True
        self._stop_pulse()
        super().closeEvent(event)

    # ────────────────────────────────────────
    #  QSS
    # ────────────────────────────────────────

    @staticmethod
    def _progress_bar_qss() -> str:
        return (
            "QProgressBar {"
            f"  background: {_G.bg_input};"
            f"  border: 1px solid {_G.border};"
            f"  border-radius: 6px;"
            f"  text-align: center;"
            f"  font-size: 11px;"
            f"  font-weight: bold;"
            f"  color: {_G.text_secondary};"
            "}"
            "QProgressBar::chunk {"
            "  border-radius: 5px;"
            f"  background: qlineargradient("
            f"    x1:0, y1:0, x2:1, y2:0,"
            f"    stop:0 {_M.primary}, stop:1 {_M.primary_gradient_end}"
            f"  );"
            "}"
        )
