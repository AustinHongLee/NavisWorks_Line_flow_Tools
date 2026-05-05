# JSON Export UI Review Brief for Opus

## Purpose

This document is for a strict UI/UX and product-flow review of the current JSON export page.

The feature now works, but the interaction still feels abstract. The most confusing part is that users do not naturally think in terms of `group_key`, `filters`, and `resolved_mapping`. They think in questions like:

- "System AI / AP / P each carries how many 3D identities?"
- "Export all pipes under system P."
- "Export one JSON per system."
- "Use serial number groups only when multiple serials represent the same item."
- "Do not accidentally select the same pipe name from another model root or area."

The review goal is not to criticize backend matching. Focus on the JSON export experience and whether an operator can confidently understand what will be exported.

## Current State

Relevant files:

- `gui/tabs/tab_json.py`
- `core/json_exporter.py`
- `core/resolved_mapping.py`
- `gui/dialogs/collision_decision_dialog.py`

Current data contract:

- Preferred source is `resolved_mapping.csv`.
- It preserves ISO source columns such as `系統`, `保溫`, `材質`, `試壓媒介`, `發包分類`, and future ISO columns.
- It also includes mapping/debug columns such as `流水號`, `群組`, `Raw_3D_PipeCode`, `PipeNodePath`, `ScopeRoot`, `ParentArea`, `NeedsDecision`, `Resolved`, `ResolutionStatus`.
- JSON export emits existing fields and adds per-pipe `搜尋範圍` when available.

Current JSON shape:

```json
[
  {
    "系統": "AI",
    "管線號": ["/1-S11U-AI-00001"],
    "搜尋範圍": [
      {
        "管線號": "/1-S11U-AI-00001",
        "ScopeRoot": "CHO_NO_INSU.RVM",
        "ParentArea": "/HPS-PIPE",
        "PipeNodePath": "HP6.nwd___CHO_NO_INSU.RVM___/HPS___/HPS-PIPE___/1-S11U-AI-00001",
        "PipeNodeLevel": 4
      }
    ]
  }
]
```

Current behavior:

- The page loads `resolved_mapping.csv` or falls back to `iso_match.xlsx`.
- Users can add up to 3 Excel-like filters.
- Users choose "分組依據" from available columns.
- If grouping by `系統`, the preview now shows summary rows like `系統`, `3D身分證數`, `流水號數`, `Scope數`, `Root數`, `ParentArea數`, `範例管線號`.
- If grouping by `流水號` or `群組`, the same grouping machinery is used.
- Safety filter blocks unresolved rows and unresolved collision rows unless scope narrowing makes them safe.

Known CP-129 example after grouping by `系統`:

| 系統 | 3D身分證數 | 流水號數 |
|---|---:|---:|
| AI | 32 | 11 |
| AP | 23 | 10 |
| FF | 7 | 4 |
| N4 | 30 | 24 |
| P | 295 | 173 |
| WCR | 14 | 8 |
| WCS | 10 | 5 |
| WD | 7 | 3 |
| WHP | 24 | 12 |
| WI | 19 | 11 |
| S5 | 35 | 18 |
| SC0 | 4 | 2 |

## Main UX Problem

The UI exposes implementation vocabulary instead of operator intent.

`分組依據 = 系統` technically answers "each system carries how many 3D identities", but the user has to infer that:

1. `分組依據` means JSON grouping, not just preview grouping.
2. `母篩選` means selecting which rows enter the export.
3. `群組` is not a special export mode; it is just an ISO/mapping column.
4. `流水號` and `群組` are only two possible grouping columns, not the whole mental model.
5. `搜尋範圍` is critical for Navisworks safety, but it is visually hidden behind a count.

This makes the page usable but not trustworthy. The operator can run it, but may not be sure whether they are exporting:

- one JSON containing many grouped selection sets,
- one JSON per selected system,
- a flat list of pipe IDs,
- serial-number groups,
- or only filtered rows.

## Review Scope for Opus

Please review the JSON export page as a professional data-operation tool, not a decorative app.

Prioritize:

1. Information architecture.
2. Label clarity.
3. Export intent clarity.
4. Safety visibility for `ScopeRoot`, `ParentArea`, `PipeNodePath`, `NeedsDecision`.
5. Preview trustworthiness.
6. Batch export ergonomics.
7. How to reduce cognitive load without hiding important diagnostics.

Do not focus on visual polish first. First make the model understandable.

## Proposed Mental Model

The UI should probably be redesigned around four explicit steps:

1. Source
   - Show loaded file: `resolved_mapping.csv`
   - Show row count, resolved count, blocked count, collision count
   - Show preserved ISO columns detected: `系統`, `保溫`, `材質`, etc.

2. Select Rows
   - Filters answer: "Which records are candidates?"
   - Examples: `系統 in AI, AP`, `保溫 = H75`, `ParentArea = /HPS-PIPE`
   - This should not be mixed conceptually with grouping.

3. Group Output
   - Grouping answers: "How should selected pipe IDs be packaged in JSON?"
   - Options should be explicit:
     - One group per `流水號`
     - One group per `群組`
     - One group per ISO column value, such as `系統`
     - One flat list
     - One file per selected value
   - `群組` should be labelled as "群組欄位" or "圖號合併欄位", not as an export feature.

4. Review and Export
   - Summary table should be primary:
     - Group value
     - Unique 3D identity count
     - Serial count
     - PipeNodePath coverage
     - Distinct ScopeRoot count
     - Distinct ParentArea count
     - Blocked rows
   - Detail rows should be drill-down, not the main first view.

## Specific UI Questions for Opus

Please answer these directly:

1. Should `分組依據` be renamed? Candidate labels:
   - `輸出分組`
   - `JSON 群組欄位`
   - `Selection Set 分組`
   - `包裝方式`

2. Should filters be renamed?
   - Current `母篩選 / 篩選 2 / 篩選 3` may be too abstract.
   - Better candidates may be `資料篩選`, `條件 2`, `條件 3`.

3. Should `群組` be pinned near `流水號`, or moved into a "serial packaging" section?

4. Should the page support two export actions?
   - `匯出單一 JSON`
   - `依分組值分檔匯出`

5. Should summary mode be the default whenever grouping is active?

6. How should the UI show that `搜尋範圍` is available and complete?
   - A count is not enough.
   - Maybe use coverage percentage: `PipeNodePath 100%`, `ScopeRoot 100%`, `ParentArea 100%`.

7. How should blocked rows be explained?
   - Current safety text is technically correct but not actionable.
   - It should probably list reasons: unresolved, needs collision decision, missing raw, missing scope.

8. Should JSON schema preview be visible?
   - Operators may trust the export more if they can see one expanded output object.
   - It should be read-only and small.

9. Should clicking a summary row drill down into detail?
   - For example click `P` and see the 295 pipe IDs, serials, roots, areas.

10. Should file naming be tied to selected filters/grouping?
    - Example: `系統_AI_AP_by_系統.json`
    - Avoid ambiguous `live_selection.json`.

## Current Technical Constraints

- UI framework: PyQt6.
- Existing code is a mixin in `gui/tabs/tab_json.py`.
- Avoid a huge architectural rewrite unless the current widget structure blocks clarity.
- `JsonExporter.build_case_result()` is already the shared preview/export planner.
- `JsonExportCaseResult.group_summaries` exists and should be reused.
- Export safety lives in `JsonExporter.filter_json_safe()`.
- Keep JSON schema backward-compatible: existing consumers expect `管線號`; new `搜尋範圍` is additive.

## Suggested Design Direction

Preferred layout:

```text
[ Source status band ]
resolved_mapping.csv | rows 2463 | resolved 1235 | blocked 1228 | scope coverage 100%

[ Select Rows ]
Column: 系統  Values: AI, AP, P
Column: 保溫  Values: H75
Column: ParentArea  Values: /HPS-PIPE

[ Group Output ]
Mode: grouped / flat / one-file-per-value
Group by: 系統

[ Summary Preview ]
系統 | 3D身分證數 | 流水號數 | PipeNodePath覆蓋率 | Root數 | ParentArea數 | blocked
AI  | 32          | 11       | 100%               | 1      | 2            | 0
AP  | 23          | 10       | 100%               | 1      | 9            | 0

[ Detail Drawer / Bottom Panel ]
Selected group AI:
Raw_3D_PipeCode | 流水號 | PipeNodePath | ScopeRoot | ParentArea | MatchType

[ Export Bar ]
filename | schema preview | export button
```

## Acceptance Criteria

The redesigned page should pass these operator scenarios:

1. User can load CP-129 and immediately answer:
   - AI carries 32 unique 3D identities.
   - P carries 295 unique 3D identities.

2. User can export all `系統 = P` pipes without touching `流水號` or `群組`.

3. User can export one JSON grouped by `系統`, containing 12 selection groups.

4. User can export one JSON per `系統` value, if this mode is implemented.

5. User can tell whether every exported pipe has a `PipeNodePath`.

6. User can tell why rows were blocked and how to fix them.

7. User can distinguish:
   - filtering rows,
   - grouping JSON,
   - splitting files,
   - and scope-safe selection.

8. User can inspect one output object before writing the file.

9. Existing tests still pass.

10. No change breaks the Navisworks importer contract.

## Requested Output From Opus

Please produce:

1. A prioritized UX findings list.
2. A revised layout proposal.
3. Exact label changes.
4. A minimal implementation plan.
5. Risks or backend contracts that should not be broken.
6. Suggested tests for the new UI behavior.

Be blunt. The current page is functional, but the user still feels it is abstract and hard to trust.
