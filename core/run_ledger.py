# -*- coding: utf-8 -*-
"""Append-only run ledger and AI-safe decision inbox.

The ledger deliberately separates observation/proposal from mutation of pipeline
artifacts.  It stores its authoritative state in SQLite and mirrors every run to
a human/agent-readable "Run Capsule" under ``<project>/.flowdesk/runs``.

The module has no Qt dependency.  Every public operation opens its own SQLite
connection, while a process-wide lock serializes writers and capsule refreshes.
This makes a single :class:`RunLedger` instance (or multiple instances pointing
at the same project) safe to call from QThread workers.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from typing import Any, Mapping, Sequence
import uuid


SCHEMA_VERSION = 1
CAPSULE_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EVENT_TYPE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")

_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[str, threading.RLock] = {}


class RunLedgerError(RuntimeError):
    """Base class for ledger errors."""


class RunNotFoundError(RunLedgerError):
    """Raised when a run id is unknown."""


class StaleStateError(RunLedgerError):
    """Raised when a proposal no longer targets the current frozen state."""


class ProposalStateError(RunLedgerError):
    """Raised when a proposal has already been decided."""


class OwnershipConflictError(RunLedgerError):
    """Raised when one item is claimed by two different ISO families."""

    def __init__(
        self,
        item_id: str,
        current_family_id: str,
        requested_family_id: str,
        event_id: str = "",
    ) -> None:
        self.item_id = item_id
        self.current_family_id = current_family_id
        self.requested_family_id = requested_family_id
        self.event_id = event_id
        super().__init__(
            f"3D ITEM {item_id!r} already belongs to "
            f"{current_family_id!r}; cannot claim it for {requested_family_id!r}"
        )


class LedgerIntegrityError(RunLedgerError):
    """Raised when an exported or stored event chain is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> str:
    """Return deterministic, strict JSON used for hashes and SQLite payloads."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not valid JSON data: {exc}") from exc


def _pretty_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _json_load(value: object, default: Any) -> Any:
    text = "" if value is None else str(value)
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _require_text(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _validate_safe_id(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(
            f"{name} may contain only letters, numbers, '.', '_' and '-' "
            "and must be at most 128 characters"
        )
    return text


def _actor(value: object, default_kind: str, default_id: str) -> dict[str, Any]:
    if value is None:
        return {"kind": default_kind, "id": default_id}
    if isinstance(value, str):
        return {"kind": default_kind, "id": _require_text(value, "actor")}
    if isinstance(value, Mapping):
        result = dict(value)
        result["kind"] = _require_text(result.get("kind", default_kind), "actor.kind")
        result["id"] = _require_text(result.get("id", default_id), "actor.id")
        _canonical_json(result)
        return result
    raise ValueError("actor must be a string or mapping")


def _project_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROJECT_LOCKS[key] = lock
        return lock


class RunLedger:
    """SQLite-backed append-only ledger for one project workspace."""

    def __init__(self, project_dir: str | os.PathLike[str], timeout: float = 30.0):
        self.project_dir = Path(project_dir).expanduser().resolve()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.flowdesk_dir = self.project_dir / ".flowdesk"
        self.runs_dir = self.flowdesk_dir / "runs"
        self.flowdesk_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.flowdesk_dir / "ledger.sqlite"
        self.timeout = float(timeout)
        self.project_id = "project-" + _sha256_text(
            os.path.normcase(str(self.project_dir))
        )[:20]
        self._write_lock = _project_lock(self.flowdesk_dir)
        with self._write_lock:
            self._initialize_database()

    # ------------------------------------------------------------------
    # Public run/event API
    # ------------------------------------------------------------------

    def start_run(
        self,
        *,
        input_fingerprint: str,
        base_state_hash: str,
        config: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        actor: object = None,
    ) -> str:
        """Create a frozen run and its first ``run.started`` event."""
        input_fp = _require_text(input_fingerprint, "input_fingerprint")
        base_hash = _require_text(base_state_hash, "base_state_hash")
        rid = _validate_safe_id(run_id or self._new_id("run"), "run_id")
        sid = str(session_id or "").strip()
        config_obj = dict(config or {})
        metadata_obj = dict(metadata or {})
        _canonical_json(config_obj)
        _canonical_json(metadata_obj)
        now = _utc_now()

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, project_id, status, created_at, started_at,
                        finished_at, input_fingerprint, base_state_hash,
                        config_json, metadata_json, summary_json,
                        last_event_sequence, last_event_hash
                    ) VALUES (?, ?, 'running', ?, ?, '', ?, ?, ?, ?, '{}', 0, '')
                    """,
                    (
                        rid,
                        self.project_id,
                        now,
                        now,
                        input_fp,
                        base_hash,
                        _canonical_json(config_obj),
                        _canonical_json(metadata_obj),
                    ),
                )
                self._insert_event(
                    conn,
                    rid,
                    "run.started",
                    payload={"config": config_obj, "metadata": metadata_obj},
                    session_id=sid,
                    actor=_actor(actor, "pipeline_engine", "pipeline"),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RunLedgerError(f"run_id already exists: {rid}") from exc
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return rid

    def emit(
        self,
        run_id: str,
        event_type: str,
        *,
        payload: Mapping[str, Any] | None = None,
        stage: str = "",
        actor: object = None,
        session_id: str = "",
        subject: Mapping[str, Any] | None = None,
        evidence_refs: Sequence[str] | None = None,
        correlation_id: str = "",
        causation_id: str = "",
    ) -> dict[str, Any]:
        """Append one structured event and refresh the Run Capsule."""
        rid = _validate_safe_id(run_id, "run_id")
        etype = self._validate_event_type(event_type)
        payload_obj = dict(payload or {})
        subject_obj = dict(subject or {})
        refs = [str(value).strip() for value in (evidence_refs or []) if str(value).strip()]
        _canonical_json(payload_obj)
        _canonical_json(subject_obj)
        _canonical_json(refs)

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                event = self._insert_event(
                    conn,
                    rid,
                    etype,
                    payload=payload_obj,
                    stage=str(stage).strip(),
                    actor=_actor(actor, "pipeline_engine", "pipeline"),
                    session_id=str(session_id).strip(),
                    subject=subject_obj,
                    evidence_refs=refs,
                    correlation_id=str(correlation_id).strip(),
                    causation_id=str(causation_id).strip(),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return event

    append = emit
    append_event = emit
    emit_event = emit

    def stage_started(
        self,
        run_id: str,
        stage: str,
        *,
        detail: str = "",
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        name = _require_text(stage, "stage")
        return self.emit(
            run_id,
            "stage.started",
            stage=name,
            payload={"detail": str(detail)},
            actor=actor,
            session_id=session_id,
        )

    start_stage = stage_started

    def stage_progress(
        self,
        run_id: str,
        stage: str,
        percent: int | float,
        *,
        message: str = "",
        current: int | float | None = None,
        total: int | float | None = None,
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        name = _require_text(stage, "stage")
        pct = float(percent)
        if not 0 <= pct <= 100:
            raise ValueError("percent must be between 0 and 100")
        payload: dict[str, Any] = {"percent": pct, "message": str(message)}
        if current is not None:
            payload["current"] = current
        if total is not None:
            payload["total"] = total
        return self.emit(
            run_id,
            "stage.progress",
            stage=name,
            payload=payload,
            actor=actor,
            session_id=session_id,
        )

    update_stage = stage_progress

    def stage_completed(
        self,
        run_id: str,
        stage: str,
        *,
        success: bool = True,
        summary: Mapping[str, Any] | str | None = None,
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        name = _require_text(stage, "stage")
        return self.emit(
            run_id,
            "stage.completed" if success else "stage.failed",
            stage=name,
            payload={"success": bool(success), "summary": summary if summary is not None else ""},
            actor=actor,
            session_id=session_id,
        )

    finish_stage = stage_completed

    def record_metric(
        self,
        run_id: str,
        name: str,
        value: Any,
        *,
        unit: str = "",
        stage: str = "",
        tags: Mapping[str, Any] | None = None,
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        metric_name = _require_text(name, "metric name")
        return self.emit(
            run_id,
            "metric.recorded",
            stage=str(stage).strip(),
            payload={
                "name": metric_name,
                "value": value,
                "unit": str(unit),
                "tags": dict(tags or {}),
            },
            actor=actor,
            session_id=session_id,
        )

    metric = record_metric

    def register_artifact(
        self,
        run_id: str,
        path: str | os.PathLike[str],
        *,
        kind: str = "file",
        name: str = "",
        metadata: Mapping[str, Any] | None = None,
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Hash and register an immutable observation of an artifact file."""
        rid = _validate_safe_id(run_id, "run_id")
        artifact_path = Path(path).expanduser().resolve()
        if not artifact_path.is_file():
            raise FileNotFoundError(f"artifact file does not exist: {artifact_path}")
        artifact_id = self._new_id("artifact")
        artifact_kind = _require_text(kind, "artifact kind")
        metadata_obj = dict(metadata or {})
        _canonical_json(metadata_obj)
        checksum = _sha256_file(artifact_path)
        size_bytes = artifact_path.stat().st_size
        uri, external = self._artifact_uri(artifact_path)
        now = _utc_now()

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._get_run_row(conn, rid)
                conn.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, run_id, kind, name, uri, external,
                        size_bytes, sha256, metadata_json, created_at, event_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                    """,
                    (
                        artifact_id,
                        rid,
                        artifact_kind,
                        str(name).strip() or artifact_path.name,
                        uri,
                        int(external),
                        size_bytes,
                        checksum,
                        _canonical_json(metadata_obj),
                        now,
                    ),
                )
                event = self._insert_event(
                    conn,
                    rid,
                    "artifact.registered",
                    payload={
                        "artifact_id": artifact_id,
                        "kind": artifact_kind,
                        "name": str(name).strip() or artifact_path.name,
                        "uri": uri,
                        "external": external,
                        "size_bytes": size_bytes,
                        "sha256": checksum,
                        "metadata": metadata_obj,
                    },
                    actor=_actor(actor, "pipeline_engine", "pipeline"),
                    session_id=str(session_id).strip(),
                    subject={"kind": "artifact", "id": artifact_id},
                )
                conn.execute(
                    "UPDATE artifacts SET event_id=? WHERE artifact_id=?",
                    (event["event_id"], artifact_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return self.get_artifact(artifact_id)

    artifact = register_artifact

    def write_review_cases(
        self,
        run_id: str,
        cases: Sequence[Mapping[str, Any]],
        *,
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Write the frozen review evidence set into the Run Capsule.

        The file is an immutable observation for this run.  AI consumers receive
        it as read-only context; decisions remain separate ledger events.
        """

        rid = _validate_safe_id(run_id, "run_id")
        normalized_cases = [dict(case) for case in cases]
        _canonical_json(normalized_cases)
        # Validate the run before creating the capsule file.
        self.get_run(rid)
        path = self._capsule_dir(rid) / "cases.json"
        payload = {
            "schema_version": 1,
            "run_id": rid,
            "case_count": len(normalized_cases),
            "cases": normalized_cases,
        }
        with self._write_lock:
            self._atomic_write(path, _pretty_json(payload))
        return self.register_artifact(
            rid,
            path,
            kind="review_cases",
            name="cases.json",
            metadata={"case_count": len(normalized_cases), "read_only": True},
            actor=actor,
            session_id=session_id,
        )

    def finish_run(
        self,
        run_id: str,
        *,
        success: bool = True,
        summary: Mapping[str, Any] | str | None = None,
        error: str = "",
        actor: object = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Close pipeline execution while keeping the run open for review events."""
        rid = _validate_safe_id(run_id, "run_id")
        status = "completed" if success else "failed"
        summary_obj: Any = summary if summary is not None else {}
        _canonical_json(summary_obj)
        now = _utc_now()

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run = self._get_run_row(conn, rid)
                if str(run["status"]) != "running":
                    raise RunLedgerError(
                        f"run {rid} is already in terminal state {run['status']!r}"
                    )
                event = self._insert_event(
                    conn,
                    rid,
                    "run.completed" if success else "run.failed",
                    payload={
                        "success": bool(success),
                        "summary": summary_obj,
                        "error": str(error),
                    },
                    actor=_actor(actor, "pipeline_engine", "pipeline"),
                    session_id=str(session_id).strip(),
                )
                conn.execute(
                    """
                    UPDATE runs
                    SET status=?, finished_at=?, summary_json=?
                    WHERE run_id=?
                    """,
                    (status, now, _canonical_json(summary_obj), rid),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return event

    # ------------------------------------------------------------------
    # Proposals and human decisions
    # ------------------------------------------------------------------

    def create_agent_proposal(
        self,
        run_id: str,
        *,
        action: str,
        payload: Mapping[str, Any] | None = None,
        agent_id: str = "agent",
        evidence_refs: Sequence[str] | None = None,
        input_fingerprint: str | None = None,
        base_state_hash: str | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Submit an AI proposal; this never mutates pipeline artifacts."""
        rid = _validate_safe_id(run_id, "run_id")
        action_name = _require_text(action, "action")
        aid = _require_text(agent_id, "agent_id")
        payload_obj = dict(payload or {})
        refs = [str(value).strip() for value in (evidence_refs or []) if str(value).strip()]
        _canonical_json(payload_obj)
        _canonical_json(refs)
        proposal_id = self._new_id("proposal")
        now = _utc_now()

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run = self._get_run_row(conn, rid)
                bound_input = str(run["input_fingerprint"])
                bound_base = str(run["base_state_hash"])
                self._validate_optional_expected(
                    input_fingerprint,
                    bound_input,
                    "input_fingerprint",
                )
                self._validate_optional_expected(
                    base_state_hash,
                    bound_base,
                    "base_state_hash",
                )
                hash_payload = {
                    "proposal_id": proposal_id,
                    "run_id": rid,
                    "created_at": now,
                    "agent_id": aid,
                    "action": action_name,
                    "input_fingerprint": bound_input,
                    "base_state_hash": bound_base,
                    "payload": payload_obj,
                    "evidence_refs": refs,
                }
                proposal_hash = _sha256_text(_canonical_json(hash_payload))
                conn.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, run_id, created_at, agent_id, action,
                        status, input_fingerprint, base_state_hash,
                        payload_json, evidence_refs_json, proposal_hash,
                        proposed_event_id, decided_at, decision_id
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, '', '', '')
                    """,
                    (
                        proposal_id,
                        rid,
                        now,
                        aid,
                        action_name,
                        bound_input,
                        bound_base,
                        _canonical_json(payload_obj),
                        _canonical_json(refs),
                        proposal_hash,
                    ),
                )
                event = self._insert_event(
                    conn,
                    rid,
                    "decision.proposed",
                    payload={
                        "proposal_id": proposal_id,
                        "proposal_hash": proposal_hash,
                        "action": action_name,
                        "payload": payload_obj,
                    },
                    actor=_actor(aid, "ai_agent", aid),
                    session_id=str(session_id).strip(),
                    subject={"kind": "proposal", "id": proposal_id},
                    evidence_refs=refs,
                    correlation_id=proposal_id,
                )
                conn.execute(
                    "UPDATE proposals SET proposed_event_id=? WHERE proposal_id=?",
                    (event["event_id"], proposal_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return self.get_proposal(proposal_id)

    create_proposal = create_agent_proposal

    def approve_proposal(
        self,
        run_id: str,
        proposal_id: str,
        *,
        input_fingerprint: str,
        base_state_hash: str,
        approved_by: str,
        note: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        return self._decide_proposal(
            run_id,
            proposal_id,
            outcome="approved",
            expected_input_fingerprint=input_fingerprint,
            expected_base_state_hash=base_state_hash,
            decided_by=approved_by,
            note=note,
            session_id=session_id,
        )

    approve = approve_proposal

    def reject_proposal(
        self,
        run_id: str,
        proposal_id: str,
        *,
        input_fingerprint: str,
        base_state_hash: str,
        rejected_by: str,
        reason: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        return self._decide_proposal(
            run_id,
            proposal_id,
            outcome="rejected",
            expected_input_fingerprint=input_fingerprint,
            expected_base_state_hash=base_state_hash,
            decided_by=rejected_by,
            note=reason,
            session_id=session_id,
        )

    reject = reject_proposal

    def advance_base_state(
        self,
        run_id: str,
        *,
        expected_base_state_hash: str,
        new_base_state_hash: str,
        actor: object = "executor",
        reason: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Compare-and-swap the mapping state after an external safe executor.

        The ledger never applies a mapping itself.  This hook lets that executor
        advance the frozen base hash, which automatically makes older proposals
        stale.
        """
        rid = _validate_safe_id(run_id, "run_id")
        expected = _require_text(expected_base_state_hash, "expected_base_state_hash")
        new_hash = _require_text(new_base_state_hash, "new_base_state_hash")
        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run = self._get_run_row(conn, rid)
                current = str(run["base_state_hash"])
                if current != expected:
                    raise StaleStateError(
                        f"base_state_hash is stale: expected {expected!r}, current {current!r}"
                    )
                event = self._insert_event(
                    conn,
                    rid,
                    "run.base_state_changed",
                    payload={"before": current, "after": new_hash, "reason": str(reason)},
                    actor=_actor(actor, "executor", "executor"),
                    session_id=str(session_id).strip(),
                )
                conn.execute(
                    "UPDATE runs SET base_state_hash=? WHERE run_id=?",
                    (new_hash, rid),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return event

    # ------------------------------------------------------------------
    # Ownership invariant
    # ------------------------------------------------------------------

    def claim_ownership(
        self,
        run_id: str,
        item_id: str,
        family_id: str,
        *,
        claimed_by: str = "pipeline",
        decision_id: str = "",
        metadata: Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Claim one stable 3D ITEM for one ISO family.

        Repeating the same claim is idempotent.  Claiming an item for a different
        family records ``ownership.conflict`` and raises
        :class:`OwnershipConflictError` without changing the current owner.
        """
        rid = _validate_safe_id(run_id, "run_id")
        item = _require_text(item_id, "item_id")
        family = _require_text(family_id, "family_id")
        claimant = _require_text(claimed_by, "claimed_by")
        metadata_obj = dict(metadata or {})
        _canonical_json(metadata_obj)
        now = _utc_now()
        conflict: OwnershipConflictError | None = None

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run = self._get_run_row(conn, rid)
                if decision_id:
                    self._validate_approved_decision(conn, rid, decision_id)
                existing = conn.execute(
                    """
                    SELECT * FROM ownership_locks
                    WHERE project_id=? AND item_id=?
                    """,
                    (self.project_id, item),
                ).fetchone()

                if existing is None:
                    event_type = "ownership.claimed"
                    status = "claimed"
                    event = self._insert_event(
                        conn,
                        rid,
                        event_type,
                        payload={
                            "item_id": item,
                            "family_id": family,
                            "decision_id": str(decision_id),
                            "metadata": metadata_obj,
                        },
                        actor=_actor(claimant, "executor", claimant),
                        session_id=str(session_id).strip(),
                        subject={"kind": "3d_item", "id": item},
                        correlation_id=str(decision_id).strip() or item,
                    )
                    conn.execute(
                        """
                        INSERT INTO ownership_locks (
                            project_id, item_id, family_id, input_fingerprint,
                            first_run_id, last_run_id, claimed_at, last_seen_at,
                            claimed_by, decision_id, metadata_json, claim_event_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.project_id,
                            item,
                            family,
                            str(run["input_fingerprint"]),
                            rid,
                            rid,
                            now,
                            now,
                            claimant,
                            str(decision_id),
                            _canonical_json(metadata_obj),
                            event["event_id"],
                        ),
                    )
                elif str(existing["family_id"]) == family:
                    status = "idempotent"
                    event = self._insert_event(
                        conn,
                        rid,
                        "ownership.claim_idempotent",
                        payload={
                            "item_id": item,
                            "family_id": family,
                            "original_claim_event_id": str(existing["claim_event_id"]),
                        },
                        actor=_actor(claimant, "executor", claimant),
                        session_id=str(session_id).strip(),
                        subject={"kind": "3d_item", "id": item},
                        correlation_id=str(decision_id).strip() or item,
                    )
                    conn.execute(
                        """
                        UPDATE ownership_locks
                        SET last_run_id=?, last_seen_at=?
                        WHERE project_id=? AND item_id=?
                        """,
                        (rid, now, self.project_id, item),
                    )
                else:
                    current_family = str(existing["family_id"])
                    event = self._insert_event(
                        conn,
                        rid,
                        "ownership.conflict",
                        payload={
                            "item_id": item,
                            "current_family_id": current_family,
                            "requested_family_id": family,
                            "current_claim_event_id": str(existing["claim_event_id"]),
                            "decision_id": str(decision_id),
                        },
                        actor=_actor(claimant, "executor", claimant),
                        session_id=str(session_id).strip(),
                        subject={"kind": "3d_item", "id": item},
                        correlation_id=str(decision_id).strip() or item,
                    )
                    conflict = OwnershipConflictError(
                        item,
                        current_family,
                        family,
                        event_id=event["event_id"],
                    )
                    status = "conflict"
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)

        if conflict is not None:
            raise conflict
        result = self.get_ownership(item)
        result["status"] = status
        result["event_id"] = event["event_id"]
        return result

    def release_ownership(
        self,
        run_id: str,
        item_id: str,
        family_id: str,
        *,
        released_by: str = "executor",
        reason: str,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Release an exact ownership claim as a compensating action.

        This is intentionally not a force-unlock: both ITEM and current family
        must match, and the append-only event remains in the audit chain.
        """

        rid = _validate_safe_id(run_id, "run_id")
        item = _require_text(item_id, "item_id")
        family = _require_text(family_id, "family_id")
        actor_id = _require_text(released_by, "released_by")
        why = _require_text(reason, "reason")

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._get_run_row(conn, rid)
                existing = conn.execute(
                    """
                    SELECT * FROM ownership_locks
                    WHERE project_id=? AND item_id=?
                    """,
                    (self.project_id, item),
                ).fetchone()
                if existing is None:
                    raise RunLedgerError(f"ownership does not exist for ITEM {item!r}")
                current_family = str(existing["family_id"])
                if current_family != family:
                    raise OwnershipConflictError(item, current_family, family)
                event = self._insert_event(
                    conn,
                    rid,
                    "ownership.released",
                    payload={
                        "item_id": item,
                        "family_id": family,
                        "reason": why,
                        "original_claim_event_id": str(existing["claim_event_id"]),
                    },
                    actor=_actor(actor_id, "executor", actor_id),
                    session_id=str(session_id).strip(),
                    subject={"kind": "3d_item", "id": item},
                    correlation_id=item,
                )
                conn.execute(
                    "DELETE FROM ownership_locks WHERE project_id=? AND item_id=?",
                    (self.project_id, item),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return {
            "status": "released",
            "item_id": item,
            "family_id": family,
            "event_id": event["event_id"],
        }

    # ------------------------------------------------------------------
    # Read/export API
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any]:
        rid = _validate_safe_id(run_id, "run_id")
        conn = self._connect()
        try:
            row = self._get_run_row(conn, rid)
            return self._run_from_row(row)
        finally:
            conn.close()

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        rid = _validate_safe_id(run_id, "run_id")
        conn = self._connect()
        try:
            self._get_run_row(conn, rid)
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY sequence",
                (rid,),
            ).fetchall()
            return [self._event_from_row(row) for row in rows]
        finally:
            conn.close()

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        pid = _require_text(proposal_id, "proposal_id")
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT p.*, r.input_fingerprint AS run_input_fingerprint,
                       r.base_state_hash AS run_base_state_hash
                FROM proposals p JOIN runs r ON r.run_id=p.run_id
                WHERE p.proposal_id=?
                """,
                (pid,),
            ).fetchone()
            if row is None:
                raise RunLedgerError(f"unknown proposal_id: {pid}")
            return self._proposal_from_row(row)
        finally:
            conn.close()

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        aid = _require_text(artifact_id, "artifact_id")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?",
                (aid,),
            ).fetchone()
            if row is None:
                raise RunLedgerError(f"unknown artifact_id: {aid}")
            return self._artifact_from_row(row)
        finally:
            conn.close()

    def get_ownership(self, item_id: str) -> dict[str, Any]:
        item = _require_text(item_id, "item_id")
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM ownership_locks
                WHERE project_id=? AND item_id=?
                """,
                (self.project_id, item),
            ).fetchone()
            if row is None:
                return {}
            return self._ownership_from_row(row)
        finally:
            conn.close()

    def snapshot(self, run_id: str) -> dict[str, Any]:
        """Return the complete current Run Capsule as JSON-compatible data."""
        rid = _validate_safe_id(run_id, "run_id")
        conn = self._connect()
        try:
            run_row = self._get_run_row(conn, rid)
            run = self._run_from_row(run_row)
            event_rows = conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY sequence",
                (rid,),
            ).fetchall()
            proposal_rows = conn.execute(
                """
                SELECT p.*, r.input_fingerprint AS run_input_fingerprint,
                       r.base_state_hash AS run_base_state_hash
                FROM proposals p JOIN runs r ON r.run_id=p.run_id
                WHERE p.run_id=? ORDER BY p.created_at, p.proposal_id
                """,
                (rid,),
            ).fetchall()
            decision_rows = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY decided_at, decision_id",
                (rid,),
            ).fetchall()
            artifact_rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at, artifact_id",
                (rid,),
            ).fetchall()
            ownership_activity = {
                str(_json_load(row["payload_json"], {}).get("item_id", "")).strip()
                for row in event_rows
                if str(row["event_type"]).startswith("ownership.")
            }
            ownership_activity.discard("")
            ownership_clause = "first_run_id=? OR last_run_id=?"
            ownership_params: list[str] = [rid, rid]
            if ownership_activity:
                placeholders = ",".join("?" for _ in ownership_activity)
                ownership_clause += f" OR item_id IN ({placeholders})"
                ownership_params.extend(sorted(ownership_activity))
            ownership_rows = conn.execute(
                f"""
                SELECT * FROM ownership_locks
                WHERE {ownership_clause}
                ORDER BY item_id
                """,
                ownership_params,
            ).fetchall()
        finally:
            conn.close()

        events = [self._event_from_row(row) for row in event_rows]
        proposals = [self._proposal_from_row(row) for row in proposal_rows]
        decisions = [self._decision_from_row(row) for row in decision_rows]
        artifacts = [self._artifact_from_row(row) for row in artifact_rows]
        ownership = [self._ownership_from_row(row) for row in ownership_rows]
        summary = self._build_summary(run, events, proposals, decisions, artifacts, ownership)
        return {
            "capsule_version": CAPSULE_VERSION,
            "run": run,
            "summary": summary,
            "events": events,
            "proposals": proposals,
            "decisions": decisions,
            "artifacts": artifacts,
            "ownership": ownership,
        }

    def export_agent_context(
        self,
        run_id: str,
        output_path: str | os.PathLike[str] | None = None,
        *,
        max_events: int = 500,
    ) -> str:
        """Write a bounded, read-only JSON context suitable for an AI agent."""
        rid = _validate_safe_id(run_id, "run_id")
        limit = max(0, int(max_events))
        snap = self.snapshot(rid)
        events = snap["events"]
        omitted = max(0, len(events) - limit)
        if limit:
            events = events[-limit:]
        else:
            events = []
        context = {
            "context_version": 1,
            "generated_at": _utc_now(),
            "read_only": True,
            "agent_capabilities": ["read_context", "submit_proposal"],
            "prohibited_capabilities": [
                "approve_proposal",
                "apply_decision",
                "write_artifact",
                "change_ownership",
            ],
            "run": snap["run"],
            "summary": snap["summary"],
            "events": events,
            "events_omitted": omitted,
            "proposals": snap["proposals"],
            "decisions": snap["decisions"],
            "artifacts": snap["artifacts"],
            "ownership": snap["ownership"],
        }
        cases_path = self._capsule_dir(rid) / "cases.json"
        if cases_path.is_file():
            try:
                with cases_path.open("r", encoding="utf-8") as handle:
                    cases_payload = json.load(handle)
                context["review_cases"] = cases_payload.get("cases", [])
                context["review_case_count"] = int(
                    cases_payload.get("case_count", 0)
                )
            except (OSError, TypeError, ValueError):
                context["review_cases"] = []
                context["review_case_count"] = 0
        path = (
            Path(output_path).expanduser().resolve()
            if output_path is not None
            else self._capsule_dir(rid) / "agent_context.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            self._atomic_write(path, _pretty_json(context))
        return str(path)

    def hash_chain_report(self, run_id: str) -> dict[str, Any]:
        rid = _validate_safe_id(run_id, "run_id")
        run = self.get_run(rid)
        events = self.list_events(rid)
        errors: list[str] = []
        previous = ""
        expected_sequence = 1
        for event in events:
            sequence = int(event.get("sequence", 0))
            if sequence != expected_sequence:
                errors.append(
                    f"sequence {sequence}: expected {expected_sequence}"
                )
            if str(event.get("previous_hash", "")) != previous:
                errors.append(f"sequence {sequence}: previous_hash mismatch")
            stored_hash = str(event.get("event_hash", ""))
            core = dict(event)
            core.pop("event_hash", None)
            computed_hash = _sha256_text(_canonical_json(core))
            if stored_hash != computed_hash:
                errors.append(f"sequence {sequence}: event_hash mismatch")
            previous = stored_hash
            expected_sequence += 1
        if int(run["last_event_sequence"]) != len(events):
            errors.append(
                "run head sequence mismatch "
                f"(stored={run['last_event_sequence']}, events={len(events)})"
            )
        if str(run["last_event_hash"]) != previous:
            errors.append("run head hash mismatch")
        return {
            "valid": not errors,
            "run_id": rid,
            "event_count": len(events),
            "head_hash": previous,
            "errors": errors,
        }

    def verify_hash_chain(self, run_id: str, *, raise_on_error: bool = False) -> bool:
        report = self.hash_chain_report(run_id)
        if raise_on_error and not report["valid"]:
            raise LedgerIntegrityError("; ".join(report["errors"]))
        return bool(report["valid"])

    # ------------------------------------------------------------------
    # Internal decision/event operations
    # ------------------------------------------------------------------

    def _decide_proposal(
        self,
        run_id: str,
        proposal_id: str,
        *,
        outcome: str,
        expected_input_fingerprint: str,
        expected_base_state_hash: str,
        decided_by: str,
        note: str,
        session_id: str,
    ) -> dict[str, Any]:
        rid = _validate_safe_id(run_id, "run_id")
        pid = _require_text(proposal_id, "proposal_id")
        decider = _require_text(decided_by, "decided_by")
        expected_input = _require_text(
            expected_input_fingerprint, "input_fingerprint"
        )
        expected_base = _require_text(expected_base_state_hash, "base_state_hash")
        if outcome not in {"approved", "rejected"}:
            raise ValueError(f"unsupported decision outcome: {outcome}")
        now = _utc_now()
        decision_id = self._new_id("decision")

        with self._write_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                run = self._get_run_row(conn, rid)
                proposal = conn.execute(
                    "SELECT * FROM proposals WHERE proposal_id=? AND run_id=?",
                    (pid, rid),
                ).fetchone()
                if proposal is None:
                    raise RunLedgerError(
                        f"proposal {pid!r} does not belong to run {rid!r}"
                    )
                if str(proposal["status"]) != "pending":
                    raise ProposalStateError(
                        f"proposal {pid} is already {proposal['status']}"
                    )
                self._validate_proposal_integrity(proposal)
                self._validate_bound_state(
                    run,
                    proposal,
                    expected_input,
                    expected_base,
                )
                event = self._insert_event(
                    conn,
                    rid,
                    f"decision.{outcome}",
                    payload={
                        "decision_id": decision_id,
                        "proposal_id": pid,
                        "proposal_hash": str(proposal["proposal_hash"]),
                        "outcome": outcome,
                        "note": str(note),
                    },
                    actor=_actor(decider, "human_reviewer", decider),
                    session_id=str(session_id).strip(),
                    subject={"kind": "proposal", "id": pid},
                    correlation_id=pid,
                    causation_id=str(proposal["proposed_event_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO decisions (
                        decision_id, run_id, proposal_id, outcome, decided_by,
                        decided_at, note, proposal_hash, input_fingerprint,
                        base_state_hash, event_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        rid,
                        pid,
                        outcome,
                        decider,
                        now,
                        str(note),
                        str(proposal["proposal_hash"]),
                        str(run["input_fingerprint"]),
                        str(run["base_state_hash"]),
                        event["event_id"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE proposals
                    SET status=?, decided_at=?, decision_id=?
                    WHERE proposal_id=?
                    """,
                    (outcome, now, decision_id, pid),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            self._refresh_run_capsule(rid)
        return self._get_decision(decision_id)

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        event_type: str,
        *,
        payload: Mapping[str, Any] | None = None,
        stage: str = "",
        actor: Mapping[str, Any] | None = None,
        session_id: str = "",
        subject: Mapping[str, Any] | None = None,
        evidence_refs: Sequence[str] | None = None,
        correlation_id: str = "",
        causation_id: str = "",
    ) -> dict[str, Any]:
        run = self._get_run_row(conn, run_id)
        sequence = int(run["last_event_sequence"]) + 1
        previous_hash = str(run["last_event_hash"] or "")
        occurred_at = _utc_now()
        event_id = self._new_id("event")
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "sequence": sequence,
            "project_id": self.project_id,
            "run_id": run_id,
            "session_id": str(session_id),
            "occurred_at": occurred_at,
            "event_type": self._validate_event_type(event_type),
            "stage": str(stage),
            "actor": dict(actor or _actor(None, "pipeline_engine", "pipeline")),
            "subject": dict(subject or {}),
            "correlation_id": str(correlation_id),
            "causation_id": str(causation_id),
            "input_fingerprint": str(run["input_fingerprint"]),
            "base_state_hash": str(run["base_state_hash"]),
            "evidence_refs": list(evidence_refs or []),
            "payload": dict(payload or {}),
            "previous_hash": previous_hash,
        }
        event_hash = _sha256_text(_canonical_json(event))
        event["event_hash"] = event_hash
        conn.execute(
            """
            INSERT INTO events (
                event_id, run_id, sequence, schema_version, project_id,
                session_id, occurred_at, event_type, stage, actor_json,
                subject_json, correlation_id, causation_id,
                input_fingerprint, base_state_hash, evidence_refs_json,
                payload_json, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                sequence,
                SCHEMA_VERSION,
                self.project_id,
                str(session_id),
                occurred_at,
                event["event_type"],
                str(stage),
                _canonical_json(event["actor"]),
                _canonical_json(event["subject"]),
                str(correlation_id),
                str(causation_id),
                str(run["input_fingerprint"]),
                str(run["base_state_hash"]),
                _canonical_json(event["evidence_refs"]),
                _canonical_json(event["payload"]),
                previous_hash,
                event_hash,
            ),
        )
        conn.execute(
            """
            UPDATE runs SET last_event_sequence=?, last_event_hash=?
            WHERE run_id=?
            """,
            (sequence, event_hash, run_id),
        )
        return event

    # ------------------------------------------------------------------
    # SQLite and serialization helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self.timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        return conn

    def _initialize_database(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    input_fingerprint TEXT NOT NULL,
                    base_state_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    last_event_sequence INTEGER NOT NULL DEFAULT 0,
                    last_event_hash TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    sequence INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    project_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    actor_json TEXT NOT NULL,
                    subject_json TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    base_state_hash TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_type
                    ON events(run_id, event_type, sequence);

                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    created_at TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    base_state_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    proposal_hash TEXT NOT NULL,
                    proposed_event_id TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    decision_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proposals_run_status
                    ON proposals(run_id, status, created_at);

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(proposal_id),
                    outcome TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    note TEXT NOT NULL,
                    proposal_hash TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    base_state_hash TEXT NOT NULL,
                    event_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    external INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_run
                    ON artifacts(run_id, created_at);

                CREATE TABLE IF NOT EXISTS ownership_locks (
                    project_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                    last_run_id TEXT NOT NULL REFERENCES runs(run_id),
                    claimed_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    claimed_by TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    claim_event_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, item_id)
                );
                """
            )
        finally:
            conn.close()

    def _get_run_row(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFoundError(f"unknown run_id: {run_id}")
        return row

    def _get_decision(self, decision_id: str) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if row is None:
                raise RunLedgerError(f"unknown decision_id: {decision_id}")
            return self._decision_from_row(row)
        finally:
            conn.close()

    @staticmethod
    def _validate_event_type(event_type: object) -> str:
        text = _require_text(event_type, "event_type")
        if not _EVENT_TYPE.fullmatch(text):
            raise ValueError(f"invalid event_type: {text!r}")
        return text

    @staticmethod
    def _validate_optional_expected(
        supplied: str | None,
        current: str,
        field: str,
    ) -> None:
        if supplied is not None and str(supplied) != current:
            raise StaleStateError(
                f"{field} is stale: proposal supplied {supplied!r}, current {current!r}"
            )

    @staticmethod
    def _validate_bound_state(
        run: sqlite3.Row,
        proposal: sqlite3.Row,
        expected_input: str,
        expected_base: str,
    ) -> None:
        current_input = str(run["input_fingerprint"])
        current_base = str(run["base_state_hash"])
        proposal_input = str(proposal["input_fingerprint"])
        proposal_base = str(proposal["base_state_hash"])
        if expected_input != current_input or proposal_input != current_input:
            raise StaleStateError(
                "input_fingerprint changed since proposal creation "
                f"(proposal={proposal_input!r}, expected={expected_input!r}, "
                f"current={current_input!r})"
            )
        if expected_base != current_base or proposal_base != current_base:
            raise StaleStateError(
                "base_state_hash changed since proposal creation "
                f"(proposal={proposal_base!r}, expected={expected_base!r}, "
                f"current={current_base!r})"
            )

    @staticmethod
    def _validate_proposal_integrity(proposal: sqlite3.Row) -> None:
        hash_payload = {
            "proposal_id": str(proposal["proposal_id"]),
            "run_id": str(proposal["run_id"]),
            "created_at": str(proposal["created_at"]),
            "agent_id": str(proposal["agent_id"]),
            "action": str(proposal["action"]),
            "input_fingerprint": str(proposal["input_fingerprint"]),
            "base_state_hash": str(proposal["base_state_hash"]),
            "payload": _json_load(proposal["payload_json"], {}),
            "evidence_refs": _json_load(proposal["evidence_refs_json"], []),
        }
        computed = _sha256_text(_canonical_json(hash_payload))
        stored = str(proposal["proposal_hash"])
        if computed != stored:
            raise LedgerIntegrityError(
                f"proposal {proposal['proposal_id']} failed integrity validation"
            )

    @staticmethod
    def _validate_approved_decision(
        conn: sqlite3.Connection,
        run_id: str,
        decision_id: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT d.*, r.input_fingerprint AS run_input_fingerprint,
                   r.base_state_hash AS run_base_state_hash
            FROM decisions d JOIN runs r ON r.run_id=d.run_id
            WHERE d.decision_id=? AND d.run_id=?
            """,
            (decision_id, run_id),
        ).fetchone()
        if row is None or str(row["outcome"]) != "approved":
            raise RunLedgerError(
                f"decision {decision_id!r} is not an approved decision for run {run_id!r}"
            )
        if (
            str(row["input_fingerprint"]) != str(row["run_input_fingerprint"])
            or str(row["base_state_hash"]) != str(row["run_base_state_hash"])
        ):
            raise StaleStateError(
                f"approved decision {decision_id!r} no longer matches the run state"
            )

    @staticmethod
    def _new_id(prefix: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:10]}"

    def _artifact_uri(self, path: Path) -> tuple[str, bool]:
        try:
            return path.relative_to(self.project_dir).as_posix(), False
        except ValueError:
            return str(path), True

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": str(row["run_id"]),
            "project_id": str(row["project_id"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "started_at": str(row["started_at"]),
            "finished_at": str(row["finished_at"]),
            "input_fingerprint": str(row["input_fingerprint"]),
            "base_state_hash": str(row["base_state_hash"]),
            "config": _json_load(row["config_json"], {}),
            "metadata": _json_load(row["metadata_json"], {}),
            "finish_summary": _json_load(row["summary_json"], {}),
            "last_event_sequence": int(row["last_event_sequence"]),
            "last_event_hash": str(row["last_event_hash"]),
        }

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": int(row["schema_version"]),
            "event_id": str(row["event_id"]),
            "sequence": int(row["sequence"]),
            "project_id": str(row["project_id"]),
            "run_id": str(row["run_id"]),
            "session_id": str(row["session_id"]),
            "occurred_at": str(row["occurred_at"]),
            "event_type": str(row["event_type"]),
            "stage": str(row["stage"]),
            "actor": _json_load(row["actor_json"], {}),
            "subject": _json_load(row["subject_json"], {}),
            "correlation_id": str(row["correlation_id"]),
            "causation_id": str(row["causation_id"]),
            "input_fingerprint": str(row["input_fingerprint"]),
            "base_state_hash": str(row["base_state_hash"]),
            "evidence_refs": _json_load(row["evidence_refs_json"], []),
            "payload": _json_load(row["payload_json"], {}),
            "previous_hash": str(row["previous_hash"]),
            "event_hash": str(row["event_hash"]),
        }

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> dict[str, Any]:
        current_input = (
            str(row["run_input_fingerprint"])
            if "run_input_fingerprint" in row.keys()
            else str(row["input_fingerprint"])
        )
        current_base = (
            str(row["run_base_state_hash"])
            if "run_base_state_hash" in row.keys()
            else str(row["base_state_hash"])
        )
        return {
            "proposal_id": str(row["proposal_id"]),
            "run_id": str(row["run_id"]),
            "created_at": str(row["created_at"]),
            "agent_id": str(row["agent_id"]),
            "action": str(row["action"]),
            "status": str(row["status"]),
            "input_fingerprint": str(row["input_fingerprint"]),
            "base_state_hash": str(row["base_state_hash"]),
            "payload": _json_load(row["payload_json"], {}),
            "evidence_refs": _json_load(row["evidence_refs_json"], []),
            "proposal_hash": str(row["proposal_hash"]),
            "proposed_event_id": str(row["proposed_event_id"]),
            "decided_at": str(row["decided_at"]),
            "decision_id": str(row["decision_id"]),
            "stale": (
                str(row["input_fingerprint"]) != current_input
                or str(row["base_state_hash"]) != current_base
            ),
        }

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "decision_id": str(row["decision_id"]),
            "run_id": str(row["run_id"]),
            "proposal_id": str(row["proposal_id"]),
            "outcome": str(row["outcome"]),
            "decided_by": str(row["decided_by"]),
            "decided_at": str(row["decided_at"]),
            "note": str(row["note"]),
            "proposal_hash": str(row["proposal_hash"]),
            "input_fingerprint": str(row["input_fingerprint"]),
            "base_state_hash": str(row["base_state_hash"]),
            "event_id": str(row["event_id"]),
        }

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "artifact_id": str(row["artifact_id"]),
            "run_id": str(row["run_id"]),
            "kind": str(row["kind"]),
            "name": str(row["name"]),
            "uri": str(row["uri"]),
            "external": bool(int(row["external"])),
            "size_bytes": int(row["size_bytes"]),
            "sha256": str(row["sha256"]),
            "metadata": _json_load(row["metadata_json"], {}),
            "created_at": str(row["created_at"]),
            "event_id": str(row["event_id"]),
        }

    @staticmethod
    def _ownership_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "project_id": str(row["project_id"]),
            "item_id": str(row["item_id"]),
            "family_id": str(row["family_id"]),
            "input_fingerprint": str(row["input_fingerprint"]),
            "first_run_id": str(row["first_run_id"]),
            "last_run_id": str(row["last_run_id"]),
            "claimed_at": str(row["claimed_at"]),
            "last_seen_at": str(row["last_seen_at"]),
            "claimed_by": str(row["claimed_by"]),
            "decision_id": str(row["decision_id"]),
            "metadata": _json_load(row["metadata_json"], {}),
            "claim_event_id": str(row["claim_event_id"]),
        }

    @staticmethod
    def _build_summary(
        run: Mapping[str, Any],
        events: Sequence[Mapping[str, Any]],
        proposals: Sequence[Mapping[str, Any]],
        decisions: Sequence[Mapping[str, Any]],
        artifacts: Sequence[Mapping[str, Any]],
        ownership: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        proposal_counts = Counter(str(item.get("status", "")) for item in proposals)
        decision_counts = Counter(str(item.get("outcome", "")) for item in decisions)
        event_counts = Counter(str(item.get("event_type", "")) for item in events)
        latest_metrics: dict[str, Any] = {}
        current_stage = ""
        for event in events:
            event_type = str(event.get("event_type", ""))
            if event_type.startswith("stage.") and str(event.get("stage", "")):
                current_stage = str(event["stage"])
            if event_type == "metric.recorded":
                payload = event.get("payload", {})
                if isinstance(payload, Mapping) and payload.get("name"):
                    latest_metrics[str(payload["name"])] = {
                        "value": payload.get("value"),
                        "unit": payload.get("unit", ""),
                        "stage": event.get("stage", ""),
                    }
        return {
            "run_id": str(run.get("run_id", "")),
            "status": str(run.get("status", "")),
            "current_stage": current_stage,
            "event_count": len(events),
            "event_types": dict(sorted(event_counts.items())),
            "last_sequence": int(run.get("last_event_sequence", 0)),
            "hash_chain_head": str(run.get("last_event_hash", "")),
            "proposal_count": len(proposals),
            "proposals_by_status": dict(sorted(proposal_counts.items())),
            "decision_count": len(decisions),
            "decisions_by_outcome": dict(sorted(decision_counts.items())),
            "artifact_count": len(artifacts),
            "ownership_count": len(ownership),
            "latest_metrics": latest_metrics,
        }

    # ------------------------------------------------------------------
    # Capsule mirrors
    # ------------------------------------------------------------------

    def _capsule_dir(self, run_id: str) -> Path:
        rid = _validate_safe_id(run_id, "run_id")
        path = self.runs_dir / rid
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _refresh_run_capsule(self, run_id: str) -> None:
        snap = self.snapshot(run_id)
        capsule_dir = self._capsule_dir(run_id)
        run = snap["run"]
        manifest = {
            "capsule_version": CAPSULE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "run_id": run_id,
            "created_at": run["created_at"],
            "input_fingerprint": run["input_fingerprint"],
            "base_state_hash": run["base_state_hash"],
            "last_event_sequence": run["last_event_sequence"],
            "last_event_hash": run["last_event_hash"],
            "config": run["config"],
            "metadata": run["metadata"],
            "files": {
                "summary": "summary.json",
                "events": "events.jsonl",
                "proposals": "proposals.json",
                "decisions": "decisions.json",
                "artifacts": "artifacts.json",
                "ownership": "ownership.json",
            },
        }
        # Write the manifest last.  Consumers can treat it as the generation's
        # commit marker and compare its sequence/head hash with events.jsonl.
        self._atomic_write(capsule_dir / "summary.json", _pretty_json(snap["summary"]))
        self._atomic_write(
            capsule_dir / "events.jsonl",
            "".join(_canonical_json(event) + "\n" for event in snap["events"]),
        )
        self._atomic_write(
            capsule_dir / "proposals.json", _pretty_json(snap["proposals"])
        )
        self._atomic_write(
            capsule_dir / "decisions.json", _pretty_json(snap["decisions"])
        )
        self._atomic_write(
            capsule_dir / "artifacts.json", _pretty_json(snap["artifacts"])
        )
        self._atomic_write(
            capsule_dir / "ownership.json", _pretty_json(snap["ownership"])
        )
        self._atomic_write(capsule_dir / "manifest.json", _pretty_json(manifest))

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


__all__ = [
    "CAPSULE_VERSION",
    "SCHEMA_VERSION",
    "LedgerIntegrityError",
    "OwnershipConflictError",
    "ProposalStateError",
    "RunLedger",
    "RunLedgerError",
    "RunNotFoundError",
    "StaleStateError",
]
