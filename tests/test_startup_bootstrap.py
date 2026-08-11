from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtGui import QImage


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_gui_package_does_not_eagerly_import_the_heavy_main_window():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, gui; "
                "assert 'gui.main_window' not in sys.modules; "
                "assert callable(gui.build_stylesheet)"
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_startup_splash_is_a_valid_compact_png():
    path = REPO_ROOT / "assets" / "branding" / "startup_splash_v2.png"
    image = QImage(str(path))

    assert not image.isNull()
    assert image.width() == 640
    assert image.height() == 360

    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(rgba.constBits().asstring(rgba.sizeInBytes()))
    assert all(alpha == 255 for alpha in pixels[3::4])
    assert not any(
        pixels[offset : offset + 3] == b"\xff\x00\xff"
        for offset in range(0, len(pixels), 4)
    )
