# -*- coding: utf-8 -*-
"""ISO 清單比對：ISO LIST → iso_match.xlsx

重構為 `IsoMatcher` 類別。
"""
from __future__ import annotations

import os
import json
import re
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from utils.trace_builder import TraceBuilder, append_trace
from utils.utils_common import CommonUtils, normalize_line_v2
from utils.iso_schema import detect_schema
from utils.pipe_parser import load_pipe_pattern, DEFAULT_CONFIG_FILENAME
from core.iso_recall_engine import IsoRecallEngine
from core.candidate_family import annotate_candidate_families, candidate_item_id
from core.match_evidence import build_match_evidence
from core.match_safety import annotate_family_aware_safety
from core.project_rules import ProjectRuleStore
from core.scope_indexer import parse_scope_context
from core.size_normalizer import STATUS_MATCHED, is_size_like, normalize_size_token

# ── 尺寸段偵測用 regex ──
_SIZE_RE = re.compile(r"^\d+([Xx]\d+)?$")
_SUPPORTS_RE = re.compile(r"_Supports$", re.IGNORECASE)


def _strip_size_segment(line: str) -> str:
    """將 5 段管線編號中的尺寸段移除，回傳 4 段 key。

    例：``AR-1701-100-AA1B-NA`` → ``AR-1701-AA1B-NA``
    若不符合 5 段+第 3 段為尺寸的條件，則原樣回傳。
    同時移除 ``_Supports`` 後綴。
    """
    clean = _SUPPORTS_RE.sub("", line).strip()
    parts = clean.split("-")
    if len(parts) == 5 and _SIZE_RE.match(parts[2]):
        return "-".join(parts[:2] + parts[3:])
    return clean


def _compute_similarity(a: str, b: str) -> float:
    """字串相似度 (0~1)。"""
    return SequenceMatcher(None, a.upper(), b.upper()).ratio()


def _split_line_parts(line: str) -> list[str]:
    """切管線號時保留 1-1/2 這類 canonical mixed size。"""
    clean = _SUPPORTS_RE.sub("", str(line)).strip().upper()
    if not clean:
        return []

    raw_parts = [p.strip() for p in clean.split("-") if p.strip()]
    parts: list[str] = []
    i = 0
    while i < len(raw_parts):
        current = raw_parts[i]
        if i + 1 < len(raw_parts):
            combined = f"{current}-{raw_parts[i + 1]}"
            canonical, _inches, status = normalize_size_token(combined)
            if status == STATUS_MATCHED:
                parts.append(canonical.upper())
                i += 2
                continue
        parts.append(current)
        i += 1
    return parts


def _is_size_part(part: str) -> bool:
    value = str(part).strip()
    if not value:
        return False
    if _SIZE_RE.match(value):
        return True
    return is_size_like(value)


def _line_stem(value: str) -> str:
    """移除 ISO 尾碼字母，讓 20951Q 可召回 20951。"""
    clean = str(value).strip().upper()
    if re.search(r"\d[A-Z]$", clean):
        return clean[:-1]
    return clean


def _semantic_keys(line: str) -> list[str]:
    seg = _parse_segments(line)
    system = seg.get("system", "")
    class_code = seg.get("class", "")
    line_no = seg.get("line_no", "")
    stem = _line_stem(line_no)
    keys: list[str] = []
    if system and class_code and stem:
        keys.append(f"SYS_CLASS_STEM:{system}|{class_code}|{stem}")
    if system and stem:
        keys.append(f"SYS_STEM:{system}|{stem}")
    if stem and len(stem) >= 4:
        keys.append(f"STEM:{stem}")
    return keys


# ── 段位名稱對照 ──
_SEG_ROLES = ["system", "line_no", "size", "class", "insulation"]

# ── 段位權重 ──
_SEG_WEIGHTS = {
    "system":     0.25,   # 系統
    "line_no":    0.30,   # 編號
    "combo":      0.20,   # 系統+編號同時吻合額外加成
    "size":       0.08,   # 尺寸
    "class":      0.07,   # 材質
    "insulation": 0.05,   # 保溫
    "residual":   0.05,   # 字串相似度餘值
}

_MATCH_TYPE_SCORES = {
    "strict": "1.00",
    "strip_size": "0.95",
    "drop_last_seg": "0.85",
    "fallback_base": "0.70",
    "loose_only": "0.50",
    "fuzzy_manual": "0.90",
}

_MATCH_TYPE_REASONS = {
    "strict": "ISO key 與 3D key 嚴謹吻合",
    "strip_size": "3D key 去尺寸段後吻合 ISO key",
    "drop_last_seg": "3D key 去末段後吻合 ISO key",
    "fallback_base": "使用舊有 base fallback 命中",
    "loose_only": "僅寬鬆 key 有 ISO 家族，保留待檢查",
    "fuzzy_manual": "使用者手動確認 fuzzy 候選",
}


def _parse_segments(line: str) -> dict[str, str]:
    """將管線編號拆成 segment dict。

    支援 5 段 ``system-line_no-size-class-insulation``
    或 4 段 ``system-line_no-class-insulation`` (ISO 常缺尺寸段)。
    回傳 ``{"system": ..., "line_no": ..., "size": ..., ...}``。
    """
    clean = _SUPPORTS_RE.sub("", line).strip().upper()
    parts = _split_line_parts(clean)
    result: dict[str, str] = {}
    if len(parts) >= 4 and _is_size_part(parts[0]):
        # CP-129 常見：尺寸-系統-材質/等級-線號，例如 3/4-S11G-N4-20951Q
        result["size"] = parts[0]
        result["system"] = parts[1]
        result["class"] = parts[2]
        result["line_no"] = "-".join(parts[3:])
        result["insulation"] = ""
    elif len(parts) >= 3 and _is_size_part(parts[0]):
        result["size"] = parts[0]
        result["system"] = parts[1]
        result["line_no"] = "-".join(parts[2:])
        result["class"] = ""
        result["insulation"] = ""
    elif len(parts) >= 5 and _SIZE_RE.match(parts[2]):
        # 5 段：系統-編號-尺寸-材質-保溫
        result["system"] = parts[0]
        result["line_no"] = parts[1]
        result["size"] = parts[2]
        result["class"] = parts[3]
        result["insulation"] = "-".join(parts[4:])  # 以防有多餘段
    elif len(parts) >= 4:
        # 4 段 (ISO 缺尺寸)：系統-編號-材質-保溫
        result["system"] = parts[0]
        result["line_no"] = parts[1]
        result["size"] = ""
        result["class"] = parts[2]
        result["insulation"] = "-".join(parts[3:])
    elif len(parts) >= 2:
        result["system"] = parts[0]
        result["line_no"] = parts[1]
        result["size"] = parts[2] if len(parts) > 2 else ""
        result["class"] = ""
        result["insulation"] = ""
    else:
        result["system"] = clean
        result["line_no"] = ""
        result["size"] = ""
        result["class"] = ""
        result["insulation"] = ""
    return result


def _compute_segment_score(iso_line: str, line_3d: str) -> tuple[float, str]:
    """段位感知計分 (0.0~1.0)。

    權重設計：
    - system 完全吻合 → +0.25
    - line_no 完全吻合 → +0.30
    - system + line_no 同時吻合 → 額外 +0.20 (合計 0.75)
    - size 吻合 → +0.08
    - class 吻合 → +0.07
    - insulation 吻合 → +0.05
    - 字串相似度餘值 → 最高 +0.05
    滿分 1.0。
    """
    seg_iso = _parse_segments(iso_line)
    seg_3d = _parse_segments(line_3d)

    score = 0.0
    reasons: list[str] = []

    sys_match = seg_iso["system"] == seg_3d["system"] and seg_iso["system"] != ""
    lineno_match = seg_iso["line_no"] == seg_3d["line_no"] and seg_iso["line_no"] != ""
    iso_stem = _line_stem(seg_iso["line_no"])
    d3_stem = _line_stem(seg_3d["line_no"])
    lineno_stem_match = (
        not lineno_match
        and iso_stem
        and d3_stem
        and iso_stem == d3_stem
    )

    if sys_match:
        score += _SEG_WEIGHTS["system"]
        reasons.append(f"系統={seg_iso['system']}")
    if lineno_match:
        score += _SEG_WEIGHTS["line_no"]
        reasons.append(f"編號={seg_iso['line_no']}")
    elif lineno_stem_match:
        score += _SEG_WEIGHTS["line_no"] * 0.8
        reasons.append(f"編號主體={iso_stem}")
    if sys_match and lineno_match:
        score += _SEG_WEIGHTS["combo"]
        reasons.append("系統+編號同時吻合(+加成)")
    elif sys_match and lineno_stem_match:
        score += _SEG_WEIGHTS["combo"] * 0.6
        reasons.append("系統+編號主體吻合")

    # size: 若其中一方缺尺寸段，視為「不懲罰」(給一半權重)
    if seg_iso["size"] and seg_3d["size"]:
        if seg_iso["size"] == seg_3d["size"]:
            score += _SEG_WEIGHTS["size"]
            reasons.append(f"尺寸={seg_iso['size']}")
    elif not seg_iso["size"] or not seg_3d["size"]:
        # 一方缺尺寸段不懲罰，給半分
        score += _SEG_WEIGHTS["size"] * 0.5

    if seg_iso["class"] and seg_3d["class"]:
        if seg_iso["class"] == seg_3d["class"]:
            score += _SEG_WEIGHTS["class"]
            reasons.append(f"材質={seg_iso['class']}")
        else:
            # 材質不同但有值，用相似度部分補分
            cls_sim = SequenceMatcher(
                None, seg_iso["class"], seg_3d["class"]
            ).ratio()
            score += _SEG_WEIGHTS["class"] * cls_sim * 0.5

    if seg_iso["insulation"] and seg_3d["insulation"]:
        if seg_iso["insulation"] == seg_3d["insulation"]:
            score += _SEG_WEIGHTS["insulation"]
            reasons.append(f"保溫={seg_iso['insulation']}")

    # residual: 全字串相似度 × 0.05
    residual = _compute_similarity(iso_line, line_3d)
    score += _SEG_WEIGHTS["residual"] * residual

    score = min(score, 1.0)
    reason_str = ", ".join(reasons) if reasons else f"相似度{residual:.0%}"
    return round(score, 4), reason_str


def _match_trace_for_row(row: pd.Series) -> str:
    match_type = str(row.get("MatchType", "")).strip()
    tb = TraceBuilder()
    if match_type:
        tb.add("match", match_type)
    tb.add("iso_key", str(row.get("ISO_Match_Key", "")).strip())
    score = _MATCH_TYPE_SCORES.get(match_type)
    if score:
        tb.add("score", score)
    tb.add("reason", _MATCH_TYPE_REASONS.get(match_type, "保留既有比對結果"))
    return tb.build()


def _normalize_key_with_trace(value: object) -> tuple[str, str]:
    normalized, events = normalize_line_v2(str(value))
    return normalized, TraceBuilder().extend_events(events).build()


class IsoMatcher:
    def __init__(self):
        # ── 模糊比對候選，Step3 完成後可供 GUI 讀取 ──
        self.fuzzy_unmatched: List[Dict] = []
        # [{
        #     "iso_line": str,       # ISO 原始管線編號
        #     "iso_spool": str,      # 流水號
        #     "candidates": [        # 候選 3D 線，命中機率高→低
        #         {"line_3d": str, "score": float, "reason": str},
        #         ...
        #     ],
        # }]

    def check_iso_coverage(
        self,
        base_dir: str,
        minus_csv_path: str,
        iso_list_path: Optional[str] = None,
        iso_sheet_name: Optional[str] = None,
        pipe_col_override: Optional[str] = None,
        spool_col_override: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """檢查 ISO LIST 每一列管線是否能在 minus_2 的 ISO_Match_Key 中找到家。

        - 讀取 123_minus_2.csv（若不存在則退回 123_minus_1.csv）。
        - 對 minus 的 ISO_Match_Key 與 ISO 的管線欄位都套用 normalize_line_v2。
        - 產出一份 coverage 報表，其中列出：
          - 每列 ISO 的原始管線編號、流水號、標準化 key
          - 是否在 minus 端找到對應 (Matched: 1/0)
        - 回傳輸出檔完整路徑。
        """

        def _log(msg: str) -> None:
            print(msg)

        if not os.path.exists(minus_csv_path):
            fallback = os.path.join(base_dir, "123_minus_1.csv")
            if os.path.exists(fallback):
                _log(f"[Coverage] 找不到 123_minus_2.csv，改用：{fallback}")
                minus_csv_path = fallback
            else:
                raise FileNotFoundError(
                    "[Coverage] 找不到可用的輸入檔："
                    f"{minus_csv_path} 或 {fallback}，請先完成 Step1/Step2。"
                )

        df_minus = pd.read_csv(
            minus_csv_path, dtype=str, encoding="utf-8-sig"
        ).fillna("")

        # 向後相容：處理舊檔案欄位名稱
        if "ISO_Match_Key" not in df_minus.columns:
            rename_map = {}
            if "Line_combined" in df_minus.columns:
                rename_map["Line_combined"] = "ISO_Match_Key"
            elif "Line combined" in df_minus.columns:
                rename_map["Line combined"] = "ISO_Match_Key"
            if rename_map:
                df_minus = df_minus.rename(columns=rename_map)
        if "ISO_Match_Key" not in df_minus.columns:
            raise ValueError(
                "[Coverage] minus 檔缺少欄位『ISO_Match_Key』，請確認先執行 Step1/Step2。"
            )

        df_minus["__line_norm"] = df_minus["ISO_Match_Key"].astype(str).apply(
            lambda value: normalize_line_v2(value)[0]
        )
        minus_set = set(df_minus["__line_norm"].tolist())

        if iso_list_path:
            iso_path = iso_list_path
            if not os.path.exists(iso_path):
                raise FileNotFoundError(
                    "[Coverage] 指定的 ISO LIST 檔案不存在："
                    f"{iso_path}，請重新選擇或留空改用自動搜尋。"
                )
        else:
            iso_path = self._find_latest_iso_list(base_dir)

        _log(f"[Coverage] 使用 ISO 清單檔案：{iso_path}")
        xls = pd.ExcelFile(iso_path, engine="openpyxl")

        schema = detect_schema(
            xls,
            sheet_name=iso_sheet_name,
            pipe_col_override=pipe_col_override,
            spool_col_override=spool_col_override,
        )
        sheet_to_use = schema.sheet_name

        iso_df = pd.read_excel(xls, sheet_name=sheet_to_use, dtype=str).fillna("")
        try:
            xls.close()
        except Exception:
            pass

        spool_col = schema.spool_col
        if spool_col not in iso_df.columns:
            iso_df["流水號"] = ""
            spool_col = "流水號"

        pipe_col = schema.pipe_col

        cov = pd.DataFrame()
        cov["管線編號"] = iso_df[pipe_col].astype(str).str.strip()
        cov["流水號"] = iso_df[spool_col].astype(str).str.strip()
        cov["line_norm"] = cov["管線編號"].apply(lambda value: normalize_line_v2(value)[0])
        cov["Matched"] = cov["line_norm"].apply(
            lambda k: 1 if k and k in minus_set else 0
        )

        if output_path is None:
            output_path = os.path.join(base_dir, "iso_line_coverage.xlsx")

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            cov.to_excel(writer, index=False, sheet_name="coverage")

        _log(
            f"[Coverage] 已輸出 ISO 覆蓋檢查報表，共 {len(cov)} 列，"
            f"其中 {int(cov['Matched'].sum())} 列有找到對應 minus line。"
        )
        return output_path

    def check_minus_coverage(
        self,
        base_dir: str,
        minus_csv_path: str,
        iso_list_path: Optional[str] = None,
        iso_sheet_name: Optional[str] = None,
        pipe_col_override: Optional[str] = None,
        loose_join_roles: Optional[List[str]] = None,
    ) -> str:
        """檢查 minus_2 的每一條 ISO_Match_Key 是否至少有一列 ISO 管線編號對應。

        這是從 3D 身分證的角度看 ISO 覆蓋率：
        - minus_2 端：使用 ISO_Match_Key → normalize_line_v2 後成 minus_line_norm。
        - ISO 端：使用管線欄位 → normalize 成 iso_line_norm。
        - 若某條 minus_line_norm 不在任何 iso_line_norm 之中，則視為「3D 有、ISO 沒有」。
        """

        def _log(msg: str) -> None:
            print(msg)

        if not os.path.exists(minus_csv_path):
            fallback = os.path.join(base_dir, "123_minus_1.csv")
            if os.path.exists(fallback):
                _log(f"[MinusCoverage] 找不到 123_minus_2.csv，改用：{fallback}")
                minus_csv_path = fallback
            else:
                raise FileNotFoundError(
                    "[MinusCoverage] 找不到可用的輸入檔："
                    f"{minus_csv_path} 或 {fallback}，請先完成 Step1/Step2。"
                )

        df_minus = pd.read_csv(
            minus_csv_path, dtype=str, encoding="utf-8-sig"
        ).fillna("")

        # 向後相容：處理舊檔案欄位名稱
        if "ISO_Match_Key" not in df_minus.columns:
            rename_map = {}
            if "Line_combined" in df_minus.columns:
                rename_map["Line_combined"] = "ISO_Match_Key"
            elif "Line combined" in df_minus.columns:
                rename_map["Line combined"] = "ISO_Match_Key"
            if rename_map:
                df_minus = df_minus.rename(columns=rename_map)
        if "ISO_Match_Key" not in df_minus.columns:
            raise ValueError(
                "[MinusCoverage] minus 檔缺少欄位『ISO_Match_Key』，請確認先執行 Step1/Step2。"
            )

        df_minus["ISO_Match_Key"] = df_minus["ISO_Match_Key"].astype(str).str.strip()
        df_minus["line_norm"] = df_minus["ISO_Match_Key"].apply(
            lambda value: normalize_line_v2(value)[0]
        )

        if iso_list_path:
            iso_path = iso_list_path
            if not os.path.exists(iso_path):
                raise FileNotFoundError(
                    "[MinusCoverage] 指定的 ISO LIST 檔案不存在："
                    f"{iso_path}，請重新選擇或留空改用自動搜尋。"
                )
        else:
            iso_path = self._find_latest_iso_list(base_dir)

        xls = pd.ExcelFile(iso_path, engine="openpyxl")

        schema = detect_schema(
            xls,
            sheet_name=iso_sheet_name,
            pipe_col_override=pipe_col_override,
        )
        sheet_to_use = schema.sheet_name

        iso_df = pd.read_excel(xls, sheet_name=sheet_to_use, dtype=str).fillna("")
        try:
            xls.close()
        except Exception:
            pass

        pipe_col = schema.pipe_col

        iso_df["pipe_raw"] = iso_df[pipe_col].astype(str).str.strip()
        iso_df["line_norm"] = iso_df["pipe_raw"].apply(
            lambda value: normalize_line_v2(value)[0]
        )
        iso_set = set(iso_df["line_norm"].tolist())

        # 嚴謹比對：完整標準化字串 1:1 覆蓋
        minus_cov = df_minus[["ISO_Match_Key", "line_norm"]].drop_duplicates().copy()
        minus_cov["Matched_strict"] = minus_cov["line_norm"].apply(
            lambda k: 1 if k and k in iso_set else 0
        )

        # 寬鬆比對：依照 pipe_code_pattern，把多個 role 串在一起當 key
        # 若呼叫端沒有指定 loose_join_roles，預設為 ["system", "line_no"]
        if loose_join_roles is None:
            loose_join_roles = ["system", "line_no"]

        # 從 base_dir 底下載入 pipeline_config.json（若不存在則略過寬鬆比對）
        config_path = os.path.join(base_dir, DEFAULT_CONFIG_FILENAME)
        pattern = load_pipe_pattern(config_path) if os.path.exists(config_path) else {}

        def _build_loose_key_from_norm(line_norm: str) -> str:
            if not line_norm:
                return ""
            if not pattern:
                return ""
            seps = pattern.get("separators") or ["-"]
            sep = str(seps[0]) if seps else "-"
            parts = str(line_norm).split(sep)
            if not parts:
                return ""
            # 依 segments.role 找出對應 index，然後從 parts 抽出並串接
            segments_def = pattern.get("segments") or []
            role_to_indices = {}
            for seg in segments_def:
                try:
                    idx = int(seg.get("index"))
                except Exception:
                    continue
                role = (seg.get("role") or "").strip()
                if not role:
                    continue
                role_to_indices.setdefault(role, []).append(idx)

            values: List[str] = []
            for role in loose_join_roles:
                for idx in role_to_indices.get(role, []):
                    if 0 <= idx < len(parts):
                        v = str(parts[idx]).strip()
                        if v:
                            values.append(v)
            return "|".join(values) if values else ""

        # 建立 ISO 端的寬鬆 key set
        iso_df["loose_key"] = iso_df["line_norm"].apply(_build_loose_key_from_norm)
        iso_loose_set = {k for k in iso_df["loose_key"].tolist() if k}

        # 3D 端也建立寬鬆 key，並判斷是否在 ISO 寬鬆 key 中
        minus_cov["loose_key"] = minus_cov["line_norm"].apply(
            _build_loose_key_from_norm
        )
        minus_cov["Matched_loose"] = minus_cov["loose_key"].apply(
            lambda k: 1 if k and k in iso_loose_set else 0
        )

        output_path = os.path.join(base_dir, "minus_line_coverage.xlsx")
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            minus_cov.to_excel(writer, index=False, sheet_name="coverage")

        _log(
            f"[MinusCoverage] 已輸出 minus_2 覆蓋檢查報表，共 {len(minus_cov)} 條 ISO_Match_Key，"
            f"嚴謹比對 {int(minus_cov['Matched_strict'].sum())} 條，寬鬆比對 {int(minus_cov['Matched_loose'].sum())} 條有對應 ISO 管線。"
        )
        return output_path

    @staticmethod
    def _find_latest_iso_list(base_dir: str) -> str:
        candidates = []
        for root, _, files in os.walk(base_dir):
            for name in files:
                lower = name.lower()
                if lower.startswith("iso list.all") and lower.endswith(
                    (".xlsx", ".xlsm")
                ):
                    full = os.path.join(root, name)
                    mtime = os.path.getmtime(full)
                    candidates.append((mtime, full))
        if not candidates:
            raise FileNotFoundError(
                "[Step3] 在 {base_dir} 底下找不到符合 'ISO LIST.ALL*.xlsx/.xlsm' 的檔案，"
                "請確認 ISO 檔名或在 GUI 裡手動指定。".format(base_dir=base_dir)
            )
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def run(
        self,
        base_dir: str,
        minus_csv_path: str,
        iso_output_path: str,
        iso_list_path: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None,
        iso_sheet_name: Optional[str] = None,
        pipe_col_override: Optional[str] = None,
        spool_col_override: Optional[str] = None,
        extra_iso_headers: Optional[List[str]] = None,
        limit_iso_cols: bool = False,
        first_try_path: Optional[str] = None,
        dataset_revision: str = "",
        approved_punctuation_aliases: Optional[Dict[str, str]] = None,
    ) -> int:
        def _log(msg: str) -> None:
            if log_fn is not None:
                log_fn(msg)
            else:
                print(msg)

        try:
            if approved_punctuation_aliases is None:
                approved_punctuation_aliases = ProjectRuleStore(
                    base_dir
                ).approved_punctuation_aliases()
            else:
                approved_punctuation_aliases = dict(
                    approved_punctuation_aliases
                )
            if approved_punctuation_aliases:
                _log(
                    "[ProjectRules] 已載入本專案核准的符號 alias："
                    + ", ".join(
                        f"{source!r}→{target!r}"
                        for source, target in approved_punctuation_aliases.items()
                    )
                )
        except Exception as rule_exc:
            approved_punctuation_aliases = {}
            _log(f"[ProjectRules] 規則載入失敗，改採全部人工覆核：{rule_exc}")

        if not os.path.exists(minus_csv_path):
            fallback = os.path.join(base_dir, "123_minus_1.csv")
            if os.path.exists(fallback):
                if log_fn:
                    log_fn(f"[Step3] 找不到 123_minus_2.csv，改用：{fallback}")
                minus_csv_path = fallback
            else:
                raise FileNotFoundError(
                    "[Step3] 找不到可用的輸入檔："
                    f"{minus_csv_path} 或 {fallback}，請先完成 Step1/Step2。"
                )

        try:
            df_minus = pd.read_csv(
                minus_csv_path, dtype=str, encoding="utf-8-sig"
            ).fillna("")
        except UnicodeDecodeError as e:
            msg = (
                "[Step3] 讀取管線中繼檔編碼失敗："
                f"{minus_csv_path}，請確認是否為 UTF-8-SIG。原始錯誤：{e.reason}"
            )
            raise UnicodeDecodeError(
                e.encoding or "utf-8-sig",
                e.object,
                e.start,
                e.end,
                msg,
            )
        except Exception as e:
            raise RuntimeError(
                "[Step3] 讀取管線中繼檔失敗："
                f"{minus_csv_path}，請檢查檔案是否被鎖定或格式是否正確。詳細：{e}"
            ) from e

        # 向後相容：處理舊檔案欄位名稱
        if "ISO_Match_Key" not in df_minus.columns:
            rename_map = {}
            if "Line_combined" in df_minus.columns:
                rename_map["Line_combined"] = "ISO_Match_Key"
            elif "Line combined" in df_minus.columns:
                rename_map["Line combined"] = "ISO_Match_Key"
            if rename_map:
                df_minus = df_minus.rename(columns=rename_map)

        if "ISO_Match_Key" not in df_minus.columns:
            raise ValueError(
                "[Step3] 123_minus_2.csv / 123_minus_1.csv 缺少欄位『ISO_Match_Key』，"
                "請確認是否有先執行 Step1/Step2 並使用新版程式產生。"
            )

        if "Raw_3D_PipeCode" not in df_minus.columns:
            if "Raw_last" in df_minus.columns:
                df_minus = df_minus.rename(columns={"Raw_last": "Raw_3D_PipeCode"})
            else:
                df_minus["Raw_3D_PipeCode"] = ""
        df_minus["Raw_3D_PipeCode"] = df_minus["Raw_3D_PipeCode"].astype(str).str.strip()
        df_minus["ISO_Match_Key"] = (
            df_minus["ISO_Match_Key"].astype(str).str.strip()
        )
        scope_cols = ["PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel"]
        for c in scope_cols:
            if c not in df_minus.columns:
                df_minus[c] = ""
            df_minus[c] = df_minus[c].astype(str).str.strip()
        identity_cols = [
            "MatchSource",
            "ConfidencePrimary",
            "IdentityReason",
            "CandidateCount",
            "CandidateTrace",
        ]
        for c in identity_cols:
            if c not in df_minus.columns:
                df_minus[c] = ""
            df_minus[c] = df_minus[c].astype(str).str.strip()
        minus_norm_trace = df_minus["ISO_Match_Key"].apply(_normalize_key_with_trace)
        df_minus["__line_norm"] = minus_norm_trace.apply(lambda item: item[0])
        df_minus["IdentityReason"] = [
            append_trace(reason, trace)
            for reason, trace in zip(
                df_minus["IdentityReason"].tolist(),
                minus_norm_trace.apply(lambda item: item[1]).tolist(),
            )
        ]

        _log("=== run_pipeline Step3 LOG ===")
        _log(f"df_minus rows = {len(df_minus)}")
        _log(f"df_minus columns = {list(df_minus.columns)}")
        _log(
            "ISO_Match_Key sample (前 5 筆標準化前): "
            + ", ".join(df_minus["ISO_Match_Key"].head(5).tolist())
        )
        _log(
            "line_norm sample (前 5 筆): "
            + ", ".join(df_minus["__line_norm"].head(5).tolist())
        )

        if iso_list_path:
            iso_path = iso_list_path
            if not os.path.exists(iso_path):
                raise FileNotFoundError(
                    "[Step3] 指定的 ISO LIST 檔案不存在："
                    f"{iso_path}，請重新選擇或留空改用自動搜尋。"
                )
        else:
            iso_path = self._find_latest_iso_list(base_dir)

        _log(f"使用 ISO 清單檔案：{iso_path}")

        try:
            xls = pd.ExcelFile(iso_path, engine="openpyxl")
        except ImportError as e:
            raise ImportError(
                "[Step3] 載入 ISO 檔案失敗，缺少 openpyxl 套件，請先在命令列執行：pip install openpyxl"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"[Step3] 讀取 ISO 檔案失敗：{iso_path}，請確認檔案未損毀且為 Excel 格式。詳細：{e}"
            ) from e

        try:
            schema = detect_schema(
                xls,
                sheet_name=iso_sheet_name,
                pipe_col_override=pipe_col_override,
                spool_col_override=spool_col_override,
            )
        except ValueError as e:
            raise ValueError(f"[Step3] {e}") from e

        sheet_to_use = schema.sheet_name
        _log(f"使用工作表：{sheet_to_use}")

        try:
            iso_df = pd.read_excel(
                xls, sheet_name=sheet_to_use, dtype=str
            ).fillna("")
            try:
                xls.close()
            except Exception:
                pass
        except Exception as e:
            raise RuntimeError(
                "[Step3] 讀取 ISO 工作表失敗："
                f"檔案={iso_path}，工作表={sheet_to_use}，請檢查格式是否為標準表格。詳細：{e}"
            ) from e

        _log(f"iso_df rows = {len(iso_df)}")
        _log(f"iso_df columns = {list(iso_df.columns)}")

        # 記住 ISO_LIST 原始欄位（後續全數輸出）
        _iso_original_cols = [
            c for c in iso_df.columns
            if not str(c).startswith("__")
        ]

        for warning in schema.warnings:
            _log(f"[Schema] {warning}")

        spool_col = schema.spool_col
        if spool_col not in iso_df.columns:
            iso_df["流水號"] = ""
            spool_col = "流水號"

        pipe_col = schema.pipe_col

        iso_df["__pipe_raw"] = iso_df[pipe_col].astype(str).str.strip()
        iso_df["流水號"] = iso_df[spool_col].astype(str).str.strip()
        iso_norm_trace = iso_df["__pipe_raw"].apply(_normalize_key_with_trace)
        iso_df["__line_norm"] = iso_norm_trace.apply(lambda item: item[0])
        iso_df["__norm_trace"] = iso_norm_trace.apply(lambda item: item[1])

        _log(
            "iso pipe_raw sample (前 5 筆): "
            + ", ".join(iso_df["__pipe_raw"].head(5).tolist())
        )
        _log(
            "iso line_norm sample (前 5 筆): "
            + ", ".join(iso_df["__line_norm"].head(5).tolist())
        )

        minus_line_set = set(df_minus["__line_norm"].tolist())
        iso_keep = iso_df[iso_df["__line_norm"].isin(minus_line_set)].copy()
        _log(f"iso_keep rows after line_norm match = {len(iso_keep)}")

        merged = None
        used_key_type = "primary"
        minus_identity_cols = [
            "ISO_Match_Key",
            "Raw_3D_PipeCode",
            "MatchSource",
            "ConfidencePrimary",
            "IdentityReason",
            "CandidateCount",
            "CandidateTrace",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
        ]

        # ── Phase 1: 嚴謹比對 ──
        if len(iso_keep) > 0:
            minus_map = df_minus[
                ["__line_norm"] + minus_identity_cols
            ].drop_duplicates()
            merged = iso_keep.merge(minus_map, on="__line_norm", how="left")
            merged["MatchType"] = "strict"
            used_key_type = "primary"
            _log(f"Phase1 strict merged rows = {len(merged)}")

        # ── Phase 2: 去尺寸段比對 ──
        # 3D 常為 5 段 (系統-編號-尺寸-材質-保溫)，ISO 為 4 段 (無尺寸)
        # 將 3D 的 ISO_Match_Key 去掉尺寸段後比對
        already_matched = set()
        if merged is not None:
            already_matched = set(merged["__line_norm"].tolist())
        iso_remaining = iso_df[~iso_df["__line_norm"].isin(already_matched)]
        if len(iso_remaining) > 0:
            _log("Phase2: 嘗試去尺寸段比對 (strip-size)...")
            df_minus["__line_stripped"] = df_minus["__line_norm"].apply(
                _strip_size_segment
            )
            stripped_set = set(df_minus["__line_stripped"].tolist())

            iso_strip_keep = iso_remaining[
                iso_remaining["__line_norm"].isin(stripped_set)
            ].copy()
            _log(f"Phase2 strip-size matched rows = {len(iso_strip_keep)}")

            if len(iso_strip_keep) > 0:
                minus_strip_map = df_minus[
                    ["__line_stripped"] + minus_identity_cols
                ].drop_duplicates()
                strip_merged = iso_strip_keep.merge(
                    minus_strip_map,
                    left_on="__line_norm",
                    right_on="__line_stripped",
                    how="left",
                )
                strip_merged["MatchType"] = "strip_size"
                if merged is not None:
                    merged = pd.concat([merged, strip_merged], ignore_index=True)
                else:
                    merged = strip_merged
                used_key_type = "strip_size" if used_key_type == "primary" and len(iso_keep) == 0 else used_key_type

        # ── Phase 2b: ISO 缺末段 (如缺 -NA)：把 3D 去掉末段後比對 ──
        already_matched_2 = set()
        if merged is not None:
            already_matched_2 = set(merged["__line_norm"].tolist())
        iso_remaining_2 = iso_df[~iso_df["__line_norm"].isin(already_matched_2)]
        if len(iso_remaining_2) > 0:
            _log("Phase2b: 嘗試 3D 去末段比對 (ISO 可能缺 -NA 後綴)...")
            df_minus["__line_drop_last"] = df_minus["__line_norm"].apply(
                lambda s: "-".join(s.split("-")[:-1]) if s.count("-") >= 3 else s
            )
            drop_last_set = set(df_minus["__line_drop_last"].tolist())
            iso_drop_keep = iso_remaining_2[
                iso_remaining_2["__line_norm"].isin(drop_last_set)
            ].copy()
            _log(f"Phase2b drop-last matched rows = {len(iso_drop_keep)}")

            if len(iso_drop_keep) > 0:
                minus_drop_map = df_minus[
                    ["__line_drop_last"] + minus_identity_cols
                ].drop_duplicates()
                drop_merged = iso_drop_keep.merge(
                    minus_drop_map,
                    left_on="__line_norm",
                    right_on="__line_drop_last",
                    how="left",
                )
                drop_merged["MatchType"] = "drop_last_seg"
                if merged is not None:
                    merged = pd.concat([merged, drop_merged], ignore_index=True)
                else:
                    merged = drop_merged

        # ── Phase 3: 舊有 fallback (去末尾 -NNN) ──
        if merged is None or len(merged) == 0:
            iso_df["__pipe_base"] = iso_df["__pipe_raw"].str.replace(
                r"-\d{3,4}$", "", regex=True
            )
            df_minus["__line_base"] = df_minus["__line_norm"].str.replace(
                r"-\d{3,4}$", "", regex=True
            )
            base_set = set(df_minus["__line_base"].tolist())
            iso_keep_base = iso_df[iso_df["__pipe_base"].isin(base_set)].copy()
            _log(f"Phase3 fallback base match rows = {len(iso_keep_base)}")
            if len(iso_keep_base) > 0:
                minus_map_base = df_minus[
                    ["__line_base"] + minus_identity_cols
                ].drop_duplicates()
                fb_merged = iso_keep_base.merge(
                    minus_map_base,
                    left_on="__pipe_base",
                    right_on="__line_base",
                    how="left",
                )
                fb_merged["MatchType"] = "fallback_base"
                if merged is not None:
                    merged = pd.concat([merged, fb_merged], ignore_index=True)
                else:
                    merged = fb_merged
                used_key_type = "fallback_base"

        # ── 確保 merged 存在 ──
        if merged is None:
            minus_map = df_minus[
                ["__line_norm"] + minus_identity_cols
            ].drop_duplicates()
            merged = iso_keep.merge(minus_map, on="__line_norm", how="left")
            if "MatchType" not in merged.columns:
                merged["MatchType"] = ""

        # ── Phase 4: 收集尚未配對的 ISO 行 + 模糊候選 ──
        matched_iso_norms = set(merged["__line_norm"].tolist()) if len(merged) > 0 else set()
        iso_still_unmatched = iso_df[~iso_df["__line_norm"].isin(matched_iso_norms)]
        _log(f"Phase4: 尚未配對的 ISO 行 = {len(iso_still_unmatched)}")

        # 建立多組 3D 索引：舊前綴 + 語意 key，避免尺寸開頭格式讓候選召回變空。
        minus_valid = df_minus[
            df_minus["__line_norm"].str.strip().ne("")
            & df_minus["__line_norm"].str.strip().ne("0")
        ]
        all_3d_lines = [str(v).strip() for v in minus_valid["__line_norm"].unique() if str(v).strip()]
        _log(
            "Phase4: 可用 3D line_norm 數 = "
            f"{len(all_3d_lines)}（minus rows={len(df_minus)}）"
        )
        if not all_3d_lines:
            _log(
                "Phase4[WARN]: minus 檔沒有可用 3D key。"
                "這通常表示 Step1 沒抓到管線身份；本階段只能嘗試 "
                "candidates.csv / First_try 反向召回。"
            )
        prefix_to_3d: Dict[str, List[str]] = {}
        system_to_3d: Dict[str, List[str]] = {}
        semantic_to_3d: Dict[str, List[str]] = {}
        stem_to_3d: Dict[str, List[str]] = {}
        for v in all_3d_lines:
            parts = _split_line_parts(v)
            if len(parts) >= 2:
                pfx = "-".join(parts[:2])
                prefix_to_3d.setdefault(pfx, []).append(v)
            seg = _parse_segments(v)
            system = seg.get("system", "").upper()
            if system:
                system_to_3d.setdefault(system, []).append(v)
            stem = _line_stem(seg.get("line_no", ""))
            if stem and len(stem) >= 4:
                stem_to_3d.setdefault(stem, []).append(v)
            for key in _semantic_keys(v):
                semantic_to_3d.setdefault(key, []).append(v)

        # __line_norm → ITEM metadata 對照。相同字串可能存在於不同 Path，
        # 因此不能只留一個 raw 值或把它們誤當成同一候選。
        norm_to_raw: Dict[str, str] = {}
        norm_to_metadata: Dict[str, List[dict]] = {}
        _meta_cols = [
            "__line_norm",
            "Raw_3D_PipeCode",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
        ]
        for _, _mrow in df_minus[_meta_cols].drop_duplicates().iterrows():
            _n = str(_mrow["__line_norm"]).strip()
            _r = str(_mrow["Raw_3D_PipeCode"]).strip()
            if _n and _r and _n not in norm_to_raw:
                norm_to_raw[_n] = _r
            if not _n:
                continue
            _meta = {
                "raw_3d": _r or _n,
                "path": str(_mrow.get("PipeNodePath", "")).strip(),
                "scope": str(_mrow.get("ScopeRoot", "")).strip(),
                "parent_area": str(_mrow.get("ParentArea", "")).strip(),
                "level": str(_mrow.get("PipeNodeLevel", "")).strip(),
            }
            _meta["item_id"] = candidate_item_id(_meta, dataset_revision)
            bucket = norm_to_metadata.setdefault(_n, [])
            if not any(old.get("item_id") == _meta["item_id"] for old in bucket):
                bucket.append(_meta)

        existing_item_owners: Dict[str, set[str]] = {}
        if merged is not None and not merged.empty:
            for _, owner_row in merged.iterrows():
                owner_payload = {
                    "raw_3d": str(owner_row.get("Raw_3D_PipeCode", "")).strip(),
                    "path": str(owner_row.get("PipeNodePath", "")).strip(),
                    "scope": str(owner_row.get("ScopeRoot", "")).strip(),
                    "parent_area": str(owner_row.get("ParentArea", "")).strip(),
                    "level": str(owner_row.get("PipeNodeLevel", "")).strip(),
                }
                owner_item_id = candidate_item_id(owner_payload, dataset_revision)
                if owner_item_id.startswith("ephemeral:"):
                    continue
                owner_raw = str(
                    owner_row.get("__pipe_raw", owner_row.get("管線編號", ""))
                ).strip()
                owner_family, _owner_events = normalize_line_v2(owner_raw)
                if owner_family:
                    existing_item_owners.setdefault(owner_item_id, set()).add(
                        owner_family.upper()
                    )

        def _add_candidate(
            bucket: list[dict],
            seen: set[str],
            iso_line: str,
            cand_3d: str,
            source_hint: str = "",
            min_score: float = 0.0,
            forced_score: float | None = None,
            forced_reason: str | None = None,
            raw_override: str | None = None,
            trace_override: str | None = None,
            metadata_override: dict | None = None,
            evidence_override: dict | None = None,
            auto_safe_override: bool | None = None,
            reason_codes_override: object = None,
        ) -> None:
            cand_3d = str(cand_3d).strip()
            if not cand_3d:
                return
            stripped_3d = _strip_size_segment(cand_3d)
            if forced_score is not None and forced_reason is not None:
                score = forced_score
                reason = forced_reason
            elif stripped_3d == iso_line:
                score = 0.97
                reason = "去尺寸段完全吻合"
            else:
                score, reason = _compute_segment_score(iso_line, cand_3d)
            if score < min_score:
                return
            if source_hint and source_hint not in reason:
                reason = f"{reason}; {source_hint}" if reason else source_hint
            comparison = build_match_evidence(
                iso_line,
                cand_3d,
                approved_punctuation_aliases=approved_punctuation_aliases,
            )
            base_evidence = dict(evidence_override or {})
            # Project-scoped comparison is authoritative for identity/symbol
            # classification; retrieval details remain as supporting evidence.
            base_evidence.update(comparison.to_dict())
            override_codes = reason_codes_override or []
            if isinstance(override_codes, str):
                override_codes = [
                    value.strip()
                    for value in override_codes.split(",")
                    if value.strip()
                ]
            # The fresh project-scoped comparison is authoritative for the
            # punctuation approval state.  Recall evidence may have been built
            # before the rule snapshot was applied.
            override_codes = [
                value
                for value in override_codes
                if value not in {
                    "punctuation_review_required",
                    "punctuation_alias_approved",
                }
            ]
            base_reason_codes: object = list(
                dict.fromkeys([*comparison.reason_codes, *list(override_codes)])
            )
            has_safety_block = any(
                code
                in {
                    "derived_stem_match",
                    "derived_stem_relation",
                    "structural_node",
                    "ownership_conflict",
                }
                for code in base_reason_codes
            )
            base_auto_safe = bool(comparison.auto_safe) and not has_safety_block
            metadata_items = (
                [dict(metadata_override)]
                if metadata_override
                else [dict(item) for item in norm_to_metadata.get(cand_3d, [])]
            )
            if not metadata_items:
                metadata_items = [{}]
            for metadata in metadata_items:
                raw_3d = (
                    raw_override
                    or str(metadata.get("raw_3d", "")).strip()
                    or norm_to_raw.get(cand_3d, cand_3d)
                )
                candidate_payload = {
                    "line_3d": cand_3d,
                    "raw_3d": raw_3d,
                    "path": str(metadata.get("path", "")).strip(),
                    "scope": str(metadata.get("scope", "")).strip(),
                    "parent_area": str(metadata.get("parent_area", "")).strip(),
                    "level": str(metadata.get("level", "")).strip(),
                }
                item_key = str(metadata.get("item_id", "")).strip() or candidate_item_id(
                    candidate_payload,
                    dataset_revision,
                )
                if item_key in seen:
                    continue
                seen.add(item_key)
                trace = trace_override or (
                    TraceBuilder()
                    .add("match", "fuzzy_candidate")
                    .add("iso_key", iso_line)
                    .add("line_3d", cand_3d)
                    .add("raw", raw_3d)
                    .add("path", candidate_payload["path"])
                    .add("score", f"{score:.2f}")
                    .add("reason", reason)
                    .build()
                )
                reason_codes = base_reason_codes or []
                if isinstance(reason_codes, str):
                    reason_codes = [
                        value.strip()
                        for value in reason_codes.split(",")
                        if value.strip()
                    ]
                iso_family, _iso_family_events = normalize_line_v2(iso_line)
                existing_owners = existing_item_owners.get(item_key, set())
                if item_key.startswith("ephemeral:"):
                    ownership_status = "unverifiable"
                elif existing_owners and iso_family.upper() not in existing_owners:
                    ownership_status = "claimed_by_other"
                    reason_codes = list(reason_codes) + ["ownership_conflict"]
                elif existing_owners:
                    ownership_status = "same_family"
                else:
                    ownership_status = "available"
                candidate_auto_safe = base_auto_safe and ownership_status in {
                    "available",
                    "same_family",
                }
                candidate_payload.update({
                    "item_id": item_key,
                    "score": score,
                    "reason": reason,
                    "trace": trace,
                    "evidence": dict(base_evidence),
                    "auto_safe": candidate_auto_safe,
                    "pair_auto_safe": candidate_auto_safe,
                    "reason_codes": list(dict.fromkeys(reason_codes)),
                    "ownership_status": ownership_status,
                    "ownership_owners": sorted(existing_owners),
                })
                bucket.append(candidate_payload)

        recall_candidates_by_iso: dict[str, list[dict]] = {}

        def _merge_recall_candidate(iso_key: str, candidate: dict) -> None:
            key = str(iso_key).strip()
            line_3d = str(candidate.get("line_3d", "")).strip()
            if not key or not line_3d:
                return
            candidate = dict(candidate)
            candidate.setdefault(
                "item_id", candidate_item_id(candidate, dataset_revision)
            )
            bucket = recall_candidates_by_iso.setdefault(key, [])
            for old in bucket:
                if str(old.get("item_id", "")).strip() == str(
                    candidate.get("item_id", "")
                ).strip():
                    if float(candidate.get("score", 0.0)) > float(
                        old.get("score", 0.0)
                    ):
                        old.update(candidate)
                    return
            bucket.append(candidate)
            bucket.sort(key=lambda item: -float(item.get("score", 0.0)))
            del bucket[10:]

        recall_path = os.path.join(base_dir, "candidates.csv")
        if os.path.exists(recall_path):
            try:
                _log(f"Phase4: 讀取 Step1 candidates.csv：{recall_path}")
                recall_df = pd.read_csv(
                    recall_path,
                    dtype=str,
                    encoding="utf-8-sig",
                    low_memory=False,
                ).fillna("")
                if "candidate_kind" in recall_df.columns:
                    recall_df = recall_df[
                        recall_df["candidate_kind"].astype(str).eq("iso_reverse_recall")
                    ].copy()
                if "iso_candidate" in recall_df.columns:
                    recall_df["__recall_iso_norm"] = recall_df["iso_candidate"].apply(
                        lambda value: normalize_line_v2(value)[0]
                    )
                    for iso_key, sub in recall_df.groupby(
                        "__recall_iso_norm",
                        sort=False,
                    ):
                        for _, crow in sub.iterrows():
                            line_3d = str(crow.get("normalized", "")).strip()
                            raw_3d = str(crow.get("raw", "")).strip()
                            if not line_3d:
                                continue
                            try:
                                score = float(str(crow.get("score", "0")).strip() or 0)
                            except Exception:
                                score = 0.0
                            recall_path_value = str(crow.get("Path", "")).strip()
                            recall_level_value = str(crow.get("Level", "")).strip()
                            recall_scope = parse_scope_context(
                                recall_path_value,
                                "___",
                                iso_match_key=line_3d,
                                raw_3d_pipe_code=raw_3d or line_3d,
                                level=recall_level_value,
                            )
                            try:
                                recall_evidence = json.loads(
                                    str(crow.get("evidence_json", "")).strip() or "{}"
                                )
                            except (TypeError, ValueError):
                                recall_evidence = {}
                            _merge_recall_candidate(str(iso_key).strip(), {
                                "line_3d": line_3d,
                                "raw_3d": raw_3d or line_3d,
                                "score": min(max(score, 0.0), 0.88),
                                "reason": str(crow.get("reason", "")).strip()
                                or "ISO 反向召回候選",
                                "trace": str(crow.get("trace_events", "")).strip(),
                                "path": str(crow.get("PipeNodePath", "")).strip()
                                or recall_scope["PipeNodePath"],
                                "scope": str(crow.get("ScopeRoot", "")).strip()
                                or recall_scope["ScopeRoot"],
                                "parent_area": str(crow.get("ParentArea", "")).strip()
                                or recall_scope["ParentArea"],
                                "level": recall_scope["PipeNodeLevel"],
                                "evidence": recall_evidence,
                                "auto_safe": str(crow.get("auto_safe", "")).strip()
                                in {"1", "true", "True"},
                                "reason_codes": str(crow.get("reason_codes", "")).strip(),
                            })
                    _log(
                        "Phase4: candidates.csv 反向召回涵蓋 "
                        f"{len(recall_candidates_by_iso)} 條 ISO"
                    )
            except Exception as exc:
                _log(f"Phase4: 讀取 ISO 反向召回候選失敗（略過）：{exc}")
        else:
            _log("Phase4: 找不到 candidates.csv，略過 Step1 反向候選檔。")

        def _normalize_first_try_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
            n_cols = min(len(chunk.columns), 5)
            chunk = chunk.iloc[:, :n_cols].copy()
            names = ["Path", "DisplayName", "Class", "Level"]
            if n_cols >= 5:
                names.append("PipelineId")
            chunk.columns = names
            if "PipelineId" not in chunk.columns:
                chunk["PipelineId"] = ""
            return chunk.fillna("")

        def _scan_first_try_reverse_recall(path: str) -> int:
            if not path or not os.path.exists(path):
                _log(f"Phase4: First_try 反向召回略過，檔案不存在：{path}")
                return 0
            iso_keys = {
                str(v).strip()
                for v in iso_still_unmatched["__line_norm"].astype(str).tolist()
                if str(v).strip()
            }
            if not iso_keys:
                _log("Phase4: First_try 反向召回略過，沒有未配對 ISO key。")
                return 0
            _log(
                "Phase4: 開始掃描 First_try 反向召回："
                f"{path}，ISO keys={len(iso_keys)}，chunksize=50000"
            )
            engine = IsoRecallEngine(iso_keys)
            found = 0
            scanned_rows = 0
            chunk_count = 0
            try:
                reader = pd.read_csv(
                    path,
                    dtype=str,
                    encoding="utf-8-sig",
                    low_memory=False,
                    on_bad_lines="skip",
                    chunksize=10000,
                )
                for chunk in reader:
                    chunk_count += 1
                    scanned_rows += len(chunk)
                    chunk = _normalize_first_try_chunk(chunk)
                    for _, first_row in chunk.iterrows():
                        for cand in engine.recall_row(
                            first_row,
                            max_candidates=5,
                            min_score=0.50,
                        ):
                            recall_candidate_path = str(
                                getattr(cand, "path", "")
                                or first_row.get("Path", "")
                            ).strip()
                            recall_candidate_level = str(
                                getattr(cand, "level", "")
                                or first_row.get("Level", "")
                            ).strip()
                            recall_scope = parse_scope_context(
                                recall_candidate_path,
                                "___",
                                iso_match_key=cand.normalized_3d,
                                raw_3d_pipe_code=cand.raw_3d,
                                level=recall_candidate_level,
                            )
                            _merge_recall_candidate(cand.iso_key, {
                                "line_3d": cand.normalized_3d,
                                "raw_3d": cand.raw_3d,
                                "score": cand.score,
                                "reason": cand.reason or "ISO 反向召回候選",
                                "trace": cand.trace,
                                "path": recall_scope["PipeNodePath"],
                                "scope": recall_scope["ScopeRoot"],
                                "parent_area": recall_scope["ParentArea"],
                                "level": recall_scope["PipeNodeLevel"],
                                "evidence": dict(getattr(cand, "evidence", {}) or {}),
                                "auto_safe": bool(getattr(cand, "auto_safe", False)),
                                "reason_codes": list(
                                    getattr(cand, "reason_codes", ()) or ()
                                ),
                            })
                            found += 1
                    _log(
                        "Phase4: First_try 反向召回進度："
                        f"已掃 {scanned_rows} 列，候選 {found} 筆"
                    )
            except Exception as exc:
                _log(f"Phase4: 掃描 First_try 反向召回失敗（略過）：{exc}")
                return 0
            _log(
                "Phase4: First_try 反向召回完成："
                f"掃描 {scanned_rows} 列，候選 {found} 筆"
            )
            return found

        first_try_to_scan = (
            first_try_path
            or os.path.join(base_dir, "First_try.csv")
        )
        recall_scan_count = _scan_first_try_reverse_recall(first_try_to_scan)
        if recall_scan_count:
            hit_iso_count = sum(
                1 for items in recall_candidates_by_iso.values() if items
            )
            _log(
                "Phase4: ISO 反向召回掃描 First_try，"
                f"候選 {recall_scan_count} 筆，涵蓋 {hit_iso_count} 條 ISO"
            )
        else:
            _log("Phase4: First_try 反向召回未找到候選。")

        self.fuzzy_unmatched = []
        _log(
            "Phase4: 建立模糊比對清單："
            f"ISO 未配對 {len(iso_still_unmatched)} 條，"
            f"3D 索引 {len(all_3d_lines)} 條，"
            f"反向召回 ISO {len(recall_candidates_by_iso)} 條"
        )
        fuzzy_total = len(iso_still_unmatched)
        for fuzzy_index, (_, row) in enumerate(
            iso_still_unmatched.iterrows(),
            start=1,
        ):
            iso_line = str(row["__line_norm"]).strip()
            iso_spool = str(row.get("流水號", "")).strip()
            if not iso_line:
                continue
            iso_metadata = {
                str(column): row.get(column, "")
                for column in _iso_original_cols
                if not str(column).startswith("__")
            }
            iso_parts = _split_line_parts(iso_line)
            pfx = "-".join(iso_parts[:2]) if len(iso_parts) >= 2 else iso_line
            iso_seg = _parse_segments(iso_line)
            iso_system = iso_seg.get("system", "").upper()
            iso_stem = _line_stem(iso_seg.get("line_no", ""))

            candidates = []
            seen_3d: set[str] = set()

            # ── 第一輪：語意 key 相同（忽略 leading size，line_no 可去尾碼）──
            for key in _semantic_keys(iso_line):
                for cand_3d in semantic_to_3d.get(key, []):
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        cand_3d,
                        source_hint="語意索引命中",
                    )

            # ── 第二輪：舊前綴 (system-line_no) 相同的候選 ──
            for cand_3d in prefix_to_3d.get(pfx, []):
                _add_candidate(
                    candidates,
                    seen_3d,
                    iso_line,
                    cand_3d,
                    source_hint="前綴索引命中",
                )

            # ── 第三輪：同系統但不同編號的候選 ──
            if iso_system and len(candidates) < 5:
                for cand_3d in system_to_3d.get(iso_system, []):
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        cand_3d,
                        source_hint="同系統候選",
                        min_score=0.20,
                    )

            # ── 第四輪：同 line_no 主體，允許系統/尺寸不同，讓人工看得到可能性 ──
            if iso_stem and len(iso_stem) >= 4 and len(candidates) < 5:
                for cand_3d in stem_to_3d.get(iso_stem, []):
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        cand_3d,
                        source_hint="編號主體候選",
                        min_score=0.18,
                    )

            # ── 第四點五輪：Step1 candidates.csv 的 ISO 反向召回候選 ──
            if len(candidates) < 8:
                for recall in recall_candidates_by_iso.get(iso_line, []):
                    recall_metadata = {
                        "item_id": recall.get("item_id", ""),
                        "raw_3d": recall.get("raw_3d", ""),
                        "path": recall.get("path", ""),
                        "scope": recall.get("scope", ""),
                        "parent_area": recall.get("parent_area", ""),
                        "level": recall.get("level", ""),
                    }
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        recall.get("line_3d", ""),
                        source_hint="ISO 反向召回",
                        forced_score=float(recall.get("score", 0.0)),
                        forced_reason=str(recall.get("reason", "")),
                        raw_override=str(recall.get("raw_3d", "")),
                        trace_override=str(recall.get("trace", "")),
                        metadata_override=recall_metadata,
                        evidence_override=dict(recall.get("evidence", {}) or {}),
                        auto_safe_override=bool(recall.get("auto_safe", False)),
                        reason_codes_override=recall.get("reason_codes", []),
                    )

            # ── 第五輪：全文搜索（前綴不同的候選）──
            if len(candidates) < 3:
                for v in all_3d_lines:
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        v,
                        source_hint="全文相似候選",
                        min_score=0.35,
                    )

            # ── 最後保底：完全沒有候選時，列出低信心全文相似 top N 供排查 ──
            if not candidates:
                fallback_scored: list[tuple[float, str, str]] = []
                for v in all_3d_lines:
                    seg_score, seg_reason = _compute_segment_score(iso_line, v)
                    text_score = _compute_similarity(iso_line, v) * 0.6
                    score = round(max(seg_score, text_score), 4)
                    if score >= 0.25:
                        fallback_scored.append((
                            score,
                            v,
                            f"{seg_reason}; 低信心全文相似候選",
                        ))
                fallback_scored.sort(key=lambda item: item[0], reverse=True)
                for score, v, reason in fallback_scored[:5]:
                    _add_candidate(
                        candidates,
                        seen_3d,
                        iso_line,
                        v,
                        forced_score=score,
                        forced_reason=reason,
                    )

            candidates.sort(key=lambda c: -c["score"])
            candidates = annotate_candidate_families(candidates[:15])
            self.fuzzy_unmatched.append({
                "iso_line": iso_line,
                "iso_spool": iso_spool,
                "iso_metadata": iso_metadata,
                "candidates": candidates,
            })
            if fuzzy_index == 1 or fuzzy_index % 25 == 0 or fuzzy_index == fuzzy_total:
                _log(
                    "Phase4: 模糊候選整理進度："
                    f"已處理 {fuzzy_index}/{fuzzy_total} 條 ISO"
                )

        # Final automation gate: scores only rank.  Reciprocal ownership is
        # evaluated per ISO family, so two spool rows from the same line do not
        # incorrectly block each other.
        annotate_family_aware_safety(self.fuzzy_unmatched)

        empty_candidate_count = sum(
            1 for item in self.fuzzy_unmatched if not item.get("candidates")
        )
        if self.fuzzy_unmatched:
            _log(
                "Phase4: 模糊比對清單完成："
                f"{len(self.fuzzy_unmatched)} 條，"
                f"其中 {empty_candidate_count} 條沒有任何候選"
            )

        if self.fuzzy_unmatched:
            _log(f"模糊比對候選：{len(self.fuzzy_unmatched)} 條 ISO 待手動確認")
            for item in self.fuzzy_unmatched[:3]:
                top = item["candidates"][0] if item["candidates"] else None
                top_str = f"最佳={top['line_3d']}({top['score']:.0%})" if top else "無候選"
                _log(f"  ISO=[{item['iso_line']}] {top_str}")

        # --- 寬鬆有家但無嚴謹 ISO 的 3D 線：補入 iso_match ---
        try:
            # 讀取 pipe_code_pattern，建立寬鬆 key（同 check_minus_coverage 邏輯）
            config_path = os.path.join(base_dir, DEFAULT_CONFIG_FILENAME)
            pattern = (
                load_pipe_pattern(config_path)
                if os.path.exists(config_path)
                else {}
            )

            def _build_loose_key_from_norm(line_norm: str, roles: Optional[List[str]] = None) -> str:
                if not line_norm or not pattern:
                    return ""
                seps = pattern.get("separators") or ["-"]
                sep = str(seps[0]) if seps else "-"
                parts = str(line_norm).split(sep)
                if not parts:
                    return ""
                segments_def = pattern.get("segments") or []
                role_to_indices = {}
                for seg in segments_def:
                    try:
                        idx = int(seg.get("index"))
                    except Exception:
                        continue
                    role = (seg.get("role") or "").strip()
                    if not role:
                        continue
                    role_to_indices.setdefault(role, []).append(idx)

                use_roles = roles or ["system", "line_no"]
                values: List[str] = []
                for role in use_roles:
                    for idx in role_to_indices.get(role, []):
                        if 0 <= idx < len(parts):
                            v = str(parts[idx]).strip()
                            if v:
                                values.append(v)
                return "|".join(values) if values else ""

            # 先計算 ISO / minus 的寬鬆 key
            iso_df["__loose_key"] = iso_df["__line_norm"].apply(_build_loose_key_from_norm)
            df_minus["__loose_key"] = df_minus["__line_norm"].apply(_build_loose_key_from_norm)

            # 嚴謹已匹配到 ISO 的 minus key
            strict_minus_keys = set(merged["ISO_Match_Key"].astype(str).tolist())

            # 找出：尚未嚴謹 match，但在对鬆 key 上有家族的 minus 列
            minus_loose_only = df_minus[
                (~df_minus["ISO_Match_Key"].astype(str).isin(strict_minus_keys))
                & df_minus["__loose_key"].astype(str).isin(
                    {k for k in iso_df["__loose_key"].astype(str).tolist() if k}
                )
            ].copy()

            if not minus_loose_only.empty:
                _log(
                    f"發現 {len(minus_loose_only)} 條 3D 線為『僅寬鬆有家族』，將補入 iso_match。"
                )
                _log(
                    "minus_loose_only sample (前 3 筆 ISO_Match_Key, __loose_key): "
                    + ", ".join(
                        [
                            f"{r['ISO_Match_Key']}|{r['__loose_key']}"
                            for _, r in minus_loose_only.head(3).iterrows()
                        ]
                    )
                )

                # 以 loose_key 找對應 ISO 代表列（每個 loose_key 取第一筆 ISO 作代表）
                iso_loose_groups = (
                    iso_df[iso_df["__loose_key"].astype(str) != ""]
                    .sort_values(by=["__loose_key"])
                    .drop_duplicates(subset=["__loose_key"], keep="first")
                )

                # 取代表 ISO 列時，保留 ISO 目前已存在於 merged 的所有欄位
                iso_cols_for_loose = [
                    c
                    for c in merged.columns
                    if c
                    not in [
                        "ISO_Match_Key",
                        "Raw_3D_PipeCode",
                        "群組",
                        "MatchType",
                    ]
                    and c in iso_df.columns
                ]

                minus_loose_only = minus_loose_only.merge(
                    iso_loose_groups[["__loose_key"] + iso_cols_for_loose],
                    how="left",
                    left_on="__loose_key",
                    right_on="__loose_key",
                    suffixes=("_3d", "_iso"),
                )

                # 準備補充列：
                # - 以代表 ISO 列的 header 為模板（來自 iso_cols_for_loose）
                # - 覆寫 3D 端的 ISO_Match_Key / Raw_3D_PipeCode
                # - 群組後面會統一重算
                add_rows = []
                for _, r in minus_loose_only.iterrows():
                    row: dict = {}
                    # 先複製 ISO 端欄位值
                    for col in iso_cols_for_loose:
                        row[col] = r.get(col, "")

                    # 3D 相關欄位覆寫
                    row["管線編號"] = r.get("__pipe_raw", "")
                    row["流水號"] = r.get("流水號", "")
                    row["ISO_Match_Key"] = r.get("ISO_Match_Key", "")
                    row["Raw_3D_PipeCode"] = r.get("Raw_3D_PipeCode", "")
                    row["MatchSource"] = r.get("MatchSource", "")
                    row["ConfidencePrimary"] = r.get("ConfidencePrimary", "")
                    row["IdentityReason"] = r.get("IdentityReason", "")
                    row["CandidateCount"] = r.get("CandidateCount", "")
                    row["CandidateTrace"] = r.get("CandidateTrace", "")
                    row["PipeNodePath"] = r.get("PipeNodePath", "")
                    row["ScopeRoot"] = r.get("ScopeRoot", "")
                    row["ParentArea"] = r.get("ParentArea", "")
                    row["PipeNodeLevel"] = r.get("PipeNodeLevel", "")

                    # 群組稍後由 group_map 重算，這裡先給空
                    row["群組"] = ""
                    row["MatchType"] = "loose_only"

                    add_rows.append(row)

                if add_rows:
                    add_df = pd.DataFrame(add_rows)
                    _log(
                        f"準備補入 {len(add_df)} 筆 loose_only 至 merged，補入前 merged.columns = {list(merged.columns)}"
                    )
                    _log(
                        "loose_only add_df sample (前 3 筆 管線編號, 流水號, ISO_Match_Key, MatchType): "
                        + ", ".join(
                            [
                                f"{r['管線編號']}|{r['流水號']}|{r['ISO_Match_Key']}|{r['MatchType']}"
                                for _, r in add_df.head(3).iterrows()
                            ]
                        )
                    )
                    merged = pd.concat([merged, add_df], ignore_index=True)
                    _log(
                        f"補入後 merged.rows = {len(merged)}，merged.columns = {list(merged.columns)}"
                    )
        except Exception as e:
            _log(f"[Step3] 補充寬鬆家族 3D 線到 iso_match 時發生錯誤（略過）：{e}")

        _log(f"merged rows = {len(merged)} (key={used_key_type})")
        _log("merged sample (前 5 筆 管線編號, 流水號, ISO_Match_Key):")
        for _, r in merged.head(5).iterrows():
            pipe_show = r.get("__pipe_raw", r.get("__pipe_base", ""))
            _log(f"  {pipe_show} | {r['流水號']} | {r['ISO_Match_Key']}")

        extra_cols = ["系統", "材質", "保溫", "試壓媒介", "預製圖", "發包分類"]
        for c in extra_cols:
            if c not in merged.columns:
                merged[c] = ""

        merged["管線編號"] = merged["__pipe_raw"]

        group_map = {}
        for pipe, sub in merged.groupby("管線編號", sort=False):
            sns = CommonUtils.unique_preserve(sub["流水號"].tolist())
            if not sns:
                continue
            if len(sns) == 1:
                grp_name = f"流水號{sns[0]}"
            else:
                grp_name = "_".join([f"流水號{s}" for s in sns])
            group_map[pipe] = grp_name

        merged["群組"] = merged["管線編號"].map(group_map).fillna("")
        _log(f"group_map size = {len(group_map)}")

        for c in ["PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel"]:
            if c not in merged.columns:
                merged[c] = ""
            merged[c] = merged[c].astype(str).str.strip()

        def _unique_nonempty(sub: pd.DataFrame, col: str) -> list[str]:
            if col not in sub.columns:
                return []
            return CommonUtils.unique_preserve(
                [
                    str(v).strip()
                    for v in sub[col].tolist()
                    if str(v).strip()
                ]
            )

        def _collision_dimension(sub: pd.DataFrame) -> tuple[str, list[str]]:
            dimensions = [
                ("ScopeRoot", _unique_nonempty(sub, "ScopeRoot")),
                ("ParentArea", _unique_nonempty(sub, "ParentArea")),
                ("PipeNodeLevel", _unique_nonempty(sub, "PipeNodeLevel")),
                ("Raw_3D_PipeCode", _unique_nonempty(sub, "Raw_3D_PipeCode")),
                ("PipeNodePath", _unique_nonempty(sub, "PipeNodePath")),
            ]
            for name, values in dimensions:
                if len(values) > 1:
                    return name, values
            for name, values in dimensions:
                if values:
                    return name, values
            return "", []

        collision_info: Dict[str, Dict[str, object]] = {}
        if "流水號" in merged.columns:
            for spool, sub in merged.groupby("流水號", sort=False):
                spool_key = str(spool).strip()
                if not spool_key:
                    continue
                dimension, parents = _collision_dimension(sub)
                collision_info[spool_key] = {
                    "count": len(parents),
                    "parents": (
                        f"{dimension}: " + " | ".join(parents)
                        if dimension and parents
                        else ""
                    ),
                    "needs": 1 if len(parents) > 1 else 0,
                }

        def _collision_value(spool: object, key: str) -> object:
            info = collision_info.get(str(spool).strip(), {})
            return info.get(key, 0 if key != "parents" else "")

        merged["CollisionCount"] = merged["流水號"].apply(
            lambda v: _collision_value(v, "count")
        )
        merged["CollisionParents"] = merged["流水號"].apply(
            lambda v: _collision_value(v, "parents")
        )
        merged["NeedsDecision"] = merged["流水號"].apply(
            lambda v: _collision_value(v, "needs")
        )
        needs_count = sum(1 for info in collision_info.values() if info.get("needs"))
        _log(f"collision groups needing decision = {needs_count}")

        if "IdentityReason" not in merged.columns:
            if "IdentityReason_y" in merged.columns:
                merged["IdentityReason"] = merged["IdentityReason_y"]
            elif "IdentityReason_x" in merged.columns:
                merged["IdentityReason"] = merged["IdentityReason_x"]
            else:
                merged["IdentityReason"] = ""
        if "__norm_trace" not in merged.columns:
            merged["__norm_trace"] = ""
        merged["IdentityReason"] = merged.apply(
            lambda r: append_trace(
                append_trace(r.get("IdentityReason", ""), r.get("__norm_trace", "")),
                _match_trace_for_row(r),
            ),
            axis=1,
        )

        full_out_cols = [
            "管線編號",
            "流水號",
            "ISO_Match_Key",
            "Raw_3D_PipeCode",
            "MatchSource",
            "ConfidencePrimary",
            "IdentityReason",
            "CandidateCount",
            "CandidateTrace",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
            "系統",
            "材質",
            "保溫",
            "試壓媒介",
            "預製圖",
            "發包分類",
            "群組",
            "MatchType",
            "CollisionCount",
            "CollisionParents",
            "NeedsDecision",
        ]
        # 加入 ISO_LIST 的所有原始欄位（去重、保留順序）
        for c in _iso_original_cols:
            if c not in full_out_cols:
                full_out_cols.append(c)
        for c in full_out_cols:
            if c not in merged.columns:
                merged[c] = ""

        if limit_iso_cols:
            base_cols = [
                "管線編號",
                "流水號",
                "ISO_Match_Key",
                "Raw_3D_PipeCode",
                "ScopeRoot",
                "ParentArea",
                "群組",
                "CollisionCount",
                "CollisionParents",
                "NeedsDecision",
            ]
            headers = extra_iso_headers or []
            keep: List[str] = []
            for col in base_cols + headers:
                if col in merged.columns and col not in keep:
                    keep.append(col)
            if "發包分類" in merged.columns and "發包分類" not in keep:
                keep.append("發包分類")
            # 無論如何都保留 MatchType，方便後續判讀嚴謹/寬鬆家族
            if "MatchType" in merged.columns and "MatchType" not in keep:
                keep.append("MatchType")
            result = merged[keep].copy()
        else:
            result = merged[full_out_cols].copy()
        _log(f"result rows (要寫進 iso_match.xlsx) = {len(result)}")
        _log(f"result columns = {list(result.columns)}")
        if "MatchType" in result.columns:
            mt_values = sorted({str(v) for v in result["MatchType"].tolist()})
        else:
            mt_values = []
        _log("result MatchType unique = " + ", ".join(mt_values))
        _log(
            "result head sample (前 3 筆 管線編號, 流水號, ISO_Match_Key, MatchType): "
            + ", ".join(
                [
                    f"{r.get('管線編號','')}|{r.get('流水號','')}|{r.get('ISO_Match_Key','')}|{r.get('MatchType','')}"  # type: ignore[index]
                    for _, r in result.head(3).iterrows()
                ]
            )
        )

        _log(f"即將寫出 iso_match.xlsx 至：{iso_output_path}")
        with pd.ExcelWriter(iso_output_path, engine="openpyxl") as writer:
            result.to_excel(writer, index=False, sheet_name="結果")
        _log(f"已寫出 iso_match.xlsx：{iso_output_path}")
        # 產生 ISO 覆蓋檢查報表：哪些 ISO 管線沒有在 minus 中找到家
        try:
            cov_path = self.check_iso_coverage(
                base_dir=base_dir,
                minus_csv_path=minus_csv_path,
                iso_list_path=iso_list_path,
                iso_sheet_name=sheet_to_use,
                pipe_col_override=pipe_col,
                spool_col_override=spool_col,
            )
            _log(f"已額外輸出 ISO 覆蓋檢查報表：{cov_path}")
        except Exception as e:
            _log(f"[Coverage] 產生 ISO 覆蓋檢查報表時發生錯誤（略過，不影響主流程）：{e}")

        # 產生 minus 覆蓋檢查報表：哪些 3D ISO_Match_Key 沒有任何 ISO 對應
        try:
            minus_cov_path = self.check_minus_coverage(
                base_dir=base_dir,
                minus_csv_path=minus_csv_path,
                iso_list_path=iso_list_path,
                iso_sheet_name=sheet_to_use,
                pipe_col_override=pipe_col,
                loose_join_roles=None,
            )
            _log(f"已額外輸出 3D 覆蓋檢查報表：{minus_cov_path}")
        except Exception as e:
            _log(f"[MinusCoverage] 產生 3D 覆蓋檢查報表時發生錯誤（略過，不影響主流程）：{e}")

        return len(result)

    # ── 模糊比對：使用者手動選擇後，追加到 iso_match.xlsx ──

    def apply_fuzzy_selections(
        self,
        iso_match_path: str,
        selections: List[Dict],
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> int:
        """將使用者手動確認的模糊配對追加至 iso_match.xlsx。

        Parameters
        ----------
        iso_match_path : str
            iso_match.xlsx 完整路徑。
        selections : list[dict]
            每筆至少為 ``{"iso_line": str, "iso_spool": str, "line_3d": str}``。
            若含 ``score`` / ``reason`` / ``trace`` / ``source``，會一併寫入
            ``MatchScore``、``IdentityReason`` 與 ``CandidateTrace``。
        log_fn : callable, optional
            日誌回呼。

        Returns
        -------
        int
            新追加的筆數。
        """
        def _log(msg: str) -> None:
            if log_fn:
                log_fn(msg)
            else:
                print(msg)

        if not selections:
            return 0

        # 讀取現有 iso_match
        try:
            existing = pd.read_excel(
                iso_match_path, sheet_name="結果", dtype=str, engine="openpyxl"
            ).fillna("")
        except Exception:
            existing = pd.DataFrame()

        cols = list(existing.columns) if len(existing) > 0 else [
            "管線編號", "流水號", "ISO_Match_Key", "Raw_3D_PipeCode", "群組", "MatchType",
        ]
        for required_col in [
            "IdentityReason",
            "CandidateTrace",
            "MatchScore",
            "MatchSource",
            "ConfidencePrimary",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
            "NeedsDecision",
            "DecisionState",
            "DecisionSource",
            "EvidenceClass",
            "ReasonCodes",
        ]:
            if required_col not in cols:
                cols.append(required_col)

        new_rows = []
        for sel in selections:
            row: dict = {c: "" for c in cols}
            iso_metadata = sel.get("iso_metadata", {})
            if isinstance(iso_metadata, dict):
                for column, value in iso_metadata.items():
                    column_name = str(column).strip()
                    if column_name and not column_name.startswith("__"):
                        row[column_name] = value

            # Matching fields are authoritative and must override any
            # same-named values carried from the original ISO row.
            row["管線編號"] = sel.get("iso_line", "")
            row["流水號"] = sel.get("iso_spool", "")
            row["ISO_Match_Key"] = sel.get("line_3d", "")
            row["Raw_3D_PipeCode"] = sel.get("raw_3d") or sel.get("line_3d", "")
            row["MatchType"] = "fuzzy_manual"
            row["PipeNodePath"] = sel.get("path") or sel.get("PipeNodePath", "")
            row["ScopeRoot"] = sel.get("scope") or sel.get("ScopeRoot", "")
            row["ParentArea"] = sel.get("parent_area") or sel.get("ParentArea", "")
            row["PipeNodeLevel"] = sel.get("level") or sel.get("PipeNodeLevel", "")
            row["NeedsDecision"] = "0"
            row["DecisionState"] = "committed"
            row["DecisionSource"] = str(
                sel.get("decision_source") or "human_workbench"
            )
            evidence = sel.get("evidence", {})
            if not isinstance(evidence, dict):
                evidence = {}
            row["EvidenceClass"] = str(
                evidence.get("classification")
                or sel.get("evidence_class", "")
            )
            reason_codes = sel.get("reason_codes") or evidence.get("reason_codes") or []
            if isinstance(reason_codes, str):
                reason_codes = [reason_codes]
            row["ReasonCodes"] = ",".join(
                str(code).strip() for code in reason_codes if str(code).strip()
            )
            try:
                score_value = float(str(sel.get("score", "")).strip())
            except Exception:
                score_value = float(_MATCH_TYPE_SCORES["fuzzy_manual"])
            score_text = f"{max(0.0, min(score_value, 1.0)):.2f}"
            reason = str(sel.get("reason", "")).strip() or _MATCH_TYPE_REASONS[
                "fuzzy_manual"
            ]
            source = str(sel.get("source", "")).strip() or "fuzzy_manual"
            candidate_trace = str(sel.get("trace", "")).strip()
            row["MatchScore"] = score_text
            row["ConfidencePrimary"] = score_text
            row["MatchSource"] = source
            manual_trace = (
                TraceBuilder()
                .add("match", "fuzzy_manual")
                .add("iso_line", row["管線編號"])
                .add("line_3d", row["ISO_Match_Key"])
                .add("raw", row["Raw_3D_PipeCode"])
                .add("score", score_text)
                .add("source", source)
                .add("reason", reason)
                .build()
            )
            trace = append_trace(candidate_trace, manual_trace)
            row["IdentityReason"] = trace
            row["CandidateTrace"] = trace
            new_rows.append(row)

        if not new_rows:
            return 0

        add_df = pd.DataFrame(new_rows)
        result = pd.concat([existing, add_df], ignore_index=True)

        # 重算群組
        group_map: Dict[str, str] = {}
        for pipe, sub in result.groupby("管線編號", sort=False):
            sns = [s for s in sub["流水號"].tolist() if str(s).strip()]
            seen: list = []
            for s in sns:
                if s not in seen:
                    seen.append(s)
            if not seen:
                continue
            if len(seen) == 1:
                group_map[str(pipe)] = f"流水號{seen[0]}"
            else:
                group_map[str(pipe)] = "_".join([f"流水號{s}" for s in seen])
        if "群組" in result.columns:
            result["群組"] = result["管線編號"].map(group_map).fillna("")

        with pd.ExcelWriter(iso_match_path, engine="openpyxl") as writer:
            result.to_excel(writer, index=False, sheet_name="結果")

        _log(f"[模糊比對] 已追加 {len(new_rows)} 筆至 iso_match.xlsx，現共 {len(result)} 筆")
        return len(new_rows)
