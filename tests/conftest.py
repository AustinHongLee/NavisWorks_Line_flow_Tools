"""Shared Qt teardown for the offscreen GUI regression suite."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _flush_qt_deferred_deletes():
    """Prevent closed top-level widgets from accumulating between tests."""

    yield
    app = QApplication.instance()
    if app is None:
        return
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
