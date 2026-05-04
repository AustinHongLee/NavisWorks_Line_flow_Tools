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


if __name__ == "__main__":
    unittest.main()
