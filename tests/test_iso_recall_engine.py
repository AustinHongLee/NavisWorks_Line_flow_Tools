# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

import pandas as pd

from core.iso_recall_engine import IsoRecallCandidate, IsoRecallEngine


class IsoRecallEngineTests(unittest.TestCase):
    def test_recall_iso_suffix_family_as_review_candidate(self):
        engine = IsoRecallEngine({"TRIM-6FL216Q-N3-001"})

        candidates = engine.recall_row(
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

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].iso_key, "TRIM-6FL216Q-N3-001")
        self.assertEqual(candidates[0].raw_3d, "/TRIM-6FL216Q-N3")
        self.assertLess(candidates[0].score, 0.9)
        self.assertIn("TRIM", candidates[0].matched_terms)
        self.assertIn("6FL216Q", candidates[0].matched_terms)

    def test_recall_ignores_leading_size_and_line_suffix(self):
        engine = IsoRecallEngine({"3/4-S11G-N4-20951Q"})

        candidates = engine.recall_row(
            pd.Series(
                {
                    "Path": "HP6.nwd___/HPS___/1-1/2-S11G-N4-20951",
                    "DisplayName": "/1-1/2-S11G-N4-20951",
                    "Level": "4",
                    "PipelineId": "/1-1/2-S11G-N4-20951",
                }
            )
        )

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].iso_key, "3/4-S11G-N4-20951Q")
        self.assertIn("S11G", candidates[0].matched_terms)
        self.assertIn("N4", candidates[0].matched_terms)
        self.assertIn("20951", candidates[0].matched_terms)
        self.assertLess(candidates[0].score, 0.9)

    def test_generic_single_token_does_not_recall(self):
        engine = IsoRecallEngine({"TRIM-6FL216Q-N3-001"})

        candidates = engine.recall_row(
            pd.Series(
                {
                    "Path": "HP6.nwd___/AREA___/TRIM PAINT",
                    "DisplayName": "TRIM PAINT",
                    "Level": "4",
                    "PipelineId": "TRIM PAINT",
                }
            )
        )

        self.assertEqual(candidates, [])

    def test_structural_node_is_never_auto_safe(self):
        line = "CHWR-32145-2-S1P4-C30"
        candidate = IsoRecallEngine({line}).recall_row(
            pd.Series(
                {
                    "Path": f"HP6.nwd___/AREA___/{line}",
                    "DisplayName": "BRANCH container",
                    "PipelineId": line,
                    "Level": "4",
                }
            )
        )[0]

        self.assertEqual(candidate.evidence["classification"], "exact")
        self.assertFalse(candidate.auto_safe)
        self.assertIn("structural_node", candidate.reason_codes)

    def test_punctuation_only_ranks_above_alphanumeric_mutation(self):
        engine = IsoRecallEngine(
            {
                "CHWR-32145-2_-S1P4-C30",
                "CHWR-32145A-2_-S1P4-C30",
            },
            approved_punctuation_aliases={"_": "inch_mark", '"': "inch_mark"},
        )

        candidates = engine.recall_row(
            pd.Series(
                {
                    "Path": 'HP6.nwd___/AREA___/CHWR-32145-2"-S1P4-C30',
                    "DisplayName": 'CHWR-32145-2"-S1P4-C30',
                    "PipelineId": 'CHWR-32145-2"-S1P4-C30',
                    "Level": "2",
                }
            ),
            min_score=0.70,
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].iso_key, "CHWR-32145-2_-S1P4-C30")
        self.assertEqual(candidates[0].evidence["classification"], "punctuation_only")
        self.assertTrue(candidates[0].auto_safe)
        self.assertIn("CHWR-32145", candidates[0].path)
        self.assertEqual(candidates[0].level, "2")
        self.assertTrue(candidates[0].pipe_node_path)
        mutated = next(c for c in candidates if "32145A" in c.iso_key)
        self.assertEqual(mutated.evidence["classification"], "identity_mutation")
        self.assertFalse(mutated.auto_safe)
        self.assertIn("derived_stem_match", mutated.reason_codes)
        self.assertLess(mutated.score, candidates[0].score)
        self.assertGreater(mutated.evidence["retrieval_score"], mutated.score)

    def test_candidate_extra_branch_token_has_explicit_penalty(self):
        engine = IsoRecallEngine({"CHWR-32145-2-S1P4-C30"})
        base = engine.recall_row(
            pd.Series({
                "Path": "",
                "DisplayName": "CHWR-32145-2-S1P4-C30",
                "PipelineId": "CHWR-32145-2-S1P4-C30",
            })
        )[0]
        branch = engine.recall_row(
            pd.Series({
                "Path": "",
                "DisplayName": "CHWR-32145-2-S1P4-C30-B1",
                "PipelineId": "CHWR-32145-2-S1P4-C30-B1",
            })
        )[0]

        self.assertEqual(branch.evidence["classification"], "extra_token")
        self.assertEqual(branch.evidence["candidate_extra_tokens"], ["B1"])
        self.assertGreater(branch.evidence["score_penalty"], 0)
        self.assertIn("score_penalty_extra_token", branch.reason_codes)
        self.assertFalse(branch.auto_safe)
        self.assertLess(branch.score, base.score)

    def test_b1_b2_extra_token_difference_remains_review_only(self):
        engine = IsoRecallEngine({"CHWR-32145-2-S1P4-C30-B1"})
        candidate = engine.recall_row(
            pd.Series({
                "Path": "",
                "DisplayName": "CHWR-32145-2-S1P4-C30-B2",
                "PipelineId": "CHWR-32145-2-S1P4-C30-B2",
            })
        )[0]

        self.assertEqual(candidate.evidence["classification"], "extra_token")
        self.assertEqual(candidate.evidence["candidate_extra_tokens"], ["B2"])
        self.assertFalse(candidate.auto_safe)
        self.assertIn("branch_extra_token", candidate.reason_codes)

    def test_candidate_dataclass_keeps_old_positional_api(self):
        candidate = IsoRecallCandidate(
            "ISO", "RAW", "NORM", "PipelineId", 0.5, (), (), "reason", "trace"
        )

        self.assertEqual(candidate.evidence, {})
        self.assertFalse(candidate.auto_safe)
        self.assertEqual(candidate.reason_codes, ())
        self.assertEqual(candidate.path, "")
        self.assertEqual(candidate.scope_root, "")


if __name__ == "__main__":
    unittest.main()
