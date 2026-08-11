# -*- coding: utf-8 -*-
"""Public GUI exports without paying MainWindow's import cost up front."""
from __future__ import annotations

from typing import TYPE_CHECKING

from gui.theme import Theme, DEFAULT_THEME
from gui.stylesheet import build_stylesheet

if TYPE_CHECKING:
    from gui.main_window import MainWindow


def __getattr__(name: str):
    if name == "MainWindow":
        from gui.main_window import MainWindow

        globals()[name] = MainWindow
        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Theme",
    "DEFAULT_THEME",
    "build_stylesheet",
    "MainWindow",
]
