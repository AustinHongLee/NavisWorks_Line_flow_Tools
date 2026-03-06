# -*- coding: utf-8 -*-
"""Test: LevelDetectWorker + DetectProgressDialog integration."""
import sys, os, warnings
warnings.filterwarnings("ignore")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QEventLoop

app = QApplication(sys.argv)

# 1. Test imports
print("1. Testing imports...")
from gui.workers.detect_worker import LevelDetectWorker
from gui.dialogs.detect_progress_dialog import DetectProgressDialog
from gui.main_window import MainWindow
print("   imports: OK")

# 2. Test MainWindow creation
print("2. Creating MainWindow...")
w = MainWindow()
base = r"g:\我的雲端硬碟\Python_Tool-main\管線流程工具"
w.txt_base_dir.setText(base)
print(f"   iso_path: {os.path.basename(w.txt_iso_path.text())}")
print(f"   sheet: {w.cbo_iso_sheet.currentText()}")
print(f"   pipe_col: {w.cbo_pipe_col.currentText()}")

# 3. Test Worker standalone (with event loop for signals)
print("3. Testing LevelDetectWorker...")
results = []
logs = []
progress_updates = []

worker = LevelDetectWorker(
    base_dir=base,
    first_name="First_try.csv",
    iso_path=os.path.join(base, "ISO_LIST.xlsm"),
    sep="___",
    sheet="DRAWING LIST",
    pipe_col="Line_No",
)

loop = QEventLoop()
worker.progress.connect(lambda p, s: progress_updates.append((p, s)))
worker.log.connect(lambda l: logs.append(l))
worker.finished.connect(lambda ok, r: (results.append((ok, r)), loop.quit()))
worker.start()

# Timeout safety
QTimer.singleShot(60000, loop.quit)
loop.exec()

print(f"   progress updates: {len(progress_updates)}")
print(f"   log lines: {len(logs)}")
if results:
    ok, r = results[0]
    print(f"   success: {ok}")
    print(f"   level: {r.get('level')}")
    print(f"   confidence: {r.get('confidence')}")
    print(f"   best_sheet: {worker.best_sheet}")
    print(f"   pipe_col: {worker.detected_pipe_col}")
    print(f"   spool_col: {worker.detected_spool_col}")
    if progress_updates:
        print(f"   first progress: {progress_updates[0]}")
        print(f"   last progress: {progress_updates[-1]}")
else:
    print("   ERROR: no results!")

# 4. Test Dialog creation
print("4. Testing DetectProgressDialog...")
dlg = DetectProgressDialog()
dlg.on_progress(50, "Phase 2/3...")
dlg.on_log("test log line")
assert dlg.progress_bar.value() == 50
assert dlg.lbl_step.text() == "Phase 2/3..."
dlg.show_result_ok(1, 1.0, "test detail")
assert "Level = 1" in dlg.lbl_step.text()
print("   dialog: OK")

# Summary
all_ok = (
    len(results) == 1
    and results[0][0] is True
    and results[0][1].get("level") == 1
    and worker.best_sheet == "DRAWING LIST"
    and worker.detected_pipe_col == "Line_No"
    and worker.detected_spool_col == "Series NO"
    and len(progress_updates) > 5
)
print(f"\n=== {'ALL PASS' if all_ok else 'FAIL'} ===")
