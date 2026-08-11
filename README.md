# 管線流程工具

Windows 桌面工具，用於整理 Navisworks 管線資料、比對 ISO LIST、產生 JSON，並保留可回查的判讀與稽核證據。

## 下載

前往 [GitHub Releases](https://github.com/AustinHongLee/NavisWorks_Line_flow_Tools/releases/latest) 下載最新版 `NavisWorks_Line_flow_Tools.exe`。這是免安裝的單檔程式，下載後可直接執行。

> 目前版本尚未使用程式碼簽章。Windows 第一次執行時可能顯示「未知發行者」警告；請確認檔案來自本專案的 Release 頁面。

## 主要功能

- 專案與 `First_try.csv` 來源設定
- ISO LIST 欄位辨識、管線／Spool 比對與候選判讀
- 模糊配對工作台、所有權衝突處理與可復原決策
- JSON 預覽、篩選、安全檢查與匯出
- 執行歷程、證據鏈與調查面板
- 長週期專案的本機 Run Capsule，可在數月後回看上次進度
- 高解析度品牌圖示、啟動畫面及按鈕互動回饋
- 有網路時安靜比對 GitHub 最新正式版，只在有新版時提示

## 使用方式

1. 執行 Release 內的 `NavisWorks_Line_flow_Tools.exe`。
2. 選擇專案資料夾並確認 `First_try.csv`。
3. 載入 ISO LIST，設定工作表與欄位。
4. 執行比對；需要人工確認的項目會進入配對工作台。
5. 確認預覽與安全提示後輸出 JSON。

若從原始碼目錄使用，也可以雙擊 `啟動管線工具.bat`；存在正式 EXE 時會優先啟動 EXE，否則才使用 `.venv`。

## 本機資料與隱私

專案執行紀錄會保存在該專案的 `.flowdesk/` 目錄，包含執行狀態、判讀事件與產物索引。這些資料不會被提交到本儲存庫；分享專案前仍建議自行檢查其中是否含內部路徑或工程資訊。

版本檢查只會讀取本專案 GitHub Release 的公開 manifest，不會上傳專案路徑或工程內容。若需完全停用，可在啟動前設定 `PIPELINE_OPS_DISABLE_UPDATE_CHECK=1`。

## 開發與驗證

需求：Windows、Python 3.12、PyQt6。

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\build_exe.ps1
```

建置腳本會產生單檔 EXE、執行隱藏 smoke test，並在 `dist/` 產生含 SHA-256 與來源 commit 的 manifest。
