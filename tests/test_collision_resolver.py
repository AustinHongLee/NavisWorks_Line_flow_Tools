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

    def test_load_and_apply_level_decision_when_parent_is_same(self):
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
                        "PipeNodeLevel": "4",
                        "NeedsDecision": "1",
                    },
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "10",
                        "Raw_3D_PipeCode": "/A-LINE/B1",
                        "ParentArea": "/A",
                        "ScopeRoot": "/A",
                        "PipeNodeLevel": "5",
                        "NeedsDecision": "1",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            groups = load_collision_groups(path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["area_col"], "PipeNodeLevel")
            self.assertEqual(
                {c["area"] for c in groups[0]["choices"]},
                {"4", "5"},
            )

            stats = apply_collision_decisions(
                path,
                {"10": {"area_col": "PipeNodeLevel", "area": "4"}},
            )
            self.assertEqual(stats["selected"], 1)
            self.assertEqual(stats["rejected"], 1)

            result = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            selected = result[result["PipeNodeLevel"] == "4"].iloc[0]
            rejected = result[result["PipeNodeLevel"] == "5"].iloc[0]
            self.assertEqual(selected["Resolved"], "1")
            self.assertEqual(selected["ResolutionStatus"], "user_selected")
            self.assertEqual(rejected["Resolved"], "0")
            self.assertEqual(rejected["ResolutionStatus"], "user_rejected")

    def test_prefers_broad_scope_before_path_hint(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            path = os.path.join(tmp, "resolved_mapping.csv")
            p1 = "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/LINE"
            p2 = "HP6.nwd___CHO_INSU.RVM___/HPS___/LINE"
            pd.DataFrame(
                [
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/LINE",
                        "ParentArea": "/HPS-PIPE",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "PipeNodePath": p1,
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "NeedsDecision": "1",
                    },
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/LINE",
                        "ParentArea": "/HPS-PIPE",
                        "ScopeRoot": "CHO_INSU.RVM",
                        "PipeNodePath": p2,
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "NeedsDecision": "1",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            groups = load_collision_groups(path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["area_col"], "ScopeRoot")
            self.assertEqual(
                {c["area"] for c in groups[0]["choices"]},
                {"CHO_NO_INSU.RVM", "CHO_INSU.RVM"},
            )

            stats = apply_collision_decisions(
                path,
                {"16": {"area_col": "ScopeRoot", "area": "CHO_NO_INSU.RVM"}},
            )
            self.assertEqual(stats["selected"], 1)
            self.assertEqual(stats["rejected"], 1)

            result = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
            self.assertEqual(
                result[result["PipeNodePath"].eq(p1)].iloc[0]["ResolutionStatus"],
                "user_selected",
            )
            self.assertEqual(
                result[result["PipeNodePath"].eq(p2)].iloc[0]["ResolutionStatus"],
                "user_rejected",
            )

    def test_uses_path_when_no_broader_dimension_differs(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            path = os.path.join(tmp, "resolved_mapping.csv")
            p1 = "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/LINE"
            p2 = "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/LINE___/LINE/B1"
            pd.DataFrame(
                [
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/LINE",
                        "ParentArea": "/HPS-PIPE",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "PipeNodeLevel": "4",
                        "PipeNodePath": p1,
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "NeedsDecision": "1",
                    },
                    {
                        "Resolved": "0",
                        "ResolutionStatus": "needs_decision",
                        "流水號": "16",
                        "Raw_3D_PipeCode": "/LINE",
                        "ParentArea": "/HPS-PIPE",
                        "ScopeRoot": "CHO_NO_INSU.RVM",
                        "PipeNodeLevel": "4",
                        "PipeNodePath": p2,
                        "CollisionParents": f"PipeNodePath: {p1} | {p2}",
                        "NeedsDecision": "1",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            groups = load_collision_groups(path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["area_col"], "PipeNodePath")
            self.assertEqual({c["area"] for c in groups[0]["choices"]}, {p1, p2})


if __name__ == "__main__":
    unittest.main()
