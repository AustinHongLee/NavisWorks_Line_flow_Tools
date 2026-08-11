# -*- coding: utf-8 -*-
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QAbstractAnimation, QEvent, QCoreApplication, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QPushButton, QWidget

from gui.button_motion import ButtonMotionController


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _make_button(app, role="primary"):
    root = QWidget()
    root.resize(320, 160)
    button = QPushButton("執行", root)
    button.setProperty("motion-role", role)
    button.setGeometry(80, 50, 140, 40)
    root.show()
    app.processEvents()
    return root, button


def test_primary_hover_and_press_animate_shadow_without_geometry_shift(app):
    root, button = _make_button(app)
    controller = ButtonMotionController(root)
    original_geometry = button.geometry()
    try:
        assert controller.is_installed(button)
        assert controller.install(button) is False
        effect = controller.effect_for(button)
        assert isinstance(effect, QGraphicsDropShadowEffect)

        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        hover_target = controller.target_for(button)
        assert controller.current_state(button) == "hover"
        assert hover_target is not None
        assert 100 <= hover_target.duration_ms <= 160
        assert hover_target.blur_radius == pytest.approx(9.5)
        assert hover_target.offset_y == pytest.approx(2.0)
        assert controller.animation_state(button) == QAbstractAnimation.State.Running
        QTest.qWait(hover_target.duration_ms + 30)
        app.processEvents()
        assert effect.blurRadius() == pytest.approx(hover_target.blur_radius, abs=0.2)
        assert effect.yOffset() == pytest.approx(hover_target.offset_y, abs=0.2)
        assert button.geometry() == original_geometry

        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        pressed_target = controller.target_for(button)
        assert controller.current_state(button) == "pressed"
        assert pressed_target is not None
        assert pressed_target.blur_radius < hover_target.blur_radius
        assert button.geometry() == original_geometry

        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        assert controller.current_state(button) == "hover"
        assert button.geometry() == original_geometry
    finally:
        controller.stop()
        root.close()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_disabled_primary_never_animates_and_resets_shadow(app):
    root, button = _make_button(app)
    controller = ButtonMotionController(root)
    original_geometry = button.geometry()
    try:
        button.setDisabled(True)
        app.processEvents()
        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        app.processEvents()

        effect = controller.effect_for(button)
        assert controller.current_state(button) == "disabled"
        assert button.property("motion-state") == "disabled"
        assert effect is not None and not effect.isEnabled()
        assert controller.animation_state(button) == QAbstractAnimation.State.Stopped
        assert button.geometry() == original_geometry
    finally:
        controller.stop()
        root.close()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_lightweight_roles_dynamic_role_and_widget_deletion_are_safe(app):
    root, button = _make_button(app, role="secondary")
    controller = ButtonMotionController(root)
    try:
        assert controller.effect_for(button) is None
        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        assert button.property("motion-state") == "hover"

        button.setProperty("motion-role", "primary")
        app.processEvents()
        assert controller.is_installed(button)
        assert isinstance(controller.effect_for(button), QGraphicsDropShadowEffect)

        button.deleteLater()
        QCoreApplication.sendPostedEvents(button, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert controller.installed_count == 0
    finally:
        controller.stop()
        root.close()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter],
)
def test_activation_keys_show_pressed_feedback_without_consuming_events(app, key):
    class KeyTrackingButton(QPushButton):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.key_presses = 0
            self.key_releases = 0

        def keyPressEvent(self, event):  # noqa: N802
            self.key_presses += 1
            super().keyPressEvent(event)

        def keyReleaseEvent(self, event):  # noqa: N802
            self.key_releases += 1
            super().keyReleaseEvent(event)

    root = QWidget()
    root.resize(320, 160)
    button = KeyTrackingButton("執行", root)
    button.setProperty("motion-role", "primary")
    button.setGeometry(80, 50, 140, 40)
    root.show()
    button.setFocus()
    app.processEvents()
    controller = ButtonMotionController(root)
    try:
        QTest.keyPress(button, key)
        assert controller.current_state(button) == "pressed"
        assert button.property("motion-state") == "pressed"
        assert controller.target_for(button).state == "pressed"
        assert button.key_presses == 1

        QTest.keyRelease(button, key)
        assert controller.current_state(button) == "focus"
        assert button.property("motion-state") == "focus"
        assert controller.target_for(button).state == "focus"
        assert controller.target_for(button).blur_radius == pytest.approx(8.0)
        assert controller.target_for(button).offset_y == pytest.approx(1.5)
        assert button.key_releases == 1
    finally:
        controller.stop()
        root.close()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_activation_key_auto_repeat_does_not_release_or_stick_state(app):
    root, button = _make_button(app)
    button.setFocus()
    app.processEvents()
    controller = ButtonMotionController(root)
    modifiers = Qt.KeyboardModifier.NoModifier
    try:
        initial_press = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Space, modifiers, " ", False, 1
        )
        QApplication.sendEvent(button, initial_press)
        assert controller.current_state(button) == "pressed"

        repeat_release = QKeyEvent(
            QEvent.Type.KeyRelease, Qt.Key.Key_Space, modifiers, " ", True, 2
        )
        repeat_press = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Space, modifiers, " ", True, 2
        )
        QApplication.sendEvent(button, repeat_release)
        QApplication.sendEvent(button, repeat_press)
        assert controller.current_state(button) == "pressed"

        final_release = QKeyEvent(
            QEvent.Type.KeyRelease, Qt.Key.Key_Space, modifiers, " ", False, 1
        )
        QApplication.sendEvent(button, final_release)
        assert controller.current_state(button) == "focus"

        # A stray auto-repeat pair without an initial key press cannot leave
        # the controller in a pressed state.
        QApplication.sendEvent(button, repeat_press)
        QApplication.sendEvent(button, repeat_release)
        assert controller.current_state(button) == "focus"
    finally:
        controller.stop()
        root.close()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(root, QEvent.Type.DeferredDelete)
        app.processEvents()
