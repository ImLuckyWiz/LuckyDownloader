"""Central motion and micro-interaction helper (Phase 9a, A6; Phase 1 Animations Upgrade).

Provides consistent duration tokens, easing curves, an accessibility / test switch
(``Motion.set_enabled(False)`` in ``tests/conftest.py`` and Windows ``SPI_GETCLIENTAREAANIMATION``
detection), and reusable height/width/color/opacity/value animators.
"""

from __future__ import annotations

import sys
from typing import Callable

import shiboken6
from PySide6.QtCore import (
    QEasingCurve, QObject, QParallelAnimationGroup, QPoint, QPropertyAnimation, QVariantAnimation,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton, QWidget

# Legacy tokens (kept for backward compatibility with existing tests and call sites)
FAST_MS = 120
NORMAL_MS = 180
SLIDE_MS = 150
EASING = QEasingCurve.Type.OutCubic
QWIDGETSIZE_MAX = 16777215

# Modern design system motion tokens (ms)
DURATION_INSTANT = 0
DURATION_MICRO = 80
DURATION_FAST = 140
DURATION_NORMAL = 200
DURATION_ENTER = 240
DURATION_PULSE = 1200

# Modern easing curves
EASING_OUT = QEasingCurve.Type.OutCubic
EASING_IN = QEasingCurve.Type.InCubic
EASING_SNAP = QEasingCurve.Type.OutBack
EASING_SMOOTH = QEasingCurve.Type.InOutQuad


def system_animations_enabled() -> bool:
    """Return False if the OS explicitly disables client-area animations (Windows SPI_GETCLIENTAREAANIMATION)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        fn = ctypes.windll.user32.SystemParametersInfoW
        fn.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
        fn.restype = wintypes.BOOL
        ok = fn(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(enabled.value) if ok else True
    except Exception:  # noqa: BLE001
        return True


class Motion:
    """Global switch and helpers for UI animations."""

    DURATION_INSTANT = DURATION_INSTANT
    DURATION_MICRO = DURATION_MICRO
    DURATION_FAST = DURATION_FAST
    DURATION_NORMAL = DURATION_NORMAL
    DURATION_ENTER = DURATION_ENTER
    DURATION_PULSE = DURATION_PULSE

    EASING_OUT = EASING_OUT
    EASING_IN = EASING_IN
    EASING_SNAP = EASING_SNAP
    EASING_SMOOTH = EASING_SMOOTH

    FAST_MS = FAST_MS
    NORMAL_MS = NORMAL_MS
    SLIDE_MS = SLIDE_MS
    EASING = EASING

    _override: bool | None = None

    @classmethod
    def set_enabled(cls, enabled: bool | None) -> None:
        """Force animations on (True), off (False), or follow the OS setting (None)."""
        cls._override = enabled

    @classmethod
    def enabled(cls) -> bool:
        """Whether UI animations should run."""
        if cls._override is not None:
            return cls._override
        return system_animations_enabled()

    @classmethod
    def duration(cls, ms: int = NORMAL_MS) -> int:
        """Effective animation duration in milliseconds (0 when motion is disabled)."""
        return int(ms) if cls.enabled() else 0


def animate_height(
    widget: QWidget,
    start_h: int,
    end_h: int,
    duration_ms: int = NORMAL_MS,
    on_finished: Callable[[], None] | None = None,
    easing: QEasingCurve.Type = EASING,
) -> QVariantAnimation | None:
    """Animate ``widget.maximumHeight`` from ``start_h`` to ``end_h`` with easing."""
    prev = getattr(widget, "_height_anim", None)
    if isinstance(prev, QVariantAnimation):
        prev.stop()
        widget._height_anim = None

    if not Motion.enabled() or not widget.isVisible() or duration_ms <= 0 or start_h == end_h:
        widget.setMaximumHeight(QWIDGETSIZE_MAX if end_h > 0 else 0)
        if on_finished is not None:
            on_finished()
        return None

    anim = QVariantAnimation(widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(max(0, int(start_h)))
    anim.setEndValue(max(0, int(end_h)))
    anim.setEasingCurve(easing)

    def _step(val) -> None:
        if shiboken6.isValid(widget):
            widget.setMaximumHeight(int(val))

    def _done() -> None:
        if shiboken6.isValid(widget):
            widget._height_anim = None
            if on_finished is not None:
                on_finished()

    anim.valueChanged.connect(_step)
    anim.finished.connect(_done)
    widget._height_anim = anim
    widget.setMaximumHeight(max(0, int(start_h)))
    anim.start()
    return anim


def animate_width(
    widget: QWidget,
    start_w: int,
    end_w: int,
    duration_ms: int = NORMAL_MS,
    on_finished: Callable[[], None] | None = None,
    easing: QEasingCurve.Type = EASING,
) -> QVariantAnimation | None:
    """Animate ``widget.setFixedWidth`` from ``start_w`` to ``end_w`` with easing."""
    prev = getattr(widget, "_width_anim", None)
    if isinstance(prev, QVariantAnimation):
        prev.stop()
        widget._width_anim = None

    if not Motion.enabled() or not widget.isVisible() or duration_ms <= 0 or start_w == end_w:
        widget.setFixedWidth(int(end_w))
        if on_finished is not None:
            on_finished()
        return None

    anim = QVariantAnimation(widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(int(start_w))
    anim.setEndValue(int(end_w))
    anim.setEasingCurve(easing)

    def _step(val) -> None:
        if shiboken6.isValid(widget):
            widget.setFixedWidth(int(val))

    def _done() -> None:
        if shiboken6.isValid(widget):
            widget.setFixedWidth(int(end_w))
            widget._width_anim = None
            if on_finished is not None:
                on_finished()

    anim.valueChanged.connect(_step)
    anim.finished.connect(_done)
    widget._width_anim = anim
    anim.start()
    return anim


def animate_opacity(
    widget: QWidget,
    start_alpha: float,
    end_alpha: float,
    duration_ms: int = NORMAL_MS,
    on_finished: Callable[[], None] | None = None,
    easing: QEasingCurve.Type = EASING_OUT,
) -> QVariantAnimation | None:
    """Animate widget opacity using a QGraphicsOpacityEffect with the given easing."""
    prev = getattr(widget, "_opacity_anim", None)
    if isinstance(prev, QVariantAnimation):
        prev.stop()
        widget._opacity_anim = None

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    target_alpha = max(0.0, min(1.0, float(end_alpha)))
    initial_alpha = max(0.0, min(1.0, float(start_alpha)))

    if not Motion.enabled() or not widget.isVisible() or duration_ms <= 0 or initial_alpha == target_alpha:
        effect.setOpacity(target_alpha)
        if on_finished is not None:
            on_finished()
        return None

    effect.setOpacity(initial_alpha)
    anim = QVariantAnimation(widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(initial_alpha)
    anim.setEndValue(target_alpha)
    anim.setEasingCurve(easing)

    def _step(val) -> None:
        if shiboken6.isValid(widget) and shiboken6.isValid(effect):
            effect.setOpacity(float(val))

    def _done() -> None:
        if shiboken6.isValid(widget):
            widget._opacity_anim = None
            if shiboken6.isValid(effect):
                effect.setOpacity(target_alpha)
            if on_finished is not None:
                on_finished()

    anim.valueChanged.connect(_step)
    anim.finished.connect(_done)
    widget._opacity_anim = anim
    anim.start()
    return anim


def animate_slide_and_fade(
    widget: QWidget,
    start_pos: QPoint,
    end_pos: QPoint,
    start_alpha: float,
    end_alpha: float,
    duration_ms: int = NORMAL_MS,
    on_finished: Callable[[], None] | None = None,
    easing: QEasingCurve.Type = EASING_OUT,
) -> QParallelAnimationGroup | None:
    """Animate widget position and opacity simultaneously."""
    prev = getattr(widget, "_slide_fade_group", None)
    if isinstance(prev, QParallelAnimationGroup):
        prev.stop()
        widget._slide_fade_group = None

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

    target_alpha = max(0.0, min(1.0, float(end_alpha)))
    initial_alpha = max(0.0, min(1.0, float(start_alpha)))

    if not Motion.enabled() or not widget.isVisible() or duration_ms <= 0:
        widget.move(end_pos)
        effect.setOpacity(target_alpha)
        if on_finished is not None:
            on_finished()
        return None

    group = QParallelAnimationGroup(widget)

    pos_anim = QPropertyAnimation(widget, b"pos", group)
    pos_anim.setDuration(duration_ms)
    pos_anim.setStartValue(start_pos)
    pos_anim.setEndValue(end_pos)
    pos_anim.setEasingCurve(easing)
    group.addAnimation(pos_anim)

    op_anim = QVariantAnimation(group)
    op_anim.setDuration(duration_ms)
    op_anim.setStartValue(initial_alpha)
    op_anim.setEndValue(target_alpha)
    op_anim.setEasingCurve(easing)

    def _op_step(val) -> None:
        if shiboken6.isValid(widget) and shiboken6.isValid(effect):
            effect.setOpacity(float(val))

    op_anim.valueChanged.connect(_op_step)
    group.addAnimation(op_anim)

    def _done() -> None:
        if shiboken6.isValid(widget):
            widget._slide_fade_group = None
            widget.move(end_pos)
            if shiboken6.isValid(effect):
                effect.setOpacity(target_alpha)
            if on_finished is not None:
                on_finished()

    group.finished.connect(_done)
    widget._slide_fade_group = group
    widget.move(start_pos)
    effect.setOpacity(initial_alpha)
    group.start()
    return group


def animate_value(
    parent: QObject,
    start_val: float,
    end_val: float,
    duration_ms: int = NORMAL_MS,
    on_update: Callable[[float], None] | None = None,
    on_finished: Callable[[], None] | None = None,
    easing: QEasingCurve.Type = EASING_OUT,
) -> QVariantAnimation | None:
    """Animate a numeric scalar with callback on each step."""
    if not Motion.enabled() or duration_ms <= 0 or start_val == end_val:
        if on_update is not None:
            on_update(float(end_val))
        if on_finished is not None:
            on_finished()
        return None

    anim = QVariantAnimation(parent)
    anim.setDuration(duration_ms)
    anim.setStartValue(float(start_val))
    anim.setEndValue(float(end_val))
    anim.setEasingCurve(easing)

    def _step(val) -> None:
        if shiboken6.isValid(parent) and on_update is not None:
            on_update(float(val))

    def _done() -> None:
        if shiboken6.isValid(parent):
            if on_update is not None:
                on_update(float(end_val))
            if on_finished is not None:
                on_finished()

    anim.valueChanged.connect(_step)
    anim.finished.connect(_done)
    anim.start()
    return anim


class ButtonHoverAnimator(QObject):
    """Opt-in colour interpolator for custom-painted or standalone buttons.

    Note: Standard QSS-styled ``QPushButton`` widgets use QSS ``:hover`` / ``:focus`` rules directly
    because setting per-frame inline ``setStyleSheet`` on a ``QPushButton`` overrides application-level
    dynamic property selectors (``[variant="..."]``, ``[selected="true"]``). Use this helper on custom
    surfaces that read ``animator.current_color`` in their ``paintEvent``.
    """

    def __init__(
        self,
        parent: QPushButton | QWidget,
        normal_color: str,
        hover_color: str,
        duration_ms: int = FAST_MS,
    ):
        super().__init__(parent)
        self._widget = parent
        self._normal = QColor(normal_color)
        self._hover = QColor(hover_color)
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration_ms)
        self._anim.setEasingCurve(EASING)
        self._anim.valueChanged.connect(self._on_step)

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def current_color(self) -> QColor:
        t = self._progress
        return QColor(
            round(self._normal.red() + (self._hover.red() - self._normal.red()) * t),
            round(self._normal.green() + (self._hover.green() - self._normal.green()) * t),
            round(self._normal.blue() + (self._hover.blue() - self._normal.blue()) * t),
        )

    def set_hovered(self, hovered: bool) -> None:
        target = 1.0 if hovered else 0.0
        self._anim.stop()
        if not Motion.enabled() or not self._widget.isVisible():
            self._progress = target
            if shiboken6.isValid(self._widget):
                self._widget.update()
            return
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_step(self, value: float) -> None:
        self._progress = float(value)
        if shiboken6.isValid(self._widget):
            self._widget.update()
