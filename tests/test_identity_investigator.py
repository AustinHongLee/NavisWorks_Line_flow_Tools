# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import pandas as pd

from core.identity_investigator import investigate_identity, make_paths


class IdentityInvestigatorTests(unittest.TestCase):
    def test_search_trim_family_across_first_try_and_minus1(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            pd.DataFrame(
                [
                    {
                        "Path": "HP6.nwd___/HPS___/HPS-TRIM___/TRIM-6FL216Q-N3",
                        "DisplayName": "/TRIM-6FL216Q-N3",
                        "Class": "群組",
                        "Level": "4",
                        "PipelineId": "/TRIM-6FL216Q-N3",
                    },
                    {
                        "Path": "HP6.nwd___/HPS___/HPS-TRIM___/TRIM-6FL216Q-N3___/TRIM-6FL216Q-N3/B1",
                        "DisplayName": "/TRIM-6FL216Q-N3/B1",
                        "Class": "群組",
                        "Level": "5",
                        "PipelineId": "/TRIM-6FL216Q-N3/B1",
                    },
                ]
            ).to_csv(os.path.join(tmp, "First_try.csv"), index=False, encoding="utf-8-sig")

            pd.DataFrame(
                [
                    {
                        "Path": "HP6.nwd___/HPS___/HPS-TRIM___/TRIM-6FL216Q-N3",
                        "DisplayName": "/TRIM-6FL216Q-N3",
                        "Class": "群組",
                        "Level": "4",
                        "PipelineId": "/TRIM-6FL216Q-N3",
                        "Raw_3D_PipeCode": "/TRIM-6FL216Q-N3",
                        "ISO_Match_Key": "TRIM-6FL216Q-N3",
                        "ScopeRoot": "HP6.nwd",
                        "ParentArea": "/HPS-TRIM",
                        "MatchSource": "pipeline_id",
                        "ConfidencePrimary": "1.0",
                        "IdentityReason": "§raw=/TRIM-6FL216Q-N3§source=pipeline_id",
                    }
                ]
            ).to_csv(os.path.join(tmp, "123_minus_1.csv"), index=False, encoding="utf-8-sig")

            pd.DataFrame(
                [
                    {
                        "流水號": "284",
                        "管線編號": "TRIM-6FL216Q-N3-001",
                        "ISO_Match_Key": "TRIM-6FL216Q-N3-001",
                        "Raw_3D_PipeCode": "",
                        "Resolved": "0",
                        "ResolutionStatus": "no_raw",
                        "MatchType": "",
                        "MatchScore": "0",
                        "NeedsDecision": "0",
                    }
                ]
            ).to_csv(os.path.join(tmp, "resolved_mapping.csv"), index=False, encoding="utf-8-sig")

            result = investigate_identity("TRIM-6FL216Q-N3-001", make_paths(tmp))

        self.assertEqual(result["family"]["normalized"], "TRIM-6FL216Q-N3-001")
        self.assertEqual(result["family"]["drop_last"], "TRIM-6FL216Q-N3")
        self.assertEqual(result["family"]["drop_last_3d_count"], "1")
        self.assertEqual(len(result["iso_rows"]), 1)
        self.assertEqual(len(result["minus1_rows"]), 1)
        self.assertEqual(len(result["first_try_rows"]), 2)
        self.assertEqual(result["level_summary"][0]["Level"], "4")

    def test_prefers_first_try_trace_when_available(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            pd.DataFrame(
                [
                    {
                        "source_row_idx": "1",
                        "Path": "/A/TRIM-6FL216Q-N3",
                        "DisplayName": "/TRIM-6FL216Q-N3",
                        "Class": "Group",
                        "Level": "4",
                        "PipelineId": "/TRIM-6FL216Q-N3",
                        "included_in_minus_1": "1",
                        "exclude_reason": "",
                        "best_candidate_normalized": "TRIM-6FL216Q-N3",
                        "minus_1_row_idx": "1",
                    },
                    {
                        "source_row_idx": "2",
                        "Path": "/A/TRIM-6FL216Q-N3/B1",
                        "DisplayName": "/TRIM-6FL216Q-N3/B1",
                        "Class": "Group",
                        "Level": "5",
                        "PipelineId": "/TRIM-6FL216Q-N3/B1",
                        "included_in_minus_1": "0",
                        "exclude_reason": "no_id",
                        "best_candidate_normalized": "",
                        "minus_1_row_idx": "",
                    },
                ]
            ).to_csv(
                os.path.join(tmp, "first_try_trace.csv"),
                index=False,
                encoding="utf-8-sig",
            )

            result = investigate_identity("TRIM-6FL216Q-N3", make_paths(tmp))

        self.assertEqual(result["family"]["first_try_source"], "first_try_trace.csv")
        self.assertEqual(len(result["first_try_rows"]), 2)
        reasons = {row["exclude_reason"] for row in result["first_try_rows"]}
        self.assertIn("no_id", reasons)


if __name__ == "__main__":
    unittest.main()
