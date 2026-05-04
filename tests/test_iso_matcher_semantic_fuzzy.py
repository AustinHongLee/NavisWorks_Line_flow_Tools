# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.iso_matcher import (
    IsoMatcher,
    _compute_segment_score,
    _parse_segments,
    _semantic_keys,
)


class IsoMatcherSemanticFuzzyTests(unittest.TestCase):
    def test_parse_size_leading_cp129_line(self):
        seg = _parse_segments("3/4-S11G-N4-20951Q")
        self.assertEqual(seg["size"], "3/4")
        self.assertEqual(seg["system"], "S11G")
        self.assertEqual(seg["class"], "N4")
        self.assertEqual(seg["line_no"], "20951Q")

    def test_parse_canonical_mixed_size_as_one_segment(self):
        seg = _parse_segments("1-1/2-S11G-N4-20951")
        self.assertEqual(seg["size"], "1-1/2")
        self.assertEqual(seg["system"], "S11G")
        self.assertEqual(seg["class"], "N4")
        self.assertEqual(seg["line_no"], "20951")

    def test_semantic_keys_ignore_leading_size_and_suffix(self):
        keys = _semantic_keys("3/4-S11G-N4-20951Q")
        self.assertIn("SYS_CLASS_STEM:S11G|N4|20951", keys)
        self.assertIn("SYS_STEM:S11G|20951", keys)

    def test_score_accepts_line_number_suffix_difference(self):
        score, reason = _compute_segment_score(
            "3/4-S11G-N4-20951Q",
            "1-1/2-S11G-N4-20951",
        )
        self.assertGreaterEqual(score, 0.65)
        self.assertIn("系統=S11G", reason)
        self.assertIn("編號主體=20951", reason)
        self.assertIn("材質=N4", reason)

    def test_score_size_leading_against_integer_size_3d(self):
        score, reason = _compute_segment_score(
            "1/2-S11-P-20909T",
            "14-S11-P-20909",
        )
        self.assertGreaterEqual(score, 0.65)
        self.assertIn("系統=S11", reason)
        self.assertIn("編號主體=20909", reason)

    def test_run_populates_candidate_for_size_leading_suffix_line(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            base = Path(tmp)
            minus_path = base / "123_minus_2.csv"
            iso_path = base / "ISO_LIST.xlsx"
            out_path = base / "iso_match.xlsx"

            pd.DataFrame(
                [{
                    "ISO_Match_Key": "1-1/2-S11G-N4-20951",
                    "Raw_3D_PipeCode": "/A/1-1/2-S11G-N4-20951",
                }]
            ).to_csv(minus_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(
                [{"流水號": "37", "Line num": "3_4-S11G-N4-20951Q"}]
            ).to_excel(iso_path, sheet_name="DWG NO.ALL", index=False)

            matcher = IsoMatcher()
            matcher.run(
                base_dir=str(base),
                minus_csv_path=str(minus_path),
                iso_output_path=str(out_path),
                iso_list_path=str(iso_path),
                iso_sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
                spool_col_override="流水號",
                log_fn=lambda _msg: None,
            )

            self.assertEqual(len(matcher.fuzzy_unmatched), 1)
            candidates = matcher.fuzzy_unmatched[0]["candidates"]
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["line_3d"], "1-1/2-S11G-N4-20951")
            self.assertGreaterEqual(candidates[0]["score"], 0.65)

    def test_run_uses_reverse_recall_candidates_csv_when_minus_has_no_line(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            base = Path(tmp)
            minus_path = base / "123_minus_2.csv"
            iso_path = base / "ISO_LIST.xlsx"
            out_path = base / "iso_match.xlsx"
            candidates_path = base / "candidates.csv"

            pd.DataFrame(
                columns=["ISO_Match_Key", "Raw_3D_PipeCode"]
            ).to_csv(minus_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(
                [{"流水號": "284", "Line num": "/TRIM-6FL216Q-N3-001"}]
            ).to_excel(iso_path, sheet_name="DWG NO.ALL", index=False)
            pd.DataFrame(
                [
                    {
                        "candidate_kind": "iso_reverse_recall",
                        "iso_candidate": "TRIM-6FL216Q-N3-001",
                        "raw": "/TRIM-6FL216Q-N3",
                        "normalized": "TRIM-6FL216Q-N3",
                        "score": "0.8400",
                        "reason": "PipelineId 命中 ISO 變體 TRIM-6FL216Q-N3",
                        "trace_events": "§candidate_kind=iso_reverse_recall",
                    }
                ]
            ).to_csv(candidates_path, index=False, encoding="utf-8-sig")

            matcher = IsoMatcher()
            matcher.run(
                base_dir=str(base),
                minus_csv_path=str(minus_path),
                iso_output_path=str(out_path),
                iso_list_path=str(iso_path),
                iso_sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
                spool_col_override="流水號",
                log_fn=lambda _msg: None,
            )

            self.assertEqual(len(matcher.fuzzy_unmatched), 1)
            candidates = matcher.fuzzy_unmatched[0]["candidates"]
            self.assertEqual(candidates[0]["line_3d"], "TRIM-6FL216Q-N3")
            self.assertEqual(candidates[0]["raw_3d"], "/TRIM-6FL216Q-N3")
            self.assertLess(candidates[0]["score"], 0.9)

    def test_run_scans_first_try_for_reverse_recall_without_candidates_csv(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            base = Path(tmp)
            minus_path = base / "123_minus_2.csv"
            iso_path = base / "ISO_LIST.xlsx"
            first_try_path = base / "First_try.csv"
            out_path = base / "iso_match.xlsx"

            pd.DataFrame(
                columns=["ISO_Match_Key", "Raw_3D_PipeCode"]
            ).to_csv(minus_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(
                [{"流水號": "284", "Line num": "/TRIM-6FL216Q-N3-001"}]
            ).to_excel(iso_path, sheet_name="DWG NO.ALL", index=False)
            pd.DataFrame(
                [
                    {
                        "Path": "HP6.nwd___/HPS___/HPS-TRIM___/TRIM-6FL216Q-N3",
                        "DisplayName": "/TRIM-6FL216Q-N3",
                        "Class": "群組",
                        "Level": "4",
                        "PipelineId": "/TRIM-6FL216Q-N3",
                    }
                ]
            ).to_csv(first_try_path, index=False, encoding="utf-8-sig")

            matcher = IsoMatcher()
            matcher.run(
                base_dir=str(base),
                minus_csv_path=str(minus_path),
                iso_output_path=str(out_path),
                iso_list_path=str(iso_path),
                iso_sheet_name="DWG NO.ALL",
                pipe_col_override="Line num",
                spool_col_override="流水號",
                first_try_path=str(first_try_path),
                log_fn=lambda _msg: None,
            )

            self.assertEqual(len(matcher.fuzzy_unmatched), 1)
            candidates = matcher.fuzzy_unmatched[0]["candidates"]
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["line_3d"], "TRIM-6FL216Q-N3")
            self.assertEqual(candidates[0]["raw_3d"], "/TRIM-6FL216Q-N3")
            self.assertIn("TRIM", candidates[0]["reason"])
            self.assertLess(candidates[0]["score"], 0.9)


if __name__ == "__main__":
    unittest.main()
