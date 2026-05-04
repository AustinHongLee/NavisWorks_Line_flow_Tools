# 管線流程工具 — 調查/排查 UI 指導書 v1.0

> 版本：2026-05-04 · 範圍：Phase A–D（診斷 UI、跨中間檔追蹤、人工指定、寫回）
> 對象：Codex / 任何具備 Python+PyQt6 經驗的 AI/人類開發者
> 撰寫者：在 Phase 1–5（size_normalizer / IdentityReason trace / normalize_line_v2 / Trace Viewer / Collision UI）已完成的基礎上，回應使用者實際排查痛點

---

## 0. 給 Codex 的執行守則（READ FIRST）

### 0.1 你的角色
你是這個專案的後端 + GUI 工程師。本指導書是**接續** `IMPLEMENTATION_SPEC.md`（Phase 1–6），目標是補上**排查/診斷 UI**——讓使用者能自己看見資料在管線中的去向，而不是讓程式「自動猜到底」。

### 0.2 不可違反的鐵則（v1.1 沿用 + 新增）

承襲 `IMPLEMENTATION_SPEC.md` v1.1 §F 的全部不可動清單，**並新增**：

- **不要重做 / 取代** Phase 1–5 已完成的：`size_normalizer` / `normalize_line_v2` / `IdentityReason` 結構化 trace / `TraceViewerDialog` / `CollisionDecisionDialog` / `resolved_mapping.csv`。
- **不要自動「猜」最終答案**。本輪 UI 的核心職責是**呈現可能性**，由使用者決策。任何「程式自動把 ISO X 配 3D Y」的行為都禁止。
- **不要破壞 `core/identity_resolver.py` 的 `collect_candidates` / `resolve` 公開 API**——它已經在收候選，本輪只是把候選**端出來給使用者看**。
- **不要新增** ISO_LIST 寫回路徑。本輪「人工指定」只寫回 `resolved_mapping.csv`，不動 ISO_LIST。
- **不要動** `OUTPUT_COLUMNS` 既有欄位順序；新增欄位一律 append 在尾端，且需在 commit message 列出。
- **不引入**新的第三方套件。測試一律用 stdlib `unittest`。

### 0.3 程式風格
- Python 3.12 / PyQt6
- UI 文字一律繁體中文；docstring 一律繁體中文
- type hints 必加
- 測試放 `tests/`，命名 `test_<module>.py`，`unittest.TestCase`
- 跑法：`python -m unittest discover -s tests -v`

### 0.4 提交順序
本輪 4 個 commit（Phase A、B、C、D 各一個），格式承襲 `IMPLEMENTATION_SPEC.md` §G：

```
[Phase A] <summary>

詳細：
- 改動 1
- 改動 2

測試：
- 新增 tests/test_xxx.py：N 個 case 全綠
- 既有 tests/test_pipeline_regression.py：M 個 case 全綠
```

每個 commit 之間必須 `python -m unittest discover -s tests -v` **全綠**。

### 0.5 遇到不確定時
追加問題到 `IMPLEMENTATION_QUESTIONS.md` 的「v2 調查 UI」區段，**不要 guess**。

---

## 1. 目前狀態同步摘要（這是 Codex 的事實基礎）

### 1.1 已完成的 Phase（不要重做）

| Phase | commit | 落地物 |
|---|---|---|
| Phase 1 | `6d50ef0` | `core/size_normalizer.py`（NPS 表、`normalize_size_token`、`is_size_like`） |
| Phase 2 | `2f7dfc7` | `utils/trace_builder.py`、`§` 結構化 trace 字串、寫進 `IdentityReason` |
| Phase 3 | `e8b5f18` | `normalize_line_v2`，接入 `iso_matcher` / `pipeline_extractor` / `identity_resolver` |
| Phase 4 | `b1bfd7e` | `gui/dialogs/trace_viewer_dialog.py` |
| Phase 5 | `e7e746f` | `gui/dialogs/collision_decision_dialog.py` + `core/collision_resolver.py` |
| 後續 | `e2dc36b` | size-leading fuzzy 候選召回（如 `3_4-S11G-N4-20951Q` 召回 `1-1/2-S11G-N4-20951`） |

### 1.2 既有資料模型（本輪會利用，不會改寫）

**`123_minus_1.csv` 欄位**（來自 `core/pipeline_extractor.py` Step1）：
```
Path, DisplayName, Class, Level,
Raw_3D_PipeCode, ISO_Match_Key,
MatchSource, ConfidencePrimary, IdentityReason,
CandidateCount, CandidateTrace,
PipeNodePath, ScopeRoot, ParentArea, PipeNodeLevel
```

**`resolved_mapping.csv` 欄位**（來自 `core/resolved_mapping.py:OUTPUT_COLUMNS`）：
```
Resolved, ResolutionStatus, ResolutionReason, ResolvedAt, ResolvedBy,
流水號, 管線編號, ISO_Match_Key, Raw_3D_PipeCode,
PipeNodePath, ScopeRoot, ParentArea, PipeNodeLevel,
MatchType, MatchScore, MatchSource, ConfidencePrimary,
IdentityReason,
CollisionCount, CollisionParents, NeedsDecision, 群組
```

**`IdentityReason` 已是結構化 trace**：可由 `utils.trace_builder.parse_trace()` 還原為 `(kind, key, value)` tuples。已被 `TraceViewerDialog` 渲染為時間軸卡片。

**`CandidateTrace` 欄位已存在於 `123_minus_1.csv`**（但**目前尚未被任何 UI 讀取**）。內容包含 `candidate_count`、最多 5 筆候選的 `candidate:idx|source|normalized|score|reason` 事件。

### 1.3 既有 UI 入口

| UI 元件 | 位置 | 觸發 |
|---|---|---|
| `TraceViewerDialog` | `gui/dialogs/trace_viewer_dialog.py` | 目前可被 `tab_json` / `fuzzy_match_dialog` 呼叫顯示單筆 trace |
| `CollisionDecisionDialog` | `gui/dialogs/collision_decision_dialog.py` | 從 `tab_pipeline` 跑完比對後呼叫 |
| `FuzzyMatchDialog` | `gui/dialogs/fuzzy_match_dialog.py` | Step3 跑完後對未配對 ISO 啟動 |
| `tab_json` | `gui/tabs/tab_json.py` | JSON 匯出主頁 |
| `tab_pipeline` | `gui/tabs/tab_pipeline.py` | 抽取/比對主流程設定 |

---

## 2. 為什麼現有 Trace Viewer 還不夠

`TraceViewerDialog` 解決了「**這條已選身份的決策過程**」的可視化，但使用者實際排查場景需要更多：

| 排查問題 | 現有 Trace Viewer 能回答？ | 缺的是什麼 |
|---|---|---|
| 為什麼 ISO `TRIM-6FL216Q-N3-001` 找不到？ | ❌ | ISO 端沒有對應的 trace；trace 只記錄被選身份的 3D 端歷程 |
| 3D 端在哪一層出現過 `TRIM-6FL216Q-N3`？ | ❌ | 沒有「以 ISO 字串反查 3D 家族」的入口 |
| Step1 從 PipelineId / DisplayName / Path 抽到的**全部候選**長什麼樣？ | 部分 | `CandidateTrace` 已寫入 csv 但沒 UI 讀；只看到最終選的那條 |
| 哪些 First_try row 被 `PIPE_SEG_PATTERN` / `_is_structural` / `_is_file_like` 過濾掉？ | ❌ | 被丟掉的列不會出現在 minus_1，trace 也找不到 |
| `TRIM-6FL216Q-N3`（3D 父節點）和 `TRIM-6FL216Q-N3-001`（ISO 子 spool）是「同家族不同層」還是「不同管線」？ | ❌ | 沒有家族關係的視覺化 |
| 從 First_try → minus_1 → minus_2 → iso_match → resolved_mapping → JSON 的整條資料流，**這條流水號在哪一站消失了**？ | ❌ | 沒有跨檔的單一查詢入口 |

**結論**：Trace Viewer 是「終點解釋器」；缺的是「**全程探勘器**」——能從任意一條 ISO 或任意一條 3D 字串出發，往兩端拉出所有相關脈絡。

---

## 3. 建議新增 / 改造的 UI

下列 4 個元件**逐 Phase 落地**（見 §8），不一次到位：

### 3.1 Identity Inspector（核心）
**檔案**：`gui/dialogs/identity_inspector_dialog.py`（新增）

**職責**：給定一個查詢字串（ISO 流水號 / 管線編號 / 3D Raw / 3D 段位），全方位顯示「相關所有資料」。**這是本輪最關鍵的 UI**。

**佈局**（單頁三欄式）：

```
┌─────────────────────────────────────────────────────────────────┐
│ 🔍 Identity Inspector                                            │
│ 查詢：[ TRIM-6FL216Q-N3-001                       ▼ ]  [搜尋]    │
│ 範圍：☑ ISO 流水號  ☑ 管線編號  ☑ 3D Raw  ☑ 3D 段位             │
└─────────────────────────────────────────────────────────────────┘
┌─ 左欄：ISO 端 ──────────┬─ 中欄：身份家族 ────┬─ 右欄：3D 端 ──┐
│                         │                      │                │
│ 流水號：6321            │ ISO normalized:       │ Level 4 (1)    │
│ 管線編號：              │   TRIM-6FL216Q-N3-001 │  /TRIM-6FL...  │
│   TRIM-6FL216Q-N3-001   │                      │                │
│ ISO_Match_Key:          │ 去末段 (drop_last):  │ Level 5 (2)    │
│   TRIM-6FL216Q-N3-001   │   TRIM-6FL216Q-N3 ←  │  /TRIM-.../B1  │
│                         │   ✓ 在 3D 端找到     │  /TRIM-.../B2  │
│ Resolution:             │                      │                │
│   ❌ 找不到 strict 配對 │ 去尺寸 (strip_size): │ Level 6 (0)    │
│   ❌ drop_last_seg 失敗 │   N/A (僅 4 段)      │                │
│   ⚠ fuzzy 候選 3 筆    │                      │                │
│                         │ ISO 系列前綴：        │ 全部 3D 候選   │
│ 點查看 → [Trace Viewer]│   TRIM-6FL216Q (5 條)│ (5 筆) [展開]  │
│                         │                      │                │
└─────────────────────────┴──────────────────────┴────────────────┘
┌─ 下欄：原始 First_try 候選（從 first_try_trace.csv 拉，可篩）───┐
│ Path                              | Level | PipelineId | reason │
│ HP6.../HPS-TRIM/TRIM-6FL216Q-N3   |   4   | /TRIM-...  | 採用    │
│ HP6.../TRIM-.../TRIM-.../B1       |   5   | /.../B1    | 過濾   │
│ HP6.../TRIM-.../TRIM-.../B2       |   5   | /.../B2    | 過濾   │
│ HP6.../HPS-TRIM/TRIM-6FL216Q-N3   |   4   | /TRIM-...  | 重複    │
│ ... [12 筆]                                                     │
└────────────────────────────────────────────────────────────────┘
```

**互動**：
- 點任一 3D row → 開啟 `TraceViewerDialog` 顯示完整 IdentityReason
- 點「全部 3D 候選」展開 → 顯示該流水號比對嘗試過的所有 candidate（從 `CandidateTrace` 解析）
- 點 First_try 列 → 顯示完整 row（Path 全文、原始 PipelineId、Level）+ 是否進入 minus_1 + 進不去的原因

### 3.2 First_try Explorer（read-only 探勘器）
**檔案**：`gui/dialogs/first_try_explorer_dialog.py`（新增）

**職責**：直接拉出 `First_try.csv` 的原始 row，可按關鍵字 / Level / Path / PipelineId 篩選。**完全 read-only，不影響任何寫入**。

**佈局**：上方搜尋列 + 中間 Path/DisplayName/Class/Level/PipelineId 表格 + 下方詳情面板（顯示選中 row 是否進入 minus_1、若沒進為什麼）。

**設計重點**：使用者輸入 `TRIM-6FL216Q-N3` 後，上方搜尋同時對 Path/DisplayName/PipelineId 做 substring match，列出所有命中 row，**不論 Level**。

### 3.3 Match Explain Panel（既有 `TraceViewerDialog` 強化）
**檔案**：`gui/dialogs/trace_viewer_dialog.py`（**擴充**，不取代）

**新增能力**：
1. 多 trace 對比模式：可同時顯示「最佳候選 trace」+「全部候選 trace」（從 `CandidateTrace` 解析）
2. 「策略嘗試」區塊：顯示 `attempts` 欄位（如 `strict:fail, drop_last_seg:fail, fuzzy:0.65`）
3. ISO 端附加區：若該流水號在 ISO_LIST 找得到原始 row，顯示該 row 的 `Line num` / `流水號` / `發包分類` 等

### 3.4 Pipeline Investigation Tab（整合入口）
**檔案**：`gui/tabs/tab_investigation.py`（新增）

**職責**：在主視窗側欄加一個新 tab「🔍 調查」，作為上述三個 dialog 的**整合入口**。預設視圖是 Identity Inspector，旁邊有快捷按鈕：
- `🔎 First_try Explorer`
- `🔍 查 ISO`（從 ISO_LIST 列出所有流水號，點任一條 → Inspector 預填）
- `🔍 查 3D`（從 minus_1 列出所有 Raw_3D_PipeCode，點任一條 → Inspector 預填）
- `📋 看 collision`（直接跳到 CollisionDecisionDialog）

這個 tab 是排查時的「main hub」。

---

## 4. 各 UI 應顯示的欄位

> 表中標 ⭐ 為「現場排查必看」；標 ⓘ 為「進階使用者才需要」

### 4.1 Identity Inspector（左欄：ISO 端）

| 欄位 | 來源 | 標記 |
|---|---|---|
| 流水號 | `resolved_mapping.csv` `流水號` | ⭐ |
| 管線編號 | `resolved_mapping.csv` `管線編號` | ⭐ |
| ISO_Match_Key | `resolved_mapping.csv` | ⭐ |
| Resolution | `Resolved` + `ResolutionStatus` + `ResolutionReason` 合併呈現 | ⭐ |
| MatchType | `resolved_mapping.csv` | ⭐ |
| MatchScore | `resolved_mapping.csv` | ⭐ |
| 發包分類 | iso_match.xlsx 帶過來的 ISO 原欄位 | ⓘ |
| 系統 / 材質 / 保溫 | iso_match.xlsx 對應欄 | ⓘ |

### 4.2 Identity Inspector（中欄：身份家族）

| 欄位 | 算法 | 標記 |
|---|---|---|
| ISO normalized | `normalize_line_v2(iso_pipe)` | ⭐ |
| ISO 去末段 | drop_last_seg：對 5 段 ISO 去掉最後一段 | ⭐ |
| ISO 去尺寸 | `_strip_size_segment` | ⓘ |
| ISO 系列前綴 | system + line_no（前兩段） | ⭐ |
| 對應 3D 命中（strict） | 在 minus 端 normalized 集合是否出現 | ⭐ |
| 對應 3D 命中（drop_last） | 同上但比對 drop_last_seg key | ⭐ |
| 對應 3D 命中（前綴） | 系列前綴有多少 3D 候選 | ⭐ |

### 4.3 Identity Inspector（右欄：3D 端，按 Level 分群）

| 欄位 | 來源 | 標記 |
|---|---|---|
| Level | `123_minus_1.csv` `Level` | ⭐ |
| 在該 Level 找到的列數 | groupby + count | ⭐ |
| Raw_3D_PipeCode（範例） | `123_minus_1.csv` 該 Level 第一筆 Raw | ⭐ |
| ISO_Match_Key（範例） | `123_minus_1.csv` | ⓘ |
| ScopeRoot / ParentArea | `123_minus_1.csv` | ⭐ |
| MatchSource | `123_minus_1.csv`（pipeline_id / path_smart / display_name） | ⭐ |
| CandidateCount | `123_minus_1.csv` | ⓘ |

### 4.4 Identity Inspector（下欄：原始 First_try 候選）

| 欄位 | 來源 | 標記 |
|---|---|---|
| Path | `First_try.csv` 原始（不切段） | ⭐ |
| DisplayName | `First_try.csv` | ⭐ |
| Class | `First_try.csv` | ⭐ |
| Level | `First_try.csv` | ⭐ |
| PipelineId | `First_try.csv` | ⭐ |
| 進入 minus_1？ | 由 `first_try_trace.csv` 標記 | ⭐ |
| 排除原因 | 若沒進 minus_1，原因（pattern_fail / structural / file_like / no_id） | ⭐ |
| 對應 minus_1 row idx | 若有進入，對應 csv 行號 | ⓘ |

### 4.5 First_try Explorer 欄位

與 §4.4 相同，加上「全表 raw search」的 highlight。

### 4.6 Trace Viewer 強化（既有頁面新增）

| 區塊 | 欄位 |
|---|---|
| 既有時間軸 | 不變 |
| 候選清單 | 從 `CandidateTrace` 解析的 5 筆候選的 (idx, source, normalized, score, reason) |
| 策略嘗試 | `attempts` 欄位（若 trace 有） |
| ISO 端原始 | iso_match.xlsx 該流水號的全部欄位 |

---

## 5. 查詢場景：使用者輸入 `TRIM-6FL216Q-N3-001`

這是現場最常見的「為什麼這條沒進 JSON」排查。Inspector 應該分這幾步呈現：

### Step 1：使用者輸入查詢字串
**搜尋範圍 checkbox**（預設全勾）：
- ☑ ISO 流水號（在 `resolved_mapping.csv` 的 `流水號` 欄做 exact）
- ☑ ISO 管線編號（在 `resolved_mapping.csv` 的 `管線編號` 欄做 substring）
- ☑ 3D Raw（在 `123_minus_1.csv` 的 `Raw_3D_PipeCode` 欄做 substring）
- ☑ 3D 段位（在 `123_minus_1.csv` 的 `ISO_Match_Key` 段位做 substring，含去尺寸/去末段）

### Step 2：Inspector 解析查詢字串並顯示
- 偵測到輸入像 ISO 管線編號 → **左欄優先**：拉 `resolved_mapping.csv` 該流水號的所有列
- 中欄計算家族 key：`TRIM-6FL216Q-N3-001` → 去末段 → `TRIM-6FL216Q-N3` → 系列前綴 `TRIM-6FL216Q`
- 右欄：把 `123_minus_1.csv` 中 `ISO_Match_Key` 等於以下任一者的列拉出來：
  - `TRIM-6FL216Q-N3-001`（strict）
  - `TRIM-6FL216Q-N3`（drop_last）
  - 以 `TRIM-6FL216Q-N3` 為前綴的（family）
  - 以 `TRIM-6FL216Q` 為前綴的（系列）
- 下欄：把 `first_try_trace.csv`（**Phase B 才會建立**，見 §6）中 Path/DisplayName/PipelineId 包含 `TRIM-6FL216Q` 的列全部拉出來，**包括沒進 minus_1 的**

### Step 3：使用者目視判斷
看到：
- 左欄：「ISO 6321 (TRIM-6FL216Q-N3-001) 目前 ResolutionStatus=needs_decision 或 fuzzy_low」
- 中欄：「ISO 去末段 = TRIM-6FL216Q-N3，✓ 在 3D 端找到 1 筆 Level 4 + 2 筆 Level 5」
- 右欄：3 筆 3D row 列表（PipelineId / Level / ScopeRoot），可一鍵 Trace Viewer
- 下欄：12 筆 First_try 原始 row，3 筆進了 minus_1、9 筆被過濾（原因都標明）

使用者拍板：
- 「我看 Level 4 那筆 `/TRIM-6FL216Q-N3` 就是 ISO -001 的整管，B1/B2 是它的支管，這條 ISO 應該對應 Level 4 那筆」
- 點下方「📌 指定此 3D Raw 為 ISO 6321 的對應」（**Phase C 才會啟用**）

---

## 6. 是否需要新增中間檔 / 索引檔

**結論：要新增 2 個 opt-in 的 trace/索引檔。** 這是讓 Inspector 能跨檔查詢的關鍵。

### 6.1 `first_try_trace.csv`（Phase B 新增）

**動機**：目前 `123_minus_1.csv` 只保留**進入 minus_1 的列**，被 `PIPE_SEG_PATTERN` / `_is_structural` / `_is_file_like` / `no_id` 過濾掉的列**完全消失**——使用者要在 Inspector 看到「`/TRIM-6FL216Q-N3/B1` 這列為什麼沒進 minus_1」，就需要這個檔。

**Schema**：
```
Path, DisplayName, Class, Level, PipelineId,
candidate_count, best_candidate_normalized, best_candidate_source,
included_in_minus_1, exclude_reason, exclude_detail,
minus_1_row_idx
```

**寫入時機**：`PipelineExtractor.build_intermediate` 跑完後，**額外**寫一份完整 trace（含被排除的 row）。

**檔案大小考量**：First_try.csv 是 ≈124MB，trace 檔可能 ≈200MB+。**預設關閉**，由 `tab_pipeline` 加 checkbox「💾 同時輸出 first_try_trace.csv（用於排查）」開啟。

**規格細節**：
- 編碼：UTF-8-SIG
- 排除規則記錄為簡短英文字串：`pattern_fail` / `structural` / `file_like` / `no_id` / `empty`
- `exclude_detail` 為人類可讀的中文短句

### 6.2 `identity_index.csv`（Phase B 新增）

**動機**：Inspector 需要快速從「ISO 字串」反查「3D 家族成員」，每次都掃 minus_1 太慢。建一個索引讓查詢 O(1)。

**Schema**：
```
iso_norm, iso_norm_drop_last, iso_norm_strip_size,
iso_series_prefix, iso_pipe_raw, iso_spool,
match_3d_strict_count, match_3d_droplast_count,
match_3d_family_count, match_3d_series_count,
sample_3d_paths
```

每條 ISO 的 normalized 變體 + 對應 3D 命中數 + 範例 path。

**寫入時機**：`build_resolved_mapping` 之後，**額外**產出。預設啟用（檔案小，~幾百 KB）。

### 6.3 `investigation_cache.csv`（Phase D 新增，opt-in）

**動機**：當使用者在 Inspector 中做了人工指定後，系統需要記住「使用者選了 ISO X → 3D Y」，下次跑流程時不能被自動算法蓋掉。這個檔是「人工決策 log」。

**Schema**：
```
iso_spool, iso_pipe, decision_type,
chosen_raw_3d, chosen_path, chosen_level, chosen_parent_area,
decided_at, decided_by, note
```

`decision_type` enum：`manual_assign` / `manual_reject` / `manual_skip`

寫入時機：使用者在 Inspector 點「📌 指定」按鈕。下次 `build_resolved_mapping` 跑時優先採納此檔的決策。

---

## 7. First_try 原始候選保留策略

**現狀問題**：`identity_resolver.collect_candidates` 會收 N 個候選，但 `resolve` 只回傳最佳那一個的資料，其他候選只在 `CandidateTrace` 留摘要（最多 5 筆，每筆只有 `idx|source|normalized|score|reason`，沒有 raw）。

**本輪策略**：**不再壓縮候選**。新增一個 `candidates.csv`（Phase B 落地）保留每個 minus_1 row 的**全部候選**：

**Schema**：
```
minus_1_row_idx, candidate_idx,
raw, normalized, source, score, reason, trace_events
```

寫入時機：`PipelineExtractor.build_intermediate` 在 `_attach_identity_columns` 階段，把每個 row 的 `IdentityResolver.collect_candidates(row)` 結果**全部**寫進此檔（不只是被選為 best 的）。

**檔案大小**：估約 minus_1 的 3-5 倍（每 row 多 N 個候選），預估 ≈10MB 量級，**可以預設啟用**。

**Inspector 用途**：使用者點某條 minus_1 row 時，可看到「這條 row 其實有 5 個候選，被選為 best 的是 #2 (score 0.92)，你可能想看 #1 (score 0.85, source=DisplayName)」。

---

## 8. Implementation Phases

### Phase A：最小可用診斷 UI（read-only）
**目標**：使用者能用 Inspector 查 ISO / 3D 字串，看到目前已存在於 csv 中的脈絡。**不寫任何新檔**。

**範圍**：
- 新增 `gui/dialogs/identity_inspector_dialog.py`
  - 上方查詢框 + checkbox 範圍選擇
  - 三欄佈局：左 ISO / 中 家族 / 右 3D Level 分群
  - 下欄：先**只**顯示 minus_1 中含查詢字串的 row（**不**讀 first_try_trace，因為還沒有）
  - 點任一 row → 開 `TraceViewerDialog`（既有）
- 新增 `gui/tabs/tab_investigation.py`：把 Inspector 嵌入新 tab
- 在 `gui/main_window.py` 註冊新 tab
- 在 `gui/dialogs/collision_decision_dialog.py` 加「🔍 在 Inspector 中查」按鈕，預填查詢字串
- 在 `gui/dialogs/fuzzy_match_dialog.py` 加同上按鈕

**不在範圍**：
- 不寫 `first_try_trace.csv`（沒有它這個 phase 仍可用，只是下欄會比較少資料）
- 不寫 `identity_index.csv`（Phase A 直接掃 csv，後續 Phase B 才優化）
- 沒有人工指定功能

**修改範圍**：
- 新增：`gui/dialogs/identity_inspector_dialog.py`、`gui/tabs/tab_investigation.py`
- 修改：`gui/main_window.py`（註冊 tab）、`gui/dialogs/collision_decision_dialog.py` / `gui/dialogs/fuzzy_match_dialog.py`（加跳轉按鈕）
- 不動：所有 `core/` 模組、所有資料檔格式

**風險**：低。完全 read-only，最壞情況是 UI 不能用，不會破壞資料。

**驗收**：
- [ ] 開 GUI → 點「🔍 調查」tab → 輸入 `TRIM-6FL216Q-N3` → 三欄都有資料
- [ ] 從 collision dialog 點跳轉 → Inspector 自動預填當前流水號的管線編號
- [ ] 從 fuzzy dialog 點跳轉 → Inspector 自動預填當前 ISO 字串
- [ ] 點 3D row → `TraceViewerDialog` 彈出顯示完整 IdentityReason
- [ ] 既有 `tests/test_pipeline_regression.py` 全綠

---

### Phase B：跨中間檔追蹤（補資料、補索引）
**目標**：補上 `first_try_trace.csv` / `identity_index.csv` / `candidates.csv`，讓 Inspector 下欄能顯示「沒進 minus_1 的 First_try row」「該 row 的全部候選」。

**範圍**：
- 修改 `core/pipeline_extractor.py` `build_intermediate`：
  - 新增 opt-in 參數 `write_first_try_trace: bool = False`
  - 若 True，在 minus_1 寫完後，把 raw_df 全列（含被過濾的）寫進 `first_try_trace.csv`，並標記 `included_in_minus_1` / `exclude_reason`
  - 新增 opt-in 參數 `write_candidates: bool = False`
  - 若 True，把 `IdentityResolver.collect_candidates` 的全部結果（不只 best）寫進 `candidates.csv`
- 新增 `core/identity_index.py`：
  - 函式 `build_identity_index(resolved_mapping_path, minus_1_path) -> str`
  - 跑 `build_resolved_mapping` 之後自動呼叫
  - 預設啟用（檔案小）
- 強化 `gui/dialogs/identity_inspector_dialog.py`：
  - 下欄改吃 `first_try_trace.csv`（若存在）；不存在時 fallback 為「需在 tab_pipeline 啟用 first_try_trace」提示
  - 中欄使用 `identity_index.csv` 加速反查
- 修改 `gui/tabs/tab_pipeline.py`：加兩個 checkbox：
  - `☐ 同時輸出 first_try_trace.csv（用於排查，~200MB）`
  - `☐ 同時輸出 candidates.csv（保留全部候選，~10MB）`

**修改範圍**：
- 新增：`core/identity_index.py`
- 修改：`core/pipeline_extractor.py`、`gui/dialogs/identity_inspector_dialog.py`、`gui/tabs/tab_pipeline.py`
- **不修改** `OUTPUT_COLUMNS` 既有順序

**風險**：中。`build_intermediate` 簽名擴充（追加 keyword-only 參數）；要確保預設 False 時行為與現況一致。

**驗收**：
- [ ] 不勾選 checkbox → 跑流程後**沒有** `first_try_trace.csv` / `candidates.csv`
- [ ] 勾選 → 跑流程後檔案存在且結構正確
- [ ] Inspector 下欄能顯示被過濾的 First_try row 與排除原因
- [ ] `identity_index.csv` 在 `build_resolved_mapping` 後自動產生
- [ ] 既有 regression 全綠

---

### Phase C：人工指定 / 修正 mapping
**目標**：使用者在 Inspector 看到「ISO X 應該對應 3D Y」時，能直接點選並暫存決策。**本 phase 不寫回 resolved_mapping.csv**——只暫存到 `investigation_cache.csv`。

**範圍**：
- 強化 `gui/dialogs/identity_inspector_dialog.py`：
  - 右欄每筆 3D row 加「📌 指定為此 ISO 的對應」按鈕
  - 點擊後彈確認框：「將 ISO 流水號 6321 (TRIM-6FL216Q-N3-001) 對應到 3D Raw_3D_PipeCode = `/TRIM-6FL216Q-N3` (Level 4)，確認？」
  - 確認後寫入 `investigation_cache.csv`（追加模式）
- 新增 `core/investigation_cache.py`：
  - `read_cache(path) -> list[dict]`
  - `append_decision(path, decision: dict)`
  - `validate_cache(cache_path, resolved_mapping_path) -> list[warning]`（檢查決策的 iso_spool / 3D Raw 是否仍存在）
- Inspector 顯示「已指定」標記：若該流水號已在 cache 有決策，左欄顯示綠色 chip「📌 已人工指定」

**修改範圍**：
- 新增：`core/investigation_cache.py`、`tests/test_investigation_cache.py`
- 修改：`gui/dialogs/identity_inspector_dialog.py`

**風險**：中。要確保 cache 結構簡單、易讀（CSV）、可手動編輯而不破壞。

**驗收**：
- [ ] 在 Inspector 點「指定」→ `investigation_cache.csv` 新增一行
- [ ] 重開 GUI → Inspector 中該流水號顯示「已人工指定」chip
- [ ] 手動刪除 cache 中某行 → Inspector 對應 chip 消失
- [ ] cache 中若某 iso_spool 不存在於 resolved_mapping → `validate_cache` 回 warning

---

### Phase D：把人工決策寫回 resolved_mapping.csv
**目標**：跑 `build_resolved_mapping` 時讀 `investigation_cache.csv`，把人工決策合併進去。

**範圍**：
- 修改 `core/resolved_mapping.py` `build_resolved_mapping`：
  - 新增參數 `investigation_cache_path: Optional[str] = None`
  - 若提供且檔案存在，跑完自動規則後**覆寫**人工指定的列：
    - `Resolved=1`、`ResolutionStatus="manual_investigation"`
    - `ResolutionReason="使用者於 Inspector 指定: <decision_type>"`
    - `ResolvedBy="user"`、`ResolvedAt=<cache 中的 decided_at>`
    - `Raw_3D_PipeCode` 改為 cache 指定的 raw
    - `NeedsDecision=0`
- 修改 `gui/tabs/tab_pipeline.py`：
  - `build_resolved_mapping` 呼叫處傳入 cache 路徑
- 修改 `core/json_exporter.py`：
  - 確保 `manual_investigation` 列被視為已 resolved，正常進入 JSON
- 新增 `tests/test_resolved_mapping_with_cache.py`

**修改範圍**：
- 修改：`core/resolved_mapping.py`、`gui/tabs/tab_pipeline.py`、`core/json_exporter.py`
- 新增：`tests/test_resolved_mapping_with_cache.py`
- 不動：`OUTPUT_COLUMNS` 既有順序（`ResolutionStatus` 已存在，新狀態值 `manual_investigation` 是字串值不是 schema 變動）

**風險**：中高。這是第一次「人工輸入會影響 JSON 結果」的環節，要做好兩件事：
1. cache 檔損毀 / 缺欄位時，**不可**讓整個 build_resolved_mapping 崩潰，要 graceful fallback + log warning
2. 人工指定的 raw 在 minus_1 中可能已不存在（資料更新了），此時要保留原邏輯結果並 log

**驗收**：
- [ ] cache 為空 / 不存在時，行為與 Phase D 之前完全一致
- [ ] cache 有 1 條決策，跑完後 `resolved_mapping.csv` 對應流水號 `Resolved=1`、`ResolutionStatus=manual_investigation`
- [ ] cache 中指定的 raw 不存在於 minus_1 時，警告但不崩潰
- [ ] JSON 匯出正確包含人工指定的 raw
- [ ] 既有 regression 全綠

---

## 9. 必要測試清單

### Phase A（read-only UI）
- `tests/test_identity_inspector_dialog.py`
  - `test_inspector_renders_with_empty_query`
  - `test_inspector_loads_resolved_mapping`
  - `test_inspector_search_by_iso_pipe_code`：輸入 `TRIM-6FL216Q-N3-001` → 左欄顯示對應流水號
  - `test_inspector_search_by_3d_raw`：輸入 `/TRIM-6FL216Q-N3` → 右欄顯示 minus_1 對應 row
  - `test_inspector_drop_last_seg_lookup`：輸入 ISO 5 段管線編號 → 中欄計算去末段並找到 3D 命中
  - `test_inspector_jumps_from_collision_dialog`：模擬 collision dialog 跳轉，預填正確
- `tests/test_tab_investigation.py`：smoke test，tab 能初始化

### Phase B（中間檔擴充）
- `tests/test_first_try_trace.py`
  - `test_no_trace_when_disabled`
  - `test_trace_includes_excluded_rows`：含 file-like / structural / pattern-fail 的 row 都應該被記錄但 `included_in_minus_1=0`
  - `test_exclude_reason_classification`：6 種排除原因都能被正確標記
- `tests/test_candidates_csv.py`
  - `test_candidates_csv_has_all_candidates`：給 1 個 row 帶 5 個候選，候選檔應有 5 行
  - `test_candidates_csv_disabled_by_default`
- `tests/test_identity_index.py`
  - `test_index_has_drop_last_lookup`
  - `test_index_lists_family_count`

### Phase C（人工指定）
- `tests/test_investigation_cache.py`
  - `test_append_decision_creates_file`
  - `test_append_idempotent_for_same_spool`
  - `test_validate_cache_warns_when_iso_missing`
  - `test_validate_cache_warns_when_raw_missing`

### Phase D（寫回）
- `tests/test_resolved_mapping_with_cache.py`
  - `test_no_cache_unchanged_behavior`
  - `test_cache_overrides_auto_resolution`：自動演算法判定為 needs_decision，cache 強制 resolve
  - `test_cache_with_missing_raw_warns_and_falls_back`
  - `test_manual_investigation_status_in_output`：`ResolutionStatus` 為 `manual_investigation` 字串

### 整體 smoke
- `tests/test_pipeline_regression.py` 必須**全 phase 全綠**

---

## 10. 不可動清單（v2 沿用 v1.1 + 新增）

| 項目 | 位置 | 為什麼不可動 |
|---|---|---|
| Phase 1–5 已完成的所有檔案 | `core/size_normalizer.py` 等 | 已上 commit、有測試 |
| `IdentityResolver` 公開 API | `core/identity_resolver.py` | 已被 extractor 呼叫 |
| `parse_trace` / `TraceBuilder` 簽名 | `utils/trace_builder.py` | 已被 TraceViewerDialog 使用 |
| `OUTPUT_COLUMNS` 既有順序 | `core/resolved_mapping.py:22-45` | 多處依賴 |
| `TraceViewerDialog` 既有渲染邏輯 | `gui/dialogs/trace_viewer_dialog.py` | Phase 4 已驗收；本輪只**擴充**新區塊，不改既有 |
| `CollisionDecisionDialog` 既有 UI | `gui/dialogs/collision_decision_dialog.py` | 同上 |
| `FuzzyMatchDialog` 候選結構 | `gui/dialogs/fuzzy_match_dialog.py` | 既有候選 dict 結構不動 |
| `build_resolved_mapping` 既有簽名 | `core/resolved_mapping.py` | Phase D 只**追加** keyword 參數，不改既有 |
| 已上 commit 的 git 歷史 | 全 repo | 不重寫 |

---

## 11. 不在範圍內的事（v2 不做）

- 不重新訓練 fuzzy 評分（既有 size-leading fuzzy 已夠用，本輪是 UI 顯示問題）
- 不引入「自動學習人工決策」（先讓使用者手動，未來再考慮）
- 不做圖形化的 3D 樹狀視覺（Path 用文字 + 縮排顯示就夠）
- 不改 ISO_LIST 寫回路徑（人工決策只寫進 `investigation_cache.csv`，不動 ISO_LIST）
- 不做 web UI（維持 PyQt6 桌面）

---

## 12. 完成檢查清單（執行前印出來，做完一條打 ✅）

### Phase A
- [ ] `gui/dialogs/identity_inspector_dialog.py` 新檔
- [ ] `gui/tabs/tab_investigation.py` 新檔
- [ ] `gui/main_window.py` 註冊新 tab
- [ ] `gui/dialogs/collision_decision_dialog.py` 加跳轉按鈕
- [ ] `gui/dialogs/fuzzy_match_dialog.py` 加跳轉按鈕
- [ ] `tests/test_identity_inspector_dialog.py` 新增、全綠
- [ ] 既有 regression 全綠
- [ ] commit `[Phase A] 新增 Identity Inspector / Investigation Tab`

### Phase B
- [ ] `core/pipeline_extractor.py` 新增 opt-in 參數 + 寫 first_try_trace / candidates
- [ ] `core/identity_index.py` 新檔
- [ ] `gui/dialogs/identity_inspector_dialog.py` 強化下欄讀 first_try_trace
- [ ] `gui/tabs/tab_pipeline.py` 加 checkbox
- [ ] `tests/test_first_try_trace.py` / `test_candidates_csv.py` / `test_identity_index.py` 全綠
- [ ] 既有 regression 全綠
- [ ] commit `[Phase B] 新增中間檔追蹤 + identity_index`

### Phase C
- [ ] `core/investigation_cache.py` 新檔
- [ ] `gui/dialogs/identity_inspector_dialog.py` 新增「指定」按鈕 + 已指定 chip
- [ ] `tests/test_investigation_cache.py` 全綠
- [ ] 既有 regression 全綠
- [ ] commit `[Phase C] 人工指定 mapping (read-write cache)`

### Phase D
- [ ] `core/resolved_mapping.py` 加 `investigation_cache_path` 參數
- [ ] `gui/tabs/tab_pipeline.py` 傳入 cache 路徑
- [ ] `core/json_exporter.py` 處理 manual_investigation 狀態
- [ ] `tests/test_resolved_mapping_with_cache.py` 全綠
- [ ] 既有 regression 全綠
- [ ] commit `[Phase D] 人工決策寫回 resolved_mapping`

### 整體
- [ ] `python -m unittest discover -s tests -v` 全綠
- [ ] 沒有新增第三方依賴
- [ ] 沒有重寫 git 歷史
- [ ] 完整跑一次真實資料：`TRIM-6FL216Q-N3-001` 在 Inspector 中能看到完整脈絡（左 ISO + 中家族 + 右 3D + 下 First_try）

---

## 附錄 A — 既有 file:line 引用一覽（給 Codex 找位置用）

| 議題 | 模組 |
|---|---|
| `IdentityResolver.collect_candidates` | `core/identity_resolver.py:193-250` |
| `IdentityResolver.resolve` | `core/identity_resolver.py:265-296` |
| `_build_candidate_trace` 結構 | `core/identity_resolver.py:91-107` |
| `_build_candidates_trace`（最多 5 筆候選摘要） | `core/identity_resolver.py:109-117` |
| Trace `§` 文法與 `parse_trace` | `utils/trace_builder.py:8-116` |
| `TraceViewerDialog` 渲染與 group 分類 | `gui/dialogs/trace_viewer_dialog.py:24-152` |
| `CollisionDecisionDialog` 流水號清單與選定 | `gui/dialogs/collision_decision_dialog.py:21-171` |
| `load_collision_groups` / `apply_collision_decisions` | `core/collision_resolver.py:22-129` |
| `OUTPUT_COLUMNS` | `core/resolved_mapping.py:22-45` |
| `build_resolved_mapping` | `core/resolved_mapping.py:79-173` |
| `PipelineExtractor.build_intermediate` 入口（含 ISO whitelist 參數） | `core/pipeline_extractor.py` |
| `PipelineExtractor._attach_identity_columns` | `core/pipeline_extractor.py:327-343` |
| `PipelineExtractor._attach_scope_columns` | `core/pipeline_extractor.py:345-359` |

---

## 附錄 B — 使用者實際痛點原文（保留以便核對）

> ISO 端有 TRIM-6FL216Q-N3-001，但 fuzzy 目前只能給低信心全文相似候選。可是從 First_try.csv 看起來，3D 明明有 TRIM-6FL216Q-N3 這個上層身份，甚至有 B1/B2 分支。現在使用者很難從 GUI 或中間檔知道：
>
> 1. 這條 ISO 為什麼找不到？
> 2. 3D 端其實在哪一層出現過相似身份？
> 3. Step1 是在哪一層抽到 Raw_3D_PipeCode？
> 4. 哪些 row 被 whitelist / strict / normalize / fuzzy 排除？
> 5. TRIM-6FL216Q-N3 與 TRIM-6FL216Q-N3-001 的關係該如何呈現給使用者人工判斷？
> 6. First_try.csv -> minus_1 -> minus_2 -> iso_match -> resolved_mapping -> JSON 這整條資料流，哪一站丟失了脈絡？

**對照表**：

| 痛點 # | 由哪個 Phase / UI 元件解決 |
|---|---|
| 1. 為什麼找不到？ | Phase A · Inspector 左欄「Resolution」+ TraceViewer 既有時間軸 |
| 2. 3D 端在哪一層？ | Phase A · Inspector 右欄 Level 分群 |
| 3. Step1 在哪一層抽到 Raw？ | Phase A · 點 3D row 開 TraceViewer 看 `level` 欄；Phase B · Inspector 下欄看 First_try 原始 row |
| 4. 哪些 row 被排除？ | Phase B · `first_try_trace.csv` + Inspector 下欄「排除原因」 |
| 5. ISO -001 vs 3D parent 的關係？ | Phase A · Inspector 中欄「身份家族」（drop_last / strip_size / 系列前綴） |
| 6. 哪一站丟失了脈絡？ | Phase A · Inspector 三欄同時顯示 minus_1 / iso_match / resolved_mapping 的對應狀態；Phase B · 補上 First_try 階段 |

---

## 收尾

本指導書 v1.0 設計目標：在 Phase 1–5 已建立的資料模型之上，補上**雙向、跨檔、可追溯**的排查 UI。

**核心理念**：程式不該猜到底；UI 要讓使用者「看見可能性」，由人決策，並把決策寫回讓下次跑流程時遵守。

> **記住：先讓使用者看見，再讓使用者決定，最後讓決定影響輸出。** 這三步**不要**合併成「程式自動配對」。

— v1.0 指導書結束 —
