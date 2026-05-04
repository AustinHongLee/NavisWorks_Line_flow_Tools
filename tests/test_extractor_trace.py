# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import pandas as pd

from core.pipeline_extractor import PipelineExtractor


class ExtractorTraceTests(unittest.TestCase):
    def test_minus_1_has_identity_reason_column(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            fix = os.path.join(tmp, "First_try.csv")
            with open(fix, "w", encoding="utf-8-sig") as f:
                f.write(
                    "Path,DisplayName,Class,Level,PipelineId\n"
                    "/A/B/C,DisplayName1,SomeClass,3,/AC-1701-100-AA1B-NA\n"
                )
            out = os.path.join(tmp, "minus_1.csv")

            extractor = PipelineExtractor()
            extractor.build_intermediate(
                input_csv=fix,
                out_csv=out,
                scan_mode="full",
            )

            df = pd.read_csv(out, encoding="utf-8-sig")
            self.assertIn("IdentityReason", df.columns)
            self.assertEqual(len(df), 1)
            trace = str(df.iloc[0]["IdentityReason"])
            self.assertIn("raw=", trace)
            self.assertIn("source=", trace)

    def test_debug_trace_and_candidates_are_opt_in(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            fix = os.path.join(tmp, "First_try.csv")
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
                        "Path": "/A/B/C",
                        "DisplayName": "/AC-1701-100-AA1B-NA",
                        "Class": "Group",
                        "Level": "3",
                        "PipelineId": "/AC-1701-100-AA1B-NA",
                    },
                ]
            ).to_csv(fix, index=False, encoding="utf-8-sig")
            out = os.path.join(tmp, "123_minus_1.csv")
            trace = os.path.join(tmp, "first_try_trace.csv")
            candidates = os.path.join(tmp, "candidates.csv")

            PipelineExtractor().build_intermediate(
                input_csv=fix,
                out_csv=out,
                scan_mode="full",
                write_first_try_trace=True,
                first_try_trace_path=trace,
                write_candidates=True,
                candidates_path=candidates,
            )

            trace_df = pd.read_csv(trace, dtype=str, encoding="utf-8-sig").fillna("")
            cand_df = pd.read_csv(candidates, dtype=str, encoding="utf-8-sig").fillna("")
            self.assertEqual(len(trace_df), 2)
            self.assertEqual(
                trace_df.loc[trace_df["PipelineId"].eq("/AC-1701-100-AA1B-NA"), "included_in_minus_1"].iloc[0],
                "1",
            )
            self.assertEqual(
                trace_df.loc[trace_df["PipelineId"].eq("model.nwd"), "exclude_reason"].iloc[0],
                "file_like",
            )
            self.assertGreaterEqual(len(cand_df), 1)
            self.assertIn("AC-1701-100-AA1B-NA", set(cand_df["normalized"]))

    def test_debug_trace_marks_out_of_scan_scope(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            fix = os.path.join(tmp, "First_try.csv")
            pd.DataFrame(
                [
                    {
                        "Path": "/A/level2",
                        "DisplayName": "/AC-1701-100-AA1B-NA",
                        "Class": "Group",
                        "Level": "2",
                        "PipelineId": "/AC-1701-100-AA1B-NA",
                    },
                    {
                        "Path": "/A/level3",
                        "DisplayName": "/AC-1702-100-AA1B-NA",
                        "Class": "Group",
                        "Level": "3",
                        "PipelineId": "/AC-1702-100-AA1B-NA",
                    },
                ]
            ).to_csv(fix, index=False, encoding="utf-8-sig")
            out = os.path.join(tmp, "123_minus_1.csv")
            trace = os.path.join(tmp, "first_try_trace.csv")

            PipelineExtractor().build_intermediate(
                input_csv=fix,
                out_csv=out,
                scan_mode="level",
                id_level=3,
                write_first_try_trace=True,
                first_try_trace_path=trace,
            )

            trace_df = pd.read_csv(trace, dtype=str, encoding="utf-8-sig").fillna("")
            self.assertEqual(len(trace_df), 2)
            self.assertEqual(
                trace_df.loc[trace_df["Level"].eq("2"), "exclude_reason"].iloc[0],
                "out_of_scan_scope",
            )


if __name__ == "__main__":
    unittest.main()
