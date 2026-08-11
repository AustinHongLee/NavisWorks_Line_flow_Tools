from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.iconography import ICON_NAMES, app_icon


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _opaque_pixel_count(icon: QIcon, mode: QIcon.Mode, size: int = 18) -> int:
    image = icon.pixmap(QSize(size, size), mode, QIcon.State.Off).toImage()
    return sum(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_every_icon_has_transparent_margin_and_visible_strokes(
    qt_app: QApplication, name: str
) -> None:
    icon = app_icon(name)
    assert not icon.isNull()

    for mode in (
        QIcon.Mode.Normal,
        QIcon.Mode.Active,
        QIcon.Mode.Disabled,
        QIcon.Mode.Selected,
    ):
        pixmap = icon.pixmap(QSize(18, 18), mode, QIcon.State.Off)
        assert not pixmap.isNull()
        assert pixmap.size() == QSize(18, 18)
        assert _opaque_pixel_count(icon, mode) >= 12

        image = pixmap.toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(17, 0).alpha() == 0
        assert image.pixelColor(0, 17).alpha() == 0
        assert image.pixelColor(17, 17).alpha() == 0


@pytest.mark.parametrize("size", [16, 18, 20])
def test_common_button_sizes_remain_visible(qt_app: QApplication, size: int) -> None:
    icon = app_icon("search", size=size)
    assert _opaque_pixel_count(icon, QIcon.Mode.Normal, size) >= 12


def test_state_pixmaps_use_requested_colors(qt_app: QApplication) -> None:
    icon = app_icon(
        "play",
        normal="#112233",
        active="#2A8BAD",
        disabled="#A1A2A3",
    )

    def colors_for(mode: QIcon.Mode, state: QIcon.State = QIcon.State.Off) -> set[str]:
        image = icon.pixmap(QSize(18, 18), mode, state).toImage()
        return {
            image.pixelColor(x, y).name().lower()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() == 255
        }

    assert "#112233" in colors_for(QIcon.Mode.Normal)
    assert "#2a8bad" in colors_for(QIcon.Mode.Normal, QIcon.State.On)
    assert "#112233" not in colors_for(QIcon.Mode.Normal, QIcon.State.On)
    assert "#2a8bad" in colors_for(QIcon.Mode.Active)
    assert "#a1a2a3" in colors_for(QIcon.Mode.Disabled)
    assert "#2a8bad" in colors_for(QIcon.Mode.Selected)
    assert "#2a8bad" in colors_for(QIcon.Mode.Selected, QIcon.State.On)


def test_checkable_on_state_is_populated(qt_app: QApplication) -> None:
    icon = app_icon("eye")
    for mode in QIcon.Mode:
        assert not icon.pixmap(QSize(18, 18), mode, QIcon.State.On).isNull()


@pytest.mark.parametrize("device_pixel_ratio", [1.0, 2.0, 3.0])
def test_high_dpi_pixmaps_are_available_at_native_resolution(
    qt_app: QApplication, device_pixel_ratio: float
) -> None:
    icon = app_icon("inspect", size=18)
    pixmap = icon.pixmap(
        QSize(18, 18),
        device_pixel_ratio,
        QIcon.Mode.Normal,
        QIcon.State.On,
    )

    assert not pixmap.isNull()
    assert pixmap.devicePixelRatio() == pytest.approx(device_pixel_ratio)
    assert pixmap.size() == QSize(
        round(18 * device_pixel_ratio), round(18 * device_pixel_ratio)
    )
    image = pixmap.toImage()
    assert sum(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    ) >= 12 * device_pixel_ratio
    assert image.pixelColor(0, 0).alpha() == 0


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("arrow_right", "arrow-right"),
        ("result/history", "history"),
        ("tune/inspect", "inspect"),
    ],
)
def test_documented_aliases_are_supported(
    qt_app: QApplication, alias: str, canonical: str
) -> None:
    alias_image = app_icon(alias).pixmap(18, 18).toImage()
    canonical_image = app_icon(canonical).pixmap(18, 18).toImage()
    assert alias_image == canonical_image


def test_unknown_name_is_an_explicit_error(qt_app: QApplication) -> None:
    with pytest.raises(ValueError, match="Unknown icon name"):
        app_icon("mystery-action")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"normal": "not-a-color"},
        {"active": "#12"},
        {"disabled": "invalid"},
        {"size": 0},
        {"size": 18.0},
    ],
)
def test_invalid_render_options_are_rejected(
    qt_app: QApplication, kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        app_icon("folder", **kwargs)  # type: ignore[arg-type]
