# -*- coding: utf-8 -*-
"""背景線程：自動偵測 ISO 載入 + Level 偵測。

分為 3 階段發送進度，讓 GUI 可即時更新讀條：
  Phase 1 (0-30%)  — 讀取 ISO 清單、選擇工作表、偵測欄位
  Phase 2 (30-60%) — 讀取 First_try.csv
  Phase 3 (60-100%)— 探針比對 + 統計
"""
from __future__ import annotations

import os
import traceback
from typing import Optional

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from utils.iso_schema import detect_pipe_col, detect_spool_col, pick_best_sheet


class LevelDetectWorker(QThread):
    """在背景線程跑 ISO 載入 + Level 偵測。"""

    # (percent 0-100, step_label)
    progress = pyqtSignal(int, str)
    # (log_line)
    log = pyqtSignal(str)
    # (success, result_dict)  result_dict 同 detect_id_level 回傳格式
    finished = pyqtSignal(bool, dict)

    def __init__(
        self,
        base_dir: str,
        first_name: str,
        iso_path: Optional[str] = None,
        sep: str = "___",
        sheet: Optional[str] = None,
        pipe_col: Optional[str] = None,
    ):
        super().__init__()
        self.base_dir = base_dir
        self.first_name = first_name
        self.iso_path = iso_path or ""
        self.sep = sep
        self.sheet = sheet
        self.pipe_col = pipe_col

        # 結果欄位供 GUI 讀取
        self.best_sheet: Optional[str] = None
        self.detected_pipe_col: Optional[str] = None
        self.detected_spool_col: Optional[str] = None
        self.all_sheets: list[str] = []

    # ────────────────────────────────────────

    def run(self):  # noqa: C901 — intentionally sequential
        try:
            self._phase1_iso()
            self._phase2_csv()
            self._phase3_match()
        except Exception as exc:
            self.log.emit(f"✗ 錯誤：{exc}")
            self.log.emit(traceback.format_exc())
            self.finished.emit(False, {
                "level": None, "confidence": 0.0, "hits": {},
                "detail": str(exc),
            })

    # ── Phase 1：ISO 載入 ──────────────────

    def _phase1_iso(self):
        self.progress.emit(2, "Phase 1/3：載入 ISO 清單…")
        self.log.emit("═══ Phase 1：載入 ISO 清單 ═══")

        # ── 若尚未指定 ISO 路徑，自動搜尋 ──
        if not self.iso_path or not os.path.isfile(self.iso_path):
            self.progress.emit(3, "搜尋 ISO 檔案…")
            self.log.emit("  ISO 路徑未指定，自動搜尋中…")
            from gui.widgets import find_any_iso
            found = find_any_iso(self.base_dir)
            if found:
                self.iso_path = found
                self.log.emit(f"  ✓ 找到 ISO：{os.path.basename(found)}")
            else:
                raise FileNotFoundError(
                    f"在 {self.base_dir} 找不到 ISO LIST 檔案。\n"
                    "請手動選取 ISO 檔案。"
                )

        self.progress.emit(5, "開啟 Excel…")
        xls = pd.ExcelFile(self.iso_path, engine="openpyxl")
        self.all_sheets = list(xls.sheet_names)
        self.log.emit(f"  共 {len(self.all_sheets)} 個工作表")

        # ── 智慧選表 ──
        self.progress.emit(10, "評分工作表…")
        if self.sheet and self.sheet in xls.sheet_names:
            best = self.sheet
            self.log.emit(f"  使用指定工作表：{best}")
        else:
            best = pick_best_sheet(xls)
            self.log.emit(f"  自動選擇工作表：{best}")
        self.best_sheet = best

        # ── 讀取欄位 ──
        self.progress.emit(15, f"讀取 [{best}] 欄位…")
        iso_df = pd.read_excel(xls, sheet_name=best, dtype=str).fillna("")
        cols = [str(c).strip() for c in iso_df.columns if str(c).strip()]
        self.log.emit(f"  欄位數：{len(cols)}")

        # ── 偵測管線 / 流水號欄位 ──
        self.progress.emit(20, "偵測管線 / 流水號欄位…")
        pipe_col = detect_pipe_col(cols)
        spool_col = detect_spool_col(cols)
        if self.pipe_col and self.pipe_col in cols:
            pipe_col = self.pipe_col  # 使用者指定優先
        self.detected_pipe_col = pipe_col
        self.detected_spool_col = spool_col
        self.log.emit(f"  管線欄位：{pipe_col or '(未偵測到)'}")
        self.log.emit(f"  流水號欄位：{spool_col or '(未偵測到)'}")

        if not pipe_col:
            raise ValueError("ISO 清單找不到管線欄位。")

        # ── 蒐集探針 ──
        self.progress.emit(25, "蒐集探針…")
        probes: set[str] = set()
        for v in iso_df[pipe_col].astype(str).str.strip().unique():
            if v and v != "nan":
                probes.add(v)
        if "DWG NO" in iso_df.columns and pipe_col != "DWG NO":
            for v in iso_df["DWG NO"].astype(str).str.strip().unique():
                if v and v != "nan":
                    probes.add(v)

        max_probes = 80
        if len(probes) > max_probes:
            probes = set(list(probes)[:max_probes])
        self.log.emit(f"  探針數：{len(probes)}")
        self._probes = probes
        self.progress.emit(30, "Phase 1 完成 ✓")

    # ── Phase 2：讀取 First_try ────────────

    def _phase2_csv(self):
        self.progress.emit(32, "Phase 2/3：讀取 First_try.csv…")
        self.log.emit("═══ Phase 2：讀取 First_try.csv ═══")

        first_path = os.path.join(self.base_dir, self.first_name)
        if not os.path.isfile(first_path):
            raise FileNotFoundError(f"First_try 不存在：{first_path}")

        self.progress.emit(38, "解析 CSV…")
        raw_df = pd.read_csv(
            first_path, dtype=str, encoding="utf-8-sig",
            low_memory=False, on_bad_lines="skip",
        ).fillna("")
        # ── 向後相容：5 欄 (含 PipelineId) 或 4 欄 (舊格式) ──
        n_cols = min(len(raw_df.columns), 5)
        raw_df = raw_df.iloc[:, :n_cols].copy()
        col_names = ["Path", "DisplayName", "Class", "Level"]
        if n_cols >= 5:
            col_names.append("PipelineId")
        raw_df.columns = col_names
        if "PipelineId" not in raw_df.columns:
            raw_df["PipelineId"] = ""
        raw_df["DisplayName"] = raw_df["DisplayName"].astype(str).str.strip()
        raw_df["Level"] = raw_df["Level"].astype(str).str.strip()
        raw_df["PipelineId"] = raw_df["PipelineId"].astype(str).str.strip()

        dn_to_levels: dict[str, list[str]] = {}
        for _, row in raw_df.iterrows():
            dn = row["DisplayName"]
            lv = row["Level"]
            if dn:
                dn_to_levels.setdefault(dn, []).append(lv)
            # PipelineId 也加入查詢表（情境 B：管線編號只在屬性）
            pid = str(row.get("PipelineId", "")).strip()
            if pid and pid != dn:
                dn_to_levels.setdefault(pid, []).append(lv)

        self.log.emit(
            f"  共 {len(raw_df)} 列，"
            f"不重複 DisplayName/PipelineId {len(dn_to_levels)} 組"
        )
        self._dn_to_levels = dn_to_levels
        self.progress.emit(60, "Phase 2 完成 ✓")

    # ── Phase 3：探針比對 ──────────────────

    def _phase3_match(self):
        import re
        from collections import Counter
        from core.iso_matcher import _strip_size_segment

        self.progress.emit(62, "Phase 3/3：探針比對中…")
        self.log.emit("═══ Phase 3：探針比對 ═══")

        probes = self._probes
        dn_to_levels = self._dn_to_levels
        level_counter: Counter = Counter()
        probe_matched = 0
        probe_detail: list[str] = []

        total = len(probes)
        for i, probe in enumerate(probes):
            # 更新進度 (60% → 95%)
            pct = 62 + int((i / max(total, 1)) * 33)
            if i % 10 == 0:
                self.progress.emit(pct, f"比對探針 {i+1}/{total}…")

            # 策略 A：精確比對
            if probe in dn_to_levels:
                for lv in dn_to_levels[probe]:
                    level_counter[lv] += 1
                probe_matched += 1
                probe_detail.append(
                    f"  ✓ {probe} → Level={dn_to_levels[probe]}"
                )
                continue

            # 策略 B：去尺寸段比對
            matched_b = False
            for dn, levels in dn_to_levels.items():
                stripped = _strip_size_segment(dn)
                if stripped == probe:
                    for lv in levels:
                        level_counter[lv] += 1
                    probe_matched += 1
                    probe_detail.append(
                        f"  ✓ {probe} ≈strip→ {dn} → Level={levels}"
                    )
                    matched_b = True
                    break
            if matched_b:
                continue

            # 策略 C：去 spool 後綴
            probe_stripped = re.sub(r"-\d{1,3}$", "", probe)
            if probe_stripped != probe and probe_stripped in dn_to_levels:
                for lv in dn_to_levels[probe_stripped]:
                    level_counter[lv] += 1
                probe_matched += 1
                probe_detail.append(
                    f"  ✓ {probe} →去spool→ {probe_stripped}"
                    f" → Level={dn_to_levels[probe_stripped]}"
                )

        self.progress.emit(96, "統計結果…")
        self.log.emit(
            f"  探針命中率：{probe_matched}/{total}"
            f" ({probe_matched / max(total, 1):.0%})"
        )
        for d in probe_detail[:6]:
            self.log.emit(d)
        if len(probe_detail) > 6:
            self.log.emit(f"  … 共 {len(probe_detail)} 筆命中")

        # ── 組裝結果 ──
        if not level_counter:
            self.progress.emit(100, "偵測完成（無命中）")
            self.finished.emit(True, {
                "level": None, "confidence": 0.0,
                "hits": {},
                "detail": f"在 First_try.csv 中找不到任何命中。\n"
                          f"（共測試 {total} 組探針）",
            })
            return

        total_hits = sum(level_counter.values())
        best_str, best_count = level_counter.most_common(1)[0]
        confidence = best_count / total_hits if total_hits else 0.0
        try:
            best_level = int(best_str)
        except ValueError:
            best_level = None

        hits = dict(level_counter.most_common())
        detail_lines = [
            f"偵測結果：id_level = {best_level}",
            f"命中統計：{hits}",
            f"信心度：{confidence:.0%}"
            f"（Level {best_level} 命中 {best_count}/{total_hits}）",
            f"探針命中率：{probe_matched}/{total}"
            f" ({probe_matched / max(total, 1):.0%})",
        ]
        detail = "\n".join(detail_lines)
        self.log.emit(f"  {detail_lines[0]}")
        self.log.emit(f"  {detail_lines[2]}")

        self.progress.emit(100, "偵測完成 ✓")
        self.finished.emit(True, {
            "level": best_level,
            "confidence": confidence,
            "hits": hits,
            "detail": detail,
        })

    # ── 輔助：工作表評分 ─────────────────

    @staticmethod
    def _pick_best_sheet(xls: pd.ExcelFile) -> str:
        return pick_best_sheet(xls)

    @staticmethod
    def _detect_pipe_col(cols: list[str]) -> Optional[str]:
        return detect_pipe_col(cols)

    @staticmethod
    def _detect_spool_col(cols: list[str]) -> Optional[str]:
        return detect_spool_col(cols)
