# -*- coding: utf-8 -*-
"""管線流程工具 v4 — 入口點。

EXE 打包命令：
    .\\scripts\\build_exe.ps1

Navisworks 插件啟動範例：
    NavisWorks_Line_flow_Tools.exe --dlldir "C:\\path\\to\\dll" --first-try "C:\\path\\to\\First_try.csv"
"""
from __future__ import annotations

import argparse
import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from gui import MainWindow, build_stylesheet


def main():
    parser = argparse.ArgumentParser(description="管線流程工具")
    parser.add_argument("--dlldir", default=None,
                        help="Navisworks 插件 DLL 所在目錄，作為工作區根目錄")
    parser.add_argument("--first-try", default=None,
                        help="Navisworks 匯出的 First_try CSV 檔案路徑")
    parser.add_argument("--smoke-test", action="store_true",
                        help=argparse.SUPPRESS)
    args, _unknown = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())
    app.setFont(QFont("Microsoft JhengHei UI", 10))

    window = MainWindow(
        dlldir=args.dlldir,
        first_try_source=getattr(args, "first_try", None),
    )
    window.show()
    if args.smoke_test:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(500, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
