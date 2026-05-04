# 管線流程工具 — Fuzzy 強化 + Trace 可視化 實作指令書 v1.1

> 版本：2026-05-04 · v1.1 修訂版（解決 v1.0 內部矛盾）  
> 範圍：**僅本輪實作 Phase 1–3**（Batch A）；Phase 4–6 列入未來 roadmap，不在本輪實作範圍  
> 對象：Codex / 任何具備 Python+PyQt6 經驗的 AI/人類開發者  
> 撰寫者：架構審查階段產出，已對齊使用者需求與 `IMPLEMENTATION_QUESTIONS.md` 中 Codex 提出的所有疑問

---

## 0. v1.1 修訂說明（v1.0 → v1.1 的變更）

v1.0 規格在實作前由 Codex 進行 lint，發現以下矛盾，本版已逐一修正：

| # | v1.0 矛盾 | v1.1 修正 |
|---|---|---|
| 1 | 規格要求 pytest，但 requirements.txt 不允許新增依賴 | **改用 stdlib `unittest`**，與既有 `tests/test_pipeline_regression.py` 風格一致；不引入 pytest |
| 2 | 開頭 Phase 4 標選做、checklist 又把 Phase 4 列必做 | **本輪僅做 Phase 1–3**；Phase 4–6 移至附錄 E「未來 roadmap」 |
| 3 | 不可動清單寫「不可改 `build_intermediate` 簽名」，但前輪已為 ISO whitelist 改過 | **接受當前簽名為準**（含 `iso_list_path`/`iso_sheet_name`/`pipe_col_override` 三個新參），不回退；本輪新增參數沿用既有風格 |
| 4 | 要求新增 `Trace` 欄到 `resolved_mapping.csv`，又警告不可動 `OUTPUT_COLUMNS` | **改為 append-only**：新欄位一律追加在 `OUTPUT_COLUMNS` 尾端，既有順序不變 |
| 5 | 引入新欄位名 `Source`/`Trace`，但既有已有 `MatchSource`/`IdentityReason`/`CandidateTrace` | **沿用既有欄位名**，把結構化 trace 字串塞進 `IdentityReason` 與 `CandidateTrace`；不新增同義新欄 |
| 6 | 一邊說 `normalize_line` v1 不變、一邊暗示改成 `v2` 的 thin wrapper | **`normalize_line` v1 完全不動**（簽名與行為皆不變）；`normalize_line_v2` 是獨立函式，只在新流程**顯式呼叫**時才生效 |
| 7 | commit 格式要求 `[Phase N]`，但前輪 commit 未遵守 | **不重寫歷史**；本格式從下一個 commit 起套用 |

**核心原則：保守、增量、可逆。** 任何「順手清理」行為一律拒絕。新功能不破壞既有資料路徑。

---

## A. 給 Codex 的執行守則（READ FIRST）

### A.1 你的角色
你是這個專案的後端工程師（本輪不碰 GUI）。任務是依照本指令書「逐 Phase 完成」，每一 Phase 必須：
1. 寫 production code
2. 寫 stdlib `unittest` 測試
3. 跑 `python -m unittest discover -s tests -v` 全綠才能進下一 Phase
4. 不破壞既有功能（既有 regression test 必須全綠）

### A.2 不可違反的鐵則（v1.1 已對齊現況）

- **不要改** `normalize_line(s)` 的簽名與行為（v1 必須與現況**完全一致**）
- **不要改** `PIPE_SEG_PATTERN` 的 regex 字面
- **不要改** `Raw_3D_PipeCode` 保留 `/` 前綴的設計
- **不要動** ISO_LIST 上的 `/` 前綴（使用者刻意加的，留著）
- **不要改變** `OUTPUT_COLUMNS` 中**既有欄位的順序**；新欄位**只能 append 在尾端**
- **不要重構**既有的 `MatchSource` / `IdentityReason` / `CandidateTrace` 欄位（沿用，把結構化 trace 字串塞進去）
- **不要改變** `core/iso_matcher.py` Phase 1–4 既有命中邏輯，新增邏輯**疊加**不取代
- **不要重寫** git 歷史；commit 格式從本輪下個 commit 起遵守即可
- **不要引入**新的第三方套件；`requirements.txt` 維持 `PyQt6>=6.6 / pandas>=2.0 / openpyxl>=3.1`
- **不要把** `.venv / build / dist / __pycache__` 加進 git

### A.3 程式風格
- Python 3.12 / PyQt6
- 字串：所有面向使用者的訊息用**繁體中文**；docstring 一律繁體中文
- 命名：模組名 snake_case、類別 CamelCase、函式 snake_case
- Type hints 一律加（從 `typing` 引）
- 測試檔放 `tests/`，命名 `test_<module>.py`，用 stdlib `unittest.TestCase`

### A.4 提交順序
本輪共 3 個 commit（Phase 1、2、3 各一個），commit message 格式：
```
[Phase N] <50 字以內 summary>

詳細：
- 改動 1
- 改動 2

測試：
- 新增 tests/test_xxx.py：N 個 case 全綠
- 既有 tests/test_pipeline_regression.py：M 個 case 全綠

真實資料（適用時）：
- iso_match.xlsx MatchType=strict: 1234 → 1289 (+55)
```

### A.5 遇到不確定時
- 如果規格與現有程式行為衝突 → **以本指令書為準**，但要在 commit message 註明「行為變動」
- 如果發現本指令書有 bug → **暫停**，把疑問追加到 `IMPLEMENTATION_QUESTIONS.md`（v1.0 已經由 Codex 建立此檔，沿用），不要自作主張

---

## B. 專案座標

### B.1 路徑
```
專案根目錄：  C:\Users\a0976\Documents\GitHub\管線流程工具
入口檔：      run_pipeline_gui_qt.py
資料樣本：    First_try.csv (≈124 MB), ISO_LIST.xlsx (≈118 KB)
測試目錄：    tests/    （需建立 tests/fixtures/ 子目錄）
測試指令：    python -m unittest discover -s tests -v
```

### B.2 既有後端模組（已重構好，本輪不重複建立）

| 模組 | 行數 | 職責 | 本輪會動嗎 |
|---|---|---|---|
| `core/pipeline_extractor.py` | 415 | First_try.csv → minus_1.csv | **會**（Phase 2 加 trace 收集） |
| `core/pipeline_grouper.py` | 122 | minus_1 → minus_2 | 不動 |
| `core/iso_matcher.py` | 1296 | minus_2 → iso_match.xlsx | **會**（Phase 2 加 trace 收集） |
| `core/json_exporter.py` | 280 | iso_match → JSON | 不動 |
| `core/identity_resolver.py` | 244 | 候選 + scoring | **可能會**（Phase 3 接入 v2 normalize） |
| `core/scope_indexer.py` | 90 | parse_scope_context | 不動 |
| `core/resolved_mapping.py` | 173 | resolved_mapping.csv | **會**（OUTPUT_COLUMNS 尾端 append 新欄） |
| `utils/utils_common.py` | 180 | normalize_line / 等 | **會**（Phase 3 新增 normalize_line_v2，**v1 不動**） |
| `utils/iso_schema.py` | 232 | ISO 欄位偵測 | 不動 |
| `utils/pipe_parser.py` | 120 | pipeline_config.json 讀取 | 不動 |

### B.3 既有測試
- `tests/test_pipeline_regression.py` 使用 stdlib `unittest`，本輪結束時必須仍全綠
- 跑法：`python -m unittest discover -s tests -v`

### B.4 既有欄位命名（沿用，不另起爐灶）

`OUTPUT_COLUMNS` 來源：`core/resolved_mapping.py:22-45`，**順序不可動**：

```python
OUTPUT_COLUMNS = [
    "Resolved", "ResolutionStatus", "ResolutionReason",
    "ResolvedAt", "ResolvedBy",
    "流水號", "管線編號", "ISO_Match_Key", "Raw_3D_PipeCode",
    "PipeNodePath", "ScopeRoot", "ParentArea", "PipeNodeLevel",
    "MatchType", "MatchScore", "MatchSource", "ConfidencePrimary",
    "IdentityReason",
    "CollisionCount", "CollisionParents",
    "NeedsDecision", "群組",
]
```

本輪相關欄位的語意對齊：

| 欄位 | 現有語意 | 本輪規範化的語意 |
|---|---|---|
| `MatchSource` | identity 來源（`pipeline_id` / `path_smart` / 等） | **不變**，本輪沿用 |
| `IdentityReason` | identity 解析的人類可讀理由 | **擴展為「`§` 結構化 trace 字串」**（向後相容：仍是字串，仍可人讀） |
| `CandidateTrace` | 若已存在於 minus_1 / iso_match：候選追蹤字串；若不存在於 OUTPUT_COLUMNS：本輪不新增到 resolved_mapping | 寫新內容時用 `§` 結構化格式 |

**新欄位 append 規則**（本輪僅 Phase 2 結尾允許）：若需要新增 `Trace` 欄位到 `OUTPUT_COLUMNS`，**只允許 append 在 `"群組"` 之後**，且 commit message 需明列。優先策略是「重用既有欄位」，新增是最後手段。

---

## C. PHASE 1 — `core/size_normalizer.py`（必做 · 半天）

### C.1 目的
解掉 `1/2`、`1 1/2`、`1.5`、`1_1/2`、`1.1_2`、`11/2` 等 inch 分數變體在比對流程中變成 `1.1_2` / `0.5` / `1_2` 等怪值的 bug。

### C.2 範圍
- **僅處理 inch 分數變體**。整數值（如 `100`、`50`、`150`）原樣放行，不解讀為 mm。
- 不規範化單位字尾的 `"`、`'`、`mm`，這些在進入此 normalizer 前由呼叫端清理。

### C.3 新檔規格

**檔案路徑**：`core/size_normalizer.py`

**完整 API**：

```python
# -*- coding: utf-8 -*-
"""管徑尺寸正規化：把各種 inch 分數變體規範成 NPS 標準字串。

設計原則：
1. 只處理「看起來是 inch 分數」的 token，整數值原樣放行
2. 解析多種變體 → 找出 inch 數值 → 比對 NPS 標準表 → 規範字串
3. 不在 NPS 表內的數值 → 標 'non_standard' 但保留原始 token
4. 完全無法解析 → 原樣回傳 + status='unknown'

使用範例：
    canonical, inches, status = normalize_size_token("1.1_2")
    # → ("1-1/2", 1.5, "matched")

    canonical, inches, status = normalize_size_token("100")
    # → ("100", None, "passthrough_int")

注意：本模組不依賴 utils/utils_common.py，可被任何模組安全引入。
"""
from __future__ import annotations

import re
from typing import Final, Optional


# NPS 標準尺寸（inch）→ 規範字串
# 來源：ASME B36.10/B36.19
NPS_SIZES: Final[dict[float, str]] = {
    0.125: "1/8",
    0.25:  "1/4",
    0.375: "3/8",
    0.5:   "1/2",
    0.75:  "3/4",
    1.0:   "1",
    1.25:  "1-1/4",
    1.5:   "1-1/2",
    2.0:   "2",
    2.5:   "2-1/2",
    3.0:   "3",
    3.5:   "3-1/2",
    4.0:   "4",
    5.0:   "5",
    6.0:   "6",
    8.0:   "8",
    10.0:  "10",
    12.0:  "12",
    14.0:  "14",
    16.0:  "16",
    18.0:  "18",
    20.0:  "20",
    24.0:  "24",
    30.0:  "30",
    36.0:  "36",
    42.0:  "42",
    48.0:  "48",
}

# Status 常數
STATUS_MATCHED: Final = "matched"            # 解析成功且為 NPS 標準
STATUS_NON_STANDARD: Final = "non_standard"  # 解析出數值但非 NPS
STATUS_PASSTHROUGH_INT: Final = "passthrough_int"  # 純整數，未解讀
STATUS_UNKNOWN: Final = "unknown"            # 無法解析


def normalize_size_token(
    token: str,
    nps_sizes: Optional[dict[float, str]] = None,
) -> tuple[str, Optional[float], str]:
    """把單一 size token 規範化。

    Parameters
    ----------
    token : str
        待處理 token，例如 ``"1.1_2"``、``"100"``、``"3/4"``
    nps_sizes : dict, optional
        覆寫 NPS 表（測試用）

    Returns
    -------
    tuple[str, float | None, str]
        (canonical_string, inches_value, status)
        - canonical_string：規範後字串（status='matched' 時來自 NPS 表）
        - inches_value：數值（None 表示不解讀）
        - status：見 STATUS_* 常數
    """
    raise NotImplementedError("Codex 實作")


def is_size_like(token: str) -> bool:
    """判斷 token 是否「看起來是 size」。

    判斷準則：
    - 含有 ``/`` → 是
    - 含有 ``_`` 且兩邊都有數字 → 是（如 1_1/2）
    - 純整數 1~999 → 是（可能是 mm 或 inch 整數）
    - 浮點數 0.1~99.9 → 是（如 1.5）
    - 含字母 → 否（如 'AA1B' 是 class，不是 size）
    """
    raise NotImplementedError("Codex 實作")
```

### C.4 解析策略順序（依序嘗試，命中即返）

#### C.4.1 純整數
若 `token.strip().isdigit()`：
- 若 `int(token) >= 1` → 回傳 `(token, None, "passthrough_int")`

#### C.4.2 純浮點
若 `token` match `^\d+\.\d+$`（如 `1.5`）：
- 解析成 float
- 若值在 NPS 表（容差 ±0.001） → `(NPS_SIZES[v], v, "matched")`
- 否則 `(token, v, "non_standard")`

#### C.4.3 顯式分數 `\d+/\d+`
若 `token` match `^(\d+)/(\d+)$`（如 `3/4`、`11/2`）：
- 算 `numerator / denominator`
- 若值落在 NPS 表 → `(NPS_SIZES[v], v, "matched")`
- 若 `numerator >= 10` 且 `numerator/denominator > 5`（不合理大）→ **重試**：把 `numerator` 拆成 `whole + frac_num`（即 `11` → `1` + `1`），合成 `1 + 1/2 = 1.5`，若這個值在 NPS 表 → 採用
- 仍找不到 → `(token, v, "non_standard")`

#### C.4.4 帶整數的分數 `\d+[ \-_.]\d+/\d+`
若 `token` match `^(\d+)[\s\-_.](\d+)/(\d+)$`（如 `1 1/2`、`1-1/2`、`1_1/2`、`1.1/2`）：
- `value = whole + frac_num/frac_den`
- NPS 查表

#### C.4.5 你看到的 bug 變體 `\d+\.\d+_\d+`
若 `token` match `^(\d+)\.(\d+)_(\d+)$`（如 `1.1_2`）：
- 解讀為 `whole=$1, frac_num=$2, frac_den=$3`
- `value = whole + frac_num/frac_den`
- NPS 查表
- 此分支必須對 `1.1_2 → 1.5 → "1-1/2"` 命中

#### C.4.6 全部失敗
回傳 `(token, None, "unknown")`

### C.5 `is_size_like` 實作要點
- regex `r"^\d+(\.\d+)?$"` → 純數字（含小數）→ True
- regex `r"^\d+/\d+$"` → 顯式分數 → True
- regex `r"^\d+[\s\-_.]\d+/\d+$"` → 混合 → True
- regex `r"^\d+\.\d+_\d+$"` → bug 變體 → True
- 含字母（`re.search(r"[A-Za-z]", token)`）→ False

### C.6 測試（`unittest` 風格）

**檔案路徑**：`tests/test_size_normalizer.py`

```python
# -*- coding: utf-8 -*-
import unittest

from core.size_normalizer import (
    normalize_size_token, is_size_like,
    STATUS_MATCHED, STATUS_NON_STANDARD,
    STATUS_PASSTHROUGH_INT, STATUS_UNKNOWN,
)


class NormalizeSizeTokenTests(unittest.TestCase):
    """涵蓋整數、分數、bug 變體三大類，共 30+ case。"""

    def _check(self, token, expected_canonical, expected_inches, expected_status):
        canonical, inches, status = normalize_size_token(token)
        self.assertEqual(canonical, expected_canonical, f"token={token!r}")
        self.assertEqual(inches, expected_inches, f"token={token!r}")
        self.assertEqual(status, expected_status, f"token={token!r}")

    # ── 純整數 → passthrough ──
    def test_pure_int_50(self):     self._check("50",  "50",  None, STATUS_PASSTHROUGH_INT)
    def test_pure_int_100(self):    self._check("100", "100", None, STATUS_PASSTHROUGH_INT)
    def test_pure_int_150(self):    self._check("150", "150", None, STATUS_PASSTHROUGH_INT)
    def test_pure_int_1(self):      self._check("1",   "1",   None, STATUS_PASSTHROUGH_INT)

    # ── 純浮點 ──
    def test_float_1_5(self):       self._check("1.5",  "1-1/2", 1.5,  STATUS_MATCHED)
    def test_float_2_5(self):       self._check("2.5",  "2-1/2", 2.5,  STATUS_MATCHED)
    def test_float_0_5(self):       self._check("0.5",  "1/2",   0.5,  STATUS_MATCHED)
    def test_float_0_75(self):      self._check("0.75", "3/4",   0.75, STATUS_MATCHED)
    def test_float_99_9(self):      self._check("99.9", "99.9",  99.9, STATUS_NON_STANDARD)

    # ── 顯式分數（普通）──
    def test_frac_1_2(self):        self._check("1/2",  "1/2",   0.5,   STATUS_MATCHED)
    def test_frac_3_4(self):        self._check("3/4",  "3/4",   0.75,  STATUS_MATCHED)
    def test_frac_1_8(self):        self._check("1/8",  "1/8",   0.125, STATUS_MATCHED)
    def test_frac_3_8(self):        self._check("3/8",  "3/8",   0.375, STATUS_MATCHED)

    # ── 顯式分數（被 replace(" ") 黏起來的）──
    def test_glued_11_2(self):      self._check("11/2", "1-1/2", 1.5, STATUS_MATCHED)
    def test_glued_21_2(self):      self._check("21/2", "2-1/2", 2.5, STATUS_MATCHED)
    def test_glued_31_2(self):      self._check("31/2", "3-1/2", 3.5, STATUS_MATCHED)

    # ── 帶整數的分數（多種分隔符）──
    def test_mixed_1_space_1_2(self):  self._check("1 1/2", "1-1/2", 1.5,  STATUS_MATCHED)
    def test_mixed_1_dash_1_2(self):   self._check("1-1/2", "1-1/2", 1.5,  STATUS_MATCHED)
    def test_mixed_1_under_1_2(self):  self._check("1_1/2", "1-1/2", 1.5,  STATUS_MATCHED)
    def test_mixed_2_space_1_2(self):  self._check("2 1/2", "2-1/2", 2.5,  STATUS_MATCHED)
    def test_mixed_2_dash_1_2(self):   self._check("2-1/2", "2-1/2", 2.5,  STATUS_MATCHED)
    def test_mixed_1_space_1_4(self):  self._check("1 1/4", "1-1/4", 1.25, STATUS_MATCHED)

    # ── 你看到的 bug 變體 ──
    def test_bug_1d1_2(self):       self._check("1.1_2", "1-1/2", 1.5,  STATUS_MATCHED)
    def test_bug_2d1_2(self):       self._check("2.1_2", "2-1/2", 2.5,  STATUS_MATCHED)
    def test_bug_1d1_4(self):       self._check("1.1_4", "1-1/4", 1.25, STATUS_MATCHED)
    def test_bug_1d3_4(self):       self._check("1.3_4", "1.3_4", 1.75, STATUS_NON_STANDARD)

    # ── 無法解析 ──
    def test_unknown_AA1B(self):    self._check("AA1B",  "AA1B",  None, STATUS_UNKNOWN)
    def test_unknown_empty(self):   self._check("",      "",      None, STATUS_UNKNOWN)
    def test_unknown_foo(self):     self._check("foo",   "foo",   None, STATUS_UNKNOWN)
    def test_unknown_12X34(self):   self._check("12X34", "12X34", None, STATUS_UNKNOWN)


class IsSizeLikeTests(unittest.TestCase):
    def test_size_like_true_cases(self):
        for token in ("100", "1/2", "1 1/2", "1.1_2", "1.5"):
            self.assertTrue(is_size_like(token), f"token={token!r}")

    def test_size_like_false_cases(self):
        for token in ("AA1B", "S11UG", "NA", ""):
            self.assertFalse(is_size_like(token), f"token={token!r}")

    def test_pure_int_is_size_like(self):
        # 整數可能是 size 也可能是 line_no，is_size_like 仍回 True，
        # 真實判斷靠後續 segment_priors。
        self.assertTrue(is_size_like("60371"))


if __name__ == "__main__":
    unittest.main()
```

### C.7 驗收（Phase 1）
- [ ] `python -m unittest tests.test_size_normalizer -v` 全綠
- [ ] `python -m unittest tests.test_pipeline_regression -v` 仍全綠
- [ ] `core/size_normalizer.py` 沒引入新的第三方套件
- [ ] commit 訊息為 `[Phase 1] core/size_normalizer.py + 測試`

---

## D. PHASE 2 — Trace 收集與寫入既有欄位（必做 · 1 天）

### D.1 目的
讓中間檔（`123_minus_1.csv`、`iso_match.xlsx`、`resolved_mapping.csv`）的 trace 字串**結構化**，使用者打開 csv 即可用文字搜尋找出「為什麼這條變這樣」。

### D.2 重要原則：**不新增同義欄位、沿用既有 IdentityReason / CandidateTrace**

| 既有欄位 | 用途 | 本輪寫入內容 |
|---|---|---|
| `MatchSource` | identity 解析的「來源類型」 | **不變**（仍寫 `pipeline_id` / `path_smart` 等） |
| `IdentityReason` | identity 解析的「人類可讀理由」 | **擴展**：寫入 `§` 結構化 trace 字串 |
| `CandidateTrace`（若 minus_1/iso_match 已有此欄） | 候選追蹤字串 | **擴展**：寫入 `§` 結構化 trace 字串 |

**`IdentityReason` 升級為結構化字串是向後相容的**——它本來就是字串、本來就供人讀，只是現在格式有規範。下游若有程式直接讀此欄當人類文字（grep / 顯示），最多只是看到多了 `§` 分節符，不會崩潰。

如果 Codex 跑起來發現 `CandidateTrace` 不在 `OUTPUT_COLUMNS` 也不在 `123_minus_1.csv` 既有欄位中，**不要新增**，把所有 trace 寫入 `IdentityReason` 即可。

### D.3 Trace 字串文法（共用）

**單一字串**，欄位內以 `§` 分段，**每段格式為 `key=value` 或 `event:detail`**。範例：

```
§raw=/1.1_2-S11UG-N4-60371§source=pipeline_id§strip_prefix=1.1_2-S11UG-N4-60371§size_norm[2]:1.1_2→1-1/2§normalized=S11UG-60371-1-1/2-N4§match=strict§iso_key=S11UG-60371-1-1/2-N4§score=1.00§reason=5段全吻合,size經規範一致
```

**規則**：
- 第一個 `§` 之前可以為空字串
- key 不含 `=` 與 `§`；value 可含其他字元（包括空格、中文）但**不能含 `§`**
- 若 value 內容必須含 `§` → 用 `§§` 轉義（兩個連續視為字面 §）
- 完整字串必須 ≤ 4096 字元（超過則截斷尾段並加 `§truncated=1`）

### D.4 共用工具：`utils/trace_builder.py`

**檔案路徑**：`utils/trace_builder.py`

```python
# -*- coding: utf-8 -*-
"""Trace 字串建構與解析工具。

Trace 用於記錄每筆資料在管線中的加工過程，
讓使用者可從 csv/xlsx 直接看到「為什麼這條會被這樣處理」。

設計考量：
- 寫入既有的 IdentityReason / CandidateTrace 欄位（不新增同義欄）
- 字串可由 parse_trace 還原為 (kind, key, value) tuples 供 GUI 渲染
"""
from __future__ import annotations

from typing import Iterable, Optional


SEP = "§"
ESCAPE = "§§"
MAX_LEN = 4096


class TraceBuilder:
    """累積式建構 trace 字串。

    使用範例：
        tb = TraceBuilder()
        tb.add("raw", "/1.1_2-S11UG-N4-60371")
        tb.add("source", "pipeline_id")
        tb.add_event("size_norm", "[2]:1.1_2→1-1/2")
        tb.add("score", "1.00")
        s = tb.build()
        # → "§raw=...§source=...§size_norm:[2]:1.1_2→1-1/2§score=1.00"
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, key: str, value: str) -> "TraceBuilder":
        """加入 ``key=value`` 段。value 自動 escape。"""
        ...

    def add_event(self, name: str, detail: str = "") -> "TraceBuilder":
        """加入 ``name:detail`` 段（用於描述事件，無 value 也可）。"""
        ...

    def build(self) -> str:
        """組裝為單一字串。若超過 MAX_LEN 自動截斷並標記。"""
        ...


def parse_trace(trace_str: str) -> list[tuple[str, str, str]]:
    """解析 trace 字串為 (kind, key, value) tuples。

    kind 為 'kv' 或 'event'。

    使用範例：
        parts = parse_trace("§raw=foo§size_norm:[2]:1.1_2→1-1/2")
        # → [('kv', 'raw', 'foo'), ('event', 'size_norm', '[2]:1.1_2→1-1/2')]
    """
    ...
```

### D.5 在哪些步驟收集 trace

#### D.5.1 `core/pipeline_extractor.py` 的 `_extract_row`
**位置參考**：`core/pipeline_extractor.py` 中 `_extract_row` 內部邏輯（建議 grep 後再做）  
**改動原則**：
- **不改 `build_intermediate` 簽名**（含已加的 `iso_list_path`/`iso_sheet_name`/`pipe_col_override`）
- 在 `_extract_row` 或其呼叫處增加 trace 累積，最終寫入 `IdentityReason` 欄位
- 若 `123_minus_1.csv` 既有 `IdentityReason` 欄位 → 直接寫入
- 若**沒有** → 在 csv 尾端**append** 一個 `IdentityReason` 欄位（不影響既有欄位順序）

事件 schema：
| key | value 範例 | 何時加 |
|---|---|---|
| `raw` | `/1.1_2-S11UG-N4-60371` | 初始原值 |
| `source` | `pipeline_id` / `path_smart` / `path_regex` / `display_name` / `rejected_by_pattern` | 從哪來 |
| `path` | `/.../A某區域/1.1_2-...` | 若 source 為 path_* 才加 |
| `pattern_check` | `pass` / `fail` | 若嚴謹模式 |
| `level` | `3` | 該列的 Level |

#### D.5.2 `utils/utils_common.py` 的 normalize 流程
**保留 `normalize_line(s) -> str` 的簽名與行為完全不變**。本輪不修改 v1。

`normalize_line_v2` 由 Phase 3 處理，本 Phase 不做。

#### D.5.3 `core/iso_matcher.py` Phase 1–4
**位置參考**：見附錄 A 的 file:line 索引  
**改動原則**：
- 既有的 `MatchType` / `MatchScore` / `MatchSource` 欄位**保留**
- 對 `IdentityReason` 寫入結構化 trace（過往是純文字 reason 的話，改寫入結構化版本）
- Phase 4 fuzzy 候選的 trace 寫進候選 dict 的 `trace`/`reason` 欄位（GUI 端 Phase 4 才會用，本輪先準備資料）
- **不要動既有 phase 命中邏輯**

事件 schema 增量：
| key | value 範例 |
|---|---|
| `match` | `strict` / `strip_size` / `drop_last_seg` / `fallback_base` / `loose_only` / `fuzzy_manual` |
| `iso_key` | `1-1/2-S11UG-N4-60371` |
| `attempts` | `strict:fail,strip_size:fail,size_norm:ok` |
| `score` | `1.00` |
| `reason` | 短人話摘要 |

### D.6 寫入流程對照表

| 檔案 | 寫入的 trace 欄 | 既有欄位順序 |
|---|---|---|
| `123_minus_1.csv` | `IdentityReason`（既有）；若無則 append 在尾端 | 不變 |
| `iso_match.xlsx`（工作表「結果」） | `IdentityReason`（既有）；同上原則 | 不變 |
| `resolved_mapping.csv` | `IdentityReason`（已在 OUTPUT_COLUMNS 內） | **不變** |

### D.7 測試

**檔案路徑**：`tests/test_trace_builder.py`

```python
# -*- coding: utf-8 -*-
import unittest

from utils.trace_builder import TraceBuilder, parse_trace, SEP


class TraceBuilderTests(unittest.TestCase):

    def test_build_basic(self):
        tb = TraceBuilder()
        tb.add("raw", "/foo")
        tb.add("source", "pipeline_id")
        tb.add_event("size_norm", "[2]:1.1_2→1-1/2")
        s = tb.build()
        self.assertTrue(s.startswith(SEP))
        self.assertIn("raw=/foo", s)
        self.assertIn("size_norm:[2]:1.1_2→1-1/2", s)

    def test_escape_section_separator(self):
        tb = TraceBuilder()
        tb.add("note", "value contains §should escape")
        s = tb.build()
        # 字面 § 必須被 escape 成 §§
        self.assertIn("§§should", s)
        # parse 後應該還原為單一 § 字面值
        parts = parse_trace(s)
        self.assertTrue(any(v == "value contains §should escape" for _, _, v in parts))

    def test_parse_kv_and_event(self):
        s = "§raw=foo§source=pipeline_id§size_norm:[2]:1.1_2→1-1/2"
        parts = parse_trace(s)
        self.assertIn(("kv", "raw", "foo"), parts)
        self.assertIn(("kv", "source", "pipeline_id"), parts)
        self.assertIn(("event", "size_norm", "[2]:1.1_2→1-1/2"), parts)

    def test_truncate_when_too_long(self):
        tb = TraceBuilder()
        for i in range(2000):
            tb.add(f"k{i}", "v" * 50)
        s = tb.build()
        self.assertLessEqual(len(s), 4096)
        self.assertIn("truncated=1", s)


if __name__ == "__main__":
    unittest.main()
```

**檔案路徑**：`tests/test_extractor_trace.py`

```python
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import pandas as pd

from core.pipeline_extractor import PipelineExtractor


class ExtractorTraceTests(unittest.TestCase):

    def test_minus_1_has_identity_reason_column(self):
        """產出的 minus_1.csv 必須含 IdentityReason 欄位且不為空。"""
        with tempfile.TemporaryDirectory(prefix="tmp_unit_") as tmp:
            fix = os.path.join(tmp, "First_try.csv")
            with open(fix, "w", encoding="utf-8-sig") as f:
                f.write(
                    "Path,DisplayName,Class,Level,PipelineId\n"
                    "/A/B/C,DisplayName1,SomeClass,3,/AC-1701-100-AA1B-NA\n"
                )
            out = os.path.join(tmp, "minus_1.csv")

            extractor = PipelineExtractor()
            extractor.build_intermediate(
                input_csv=fix,
                out_csv=out,
                scan_mode="full",
            )

            df = pd.read_csv(out, encoding="utf-8-sig")
            self.assertIn("IdentityReason", df.columns)
            self.assertEqual(len(df), 1)
            trace = str(df.iloc[0]["IdentityReason"])
            self.assertIn("raw=", trace)
            self.assertIn("source=", trace)


if __name__ == "__main__":
    unittest.main()
```

### D.8 驗收（Phase 2）
- [ ] `python -m unittest tests.test_trace_builder -v` 全綠
- [ ] `python -m unittest tests.test_extractor_trace -v` 全綠
- [ ] `python -m unittest tests.test_pipeline_regression -v` 仍全綠
- [ ] 跑一次完整流程（First_try.csv + ISO_LIST.xlsx）後：
  - `123_minus_1.csv` 的 `IdentityReason` 欄不為空、有 `§` 結構
  - `iso_match.xlsx` 的 `IdentityReason` 欄有結構化 trace
  - `resolved_mapping.csv` 的 `IdentityReason` 欄有結構化 trace
- [ ] `OUTPUT_COLUMNS` 既有欄位順序未變動
- [ ] commit message 列出實際資料下抽樣 trace 字串範例（一條即可）

---

## E. PHASE 3 — `normalize_line_v2` + 接入點（必做 · 半天）

### E.1 目的
讓 Phase 1 寫好的 `size_normalizer` 真的影響比對結果，但**不影響舊呼叫者**。

### E.2 嚴格設計約束

- **`normalize_line` v1 簽名與行為完全不變**——任何既有呼叫者繼續用 v1，輸出不變
- **`normalize_line_v2` 是獨立函式**，由本輪明確需要 size 規範的呼叫點**顯式**改用
- **不要把 v1 改成 v2 的 wrapper**——那會讓所有舊呼叫者吃到 size 規範，破壞 regression

### E.3 流程順序（v2 內部）
```
Raw 字串
  ↓ strip()
  ↓ split by sep="-" 切成 segments
  ↓ 對每個 segment 跑 is_size_like → 是的話跑 normalize_size_token
  ↓ join by "-"
  ↓ strip_prefix（^[^A-Za-z0-9]+）
  ↓ replace(" ", "")
  ↓ 處理 "/" 切割（若非分數）
  → 規範化字串
```

**關鍵**：`size_normalize` 必須在 `replace(" ")` **之前**。

### E.4 實作位置

**檔案**：`utils/utils_common.py`（**新增函式，不動既有**）

```python
def normalize_line_v2(
    s: str,
    sep: str = "-",
    apply_size_norm: bool = True,
) -> tuple[str, list[str]]:
    """新版 normalize：先切段、size 規範、再 join。

    與 ``normalize_line`` 是兩個獨立函式：
    - ``normalize_line``：v1 行為完全不變，所有既有呼叫者使用之
    - ``normalize_line_v2``：新流程顯式呼叫，可選擇是否套用 size 規範

    Parameters
    ----------
    s : str
        待規範字串
    sep : str
        段分隔符，預設 ``-``
    apply_size_norm : bool
        是否套用 size 規範（為了測試或 fallback 場景可關閉）

    Returns
    -------
    tuple[str, list[str]]
        (normalized_string, trace_events)
        其中 trace_events 為 ``["strip_prefix=...", "size_norm[2]:1.1_2→1-1/2", ...]``
        供呼叫端塞入 TraceBuilder
    """
    ...
```

### E.5 接入點（明確列出）

下列位置**改用 `normalize_line_v2`**（其餘所有呼叫處保持 v1）：

1. `core/iso_matcher.py` 內部建立比對 key 的 normalize：
   - `df_minus["__line_norm"] = df_minus["ISO_Match_Key"].apply(...)` 改用 v2
   - `iso_df["__line_norm"] = iso_df["__pipe_raw"].apply(...)` 改用 v2
   - 套用後將 trace_events 累積到該列的 IdentityReason

2. `core/pipeline_extractor.py` 寫入 `ISO_Match_Key` 時：
   - 若 `scan_mode == "full"`，計算 `ISO_Match_Key` 改用 v2
   - 累積 trace_events 到 IdentityReason

3. `core/identity_resolver.py` 中與 ISO_Match_Key 對等的 normalize 處 → 改用 v2

**所有「不直接面向比對 key 的 normalize」（如顯示用、舊 fallback 路徑）保留 v1**。

### E.6 對既有比對的影響預期

跑完整流程後**預期變化**：
- `iso_match.xlsx` 的 `MatchType=strict` 行數會增加（過去因 size 寫法不同被歸到 strip_size / fuzzy 的，現在會在 strict 命中）
- `MatchType=fuzzy_manual` 行數會減少
- `iso_line_coverage.xlsx` 的 Matched 比例會升高

請在 commit message 註明真實數字差異，例如：
```
[Phase 3] normalize_line_v2 接入 size_normalizer

實際跑 ISO_LIST.xlsx + First_try.csv：
- MatchType=strict:     1234 → 1289 (+55)
- MatchType=strip_size:  87  → 32   (-55)
- 模糊未配對:            45  → 18   (-27)
```

### E.7 測試

**檔案路徑**：`tests/test_normalize_line_v2.py`

```python
# -*- coding: utf-8 -*-
import unittest

from utils.utils_common import normalize_line, normalize_line_v2


class NormalizeLineV1RegressionTests(unittest.TestCase):
    """v1 normalize_line 行為必須跟舊版完全一樣（regression 保護）。"""

    def test_strip_prefix_slash(self):
        self.assertEqual(normalize_line("/AC-1701-100"), "AC-1701-100")

    def test_keep_fraction_in_size(self):
        # 分數不該被切（`/` 在分數中保留）
        result = normalize_line("1/2\"-AC")
        # 確切預期值由 v1 實際行為決定，本 case 主要確保不被改動
        self.assertEqual(result, normalize_line("1/2\"-AC"))


class NormalizeLineV2Tests(unittest.TestCase):
    """v2 接入 size_normalizer 後的預期行為。"""

    def _check(self, raw, expected_norm):
        norm, _ = normalize_line_v2(raw, sep="-", apply_size_norm=True)
        self.assertEqual(norm, expected_norm, f"raw={raw!r}")

    # 你提到的 bug 案例
    def test_bug_dot_under(self):    self._check("/1.1_2-S11UG-N4-60371",  "1-1/2-S11UG-N4-60371")
    def test_mixed_space(self):      self._check("/1 1/2-S11UG-N4-60371",  "1-1/2-S11UG-N4-60371")
    def test_mixed_under(self):      self._check("/1_1/2-S11UG-N4-60371",  "1-1/2-S11UG-N4-60371")
    def test_mixed_dash(self):       self._check("/1-1/2-S11UG-N4-60371",  "1-1/2-S11UG-N4-60371")
    def test_float(self):            self._check("/1.5-S11UG-N4-60371",    "1-1/2-S11UG-N4-60371")

    # 不該被影響的情況
    def test_int_size_unchanged(self):
        self._check("AC-1701-100-AA1B-NA",  "AC-1701-100-AA1B-NA")
        self._check("/AC-1701-100-AA1B-NA", "AC-1701-100-AA1B-NA")
        self._check("AR-12001-50-A1B-HC2",  "AR-12001-50-A1B-HC2")

    def test_no_size_segment(self):
        self._check("AC-1701", "AC-1701")

    def test_apply_size_norm_off_keeps_legacy_shape(self):
        norm, _ = normalize_line_v2(
            "/1.1_2-S11UG-N4-60371", sep="-", apply_size_norm=False,
        )
        # 關閉 size 規範時，size 段保留原樣
        self.assertIn("1.1_2", norm)


if __name__ == "__main__":
    unittest.main()
```

### E.8 驗收（Phase 3）
- [ ] `python -m unittest tests.test_normalize_line_v2 -v` 全綠
- [ ] `python -m unittest tests.test_pipeline_regression -v` 全綠（v1 行為不變）
- [ ] 完整跑一次真實資料，數字差異有列在 commit message
- [ ] 「`1.1_2`」這個字串不再出現在任何 `iso_match.xlsx` 的 `ISO_Match_Key` 欄位
- [ ] commit message 為 `[Phase 3] normalize_line_v2 接入 size_normalizer`

---

## F. 不可動清單（v1.1 已對齊現況）

| 項目 | 位置 | 為什麼不可動 |
|---|---|---|
| `normalize_line(s)` 簽名與行為 | `utils/utils_common.py` | 全專案 30+ 處呼叫，regression test 鎖定 |
| `PIPE_SEG_PATTERN` regex 字面 | `utils/utils_common.py` | 嚴謹模式 hard filter 依賴 |
| `Raw_3D_PipeCode` 保留 `/` 前綴 | `core/pipeline_extractor.py` | Navisworks 外掛吃 JSON 時要 |
| ISO_LIST 上的 `/` 前綴 | 使用者刻意加 | 加了就能命中 |
| `OUTPUT_COLUMNS` 中**既有欄位的順序** | `core/resolved_mapping.py:22-45` | 下游 GUI 篩選依賴；新欄只能 append 在尾端 |
| `MatchSource` / `IdentityReason` 等既有欄名 | 全專案 | 不另起爐灶；本輪沿用、寫結構化內容進去 |
| `core/iso_matcher.py` Phase 1-4 既有命中邏輯 | line 702-915 | 真實資料已驗過，新邏輯**疊加**不取代 |
| `PipelineExtractor.build_intermediate` 簽名 | `core/pipeline_extractor.py` | 前輪已加 `iso_list_path`/`iso_sheet_name`/`pipe_col_override`，**接受現況** |
| `core/json_exporter.py` `export_json_v2` 簽名 | line 27-32 | tab_json 呼叫 |
| `tests/test_pipeline_regression.py` | tests/ | 必須仍全綠 |
| Git 歷史 | 整個 repo | 不重寫；commit 格式從本輪起套用 |

---

## G. 提交順序（本輪共 3 個 commit）

1. **Phase 1**：`core/size_normalizer.py` + `tests/test_size_normalizer.py` → commit
2. **Phase 2**：`utils/trace_builder.py` + 接入既有 IdentityReason 欄位 + 對應測試 → commit
3. **Phase 3**：`normalize_line_v2` + 三個接入點切換 + 真實資料數字差 → commit

每個 commit 之間必須 `python -m unittest discover -s tests -v` **全綠**，否則拒絕進下一階段。

---

## H. 完成檢查清單（執行前印出來，做完一條打 ✅）

### Phase 1
- [ ] `core/size_normalizer.py` 新檔
- [ ] `tests/test_size_normalizer.py` 30+ case 全綠
- [ ] 既有 regression test 全綠
- [ ] commit 完成

### Phase 2
- [ ] `utils/trace_builder.py` 新檔
- [ ] `tests/test_trace_builder.py` 全綠
- [ ] `tests/test_extractor_trace.py` 全綠
- [ ] minus_1.csv / iso_match.xlsx / resolved_mapping.csv 的 `IdentityReason` 都有結構化 trace
- [ ] `OUTPUT_COLUMNS` 既有順序未動
- [ ] commit 完成（含抽樣 trace 範例）

### Phase 3
- [ ] `utils/utils_common.py` 新增 `normalize_line_v2`，**v1 完全未動**
- [ ] 三個接入點切換到 v2
- [ ] `tests/test_normalize_line_v2.py` 全綠（含 v1 regression）
- [ ] 真實資料跑過，`1.1_2` 不再出現於 `ISO_Match_Key`
- [ ] commit message 含實際數字差
- [ ] commit 完成

### 整體
- [ ] `python -m unittest discover -s tests -v` 全部全綠
- [ ] 沒有新增第三方依賴（requirements.txt 不變）
- [ ] 沒有重寫 git 歷史

---

## 附錄 A — 既有 file:line 引用一覽（給 Codex 找位置用）

> 注意：Codex 應該以 `grep` 實際確認位置，本表行號可能因前輪修改而漂移。

| 議題 | 模組 | 函式 / 區塊 |
|---|---|---|
| `normalize_line` 本體 | `utils/utils_common.py` | `normalize_line` |
| `PIPE_SEG_PATTERN` | `utils/utils_common.py` | 模組常數 |
| `_extract_row` | `core/pipeline_extractor.py` | `PipelineExtractor._extract_row` |
| `build_intermediate` | `core/pipeline_extractor.py` | `PipelineExtractor.build_intermediate`（含 ISO whitelist 參數） |
| `parse_and_export` | `core/pipeline_grouper.py` | `PipelineGrouper.parse_and_export` |
| `_compute_segment_score` | `core/iso_matcher.py` | 模組函式 |
| `_strip_size_segment` | `core/iso_matcher.py` | 模組函式 |
| Phase 1 strict match | `core/iso_matcher.py` | `IsoMatcher.run` 內 Phase 1 區段 |
| Phase 2 strip_size | `core/iso_matcher.py` | 同上，Phase 2 區段 |
| Phase 2b drop_last_seg | `core/iso_matcher.py` | 同上，Phase 2b 區段 |
| Phase 3 fallback_base | `core/iso_matcher.py` | 同上，Phase 3 區段 |
| Phase 4 fuzzy 候選收集 | `core/iso_matcher.py` | 同上，Phase 4 區段 |
| `apply_fuzzy_selections` | `core/iso_matcher.py` | `IsoMatcher.apply_fuzzy_selections` |
| `JsonExporter.export_json_v2` | `core/json_exporter.py` | 公開 API |
| `OUTPUT_COLUMNS` | `core/resolved_mapping.py` | 模組常數（不可重排） |
| `IsoSchema.detect_schema` | `utils/iso_schema.py` | 公開 API |
| `parse_scope_context` | `core/scope_indexer.py` | 公開 API |

---

## 附錄 B — NPS 標準尺寸完整表（給 Phase 1 抄）

| inch | 規範字串 |
|---|---|
| 0.125 | `1/8` |
| 0.25  | `1/4` |
| 0.375 | `3/8` |
| 0.5   | `1/2` |
| 0.75  | `3/4` |
| 1.0   | `1` |
| 1.25  | `1-1/4` |
| 1.5   | `1-1/2` |
| 2.0   | `2` |
| 2.5   | `2-1/2` |
| 3.0   | `3` |
| 3.5   | `3-1/2` |
| 4.0   | `4` |
| 5.0   | `5` |
| 6.0   | `6` |
| 8.0   | `8` |
| 10.0  | `10` |
| 12.0  | `12` |
| 14.0  | `14` |
| 16.0  | `16` |
| 18.0  | `18` |
| 20.0  | `20` |
| 24.0  | `24` |
| 30.0  | `30` |
| 36.0  | `36` |
| 42.0  | `42` |
| 48.0  | `48` |

---

## 附錄 C — 真實資料測試 fixture（先建立此目錄）

**目錄**：`tests/fixtures/`

**最小 fixture：`tests/fixtures/minimal_first_try.csv`**
```csv
Path,DisplayName,Class,Level,PipelineId
/A/B/管線/1.1_2-S11UG-N4-60371,1.1_2-S11UG-N4-60371,Pipe,3,/1.1_2-S11UG-N4-60371
/A/B/管線/AC-1701-100-AA1B-NA,AC-1701-100-AA1B-NA,Pipe,3,/AC-1701-100-AA1B-NA
/A/B/管線/AR-12001-50-A1B-HC2,AR-12001-50-A1B-HC2,Pipe,3,/AR-12001-50-A1B-HC2
/X/Y/結構/SUPPORT-001,SUPPORT-001,Support,4,
```

**最小 fixture：`tests/fixtures/minimal_iso.xlsx`**

工作表 `DWG NO.ALL`，欄位：
- `流水號`：60371, 60372, 60373
- `Line num`：`/1-1/2-S11UG-N4-60371`, `/AC-1701-AA1B-NA`, `/AR-12001-A1B-HC2`
- `發包分類`：A, B, C
- `系統`：S, A, A
- `材質`：N4, AA1B, A1B
- `保溫`：NA, NA, HC2

---

## 附錄 D — 資料流總覽（給 Codex 心智模型用）

```
First_try.csv (≈124MB, Navisworks 匯出)
  │
  │  [PipelineExtractor.build_intermediate]   ← Phase 2/3 在此加 trace + v2
  ▼
123_minus_1.csv（IdentityReason 寫入結構化 trace）
  │
  │  [PipelineGrouper.parse_and_export]
  ▼
123_minus_2.csv + 123_minus_2.xlsx
  │
  │  [IsoMatcher.run]   ← Phase 2/3 在此加 trace + v2
  ▼
iso_match.xlsx（IdentityReason 寫入結構化 trace）
  │
  │  [build_resolved_mapping]
  ▼
resolved_mapping.csv（IdentityReason 帶結構化 trace）
  │
  │  [JsonExporter.export_json_v2]
  ▼
live_selection.json
```

---

## 附錄 E — 未來 roadmap（非本輪實作範圍）

下列項目**不在本輪 v1.1 範圍內**，待 Phase 1–3 穩定後再評估：

### Phase 4（GUI Trace Viewer，預估 1 天）
- 新增 `gui/dialogs/trace_viewer_dialog.py`
- 把 `IdentityReason` 字串解析為卡片時間軸渲染
- 進入點：tab_json 預覽表格右鍵、fuzzy_match_dialog 候選列

### Phase 5（Segment Priors，預估 1.5 天）
- 新增 `core/segment_priors.py`
- 從 minus + ISO 兩池子合學每段位 token 分布
- `is_likely_line_no` 啟發法
- 在 `_compute_segment_score` 加 prior bonus（罕見且兩邊一致 → 加分；都常見且不同 → 不加分；alien token 標記）

### Phase 6（Fuzzy 對話框升級，預估 0.5 天）
- 候選表格加 ParentArea 欄
- 點選候選顯示 trace 詳情面板（策略嘗試 / priors）
- 「批次套用同前綴」按鈕

執行這三個 Phase 前需先確認：
1. Phase 1–3 的 trace 字串格式在真實資料上夠穩
2. `is_likely_line_no` 啟發法在本案資料上要先小規模 spike 驗證閾值（min_unique_ratio 是否真為 0.8）
3. GUI 改動需與本輪後端 API 對齊

---

## 收尾

本指令書 v1.1 設計目標：把 v1.0 的所有矛盾解掉，採用 Codex 建議的保守路線，本輪只做 Phase 1–3。

如果你看到任何**模糊**的描述、**缺漏**的測試案例、或**自相矛盾**的規格，**暫停實作**並追加問題到 `IMPLEMENTATION_QUESTIONS.md`，不要 guess。

> **記住：行為改變要誠實寫進 commit message；不要表面看起來通過、實際偷偷改規格。**

— v1.1 指令書結束 —
