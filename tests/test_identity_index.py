# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import pandas as pd

from core.identity_index import build_identity_index
from core.resolved_mapping import build_resolved_mapping


class IdentityIndexTests(unittest.TestCase):
    def test_build_index_counts_drop_last_family(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            resolved = os.path.join(tmp, "resolved_mapping.csv")
            minus1 = os.path.join(tmp, "123_minus_1.csv")
            out = os.path.join(tmp, "identity_index.csv")

            pd.DataFrame(
                [
                    {
                        "流水號": "284",
                        "管線編號": "TRIM-6FL216Q-N3-001",
                    }
                ]
            ).to_csv(resolved, index=False, encoding="utf-8-sig")
            pd.DataFrame(
                [
                    {
                        "ISO_Match_Key": "TRIM-6FL216Q-N3",
                        "Raw_3D_PipeCode": "/TRIM-6FL216Q-N3",
                        "PipeNodePath": "/HPS/HPS-TRIM/TRIM-6FL216Q-N3",
                    },
                    {
                        "ISO_Match_Key": "TRIM-6FL216Q-N3-B1",
                        "Raw_3D_PipeCode": "/TRIM-6FL216Q-N3/B1",
                        "PipeNodePath": "/HPS/HPS-TRIM/TRIM-6FL216Q-N3/B1",
                    },
                ]
            ).to_csv(minus1, index=False, encoding="utf-8-sig")

            result_path = build_identity_index(resolved, minus1, out)
            df = pd.read_csv(result_path, dtype=str, encoding="utf-8-sig").fillna("")

        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row["iso_norm_drop_last"], "TRIM-6FL216Q-N3")
        self.assertEqual(row["match_3d_droplast_count"], "1")
        self.assertEqual(row["match_3d_family_count"], "2")
        self.assertIn("TRIM-6FL216Q-N3", row["sample_3d_paths"])

    def test_resolved_mapping_auto_builds_index_when_minus1_exists(self):
        with tempfile.TemporaryDirectory(prefix="tmp_unit_", dir=os.getcwd()) as tmp:
            iso_match = os.path.join(tmp, "iso_match.xlsx")
            minus1 = os.path.join(tmp, "123_minus_1.csv")
            mapping = os.path.join(tmp, "resolved_mapping.csv")
            index = os.path.join(tmp, "identity_index.csv")

            pd.DataFrame(
                [
                    {
                        "流水號": "284",
                        "管線編號": "TRIM-6FL216Q-N3-001",
                        "Raw_3D_PipeCode": "",
                        "NeedsDecision": "0",
                    }
                ]
            ).to_excel(iso_match, index=False, sheet_name="結果")
            pd.DataFrame(
                [
                    {
                        "ISO_Match_Key": "TRIM-6FL216Q-N3",
                        "Raw_3D_PipeCode": "/TRIM-6FL216Q-N3",
                    }
                ]
            ).to_csv(minus1, index=False, encoding="utf-8-sig")

            stats = build_resolved_mapping(iso_match, mapping)
            self.assertTrue(os.path.exists(index))
            self.assertEqual(stats["identity_index_path"], index)


if __name__ == "__main__":
    unittest.main()
