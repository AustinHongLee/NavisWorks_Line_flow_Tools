"""集中管理 GUI 說明文字 / 註解內容。

目前使用者：
- `run_pipeline_gui.PipelineGUI._show_minus_help` 使用 `ISO_MINUS_HELP`。

給開發者看的欄位語意說明：
- `RAW_LAST_DESC` 與 `LINE_COMBINED_DESC` 主要給程式維護者閱讀，
   協助理解 Raw_3D_PipeCode / ISO_Match_Key 的真正用途與推薦語意名稱。

未來若有其他 GUI / CLI 需要共用說明文字，
請在此新增常數，並在這裡標註「誰在用」。
"""


ISO_MINUS_HELP = """
【整體流程】
1. 管線抽取：從 First_try 的 Path/Level 中挑出與『管線』相關的節點，
   產生中繼檔 123_minus_1.csv，並計算每一列的 Raw_3D_PipeCode。

2. 群組整理：在 123_minus_1 基礎上推導出管線段，
   再經過標準化得到 ISO_Match_Key，輸出 123_minus_2.csv / 123_minus_2.xlsx。

3. ISO 比對：以 123_minus_2 的 ISO_Match_Key / Raw_3D_PipeCode，
   去對應 ISO LIST.ALL 裡的管線編號與流水號，輸出 iso_match.xlsx。

【Raw_3D_PipeCode 是什麼？】
- 由 Path 以分隔符（預設 ___）切開後，取最後一段（或指定 Level 的節點）作為 3D 身分證。
- 若勾選『Raw_3D_PipeCode 前面加 "/"』，會強制以 / 開頭，例如 /AREA-PIPE-001。
- 這就是 Navisworks 中 3D 物件的原始管線識別碼，ISO 比對以此為依據。

【ISO_Match_Key 是什麼？】
- 把 Raw_3D_PipeCode 做一層標準化（大小寫、空白、符號），
  讓相同管線即使在表現形式略有差異，也能比對到同一條 ISO。
- 若 ISO_Match_Key 與 ISO 清單中的管線編號（標準化後）一致，就算比到了。
- 若比對失敗，可以對照 ISO_Match_Key 與 ISO 清單的管線編號，
  找出格式差異（多了段、少了段、大小寫、符號等）。

【ISO 比對如何使用這些欄位？】
- 先從 ISO LIST.ALL 讀出『管線欄位名』（例：管線編號或含 line 的欄位），
  對該欄位做同樣的標準化，得到 ISO 端的 line_norm。
- 再用 123_minus_2 中的 ISO_Match_Key 與 ISO 端的 line_norm 做一對一比對。
- 若完全比不到，會退一步只比對『去掉尾巴流水號』的管線基底（例如去掉 -001）。

【這一頁的 ISO 設定在做什麼？】
- ISO 檔案：指定或讓程式在專案資料夾底下自動尋找 ISO LIST.ALL*.xlsx。
- ISO 工作表：選擇實際存放管線清單的 sheet（常見為 DWG NO.ALL）。
- 管線欄位名：ISO 裡用來表示管線編號的欄位，例如『管線編號』或其他含 line 的欄位。
- 流水號欄位名：ISO 裡用來表示 spool / 流水號的欄位，例如『流水號』、『Spool』。
- 分類欄位名：例如『發包分類』，後續可以當成 JSON 的 header 或篩選條件。

【建議操作順序】
1. 先確認 123_minus_2 已成功產生，再回到這一頁設定 ISO。
2. 點『選 ISO 檔...』與『ISO 工作表』，檢查下方三個欄位是否自動帶入正確名稱。
3. 若專案的欄位命名不同，可自行從下拉選單中改成正確欄位。
4. 全部設定完成後，再執行上方的『執行管線抽取 / 群組整理 / ISO 比對』或
   『只執行 ISO 比對（已完成 123_minus_2）』。
"""


# ---- 給開發者的欄位語意說明 ----

RAW_LAST_DESC = """
Raw_3D_PipeCode（舊名：Raw_last）：
- 從 First_try 的 Path 或指定 Level 抓出的「原始 3D 身分證」字串。
- 幾乎不做加工，最多只會依勾選決定前面要不要加 "/"。
- 語意理解為：pipeline_id_raw（原始管線 ID / Navisworks 原始身分證）。
"""


LINE_COMBINED_DESC = """
ISO_Match_Key（舊名：Line_combined）：
- 由管線段推導而來，再做大小寫、空白、符號等正規化。
- 目的是把「看起來長得差不多的管線編號」收斂成同一個 key，方便和 ISO 清單比對。
- 語意理解為：pipeline_id_norm / ISO 比對用標準化管線鍵。
"""

