# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import unittest

import pandas as pd

from core.resolved_mapping import build_resolved_mapping


class ResolvedMappingMetadataTests(unittest.TestCase):
    @staticmethod
    def _match_row(spool: str, pipe: str) -> dict:
        return {
            "管線編號": pipe,
            "流水號": spool,
            "ISO_Match_Key": pipe,
            "Raw_3D_PipeCode": pipe,
            "PipeNodePath": f"/MODEL___{pipe}",
            "ScopeRoot": "/MODEL",
            "PipeNodeLevel": "3",
            "NeedsDecision": "0",
            "MatchType": "fuzzy_manual",
            "系統": "",
            "Class": "",
            "Size": "",
            "drawing_group2": "",
            "區域": "",
        }

    def test_backfills_blank_business_fields_by_unique_serial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            iso_match = os.path.join(temp_dir, "iso_match.xlsx")
            iso_source = os.path.join(temp_dir, "iso_source.xlsx")
            output = os.path.join(temp_dir, "resolved_mapping.csv")

            first = self._match_row("1", "/MATCH-A")
            second = self._match_row("2", "/MATCH-B")
            second.update(
                {
                    "系統": "NI",
                    "Class": "S1P4",
                    "Size": "2",
                    "drawing_group2": "/MATCH-B-SOURCE",
                    "區域": "製程",
                }
            )
            pd.DataFrame([first, second]).to_excel(
                iso_match,
                index=False,
                sheet_name="結果",
            )
            pd.DataFrame(
                [
                    {
                        "流水號": "1",
                        "管線編號": "/SOURCE-MUST-NOT-OVERRIDE",
                        "系統": "P",
                        "Class": "S1PA",
                        "Size": "1",
                        "drawing_group2": "/MATCH-A-SOURCE",
                        "區域": "公用",
                    },
                    {
                        "流水號": "2",
                        "管線編號": "/SOURCE-MUST-NOT-OVERRIDE-2",
                        "系統": "NI",
                        "Class": "S1P4",
                        "Size": "2",
                        "drawing_group2": "/MATCH-B-SOURCE",
                        "區域": "製程",
                    },
                ]
            ).to_excel(iso_source, index=False, sheet_name="DWG NO.ALL")

            stats = build_resolved_mapping(
                iso_match,
                output,
                iso_source_path=iso_source,
                iso_source_sheet="DWG NO.ALL",
                iso_source_spool_col="流水號",
            )
            result = pd.read_csv(
                output,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")
            by_spool = result.set_index("流水號")

            self.assertEqual(by_spool.loc["1", "系統"], "P")
            self.assertEqual(by_spool.loc["1", "Class"], "S1PA")
            self.assertEqual(by_spool.loc["1", "Size"], "1")
            self.assertEqual(
                by_spool.loc["1", "drawing_group2"],
                "/MATCH-A-SOURCE",
            )
            self.assertEqual(by_spool.loc["1", "區域"], "公用")
            self.assertEqual(by_spool.loc["1", "管線編號"], "/MATCH-A")
            self.assertEqual(by_spool.loc["2", "系統"], "NI")
            self.assertEqual(stats["metadata_joined_rows"], 2)
            self.assertEqual(stats["metadata_backfilled_rows"], 1)
            self.assertEqual(stats["metadata_backfilled_cells"], 5)
            self.assertEqual(stats["metadata_conflicts"], 0)
            self.assertEqual(stats["metadata_skipped"], 0)
            self.assertEqual(stats["metadata_errors"], 0)
            self.assertEqual(stats["metadata_error"], "")

    def test_ambiguous_source_serial_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            iso_match = os.path.join(temp_dir, "iso_match.xlsx")
            iso_source = os.path.join(temp_dir, "iso_source.xlsx")
            output = os.path.join(temp_dir, "resolved_mapping.csv")
            pd.DataFrame([self._match_row("1", "/MATCH-A")]).to_excel(
                iso_match,
                index=False,
                sheet_name="結果",
            )
            pd.DataFrame(
                [
                    {"流水號": "1", "系統": "P"},
                    {"流水號": "1", "系統": "NI"},
                ]
            ).to_excel(iso_source, index=False, sheet_name="DWG NO.ALL")

            stats = build_resolved_mapping(
                iso_match,
                output,
                iso_source_path=iso_source,
                iso_source_sheet="DWG NO.ALL",
                iso_source_spool_col="流水號",
            )
            result = pd.read_csv(
                output,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")

            self.assertEqual(result.iloc[0]["系統"], "")
            self.assertEqual(stats["metadata_ambiguous_spools"], 1)
            self.assertEqual(stats["metadata_joined_rows"], 0)
            self.assertEqual(stats["metadata_backfilled_rows"], 0)

    def test_unavailable_source_is_fail_soft_and_preserves_mapping(self):
        for mode in ("missing", "unreadable"):
            with self.subTest(mode=mode), \
                    tempfile.TemporaryDirectory() as temp_dir:
                iso_match = os.path.join(temp_dir, "iso_match.xlsx")
                iso_source = os.path.join(temp_dir, "iso_source.xlsx")
                output = os.path.join(temp_dir, "resolved_mapping.csv")
                logs: list[str] = []

                row = self._match_row("9", "/MATCH-KEEP")
                row.update(
                    {
                        "系統": "NI",
                        "Class": "S1P4",
                        "Size": "2",
                        "drawing_group2": "/MATCH-KEEP-SOURCE",
                        "區域": "製程",
                    }
                )
                pd.DataFrame([row]).to_excel(
                    iso_match,
                    index=False,
                    sheet_name="結果",
                )
                if mode == "unreadable":
                    with open(iso_source, "wb") as handle:
                        handle.write(b"not an xlsx workbook")

                stats = build_resolved_mapping(
                    iso_match,
                    output,
                    log_fn=logs.append,
                    iso_source_path=iso_source,
                    iso_source_sheet="DWG NO.ALL",
                    iso_source_spool_col="流水號",
                )
                result = pd.read_csv(
                    output,
                    dtype=str,
                    encoding="utf-8-sig",
                ).fillna("")
                built = result.iloc[0]

                self.assertEqual(built["流水號"], "9")
                self.assertEqual(built["管線編號"], "/MATCH-KEEP")
                self.assertEqual(built["ISO_Match_Key"], "/MATCH-KEEP")
                self.assertEqual(built["Raw_3D_PipeCode"], "/MATCH-KEEP")
                self.assertEqual(built["系統"], "NI")
                self.assertEqual(built["drawing_group2"], "/MATCH-KEEP-SOURCE")
                self.assertEqual(stats["metadata_skipped"], 1)
                self.assertEqual(stats["metadata_errors"], 1)
                self.assertTrue(stats["metadata_error"])
                self.assertEqual(stats["metadata_backfilled_rows"], 0)
                self.assertTrue(
                    any(
                        "ISO metadata 回填略過" in message
                        and iso_source in message
                        for message in logs
                    )
                )


if __name__ == "__main__":
    unittest.main()
