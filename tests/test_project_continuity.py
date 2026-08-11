# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.project_continuity import load_project_continuity


def _write_capsule(
    project_dir: Path,
    folder_name: str,
    *,
    run_id: str,
    activity_at: datetime,
    status: str = "completed",
    stage: str = "match",
    event_type: str | None = None,
    finish_time: str = "",
    cases: list[dict] | None = None,
    extra_events: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> Path:
    capsule = project_dir / ".flowdesk" / "runs" / folder_name
    capsule.mkdir(parents=True)
    (capsule / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "created_at": "2000-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    (capsule / "summary.json").write_text(
        json.dumps(
            {
                "status": status,
                "current_stage": stage,
                # This value is deliberately not used for recency selection.
                "finished_at": finish_time,
            }
        ),
        encoding="utf-8",
    )
    kind = event_type
    if kind is None:
        kind = {
            "completed": "run.completed",
            "failed": "run.failed",
        }.get(status, "stage.started")
    events = [
        {
            "sequence": 1,
            "occurred_at": activity_at.isoformat(),
            "event_type": kind,
            "stage": stage,
            "payload": {},
        }
    ]
    events.extend(extra_events or [])
    (capsule / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    if cases is not None:
        (capsule / "cases.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "case_count": len(cases),
                    "cases": cases,
                }
            ),
            encoding="utf-8",
        )
    if artifacts is not None:
        (capsule / "artifacts.json").write_text(
            json.dumps(artifacts),
            encoding="utf-8",
        )
    return capsule


def test_probe_is_read_only_and_does_not_create_flowdesk(tmp_path: Path):
    missing_project = tmp_path / "project-that-does-not-exist"
    snapshot = load_project_continuity(missing_project)

    assert snapshot.status == "no_history"
    assert snapshot.operator_state == "no_history"
    assert not missing_project.exists()

    existing_project = tmp_path / "existing"
    existing_project.mkdir()
    before = sorted(path.relative_to(existing_project) for path in existing_project.rglob("*"))
    load_project_continuity(existing_project)
    after = sorted(path.relative_to(existing_project) for path in existing_project.rglob("*"))
    assert after == before == []


def test_latest_capsule_uses_last_event_activity_not_folder_or_finish_time(
    tmp_path: Path,
):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    _write_capsule(
        tmp_path,
        "zzz-sorts-last",
        run_id="run-older",
        activity_at=now - timedelta(days=10),
        finish_time="2099-01-01T00:00:00+00:00",
    )
    _write_capsule(
        tmp_path,
        "aaa-sorts-first",
        run_id="run-newer",
        activity_at=now - timedelta(days=2),
        finish_time="1999-01-01T00:00:00+00:00",
    )
    corrupt = tmp_path / ".flowdesk" / "runs" / "zzzz-corrupt"
    corrupt.mkdir()
    (corrupt / "manifest.json").write_text("{not json", encoding="utf-8")
    (corrupt / "events.jsonl").write_text(
        json.dumps(
            {
                "occurred_at": "2199-01-01T00:00:00+00:00",
                "event_type": "run.completed",
            }
        ),
        encoding="utf-8",
    )

    snapshot = load_project_continuity(tmp_path, now=now)

    assert snapshot.run_id == "run-newer"
    assert snapshot.age_days == 2
    assert snapshot.age_label == "2天前"


def test_completed_capsule_with_cases_requires_review_conservatively(tmp_path: Path):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    _write_capsule(
        tmp_path,
        "run",
        run_id="run-review",
        activity_at=now - timedelta(days=1),
        cases=[{"iso_line": "A"}, {"iso_line": "B"}, {"iso_line": "C"}],
    )

    snapshot = load_project_continuity(tmp_path, now=now)

    assert snapshot.run_status == "completed"
    assert snapshot.status == snapshot.operator_state == "awaiting_review"
    assert snapshot.review_total == 3
    assert snapshot.review_remaining == 3
    assert snapshot.review_remaining_is_conservative
    assert "保守估計" in snapshot.review_note
    assert snapshot.next_action_id == "continue_review"


def test_exact_remaining_review_count_uses_latest_applied_event(tmp_path: Path):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    _write_capsule(
        tmp_path,
        "run",
        run_id="run-applied",
        activity_at=now - timedelta(hours=2),
        cases=[{"iso_line": "A"}, {"iso_line": "B"}, {"iso_line": "C"}],
        extra_events=[
            {
                "sequence": 2,
                "occurred_at": (now - timedelta(hours=1)).isoformat(),
                "event_type": "decision.applied",
                "stage": "review",
                "payload": {"selection_count": 2, "remaining_review_cases": 1},
            }
        ],
    )

    snapshot = load_project_continuity(tmp_path, now=now)

    assert snapshot.review_total == 3
    assert snapshot.review_remaining == 1
    assert not snapshot.review_remaining_is_conservative
    assert snapshot.stage_label == "人工判讀"
    assert snapshot.last_activity_at == now - timedelta(hours=1)


def test_completed_capsule_with_zero_remaining_review_is_completed(tmp_path: Path):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    _write_capsule(
        tmp_path,
        "run",
        run_id="run-finished-review",
        activity_at=now - timedelta(hours=2),
        cases=[{"iso_line": "A"}],
        extra_events=[
            {
                "sequence": 2,
                "occurred_at": (now - timedelta(hours=1)).isoformat(),
                "event_type": "decision.applied",
                "stage": "review",
                "payload": {"remaining_review_cases": 0},
            }
        ],
    )

    snapshot = load_project_continuity(tmp_path, now=now)

    assert snapshot.review_total == 1
    assert snapshot.review_remaining == 0
    assert snapshot.operator_state == "completed"


def test_artifact_availability_and_missing_counts(tmp_path: Path):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    (tmp_path / "available.txt").write_text("ready", encoding="utf-8")
    _write_capsule(
        tmp_path,
        "run",
        run_id="run-artifacts",
        activity_at=now,
        artifacts=[
            {"name": "available", "uri": "available.txt", "external": False},
            {"name": "missing", "uri": "missing.txt", "external": False},
        ],
    )

    snapshot = load_project_continuity(tmp_path, now=now)

    assert snapshot.artifact_available_count == 1
    assert snapshot.artifact_missing_count == 1
    assert "1 個可用、1 個遺失" in snapshot.detail


def test_running_capsule_is_interrupted_and_failed_keeps_last_stage(tmp_path: Path):
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    running_project = tmp_path / "running"
    _write_capsule(
        running_project,
        "run",
        run_id="run-interrupted",
        activity_at=now - timedelta(days=1),
        status="running",
        stage="extract",
    )
    interrupted = load_project_continuity(running_project, now=now)
    assert interrupted.status == "interrupted"
    assert interrupted.stage_label == "掃描 3D 管線"

    failed_project = tmp_path / "failed"
    _write_capsule(
        failed_project,
        "run",
        run_id="run-failed",
        activity_at=now,
        status="failed",
        stage="mapping",
    )
    failed = load_project_continuity(failed_project, now=now)
    assert failed.status == "failed"
    assert failed.stage_label == "建立映射"
    assert "失敗階段：建立映射" in failed.detail
    assert "建立映射" in failed.next_action_text


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, "今天"),
        (61, "約2個月前"),
        (183, "約6個月前"),
        (366, "約1年前"),
    ],
)
def test_long_gap_age_labels_keep_absolute_date(
    tmp_path: Path,
    days: int,
    expected: str,
):
    now = datetime(2026, 8, 11, 9, 30, tzinfo=timezone.utc)
    activity = now - timedelta(days=days)
    project = tmp_path / str(days)
    _write_capsule(
        project,
        "run",
        run_id=f"run-{days}",
        activity_at=activity,
    )

    snapshot = load_project_continuity(project, now=now)
    exact = activity.strftime("%Y/%m/%d %H:%M")

    assert snapshot.age_days == days
    assert snapshot.age_label == expected
    assert snapshot.last_activity_display == exact
    assert snapshot.exact_display == exact
    assert exact in snapshot.detail


def test_all_broken_capsules_degrade_to_no_history(tmp_path: Path):
    capsule = tmp_path / ".flowdesk" / "runs" / "broken"
    capsule.mkdir(parents=True)
    (capsule / "manifest.json").write_text(json.dumps({"run_id": "broken"}), encoding="utf-8")
    (capsule / "summary.json").write_text("[]", encoding="utf-8")
    (capsule / "events.jsonl").write_text("not-json\n", encoding="utf-8")

    snapshot = load_project_continuity(tmp_path)

    assert snapshot.status == "no_history"
    assert snapshot.run_id == ""
