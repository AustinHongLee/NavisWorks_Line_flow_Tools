# -*- coding: utf-8 -*-
"""管線群組整理：123_minus_1.csv → 123_minus_2.*

重構為 `PipelineGrouper` 類別。
"""
from __future__ import annotations

import re
import os
from typing import Tuple

import pandas as pd

from utils.utils_common import CommonUtils, PipelineKeyExtractor


class PipelineGrouper:
    def __init__(self, sep: str = "___", raw_prefix: str = "/"):
        self.sep = sep
        self.raw_prefix = raw_prefix

    def parse_and_export(
        self,
        in_csv: str,
        out_csv: str,
        excel_path: str,
    ) -> Tuple[int, int]:
        if not os.path.exists(in_csv):
            raise FileNotFoundError(
                f"[Step2] 找不到中繼檔 123_minus_1.csv：{in_csv}"
            )

        try:
            df = pd.read_csv(in_csv, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError as e:
            msg = (
                "[Step2] 讀取 123_minus_1.csv 編碼失敗，請確認是否為 "
                "UTF-8-SIG。原始錯誤："
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
                "[Step2] 讀取 123_minus_1.csv 失敗："
                f"{in_csv}，請檢查檔案是否被鎖定或格式是否正確。詳細：{e}"
            ) from e

        df = df.fillna("")

        if "Raw_last" not in df.columns:
            raw_col = CommonUtils.detect_raw_column(df)
            raw_series = df[raw_col].astype(str)
            if self.sep:
                raw_last = raw_series.str.split(self.sep).str[-1].str.strip()
            else:
                raw_last = raw_series.str.strip()

            def _apply_prefix(x: str) -> str:
                if not x:
                    return ""
                core = re.sub(r'^[^A-Za-z0-9]+', '', x)
                if self.raw_prefix:
                    return self.raw_prefix + core
                return core

            df["Raw_last"] = raw_last.apply(_apply_prefix)

        df["__pipeline_seg"] = df.apply(
            lambda r: PipelineKeyExtractor.guess_pipeline_segment(
                [x for x in str(r.get("Path", "")).split(self.sep) if x]
            )
            or str(r.get("Raw_last", "")).lstrip("/"),
            axis=1,
        )
        df["Line_combined"] = df["__pipeline_seg"].astype(str).apply(
            CommonUtils.normalize_line
        )

        df["Raw_last"] = df["Raw_last"].astype(str).str.strip()
        df["Line_combined"] = df["Line_combined"].astype(str).str.strip()

        detail_df = df.copy()
        detail_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

        group_df = (
            detail_df.groupby("Line_combined", sort=False)
            .agg(
                筆數=("Raw_last", "size"),
                流水號群組=(
                    "Raw_last",
                    lambda s: "_".join(CommonUtils.unique_preserve(s)),
                ),
            )
            .reset_index()
        )

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            detail_df.to_excel(writer, index=False, sheet_name="明細")
            group_df.to_excel(writer, index=False, sheet_name="群組")

        return len(detail_df), len(group_df)
