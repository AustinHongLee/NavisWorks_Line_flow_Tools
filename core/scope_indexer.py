# -*- coding: utf-8 -*-
"""Helpers for keeping 3D tree scope context beside pipe identity keys."""
from __future__ import annotations

import re
from typing import Any

from utils.utils_common import CommonUtils


_FILE_EXT_RE = re.compile(r"\.[a-zA-Z]{2,4}$")
_NAVIS_FILE_RE = re.compile(r"\.(?:nwd|nwc|nwf)$", re.IGNORECASE)


def _split_path(path: Any, sep: str) -> list[str]:
    if not isinstance(path, str):
        path = "" if path is None else str(path)
    return [s.strip() for s in path.split(sep) if str(s).strip()]


def _is_file_like(segment: str) -> bool:
    return bool(_FILE_EXT_RE.search(segment.strip()))


def _is_navis_file(segment: str) -> bool:
    return bool(_NAVIS_FILE_RE.search(segment.strip()))


def _strip_prefix(value: str) -> str:
    return re.sub(r"^[^A-Za-z0-9/]+", "", str(value).strip())


def _raw_forms(value: str) -> set[str]:
    text = _strip_prefix(value)
    if not text:
        return set()
    forms = {text}
    if text.startswith("/"):
        forms.add(text.lstrip("/"))
    else:
        forms.add("/" + text)
    return forms


def parse_scope_context(
    path: Any,
    sep: str,
    iso_match_key: str = "",
    raw_3d_pipe_code: str = "",
    level: Any = "",
) -> dict[str, str]:
    """Extract coarse scope context from a Navisworks tree path.

    The values are intentionally conservative diagnostics. They do not decide
    which area is correct; they preserve enough context for collision reports.
    """
    segments = _split_path(path, sep)
    if not segments:
        return {
            "PipeNodePath": "" if path is None else str(path),
            "ScopeRoot": "",
            "ParentArea": "",
            "PipeNodeLevel": "",
        }

    raw_targets = _raw_forms(raw_3d_pipe_code)
    normalized_targets = {
        CommonUtils.normalize_line(iso_match_key),
        CommonUtils.normalize_line(raw_3d_pipe_code),
    }
    normalized_targets = {t for t in normalized_targets if t}

    pipe_idx: int | None = None
    if raw_targets:
        for idx, segment in enumerate(segments):
            if _strip_prefix(segment) in raw_targets:
                pipe_idx = idx
                break

    if pipe_idx is None and normalized_targets:
        for idx, segment in enumerate(segments):
            if CommonUtils.normalize_line(segment) in normalized_targets:
                pipe_idx = idx
                break

    if pipe_idx is None:
        try:
            lv = int(str(level).strip())
            if 0 <= lv < len(segments):
                pipe_idx = lv
        except Exception:
            pipe_idx = None

    if pipe_idx is None:
        pipe_idx = len(segments) - 1

    parent_area = segments[pipe_idx - 1] if pipe_idx > 0 else ""
    pipe_node_path = sep.join(segments[: pipe_idx + 1]) if sep else str(path)

    search_limit = max(pipe_idx, 0)
    scope_root = ""
    for segment in segments[:search_limit]:
        if _is_navis_file(segment):
            continue
        scope_root = segment
        break
    if not scope_root:
        for segment in segments:
            if not _is_navis_file(segment):
                scope_root = segment
                break

    return {
        "PipeNodePath": pipe_node_path,
        "ScopeRoot": scope_root,
        "ParentArea": parent_area,
        "PipeNodeLevel": str(pipe_idx),
    }
