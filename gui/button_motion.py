# -*- coding: utf-8 -*-
"""Reusable, geometry-safe micro-interactions for ``QPushButton`` widgets.

Buttons opt in with a dynamic ``motion-role`` property.  Supported values are
``primary``, ``secondary`` and ``quiet``.  Primary buttons receive a subtle
animated shadow; every role receives a ``motion-state`` property that can be
used from QSS (``idle``, ``hover``, ``pressed``, ``focus`` or ``disabled``).

Only a graphics effect is animated.  Widget geometry, layout margins and size
policies are never changed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import weakref

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
)
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QPushButton,
    QWidget,
)


_OWNER_PROPERTY = "_button-motion-owner"
_ROLE_PROPERTY = "motion-role"
_STATE_PROPERTY = "motion-state"
_SUPPORTED_ROLES = frozenset({"primary", "secondary", "quiet"})
_ACTIVE_OWNER_IDS: set[int] = set()


@dataclass(frozen=True, slots=True)
class MotionTarget:
    """Inspectable destination for the current primary-button animation."""

    state: str
    blur_radius: float
    offset_y: float
    duration_ms: int


@dataclass(slots=True)
class _ButtonState:
    role: str
    hovered: bool = False
    pressed: bool = False
    focused: bool = False
    target: MotionTarget | None = None
    effect: QGraphicsDropShadowEffect | None = None
    group: QParallelAnimationGroup | None = None
    blur_animation: QPropertyAnimation | None = None
    offset_animation: QPropertyAnimation | None = None


_TARGETS = {
    "idle": MotionTarget("idle", 3.5, 0.5, 140),
    "hover": MotionTarget("hover", 9.5, 2.0, 130),
    "pressed": MotionTarget("pressed", 2.0, 0.25, 100),
    "focus": MotionTarget("focus", 8.0, 1.5, 130),
}

_SHADOW_COLORS = {
    "idle": QColor(15, 23, 42, 40),
    "hover": QColor(37, 99, 235, 62),
    "pressed": QColor(15, 23, 42, 34),
    "focus": QColor(37, 99, 235, 56),
}


class ButtonMotionController(QObject):
    """Apply restrained button micro-interactions below *root_or_app*.

    Constructing the controller starts it immediately.  Keep the controller
    alive for as long as the UI should be animated.  ``refresh()`` is public
    for callers that want an eager scan, although the application event filter
    also discovers buttons created later.
    """

    def __init__(self, root_or_app: QWidget | QApplication):
        if not isinstance(root_or_app, (QWidget, QApplication)):
            raise TypeError("root_or_app must be a QWidget or QApplication")
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication must exist before button motion")

        super().__init__(root_or_app)
        self._root = root_or_app
        self._app = app
        self._states: dict[int, _ButtonState] = {}
        self._running = False
        self._owner_id = id(self)
        _ACTIVE_OWNER_IDS.add(self._owner_id)
        owner_id = self._owner_id
        self.destroyed.connect(
            lambda _obj=None, key=owner_id: _ACTIVE_OWNER_IDS.discard(key)
        )
        self.start()

    @property
    def installed_count(self) -> int:
        """Number of live buttons currently owned by this controller."""

        return len(self._states)

    def start(self) -> None:
        """Start observing events.  Calling this repeatedly is harmless."""

        if not self._running:
            self._app.installEventFilter(self)
            self._running = True
        self.refresh()

    def stop(self) -> None:
        """Stop observing and remove effects owned by this controller."""

        if self._running:
            self._app.removeEventFilter(self)
            self._running = False
        for button in self._buttons_in_scope():
            self.uninstall(button)
        # Deleted buttons can disappear from the scope scan before their
        # ``destroyed`` callback runs.  Their callbacks safely clear the rest.

    def refresh(self) -> None:
        """Eagerly discover opted-in buttons under the configured root."""

        for button in self._buttons_in_scope():
            role = self._role_for(button)
            if role in _SUPPORTED_ROLES:
                self.install(button)
            elif id(button) in self._states:
                self.uninstall(button)

    def install(self, button: QPushButton) -> bool:
        """Install motion for *button*; return ``False`` if already installed.

        A button can only be owned by one live controller, preventing duplicate
        event handling and stacked graphics effects.
        """

        if not isinstance(button, QPushButton) or not self._in_scope(button):
            return False
        role = self._role_for(button)
        if role not in _SUPPORTED_ROLES:
            return False

        key = id(button)
        current = self._states.get(key)
        if current is not None:
            if current.role == role:
                return False
            self.uninstall(button)

        marker = button.property(_OWNER_PROPERTY)
        try:
            marker_id = int(marker) if marker is not None else 0
        except (TypeError, ValueError):
            marker_id = 0
        if marker_id and marker_id != self._owner_id:
            if marker_id in _ACTIVE_OWNER_IDS:
                return False
            button.setProperty(_OWNER_PROPERTY, None)

        state = _ButtonState(role=role, focused=button.hasFocus())
        self._states[key] = state
        button.setProperty(_OWNER_PROPERTY, self._owner_id)
        button.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        controller_ref = weakref.ref(self)

        def _button_destroyed(_obj=None, state_key=key) -> None:
            controller = controller_ref()
            if controller is not None:
                controller._forget(state_key)

        button.destroyed.connect(_button_destroyed)
        if role == "primary":
            self._ensure_primary_effect(button, state)
        self._apply(button, state, animate=False)
        return True

    def uninstall(self, button: QPushButton) -> bool:
        """Remove only the animation/effect owned by this controller."""

        key = id(button)
        state = self._states.pop(key, None)
        if state is None:
            return False

        group = state.group
        if group is not None:
            try:
                group.stop()
            except RuntimeError:
                pass
        try:
            marker = button.property(_OWNER_PROPERTY)
            if marker == self._owner_id:
                button.setProperty(_OWNER_PROPERTY, None)
                button.setProperty(_STATE_PROPERTY, None)
            if state.effect is not None and button.graphicsEffect() is state.effect:
                button.setGraphicsEffect(None)
        except RuntimeError:
            pass
        return True

    def is_installed(self, button: QPushButton) -> bool:
        return id(button) in self._states

    def current_state(self, button: QPushButton) -> str | None:
        """Return the semantic interaction state for tests/QSS integration."""

        state = self._states.get(id(button))
        if state is None:
            return None
        if not button.isEnabled():
            return "disabled"
        return self._visual_state(state)

    def target_for(self, button: QPushButton) -> MotionTarget | None:
        """Return the last primary animation target, if any."""

        state = self._states.get(id(button))
        return state.target if state is not None else None

    def effect_for(
        self, button: QPushButton
    ) -> QGraphicsDropShadowEffect | None:
        """Return this controller's shadow effect for a primary button."""

        state = self._states.get(id(button))
        return state.effect if state is not None else None

    def animation_state(self, button: QPushButton) -> QAbstractAnimation.State | None:
        """Return the primary animation group's state, if present."""

        state = self._states.get(id(button))
        if state is None or state.group is None:
            return None
        try:
            return state.group.state()
        except RuntimeError:
            return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not isinstance(watched, QPushButton) or not self._in_scope(watched):
            return False

        try:
            event_type = event.type()
            if event_type == QEvent.Type.DynamicPropertyChange:
                name = bytes(event.propertyName()).decode("utf-8", "ignore")
                # Updating our bookkeeping properties emits another dynamic
                # property event synchronously.  Only a role change requires
                # re-installation; ignoring the rest prevents re-entrant
                # installs from replacing a freshly created state object.
                if name != _ROLE_PROPERTY:
                    return False

            role = self._role_for(watched)
            key = id(watched)
            state = self._states.get(key)
            if role not in _SUPPORTED_ROLES:
                if state is not None:
                    self.uninstall(watched)
                return False
            if state is None or state.role != role:
                self.install(watched)
                state = self._states.get(key)
            if state is None:
                return False

            changed = False
            animate = True
            if event_type == QEvent.Type.Enter:
                state.hovered = True
                changed = True
            elif event_type == QEvent.Type.Leave:
                state.hovered = False
                state.pressed = False
                changed = True
            elif event_type == QEvent.Type.MouseButtonPress:
                if self._is_left_mouse_event(event):
                    state.pressed = True
                    changed = True
            elif event_type == QEvent.Type.MouseButtonRelease:
                if self._is_left_mouse_event(event):
                    state.pressed = False
                    changed = True
            elif event_type == QEvent.Type.KeyPress:
                if (
                    self._is_activation_key_event(event)
                    and not event.isAutoRepeat()
                ):
                    state.pressed = True
                    changed = True
            elif event_type == QEvent.Type.KeyRelease:
                if (
                    self._is_activation_key_event(event)
                    and not event.isAutoRepeat()
                ):
                    state.pressed = False
                    changed = True
            elif event_type == QEvent.Type.FocusIn:
                state.focused = True
                changed = True
            elif event_type == QEvent.Type.FocusOut:
                state.focused = False
                state.pressed = False
                changed = True
            elif event_type == QEvent.Type.EnabledChange:
                state.pressed = False
                if not watched.isEnabled():
                    state.hovered = False
                changed = True
                animate = False
            elif event_type == QEvent.Type.DynamicPropertyChange:
                changed = True
                animate = False

            if changed:
                self._apply(watched, state, animate=animate)
        except RuntimeError:
            self._forget(id(watched))
        return False

    def _buttons_in_scope(self) -> list[QPushButton]:
        if isinstance(self._root, QApplication):
            return [
                widget
                for widget in self._root.allWidgets()
                if isinstance(widget, QPushButton)
            ]
        buttons = self._root.findChildren(QPushButton)
        if isinstance(self._root, QPushButton):
            buttons.insert(0, self._root)
        return buttons

    def _in_scope(self, button: QPushButton) -> bool:
        if isinstance(self._root, QApplication):
            return True
        return button is self._root or self._root.isAncestorOf(button)

    @staticmethod
    def _role_for(button: QPushButton) -> str:
        value = button.property(_ROLE_PROPERTY)
        return str(value or "").strip().lower()

    @staticmethod
    def _is_left_mouse_event(event: QEvent) -> bool:
        return (
            isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        )

    @staticmethod
    def _is_activation_key_event(event: QEvent) -> bool:
        return isinstance(event, QKeyEvent) and event.key() in {
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        }

    @staticmethod
    def _visual_state(state: _ButtonState) -> str:
        if state.pressed:
            return "pressed"
        if state.hovered:
            return "hover"
        if state.focused:
            return "focus"
        return "idle"

    def _apply(
        self,
        button: QPushButton,
        state: _ButtonState,
        *,
        animate: bool,
    ) -> None:
        if not button.isEnabled():
            self._set_motion_property(button, "disabled")
            self._reset_disabled(state)
            return

        visual_state = self._visual_state(state)
        self._set_motion_property(button, visual_state)
        if state.role != "primary":
            return
        self._ensure_primary_effect(button, state)
        effect = state.effect
        if effect is None:
            return
        effect.setEnabled(True)
        target = _TARGETS[visual_state]
        state.target = target
        effect.setColor(_SHADOW_COLORS[visual_state])
        self._move_effect(state, target, animate=animate)

    @staticmethod
    def _set_motion_property(button: QPushButton, value: str) -> None:
        if button.property(_STATE_PROPERTY) != value:
            button.setProperty(_STATE_PROPERTY, value)
            button.update()

    def _ensure_primary_effect(
        self, button: QPushButton, state: _ButtonState
    ) -> None:
        if state.effect is not None:
            try:
                if button.graphicsEffect() is state.effect:
                    return
            except RuntimeError:
                state.effect = None
                state.group = None
                state.blur_animation = None
                state.offset_animation = None

        # Never replace a graphics effect owned by another component.
        if button.graphicsEffect() is not None:
            return

        effect = QGraphicsDropShadowEffect(button)
        idle = _TARGETS["idle"]
        effect.setBlurRadius(idle.blur_radius)
        effect.setOffset(QPointF(0.0, idle.offset_y))
        effect.setColor(_SHADOW_COLORS["idle"])
        button.setGraphicsEffect(effect)

        group = QParallelAnimationGroup(effect)
        blur_animation = QPropertyAnimation(effect, b"blurRadius", group)
        offset_animation = QPropertyAnimation(effect, b"offset", group)
        easing = QEasingCurve(QEasingCurve.Type.OutCubic)
        blur_animation.setEasingCurve(easing)
        offset_animation.setEasingCurve(easing)
        state.effect = effect
        state.group = group
        state.blur_animation = blur_animation
        state.offset_animation = offset_animation

        controller_ref = weakref.ref(self)
        key = id(button)

        def _effect_destroyed(_obj=None, state_key=key) -> None:
            controller = controller_ref()
            if controller is None:
                return
            current = controller._states.get(state_key)
            if current is not None:
                current.effect = None
                current.group = None
                current.blur_animation = None
                current.offset_animation = None

        effect.destroyed.connect(_effect_destroyed)

    @staticmethod
    def _move_effect(
        state: _ButtonState, target: MotionTarget, *, animate: bool
    ) -> None:
        effect = state.effect
        group = state.group
        blur_animation = state.blur_animation
        offset_animation = state.offset_animation
        if (
            effect is None
            or group is None
            or blur_animation is None
            or offset_animation is None
        ):
            return

        group.stop()
        if not animate:
            effect.setBlurRadius(target.blur_radius)
            effect.setOffset(QPointF(0.0, target.offset_y))
            return

        blur_animation.setDuration(target.duration_ms)
        blur_animation.setStartValue(effect.blurRadius())
        blur_animation.setEndValue(target.blur_radius)
        offset_animation.setDuration(target.duration_ms)
        offset_animation.setStartValue(effect.offset())
        offset_animation.setEndValue(QPointF(0.0, target.offset_y))
        group.start()

    @staticmethod
    def _reset_disabled(state: _ButtonState) -> None:
        state.target = _TARGETS["idle"] if state.role == "primary" else None
        if state.group is not None:
            try:
                state.group.stop()
            except RuntimeError:
                pass
        if state.effect is not None:
            try:
                idle = _TARGETS["idle"]
                state.effect.setBlurRadius(idle.blur_radius)
                state.effect.setOffset(QPointF(0.0, idle.offset_y))
                state.effect.setColor(_SHADOW_COLORS["idle"])
                state.effect.setEnabled(False)
            except RuntimeError:
                pass

    def _forget(self, key: int) -> None:
        self._states.pop(key, None)


__all__ = ["ButtonMotionController", "MotionTarget"]
