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
from utils.iso_schema import detect_schema, load_iso_line_key_set


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

    def test_iso_key_set_includes_v2_size_normalization(self):
        with self._tmpdir() as d:
            iso_path = os.path.join(d, "ISO_LIST.xlsx")
            pd.DataFrame(
                [{"Line num": "/3_4-S11G-N4-20951Q", "流水號": "37"}]
            ).to_excel(
                iso_path,
                index=False,
                sheet_name="DWG NO.ALL",
                engine="openpyxl",
            )

            keys = load_iso_line_key_set(
                iso_path,
                sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
            )

            self.assertIn("3/4-S11G-N4-20951Q", keys)

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

    def test_identity_resolver_does_not_promote_iso_suffix_family(self):
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

        self.assertEqual(result["Raw_3D_PipeCode"], "")
        self.assertEqual(result["ISO_Match_Key"], "")
        self.assertEqual(result["CandidateCount"], 0)

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

            self.assertEqual(n, 0)
            self.assertTrue(result.empty)
            self.assertTrue((trace["candidate_count"].astype(str) == "0").all())
            self.assertTrue((trace["included_in_minus_1"].astype(str) == "0").all())
            self.assertTrue(
                (trace["recall_candidate_count"].astype(int) > 0).all()
            )
            self.assertIn(
                "TRIM-6FL216Q-N3-001",
                set(candidates["iso_candidate"].astype(str)),
            )
            recall_rows = candidates[
                candidates["candidate_kind"].astype(str).eq("iso_reverse_recall")
            ]
            self.assertGreaterEqual(len(recall_rows), 2)
            self.assertLess(float(recall_rows.iloc[0]["score"]), 0.9)

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
            self.assertEqual(
                data,
                [
                    {
                        "流水號": "1",
                        "管線號": ["/A-LINE"],
                        "搜尋範圍": [
                            {"管線號": "/A-LINE", "ParentArea": "/A"}
                        ],
                    }
                ],
            )

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
                    {
                        "流水號": "1",
                        "管線號": ["/A-LINE"],
                        "搜尋範圍": [
                            {"管線號": "/A-LINE", "ParentArea": "/A"}
                        ],
                    },
                    {
                        "流水號": "2",
                        "管線號": ["/B-LINE-A"],
                        "搜尋範圍": [
                            {"管線號": "/B-LINE-A", "ParentArea": "/A"}
                        ],
                    },
                ],
            )

    def test_json_export_includes_scope_hints_for_navis_import(self):
        with self._tmpdir() as d:
            mapping = os.path.join(d, "resolved_mapping.csv")
            pd.DataFrame(
                [
                    {
                        "Resolved": "1",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/1-S11U-AP-US02",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/HPS-PIPE",
                        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02",
                        "PipeNodeLevel": "4",
                    },
                    {
                        "Resolved": "1",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/1-S11U-AP-US02/B1",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/1-S11U-AP-US02",
                        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02___/1-S11U-AP-US02/B1",
                        "PipeNodeLevel": "5",
                    },
                ]
            ).to_csv(mapping, index=False, encoding="utf-8-sig")

            count = JsonExporter().export_json_v2(
                mapping,
                [{"name": "scope_selection", "group_key": "流水號", "filters": {}}],
                out_dir=d,
            )
            self.assertEqual(count, 1)
            with open(os.path.join(d, "scope_selection.json"), encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data[0]["流水號"], "16")
            self.assertEqual(
                data[0]["管線號"],
                ["/1-S11U-AP-US02", "/1-S11U-AP-US02/B1"],
            )
            self.assertEqual(
                data[0]["搜尋範圍"],
                [
                    {
                        "管線號": "/1-S11U-AP-US02",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/HPS-PIPE",
                        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02",
                        "PipeNodeLevel": 4,
                    },
                    {
                        "管線號": "/1-S11U-AP-US02/B1",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/1-S11U-AP-US02",
                        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02___/1-S11U-AP-US02/B1",
                        "PipeNodeLevel": 5,
                    },
                ],
            )

    def test_json_export_flat_mode_uses_schema_consistent_pipe_arrays(self):
        with self._tmpdir() as d:
            mapping = os.path.join(d, "resolved_mapping.csv")
            pd.DataFrame(
                [
                    {
                        "Resolved": "1",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/1-S11U-AP-US02",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/HPS-PIPE",
                        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02",
                        "PipeNodeLevel": "4",
                    },
                ]
            ).to_csv(mapping, index=False, encoding="utf-8-sig")

            count = JsonExporter().export_json_v2(
                mapping,
                [{"name": "flat_selection", "group_key": "__FLAT__", "filters": {}}],
                out_dir=d,
            )
            self.assertEqual(count, 1)
            with open(os.path.join(d, "flat_selection.json"), encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(
                data,
                [
                    {
                        "管線號": ["/1-S11U-AP-US02"],
                        "搜尋範圍": [
                            {
                                "管線號": "/1-S11U-AP-US02",
                                "ScopeRoot": "CHO_NO_INSU.RVM",
                                "ParentArea": "/HPS-PIPE",
                                "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AP-US02",
                                "PipeNodeLevel": 4,
                            }
                        ],
                    }
                ],
            )

    def test_json_export_case_result_reports_safety_blocks(self):
        df = pd.DataFrame(
            [
                {
                    "Resolved": "1",
                    "流水號": "1",
                    "Raw_3D_PipeCode": "/OK",
                },
                {
                    "Resolved": "0",
                    "ResolutionStatus": "needs_decision",
                    "流水號": "2",
                    "Raw_3D_PipeCode": "/PENDING",
                },
            ]
        )
        result = JsonExporter().build_case_result(
            df,
            {"name": "selection", "group_key": "流水號", "filters": {}},
        )

        self.assertEqual(result.filtered_rows, 2)
        self.assertEqual(result.export_rows, 1)
        self.assertEqual(result.blocked_rows, 1)
        self.assertEqual(result.pipe_count, 1)
        self.assertEqual(result.group_count, 1)

    def test_json_export_defaults_to_group_column_when_present(self):
        df = pd.DataFrame(
            [
                {
                    "Resolved": "1",
                    "流水號": "1",
                    "群組": "流水號1_流水號2",
                    "Raw_3D_PipeCode": "/LINE-A",
                },
                {
                    "Resolved": "1",
                    "流水號": "2",
                    "群組": "流水號1_流水號2",
                    "Raw_3D_PipeCode": "/LINE-B",
                },
            ]
        )

        result = JsonExporter().build_case_result(
            df,
            {"name": "selection", "filters": {}},
        )

        self.assertEqual(result.group_key, "群組")
        self.assertEqual(result.group_count, 1)
        self.assertEqual(
            result.entries,
            [
                {
                    "群組": "流水號1_流水號2",
                    "管線號": ["/LINE-A", "/LINE-B"],
                }
            ],
        )

    def test_json_export_defaults_to_serial_when_group_column_is_empty(self):
        df = pd.DataFrame(
            [
                {
                    "Resolved": "1",
                    "流水號": "1",
                    "群組": None,
                    "Raw_3D_PipeCode": "/LINE-A",
                },
            ]
        )

        result = JsonExporter().build_case_result(
            df,
            {"name": "selection", "filters": {}},
        )

        self.assertEqual(result.group_key, "流水號")
        self.assertEqual(result.entries[0]["流水號"], "1")

    def test_resolved_mapping_preserves_iso_source_classification_columns(self):
        with self._tmpdir() as d:
            iso_match = os.path.join(d, "iso_match.xlsx")
            mapping = os.path.join(d, "resolved_mapping.csv")
            pd.DataFrame(
                [
                    {
                        "流水號": "16",
                        "管線編號": "/LINE-A",
                        "Raw_3D_PipeCode": "/LINE-A",
                        "NeedsDecision": "0",
                        "MatchType": "strict",
                        "系統": "S11U",
                        "保溫": "NO_INSU",
                        "未來分類": "A-ZONE",
                        "__line_norm": "internal",
                    }
                ]
            ).to_excel(iso_match, index=False, sheet_name="結果")

            build_resolved_mapping(iso_match, mapping)
            result = pd.read_csv(mapping, dtype=str, encoding="utf-8-sig").fillna("")

            self.assertIn("系統", result.columns)
            self.assertIn("保溫", result.columns)
            self.assertIn("未來分類", result.columns)
            self.assertNotIn("__line_norm", result.columns)
            row = result.iloc[0]
            self.assertEqual(row["系統"], "S11U")
            self.assertEqual(row["保溫"], "NO_INSU")
            self.assertEqual(row["未來分類"], "A-ZONE")

    def test_resolved_mapping_keeps_distinct_pipe_node_paths(self):
        with self._tmpdir() as d:
            iso_match = os.path.join(d, "iso_match.xlsx")
            mapping = os.path.join(d, "resolved_mapping.csv")
            p1 = "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/LINE"
            p2 = "HP6.nwd___CHO_INSU.RVM___/HPS___/HPS-PIPE___/LINE"
            pd.DataFrame(
                [
                    {
                        "流水號": "16",
                        "管線編號": "/LINE",
                        "Raw_3D_PipeCode": "/LINE",
                        "PipeNodePath": p1,
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "ParentArea": "/HPS-PIPE",
                        "PipeNodeLevel": "4",
                        "NeedsDecision": "1",
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "MatchType": "strict",
                    },
                    {
                        "流水號": "16",
                        "管線編號": "/LINE",
                        "Raw_3D_PipeCode": "/LINE",
                        "PipeNodePath": p2,
                        "ScopeRoot": "CHO_INSU.RVM",
                        "ParentArea": "/HPS-PIPE",
                        "PipeNodeLevel": "4",
                        "NeedsDecision": "1",
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "MatchType": "strict",
                    },
                ]
            ).to_excel(iso_match, index=False, sheet_name="結果")

            stats = build_resolved_mapping(iso_match, mapping)
            result = pd.read_csv(mapping, dtype=str, encoding="utf-8-sig").fillna("")

            self.assertEqual(stats["needs_decision"], 2)
            self.assertEqual(len(result), 2)
            self.assertEqual(set(result["PipeNodePath"]), {p1, p2})


if __name__ == "__main__":
    unittest.main()
