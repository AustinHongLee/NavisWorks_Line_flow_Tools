# -*- coding: utf-8 -*-
"""管線流程工具 v4 — 入口點。

EXE 打包命令：
    .\\scripts\\build_exe.ps1

Navisworks 插件啟動範例：
    NavisWorks_Line_flow_Tools.exe --dlldir "C:\\path\\to\\dll" --first-try "C:\\path\\to\\First_try.csv"
"""
from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from gui import build_stylesheet


APP_ICON_PATH = (
    Path(__file__).resolve().parent / "assets" / "branding" / "ie_mark_v2.png"
)
STARTUP_SPLASH_PATH = (
    Path(__file__).resolve().parent
    / "assets"
    / "branding"
    / "startup_splash_v2.png"
)

_STARTUP_LOG_HANDLE = None


def _write_startup_log(handle, message: str) -> None:
    """Never let best-effort diagnostics become a startup failure."""

    if handle is None:
        return
    try:
        handle.write(message)
        handle.flush()
    except (OSError, ValueError):
        pass


def _install_startup_diagnostics():
    """Keep windowed-build failures observable without requiring a console."""

    global _STARTUP_LOG_HANDLE
    try:
        local_root = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
        if not local_root:
            return None
        log_dir = Path(local_root) / "PipelineOps" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "startup.log"
        handle = log_path.open("a", encoding="utf-8", buffering=1)
        _STARTUP_LOG_HANDLE = handle
        handle.write(
            f"\n[{datetime.now().astimezone().isoformat()}] "
            f"start frozen={bool(getattr(sys, 'frozen', False))} "
            f"args={sys.argv[1:]!r}\n"
        )
        faulthandler.enable(handle, all_threads=True)
    except Exception:
        return None

    def _exception_hook(exc_type, exc_value, exc_traceback):
        try:
            handle.write("Unhandled startup/runtime exception:\n")
            traceback.print_exception(
                exc_type,
                exc_value,
                exc_traceback,
                file=handle,
            )
            handle.flush()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None and "--smoke-test" not in sys.argv:
            try:
                QMessageBox.critical(
                    None,
                    "管線流程工具無法啟動",
                    f"啟動時發生錯誤。\n\n診斷紀錄：\n{log_path}",
                )
            except Exception:
                pass
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _exception_hook
    return handle


def _connect_boot_splash():
    """Connect to PyInstaller's pre-Python splash when running frozen."""

    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.update_text("正在載入操作介面…")
            return pyi_splash
    except (ImportError, ConnectionError, OSError, RuntimeError):
        pass
    return None


def _show_source_splash(app: QApplication) -> QSplashScreen | None:
    """Give source/fallback launches feedback before heavy GUI imports."""

    if not STARTUP_SPLASH_PATH.is_file():
        return None
    pixmap = QPixmap(str(STARTUP_SPLASH_PATH))
    if pixmap.isNull():
        return None
    splash = QSplashScreen(pixmap, Qt.WindowType.SplashScreen)
    splash.showMessage(
        "正在載入操作介面…",
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
        QColor("#52697F"),
    )
    splash.show()
    app.processEvents()
    return splash


def main() -> int:
    parser = argparse.ArgumentParser(description="管線流程工具")
    parser.add_argument("--dlldir", default=None,
                        help="Navisworks 插件 DLL 所在目錄，作為工作區根目錄")
    parser.add_argument("--first-try", default=None,
                        help="Navisworks 匯出的 First_try CSV 檔案路徑")
    parser.add_argument("--smoke-test", action="store_true",
                        help=argparse.SUPPRESS)
    args, _unknown = parser.parse_known_args()

    diagnostics = _install_startup_diagnostics()
    app = QApplication(sys.argv)
    app.setOrganizationName("Intelligent Engineering Co., Ltd.")
    app.setOrganizationDomain("intelligent-engineering.com.tw")
    app.setApplicationName("PipelineOps")
    if APP_ICON_PATH.is_file():
        app_icon = QIcon(str(APP_ICON_PATH))
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
    app.setStyleSheet(build_stylesheet())
    app.setFont(QFont("Microsoft JhengHei UI", 10))

    boot_splash = _connect_boot_splash()
    source_splash = None
    if not args.smoke_test and boot_splash is None:
        source_splash = _show_source_splash(app)

    # MainWindow pulls in pandas/openpyxl-backed workflow modules.  Import it
    # only after a splash is visible so a cold launch never looks like a miss.
    from gui.main_window import MainWindow

    if boot_splash is not None:
        try:
            boot_splash.update_text("正在建立專案工作區…")
        except (ConnectionError, OSError, RuntimeError):
            pass
    window = MainWindow(
        dlldir=args.dlldir,
        first_try_source=getattr(args, "first_try", None),
    )
    window.show()
    app.processEvents()
    if source_splash is not None:
        source_splash.finish(window)
    if boot_splash is not None:
        try:
            boot_splash.close()
        except (ConnectionError, OSError, RuntimeError):
            pass
    app.aboutToQuit.connect(window.shutdown)
    _write_startup_log(diagnostics, "main window shown\n")
    if args.smoke_test:
        QTimer.singleShot(500, app.quit)
    exit_code = app.exec()
    _write_startup_log(diagnostics, f"event loop exited code={exit_code}\n")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
