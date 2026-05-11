# -*- mode: python ; coding: utf-8 -*-
r"""PyInstaller spec for the Navisworks line-flow helper GUI.

Build with:
    .\scripts\build_exe.ps1
"""

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)
ENTRYPOINT = PROJECT_ROOT / "run_pipeline_gui_qt.py"

block_cipher = None

hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "pandas",
    "openpyxl",
    "dateutil",
    "tzdata",
]

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "pygments",
        "pluggy",
        "iniconfig",
        "colorama",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NavisWorks_Line_flow_Tools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
