# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
import unittest

import pandas as pd

from core.identity_resolver import IdentityResolver
from core.json_exporter import JsonExporter
from core.pipeline_extractor import PipelineExtractor
from core.resolved_mapping import build_resolved_mapping
from utils.iso_schema import detect_schema


class PipelineRegressionTests(unittest.TestCase):
    def _tmpdir(self):
        return tempfile.TemporaryDirectory(
            dir=os.getcwd(),
            prefix="tmp_unit_",
            ignore_cleanup_errors=True,
        )

    def _write_iso(self, path: str):
        df = pd.DataFrame(
            [
                {"Line num": "/1-S11U-AI-00001", "流水號": "1"},
                {"Line num": "/4-S11-P-60338", "流水號": "2"},
            ]
        )
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="DWG NO.ALL")
            pd.DataFrame({"note": ["x"]}).to_excel(
                writer,
                index=False,
                sheet_name="列印用",
            )

    def test_iso_schema_prefers_cp129_columns(self):
        with self._tmpdir() as d:
            iso_path = os.path.join(d, "ISO_LIST.xlsx")
            self._write_iso(iso_path)
            xls = pd.ExcelFile(iso_path, engine="openpyxl")
            try:
                schema = detect_schema(xls)
            finally:
                xls.close()

            self.assertEqual(schema.sheet_name, "DWG NO.ALL")
            self.assertEqual(schema.pipe_col, "Line num")
            self.assertEqual(schema.spool_col, "流水號")

    def test_identity_resolver_uses_iso_whitelist(self):
        known = {"1-S11U-AI-00001", "4-S11-P-60338"}
        resolver = IdentityResolver(known_iso_keys=known)

        area = resolver.resolve(
            pd.Series(
                {
                    "Path": "model.nwd___/CABLETRAY___/4F-6F",
                    "DisplayName": "/4F-6F",
                    "PipelineId": "/4F-6F",
                }
            )
        )
        self.assertEqual(area["Raw_3D_PipeCode"], "")

        pipe = resolver.resolve(
            pd.Series(
                {
                    "Path": "x___BRANCH 1 of PIPE /4-S11-P-60338-H50",
                    "DisplayName": "BRANCH 1 of PIPE /4-S11-P-60338-H50",
                    "PipelineId": "BRANCH 1 of PIPE /4-S11-P-60338-H50",
                }
            )
        )
        self.assertEqual(pipe["Raw_3D_PipeCode"], "/4-S11-P-60338-H50")
        self.assertEqual(pipe["ISO_Match_Key"], "4-S11-P-60338-H50")
        self.assertIn("去末段後命中", pipe["IdentityReason"])

    def test_identity_resolver_accepts_iso_suffix_family(self):
        known = {"TRIM-6FL216Q-N3-001"}
        resolver = IdentityResolver(known_iso_keys=known)

        result = resolver.resolve(
            pd.Series(
                {
                    "Path": (
                        "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-TRIM"
                        "___/TRIM-6FL216Q-N3"
                    ),
                    "DisplayName": "/TRIM-6FL216Q-N3",
                    "Level": "4",
                    "PipelineId": "/TRIM-6FL216Q-N3",
                }
            )
        )

        self.assertEqual(result["Raw_3D_PipeCode"], "/TRIM-6FL216Q-N3")
        self.assertEqual(result["ISO_Match_Key"], "TRIM-6FL216Q-N3")
        self.assertIn("ISO 去末段後命中", result["IdentityReason"])

    def test_pipeline_extractor_filters_to_iso_lines(self):
        with self._tmpdir() as d:
            iso_path = os.path.join(d, "ISO_LIST.xlsx")
            first_path = os.path.join(d, "First_try.csv")
            out_path = os.path.join(d, "123_minus_1.csv")
            self._write_iso(iso_path)
            pd.DataFrame(
                [
                    {
                        "Path": "model.nwd",
                        "DisplayName": "model.nwd",
                        "Class": "File",
                        "Level": "0",
                        "PipelineId": "model.nwd",
                    },
                    {
                        "Path": "model.nwd___/CABLETRAY___/4F-6F",
                        "DisplayName": "/4F-6F",
                        "Class": "Group",
                        "Level": "2",
                        "PipelineId": "/4F-6F",
                    },
                    {
                        "Path": "model.nwd___/A___/1-S11U-AI-00001",
                        "DisplayName": "/1-S11U-AI-00001",
                        "Class": "Group",
                        "Level": "2",
                        "PipelineId": "/1-S11U-AI-00001",
                    },
                ]
            ).to_csv(first_path, index=False, encoding="utf-8-sig")

            n = PipelineExtractor().build_intermediate(
                first_path,
                out_path,
                scan_mode="full",
                iso_list_path=iso_path,
                iso_sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
            )
            result = pd.read_csv(out_path, dtype=str, encoding="utf-8-sig").fillna("")
            self.assertEqual(n, 1)
            self.assertEqual(result.iloc[0]["ISO_Match_Key"], "1-S11U-AI-00001")

    def test_pipeline_extractor_traces_iso_suffix_family_candidates(self):
        with self._tmpdir() as d:
            iso_path = os.path.join(d, "ISO_LIST.xlsx")
            first_path = os.path.join(d, "First_try.csv")
            out_path = os.path.join(d, "123_minus_1.csv")
            trace_path = os.path.join(d, "first_try_trace.csv")
            candidates_path = os.path.join(d, "candidates.csv")

            pd.DataFrame(
                [
                    {"Line num": "/TRIM-6FL216Q-N3-001", "流水號": "284"},
                ]
            ).to_excel(
                iso_path,
                index=False,
                sheet_name="DWG NO.ALL",
                engine="openpyxl",
            )
            pd.DataFrame(
                [
                    {
                        "Path": (
                            "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-TRIM"
                            "___/TRIM-6FL216Q-N3"
                        ),
                        "DisplayName": "/TRIM-6FL216Q-N3",
                        "Class": "群組",
                        "Level": "4",
                        "PipelineId": "/TRIM-6FL216Q-N3",
                    },
                    {
                        "Path": (
                            "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-TRIM"
                            "___/TRIM-6FL216Q-N3___/TRIM-6FL216Q-N3/B1"
                        ),
                        "DisplayName": "/TRIM-6FL216Q-N3/B1",
                        "Class": "群組",
                        "Level": "5",
                        "PipelineId": "/TRIM-6FL216Q-N3/B1",
                    },
                ]
            ).to_csv(first_path, index=False, encoding="utf-8-sig")

            n = PipelineExtractor().build_intermediate(
                first_path,
                out_path,
                scan_mode="full",
                iso_list_path=iso_path,
                iso_sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
                write_first_try_trace=True,
                first_try_trace_path=trace_path,
                write_candidates=True,
                candidates_path=candidates_path,
            )

            result = pd.read_csv(out_path, dtype=str, encoding="utf-8-sig").fillna("")
            trace = pd.read_csv(trace_path, dtype=str, encoding="utf-8-sig").fillna("")
            candidates = pd.read_csv(
                candidates_path,
                dtype=str,
                encoding="utf-8-sig",
            ).fillna("")

            self.assertEqual(n, 2)
            self.assertEqual(set(result["ISO_Match_Key"]), {"TRIM-6FL216Q-N3"})
            self.assertTrue((trace["candidate_count"].astype(str) != "0").all())
            self.assertTrue((trace["included_in_minus_1"].astype(str) == "1").all())
            self.assertGreaterEqual(len(candidates), 2)

    def test_resolved_mapping_blocks_collision_from_json(self):
        with self._tmpdir() as d:
            iso_match = os.path.join(d, "iso_match.xlsx")
            mapping = os.path.join(d, "resolved_mapping.csv")
            pd.DataFrame(
                [
                    {
                        "流水號": "1",
                        "管線編號": "/A-LINE",
                        "Raw_3D_PipeCode": "/A-LINE",
                        "NeedsDecision": "0",
                        "ParentArea": "/A",
                        "MatchType": "strict",
                    },
                    {
                        "流水號": "2",
                        "管線編號": "/B-LINE",
                        "Raw_3D_PipeCode": "/B-LINE-A",
                        "NeedsDecision": "1",
                        "ParentArea": "/A",
                        "CollisionParents": "/A | /B",
                        "MatchType": "strict",
                    },
                ]
            ).to_excel(iso_match, index=False, sheet_name="結果")

            stats = build_resolved_mapping(iso_match, mapping)
            self.assertEqual(stats["resolved"], 1)
            self.assertEqual(stats["needs_decision"], 1)

            count = JsonExporter().export_json_v2(
                mapping,
                [{"name": "selection", "group_key": "流水號", "filters": {}}],
                out_dir=d,
            )
            self.assertEqual(count, 1)
            with open(os.path.join(d, "selection.json"), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data, [{"流水號": "1", "管線號": ["/A-LINE"]}])

            count = JsonExporter().export_json_v2(
                mapping,
                [
                    {
                        "name": "selection_a",
                        "group_key": "流水號",
                        "filters": {"ParentArea": ["/A"]},
                    }
                ],
                out_dir=d,
            )
            self.assertEqual(count, 1)
            with open(os.path.join(d, "selection_a.json"), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(
                data,
                [
                    {"流水號": "1", "管線號": ["/A-LINE"]},
                    {"流水號": "2", "管線號": ["/B-LINE-A"]},
                ],
            )


if __name__ == "__main__":
    unittest.main()
