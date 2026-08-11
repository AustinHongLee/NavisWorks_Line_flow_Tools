# -*- coding: utf-8 -*-
"""Read-only project re-entry summary built from existing Run Capsules.

The GUI uses this module as a probe.  It deliberately does not construct a
``RunLedger`` because doing so would create ``.flowdesk``.  Every filesystem
operation here is a read, and damaged/incomplete capsules are ignored rather
than surfaced as an exception to the caller.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


_STAGE_LABELS = {
    "extract": "掃描 3D 管線",
    "group": "整理 3D 群組",
    "match": "ISO 比對",
    "review": "人工判讀",
    "mapping": "建立映射",
}

_STATE_LABELS = {
    "failed": "執行失敗",
    "interrupted": "上次執行中斷",
    "awaiting_review": "等待人工判讀",
    "completed": "上次執行已完成",
    "no_history": "尚無執行紀錄",
}


@dataclass(frozen=True)
class ProjectContinuitySnapshot:
    """A compact, display-ready description of where a project was left.

    ``status`` and ``operator_state`` intentionally contain the same UX state.
    ``run_status`` retains the lower-level Run Ledger status when it is useful
    for diagnostics.
    """

    project_dir: str
    run_id: str
    status: str
    operator_state: str
    run_status: str
    last_activity_at: datetime | None
    last_activity_display: str
    age_days: int | None
    age_label: str
    stage: str
    stage_label: str
    review_total: int
    review_remaining: int
    review_note: str
    review_remaining_is_conservative: bool
    artifact_available_count: int
    artifact_missing_count: int
    next_action_id: str
    next_action_text: str
    detail: str

    @property
    def exact_display(self) -> str:
        """Alias for callers that name the absolute timestamp explicitly."""

        return self.last_activity_display

    @property
    def artifact_available(self) -> int:
        return self.artifact_available_count

    @property
    def artifact_missing(self) -> int:
        return self.artifact_missing_count

    @property
    def available_artifact_count(self) -> int:
        return self.artifact_available_count

    @property
    def missing_artifact_count(self) -> int:
        return self.artifact_missing_count


@dataclass(frozen=True)
class _CapsuleProbe:
    capsule_dir: Path
    run_id: str
    manifest: Mapping[str, Any]
    summary: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    event_times: tuple[datetime | None, ...]
    last_activity_at: datetime
    review_total: int
    review_remaining: int
    review_note: str
    review_remaining_is_conservative: bool
    artifact_available_count: int
    artifact_missing_count: int


def _safe_project_path(project_dir: object) -> Path:
    try:
        return Path(project_dir)  # type: ignore[arg-type]
    except Exception:
        return Path("")


def _display_project_path(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except Exception:
        return str(path)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_now(now: datetime | str | None) -> datetime:
    parsed = _parse_datetime(now)
    return parsed if parsed is not None else datetime.now(timezone.utc)


def _read_json_object(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _read_events(path: Path) -> tuple[tuple[Mapping[str, Any], ...], tuple[datetime | None, ...]]:
    events: list[Mapping[str, Any]] = []
    times: list[datetime | None] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # One torn line should not hide the intact history around it.
                    continue
                if not isinstance(value, Mapping):
                    continue
                events.append(value)
                times.append(_parse_datetime(value.get("occurred_at")))
    except (OSError, UnicodeError):
        return (), ()
    return tuple(events), tuple(times)


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _review_counts(
    capsule_dir: Path,
    events: Sequence[Mapping[str, Any]],
    event_times: Sequence[datetime | None],
) -> tuple[int, int, str, bool]:
    cases_payload = _read_json_value(capsule_dir / "cases.json")
    total = 0
    if isinstance(cases_payload, Mapping):
        cases = cases_payload.get("cases")
        if isinstance(cases, list):
            total = len(cases)
        else:
            total = _non_negative_int(cases_payload.get("case_count")) or 0
    elif isinstance(cases_payload, list):
        total = len(cases_payload)

    if total <= 0:
        return 0, 0, "", False

    # The production executor records an exact remaining count after applying a
    # batch.  Merely summing ``selection_count`` is not safe because decisions
    # can overlap, so it is intentionally not used as a fallback.
    reliable: list[tuple[datetime, int, int]] = []
    for index, event in enumerate(events):
        if str(event.get("event_type", "")).strip() != "decision.applied":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        remaining = _non_negative_int(payload.get("remaining_review_cases"))
        if remaining is None or remaining > total:
            continue
        event_time = event_times[index] if index < len(event_times) else None
        if event_time is not None:
            reliable.append((event_time.astimezone(timezone.utc), index, remaining))

    if reliable:
        remaining = max(reliable, key=lambda item: (item[0], item[1]))[2]
        return total, remaining, "依最近一次已套用紀錄計算", False

    return (
        total,
        total,
        "未找到可靠的已套用項目鍵，待確認數採保守估計",
        True,
    )


def _artifact_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping) and isinstance(value.get("artifacts"), list):
        return [
            item
            for item in value["artifacts"]
            if isinstance(item, Mapping)
        ]
    return []


def _artifact_counts(project_dir: Path, capsule_dir: Path) -> tuple[int, int]:
    items = _artifact_items(_read_json_value(capsule_dir / "artifacts.json"))
    available = 0
    missing = 0
    for item in items:
        uri = str(item.get("uri", "")).strip()
        if not uri:
            missing += 1
            continue
        try:
            artifact_path = Path(uri)
            if not artifact_path.is_absolute():
                artifact_path = project_dir / artifact_path
            exists = artifact_path.exists()
        except (OSError, TypeError, ValueError):
            exists = False
        if exists:
            available += 1
        else:
            missing += 1
    return available, missing


def _probe_capsule(project_dir: Path, capsule_dir: Path) -> _CapsuleProbe | None:
    manifest = _read_json_object(capsule_dir / "manifest.json")
    if manifest is None:
        return None
    summary = _read_json_object(capsule_dir / "summary.json") or {}
    events, event_times = _read_events(capsule_dir / "events.jsonl")
    valid_times = [item for item in event_times if item is not None]
    if not events or not valid_times:
        # Recency must come from evidence, never from folder or file mtimes.
        return None

    run_id = str(manifest.get("run_id", "")).strip() or capsule_dir.name
    review_total, review_remaining, review_note, conservative = _review_counts(
        capsule_dir,
        events,
        event_times,
    )
    artifact_available, artifact_missing = _artifact_counts(
        project_dir,
        capsule_dir,
    )
    return _CapsuleProbe(
        capsule_dir=capsule_dir,
        run_id=run_id,
        manifest=manifest,
        summary=summary,
        events=events,
        event_times=event_times,
        last_activity_at=max(valid_times),
        review_total=review_total,
        review_remaining=review_remaining,
        review_note=review_note,
        review_remaining_is_conservative=conservative,
        artifact_available_count=artifact_available,
        artifact_missing_count=artifact_missing,
    )


def _raw_run_status(probe: _CapsuleProbe) -> str:
    status = str(probe.summary.get("status", "")).strip().lower()
    terminal = ""
    for event in probe.events:
        event_type = str(event.get("event_type", "")).strip()
        if event_type == "run.failed":
            terminal = "failed"
        elif event_type == "run.completed":
            terminal = "completed"
    if terminal:
        return terminal
    return status or "running"


def _operator_state(run_status: str, review_remaining: int) -> str:
    if run_status == "failed":
        return "failed"
    if run_status == "completed":
        return "awaiting_review" if review_remaining > 0 else "completed"
    # A historical capsule that never reached a terminal event cannot still be
    # presumed active after the application has been reopened.
    return "interrupted"


def _last_stage(probe: _CapsuleProbe) -> str:
    stage = ""
    for event in probe.events:
        candidate = str(event.get("stage", "")).strip()
        if candidate:
            stage = candidate
    if not stage:
        stage = str(probe.summary.get("current_stage", "")).strip()
    return stage


def _stage_label(stage: str) -> str:
    if not stage:
        return "未記錄階段"
    return _STAGE_LABELS.get(stage.lower(), stage.replace("_", " "))


def _activity_display(activity: datetime, now: datetime) -> tuple[str, int, str]:
    display_zone = now.tzinfo or timezone.utc
    local_activity = activity.astimezone(display_zone)
    local_now = now.astimezone(display_zone)
    exact = local_activity.strftime("%Y/%m/%d %H:%M")
    age_days = max(0, (local_now.date() - local_activity.date()).days)
    if age_days == 0:
        age_label = "今天"
    elif age_days < 60:
        age_label = f"{age_days}天前"
    elif age_days < 365:
        months = max(2, int(math.floor(age_days / 30.4375 + 0.5)))
        age_label = f"約{months}個月前"
    else:
        years = max(1, int(math.floor(age_days / 365.2425 + 0.5)))
        age_label = f"約{years}年前"
    return exact, age_days, age_label


def _next_action(state: str, stage_label: str, remaining: int) -> tuple[str, str]:
    if state == "failed":
        return "inspect_failed_run", f"查看「{stage_label}」失敗原因後重新執行"
    if state == "interrupted":
        return "restart_interrupted_run", "確認上次中斷位置與輸入檔後重新執行"
    if state == "awaiting_review":
        return "continue_review", f"繼續處理 {remaining} 筆待確認項目"
    if state == "completed":
        return "review_last_run", "檢視上次成果，確認輸入更新後再執行"
    return "start_first_run", "完成專案設定並執行第一次分析"


def _detail(
    state: str,
    exact: str,
    age_label: str,
    stage_label: str,
    review_total: int,
    review_remaining: int,
    review_note: str,
    artifact_available: int,
    artifact_missing: int,
) -> str:
    parts = [
        f"上次活動：{exact}（{age_label}）",
        f"狀態：{_STATE_LABELS[state]}",
        f"最後階段：{stage_label}",
    ]
    if state == "failed":
        parts.append(f"失敗階段：{stage_label}")
    if review_total:
        review = f"待確認：{review_remaining}/{review_total} 筆"
        if review_note:
            review += f"（{review_note}）"
        parts.append(review)
    parts.append(f"產物：{artifact_available} 個可用、{artifact_missing} 個遺失")
    return "；".join(parts) + "。"


def _no_history(project_dir: Path) -> ProjectContinuitySnapshot:
    action_id, action_text = _next_action("no_history", "", 0)
    return ProjectContinuitySnapshot(
        project_dir=_display_project_path(project_dir),
        run_id="",
        status="no_history",
        operator_state="no_history",
        run_status="no_history",
        last_activity_at=None,
        last_activity_display="",
        age_days=None,
        age_label="",
        stage="",
        stage_label="尚未開始",
        review_total=0,
        review_remaining=0,
        review_note="",
        review_remaining_is_conservative=False,
        artifact_available_count=0,
        artifact_missing_count=0,
        next_action_id=action_id,
        next_action_text=action_text,
        detail="尚未找到執行紀錄；可從專案設定開始第一次分析。",
    )


def load_project_continuity(
    project_dir: object,
    now: datetime | str | None = None,
) -> ProjectContinuitySnapshot:
    """Load the newest trustworthy Run Capsule without changing the project.

    This function is a GUI-safe boundary: inaccessible paths, malformed JSON,
    partial writes, and unexpected values all degrade to ``no_history``.
    """

    project_path = _safe_project_path(project_dir)
    try:
        runs_root = project_path / ".flowdesk" / "runs"
        if not runs_root.is_dir():
            return _no_history(project_path)

        probes: list[_CapsuleProbe] = []
        try:
            capsule_dirs = list(runs_root.iterdir())
        except OSError:
            return _no_history(project_path)
        for capsule_dir in capsule_dirs:
            try:
                if not capsule_dir.is_dir():
                    continue
                probe = _probe_capsule(project_path, capsule_dir)
                if probe is not None:
                    probes.append(probe)
            except Exception:
                # A corrupt capsule must not prevent an older intact one from
                # helping the operator re-enter the project.
                continue
        if not probes:
            return _no_history(project_path)

        latest = max(
            probes,
            key=lambda item: item.last_activity_at.astimezone(timezone.utc),
        )
        current_time = _normalize_now(now)
        exact, age_days, age_label = _activity_display(
            latest.last_activity_at,
            current_time,
        )
        run_status = _raw_run_status(latest)
        state = _operator_state(run_status, latest.review_remaining)
        stage = _last_stage(latest)
        stage_label = _stage_label(stage)
        action_id, action_text = _next_action(
            state,
            stage_label,
            latest.review_remaining,
        )
        return ProjectContinuitySnapshot(
            project_dir=_display_project_path(project_path),
            run_id=latest.run_id,
            status=state,
            operator_state=state,
            run_status=run_status,
            last_activity_at=latest.last_activity_at,
            last_activity_display=exact,
            age_days=age_days,
            age_label=age_label,
            stage=stage,
            stage_label=stage_label,
            review_total=latest.review_total,
            review_remaining=latest.review_remaining,
            review_note=latest.review_note,
            review_remaining_is_conservative=(
                latest.review_remaining_is_conservative
            ),
            artifact_available_count=latest.artifact_available_count,
            artifact_missing_count=latest.artifact_missing_count,
            next_action_id=action_id,
            next_action_text=action_text,
            detail=_detail(
                state,
                exact,
                age_label,
                stage_label,
                latest.review_total,
                latest.review_remaining,
                latest.review_note,
                latest.artifact_available_count,
                latest.artifact_missing_count,
            ),
        )
    except Exception:
        return _no_history(project_path)


__all__ = ["ProjectContinuitySnapshot", "load_project_continuity"]
