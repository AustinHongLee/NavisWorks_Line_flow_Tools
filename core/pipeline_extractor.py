# -*- coding: utf-8 -*-
"""管線抽取：First_try.csv → 123_minus_1.csv

重構為 `PipelineExtractor` 類別，方便在 GUI/CLI 共用。
"""
from __future__ import annotations

import os
import json
import re
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from core.identity_resolver import IdentityResolver
from core.iso_recall_engine import IsoRecallEngine
from core.scope_indexer import parse_scope_context
from utils.iso_schema import detect_schema, load_iso_line_key_set
from utils.utils_common import CommonUtils
from utils.pipe_parser import load_pipe_pattern, parse_pipe_code


# ── 管線編號常見格式 regex（用於從 DisplayName 中辨識管線身分證） ──
_PIPE_CODE_RE = re.compile(
    r"^[A-Z]{1,6}-[A-Z]?\d{3,5}", re.IGNORECASE
)


def detect_id_level(
    first_try_csv: str,
    iso_list_path: str,
    sep: str = "___",
    iso_sheet_name: Optional[str] = None,
    pipe_col_override: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    max_probes: int = 80,
) -> Dict:
    """自動偵測 3D 身分證階層 (id_level)。

    演算法
    ------
    1. 從 ISO 清單取出 **不重複的管線編號** 作為探針 (probes)。
       優先使用 ``Line_No`` 欄位（去 spool 後綴）；
       若該欄位不存在則退回 ``DWG NO`` / 管線編號欄位。
       若有 ``DWG NO`` 欄位，會額外把 DWG NO 值也加入探針集。
    2. 讀取 ``First_try.csv``，取 ``DisplayName`` 與 ``Level`` 兩欄。
    3. 逐一將探針與 ``DisplayName`` 精確比對 + 子字串（去尺寸段）比對。
    4. 統計各 ``Level`` 的命中次數，取 **最多命中** 的 Level 作為建議值。

    Returns
    -------
    dict
        ``{"level": int | None, "confidence": float, "hits": dict, "detail": str}``
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    # ── 1. 讀 ISO 清單，蒐集探針 ──
    if not os.path.exists(iso_list_path):
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": f"ISO 清單檔案不存在：{iso_list_path}"}

    try:
        xls = pd.ExcelFile(iso_list_path, engine="openpyxl")
    except Exception as exc:
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": f"無法開啟 ISO 檔案：{exc}"}

    try:
        schema = detect_schema(
            xls,
            sheet_name=iso_sheet_name,
            pipe_col_override=pipe_col_override,
        )
    except Exception as exc:
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": f"ISO 清單找不到管線欄位：{exc}"}
    sheet = schema.sheet_name

    iso_df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
    try:
        xls.close()
    except Exception:
        pass

    pipe_col: Optional[str] = schema.pipe_col

    probes: set[str] = set()
    # 主欄位 (Line_No) — 去重複
    for v in iso_df[pipe_col].astype(str).str.strip().unique():
        if v and v != "nan":
            probes.add(v)

    # DWG NO — 也加入（可能帶 spool 後綴，3D 側不一定有，但試試）
    if "DWG NO" in iso_df.columns and pipe_col != "DWG NO":
        for v in iso_df["DWG NO"].astype(str).str.strip().unique():
            if v and v != "nan":
                probes.add(v)

    # LINE   NUMBER 格式不同 (帶尺寸前綴如 2"-AC-...)，不適合直接用
    _log(f"[偵測] 共 {len(probes)} 組探針 (來自 {pipe_col}" +
         (" + DWG NO)" if "DWG NO" in iso_df.columns else ")"))

    if not probes:
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": "ISO 清單中沒有可用的管線編號。"}

    # 限制探針數量（避免 70 萬列 × 千級探針太慢）
    if len(probes) > max_probes:
        probes = set(list(probes)[:max_probes])
        _log(f"[偵測] 探針數超過 {max_probes}，截取前 {max_probes} 組")

    # ── 2. 讀 First_try.csv ──
    if not os.path.exists(first_try_csv):
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": f"First_try CSV 不存在：{first_try_csv}"}

    try:
        raw_df = pd.read_csv(
            first_try_csv, dtype=str, encoding="utf-8-sig",
            low_memory=False, on_bad_lines="skip",
        ).fillna("")
    except Exception as exc:
        return {"level": None, "confidence": 0.0, "hits": {},
                "detail": f"讀取 First_try CSV 失敗：{exc}"}

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

    # 建立 DisplayName / PipelineId → Level 的快速查詢
    dn_to_levels: Dict[str, List[str]] = {}
    for _, row in raw_df.iterrows():
        dn = row["DisplayName"]
        lv = row["Level"]
        if dn:
            dn_to_levels.setdefault(dn, []).append(lv)
        # PipelineId 也加入查詢表（情境 B：管線編號只在屬性）
        pid = row["PipelineId"]
        if pid and pid != dn:
            dn_to_levels.setdefault(pid, []).append(lv)

    _log(f"[偵測] First_try.csv 共 {len(raw_df)} 列，"
         f"不重複 DisplayName/PipelineId {len(dn_to_levels)} 組")

    # ── 3. 比對探針 → 統計 Level ──
    level_counter: Counter = Counter()
    probe_matched = 0
    probe_detail: List[str] = []

    # 也建一個去尺寸段的 DisplayName 表
    from core.iso_matcher import _strip_size_segment, _SIZE_RE, _SUPPORTS_RE

    for probe in probes:
        # 策略 A：精確比對 DisplayName
        if probe in dn_to_levels:
            for lv in dn_to_levels[probe]:
                level_counter[lv] += 1
            probe_matched += 1
            probe_detail.append(f"  ✓ {probe} → Level={dn_to_levels[probe]}")
            continue

        # 策略 B：去尺寸段比對（3D 可能帶尺寸段，ISO probe 不帶）
        # 遍歷所有 DisplayName，把 3D 端去尺寸後比
        matched_b = False
        for dn, levels in dn_to_levels.items():
            stripped = _strip_size_segment(dn)
            if stripped == probe:
                for lv in levels:
                    level_counter[lv] += 1
                probe_matched += 1
                probe_detail.append(f"  ✓ {probe} ≈strip→ {dn} → Level={levels}")
                matched_b = True
                break
        if matched_b:
            continue

        # 策略 C：probe 帶 spool 後綴 (如 -1)，去掉再比
        # e.g., DWG NO = AC-1801-50-AA2B-NA-1 → try AC-1801-50-AA2B-NA
        probe_stripped = re.sub(r"-\d{1,3}$", "", probe)
        if probe_stripped != probe and probe_stripped in dn_to_levels:
            for lv in dn_to_levels[probe_stripped]:
                level_counter[lv] += 1
            probe_matched += 1
            probe_detail.append(
                f"  ✓ {probe} →去spool→ {probe_stripped} → Level={dn_to_levels[probe_stripped]}"
            )
            continue

    _log(f"[偵測] 探針命中率：{probe_matched}/{len(probes)} "
         f"({probe_matched / len(probes):.0%})")

    # 顯示前幾筆 detail
    for d in probe_detail[:8]:
        _log(d)
    if len(probe_detail) > 8:
        _log(f"  ... 共 {len(probe_detail)} 筆命中")

    # ── 4. 決定最佳 Level ──
    if not level_counter:
        return {
            "level": None,
            "confidence": 0.0,
            "hits": dict(level_counter),
            "detail": (
                f"在 First_try.csv 中找不到任何 ISO 探針的 DisplayName 命中。"
                f"\n（共測試 {len(probes)} 組探針）"
            ),
        }

    total_hits = sum(level_counter.values())
    best_level_str, best_count = level_counter.most_common(1)[0]
    confidence = best_count / total_hits if total_hits > 0 else 0.0

    try:
        best_level = int(best_level_str)
    except ValueError:
        best_level = None

    hits_dict = {k: v for k, v in level_counter.most_common()}
    detail_lines = [
        f"偵測結果：id_level = {best_level}",
        f"命中統計：{hits_dict}",
        f"信心度：{confidence:.0%}（Level {best_level} 命中 {best_count}/{total_hits}）",
        f"探針命中率：{probe_matched}/{len(probes)} ({probe_matched / len(probes):.0%})",
    ]
    detail = "\n".join(detail_lines)
    _log(f"[偵測] {detail_lines[0]}")
    _log(f"[偵測] {detail_lines[2]}")

    return {
        "level": best_level,
        "confidence": confidence,
        "hits": hits_dict,
        "detail": detail,
    }


class PipelineExtractor:
    """從 First_try 抽取管線關鍵字並產生中繼檔。"""

    def __init__(self, sep: str = "___", raw_prefix: str = "/"):
        self.sep = sep
        self.raw_prefix = raw_prefix

    def build_intermediate(
        self,
        input_csv: str,
        out_csv: str,
        filter_key: Optional[str] = None,
        id_level: Optional[int] = None,
        pipeline_mode: str = "smart",
        pipeline_index: Optional[int] = None,
        pipeline_regex: Optional[str] = None,
        scan_mode: str = "full",
        iso_list_path: Optional[str] = None,
        iso_sheet_name: Optional[str] = None,
        pipe_col_override: Optional[str] = None,
        write_first_try_trace: bool = False,
        first_try_trace_path: Optional[str] = None,
        write_candidates: bool = False,
        candidates_path: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> int:
        def _log(msg: str) -> None:
            if log_fn is not None:
                log_fn(msg)
            else:
                print(msg)

        if not os.path.exists(input_csv):
            raise FileNotFoundError(f"[Step1] 找不到輸入檔 First_try CSV：{input_csv}")

        try:
            raw_df = pd.read_csv(
                input_csv,
                dtype=str,
                encoding="utf-8-sig",
                low_memory=False,
                on_bad_lines="skip",
            )
        except UnicodeDecodeError as e:
            msg = (
                "[Step1] 讀取 First_try CSV 編碼失敗，請確認是否為 "
                "UTF-8-SIG 或改用其他編碼開啟後另存。原始錯誤："
                f"{e.reason}"
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
                "[Step1] 讀取 First_try CSV 失敗："
                f"{input_csv}，請檢查檔案是否被鎖定或格式是否正確。詳細：{e}"
            ) from e

        # ── 向後相容：5 欄 (含 PipelineId) 或 4 欄 (舊格式) ──
        n_cols = min(len(raw_df.columns), 5)
        raw_df = raw_df.iloc[:, :n_cols].copy()
        col_names = ["Path", "DisplayName", "Class", "Level"]
        if n_cols >= 5:
            col_names.append("PipelineId")
        raw_df.columns = col_names
        if "PipelineId" not in raw_df.columns:
            raw_df["PipelineId"] = ""
        raw_df = raw_df.fillna("")
        raw_df["__source_row_idx"] = [str(i + 1) for i in range(len(raw_df))]
        _log(
            "[Step1] First_try 讀取完成："
            f"rows={len(raw_df)}, columns={list(raw_df.columns)}"
        )
        _log(
            "[Step1] 掃描設定："
            f"scan_mode={scan_mode}, id_level={id_level}, "
            f"filter_key='{filter_key or ''}', sep='{self.sep}', "
            f"raw_prefix='{self.raw_prefix}'"
        )
        if "Level" in raw_df.columns:
            level_counts = raw_df["Level"].astype(str).str.strip().value_counts()
            _log(
                "[Step1] Level 分布（前 8）："
                + str(level_counts.head(8).to_dict())
            )
        for sample_col in ["DisplayName", "PipelineId"]:
            if sample_col in raw_df.columns:
                samples = [
                    str(v).strip()
                    for v in raw_df[sample_col].tolist()
                    if str(v).strip()
                ][:5]
                _log(f"[Step1] {sample_col} sample：{samples}")

        known_iso_keys: set[str] = set()
        if iso_list_path and os.path.exists(iso_list_path):
            try:
                known_iso_keys = load_iso_line_key_set(
                    iso_list_path,
                    sheet_name=iso_sheet_name,
                    pipe_col_override=pipe_col_override,
                )
                _log(
                    "[Step1] ISO 白名單載入："
                    f"{len(known_iso_keys)} keys "
                    f"(sheet={iso_sheet_name or 'auto'}, "
                    f"pipe_col={pipe_col_override or 'auto'})"
                )
            except Exception as exc:
                known_iso_keys = set()
                _log(f"[Step1] ISO 白名單載入失敗，改用純 3D 辨識：{exc}")
        else:
            _log("[Step1] 未指定 ISO 白名單，改用純 3D 辨識。")

        resolver = IdentityResolver(
            sep=self.sep,
            raw_prefix=self.raw_prefix,
            known_iso_keys=known_iso_keys,
        )
        recall_engine = IsoRecallEngine(known_iso_keys)

        def _attach_identity_columns(df_src: pd.DataFrame) -> pd.DataFrame:
            if df_src.empty:
                resolved = df_src.apply(
                    resolver.resolve,
                    axis=1,
                    result_type="expand",
                )
            else:
                resolved_parts: list[pd.DataFrame] = []
                total = len(df_src)
                chunk_size = 5000
                for start in range(0, total, chunk_size):
                    stop = min(start + chunk_size, total)
                    resolved_parts.append(
                        df_src.iloc[start:stop].apply(
                            resolver.resolve,
                            axis=1,
                            result_type="expand",
                        )
                    )
                    _log(
                        "[Step1] 身份解析進度："
                        f"已處理 {stop}/{total} 列"
                    )
                resolved = pd.concat(resolved_parts).sort_index()
            for col in [
                "Raw_3D_PipeCode",
                "ISO_Match_Key",
                "MatchSource",
                "ConfidencePrimary",
                "IdentityReason",
                "CandidateCount",
                "CandidateTrace",
            ]:
                df_src[col] = resolved[col] if col in resolved else ""
            return df_src

        def _trace_path() -> str:
            return first_try_trace_path or os.path.join(
                os.path.dirname(os.path.abspath(out_csv)),
                "first_try_trace.csv",
            )

        def _candidates_path() -> str:
            return candidates_path or os.path.join(
                os.path.dirname(os.path.abspath(out_csv)),
                "candidates.csv",
            )

        def _classify_exclusion(row: pd.Series, resolved_known: bool) -> tuple[str, str]:
            if not resolved_known:
                return "out_of_scan_scope", "不在本次掃描範圍"
            values = [
                str(row.get("PipelineId", "")),
                str(row.get("DisplayName", "")),
            ]
            if any(IdentityResolver._is_file_like(v) for v in values if v):
                return "file_like", "看起來是模型/檔案節點，不作為管線身份"
            if any(IdentityResolver._is_structural(v) for v in values if v):
                return "structural", "看起來是結構/支架類節點，不作為管線身份"
            return "no_id", "沒有找到符合管線格式或 ISO 白名單的身份候選"

        def _write_debug_outputs(
            scan_df: pd.DataFrame,
            included_df: pd.DataFrame,
        ) -> None:
            if not write_first_try_trace and not write_candidates:
                return
            included_source = set(
                included_df.get("__source_row_idx", pd.Series([], dtype=str))
                .astype(str)
                .tolist()
            )
            scan_by_source = {
                str(r.get("__source_row_idx", "")): r
                for _, r in scan_df.iterrows()
            }
            minus_row_by_source = {
                str(src): str(i + 1)
                for i, src in enumerate(
                    included_df.get("__source_row_idx", pd.Series([], dtype=str))
                    .astype(str)
                    .tolist()
                )
            }

            if write_first_try_trace:
                trace_rows: list[dict[str, object]] = []
                for _, raw_row in raw_df.iterrows():
                    source_idx = str(raw_row.get("__source_row_idx", ""))
                    resolved_row = scan_by_source.get(source_idx)
                    resolved_known = resolved_row is not None
                    if resolved_known:
                        resolved_row = resolved_row.fillna("")
                    included = source_idx in included_source
                    reason = ""
                    detail = ""
                    if not included:
                        reason, detail = _classify_exclusion(raw_row, resolved_known)
                    recall_candidates = []
                    if not included:
                        recall_candidates = recall_engine.recall_row(
                            resolved_row if resolved_known else raw_row,
                            max_candidates=3,
                        )
                    best_recall = recall_candidates[0] if recall_candidates else None
                    trace_rows.append(
                        {
                            "source_row_idx": source_idx,
                            "Path": raw_row.get("Path", ""),
                            "DisplayName": raw_row.get("DisplayName", ""),
                            "Class": raw_row.get("Class", ""),
                            "Level": raw_row.get("Level", ""),
                            "PipelineId": raw_row.get("PipelineId", ""),
                            "candidate_count": (
                                resolved_row.get("CandidateCount", "")
                                if resolved_known else ""
                            ),
                            "best_candidate_raw": (
                                resolved_row.get("Raw_3D_PipeCode", "")
                                if resolved_known else ""
                            ),
                            "best_candidate_normalized": (
                                resolved_row.get("ISO_Match_Key", "")
                                if resolved_known else ""
                            ),
                            "best_candidate_source": (
                                resolved_row.get("MatchSource", "")
                                if resolved_known else ""
                            ),
                            "included_in_minus_1": "1" if included else "0",
                            "exclude_reason": reason,
                            "exclude_detail": detail,
                            "minus_1_row_idx": minus_row_by_source.get(source_idx, ""),
                            "recall_candidate_count": str(len(recall_candidates)),
                            "best_recall_iso": best_recall.iso_key if best_recall else "",
                            "best_recall_score": (
                                f"{best_recall.score:.4f}" if best_recall else ""
                            ),
                            "best_recall_raw": best_recall.raw_3d if best_recall else "",
                            "best_recall_normalized": (
                                best_recall.normalized_3d if best_recall else ""
                            ),
                            "best_recall_terms": (
                                ",".join(best_recall.matched_terms)
                                if best_recall else ""
                            ),
                            "best_recall_reason": (
                                best_recall.reason if best_recall else ""
                            ),
                        }
                    )
                pd.DataFrame(trace_rows).to_csv(
                    _trace_path(),
                    index=False,
                    encoding="utf-8-sig",
                )

            if write_candidates:
                candidate_rows: list[dict[str, object]] = []
                for _, scan_row in scan_df.iterrows():
                    source_idx = str(scan_row.get("__source_row_idx", ""))
                    candidates = resolver.collect_candidates(scan_row)
                    for idx, cand in enumerate(candidates, start=1):
                        candidate_rows.append(
                            {
                                "candidate_kind": "primary_identity",
                                "source_row_idx": source_idx,
                                "minus_1_row_idx": minus_row_by_source.get(source_idx, ""),
                                "included_in_minus_1": (
                                    "1" if source_idx in included_source else "0"
                                ),
                                "candidate_idx": idx,
                                "raw": cand.raw,
                                "normalized": cand.normalized,
                                "source": cand.source,
                                "score": f"{cand.score:.4f}",
                                "reason": cand.reason,
                                "trace_events": " | ".join(cand.trace_events),
                                "iso_candidate": "",
                                "matched_terms": "",
                                "missing_terms": "",
                                "evidence_json": "",
                                "auto_safe": "",
                                "reason_codes": "",
                                "review_status": (
                                    "auto_identity"
                                    if source_idx in included_source
                                    else "not_selected"
                                ),
                                "Path": scan_row.get("Path", ""),
                                "DisplayName": scan_row.get("DisplayName", ""),
                                "Level": scan_row.get("Level", ""),
                                "PipelineId": scan_row.get("PipelineId", ""),
                            }
                        )
                    recall_candidates = []
                    if not candidates:
                        recall_candidates = recall_engine.recall_row(
                            scan_row,
                            max_candidates=5,
                        )
                    for idx, cand in enumerate(recall_candidates, start=1):
                        candidate_rows.append(
                            {
                                "candidate_kind": "iso_reverse_recall",
                                "source_row_idx": source_idx,
                                "minus_1_row_idx": minus_row_by_source.get(source_idx, ""),
                                "included_in_minus_1": (
                                    "1" if source_idx in included_source else "0"
                                ),
                                "candidate_idx": idx,
                                "raw": cand.raw_3d,
                                "normalized": cand.normalized_3d,
                                "source": cand.source,
                                "score": f"{cand.score:.4f}",
                                "reason": cand.reason,
                                "trace_events": cand.trace,
                                "iso_candidate": cand.iso_key,
                                "matched_terms": ",".join(cand.matched_terms),
                                "missing_terms": ",".join(cand.missing_terms[:8]),
                                "evidence_json": json.dumps(
                                    cand.evidence,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                                "auto_safe": "1" if cand.auto_safe else "0",
                                "reason_codes": ",".join(cand.reason_codes),
                                "review_status": "needs_review",
                                "Path": cand.path or scan_row.get("Path", ""),
                                "DisplayName": scan_row.get("DisplayName", ""),
                                "Level": cand.level or scan_row.get("Level", ""),
                                "PipelineId": scan_row.get("PipelineId", ""),
                                "PipeNodePath": cand.pipe_node_path,
                                "ScopeRoot": cand.scope_root,
                                "ParentArea": cand.parent_area,
                            }
                        )
                pd.DataFrame(
                    candidate_rows,
                    columns=[
                        "candidate_kind",
                        "source_row_idx",
                        "minus_1_row_idx",
                        "included_in_minus_1",
                        "candidate_idx",
                        "raw",
                        "normalized",
                        "source",
                        "score",
                        "reason",
                        "trace_events",
                        "iso_candidate",
                        "matched_terms",
                        "missing_terms",
                        "evidence_json",
                        "auto_safe",
                        "reason_codes",
                        "review_status",
                        "Path",
                        "DisplayName",
                        "Level",
                        "PipelineId",
                        "PipeNodePath",
                        "ScopeRoot",
                        "ParentArea",
                    ],
                ).to_csv(
                    _candidates_path(),
                    index=False,
                    encoding="utf-8-sig",
                )

        def _attach_scope_columns(df_src: pd.DataFrame) -> pd.DataFrame:
            contexts = df_src.apply(
                lambda r: parse_scope_context(
                    r.get("Path", ""),
                    self.sep,
                    iso_match_key=r.get("ISO_Match_Key", ""),
                    raw_3d_pipe_code=r.get("Raw_3D_PipeCode", ""),
                    level=r.get("Level", ""),
                ),
                axis=1,
                result_type="expand",
            )
            for col in ["PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel"]:
                df_src[col] = contexts[col].astype(str) if col in contexts else ""
            return df_src

        def _nonempty_values(df_src: pd.DataFrame, col: str, limit: int = 5) -> list[str]:
            if col not in df_src.columns:
                return []
            result: list[str] = []
            for value in df_src[col].tolist():
                text = str(value).strip()
                if text and text not in result:
                    result.append(text)
                if len(result) >= limit:
                    break
            return result

        def _log_identity_summary(
            label: str,
            scan_df: pd.DataFrame,
            included_df: pd.DataFrame,
        ) -> None:
            _log(
                f"[Step1] {label} 掃描結果："
                f"掃描 {len(scan_df)} 列，抓到 {len(included_df)} 列，"
                f"未抓到 {max(len(scan_df) - len(included_df), 0)} 列"
            )
            if scan_df.empty:
                _log("[Step1] 掃描範圍是空的，請檢查 scan_mode / id_level / filter_key。")
                return

            if "MatchSource" in scan_df.columns:
                sources = (
                    scan_df["MatchSource"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .replace("", "(empty)")
                    .value_counts()
                    .head(8)
                    .to_dict()
                )
                _log(f"[Step1] MatchSource 分布：{sources}")

            if "CandidateCount" in scan_df.columns:
                candidate_counts = pd.to_numeric(
                    scan_df["CandidateCount"],
                    errors="coerce",
                ).fillna(0)
                _log(
                    "[Step1] 身份候選統計："
                    f"有候選列={int((candidate_counts > 0).sum())}, "
                    f"最大候選數={int(candidate_counts.max()) if len(candidate_counts) else 0}"
                )

            matched_samples = []
            for _, row in included_df.head(5).iterrows():
                matched_samples.append(
                    f"{row.get('Raw_3D_PipeCode', '')} -> "
                    f"{row.get('ISO_Match_Key', '')} "
                    f"({row.get('MatchSource', '')})"
                )
            if matched_samples:
                _log(f"[Step1] 已抓到 sample：{matched_samples}")

            unmatched = scan_df[
                scan_df.get("ISO_Match_Key", pd.Series([], dtype=str))
                .astype(str)
                .str.strip()
                .eq("")
            ].head(5)
            if not unmatched.empty:
                samples = []
                for _, row in unmatched.iterrows():
                    reason, detail = _classify_exclusion(row, True)
                    samples.append(
                        "Level={level}, DisplayName='{display}', "
                        "PipelineId='{pid}', reason={reason}, detail={detail}".format(
                            level=row.get("Level", ""),
                            display=str(row.get("DisplayName", ""))[:80],
                            pid=str(row.get("PipelineId", ""))[:80],
                            reason=reason,
                            detail=detail,
                        )
                    )
                _log(f"[Step1] 未抓到 sample：{samples}")

            if included_df.empty:
                _log(
                    "[Step1][WARN] 本次沒有抓到任何 3D 管線身份。"
                    "後續 Step3 沒有 3D key 可比對，ISO 會全部變成未配對。"
                )
                _log(
                    "[Step1][HINT] 優先檢查：First_try 是否有 PipelineId、"
                    "目前 scan_mode/id_level 是否掃到管線列、ISO 欄位是否選到管線號。"
                )
                _log(
                    "[Step1][HINT] 目前非空 DisplayName sample="
                    f"{_nonempty_values(scan_df, 'DisplayName')}; "
                    "PipelineId sample="
                    f"{_nonempty_values(scan_df, 'PipelineId')}"
                )

        # ── 根據 scan_mode 決定掃描範圍 ──
        if scan_mode == "full":
            # 嚴謹模式：全掃所有列，純靠 PipelineId / regex 辨識
            df = raw_df.copy()
            _log("[Step1] 使用 full 掃描：全列辨識 PipelineId / DisplayName。")
            df = _attach_identity_columns(df)
            mask = df["ISO_Match_Key"].astype(str).str.strip().ne("")
            scan_df = df.copy()
            df = df[mask].copy()
            _log_identity_summary("full", scan_df, df)
            df = _attach_scope_columns(df)
            _write_debug_outputs(scan_df, df)
            out_cols = [
                "Path", "DisplayName", "Class", "Level",
                "Raw_3D_PipeCode", "ISO_Match_Key",
                "MatchSource", "ConfidencePrimary", "IdentityReason",
                "CandidateCount", "CandidateTrace",
                "PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel",
            ]
            df[out_cols].to_csv(out_csv, index=False, encoding="utf-8-sig")
            return len(df)

        if scan_mode == "level" and id_level is not None:
            # 加速模式：僅掃描指定 Level
            id_level_str = str(id_level)
            df = raw_df[
                raw_df["Level"].astype(str).str.strip() == id_level_str
            ].copy()
            _log(
                f"[Step1] 使用 level 掃描：Level={id_level_str}, "
                f"命中 {len(df)} / {len(raw_df)} 列"
            )

            df = _attach_identity_columns(df)
            scan_df = df.copy()
            df = df[df["ISO_Match_Key"].astype(str).str.strip().ne("")].copy()
            _log_identity_summary("level", scan_df, df)
            df = _attach_scope_columns(df)
            _write_debug_outputs(scan_df, df)

            out_cols = [
                "Path", "DisplayName", "Class", "Level",
                "Raw_3D_PipeCode", "ISO_Match_Key",
                "MatchSource", "ConfidencePrimary", "IdentityReason",
                "CandidateCount", "CandidateTrace",
                "PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel",
            ]
            df[out_cols].to_csv(out_csv, index=False, encoding="utf-8-sig")
            return len(df)

        # fallback: filter_key 模式（進階選項）
        key = filter_key if filter_key else "管線"

        roots = raw_df[
            (raw_df["Level"] == "2")
            & (raw_df["DisplayName"].str.contains(key, na=False))
        ].copy()
        _log(f"[Step1] 使用 filter_key 掃描：key='{key}', roots={len(roots)}")

        result_records = []
        for _, row in roots.iterrows():
            root_path = row["Path"]
            sub_df = raw_df[
                (raw_df["Path"].str.startswith(root_path + self.sep))
                & (raw_df["Level"].isin(["3", "4", "5"]))
            ].copy()
            result_records.append(row.to_dict())
            result_records.extend(sub_df.to_dict("records"))

        if not result_records:
            _write_debug_outputs(
                pd.DataFrame(columns=list(raw_df.columns)),
                pd.DataFrame(columns=list(raw_df.columns)),
            )
            pd.DataFrame(
                columns=["Path", "DisplayName", "Class", "Level"]
            ).to_csv(out_csv, index=False, encoding="utf-8-sig")
            return 0

        df = pd.DataFrame(result_records).fillna("")

        df = _attach_identity_columns(df)
        scan_df = df.copy()
        df = df[df["ISO_Match_Key"].astype(str).str.strip().ne("")].copy()
        _log_identity_summary("filter_key", scan_df, df)
        df = _attach_scope_columns(df)
        _write_debug_outputs(scan_df, df)

        _log("[Step1] final columns in minus_1: " + str(list(df.columns)))
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        return len(df)
