# -*- coding: utf-8 -*-
"""管線流程工具 v4 — 入口點。

EXE 打包命令（PyInstaller）：
    pyinstaller --onefile --windowed --name="管線流程工具" ^
        --add-data="pipeline_config.json;." ^
        run_pipeline_gui_qt.py
"""
from __future__ import annotations

import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from gui import MainWindow, build_stylesheet


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())
    app.setFont(QFont("Microsoft JhengHei UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()