# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from core.match_evidence import alnum_tokens, build_match_evidence


class MatchEvidenceTests(unittest.TestCase):
    def test_exact_identity_is_auto_safe_without_project_aliases(self):
        evidence = build_match_evidence(
            "CHWR-32145-2-S1P4-C30",
            "chwr-32145-2-s1p4-c30",
        )

        self.assertEqual(evidence.classification, "exact")
        self.assertTrue(evidence.auto_safe)

    def test_punctuation_only_preserves_every_alphanumeric_token(self):
        evidence = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145-2"-S1P4-C30',
        )

        self.assertEqual(evidence.classification, "punctuation_only")
        self.assertEqual(
            evidence.iso_tokens,
            ("CHWR", "32145", "2", "S1P4", "C30"),
        )
        self.assertEqual(evidence.iso_tokens, evidence.candidate_tokens)
        self.assertFalse(evidence.auto_safe)
        self.assertIn("punctuation_review_required", evidence.reason_codes)
        self.assertEqual(evidence.candidate_extra_tokens, ())
        self.assertEqual(evidence.identity_mutations, ())
        self.assertEqual(evidence.iso_punctuation_shape[3], "_-")
        self.assertEqual(evidence.candidate_punctuation_shape[3], '"-')
        self.assertEqual(len(evidence.punctuation_changes), 1)
        self.assertEqual(evidence.punctuation_changes[0].iso_symbol, "_")
        self.assertEqual(evidence.punctuation_changes[0].candidate_symbol, '"')

    def test_project_approved_punctuation_alias_can_be_auto_safe(self):
        evidence = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145-2"-S1P4-C30',
            approved_punctuation_aliases={"_": '"'},
        )

        self.assertEqual(evidence.classification, "punctuation_only")
        self.assertTrue(evidence.approved_punctuation_alias)
        self.assertTrue(evidence.auto_safe)
        self.assertIn("punctuation_alias_approved", evidence.reason_codes)

    def test_unapproved_gap_change_keeps_punctuation_match_review_only(self):
        evidence = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145-2"/S1P4-C30',
            approved_punctuation_aliases={"_": '"'},
        )

        self.assertEqual(evidence.classification, "punctuation_only")
        self.assertFalse(evidence.approved_punctuation_alias)
        self.assertFalse(evidence.auto_safe)

    def test_alphanumeric_suffix_is_not_silently_stemmed(self):
        evidence = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145A-2"-S1P4-C30',
        )

        self.assertEqual(evidence.classification, "identity_mutation")
        self.assertFalse(evidence.auto_safe)
        self.assertIn("32145", evidence.iso_tokens)
        self.assertIn("32145A", evidence.candidate_tokens)
        self.assertNotIn("32145", alnum_tokens('CHWR-32145A-2"-S1P4-C30'))
        self.assertEqual(evidence.identity_mutations[0].iso_token, "32145")
        self.assertEqual(evidence.identity_mutations[0].candidate_token, "32145A")

    def test_branch_suffix_is_an_extra_token_not_identity_equality(self):
        evidence = build_match_evidence(
            "CHWR-32145-2-S1P4-C30",
            "CHWR-32145-2-S1P4-C30-B1",
        )

        self.assertEqual(evidence.classification, "extra_token")
        self.assertEqual(evidence.candidate_extra_tokens, ("B1",))
        self.assertFalse(evidence.auto_safe)
        self.assertIn("candidate_extra_token", evidence.reason_codes)

    def test_b1_and_b2_are_extra_tokens_not_equal(self):
        evidence = build_match_evidence(
            "CHWR-32145-2-S1P4-C30-B1",
            "CHWR-32145-2-S1P4-C30-B2",
        )

        self.assertEqual(evidence.classification, "extra_token")
        self.assertFalse(evidence.auto_safe)
        self.assertEqual(evidence.iso_missing_tokens, ("B1",))
        self.assertEqual(evidence.candidate_extra_tokens, ("B2",))
        self.assertEqual(evidence.identity_mutations, ())
        self.assertIn("branch_extra_token", evidence.reason_codes)


if __name__ == "__main__":
    unittest.main()
