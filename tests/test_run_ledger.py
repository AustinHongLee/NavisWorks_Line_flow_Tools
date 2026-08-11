# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest

from core.run_ledger import (
    OwnershipConflictError,
    RunLedger,
    StaleStateError,
)


class RunLedgerTests(unittest.TestCase):
    def test_normal_run_builds_complete_capsule(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="mapping-v1",
                config={"scan_mode": "full"},
                metadata={"project_name": "demo"},
            )
            ledger.stage_started(run_id, "step1", detail="scan")
            ledger.stage_progress(run_id, "step1", 50, current=5, total=10)
            ledger.record_metric(run_id, "rows_scanned", 10, unit="rows", stage="step1")
            ledger.stage_completed(run_id, "step1", summary={"rows": 10})

            artifact_path = os.path.join(tmp, "resolved_mapping.csv")
            with open(artifact_path, "wb") as handle:
                handle.write(b"id,value\n1,A\n")
            artifact = ledger.register_artifact(
                run_id,
                artifact_path,
                kind="resolved_mapping",
            )
            self.assertEqual(
                artifact["sha256"],
                hashlib.sha256(b"id,value\n1,A\n").hexdigest(),
            )
            cases_artifact = ledger.write_review_cases(
                run_id,
                [
                    {
                        "iso_line": "LINE-A",
                        "candidates": [
                            {
                                "line_3d": "LINE_A",
                                "evidence": {"classification": "punctuation_only"},
                            }
                        ],
                    }
                ],
            )
            self.assertEqual(cases_artifact["kind"], "review_cases")

            proposal = ledger.create_agent_proposal(
                run_id,
                action="assign_items_to_family",
                payload={"item_ids": ["item-1"], "family_id": "family-A"},
                agent_id="agent-test",
                evidence_refs=[artifact["artifact_id"]],
            )
            decision = ledger.approve_proposal(
                run_id,
                proposal["proposal_id"],
                input_fingerprint="input-v1",
                base_state_hash="mapping-v1",
                approved_by="operator",
                note="checked",
            )
            self.assertEqual(decision["outcome"], "approved")

            claim = ledger.claim_ownership(
                run_id,
                "item-1",
                "family-A",
                claimed_by="executor",
                decision_id=decision["decision_id"],
            )
            self.assertEqual(claim["status"], "claimed")
            ledger.finish_run(run_id, summary={"resolved": 1})

            snapshot = ledger.snapshot(run_id)
            self.assertEqual(snapshot["run"]["status"], "completed")
            self.assertEqual(snapshot["summary"]["latest_metrics"]["rows_scanned"]["value"], 10)
            self.assertEqual(len(snapshot["proposals"]), 1)
            self.assertEqual(len(snapshot["decisions"]), 1)
            self.assertEqual(len(snapshot["artifacts"]), 2)
            self.assertEqual(len(snapshot["ownership"]), 1)
            self.assertTrue(ledger.verify_hash_chain(run_id))

            capsule = os.path.join(tmp, ".flowdesk", "runs", run_id)
            for name in (
                "manifest.json",
                "summary.json",
                "events.jsonl",
                "proposals.json",
                "decisions.json",
                "artifacts.json",
                "ownership.json",
            ):
                self.assertTrue(os.path.isfile(os.path.join(capsule, name)), name)

            with open(os.path.join(capsule, "events.jsonl"), encoding="utf-8") as handle:
                exported_events = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(
                [event["sequence"] for event in exported_events],
                list(range(1, len(exported_events) + 1)),
            )

            context_path = ledger.export_agent_context(run_id, max_events=3)
            with open(context_path, encoding="utf-8") as handle:
                context = json.load(handle)
            self.assertTrue(context["read_only"])
            self.assertLessEqual(len(context["events"]), 3)
            self.assertIn("apply_decision", context["prohibited_capabilities"])
            self.assertEqual(context["review_case_count"], 1)
            self.assertEqual(context["review_cases"][0]["iso_line"], "LINE-A")

    def test_stale_proposal_cannot_be_approved_or_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="base-v1",
            )
            proposal = ledger.create_agent_proposal(
                run_id,
                action="manual_assign",
                payload={"item_id": "item-1"},
            )

            with self.assertRaises(StaleStateError):
                ledger.approve_proposal(
                    run_id,
                    proposal["proposal_id"],
                    input_fingerprint="wrong-input",
                    base_state_hash="base-v1",
                    approved_by="operator",
                )
            self.assertEqual(
                ledger.get_proposal(proposal["proposal_id"])["status"], "pending"
            )

            ledger.advance_base_state(
                run_id,
                expected_base_state_hash="base-v1",
                new_base_state_hash="base-v2",
            )
            self.assertTrue(ledger.get_proposal(proposal["proposal_id"])["stale"])
            with self.assertRaises(StaleStateError):
                ledger.reject_proposal(
                    run_id,
                    proposal["proposal_id"],
                    input_fingerprint="input-v1",
                    base_state_hash="base-v2",
                    rejected_by="operator",
                    reason="state changed",
                )

    def test_ownership_same_family_is_idempotent_and_other_family_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="base-v1",
            )
            first = ledger.claim_ownership(run_id, "item-1", "family-A")
            second = ledger.claim_ownership(run_id, "item-1", "family-A")
            self.assertEqual(first["status"], "claimed")
            self.assertEqual(second["status"], "idempotent")

            with self.assertRaises(OwnershipConflictError) as caught:
                ledger.claim_ownership(run_id, "item-1", "family-B")
            self.assertEqual(caught.exception.current_family_id, "family-A")
            self.assertEqual(caught.exception.requested_family_id, "family-B")
            self.assertEqual(ledger.get_ownership("item-1")["family_id"], "family-A")
            self.assertIn(
                "ownership.conflict",
                [event["event_type"] for event in ledger.list_events(run_id)],
            )
            self.assertTrue(ledger.verify_hash_chain(run_id))

    def test_release_ownership_is_exact_compensating_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="base-v1",
            )
            ledger.claim_ownership(run_id, "item-1", "family-A")

            with self.assertRaises(OwnershipConflictError):
                ledger.release_ownership(
                    run_id,
                    "item-1",
                    "family-B",
                    reason="wrong family must not unlock",
                )
            released = ledger.release_ownership(
                run_id,
                "item-1",
                "family-A",
                reason="rollback failed artifact apply",
            )

            self.assertEqual(released["status"], "released")
            self.assertEqual(ledger.get_ownership("item-1"), {})
            self.assertIn(
                "ownership.released",
                [event["event_type"] for event in ledger.list_events(run_id)],
            )
            self.assertTrue(ledger.verify_hash_chain(run_id))

    def test_hash_chain_detects_database_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="base-v1",
            )
            ledger.emit(run_id, "custom.observation", payload={"value": 1})
            ledger.record_metric(run_id, "rows", 5)
            self.assertTrue(ledger.verify_hash_chain(run_id))

            conn = sqlite3.connect(str(ledger.db_path))
            try:
                conn.execute(
                    "UPDATE events SET payload_json=? WHERE run_id=? AND sequence=2",
                    ('{"value":999}', run_id),
                )
                conn.commit()
            finally:
                conn.close()
            report = ledger.hash_chain_report(run_id)
            self.assertFalse(report["valid"])
            self.assertTrue(any("event_hash mismatch" in error for error in report["errors"]))

    def test_parallel_emit_uses_unique_contiguous_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(tmp)
            run_id = ledger.start_run(
                input_fingerprint="input-v1",
                base_state_hash="base-v1",
            )
            errors: list[Exception] = []

            def emit(index: int) -> None:
                try:
                    # Each thread may also construct its own facade, as a QThread can.
                    RunLedger(tmp).emit(
                        run_id,
                        "worker.observation",
                        payload={"index": index},
                    )
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [threading.Thread(target=emit, args=(index,)) for index in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            events = ledger.list_events(run_id)
            self.assertEqual(
                [event["sequence"] for event in events],
                list(range(1, len(events) + 1)),
            )
            self.assertTrue(ledger.verify_hash_chain(run_id))


if __name__ == "__main__":
    unittest.main()
