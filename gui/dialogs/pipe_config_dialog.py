# -*- coding: utf-8 -*-
"""管線編號拆解設定對話框。"""
from __future__ import annotations

import json
import os

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import C_NOTE


class PipeCodeConfigDialog(QDialog):
    """設定 pipeline_config.json 的 pipe_code_pattern。"""

    ROLE_OPTIONS = ["system", "line_no", "size", "class", "insulation", "ignore"]

    def __init__(
        self, parent, config_path: str, initial_pattern: dict | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle("管線編號拆解設定")
        self.setMinimumSize(700, 400)
        self.resize(780, 460)
        self.setModal(True)

        self.config_path = config_path
        self.initial_pattern = initial_pattern or {}
        self.segment_labels: list[QLabel] = []
        self.segment_role_cbos: list[QComboBox] = []
        self._seg_widgets: list[QWidget] = []

        self._build_ui()
        self._load_from_initial_pattern()

    def _build_ui(self):
        root = QVBoxLayout(self)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("config 檔案："))
        r0.addWidget(QLabel(self.config_path))
        r0.addStretch()
        root.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("sample 管線編號："))
        self.txt_sample = QLineEdit()
        self.txt_sample.setMinimumWidth(240)
        r1.addWidget(self.txt_sample)
        r1.addWidget(QLabel("分隔符："))
        self.txt_sep = QLineEdit("-")
        self.txt_sep.setFixedWidth(60)
        r1.addWidget(self.txt_sep)
        btn_preview = QPushButton("預覽拆解")
        btn_preview.clicked.connect(self._preview_segments)
        r1.addWidget(btn_preview)
        r1.addStretch()
        root.addLayout(r1)

        note = QLabel(
            "說明：此處只負責『整串管線編號』的拆解設定，"
            "實際取得管線編號（如從 Raw_3D_PipeCode 截取）仍由程式負責。\n"
            "常見範例：A-10-DN25-CS → system=A, line_no=10, size=DN25, class=CS。"
        )
        note.setStyleSheet(f"color: {C_NOTE}; font-size: 11px;")
        note.setWordWrap(True)
        root.addWidget(note)

        self.seg_group = QGroupBox("分段與角色設定")
        self.seg_layout = QVBoxLayout(self.seg_group)
        root.addWidget(self.seg_group, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        btn_save = QPushButton("儲存設定")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _load_from_initial_pattern(self):
        if not self.initial_pattern:
            return
        seps = self.initial_pattern.get("separators") or []
        if seps:
            self.txt_sep.setText(str(seps[0]))
        segments = self.initial_pattern.get("segments") or []
        if not segments:
            return
        parts = [f"SEG{i + 1}" for i in range(len(segments))]
        self._render_segments(parts)
        for seg_cfg in segments:
            try:
                idx = int(seg_cfg.get("index", 0))
            except Exception:
                continue
            role = str(seg_cfg.get("role", "") or "").strip()
            if 0 <= idx < len(self.segment_role_cbos) and role in self.ROLE_OPTIONS:
                self.segment_role_cbos[idx].setCurrentText(role)

    def _preview_segments(self):
        code = self.txt_sample.text().strip()
        sep = self.txt_sep.text().strip()
        if not code or not sep:
            QMessageBox.warning(
                self, "提示", "請先輸入 sample 管線編號與分隔符。"
            )
            return
        parts = code.split(sep)
        self._render_segments(parts)

    def _render_segments(self, parts: list[str]):
        for w in self._seg_widgets:
            w.setParent(None)
            w.deleteLater()
        self._seg_widgets.clear()
        self.segment_labels.clear()
        self.segment_role_cbos.clear()

        for i, part in enumerate(parts):
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(4, 2, 4, 2)
            row_l.addWidget(QLabel(f"第 {i + 1} 段："))
            lbl = QLabel(part)
            lbl.setStyleSheet("font-weight: bold;")
            row_l.addWidget(lbl)
            self.segment_labels.append(lbl)
            row_l.addWidget(QLabel("  角色："))
            cbo = QComboBox()
            cbo.addItems(self.ROLE_OPTIONS)
            cbo.setCurrentText("ignore")
            cbo.setFixedWidth(130)
            row_l.addWidget(cbo)
            self.segment_role_cbos.append(cbo)
            row_l.addStretch()
            self.seg_layout.addWidget(row_w)
            self._seg_widgets.append(row_w)

    def _save(self):
        sep = self.txt_sep.text().strip()
        if not sep:
            QMessageBox.warning(self, "提示", "分隔符不可為空。")
            return
        segments_cfg = []
        for idx, cbo in enumerate(self.segment_role_cbos):
            role = cbo.currentText().strip() or "ignore"
            segments_cfg.append({"index": idx, "role": role})

        new_pattern = {"separators": [sep], "segments": segments_cfg}

        cfg = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
            except Exception:
                cfg = {}

        cfg["pipe_code_pattern"] = new_pattern
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "寫入失敗", str(e))
            return

        QMessageBox.information(
            self, "完成",
            f"已儲存管線拆解設定至：\n{self.config_path}",
        )
