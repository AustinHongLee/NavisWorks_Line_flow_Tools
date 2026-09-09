# -*- mode: python ; coding: utf-8 -*-
r"""PyInstaller spec for the Navisworks line-flow helper GUI.

Build with:
    .\scripts\build_exe.ps1
"""

from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)
ENTRYPOINT = PROJECT_ROOT / "run_pipeline_gui_qt.py"
BRAND_DIR = PROJECT_ROOT / "assets" / "branding"
APP_ICON_PNG = BRAND_DIR / "ie_mark_v2.png"
APP_ICON_ICO = BRAND_DIR / "pipeline_ops_v2.ico"
STARTUP_SPLASH = BRAND_DIR / "startup_splash_v2.png"
WORKFLOW_ART_DIR = PROJECT_ROOT / "assets" / "ui" / "workflow"
WORKFLOW_ART_FILES = (
    "project-intake.png",
    "iso-matching.png",
    "json-export.png",
    "audit-trace.png",
)
VERSION_INFO = BRAND_DIR / "windows_version_info_v4.txt"

block_cipher = None

hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "pandas",
    "openpyxl",
    "dateutil",
    "tzdata",
]

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(APP_ICON_PNG), "assets/branding"),
        (str(STARTUP_SPLASH), "assets/branding"),
    ] + [
        (str(WORKFLOW_ART_DIR / filename), "assets/ui/workflow")
        for filename in WORKFLOW_ART_FILES
    ],
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

# Qt6Core on Windows links against the unversioned ICU shim provided by the
# operating system.  Some developer shells add Poppler to PATH; PyInstaller
# can then mistake Poppler's version-suffixed ICU 78 binaries for that shim.
# They have incompatible exports (for example ``ucnv_open_78`` instead of
# ``ucnv_open``), which makes the packaged app fail while importing QtCore.
a.binaries = [
    item
    for item in a.binaries
    if Path(item[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
]
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

splash = Splash(
    str(STARTUP_SPLASH),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(56, 326),
    text_size=11,
    text_color="#52697F",
    text_default="正在啟動，請稍候…",
    always_on_top=False,
    minify_script=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
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
    icon=str(APP_ICON_ICO),
    version=str(VERSION_INFO),
)
