# -*- coding: utf-8 -*-
"""ISO 清單比對：ISO LIST → iso_match.xlsx

重構為 `IsoMatcher` 類別。
"""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from utils.utils_common import CommonUtils
from utils.pipe_parser import load_pipe_pattern, DEFAULT_CONFIG_FILENAME

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


def _parse_segments(line: str) -> dict[str, str]:
    """將管線編號拆成 segment dict。

    支援 5 段 ``system-line_no-size-class-insulation``
    或 4 段 ``system-line_no-class-insulation`` (ISO 常缺尺寸段)。
    回傳 ``{"system": ..., "line_no": ..., "size": ..., ...}``。
    """
    clean = _SUPPORTS_RE.sub("", line).strip().upper()
    parts = clean.split("-")
    result: dict[str, str] = {}
    if len(parts) >= 5 and _SIZE_RE.match(parts[2]):
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

    if sys_match:
        score += _SEG_WEIGHTS["system"]
        reasons.append(f"系統={seg_iso['system']}")
    if lineno_match:
        score += _SEG_WEIGHTS["line_no"]
        reasons.append(f"編號={seg_iso['line_no']}")
    if sys_match and lineno_match:
        score += _SEG_WEIGHTS["combo"]
        reasons.append("系統+編號同時吻合(+加成)")

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
        """檢查 ISO LIST 每一列管線是否能在 minus_2 的 Line_combined 中找到家。

        - 讀取 123_minus_2.csv（若不存在則退回 123_minus_1.csv）。
        - 對 minus 的 Line_combined 與 ISO 的管線欄位都套用 CommonUtils.normalize_line。
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

        if "Line_combined" not in df_minus.columns and "Line combined" in df_minus.columns:
            df_minus = df_minus.rename(columns={"Line combined": "Line_combined"})
        if "Line_combined" not in df_minus.columns:
            raise ValueError(
                "[Coverage] minus 檔缺少欄位『Line_combined』，請確認先執行 Step1/Step2。"
            )

        df_minus["__line_norm"] = df_minus["Line_combined"].astype(str).apply(
            CommonUtils.normalize_line
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

        if iso_sheet_name and iso_sheet_name in xls.sheet_names:
            sheet_to_use = iso_sheet_name
        else:
            sheet_to_use = (
                "DWG NO.ALL" if "DWG NO.ALL" in xls.sheet_names else xls.sheet_names[0]
            )

        iso_df = pd.read_excel(xls, sheet_name=sheet_to_use, dtype=str).fillna("")

        spool_col: str | None = None
        if spool_col_override and spool_col_override in iso_df.columns:
            spool_col = spool_col_override
        if spool_col is None:
            for cand in ["流水號", "Spool", "SPOOL"]:
                if cand in iso_df.columns:
                    spool_col = cand
                    break
        if spool_col is None:
            iso_df["流水號"] = ""
            spool_col = "流水號"

        pipe_col: str | None = None
        if pipe_col_override and pipe_col_override in iso_df.columns:
            pipe_col = pipe_col_override
        if pipe_col is None:
            if "管線編號" in iso_df.columns:
                pipe_col = "管線編號"
            else:
                for c in iso_df.columns:
                    if "line" in str(c).lower():
                        pipe_col = c
                        break
        if pipe_col is None:
            raise ValueError(
                "[Coverage] ISO 清單找不到『管線編號』或名稱中含 'line' 的欄位，"
                "請檢查 ISO 欄位名稱，或在 GUI 指定管線欄位名。"
            )

        cov = pd.DataFrame()
        cov["管線編號"] = iso_df[pipe_col].astype(str).str.strip()
        cov["流水號"] = iso_df[spool_col].astype(str).str.strip()
        cov["line_norm"] = cov["管線編號"].apply(CommonUtils.normalize_line)
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
        """檢查 minus_2 的每一條 Line_combined 是否至少有一列 ISO 管線編號對應。

        這是從 3D 身分證的角度看 ISO 覆蓋率：
        - minus_2 端：使用 Line_combined → normalize 後成 minus_line_norm。
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

        if "Line_combined" not in df_minus.columns and "Line combined" in df_minus.columns:
            df_minus = df_minus.rename(columns={"Line combined": "Line_combined"})
        if "Line_combined" not in df_minus.columns:
            raise ValueError(
                "[MinusCoverage] minus 檔缺少欄位『Line_combined』，請確認先執行 Step1/Step2。"
            )

        df_minus["Line_combined"] = df_minus["Line_combined"].astype(str).str.strip()
        df_minus["line_norm"] = df_minus["Line_combined"].apply(CommonUtils.normalize_line)

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

        if iso_sheet_name and iso_sheet_name in xls.sheet_names:
            sheet_to_use = iso_sheet_name
        else:
            sheet_to_use = (
                "DWG NO.ALL" if "DWG NO.ALL" in xls.sheet_names else xls.sheet_names[0]
            )

        iso_df = pd.read_excel(xls, sheet_name=sheet_to_use, dtype=str).fillna("")

        pipe_col: str | None = None
        if pipe_col_override and pipe_col_override in iso_df.columns:
            pipe_col = pipe_col_override
        if pipe_col is None:
            if "管線編號" in iso_df.columns:
                pipe_col = "管線編號"
            else:
                for c in iso_df.columns:
                    if "line" in str(c).lower():
                        pipe_col = c
                        break
        if pipe_col is None:
            raise ValueError(
                "[MinusCoverage] ISO 清單找不到『管線編號』或名稱中含 'line' 的欄位，"
                "請檢查 ISO 欄位名稱，或在 GUI 指定管線欄位名。"
            )

        iso_df["pipe_raw"] = iso_df[pipe_col].astype(str).str.strip()
        iso_df["line_norm"] = iso_df["pipe_raw"].apply(CommonUtils.normalize_line)
        iso_set = set(iso_df["line_norm"].tolist())

        # 嚴謹比對：完整標準化字串 1:1 覆蓋
        minus_cov = df_minus[["Line_combined", "line_norm"]].drop_duplicates().copy()
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
            f"[MinusCoverage] 已輸出 minus_2 覆蓋檢查報表，共 {len(minus_cov)} 條 Line_combined，"
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
    ) -> int:
        def _log(msg: str) -> None:
            if log_fn is not None:
                log_fn(msg)
            else:
                print(msg)

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

        if "Line_combined" not in df_minus.columns and "Line combined" in df_minus.columns:
            df_minus = df_minus.rename(columns={"Line combined": "Line_combined"})

        if "Line_combined" not in df_minus.columns:
            raise ValueError(
                "[Step3] 123_minus_2.csv / 123_minus_1.csv 缺少欄位『Line_combined』，"
                "請確認是否有先執行 Step1/Step2 並使用新版程式產生。"
            )

        if "Raw_last" not in df_minus.columns:
            df_minus["Raw_last"] = ""
        df_minus["Raw_last"] = df_minus["Raw_last"].astype(str).str.strip()
        df_minus["Line_combined"] = (
            df_minus["Line_combined"].astype(str).str.strip()
        )
        df_minus["__line_norm"] = df_minus["Line_combined"].apply(
            CommonUtils.normalize_line
        )

        _log("=== run_pipeline Step3 LOG ===")
        _log(f"df_minus rows = {len(df_minus)}")
        _log(f"df_minus columns = {list(df_minus.columns)}")
        _log(
            "Line_combined sample (前 5 筆標準化前): "
            + ", ".join(df_minus["Line_combined"].head(5).tolist())
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

        sheet_to_use: str
        if iso_sheet_name:
            if iso_sheet_name in xls.sheet_names:
                sheet_to_use = iso_sheet_name
            else:
                raise ValueError(
                    "[Step3] ISO 檔案中找不到指定工作表："
                    f"{iso_sheet_name}，可用工作表：{xls.sheet_names}"
                )
        else:
            if "DWG NO.ALL" in xls.sheet_names:
                sheet_to_use = "DWG NO.ALL"
            else:
                sheet_to_use = xls.sheet_names[0]
        _log(f"使用工作表：{sheet_to_use}")

        try:
            iso_df = pd.read_excel(
                xls, sheet_name=sheet_to_use, dtype=str
            ).fillna("")
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

        spool_col: str | None = None
        if spool_col_override:
            if spool_col_override in iso_df.columns:
                spool_col = spool_col_override
            else:
                raise ValueError(
                    "[Step3] ISO 工作表找不到使用者指定的流水號欄位："
                    f"{spool_col_override}，請確認欄位名稱與大小寫。"
                )
        if spool_col is None:
            for cand in ["流水號", "Spool", "SPOOL"]:
                if cand in iso_df.columns:
                    spool_col = cand
                    break
        if spool_col is None:
            iso_df["流水號"] = ""
            spool_col = "流水號"

        pipe_col: str | None = None
        if pipe_col_override:
            if pipe_col_override in iso_df.columns:
                pipe_col = pipe_col_override
            else:
                raise ValueError(
                    "[Step3] ISO 工作表找不到使用者指定的管線編號欄位："
                    f"{pipe_col_override}，請確認欄位名稱與大小寫。"
                )
        if pipe_col is None:
            if "管線編號" in iso_df.columns:
                pipe_col = "管線編號"
            else:
                for c in iso_df.columns:
                    if "line" in str(c).lower():
                        pipe_col = c
                        break
        if pipe_col is None:
            raise ValueError(
                "[Step3] ISO 清單找不到『管線編號』或名稱中含 'line' 的欄位，"
                "請檢查 ISO 欄位名稱，或在 GUI 指定管線欄位名。"
            )

        iso_df["__pipe_raw"] = iso_df[pipe_col].astype(str).str.strip()
        iso_df["流水號"] = iso_df[spool_col].astype(str).str.strip()
        iso_df["__line_norm"] = iso_df["__pipe_raw"].apply(
            CommonUtils.normalize_line
        )

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

        # ── Phase 1: 嚴謹比對 ──
        if len(iso_keep) > 0:
            minus_map = df_minus[
                ["__line_norm", "Line_combined", "Raw_last"]
            ].drop_duplicates()
            merged = iso_keep.merge(minus_map, on="__line_norm", how="left")
            merged["MatchType"] = "strict"
            used_key_type = "primary"
            _log(f"Phase1 strict merged rows = {len(merged)}")

        # ── Phase 2: 去尺寸段比對 ──
        # 3D 常為 5 段 (系統-編號-尺寸-材質-保溫)，ISO 為 4 段 (無尺寸)
        # 將 3D 的 Line_combined 去掉尺寸段後比對
        if merged is None or len(merged) < len(iso_df):
            _log("Phase2: 嘗試去尺寸段比對 (strip-size)...")
            df_minus["__line_stripped"] = df_minus["__line_norm"].apply(
                _strip_size_segment
            )
            stripped_set = set(df_minus["__line_stripped"].tolist())

            # 已嚴謹配對的 ISO line_norm
            already_matched = set()
            if merged is not None:
                already_matched = set(merged["__line_norm"].tolist())

            # 找出尚未配對的 ISO 列
            iso_remaining = iso_df[~iso_df["__line_norm"].isin(already_matched)]
            iso_strip_keep = iso_remaining[
                iso_remaining["__line_norm"].isin(stripped_set)
            ].copy()
            _log(f"Phase2 strip-size matched rows = {len(iso_strip_keep)}")

            if len(iso_strip_keep) > 0:
                minus_strip_map = df_minus[
                    ["__line_stripped", "Line_combined", "Raw_last"]
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
                    ["__line_drop_last", "Line_combined", "Raw_last"]
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
                    ["__line_base", "Line_combined", "Raw_last"]
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
                ["__line_norm", "Line_combined", "Raw_last"]
            ].drop_duplicates()
            merged = iso_keep.merge(minus_map, on="__line_norm", how="left")
            if "MatchType" not in merged.columns:
                merged["MatchType"] = ""

        # ── Phase 4: 收集尚未配對的 ISO 行 + 模糊候選 ──
        matched_iso_norms = set(merged["__line_norm"].tolist()) if len(merged) > 0 else set()
        iso_still_unmatched = iso_df[~iso_df["__line_norm"].isin(matched_iso_norms)]
        _log(f"Phase4: 尚未配對的 ISO 行 = {len(iso_still_unmatched)}")

        # 建立 prefix→3D 對照表  (system-line_no 前兩段)
        minus_valid = df_minus[
            df_minus["__line_norm"].str.strip().ne("")
            & df_minus["__line_norm"].str.strip().ne("0")
        ]
        prefix_to_3d: Dict[str, List[str]] = {}
        # 也建立 system→3D 對照表 (僅第一段)，用於 fallback 搜索
        system_to_3d: Dict[str, List[str]] = {}
        for v in minus_valid["__line_norm"].unique():
            parts = str(v).split("-")
            if len(parts) >= 2:
                pfx = "-".join(parts[:2])
                prefix_to_3d.setdefault(pfx, []).append(v)
            if len(parts) >= 1 and parts[0]:
                system_to_3d.setdefault(parts[0].upper(), []).append(v)

        self.fuzzy_unmatched = []
        for _, row in iso_still_unmatched.iterrows():
            iso_line = str(row["__line_norm"]).strip()
            iso_spool = str(row.get("流水號", "")).strip()
            if not iso_line:
                continue
            iso_parts = iso_line.split("-")
            pfx = "-".join(iso_parts[:2]) if len(iso_parts) >= 2 else iso_line
            iso_system = iso_parts[0].upper() if iso_parts else ""

            candidates = []
            seen_3d: set[str] = set()

            # ── 第一輪：前綴 (system-line_no) 相同的候選 ──
            for cand_3d in prefix_to_3d.get(pfx, []):
                if cand_3d in seen_3d:
                    continue
                seen_3d.add(cand_3d)
                stripped_3d = _strip_size_segment(cand_3d)
                if stripped_3d == iso_line:
                    score = 0.97
                    reason = "去尺寸段完全吻合"
                else:
                    score, reason = _compute_segment_score(iso_line, cand_3d)
                candidates.append({
                    "line_3d": cand_3d,
                    "score": score,
                    "reason": reason,
                })

            # ── 第二輪：同系統但不同編號的候選 ──
            if iso_system and len(candidates) < 5:
                for cand_3d in system_to_3d.get(iso_system, []):
                    if cand_3d in seen_3d:
                        continue
                    seen_3d.add(cand_3d)
                    score, reason = _compute_segment_score(iso_line, cand_3d)
                    if score >= 0.20:
                        candidates.append({
                            "line_3d": cand_3d,
                            "score": score,
                            "reason": reason,
                        })

            # ── 第三輪：全文搜索（前綴不同的候選）──
            if len(candidates) < 3:
                for v in minus_valid["__line_norm"].unique():
                    if v in seen_3d:
                        continue
                    score, reason = _compute_segment_score(iso_line, str(v))
                    if score >= 0.40:
                        candidates.append({
                            "line_3d": v,
                            "score": score,
                            "reason": reason,
                        })
                        seen_3d.add(v)

            candidates.sort(key=lambda c: -c["score"])
            candidates = candidates[:15]  # 保留前 15 筆候選
            self.fuzzy_unmatched.append({
                "iso_line": iso_line,
                "iso_spool": iso_spool,
                "candidates": candidates,
            })

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
            strict_minus_keys = set(merged["Line_combined"].astype(str).tolist())

            # 找出：尚未嚴謹 match，但在寬鬆 key 上有家族的 minus 列
            minus_loose_only = df_minus[
                (~df_minus["Line_combined"].astype(str).isin(strict_minus_keys))
                & df_minus["__loose_key"].astype(str).isin(
                    {k for k in iso_df["__loose_key"].astype(str).tolist() if k}
                )
            ].copy()

            if not minus_loose_only.empty:
                _log(
                    f"發現 {len(minus_loose_only)} 條 3D 線為『僅寬鬆有家族』，將補入 iso_match。"
                )
                _log(
                    "minus_loose_only sample (前 3 筆 Line_combined, __loose_key): "
                    + ", ".join(
                        [
                            f"{r['Line_combined']}|{r['__loose_key']}"
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
                        "Line_combined",
                        "Raw_last",
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
                # - 覆寫 3D 端的 Line_combined / Raw_last
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
                    row["Line_combined"] = r.get("Line_combined", "")
                    row["Raw_last"] = r.get("Raw_last", "")

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
                        "loose_only add_df sample (前 3 筆 管線編號, 流水號, Line_combined, MatchType): "
                        + ", ".join(
                            [
                                f"{r['管線編號']}|{r['流水號']}|{r['Line_combined']}|{r['MatchType']}"
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
        _log("merged sample (前 5 筆 管線編號, 流水號, Line_combined):")
        for _, r in merged.head(5).iterrows():
            pipe_show = r.get("__pipe_raw", r.get("__pipe_base", ""))
            _log(f"  {pipe_show} | {r['流水號']} | {r['Line_combined']}")

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

        full_out_cols = [
            "管線編號",
            "流水號",
            "Line_combined",
            "Raw_last",
            "系統",
            "材質",
            "保溫",
            "試壓媒介",
            "預製圖",
            "發包分類",
            "群組",
            "MatchType",
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
                "Line_combined",
                "Raw_last",
                "群組",
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
            "result head sample (前 3 筆 管線編號, 流水號, Line_combined, MatchType): "
            + ", ".join(
                [
                    f"{r.get('管線編號','')}|{r.get('流水號','')}|{r.get('Line_combined','')}|{r.get('MatchType','')}"  # type: ignore[index]
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

        # 產生 minus 覆蓋檢查報表：哪些 3D Line_combined 沒有任何 ISO 對應
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
            每筆為 ``{"iso_line": str, "iso_spool": str, "line_3d": str}``。
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
            "管線編號", "流水號", "Line_combined", "Raw_last", "群組", "MatchType",
        ]

        new_rows = []
        for sel in selections:
            row: dict = {c: "" for c in cols}
            row["管線編號"] = sel.get("iso_line", "")
            row["流水號"] = sel.get("iso_spool", "")
            row["Line_combined"] = sel.get("line_3d", "")
            row["Raw_last"] = sel.get("line_3d", "")
            row["MatchType"] = "fuzzy_manual"
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
