# -*- coding: utf-8 -*-
"""Project-scoped declarative matching rules.

Rules never contain executable regular expressions or code.  They are local to
one project workspace and require an explicit human approval record.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile
import uuid


SCHEMA_VERSION = 1
RULE_TEMPLATE_PUNCTUATION_ALIAS = "same_alnum_skeleton_symbol_alias"
_STRUCTURAL_SYMBOLS = {"-", "|"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_symbol(value: object) -> str:
    symbol = str(value)
    if not symbol or len(symbol) > 4:
        raise ValueError("符號 alias 必須是 1–4 個字元")
    if any(ch.isalnum() for ch in symbol):
        raise ValueError("符號 alias 不可包含英數字元")
    if any(ch in _STRUCTURAL_SYMBOLS for ch in symbol):
        raise ValueError("'-' 與 '|' 是結構分隔符，不可建立 alias")
    return symbol


class ProjectRuleStore:
    def __init__(self, project_dir: str):
        self.project_dir = os.path.abspath(project_dir)
        self.flowdesk_dir = os.path.join(self.project_dir, ".flowdesk")
        self.path = os.path.join(self.flowdesk_dir, "project_rules.json")

    def _empty(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "scope": "project",
            "project_dir": self.project_dir,
            "updated_at": "",
            "rules": [],
        }

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return self._empty()
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
            raise ValueError("project_rules.json 格式錯誤")
        if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError("project_rules.json schema 版本不支援")
        return data

    def _save(self, data: dict) -> None:
        os.makedirs(self.flowdesk_dir, exist_ok=True)
        data["updated_at"] = _utc_now()
        handle, temp_path = tempfile.mkstemp(
            prefix="project_rules_",
            suffix=".tmp",
            dir=self.flowdesk_dir,
            text=True,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def propose_punctuation_alias(
        self,
        iso_symbol: object,
        candidate_symbol: object,
        *,
        actor: str = "user",
        sample_iso: str = "",
        sample_candidate: str = "",
    ) -> dict:
        left = _validate_symbol(iso_symbol)
        right = _validate_symbol(candidate_symbol)
        if left == right:
            raise ValueError("相同符號不需要 alias")
        data = self.load()
        for rule in data["rules"]:
            params = rule.get("parameters", {})
            pair = {str(params.get("iso_symbol", "")), str(params.get("candidate_symbol", ""))}
            if (
                rule.get("template_id") == RULE_TEMPLATE_PUNCTUATION_ALIAS
                and pair == {left, right}
                and rule.get("status") in {"proposed", "approved"}
            ):
                return dict(rule)

        rule = {
            "rule_id": f"rule-{uuid.uuid4()}",
            "template_id": RULE_TEMPLATE_PUNCTUATION_ALIAS,
            "scope": "project",
            "status": "proposed",
            "parameters": {
                "iso_symbol": left,
                "candidate_symbol": right,
            },
            "sample": {
                "iso": str(sample_iso),
                "candidate": str(sample_candidate),
            },
            "proposed_by": str(actor or "user"),
            "proposed_at": _utc_now(),
            "approved_by": "",
            "approved_at": "",
        }
        data["rules"].append(rule)
        self._save(data)
        return dict(rule)

    def approve_rule(self, rule_id: str, *, actor: str = "user") -> dict:
        data = self.load()
        for rule in data["rules"]:
            if str(rule.get("rule_id", "")) != str(rule_id):
                continue
            if rule.get("template_id") != RULE_TEMPLATE_PUNCTUATION_ALIAS:
                raise ValueError("不支援的規則 template")
            rule["status"] = "approved"
            rule["approved_by"] = str(actor or "user")
            rule["approved_at"] = _utc_now()
            self._save(data)
            return dict(rule)
        raise KeyError(f"找不到規則：{rule_id}")

    def disable_rule(self, rule_id: str, *, actor: str = "user") -> dict:
        data = self.load()
        for rule in data["rules"]:
            if str(rule.get("rule_id", "")) == str(rule_id):
                rule["status"] = "disabled"
                rule["disabled_by"] = str(actor or "user")
                rule["disabled_at"] = _utc_now()
                self._save(data)
                return dict(rule)
        raise KeyError(f"找不到規則：{rule_id}")

    def approved_punctuation_aliases(self) -> dict[str, str]:
        """Return symmetric canonical aliases for the evidence comparator."""

        pairs: list[tuple[str, str]] = []
        for rule in self.load()["rules"]:
            if (
                rule.get("template_id") != RULE_TEMPLATE_PUNCTUATION_ALIAS
                or rule.get("status") != "approved"
            ):
                continue
            params = rule.get("parameters", {})
            left = _validate_symbol(params.get("iso_symbol", ""))
            right = _validate_symbol(params.get("candidate_symbol", ""))
            pairs.append((left, right))

        # Small union-find so overlapping approved pairs share one canonical
        # representation regardless of approval direction.
        parent: dict[str, str] = {}

        def find(value: str) -> str:
            parent.setdefault(value, value)
            if parent[value] != value:
                parent[value] = find(parent[value])
            return parent[value]

        def union(left: str, right: str) -> None:
            root_left = find(left)
            root_right = find(right)
            if root_left == root_right:
                return
            canonical = min(root_left, root_right)
            other = root_right if canonical == root_left else root_left
            parent[other] = canonical

        for left, right in pairs:
            union(left, right)
        return {symbol: find(symbol) for symbol in parent}
