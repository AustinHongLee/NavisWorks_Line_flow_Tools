"""Small, dependency-free line icons used by the desktop UI.

The icons are drawn at runtime with Qt rather than loaded from a font or an
external SVG.  Keeping the geometry on an 18-unit grid makes the strokes stay
legible at the 16–20 px sizes used by buttons and navigation items.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


_GRID = 18.0
_DEVICE_PIXEL_RATIOS = (1.0, 2.0, 3.0)

ICON_NAMES = frozenset(
    {
        "folder",
        "link",
        "export",
        "search",
        "play",
        "trash",
        "eye",
        "refresh",
        "warning",
        "result",
        "history",
        "tune",
        "inspect",
        "arrow-right",
    }
)

_ALIASES = {
    "arrow_right": "arrow-right",
    "result/history": "history",
    "tune/inspect": "inspect",
}


def _path(*points: tuple[float, float], closed: bool = False) -> QPainterPath:
    result = QPainterPath()
    result.moveTo(*points[0])
    for point in points[1:]:
        result.lineTo(*point)
    if closed:
        result.closeSubpath()
    return result


def _folder(painter: QPainter, color: QColor) -> None:
    shape = QPainterPath()
    shape.moveTo(2.5, 5.0)
    shape.lineTo(2.5, 14.2)
    shape.quadTo(2.5, 15.2, 3.5, 15.2)
    shape.lineTo(14.5, 15.2)
    shape.quadTo(15.5, 15.2, 15.5, 14.2)
    shape.lineTo(15.5, 6.5)
    shape.quadTo(15.5, 5.5, 14.5, 5.5)
    shape.lineTo(9.1, 5.5)
    shape.lineTo(7.3, 3.7)
    shape.lineTo(3.5, 3.7)
    shape.quadTo(2.5, 3.7, 2.5, 5.0)
    painter.drawPath(shape)


def _link(painter: QPainter, color: QColor) -> None:
    first = QPainterPath()
    first.moveTo(7.3, 11.9)
    first.lineTo(6.1, 13.1)
    first.cubicTo(4.8, 14.4, 2.7, 14.4, 1.6, 13.2)
    first.cubicTo(0.5, 12.1, 0.6, 10.1, 1.8, 8.9)
    first.lineTo(5.0, 5.7)
    first.cubicTo(6.2, 4.5, 8.2, 4.4, 9.3, 5.5)
    painter.drawPath(first)

    second = QPainterPath()
    second.moveTo(10.7, 6.1)
    second.lineTo(11.9, 4.9)
    second.cubicTo(13.2, 3.6, 15.3, 3.6, 16.4, 4.8)
    second.cubicTo(17.5, 5.9, 17.4, 7.9, 16.2, 9.1)
    second.lineTo(13.0, 12.3)
    second.cubicTo(11.8, 13.5, 9.8, 13.6, 8.7, 12.5)
    painter.drawPath(second)
    painter.drawLine(QPointF(6.1, 11.9), QPointF(11.9, 6.1))


def _export(painter: QPainter, color: QColor) -> None:
    painter.drawPath(_path((3.0, 11.5), (3.0, 14.8), (15.0, 14.8), (15.0, 11.5)))
    painter.drawLine(QPointF(9.0, 12.0), QPointF(9.0, 2.8))
    painter.drawPath(_path((5.8, 6.0), (9.0, 2.8), (12.2, 6.0)))


def _search(painter: QPainter, color: QColor) -> None:
    painter.drawEllipse(QRectF(2.3, 2.3, 9.7, 9.7))
    painter.drawLine(QPointF(11.0, 11.0), QPointF(15.5, 15.5))


def _play(painter: QPainter, color: QColor) -> None:
    triangle = _path((5.1, 3.2), (14.4, 9.0), (5.1, 14.8), closed=True)
    painter.save()
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPath(triangle)
    painter.restore()


def _trash(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(3.0, 5.0), QPointF(15.0, 5.0))
    painter.drawPath(_path((6.5, 5.0), (6.8, 3.1), (11.2, 3.1), (11.5, 5.0)))
    body = QPainterPath()
    body.moveTo(4.3, 5.0)
    body.lineTo(5.0, 15.0)
    body.lineTo(13.0, 15.0)
    body.lineTo(13.7, 5.0)
    painter.drawPath(body)
    painter.drawLine(QPointF(7.2, 7.5), QPointF(7.5, 12.7))
    painter.drawLine(QPointF(10.8, 7.5), QPointF(10.5, 12.7))


def _eye(painter: QPainter, color: QColor) -> None:
    eye = QPainterPath()
    eye.moveTo(1.8, 9.0)
    eye.cubicTo(4.1, 5.2, 6.4, 3.8, 9.0, 3.8)
    eye.cubicTo(11.6, 3.8, 13.9, 5.2, 16.2, 9.0)
    eye.cubicTo(13.9, 12.8, 11.6, 14.2, 9.0, 14.2)
    eye.cubicTo(6.4, 14.2, 4.1, 12.8, 1.8, 9.0)
    eye.closeSubpath()
    painter.drawPath(eye)
    painter.drawEllipse(QRectF(6.6, 6.6, 4.8, 4.8))


def _refresh(painter: QPainter, color: QColor) -> None:
    painter.drawArc(QRectF(2.4, 2.4, 13.2, 13.2), 35 * 16, 275 * 16)
    painter.drawPath(_path((13.7, 2.5), (15.7, 5.8), (12.1, 5.9)))


def _warning(painter: QPainter, color: QColor) -> None:
    warning = QPainterPath()
    warning.moveTo(8.1, 2.5)
    warning.quadTo(9.0, 1.2, 9.9, 2.5)
    warning.lineTo(16.0, 14.2)
    warning.quadTo(16.7, 15.5, 15.1, 15.5)
    warning.lineTo(2.9, 15.5)
    warning.quadTo(1.3, 15.5, 2.0, 14.2)
    warning.closeSubpath()
    painter.drawPath(warning)
    painter.drawLine(QPointF(9.0, 6.1), QPointF(9.0, 10.5))
    painter.save()
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(8.1, 12.2, 1.8, 1.8))
    painter.restore()


def _result(painter: QPainter, color: QColor) -> None:
    document = QPainterPath()
    document.moveTo(4.0, 2.2)
    document.lineTo(10.8, 2.2)
    document.lineTo(14.2, 5.6)
    document.lineTo(14.2, 15.8)
    document.lineTo(4.0, 15.8)
    document.closeSubpath()
    painter.drawPath(document)
    painter.drawPath(_path((10.8, 2.2), (10.8, 5.6), (14.2, 5.6)))
    painter.drawPath(_path((6.2, 10.1), (8.1, 12.0), (12.1, 8.0)))


def _history(painter: QPainter, color: QColor) -> None:
    painter.drawArc(QRectF(2.4, 2.4, 13.2, 13.2), 25 * 16, 300 * 16)
    painter.drawPath(_path((2.3, 5.2), (2.4, 9.0), (5.9, 7.3)))
    painter.drawPath(_path((9.0, 5.1), (9.0, 9.1), (12.0, 10.9)))


def _tune(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(2.4, 4.2), QPointF(15.6, 4.2))
    painter.drawLine(QPointF(2.4, 9.0), QPointF(15.6, 9.0))
    painter.drawLine(QPointF(2.4, 13.8), QPointF(15.6, 13.8))
    painter.save()
    painter.setBrush(color)
    painter.drawEllipse(QRectF(5.0, 2.6, 3.2, 3.2))
    painter.drawEllipse(QRectF(10.2, 7.4, 3.2, 3.2))
    painter.drawEllipse(QRectF(6.8, 12.2, 3.2, 3.2))
    painter.restore()


def _inspect(painter: QPainter, color: QColor) -> None:
    corners = (
        ((2.3, 6.1), (2.3, 2.3), (6.1, 2.3)),
        ((11.9, 2.3), (15.7, 2.3), (15.7, 6.1)),
        ((15.7, 11.9), (15.7, 15.7), (11.9, 15.7)),
        ((6.1, 15.7), (2.3, 15.7), (2.3, 11.9)),
    )
    for corner in corners:
        painter.drawPath(_path(*corner))
    painter.drawEllipse(QRectF(6.2, 6.2, 5.6, 5.6))
    painter.drawLine(QPointF(10.8, 10.8), QPointF(13.3, 13.3))


def _arrow_right(painter: QPainter, color: QColor) -> None:
    painter.drawLine(QPointF(2.8, 9.0), QPointF(14.7, 9.0))
    painter.drawPath(_path((10.5, 4.7), (14.8, 9.0), (10.5, 13.3)))


_DRAWERS: dict[str, Callable[[QPainter, QColor], None]] = {
    "folder": _folder,
    "link": _link,
    "export": _export,
    "search": _search,
    "play": _play,
    "trash": _trash,
    "eye": _eye,
    "refresh": _refresh,
    "warning": _warning,
    "result": _result,
    "history": _history,
    "tune": _tune,
    "inspect": _inspect,
    "arrow-right": _arrow_right,
}


def _validated_color(value: str, argument: str) -> QColor:
    color = QColor(value)
    if not color.isValid():
        raise ValueError(f"Invalid {argument} color: {value!r}")
    return color


def _render(name: str, color: QColor, size: int, device_pixel_ratio: float) -> QPixmap:
    physical_size = round(size * device_pixel_ratio)
    pixmap = QPixmap(QSize(physical_size, physical_size))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(physical_size / _GRID, physical_size / _GRID)
    pen = QPen(color, 1.65)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _DRAWERS[name](painter, color)
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap


def app_icon(
    name: str,
    *,
    normal: str = "#52697F",
    active: str = "#167493",
    disabled: str = "#AAB6C2",
    size: int = 18,
) -> QIcon:
    """Return a state-aware line icon rendered on a transparent background.

    ``name`` is one of :data:`ICON_NAMES`.  Active and selected modes use the
    accent color; disabled mode has its own muted color.  Both On and Off
    states are populated so the same icon works for regular and checkable
    buttons.  Icons remain owned by their widgets, so no QPixmap survives the
    QApplication that created it.
    """

    canonical_name = _ALIASES.get(name, name)
    if canonical_name not in _DRAWERS:
        choices = ", ".join(sorted(ICON_NAMES))
        raise ValueError(f"Unknown icon name {name!r}; expected one of: {choices}")
    if isinstance(size, bool) or not isinstance(size, int) or not 8 <= size <= 256:
        raise ValueError("size must be an integer between 8 and 256")

    normal_color = _validated_color(normal, "normal")
    active_color = _validated_color(active, "active")
    disabled_color = _validated_color(disabled, "disabled")
    colors = {
        (QIcon.Mode.Normal, QIcon.State.Off): normal_color,
        (QIcon.Mode.Normal, QIcon.State.On): active_color,
        (QIcon.Mode.Active, QIcon.State.Off): active_color,
        (QIcon.Mode.Active, QIcon.State.On): active_color,
        (QIcon.Mode.Disabled, QIcon.State.Off): disabled_color,
        (QIcon.Mode.Disabled, QIcon.State.On): disabled_color,
        (QIcon.Mode.Selected, QIcon.State.Off): active_color,
        (QIcon.Mode.Selected, QIcon.State.On): active_color,
    }
    icon = QIcon()
    for (mode, state), color in colors.items():
        for device_pixel_ratio in _DEVICE_PIXEL_RATIOS:
            pixmap = _render(canonical_name, color, size, device_pixel_ratio)
            icon.addPixmap(pixmap, mode, state)
    return icon


__all__ = ["ICON_NAMES", "app_icon"]
