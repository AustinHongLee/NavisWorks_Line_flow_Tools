@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

:: ── 一般使用優先啟動已驗證的正式 EXE ──
:: 開發者若要強制跑 source，可先設定 PIPELINE_OPS_SOURCE=1。
if /i not "%PIPELINE_OPS_SOURCE%"=="1" (
    if exist "dist\NavisWorks_Line_flow_Tools.exe" (
        echo [INFO] 啟動正式版本，請稍候啟動畫面...
        start "" /D "%~dp0dist" "%~dp0dist\NavisWorks_Line_flow_Tools.exe" %*
        exit /b 0
    )
)

:: ── 驗證 venv 是否正常（Google Drive 雲端佔位檔無法執行） ──
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe --version >nul 2>&1
    if !errorlevel! neq 0 goto :rebuild_venv
    .venv\Scripts\python.exe -c "import sys" >nul 2>&1
    if !errorlevel! neq 0 goto :rebuild_venv
)

:: ── 決定 Python 路徑 ──
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    set "PIP=.venv\Scripts\pip.exe"
    echo [INFO] 使用 .venv 虛擬環境
) else (
    set "PY=python"
    set "PIP=pip"
    echo [INFO] 使用系統 Python
)
goto :check_deps

:rebuild_venv
echo [WARN] .venv 損壞或為雲端佔位檔，正在重建...
rmdir /s /q .venv 2>nul
echo [INFO] 建立新的虛擬環境...
python -m venv .venv
if !errorlevel! neq 0 (
    echo [ERROR] 建立 venv 失敗，請確認系統已安裝 Python 3
    pause
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"
echo [INFO] 安裝依賴...
!PIP! install -r requirements.txt
if !errorlevel! neq 0 (
    echo.
    echo ===================================
    echo  依賴安裝失敗，請手動執行：
    echo  pip install -r requirements.txt
    echo ===================================
    pause
    exit /b 1
)
echo [INFO] venv 重建完成
goto :launch

:check_deps
:: ── 自動檢查 / 安裝依賴 ──
%PY% -c "import PyQt6" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 偵測到缺少 PyQt6，正在自動安裝依賴...
    %PIP% install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo ===================================
        echo  依賴安裝失敗，請手動執行：
        echo  %PIP% install -r requirements.txt
        echo ===================================
        pause
        exit /b 1
    )
    echo [INFO] 依賴安裝完成
)

:launch
:: ── 啟動 GUI ──
%PY% run_pipeline_gui_qt.py %*

if %errorlevel% neq 0 (
    echo.
    echo ===================================
    echo  啟動失敗，錯誤碼: %errorlevel%
    echo ===================================
    echo.
    pause
)
