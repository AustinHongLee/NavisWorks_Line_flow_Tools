# -*- coding: utf-8 -*-
"""Topology-only grouping for 3D match candidates.

Tree ancestry is useful for presentation (for example folding B1/B2 below a
parent ITEM), but it never rewrites or equates the candidate identity text.
"""
from __future__ import annotations

import hashlib
from typing import Iterable


def _text(candidate: dict, *names: str) -> str:
    for name in names:
        value = str(candidate.get(name, "")).strip()
        if value:
            return value
    return ""


def path_parts(value: object) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in str(value or "").split("___")
        if part.strip()
    )


def candidate_item_id(candidate: dict, dataset_revision: str = "") -> str:
    """Return a stable-in-dataset item key for candidate review."""

    native = _text(
        candidate,
        "item_id",
        "NavisGuid",
        "NavisGUID",
        "ItemGuid",
        "ElementGuid",
    )
    if native:
        return native if native.startswith(("native:", "fallback:")) else f"native:{native}"

    path = _text(candidate, "path", "PipeNodePath")
    scope = _text(candidate, "scope", "ScopeRoot")
    level = _text(candidate, "level", "PipeNodeLevel")
    raw = _text(candidate, "raw_3d", "Raw_3D_PipeCode", "line_3d")
    material = "\x1f".join((scope, path, level, raw))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    prefix = "fallback" if path or scope or level else "ephemeral"
    revision = str(dataset_revision).strip()
    if prefix == "fallback" and revision:
        return f"{prefix}:{revision}:{digest}"
    return f"{prefix}:{digest}"


def _is_strict_ancestor(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    return bool(parent and len(parent) < len(child) and child[: len(parent)] == parent)


def annotate_candidate_families(candidates: Iterable[dict]) -> list[dict]:
    """Annotate candidates with Path-proven family display metadata.

    A family is created only when an actual candidate path is a strict ancestor
    of another actual candidate path.  Similar names, suffixes, and scores never
    create a family relation.
    """

    rows = [dict(candidate) for candidate in candidates]
    paths = [path_parts(_text(row, "path", "PipeNodePath")) for row in rows]
    item_ids = [candidate_item_id(row) for row in rows]
    parent_indices: list[int | None] = [None] * len(rows)

    for child_idx, child_path in enumerate(paths):
        possible = [
            parent_idx
            for parent_idx, parent_path in enumerate(paths)
            if parent_idx != child_idx and _is_strict_ancestor(parent_path, child_path)
        ]
        if possible:
            parent_indices[child_idx] = max(
                possible,
                key=lambda idx: len(paths[idx]),
            )

    root_indices: list[int] = []
    for idx in range(len(rows)):
        root = idx
        visited: set[int] = set()
        while parent_indices[root] is not None and root not in visited:
            visited.add(root)
            root = int(parent_indices[root])
        root_indices.append(root)

    family_counts: dict[str, int] = {}
    for root_idx in root_indices:
        family_id = item_ids[root_idx]
        family_counts[family_id] = family_counts.get(family_id, 0) + 1

    independent_family_count = len(family_counts)
    child_parent_ids = {
        int(parent_idx)
        for parent_idx in parent_indices
        if parent_idx is not None
    }
    for idx, row in enumerate(rows):
        parent_idx = parent_indices[idx]
        root_idx = root_indices[idx]
        family_id = item_ids[root_idx]
        if parent_idx is not None:
            role = "child"
        elif idx in child_parent_ids:
            role = "root"
        else:
            role = "independent"
        row.update(
            {
                "item_id": item_ids[idx],
                "family_id": family_id,
                "family_role": role,
                "family_member_count": family_counts[family_id],
                "independent_family_count": independent_family_count,
                "family_relation": "path_descendant" if parent_idx is not None else "",
                "family_parent_item_id": item_ids[parent_idx] if parent_idx is not None else "",
                "family_parent_line_3d": (
                    _text(rows[parent_idx], "line_3d", "raw_3d")
                    if parent_idx is not None
                    else ""
                ),
                # Explicitly tells consumers that topology is not identity proof.
                "family_identity_equivalent": False,
            }
        )
    return rows
