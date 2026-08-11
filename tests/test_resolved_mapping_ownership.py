# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import unittest

import pandas as pd

from core.resolved_mapping import build_resolved_mapping


class ResolvedMappingOwnershipTests(unittest.TestCase):
    def _build(self, rows: list[dict]) -> tuple[dict, pd.DataFrame]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = os.path.join(temp.name, "iso_match.xlsx")
        output = os.path.join(temp.name, "resolved_mapping.csv")
        pd.DataFrame(rows).to_excel(source, index=False, sheet_name="結果")
        stats = build_resolved_mapping(source, output)
        result = pd.read_csv(output, dtype=str, encoding="utf-8-sig").fillna("")
        return stats, result

    @staticmethod
    def _row(pipe: str, spool: str, path: str = "/MODEL___/ITEM") -> dict:
        return {
            "管線編號": pipe,
            "流水號": spool,
            "ISO_Match_Key": "/3D-ITEM",
            "Raw_3D_PipeCode": "/3D-ITEM",
            "PipeNodePath": path,
            "ScopeRoot": "/MODEL",
            "PipeNodeLevel": "4",
            "NeedsDecision": "0",
            "MatchType": "strict",
        }

    def test_same_iso_family_can_own_item_across_multiple_spools(self):
        stats, result = self._build(
            [self._row("/LINE-A", "1"), self._row("/LINE-A", "2")]
        )

        self.assertEqual(stats["resolved"], 2)
        self.assertEqual(stats["ownership_conflicts"], 0)
        self.assertEqual(set(result["OwnershipStatus"]), {"claimed"})
        self.assertEqual(len(set(result["ItemIdentityKey"])), 1)

    def test_same_item_cannot_receive_two_iso_family_names(self):
        stats, result = self._build(
            [self._row("/LINE-A", "1"), self._row("/LINE-B", "2")]
        )

        self.assertEqual(stats["resolved"], 0)
        self.assertEqual(stats["ownership_conflicts"], 2)
        self.assertEqual(set(result["ResolutionStatus"]), {"ownership_conflict"})
        self.assertEqual(set(result["NeedsDecision"]), {"1"})
        self.assertTrue(result["OwnershipOwners"].str.contains("LINE-A").all())
        self.assertTrue(result["OwnershipOwners"].str.contains("LINE-B").all())

    def test_same_raw_on_distinct_tree_items_remains_independent(self):
        stats, result = self._build(
            [
                self._row("/LINE-A", "1", "/MODEL___/ITEM-1"),
                self._row("/LINE-B", "2", "/MODEL___/ITEM-2"),
            ]
        )

        self.assertEqual(stats["ownership_conflicts"], 0)
        self.assertEqual(stats["resolved"], 2)
        self.assertEqual(len(set(result["ItemIdentityKey"])), 2)

    def test_missing_item_context_is_explicitly_unverifiable(self):
        rows = [self._row("/LINE-A", "1", "")]
        rows[0]["ScopeRoot"] = ""
        rows[0]["PipeNodeLevel"] = ""

        stats, result = self._build(rows)

        self.assertEqual(stats["ownership_unverifiable"], 1)
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(result.iloc[0]["OwnershipStatus"], "unverifiable")
        self.assertEqual(result.iloc[0]["ItemIdentityKey"], "")

    def test_native_guid_is_preferred_over_path(self):
        first = self._row("/LINE-A", "1", "/MODEL___/ITEM-1")
        second = self._row("/LINE-B", "2", "/MODEL___/ITEM-2")
        first["NavisGuid"] = "GUID-100"
        second["NavisGuid"] = "GUID-100"

        stats, result = self._build([first, second])

        self.assertEqual(stats["ownership_conflicts"], 2)
        self.assertEqual(set(result["ItemIdentityKey"]), {"native:NavisGuid:GUID-100"})


if __name__ == "__main__":
    unittest.main()
