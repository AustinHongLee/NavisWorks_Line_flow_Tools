# -*- coding: utf-8 -*-
"""背景線程：Step1 → Step3 全流程。"""
from __future__ import annotations

import os
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from core.pipeline_extractor import PipelineExtractor
from core.pipeline_grouper import PipelineGrouper
from core.iso_matcher import IsoMatcher
from core.resolved_mapping import build_resolved_mapping


class PipelineWorker(QThread):
    """在背景線程跑 Step1/2/3，不凍結 GUI。"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, params: dict):
        super().__init__()
        self.p = params
        self.fuzzy_unmatched: list[dict] = []

    def _path(self, name: str) -> str:
        return os.path.join(self.p["base_dir"], name)

    def run(self):
        try:
            # ── Step 1 ──
            self.progress_signal.emit(5, "Step1：管線抽取中...")
            self.log_signal.emit("═══ Step1：管線抽取 First_try → 123_minus_1 ═══")
            step1 = PipelineExtractor(
                sep=self.p["sep"],
                raw_prefix=self.p["raw_prefix"],
            )
            scan_mode = self.p.get("scan_mode", "full")
            n1 = step1.build_intermediate(
                self._path(self.p["first_name"]),
                self._path("123_minus_1.csv"),
                filter_key=self.p["filter_key"],
                id_level=self.p["id_level"],
                scan_mode=scan_mode,
                iso_list_path=self.p.get("iso_list_path") or None,
                iso_sheet_name=self.p.get("iso_sheet") or None,
                pipe_col_override=self.p.get("pipe_col") or None,
                write_first_try_trace=bool(self.p.get("write_first_try_trace")),
                write_candidates=bool(self.p.get("write_candidates")),
            )
            self.log_signal.emit(f"  ✓ Step1 完成，輸出 {n1} 筆")
            if self.p.get("write_first_try_trace"):
                self.log_signal.emit(
                    f"  ✓ 已輸出 first_try_trace.csv：{self._path('first_try_trace.csv')}"
                )
            if self.p.get("write_candidates"):
                self.log_signal.emit(
                    "  ✓ 已輸出 candidates.csv（含 ISO 反向召回候選）："
                    f"{self._path('candidates.csv')}"
                )
            self.progress_signal.emit(33, "Step1 完成")

            # ── Step 2 ──
            self.progress_signal.emit(35, "Step2：群組整理中...")
            self.log_signal.emit("═══ Step2：群組整理 → 123_minus_2 ═══")
            step2 = PipelineGrouper(
                sep=self.p["sep"],
                raw_prefix=self.p["raw_prefix"],
            )
            n2d, n2g = step2.parse_and_export(
                self._path("123_minus_1.csv"),
                self._path("123_minus_2.csv"),
                self._path("123_minus_2.xlsx"),
            )
            self.log_signal.emit(f"  ✓ Step2 完成，明細 {n2d} 筆，群組 {n2g} 筆")
            self.progress_signal.emit(66, "Step2 完成")

            # ── Step 3 ──
            self.progress_signal.emit(68, "Step3：ISO 比對中...")
            self.log_signal.emit("═══ Step3：ISO 比對 → iso_match.xlsx ═══")
            matcher = IsoMatcher()
            n3 = matcher.run(
                base_dir=self.p["base_dir"],
                minus_csv_path=self._path("123_minus_2.csv"),
                iso_output_path=self._path("iso_match.xlsx"),
                iso_list_path=self.p["iso_list_path"] or None,
                log_fn=lambda msg: self.log_signal.emit(f"  {msg}"),
                iso_sheet_name=self.p["iso_sheet"] or None,
                pipe_col_override=self.p["pipe_col"] or None,
                spool_col_override=self.p["spool_col"] or None,
                extra_iso_headers=self.p.get("extra_headers", []),
                limit_iso_cols=self.p.get("limit_iso_cols", False),
                first_try_path=self._path(self.p["first_name"]),
            )
            self.fuzzy_unmatched = matcher.fuzzy_unmatched
            fuzzy_count = len(self.fuzzy_unmatched)
            self.log_signal.emit(f"  ✓ Step3 完成，iso_match {n3} 筆")
            if fuzzy_count > 0:
                self.log_signal.emit(
                    f"  ⚠ 尚有 {fuzzy_count} 條 ISO 行未配對，將進入模糊比對…"
                )

            # ── Step 3b ──
            self.progress_signal.emit(92, "Step3b：建立 resolved mapping...")
            self.log_signal.emit("═══ Step3b：建立 JSON-safe resolved_mapping.csv ═══")
            stats = build_resolved_mapping(
                iso_match_path=self._path("iso_match.xlsx"),
                output_path=self._path("resolved_mapping.csv"),
                log_fn=lambda msg: self.log_signal.emit(f"  {msg}"),
            )
            self.log_signal.emit(
                "  ✓ resolved_mapping 完成，"
                f"可匯出 {stats['resolved']} 筆；"
                f"需人工決定 {stats['needs_decision']} 筆"
            )
            self.progress_signal.emit(100, "全部完成！")

            summary = (
                f"全部完成！ Step1={n1} → "
                f"Step2=明細{n2d}/群組{n2g} → "
                f"iso_match={n3} → resolved={stats['resolved']}"
            )
            self.finished_signal.emit(True, summary)

        except Exception as e:
            self.log_signal.emit(f"  ✗ 錯誤：{e}")
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(e))
