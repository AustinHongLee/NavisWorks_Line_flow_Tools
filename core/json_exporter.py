# -*- coding: utf-8 -*-
"""JSON 匯出：resolved mapping / iso_match → Navisworks selection JSON."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Dict, List, Optional

import pandas as pd

from utils.utils_common import CommonUtils, FileLogger


@dataclass
class JsonExportCaseResult:
    """A fully materialized export case.

    UI code can use this object as the same "truth" that file export uses.
    """

    name: str
    group_key: str
    output_mode: str
    source_rows: int
    filtered_rows: int
    export_rows: int
    blocked_rows: int
    pipe_count: int
    group_count: int
    scope_count: int
    entries: List[dict]
    filtered_df: pd.DataFrame = field(repr=False)
    export_df: pd.DataFrame = field(repr=False)


class JsonExporter:
    def __init__(self, logger: FileLogger | None = None):
        self.logger = logger

    def _log_print(self, msg: str) -> None:
        print(msg)
        if self.logger is not None:
            self.logger.append(msg)

    # ─────────────────────────────────────────────────────────
    # Public helpers used by GUI preview/export
    # ─────────────────────────────────────────────────────────

    def load_dataframe(self, iso_match_path: str) -> pd.DataFrame:
        if not os.path.exists(iso_match_path):
            raise FileNotFoundError(f"找不到 iso 比對結果：{iso_match_path}")

        ext = os.path.splitext(iso_match_path)[1].lower()
        if ext in (".xlsx", ".xlsm", ".xls"):
            self._log_print("[Step4_v2] 讀取 iso_match 為 Excel 格式")
            xls = pd.ExcelFile(iso_match_path, engine="openpyxl")
            sheet_name = "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
            self._log_print(f"[Step4_v2] 使用工作表 sheet = {sheet_name}")
            df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str).fillna("")
            try:
                xls.close()
            except Exception:
                pass
        else:
            self._log_print("[Step4_v2] 讀取 iso_match 為 CSV 格式")
            df = pd.read_csv(
                iso_match_path,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")

        return self.normalize_dataframe(df)

    def normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().fillna("")
        df = df.rename(columns={c: str(c).strip() for c in df.columns})

        if "Raw_3D_PipeCode" not in df.columns and "Raw_last" in df.columns:
            df = df.rename(columns={"Raw_last": "Raw_3D_PipeCode"})

        if "Raw_3D_PipeCode" not in df.columns:
            raise ValueError("改比對結果缺少必要欄位『Raw_3D_PipeCode』")
        df["Raw_3D_PipeCode"] = df["Raw_3D_PipeCode"].astype(str).str.strip()
        return df

    def build_case_result(
        self,
        df: pd.DataFrame,
        case: Dict[str, dict],
        log: bool = False,
    ) -> JsonExportCaseResult:
        df = self.normalize_dataframe(df)
        name = str(case.get("name", "")).strip() or "case"
        filters = case.get("filters") or {}
        group_key = str(case.get("group_key", "")).strip()

        if log:
            self._log_print("[Step4_v2] --- case 開始 ---")
            self._log_print(f"[Step4_v2] case_name  = {name}")
            self._log_print(f"[Step4_v2] group_key = '{group_key}'")
            self._log_print(f"[Step4_v2] filters   = {filters}")

        filtered_df = self.apply_filters(df, filters, log=log)
        if filtered_df.empty:
            resolved_group_key = self.resolve_group_key(df, group_key)
            return JsonExportCaseResult(
                name=name,
                group_key=resolved_group_key,
                output_mode=self.output_mode_label(resolved_group_key),
                source_rows=len(df),
                filtered_rows=0,
                export_rows=0,
                blocked_rows=0,
                pipe_count=0,
                group_count=0,
                scope_count=0,
                entries=[],
                filtered_df=filtered_df,
                export_df=filtered_df,
            )

        export_df = self.filter_json_safe(filtered_df, filters, log=log)
        resolved_group_key = self.resolve_group_key(export_df, group_key)
        entries = self.build_entries(export_df, resolved_group_key)
        pipe_count = self.unique_pipe_count(export_df)
        scope_count = sum(len(e.get("搜尋範圍", [])) for e in entries)
        return JsonExportCaseResult(
            name=name,
            group_key=resolved_group_key,
            output_mode=self.output_mode_label(resolved_group_key),
            source_rows=len(df),
            filtered_rows=len(filtered_df),
            export_rows=len(export_df),
            blocked_rows=max(0, len(filtered_df) - len(export_df)),
            pipe_count=pipe_count,
            group_count=len(entries),
            scope_count=scope_count,
            entries=entries,
            filtered_df=filtered_df,
            export_df=export_df,
        )

    # ─────────────────────────────────────────────────────────
    # Pipeline steps
    # ─────────────────────────────────────────────────────────

    def apply_filters(
        self,
        df_src: pd.DataFrame,
        filters: Dict[str, list[str]],
        log: bool = False,
    ) -> pd.DataFrame:
        sub = df_src
        for col, allowed in (filters or {}).items():
            col = str(col).strip()
            values = [str(v).strip() for v in (allowed or []) if str(v).strip()]
            if log:
                self._log_print(f"[Step4_v2]  篩選欄位 = '{col}', 值 = {values}")

            if not col or col not in sub.columns:
                if log:
                    self._log_print(
                        "[Step4_v2][WARN] 欄位不存在於 iso_match，該 case 視為無結果。"
                    )
                return sub.iloc[0:0]
            if not values:
                if log:
                    self._log_print("[Step4_v2]  該欄位沒有任何有效值，略過此欄位。")
                continue

            before = len(sub)
            sub = sub[sub[col].astype(str).str.strip().isin(values)]
            if log:
                self._log_print(f"[Step4_v2]  篩選後筆數：{before} -> {len(sub)}")
        return sub

    def filter_json_safe(
        self,
        df_src: pd.DataFrame,
        applied_filters: Dict[str, list[str]],
        log: bool = False,
    ) -> pd.DataFrame:
        has_scope_filter = any(
            str(k).strip() in {"ParentArea", "ScopeRoot"}
            for k in (applied_filters or {}).keys()
        )
        before = len(df_src)

        if "Resolved" in df_src.columns:
            resolved_mask = self.truthy_series(df_src["Resolved"])
            if "ResolutionStatus" in df_src.columns:
                pending_mask = (
                    df_src["ResolutionStatus"]
                    .astype(str)
                    .str.strip()
                    .eq("needs_decision")
                )
            else:
                pending_mask = pd.Series(False, index=df_src.index)
            narrowed_mask = (
                pending_mask & self.allow_narrowed_collision(df_src)
                if has_scope_filter
                else pd.Series(False, index=df_src.index)
            )
            safe = df_src[resolved_mask | narrowed_mask].copy()
            if log:
                self._log_print(
                    "[Step4_v2] resolved safety filter："
                    f"{before} -> {len(safe)}"
                    f"（含已用 ParentArea/ScopeRoot 篩定的 collision {int(narrowed_mask.sum())} 列）"
                )
            return safe

        if "NeedsDecision" in df_src.columns:
            decision_mask = self.truthy_series(df_src["NeedsDecision"])
            narrowed_mask = (
                decision_mask & self.allow_narrowed_collision(df_src)
                if has_scope_filter
                else pd.Series(False, index=df_src.index)
            )
            safe = df_src[(~decision_mask) | narrowed_mask].copy()
            if log:
                self._log_print(
                    "[Step4_v2] collision safety filter："
                    f"{before} -> {len(safe)}"
                    f"（含已用 ParentArea/ScopeRoot 篩定的 collision {int(narrowed_mask.sum())} 列）"
                )
            return safe

        return df_src

    def resolve_group_key(self, df_src: pd.DataFrame, group_key: str) -> str:
        group_key = str(group_key or "").strip()
        if group_key:
            return group_key
        if self.column_has_values(df_src, "群組"):
            return "群組"
        if "流水號" in df_src.columns:
            return "流水號"
        return "__ALL__"

    @staticmethod
    def column_has_values(df_src: pd.DataFrame, column: str) -> bool:
        if column not in df_src.columns:
            return False
        values = df_src[column].fillna("").astype(str).str.strip()
        return bool(values.ne("").any())

    @staticmethod
    def output_mode_label(group_key: str) -> str:
        if group_key == "__FLAT__":
            return "flat"
        if group_key == "__ALL__":
            return "all"
        return "grouped"

    def build_entries(self, df_src: pd.DataFrame, group_key: str) -> List[dict]:
        if df_src.empty:
            return []
        if group_key == "__FLAT__":
            return self.build_flat_entries(df_src)
        if group_key == "__ALL__":
            return self.build_all_entry(df_src)
        return self.build_grouped_entries(df_src, group_key)

    def build_grouped_entries(self, df_src: pd.DataFrame, group_key: str) -> List[dict]:
        entries: List[dict] = []
        if group_key not in df_src.columns:
            return entries
        sub_df = df_src[df_src["Raw_3D_PipeCode"] != ""]
        for key, sub in sub_df.groupby(group_key, sort=False):
            key_v = str(key).strip()
            if not key_v:
                continue
            raws = CommonUtils.unique_preserve(sub["Raw_3D_PipeCode"].tolist())
            if not raws:
                continue
            entry = {group_key: key_v, "管線號": raws}
            scope = self.build_scope_metadata(sub, raws)
            if scope:
                entry["搜尋範圍"] = scope
            entries.append(entry)
        return self.sort_group_entries(entries, key_name=group_key)

    def build_flat_entries(self, df_src: pd.DataFrame) -> List[dict]:
        sub_df = df_src[df_src["Raw_3D_PipeCode"] != ""]
        raws = CommonUtils.unique_preserve(sub_df["Raw_3D_PipeCode"].tolist())
        entries: List[dict] = []
        raw_series = sub_df["Raw_3D_PipeCode"].astype(str).str.strip()
        for raw in raws:
            raw_text = str(raw).strip()
            raw_rows = sub_df[raw_series.eq(raw_text)]
            entry = {"管線號": [raw_text]}
            scope = self.build_scope_metadata(raw_rows, [raw_text])
            if scope:
                entry["搜尋範圍"] = scope
            entries.append(entry)
        return entries

    def build_all_entry(self, df_src: pd.DataFrame) -> List[dict]:
        raws = CommonUtils.unique_preserve(df_src["Raw_3D_PipeCode"].tolist())
        if not raws:
            return []
        entry = {"__ALL__": "ALL", "管線號": raws}
        scope = self.build_scope_metadata(df_src, raws)
        if scope:
            entry["搜尋範圍"] = scope
        return [entry]

    # ─────────────────────────────────────────────────────────
    # Metadata / safety helpers
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def truthy_series(series: pd.Series) -> pd.Series:
        return series.astype(str).str.strip().str.lower().isin(
            ["1", "true", "yes", "y", "是"]
        )

    def allow_narrowed_collision(self, df_src: pd.DataFrame) -> pd.Series:
        allowed = pd.Series(False, index=df_src.index)
        if "流水號" not in df_src.columns:
            return allowed
        area_col = "ParentArea" if "ParentArea" in df_src.columns else ""
        if not area_col and "ScopeRoot" in df_src.columns:
            area_col = "ScopeRoot"
        if not area_col:
            return allowed

        for _, group in df_src.groupby("流水號", sort=False):
            areas = CommonUtils.unique_preserve(
                [
                    str(v).strip()
                    for v in group[area_col].tolist()
                    if str(v).strip()
                ]
            )
            if len(areas) == 1:
                allowed.loc[group.index] = True
        return allowed

    @staticmethod
    def scope_value(col: str, value: object):
        text = str(value).strip()
        if col == "PipeNodeLevel" and text.isdigit():
            return int(text)
        return text

    def build_scope_metadata(
        self,
        df_src: pd.DataFrame,
        raws: List[str],
    ) -> List[dict]:
        if df_src.empty or not raws:
            return []
        scope_cols = ["ScopeRoot", "ParentArea", "PipeNodePath", "PipeNodeLevel"]
        present_cols = [c for c in scope_cols if c in df_src.columns]
        if not present_cols:
            return []

        entries: List[dict] = []
        seen: set[tuple] = set()
        raw_series = df_src["Raw_3D_PipeCode"].astype(str).str.strip()
        for raw in raws:
            raw_text = str(raw).strip()
            if not raw_text:
                continue
            raw_rows = df_src[raw_series.eq(raw_text)]
            if raw_rows.empty:
                continue
            for _, row in raw_rows.iterrows():
                entry = {"管線號": raw_text}
                for col in present_cols:
                    value = str(row.get(col, "")).strip()
                    if value:
                        entry[col] = self.scope_value(col, value)
                if len(entry) <= 1:
                    continue
                key = tuple((k, str(entry[k])) for k in sorted(entry.keys()))
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
        return entries

    @staticmethod
    def unique_pipe_count(df_src: pd.DataFrame) -> int:
        if "Raw_3D_PipeCode" not in df_src.columns:
            return 0
        return len(
            CommonUtils.unique_preserve(
                [
                    str(v).strip()
                    for v in df_src["Raw_3D_PipeCode"].tolist()
                    if str(v).strip()
                ]
            )
        )

    @staticmethod
    def sort_group_entries(entries: List[dict], key_name: str = "群組") -> List[dict]:
        def _parse_numeric_group(g: str):
            g = str(g).strip()
            if not g:
                return None
            if g.isdigit():
                return (int(g), None)
            if re.fullmatch(r"\d+-\d+", g):
                main_s, sub_s = g.split("-", 1)
                try:
                    return (int(main_s), int(sub_s))
                except ValueError:
                    return None
            return None

        def _natural_key(s: str):
            parts = re.findall(r"\d+|\D+", str(s))
            key = []
            for part in parts:
                key.append(int(part) if part.isdigit() else part.lower())
            return tuple(key)

        def _key(e: dict):
            g = str(e.get(key_name, "")).strip()
            parsed = _parse_numeric_group(g)
            if parsed is not None:
                main, sub = parsed
                has_sub = 1 if sub is not None else 0
                sub_val = sub if sub is not None else 0
                return (0, main, has_sub, sub_val, g)
            return (1,) + _natural_key(g)

        return sorted(entries, key=_key)

    # ─────────────────────────────────────────────────────────
    # File export
    # ─────────────────────────────────────────────────────────

    def export_json_v2(
        self,
        iso_match_path: str,
        cases: List[Dict[str, dict]],
        out_dir: Optional[str] = None,
    ) -> int:
        self._log_print("[Step4_v2] ===== 進入 export_json_v2 =====")
        self._log_print(f"[Step4_v2] iso_match_path = {iso_match_path}")
        self._log_print(f"[Step4_v2] out_dir (原始) = {out_dir}")
        self._log_print(f"[Step4_v2] cases 數量 = {len(cases)}")

        df = self.load_dataframe(iso_match_path)
        self._log_print(f"[Step4_v2] iso_match 欄位 = {list(df.columns)}")

        if out_dir is None or not str(out_dir).strip():
            out_dir = os.path.dirname(os.path.abspath(iso_match_path)) or os.getcwd()
        self._log_print(f"[Step4_v2] out_dir (實際使用) = {out_dir}")
        os.makedirs(out_dir, exist_ok=True)

        file_count = 0
        for idx, case in enumerate(cases, start=1):
            self._log_print(f"[Step4_v2] case_index = {idx}")
            result = self.build_case_result(df, case, log=True)

            if result.filtered_rows == 0:
                self._log_print("[Step4_v2] case 套用 filters 後沒有任何列，跳過本 case。")
                continue
            if result.export_rows == 0:
                self._log_print("[Step4_v2] safety filter 後沒有可安全匯出的列，跳過本 case。")
                continue
            if not result.entries:
                self._log_print(
                    "[Step4_v2] 分組後沒有任何有效群組（可能 key 都是空或無 Raw_3D_PipeCode）。"
                )
                continue

            safe_name = CommonUtils.sanitize_filename(result.name)
            out_path = os.path.join(out_dir, f"{safe_name}.json")
            self._log_print(
                "[Step4_v2] 寫出 JSON："
                f"{out_path} | groups={result.group_count}, "
                f"pipes={result.pipe_count}, scopes={result.scope_count}"
            )
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result.entries, f, ensure_ascii=False, indent=2)
            file_count += 1

        self._log_print(
            f"[Step4_v2] ===== 結束 export_json_v2，輸出檔案數 = {file_count} ====="
        )
        return file_count
