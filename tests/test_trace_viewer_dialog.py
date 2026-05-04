# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QLabel
    from gui.dialogs.trace_viewer_dialog import TraceViewerDialog
except ModuleNotFoundError:  # pragma: no cover - depends on local GUI runtime
    QApplication = None
    QLabel = None
    TraceViewerDialog = None


class TraceViewerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest("PyQt6 不在目前測試 runtime 中")
        cls._app = QApplication.instance() or QApplication([])

    def test_trace_viewer_renders_groups(self):
        trace = (
            "§raw=/foo§source=pipeline_id"
            "§size_norm[0]:1.1_2→1-1/2"
            "§match=strict§score=1.00§reason=ok"
        )
        dlg = TraceViewerDialog(None, "42", "foo", trace)
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        self.assertIn("來源", labels)
        self.assertIn("規範化", labels)
        self.assertIn("比對", labels)
        self.assertIn("評分", labels)


if __name__ == "__main__":
    unittest.main()
