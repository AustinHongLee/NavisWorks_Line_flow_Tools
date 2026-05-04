# -*- coding: utf-8 -*-
"""調查頁：跨中間檔查 ISO/3D 線索。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from core.identity_investigator import make_paths
from gui.dialogs.identity_inspector_dialog import IdentityInspectorWidget

if TYPE_CHECKING:
    from gui.main_window import MainWindow  # noqa: F401


class InvestigationTabMixin:
    """提供 MainWindow 的調查頁。"""

    def _build_page_investigation(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)

        self.identity_inspector = IdentityInspectorWidget(
            page,
            self._get_investigation_paths,
        )
        lay.addWidget(self.identity_inspector)
        self.pages.addWidget(page)

    def _get_investigation_paths(self):
        base = self._get_base_dir()
        first = self.txt_first_name.text().strip() or "First_try.csv"
        return make_paths(base, first)

    def open_identity_inspector(self, query: str) -> None:
        self._on_nav_clicked(3)
        self.identity_inspector.set_query(query)
