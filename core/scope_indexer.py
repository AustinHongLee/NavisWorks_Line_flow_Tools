# -*- coding: utf-8 -*-
"""Helpers for keeping 3D tree scope context beside pipe identity keys."""
from __future__ import annotations

import re
from typing import Any

from utils.utils_common import CommonUtils


_FILE_EXT_RE = re.compile(r"\.[a-zA-Z]{2,4}$")


def _split_path(path: Any, sep: str) -> list[str]:
    if not isinstance(path, str):
        path = "" if path is None else str(path)
    return [s.strip() for s in path.split(sep) if str(s).strip()]


def _is_file_like(segment: str) -> bool:
    return bool(_FILE_EXT_RE.search(segment.strip()))


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

    targets = {
        CommonUtils.normalize_line(iso_match_key),
        CommonUtils.normalize_line(raw_3d_pipe_code),
    }
    targets = {t for t in targets if t}

    pipe_idx: int | None = None
    if targets:
        for idx, segment in enumerate(segments):
            if CommonUtils.normalize_line(segment) in targets:
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

    search_limit = max(pipe_idx, 0)
    scope_root = ""
    for segment in segments[:search_limit]:
        if _is_file_like(segment):
            continue
        if segment.startswith("/"):
            scope_root = segment
            break
    if not scope_root:
        for segment in segments:
            if not _is_file_like(segment):
                scope_root = segment
                break

    return {
        "PipeNodePath": str(path) if path is not None else "",
        "ScopeRoot": scope_root,
        "ParentArea": parent_area,
        "PipeNodeLevel": str(pipe_idx),
    }
