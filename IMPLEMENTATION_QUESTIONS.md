# IMPLEMENTATION_SPEC.md 決議紀錄

> 本檔原為 v1.0 規格 lint 後的疑問清單；`IMPLEMENTATION_SPEC.md` v1.1 已逐項修正。保留此檔作為決策紀錄。

## 已決議事項

1. 測試框架  
   v1.1 改用 stdlib `unittest`，不新增 `pytest` 或其他第三方依賴。

2. 本輪範圍  
   v1.1 明確限定 Batch A 只做 Phase 1-3；GUI Trace Viewer 與 fuzzy/collision UI 移到後續 roadmap。

3. `PipelineExtractor.build_intermediate` 簽名  
   接受前輪已加入的 `iso_list_path` / `iso_sheet_name` / `pipe_col_override`，不回退。

4. `resolved_mapping.csv` 欄位順序  
   `OUTPUT_COLUMNS` 既有欄位順序不重排；若未來新增欄位只允許 append-only。

5. `Source` / `Trace` 欄位命名  
   不新增同義欄位，沿用既有 `MatchSource` / `IdentityReason` / `CandidateTrace`。

6. `normalize_line` 行為  
   v1 簽名與行為完全不動；新增獨立 `normalize_line_v2`，只在新比對流程顯式呼叫。

7. commit 格式  
   不重寫既有歷史；從 v1.1 後續 phase commit 起使用 `[Phase N] ...` 格式。

8. GUI Trace Viewer 驗證  
   Phase 4 之後會以程式化 PyQt smoke test 與實際模組匯入測試驗證；互動式操作可由使用者在本機補確認。

## 目前進度

- Phase 1 已完成：`core/size_normalizer.py` 與尺寸正規化測試。
- Phase 2 已完成：`utils/trace_builder.py` 與結構化 `IdentityReason` trace。
- Phase 3 已完成：`normalize_line_v2` 接入真實比對 key。

## 後續 Roadmap

1. Phase 4：GUI Trace Viewer，讓使用者在表格列上直接查看 `IdentityReason` 時間軸。
2. Phase 5：Collision 決策 UI，把 `NeedsDecision=1` 的流水號做成可選 A/B ParentArea 的人工決策流程。
