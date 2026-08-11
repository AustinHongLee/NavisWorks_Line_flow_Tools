# -*- coding: utf-8 -*-
"""背景線程：Step1 → Step3 全流程。"""
from __future__ import annotations

import os
import hashlib
import json
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from core.pipeline_extractor import PipelineExtractor
from core.pipeline_grouper import PipelineGrouper
from core.iso_matcher import IsoMatcher
from core.resolved_mapping import build_resolved_mapping
from core.run_ledger import RunLedger
from core.project_rules import ProjectRuleStore


class PipelineWorker(QThread):
    """在背景線程跑 Step1/2/3，不凍結 GUI。"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    event_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, params: dict):
        super().__init__()
        self.p = params
        self.fuzzy_unmatched: list[dict] = []
        self.run_id = ""
        self.input_fingerprint = ""
        self.ledger: RunLedger | None = None
        self.approved_punctuation_aliases: dict[str, str] = {}

    def _path(self, name: str) -> str:
        return os.path.join(self.p["base_dir"], name)

    @staticmethod
    def _hash_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _input_fingerprint(self) -> str:
        digest = hashlib.sha256()
        paths = [
            self._path(self.p["first_name"]),
            str(self.p.get("iso_list_path") or ""),
            ProjectRuleStore(self.p["base_dir"]).path,
        ]
        for path in paths:
            absolute = os.path.abspath(path) if path else ""
            digest.update(absolute.encode("utf-8"))
            digest.update(b"\0")
            if absolute and os.path.isfile(absolute):
                digest.update(self._hash_file(absolute).encode("ascii"))
            else:
                digest.update(b"missing")
            digest.update(b"\0")
        config = {
            key: value
            for key, value in self.p.items()
            if key not in {"base_dir"} and isinstance(value, (str, int, float, bool, list, dict, type(None)))
        }
        digest.update(
            json.dumps(
                config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return "sha256:" + digest.hexdigest()

    def _base_state_hash(self) -> str:
        mapping_path = self._path("resolved_mapping.csv")
        if os.path.isfile(mapping_path):
            return "sha256:" + self._hash_file(mapping_path)
        return "sha256:" + hashlib.sha256(b"").hexdigest()

    def _publish(self, event: dict) -> dict:
        self.event_signal.emit(dict(event))
        return event

    def _stage_started(self, stage: str, detail: str) -> None:
        if self.ledger and self.run_id:
            self._publish(
                self.ledger.stage_started(self.run_id, stage, detail=detail)
            )

    def _stage_completed(self, stage: str, summary: dict) -> None:
        if self.ledger and self.run_id:
            self._publish(
                self.ledger.stage_completed(self.run_id, stage, summary=summary)
            )

    def _metric(self, name: str, value: object, unit: str, stage: str) -> None:
        if self.ledger and self.run_id:
            self._publish(
                self.ledger.record_metric(
                    self.run_id,
                    name,
                    value,
                    unit=unit,
                    stage=stage,
                )
            )

    def _artifact(self, path: str, kind: str, name: str, **metadata) -> None:
        if self.ledger and self.run_id and os.path.isfile(path):
            artifact = self.ledger.register_artifact(
                self.run_id,
                path,
                kind=kind,
                name=name,
                metadata=metadata,
            )
            event_id = str(artifact.get("event_id", ""))
            if event_id:
                events = self.ledger.list_events(self.run_id)
                for event in reversed(events):
                    if event.get("event_id") == event_id:
                        self._publish(event)
                        break

    def run(self):
        try:
            self.progress_signal.emit(1, "Preflight：建立 Run Capsule 與輸入指紋...")
            self.ledger = RunLedger(self.p["base_dir"])
            rule_store = ProjectRuleStore(self.p["base_dir"])
            self.approved_punctuation_aliases = (
                rule_store.approved_punctuation_aliases()
            )
            self.p["project_rule_count"] = len(
                {
                    tuple(sorted((source, target)))
                    for source, target in self.approved_punctuation_aliases.items()
                    if source != target
                }
            )
            self.input_fingerprint = self._input_fingerprint()
            self.run_id = self.ledger.start_run(
                input_fingerprint=self.input_fingerprint,
                base_state_hash=self._base_state_hash(),
                config={
                    key: value
                    for key, value in self.p.items()
                    if isinstance(value, (str, int, float, bool, list, dict, type(None)))
                },
                metadata={"application": "pipeline-workbench", "capsule_version": 1},
            )
            self._publish(self.ledger.list_events(self.run_id)[-1])
            self.log_signal.emit(
                f"═══ Run Capsule：{self.run_id}（結構化稽核已啟用）═══"
            )

            # ── Step 1 ──
            self.progress_signal.emit(5, "Step1：管線抽取中...")
            self.log_signal.emit("═══ Step1：管線抽取 First_try → 123_minus_1 ═══")
            self._stage_started("extract", "掃描 First_try 並建立 3D 身分證據")
            step1 = PipelineExtractor(
                sep=self.p["sep"],
                raw_prefix=self.p["raw_prefix"],
            )
            scan_mode = self.p.get("scan_mode", "full")
            n1 = step1.build_intermediate(
                self._path(self.p["first_name"]),
                self._path("123_minus_1.csv"),
                filter_key=self.p["filter_key"],
                id_level=self.p["id_level"],
                scan_mode=scan_mode,
                iso_list_path=self.p.get("iso_list_path") or None,
                iso_sheet_name=self.p.get("iso_sheet") or None,
                pipe_col_override=self.p.get("pipe_col") or None,
                write_first_try_trace=bool(self.p.get("write_first_try_trace")),
                write_candidates=bool(self.p.get("write_candidates")),
                log_fn=lambda msg: self.log_signal.emit(f"  {msg}"),
            )
            self.log_signal.emit(f"  ✓ Step1 完成，輸出 {n1} 筆")
            self._metric("extract.matched_items", n1, "3D ITEM rows", "extract")
            self._artifact(
                self._path("123_minus_1.csv"),
                "pipeline_intermediate",
                "123_minus_1.csv",
                rows=n1,
            )
            if self.p.get("write_first_try_trace"):
                self.log_signal.emit(
                    f"  ✓ 已輸出 first_try_trace.csv：{self._path('first_try_trace.csv')}"
                )
            if self.p.get("write_candidates"):
                self.log_signal.emit(
                    "  ✓ 已輸出 candidates.csv（含 ISO 反向召回候選）："
                    f"{self._path('candidates.csv')}"
                )
                self._artifact(
                    self._path("candidates.csv"),
                    "match_evidence",
                    "candidates.csv",
                )
            if self.p.get("write_first_try_trace"):
                self._artifact(
                    self._path("first_try_trace.csv"),
                    "trace",
                    "first_try_trace.csv",
                )
            self._stage_completed("extract", {"matched_item_rows": n1})
            self.progress_signal.emit(33, "Step1 完成")

            # ── Step 2 ──
            self.progress_signal.emit(35, "Step2：群組整理中...")
            self.log_signal.emit("═══ Step2：群組整理 → 123_minus_2 ═══")
            self._stage_started("group", "整理 3D 明細與家族顯示群組")
            step2 = PipelineGrouper(
                sep=self.p["sep"],
                raw_prefix=self.p["raw_prefix"],
            )
            n2d, n2g = step2.parse_and_export(
                self._path("123_minus_1.csv"),
                self._path("123_minus_2.csv"),
                self._path("123_minus_2.xlsx"),
            )
            self.log_signal.emit(f"  ✓ Step2 完成，明細 {n2d} 筆，群組 {n2g} 筆")
            self._metric("group.detail_rows", n2d, "3D ITEM rows", "group")
            self._metric("group.family_rows", n2g, "3D display families", "group")
            self._artifact(
                self._path("123_minus_2.csv"),
                "pipeline_grouped",
                "123_minus_2.csv",
                detail_rows=n2d,
                family_rows=n2g,
            )
            self._artifact(
                self._path("123_minus_2.xlsx"),
                "pipeline_grouped_workbook",
                "123_minus_2.xlsx",
                detail_rows=n2d,
                family_rows=n2g,
            )
            self._stage_completed("group", {"detail_rows": n2d, "family_rows": n2g})
            self.progress_signal.emit(66, "Step2 完成")

            # ── Step 3 ──
            self.progress_signal.emit(68, "Step3：ISO 比對中...")
            self.log_signal.emit("═══ Step3：ISO 比對 → iso_match.xlsx ═══")
            self._stage_started("match", "執行嚴謹比對、候選召回與證據分流")
            matcher = IsoMatcher()
            n3 = matcher.run(
                base_dir=self.p["base_dir"],
                minus_csv_path=self._path("123_minus_2.csv"),
                iso_output_path=self._path("iso_match.xlsx"),
                iso_list_path=self.p["iso_list_path"] or None,
                log_fn=lambda msg: self.log_signal.emit(f"  {msg}"),
                iso_sheet_name=self.p["iso_sheet"] or None,
                pipe_col_override=self.p["pipe_col"] or None,
                spool_col_override=self.p["spool_col"] or None,
                extra_iso_headers=self.p.get("extra_headers", []),
                limit_iso_cols=self.p.get("limit_iso_cols", False),
                first_try_path=self._path(self.p["first_name"]),
                dataset_revision=self.input_fingerprint,
                approved_punctuation_aliases=self.approved_punctuation_aliases,
            )
            self.fuzzy_unmatched = matcher.fuzzy_unmatched
            fuzzy_count = len(self.fuzzy_unmatched)
            self.log_signal.emit(f"  ✓ Step3 完成，iso_match {n3} 筆")
            self._metric("match.output_rows", n3, "mapping rows", "match")
            self._metric("match.unmatched_iso", fuzzy_count, "ISO rows", "match")
            self._artifact(
                self._path("iso_match.xlsx"),
                "match_workbook",
                "iso_match.xlsx",
                rows=n3,
                review_cases=fuzzy_count,
            )
            cases_artifact = self.ledger.write_review_cases(
                self.run_id,
                self.fuzzy_unmatched,
                actor="pipeline",
            )
            cases_event_id = str(cases_artifact.get("event_id", ""))
            if cases_event_id:
                for event in reversed(self.ledger.list_events(self.run_id)):
                    if event.get("event_id") == cases_event_id:
                        self._publish(event)
                        break
            if fuzzy_count > 0:
                self.log_signal.emit(
                    f"  ⚠ 尚有 {fuzzy_count} 條 ISO 行未配對，將進入模糊比對…"
                )
                self._publish(
                    self.ledger.emit(
                        self.run_id,
                        "review.requested",
                        stage="review",
                        payload={
                            "message": f"{fuzzy_count} 條 ISO 行需要配對工作檯",
                            "case_count": fuzzy_count,
                            "unit": "ISO rows",
                        },
                    )
                )
            self._stage_completed(
                "match", {"output_rows": n3, "review_cases": fuzzy_count}
            )

            # ── Step 3b ──
            self.progress_signal.emit(92, "Step3b：建立 resolved mapping...")
            self.log_signal.emit("═══ Step3b：建立 JSON-safe resolved_mapping.csv ═══")
            self._stage_started("mapping", "驗證 collision 與 3D ITEM 單一歸屬")
            stats = build_resolved_mapping(
                iso_match_path=self._path("iso_match.xlsx"),
                output_path=self._path("resolved_mapping.csv"),
                log_fn=lambda msg: self.log_signal.emit(f"  {msg}"),
                dataset_revision=self.input_fingerprint,
                iso_source_path=self.p.get("iso_list_path") or None,
                iso_source_sheet=self.p.get("iso_sheet") or None,
                iso_source_spool_col=self.p.get("spool_col") or None,
            )
            self.log_signal.emit(
                "  ✓ resolved_mapping 完成，"
                f"可匯出 {stats['resolved']} 筆；"
                f"需人工決定 {stats['needs_decision']} 筆"
            )
            self._metric(
                "mapping.resolved_rows", stats["resolved"], "mapping rows", "mapping"
            )
            self._metric(
                "mapping.review_rows",
                stats["needs_decision"],
                "mapping rows",
                "mapping",
            )
            self._metric(
                "mapping.ownership_conflicts",
                stats.get("ownership_conflicts", 0),
                "mapping rows",
                "mapping",
            )
            self._artifact(
                self._path("resolved_mapping.csv"),
                "resolved_mapping",
                "resolved_mapping.csv",
                **{
                    key: value
                    for key, value in stats.items()
                    if key not in {"path", "identity_index_path"}
                },
            )
            mapping_state_hash = "sha256:" + self._hash_file(
                self._path("resolved_mapping.csv")
            )
            current_base_hash = str(
                self.ledger.get_run(self.run_id)["base_state_hash"]
            )
            if mapping_state_hash != current_base_hash:
                self._publish(
                    self.ledger.advance_base_state(
                        self.run_id,
                        expected_base_state_hash=current_base_hash,
                        new_base_state_hash=mapping_state_hash,
                        reason="pipeline resolved_mapping output",
                    )
                )
            self._stage_completed("mapping", dict(stats))
            self.progress_signal.emit(100, "全部完成！")

            summary = (
                f"全部完成！ Step1={n1} → "
                f"Step2=明細{n2d}/群組{n2g} → "
                f"iso_match={n3} → resolved={stats['resolved']}"
            )
            finish_event = self.ledger.finish_run(
                self.run_id,
                success=True,
                summary={
                    "step1_item_rows": n1,
                    "step2_detail_rows": n2d,
                    "step2_family_rows": n2g,
                    "iso_match_rows": n3,
                    "review_cases": fuzzy_count,
                    "resolved_rows": stats["resolved"],
                    "needs_decision_rows": stats["needs_decision"],
                    "ownership_conflicts": stats.get("ownership_conflicts", 0),
                },
            )
            self._publish(finish_event)
            agent_context_path = self.ledger.export_agent_context(self.run_id)
            self.log_signal.emit(
                f"  ✓ Agent 可讀 context：{agent_context_path}（唯讀／只可提案）"
            )
            self.finished_signal.emit(True, summary)

        except Exception as e:
            self.log_signal.emit(f"  ✗ 錯誤：{e}")
            self.log_signal.emit(traceback.format_exc())
            if self.ledger and self.run_id:
                try:
                    finish_event = self.ledger.finish_run(
                        self.run_id,
                        success=False,
                        summary={"phase": "pipeline"},
                        error=str(e),
                    )
                    self._publish(finish_event)
                except Exception as ledger_exc:
                    self.log_signal.emit(f"  ⚠ Run Capsule 結案失敗：{ledger_exc}")
            self.finished_signal.emit(False, str(e))
