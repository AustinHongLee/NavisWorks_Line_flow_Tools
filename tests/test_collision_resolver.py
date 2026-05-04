# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import pandas as pd

from core.collision_resolver import (
    apply_collision_decisions,
    load_collision_groups,
)


class CollisionResolverTests(unittest.TestCase):
    def test_load_and_apply_parent_area_decision(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            path = os.path.join(tmp, "resolved_mapping.csv")
            pd.DataFrame(
                [
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "10",
                        "Raw_3D_PipeCode": "/A-LINE",
                        "ParentArea": "/A",
                        "ScopeRoot": "/A",
                        "NeedsDecision": "1",
                    },
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "10",
                        "Raw_3D_PipeCode": "/B-LINE",
                        "ParentArea": "/B",
                        "ScopeRoot": "/B",
                        "NeedsDecision": "1",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            groups = load_collision_groups(path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["spool"], "10")
            self.assertEqual(
                {c["area"] for c in groups[0]["choices"]},
                {"/A", "/B"},
            )

            stats = apply_collision_decisions(path, {"10": "/A"})
            self.assertEqual(stats["selected"], 1)
            self.assertEqual(stats["rejected"], 1)

            result = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            selected = result[result["ParentArea"] == "/A"].iloc[0]
            rejected = result[result["ParentArea"] == "/B"].iloc[0]
            self.assertEqual(selected["Resolved"], "1")
            self.assertEqual(selected["ResolutionStatus"], "user_selected")
            self.assertEqual(selected["NeedsDecision"], "0")
            self.assertEqual(rejected["Resolved"], "0")
            self.assertEqual(rejected["ResolutionStatus"], "user_rejected")
            self.assertEqual(rejected["NeedsDecision"], "0")


if __name__ == "__main__":
    unittest.main()
