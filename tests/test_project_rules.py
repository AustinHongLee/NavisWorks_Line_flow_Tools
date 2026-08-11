# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile

import pytest

from core.match_evidence import build_match_evidence
from core.project_rules import ProjectRuleStore


def test_punctuation_alias_requires_explicit_project_approval():
    with tempfile.TemporaryDirectory() as project:
        store = ProjectRuleStore(project)
        proposed = store.propose_punctuation_alias(
            "_",
            '"',
            sample_iso="CHWR-32145-2_-S1P4-C30",
            sample_candidate='CHWR-32145-2"-S1P4-C30',
        )

        before = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145-2"-S1P4-C30',
            store.approved_punctuation_aliases(),
        )
        assert before.classification == "punctuation_only"
        assert before.auto_safe is False

        store.approve_rule(proposed["rule_id"], actor="reviewer")
        aliases = store.approved_punctuation_aliases()
        after = build_match_evidence(
            "CHWR-32145-2_-S1P4-C30",
            'CHWR-32145-2"-S1P4-C30',
            aliases,
        )
        assert after.approved_punctuation_alias is True
        assert after.auto_safe is True


def test_project_rules_are_not_shared_between_workspaces():
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        first_store = ProjectRuleStore(first)
        rule = first_store.propose_punctuation_alias("_", '"')
        first_store.approve_rule(rule["rule_id"])

        assert first_store.approved_punctuation_aliases()
        assert ProjectRuleStore(second).approved_punctuation_aliases() == {}


@pytest.mark.parametrize("unsafe", ["-", "|", "A", "", "123"])
def test_executable_or_structural_aliases_are_rejected(unsafe: str):
    with tempfile.TemporaryDirectory() as project:
        with pytest.raises(ValueError):
            ProjectRuleStore(project).propose_punctuation_alias(unsafe, '"')
