# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

import pandas as pd

from core.iso_recall_engine import IsoRecallEngine


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


if __name__ == "__main__":
    unittest.main()
