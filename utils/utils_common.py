# -*- coding: utf-8 -*-
"""共用工具：字串處理、檔名清理、log 等。

由 Ver02 的 `run_pipeline.py` 重構為獨立模組與 class。
"""
from __future__ import annotations

import os
import re
from typing import List

import pandas as pd


class CommonUtils:
    """共用靜態工具函式集合。"""

    @staticmethod
    def detect_raw_column(df: pd.DataFrame) -> str:
        """嘗試猜「原始字串欄位」的欄名。"""
        candidates = ["Raw_3D_PipeCode", "Raw_last", "Raw last", "raw_last", "RAW_LAST"]
        for c in candidates:
            if c in df.columns:
                return c
        for c in df.columns:
            if "raw" in str(c).lower():
                return c
        return df.columns[0]

    @staticmethod
    def unique_preserve(seq) -> List[str]:
        """去重並保留原始順序。"""
        seen = set()
        out: List[str] = []
        for s in seq:
            s = "" if pd.isna(s) else str(s)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    @staticmethod
    def sanitize_filename(name: str, replacement: str = "_") -> str:
        """清理可能包含路徑或正則特殊符的檔名，轉為安全字串。"""
        if not isinstance(name, str):
            name = str(name)
        remove_set = set('<>:"|?*()[]{}^$+.%')
        cleaned = []
        for ch in name.strip():
            if ch in "/\\":
                cleaned.append(replacement)
            elif ch in remove_set:
                continue
            else:
                cleaned.append(ch)
        result = "".join(cleaned).strip()
        while replacement * 2 in result:
            result = result.replace(replacement * 2, replacement)
        return result or "file"

    @staticmethod
    def normalize_line(s: str) -> str:
        """將 Navis / 管線編號轉成標準化 key。"""
        if not isinstance(s, str):
            s = "" if pd.isna(s) else str(s)
        s = s.strip()
        if not s:
            return ""
        s = re.sub(r'^[^A-Za-z0-9]+', '', s).replace(" ", "")
        # 只在 "/" 不是分數（如 1/2", 3/4"）時才切割
        # 分數特徵：數字/數字（管徑標記）
        if "/" in s and not re.search(r'\d/\d', s):
            s = s.split("/", 1)[0]
        return s


PIPE_SEG_PATTERN = re.compile(
    r"(?i)^(?=.*\d)(?=.*-)[A-Z0-9][A-Z0-9\-\"'_/.]*[A-Z0-9\"']$"
)
STRUCTURAL_KEYWORDS = {
    "FRMWORK",
    "SUBSTRUCTURE",
    "STRUCTURE",
    "BRANCH",
    "WELD",
    "TUBE",
    "PIPELINE",
    "PIPELINEGROUP",
    "SKID",
    "SUPPORT",
    "FRAME",
}

# 含副檔名（如 .nwd / .rvm / .rvt）的段不應被當成管線段
_FILE_EXT_RE = re.compile(r'\.[a-zA-Z]{2,4}$')


class PipelineKeyExtractor:
    """管線段擷取與標準化相關工具。"""

    @staticmethod
    def guess_pipeline_segment(segments: List[str]) -> str:
        candidates = []
        for idx, seg in enumerate(segments):
            s = str(seg).strip()
            if not s:
                continue
            upper = s.upper()
            if any(k in upper for k in STRUCTURAL_KEYWORDS):
                continue
            # 含副檔名的段（如 HP6-20260127.nwd）不是管線段
            if _FILE_EXT_RE.search(s):
                continue
            if PIPE_SEG_PATTERN.match(s):
                candidates.append((len(s), idx, s))
        if not candidates:
            return ""
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]

    @staticmethod
    def extract_pipeline(
        path: str,
        sep: str,
        mode: str = "smart",
        index: int | None = None,
        regex: str | None = None,
        raw_prefix: str = "/",
    ) -> str:
        """通用管線段擷取（從 Ver02 拆出）。"""
        if not isinstance(path, str):
            path = "" if pd.isna(path) else str(path)
        segs = [x for x in path.split(sep) if x]
        if not segs:
            return ""
        chosen = ""
        if mode == "smart":
            chosen = PipelineKeyExtractor.guess_pipeline_segment(segs) or segs[-1]
        elif mode == "last":
            chosen = segs[-1]
        elif mode == "index" and index is not None:
            try:
                chosen = segs[index]
            except IndexError:
                chosen = segs[-1]
        elif mode == "regex" and regex:
            try:
                pattern = re.compile(regex)
                for s in segs:
                    if pattern.search(s):
                        chosen = s
                        break
            except re.error:
                chosen = segs[-1]
            if not chosen:
                chosen = segs[-1]
        else:
            chosen = segs[-1]
        chosen = re.sub(r'^[^A-Za-z0-9]+', '', chosen)
        if not chosen:
            return ""
        return (raw_prefix + chosen) if raw_prefix else chosen


class FileLogger:
    """簡單檔案 log 工具。"""

    def __init__(self, base_dir: str | None):
        self.base_dir = base_dir or ""

    def append(self, msg: str) -> None:
        if not self.base_dir:
            return
        try:
            log_path = os.path.join(self.base_dir, "run_pipeline_log.txt")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            # 寫 log 失敗不影響主流程
            pass
