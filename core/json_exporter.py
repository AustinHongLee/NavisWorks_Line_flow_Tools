# -*- coding: utf-8 -*-
"""JSON 匯出：多案例篩選 → JSON

重構為 `JsonExporter` 類別。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

import pandas as pd

from utils.utils_common import CommonUtils, FileLogger


class JsonExporter:
    def __init__(self, logger: FileLogger | None = None):
        self.logger = logger

    def _log_print(self, msg: str) -> None:
        print(msg)
        if self.logger is not None:
            self.logger.append(msg)

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

        if not os.path.exists(iso_match_path):
            self._log_print("[Step4_v2][ERROR] 找不到 iso_match 檔案")
            raise FileNotFoundError(f"找不到 iso 比對結果：{iso_match_path}")

        ext = os.path.splitext(iso_match_path)[1].lower()
        if ext in (".xlsx", ".xlsm", ".xls"):
            self._log_print("[Step4_v2] 讀取 iso_match 為 Excel 格式")
            xls = pd.ExcelFile(iso_match_path, engine="openpyxl")
            sheet_name = (
                "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
            )
            self._log_print(
                f"[Step4_v2] 使用工作表 sheet = {sheet_name}"
            )
            df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str).fillna(
                ""
            )
        else:
            self._log_print("[Step4_v2] 讀取 iso_match 為 CSV 格式")
            df = pd.read_csv(
                iso_match_path,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")

        df = df.rename(columns={c: str(c).strip() for c in df.columns})
        self._log_print(f"[Step4_v2] iso_match 欄位 = {list(df.columns)}")

        # 向後相容：舊檔案可能使用舊欄位名稱
        if "Raw_3D_PipeCode" not in df.columns and "Raw_last" in df.columns:
            df = df.rename(columns={"Raw_last": "Raw_3D_PipeCode"})

        if "Raw_3D_PipeCode" not in df.columns:
            self._log_print("[Step4_v2][ERROR] iso_match 缺少 Raw_3D_PipeCode 欄位")
            raise ValueError("改比對結果缺少必要欄位『Raw_3D_PipeCode』")
        df["Raw_3D_PipeCode"] = df["Raw_3D_PipeCode"].astype(str).str.strip()

        if out_dir is None or not str(out_dir).strip():
            out_dir = (
                os.path.dirname(os.path.abspath(iso_match_path))
                or os.getcwd()
            )
        self._log_print(f"[Step4_v2] out_dir (實際使用) = {out_dir}")
        os.makedirs(out_dir, exist_ok=True)

        def _build_basic_groups(df_src: pd.DataFrame, group_key: str) -> List[dict]:
            entries: List[dict] = []
            if group_key not in df_src.columns:
                return entries
            sub_df = df_src[(df_src["Raw_3D_PipeCode"] != "")]
            for key, sub in sub_df.groupby(group_key, sort=False):
                key_v = str(key).strip()
                if not key_v:
                    continue
                raws = CommonUtils.unique_preserve(sub["Raw_3D_PipeCode"].tolist())
                if not raws:
                    continue
                entries.append({group_key: key_v, "管線號": raws})
            return entries

        def _build_flat_list(df_src: pd.DataFrame) -> List[dict]:
            """不分組，純列出每筆 Raw_3D_PipeCode。"""
            sub_df = df_src[(df_src["Raw_3D_PipeCode"] != "")]
            raws = CommonUtils.unique_preserve(sub_df["Raw_3D_PipeCode"].tolist())
            if not raws:
                return []
            return [{"管線號": r} for r in raws]

        def _sort_group_entries(entries: List[dict], key_name: str = "群組") -> List[dict]:
            """依分組欄位排序：

            規則：
            - 純數字，例如 "30" → 視為主軸 30、無副軸
            - "主軸-副軸" 數字格式，例如 "30-1" → 主軸 30、副軸 1
            - 以上兩種都視為「數字群組」，會排在前面，
              先依主軸數值、再依是否有副軸（無副軸在前）、
              最後依副軸數值排序。
            - 其他非純數字的群組：保留為一般字串，排在數字群組之後，
              並以字典順序排序。
            """

            def _parse_numeric_group(g: str):
                g = str(g).strip()
                if not g:
                    return None
                if g.isdigit():
                    # 純數字：主軸 = 整數值，副軸 = None
                    return (int(g), None)
                # 主軸-副軸 的數字格式，例如 30-1
                if re.fullmatch(r"\d+-\d+", g):
                    main_s, sub_s = g.split("-", 1)
                    try:
                        return (int(main_s), int(sub_s))
                    except ValueError:
                        return None
                return None

            def _natural_key(s: str):
                """產生類似 Windows 檔案總管的自然排序 key。

                將字串拆成「數字片段」與「非數字片段」，
                數字轉成 int，其餘轉成小寫字串，
                例如："A10B2" -> ["a", 10, "b", 2]
                """

                s = str(s)
                parts = re.findall(r"\d+|\D+", s)
                key = []
                for part in parts:
                    if part.isdigit():
                        key.append(int(part))
                    else:
                        key.append(part.lower())
                return tuple(key)

            def _key(e: dict):
                g = str(e.get(key_name, "")).strip()
                parsed = _parse_numeric_group(g)
                if parsed is not None:
                    main, sub = parsed
                    # 數字群組：category = 0
                    # 無副軸排在有副軸前面
                    has_sub = 1 if sub is not None else 0
                    sub_val = sub if sub is not None else 0
                    return (0, main, has_sub, sub_val, g)
                # 其餘一律當作一般字串處理，category = 1
                return (1,) + _natural_key(g)

            return sorted(entries, key=_key)

        file_count = 0

        for idx, case in enumerate(cases, start=1):
            name = str(case.get("name", "")).strip() or "case"
            filters = case.get("filters") or {}
            group_key = str(case.get("group_key", "")).strip()

            self._log_print("[Step4_v2] --- case 開始 ---")
            self._log_print(f"[Step4_v2] case_index = {idx}")
            self._log_print(f"[Step4_v2] case_name  = {name}")
            self._log_print(f"[Step4_v2] group_key = '{group_key}'")
            self._log_print(f"[Step4_v2] filters   = {filters}")

            sub = df
            for col, allowed in filters.items():
                col = str(col).strip()
                values = [
                    str(v).strip() for v in (allowed or []) if str(v).strip()
                ]
                self._log_print(
                    f"[Step4_v2]  篩選欄位 = '{col}', 值 = {values}"
                )

                if not col or col not in sub.columns:
                    self._log_print(
                        "[Step4_v2][WARN] 欄位不存在於 iso_match，該 case 視為無結果。"
                    )
                    sub = sub.iloc[0:0]
                    break
                if not values:
                    self._log_print("[Step4_v2]  該欄位沒有任何有效值，略過此欄位。")
                    continue
                before = len(sub)
                sub = sub[
                    sub[col].astype(str).str.strip().isin(values)
                ]
                after = len(sub)
                self._log_print(
                    f"[Step4_v2]  篩選後筆數：{before} -> {after}"
                )

            if sub.empty:
                self._log_print(
                    "[Step4_v2] case 套用 filters 後沒有任何列，跳過本 case。"
                )
                continue

            if not group_key:
                self._log_print(
                    "[Step4_v2] 未指定 group_key，使用預設邏輯。"
                )
                if "群組" in sub.columns:
                    group_key = "群組"
                elif "流水號" in sub.columns:
                    group_key = "流水號"
                else:
                    group_key = "__ALL__"
            else:
                self._log_print(
                    f"[Step4_v2] 使用指定 group_key = '{group_key}'"
                )

            if group_key == "__FLAT__":
                self._log_print(
                    "[Step4_v2] group_key='__FLAT__'，不分組，純列出管線號。"
                )
                merged_entries = _build_flat_list(sub)
                if not merged_entries:
                    self._log_print(
                        "[Step4_v2] 不分組模式下沒有任何 Raw_3D_PipeCode。"
                    )
                    continue
            elif group_key == "__ALL__":
                self._log_print(
                    "[Step4_v2] group_key='__ALL__'，全部視為一組 ALL。"
                )
                raws_all = CommonUtils.unique_preserve(
                    sub["Raw_3D_PipeCode"].tolist()
                )
                if not raws_all:
                    self._log_print(
                        "[Step4_v2] ALL 群組下沒有任何 Raw_3D_PipeCode，有點異常。"
                    )
                    continue
                merged_entries = [{group_key: "ALL", "管線號": raws_all}]
            else:
                self._log_print(
                    f"[Step4_v2] 依 group_key='{group_key}' 分組 Raw_3D_PipeCode。"
                )
                merged_entries = _build_basic_groups(sub, group_key)
                if not merged_entries:
                    self._log_print(
                        "[Step4_v2] 分組後沒有任何有效群組（可能 key 都是空或無 Raw_3D_PipeCode）。"
                    )
                    continue

                # 依群組排序：數字群組優先且按數值大小，其餘為一般字串
                merged_entries = _sort_group_entries(merged_entries, key_name=group_key)

            safe_name = CommonUtils.sanitize_filename(name)
            out_path = os.path.join(out_dir, f"{safe_name}.json")
            self._log_print(f"[Step4_v2] 寫出 JSON 檔案：{out_path}")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(merged_entries, f, ensure_ascii=False, indent=2)
            file_count += 1

        self._log_print(
            f"[Step4_v2] ===== 結束 export_json_v2，輸出檔案數 = {file_count} ====="
        )

        return file_count
