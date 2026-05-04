# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from core.scope_indexer import parse_scope_context


class ScopeIndexerTests(unittest.TestCase):
    def test_scope_root_keeps_rvm_model_root(self):
        ctx = parse_scope_context(
            (
                "HP6-20260127.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE"
                "___/1-S11U-AP-US02"
            ),
            "___",
            iso_match_key="1-S11U-AP-US02",
            raw_3d_pipe_code="/1-S11U-AP-US02",
            level="4",
        )

        self.assertEqual(ctx["ScopeRoot"], "CHO_NO_INSU.RVM")
        self.assertEqual(ctx["ParentArea"], "/HPS-PIPE")
        self.assertEqual(
            ctx["PipeNodePath"],
            (
                "HP6-20260127.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE"
                "___/1-S11U-AP-US02"
            ),
        )

    def test_pipe_node_path_stops_at_branch_identity_node(self):
        ctx = parse_scope_context(
            (
                "HP6-20260127.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE"
                "___/1-S11U-AP-US02___/1-S11U-AP-US02/B1"
                "___ELBOW 1 of BRANCH /1-S11U-AP-US02/B1"
            ),
            "___",
            iso_match_key="1-S11U-AP-US02",
            raw_3d_pipe_code="/1-S11U-AP-US02/B1",
            level="6",
        )

        self.assertEqual(ctx["ScopeRoot"], "CHO_NO_INSU.RVM")
        self.assertEqual(ctx["ParentArea"], "/1-S11U-AP-US02")
        self.assertEqual(ctx["PipeNodeLevel"], "5")
        self.assertEqual(
            ctx["PipeNodePath"],
            (
                "HP6-20260127.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE"
                "___/1-S11U-AP-US02___/1-S11U-AP-US02/B1"
            ),
        )


if __name__ == "__main__":
    unittest.main()
