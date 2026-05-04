# -*- coding: utf-8 -*-
"""Trace 字串建構與解析工具。"""
from __future__ import annotations

from typing import Iterable


SEP = "§"
ESCAPE = "§§"
MAX_LEN = 4096


def _clean_key(key: str) -> str:
    cleaned = str(key).strip().replace("=", "_").replace(SEP, "_")
    return cleaned


def _escape_value(value: object) -> str:
    return str(value).replace(SEP, ESCAPE)


def _truncate(text: str) -> str:
    marker = f"{SEP}truncated=1"
    if len(text) <= MAX_LEN:
        return text
    if len(marker) >= MAX_LEN:
        return marker[:MAX_LEN]
    return text[: MAX_LEN - len(marker)] + marker


class TraceBuilder:
    """累積式建構 trace 字串。"""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, key: str, value: object) -> "TraceBuilder":
        """加入 ``key=value`` 段。value 自動 escape。"""
        safe_key = _clean_key(key)
        if not safe_key:
            return self
        self._parts.append(f"{safe_key}={_escape_value(value)}")
        return self

    def add_event(self, name: str, detail: object = "") -> "TraceBuilder":
        """加入 ``name:detail`` 段。"""
        safe_name = _clean_key(name)
        if not safe_name:
            return self
        self._parts.append(f"{safe_name}:{_escape_value(detail)}")
        return self

    def extend_events(self, events: Iterable[str]) -> "TraceBuilder":
        """批次加入已格式化的事件字串。"""
        for event in events:
            text = str(event).strip()
            if not text:
                continue
            if "=" in text:
                key, value = text.split("=", 1)
                self.add(key, value)
            elif ":" in text:
                key, value = text.split(":", 1)
                self.add_event(key, value)
            else:
                self.add_event("event", text)
        return self

    def build(self) -> str:
        """組裝為單一字串。若超過 MAX_LEN 自動截斷並標記。"""
        if not self._parts:
            return ""
        return _truncate(SEP + SEP.join(self._parts))


def parse_trace(trace_str: str) -> list[tuple[str, str, str]]:
    """解析 trace 字串為 ``(kind, key, value)`` tuples。"""
    text = "" if trace_str is None else str(trace_str)
    if not text:
        return []

    raw_parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == SEP:
            if i + 1 < len(text) and text[i + 1] == SEP:
                current.append(SEP)
                i += 2
                continue
            if current:
                raw_parts.append("".join(current))
                current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    if current:
        raw_parts.append("".join(current))

    parsed: list[tuple[str, str, str]] = []
    for part in raw_parts:
        if not part:
            continue
        eq_pos = part.find("=")
        colon_pos = part.find(":")
        if eq_pos >= 0 and (colon_pos < 0 or eq_pos < colon_pos):
            key, value = part.split("=", 1)
            parsed.append(("kv", key, value))
        elif colon_pos >= 0:
            key, value = part.split(":", 1)
            parsed.append(("event", key, value))
        else:
            parsed.append(("event", part, ""))
    return parsed


def append_trace(existing: object, extra: object) -> str:
    """把新 trace 片段安全接到既有 IdentityReason 後方。"""
    base = "" if existing is None else str(existing).strip()
    more = "" if extra is None else str(extra).strip()
    parts: list[str] = []
    if base:
        if base.startswith(SEP):
            parts.append(base)
        else:
            parts.append(TraceBuilder().add("legacy_reason", base).build())
    if more:
        parts.append(more if more.startswith(SEP) else f"{SEP}{more}")
    return _truncate("".join(parts))
