# JSON 匯出頁 UI/UX 審核回覆（Opus）

回應對象：`docs/reviews/JSON_EXPORT_UI_REVIEW_FOR_OPUS.md`
基準：`gui/tabs/tab_json.py`、`core/json_exporter.py`（已逐行讀過）
語氣：依要求直球。

> Codex 註記（2026-05-05）：此回覆產生於 `96b96d3 fix: keep json selection group field stable` 之前。
> 後續已修正 JSON grouped schema：分組欄位可選 `系統` / `流水號` / `群組` 等任一欄，但輸出 selection-set 名稱一律使用穩定鍵 `"群組"`，例如 `"群組": "AI"`。
> 因此本文中提到 `{group_key: ...}` 或 `"系統": "AI"` 作為輸出 key 的地方，請改讀為 `"群組": <分組值>`；其他 UI/UX 審查意見仍可沿用。

---

## TL;DR（一句話）

目前頁面把「**選資料**」、「**包裝成 JSON**」、「**輸出檔策略**」三件事擠在同一排控件，又用 `母篩選 / 分組依據 / 群組` 這種 backend 字眼當主語，所以操作者無法在不問工程師的前提下回答「這次匯出到底會產生什麼」。**問題不是好不好看，是模型不對**。要修的是資訊架構，不是樣式。

---

## 1. 優先排序的 UX 發現（高 → 低）

1. **語彙錯位（HIGH）**
   `母篩選 / 篩選 2 / 篩選 3 / 分組依據 / 群組 / 流水號` 全是實作字眼。操作者腦中只有三個動詞：**選**（哪些列）→ **包**（怎麼塞進 JSON）→ **存**（一個檔還是多個檔）。目前 UI 把「包」和「存」混在 `分組依據` 一個下拉選單裡，靠「— 不分組（平面清單）」這個 sentinel 偽裝成第三選項。

2. **`分組依據` 過載三種語意（HIGH）**
   它同時控制：(a) JSON entries 的鍵；(b) 預覽是顯示明細還是摘要；(c) 是否進入 `__FLAT__` 模式。對使用者來說，這是三件事，應該拆。

3. **「母篩選」這個詞誤導（HIGH）**
   後端 `apply_filters` 對所有條件做 AND，沒有主從關係。叫第一個「母」會讓人以為它優先或具有特殊性，實際上只是順序。

4. **安全攔截不可診斷（HIGH）**
   `已擋 X 列` 無細目。`filter_json_safe` 內部本來就分得出 `Resolved=0`、`needs_decision`、`narrowed_collision` 三類，UI 卻只回傳一個總數。操作者沒辦法知道「該去處理 collision 還是去重跑 ISO」。

5. **`搜尋範圍` 用次數隱藏（HIGH）**
   底部只顯示 `N 筆 scope`。真正要回答的是「每一根管子是不是都有 PipeNodePath / ScopeRoot / ParentArea」——這需要 **覆蓋率**，不是次數。沒有覆蓋率就沒有 Navisworks 的信任感。

6. **單一 `匯出 JSON` 按鈕（MED）**
   缺「每個分組值各自一個 JSON 檔」這個常見需求。後端 `export_json_v2(cases=[…])` 本來就支援多 case，是 UI 沒給入口。

7. **群組摘要無法 drill-down（MED）**
   點 `P` 會看到 295，但無法即時看是哪 295 條。操作者得切回明細模式再篩，違反「驗證一眼」原則。

8. **無 JSON schema 預覽（MED）**
   下載前看不到 `entries[0]` 的真實樣子。對首次使用 Navisworks 端的人是黑盒。

9. **檔名預設 `live_selection`（MED）**
   無稽核線索。已有 `_v2_update_filename` 會用篩選欄位拼接，但沒帶分組欄位，且沒帶值。多次匯出互相覆蓋風險高。

10. **黃色說明欄位置不對（LOW）**
    把「篩選 / 安全 / 分組 / 搜尋範圍」四件事塞在右側一整塊文字裡，等於一面牆。應該拆成各區段的 inline tooltip 或副標。

11. **PINNED 欄位順序混合 ISO 與 debug 欄（LOW）**
    `ParentArea / ScopeRoot / ResolutionStatus / Resolved / NeedsDecision` 直接和 `系統 / 保溫 / 材質` 並列在篩選下拉。操作者大多時候只想用 ISO 欄篩，debug 欄應該降到次群組或加分隔。

12. **`流水號` 欄位是「合併單位」還是「分組鍵」不明（LOW）**
    從 brief 第七條 use case 看，`流水號 / 群組` 的用途是「多個 serial 代表同一個東西時的合併」，但 UI 把它和 `系統` 平鋪在同一下拉，當作對等選擇。

---

## 2. 修訂後的版面方案

維持 PyQt6、維持 mixin 結構，**版面從上而下分四段**，每段都有明確的問句：

```text
┌──────────────────────────────────────────────────────────────────┐
│ 1. 來源 [Source band]                                             │
│   📄 resolved_mapping.csv  ·  2463 列  ·  ✅ 1235 可匯出           │
│   ⚠ 1228 攔截：未解析 612 / 待決策 580 / 缺 raw 36                  │
│   範圍覆蓋：PipeNodePath 100% · ScopeRoot 100% · ParentArea 98%   │
│   [自動載入] [選擇檔案…] [處理衝突]                                  │
├──────────────────────────────────────────────────────────────────┤
│ 2. 選列 [Select rows] — 哪些列要進入候選？                          │
│   條件 1 ▸ 系統  ▾   值: AI, AP                                   │
│   條件 2 ▸ 保溫  ▾   值: H75                                      │
│   條件 3 ▸ 不使用                                                  │
│   ➕ 新增條件                                          ✕ 全部清除   │
├──────────────────────────────────────────────────────────────────┤
│ 3. 包裝 [Package output] — 選好的列要怎麼變成 JSON？                 │
│   輸出模式：( ) 平面清單                                            │
│             (●) 依欄位分組（單一檔）                                 │
│             ( ) 依欄位分組（每組一個檔）                              │
│   分組欄位： [系統 ▾]   ← 僅在分組模式下啟用                          │
├──────────────────────────────────────────────────────────────────┤
│ 4. 預覽與匯出 [Review & export]                                    │
│   ┌ 分組摘要 ─┬ JSON 預覽 ─┬ 明細 ─┐                               │
│   │ 系統 │ 3D 身分證數 │ 流水號數 │ Path 覆蓋 │ Root │ Area │ 攔 │ │
│   │ AI  │ 32        │ 11      │ 100%     │ 1   │ 2   │ 0  │ │
│   │ P   │ 295       │ 173     │ 100%     │ 1   │ 5   │ 0  │ │
│   │ ...                                                          │
│   └─────────────────────────────────────────────────────────────┘ │
│   點擊一列展開：Raw_3D_PipeCode / 流水號 / PipeNodePath / Root / Area │
│                                                                    │
│   檔名：[ system-AI_AP__by-系統 ___________________________ ]      │
│   [ 匯出 ]                                                         │
└──────────────────────────────────────────────────────────────────┘
```

關鍵原則：

- **每段都有問句副標**。中文現場操作者一看就知道現在在回答什麼。
- **`輸出模式` 用 radio**，不能再用 dropdown 偽裝。Radio 是「互斥的小選擇」，dropdown 才是「從很多裡挑一個」，目前語意是前者。
- **`分組欄位` 只在分組模式下亮起**，否則 disabled。這就消除了「— 不分組（平面清單）」這種 sentinel 假裝。
- **預覽表格用 tab**，不再依 group_key 切換預覽身份。摘要、JSON 預覽、明細是三個獨立檢視，不是同一視窗的不同模式。
- **覆蓋率與攔截細目放在「來源 band」**，不是底部。原因：這是「我能不能信任這份資料」的問題，屬於 source 層的健康指標，不是匯出層。

---

## 3. 確切的字串變更（找誰換誰）

| 現有 | 改為 | 理由 |
|---|---|---|
| `母篩選` | `條件 1` | 全部 AND，無主從 |
| `篩選 2` / `篩選 3` | `條件 2` / `條件 3` | 一致 |
| `分組依據` | 拆成兩個控件：`輸出模式` + `分組欄位` | 概念解耦 |
| `— 不分組（平面清單）` (dropdown 內) | 移到 `輸出模式` radio：`平面清單` | 概念分離 |
| `live_selection` (預設檔名) | `flat__live` 或自動依 filters/group 拼字 | 可稽核 |
| `已擋 X 列` | `攔截 X：未解析 a / 待決策 b / 缺 raw c` | 可行動 |
| `N 筆 scope` (底部) | 移到頂部：`Path 覆蓋 N/M (P%)` 三欄 | 可信任 |
| `匯出 JSON`（單按鈕） | 跟 `輸出模式` 自動聯動：模式變則按鈕標籤跟著變（`匯出單一檔` / `匯出 N 個檔`） | 意圖明確 |
| `群組`（在 `分組依據` 下拉裡） | `群組（多流水號合併）` 或移到 `輸出模式` 的 hint | 釐清語意 |
| `分組依據 = 系統` 預覽標題：`分組摘要：依「系統」聚合` | 保留但加副標：`12 組 · 共 533 條 3D 身分證 · 0 攔截` | 一眼讀懂 |
| `資料預覽` | `明細預覽`（已有切換邏輯） | 與 tab 名一致 |
| `輸出規則`（黃色說明欄） | 拆解為各區段的 hint label，移除整塊 sidebar | 減低牆面 |

---

## 4. 最小可行實作計畫

按 dependency 順序，不一次重寫：

### Phase A — 純 UI 重排（不動 backend）
1. 在 `_build_page_json` 把「條件列 × 3」與「分組依據」抽成兩個 `QGroupBox`：`grp_select_rows`、`grp_package_output`。
2. `grp_package_output` 內：上方 `QButtonGroup` 三個 radio（`flat` / `grouped_single` / `grouped_split`），下方 `分組欄位` `QComboBox`，根據 radio 啟用/停用。
3. 將現有 `_v2_cbo_group_key` 改成 internal-only：radio + combo 的組合對應 `group_key` sentinel：
   - `flat` → `__FLAT__`
   - `grouped_single` / `grouped_split` → 取 `_v2_cbo_group_field.currentText()`
4. 重新命名 labels（見 §3）。
5. 刪除黃色 `help_browser`，改寫成各區段 `setToolTip` + 一行副標。

### Phase B — `JsonExportCaseResult` 加診斷欄位（小幅後端）
在 `core/json_exporter.py`：

```python
@dataclass
class JsonExportCaseResult:
    ...
    blocked_breakdown: dict = field(default_factory=dict)  # {"unresolved": n, "needs_decision": n, "missing_raw": n}
    scope_coverage: dict = field(default_factory=dict)     # {"PipeNodePath": (with, total), ...}
```

`filter_json_safe` 已經有 `resolved_mask` 與 `pending_mask`，直接把計數塞進 `build_case_result` 回傳即可。**不影響舊呼叫者**——dataclass 新欄位有 default。

### Phase C — Source band 改寫
`_v2_lbl_source` 拆成三條：檔名+列數 / 攔截細目 / 覆蓋率。覆蓋率資料源：Phase B 的 `scope_coverage`。

### Phase D — 預覽 tab 化
1. `QTabWidget` 三個 tab：`分組摘要` / `JSON 預覽` / `明細`。
2. `JSON 預覽` tab 內放唯讀 `QPlainTextEdit`，顯示 `json.dumps(result.entries[0], indent=2, ensure_ascii=False)`，並截斷到例如 80 行。
3. 摘要 tab 點擊一列 → 在下方加 `QSplitter` drawer，顯示該分組值的明細列。drawer 從 `result.export_df` 即時 filter，不再算一次。

### Phase E — `grouped_split` 模式
新增 `_v2_live_export` 分支：

```python
if mode == "grouped_split":
    cases = []
    for row in result.group_summaries:
        gv = row[group_key]
        cases.append({
            "name": f"{base}_{group_key}_{gv}",
            "group_key": group_key,
            "filters": {**filters, group_key: [gv]},
        })
    exporter.export_json_v2(iso_match_path=iso_path, cases=cases, out_dir=base_dir)
```

注意：因為加了 `{group_key: [gv]}` 這個 filter，`filter_json_safe` 中 `has_scope_filter` 的判斷不會被觸發（仍只看 ParentArea/ScopeRoot），所以安全攔截行為與單檔模式一致——這點要在測試裡釘住。

### Phase F — 檔名 derivation
`_v2_update_filename` 改成：

```python
def _v2_update_filename(self):
    parts = []
    for info in self._v2_filter_row_widgets:
        col = info["active_col"]
        if col and col in self._v2_live_filters:
            vals = self._v2_live_filters[col]
            short = "_".join(vals[:3]) if len(vals) <= 3 else f"{len(vals)}values"
            parts.append(f"{col}-{short}")
    mode = self._current_mode()
    gk = self._v2_cbo_group_field.currentText()
    if mode != "flat" and gk:
        parts.append(f"by-{gk}")
    if mode == "grouped_split":
        parts.append("split")
    self.v2_txt_filename.setText("__".join(parts) or "live_selection")
```

### 工時估算
| Phase | 工時 |
|---|---|
| A 排版/字串 | 0.5 天 |
| B dataclass + filter_json_safe 計數 | 0.5 天 |
| C source band | 0.25 天 |
| D 預覽 tab + drill-down | 1 天 |
| E split 模式 | 0.5 天 |
| F 檔名 + 收尾 + 對應測試 | 0.5 天 |
| **合計** | **約 3.25 天** |

---

## 5. 不能踩的後端契約 / 風險

1. **JSON schema 向後相容。**
   現有消費者（Navisworks importer）期待：
   - grouped：`[{group_key: "AI", "管線號": [...], "搜尋範圍": [...]?}]`
   - flat：`[{"管線號": ["pipe1"], "搜尋範圍": [...]?}, ...]`
   `搜尋範圍` 是 additive；新加的 UI 診斷欄位（`blocked_breakdown` / `scope_coverage`）**只放在 `JsonExportCaseResult` dataclass，不要洩漏到 entries**。

2. **`build_case_result` 是預覽與匯出共用 planner。**
   不要在 UI 計算另一份「攔截原因」、然後跟匯出時的真實攔截不一致。所有診斷必須來自同一條 pipeline。

3. **`grouped_split` 模式必須走同一條 `filter_json_safe`。**
   危險場景：操作者用 `ParentArea = /HPS-PIPE` 篩，narrowed_collision 救回幾列；如果在 split 時把 `ParentArea` filter 拆掉、改成 `系統 = P`，這幾列會被擋掉，匯出結果跟使用者預期不一致。Phase E 的實作把 `group_key` 當作「附加」filter（保留原有 `ParentArea`），不改動 `has_scope_filter` 判斷，這是必要的。

4. **`__FLAT__` / `__ALL__` 是 sentinel，永遠不要在 UI 顯示。**
   現在用 `output_mode_label` 隔開，保留這層。

5. **Collision decision 寫回後 reload。**
   `_v2_open_collision_decisions` 結束時呼叫 `_v2_load_source(mapping_path)`。新版面要保留同一入口，否則決策後預覽不會更新。

6. **PINNED 欄位順序。**
   使用者已經有肌肉記憶。Phase A 重排時保留現有 `_PINNED` list 順序，不要因為「合理」去重排。

7. **`資料來源` 可能是 xlsx 或 csv。**
   Collision 寫回只支援 csv（`_v2_open_collision_decisions` 已擋）。若新加「處理衝突」的提示位置，記得保留這個 guard。

8. **`分組欄位 = 群組` 可能空值。**
   `resolve_group_key` 已 fallback 到 `流水號`。`grouped_split` 模式遍歷 `group_summaries` 時不會包到空字串（`build_group_summaries` 已過濾），但要在測試裡覆蓋一次。

---

## 6. 建議測試（針對新 UI 行為）

依 brief 的 10 條 acceptance scenarios 各對應一條，再補幾條：

### UI / 互動（pytest-qt）
1. `test_source_band_breakdown`：載 CP-129 fixture，斷言來源 band 顯示 `2463 列 · ✅ 1235 · 攔截 1228（未解析 X / 待決策 Y / 缺 raw Z）`，且 `X+Y+Z == 1228`。
2. `test_coverage_chip`：同 fixture，斷言 `PipeNodePath` 覆蓋率欄位顯示 `100%` 並可從 `result.scope_coverage["PipeNodePath"]` 推回 `(n_with, n_total)`。
3. `test_summary_default_when_grouping`：選 `輸出模式 = 分組單一檔`、`分組欄位 = 系統`、無 filter →「分組摘要」tab 為預設、表格 12 列、`P=295`、`AI=32`。
4. `test_flat_mode_shows_detail`：切到「平面清單」→「明細」tab 為預設、caption = `明細預覽`。
5. `test_drill_down`：在分組摘要點 `P` 一列 → drawer 列出 295 個 distinct `Raw_3D_PipeCode`。
6. `test_grouped_split_export`：模式 = `每組一檔`、分組 = `系統` → 寫出 12 個檔，檔名形如 `system-by-系統__系統-P.json`，每檔僅包含一個 entry，且該 entry 的 `系統` 鍵等於檔名中的值。
7. `test_blocked_breakdown_sums`：對人工建構的 fixture（含 needs_decision 與 unresolved）斷言三類數字加總等於總攔截數。
8. `test_narrowed_collision_via_parentarea`：filter `ParentArea = /HPS-PIPE` 時 narrowed_collision 列入 export；移除此 filter 後同樣那批列被擋。確認 split 模式不破壞此行為。
9. `test_filename_auto_derive`：filter `系統 ∈ {AI, AP}` + 分組 `系統` → 檔名 `系統-AI_AP__by-系統`；改 split → 加 `__split` 尾巴。
10. `test_json_preview_renders_first_entry`：`JSON 預覽` tab 顯示 `entries[0]` 格式化字串；切換 filter 即時更新。

### 後端回歸（不靠 GUI）
11. `test_build_case_result_backward_compat`：相同 case dict（filter + group_key）在重構前後產出的 `entries` 完全相等（用既有 fixture 做 golden）。
12. `test_dataclass_new_fields_default`：未設定 `blocked_breakdown` / `scope_coverage` 時 dataclass 仍可建構（保護舊 caller）。
13. `test_export_json_v2_split_cases`：`cases=[{...}, {...}]` 多 case 一次寫入，斷言檔案內容與分別呼叫一致。

### 操作者場景（end-to-end）
14. brief §Acceptance 1–10 全部當 e2e 跑一次（QTest sequence）。

---

## 補充：兩個小提醒（非阻擋）

- **目前 `_get_pinned_head` 用 `分組依據` 的 currentText 來決定預覽欄位順序**。重構後若 `分組欄位` 在 flat 模式下 disabled，仍要回傳合理 head（例如 `流水號 + Raw_3D_PipeCode`），否則表格欄位會閃爍。
- **`set _v2_cat_cols` 在 `_v2_load_source` 一次計算後就不變**。若未來 `處理衝突` 寫回新增了某欄的 unique 值，會被 `_CAT_THRESHOLD = 50` 切掉。Phase B 順手在 reload 時重算，避免使用者抱怨「我加了幾筆，篩選下拉的選項沒更新」。

---

如果這份方向 ok，我可以接著把 Phase A 的 PR 草稿寫出來——只是換版面與字串，零 backend 風險，是最便宜的第一步。
