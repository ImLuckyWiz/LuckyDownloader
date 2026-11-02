"""
Custom window title bar (Phase W, v2.6.0).

Provides an in-app title bar matching the LuckyTwitch dark theme, with native-like
window controls (minimize, maximize/restore, close), dragging, double-click to maximize,
and seamless integration with Qt window management.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from core.palette import BG, BG2, FG, MUTED, WHITE
from core.resources import resource_path
from core.i18n import t
from qt_ui.icons import icon
from qt_ui.i18n_qt import language_bus

TITLEBAR_HEIGHT = 32
CLOSE_HOVER_BG = "#c42b1c"
CLOSE_PRESS_BG = "#b22416"
CAPTION_HOVER_BG = "rgba(255, 255, 255, 0.08)"
CAPTION_PRESS_BG = "rgba(255, 255, 255, 0.14)"


class CaptionButton(QToolButton):
    """Window control button (minimize, maximize, close) with responsive hover styling."""

    def __init__(self, icon_name: str, tooltip: str, is_close: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._is_close = is_close
        self._icon_name = icon_name
        self.setToolTip(tooltip)
        self.setFixedSize(46, TITLEBAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)
        self._update_icon(FG)

        if self._is_close:
            self.setStyleSheet(f"""
                QToolButton {{
                    border: none;
                    background-color: transparent;
                }}
                QToolButton:hover {{
                    background-color: {CLOSE_HOVER_BG};
                }}
                QToolButton:pressed {{
                    background-color: {CLOSE_PRESS_BG};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QToolButton {{
                    border: none;
                    background-color: transparent;
                }}
                QToolButton:hover {{
                    background-color: {CAPTION_HOVER_BG};
                }}
                QToolButton:pressed {{
                    background-color: {CAPTION_PRESS_BG};
                }}
            """)

    def _update_icon(self, color: str) -> None:
        self.setIcon(icon(self._icon_name, 12, color))
        self.setIconSize(QSize(12, 12))

    def set_native_state(self, hover: bool, pressed: bool) -> None:
        """Update visual state when Windows handles mouse over HTMAXBUTTON for Snap Layouts."""
        if pressed:
            bg = CLOSE_PRESS_BG if self._is_close else CAPTION_PRESS_BG
        elif hover:
            bg = CLOSE_HOVER_BG if self._is_close else CAPTION_HOVER_BG
        else:
            bg = "transparent"
        hover_bg = CLOSE_HOVER_BG if self._is_close else CAPTION_HOVER_BG
        press_bg = CLOSE_PRESS_BG if self._is_close else CAPTION_PRESS_BG
        self.setStyleSheet(f"""
            QToolButton {{
                border: none;
                background-color: {bg};
            }}
            QToolButton:hover {{
                background-color: {hover_bg};
            }}
            QToolButton:pressed {{
                background-color: {press_bg};
            }}
        """)

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._update_icon(FG)

    def enterEvent(self, event) -> None:
        if self._is_close:
            self._update_icon(WHITE)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._is_close:
            self._update_icon(FG)
        super().leaveEvent(event)


class CustomTitleBar(QWidget):
    """Window title bar widget drawn inside the client area."""

    close_clicked = Signal()
    minimize_clicked = Signal()
    maximize_clicked = Signal()

    def __init__(self, window: QWidget, title: str = "LuckyDownloader"):
        super().__init__(window)
        self.window = window
        self._drag_pos: QPoint | None = None
        self.setFixedHeight(TITLEBAR_HEIGHT)
        self.setObjectName("customTitleBar")

        self.setStyleSheet(f"""
            QWidget#customTitleBar {{
                background-color: {BG};
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        # App icon
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setScaledContents(True)
        icon_path = resource_path("assets/icon.png")
        if icon_path.is_file():
            self.icon_label.setPixmap(QPixmap(str(icon_path)))
        else:
            self.icon_label.setPixmap(icon("film", 16, FG).pixmap(16, 16))
        layout.addWidget(self.icon_label)

        # Title label
        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {FG};
                font-size: 12px;
                font-weight: 500;
                background: transparent;
            }}
        """)
        layout.addWidget(self.title_label)
        layout.addStretch()

        # Window controls
        self.min_btn = CaptionButton("window-minimize", t("Minimize"), is_close=False, parent=self)
        self.min_btn.clicked.connect(self._on_minimize)
        layout.addWidget(self.min_btn)

        self.max_btn = CaptionButton("window-maximize", t("Maximize"), is_close=False, parent=self)
        self.max_btn.clicked.connect(self._on_maximize)
        layout.addWidget(self.max_btn)

        self.close_btn = CaptionButton("x", t("Close"), is_close=True, parent=self)
        self.close_btn.clicked.connect(self._on_close)
        layout.addWidget(self.close_btn)

        language_bus().changed.connect(self.retranslate_ui)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def retranslate_ui(self) -> None:
        """Retranslate titlebar tooltips on language change."""
        self.min_btn.setToolTip(t("Minimize"))
        self.close_btn.setToolTip(t("Close"))
        self.update_maximized_state(self.window.isMaximized())

    def update_maximized_state(self, is_maximized: bool) -> None:
        """Update maximize / restore button icon and tooltip based on window state."""
        if is_maximized:
            self.max_btn.set_icon_name("window-restore")
            self.max_btn.setToolTip(t("Restore"))
        else:
            self.max_btn.set_icon_name("window-maximize")
            self.max_btn.setToolTip(t("Maximize"))

    def _on_minimize(self) -> None:
        self.minimize_clicked.emit()
        self.window.showMinimized()

    def _on_maximize(self) -> None:
        self.maximize_clicked.emit()
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()
        self.update_maximized_state(self.window.isMaximized())

    def _on_close(self) -> None:
        self.close_clicked.emit()
        self.window.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicked on a child button
            child = self.childAt(event.position().toPoint())
            if child in (self.min_btn, self.max_btn, self.close_btn):
                super().mousePressEvent(event)
                return

            wh = self.window.windowHandle()
            if wh is not None and hasattr(wh, "startSystemMove") and sys.platform != "darwin":
                if wh.startSystemMove():
                    return

            self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self.window.isMaximized():
                # Dragging a maximized window restores it at cursor
                normal_geom = self.window.normalGeometry()
                curr_w = normal_geom.width() if normal_geom.isValid() else 1020
                ratio = event.position().x() / max(1, self.width())
                self.window.showNormal()
                self.update_maximized_state(False)
                new_x = int(event.globalPosition().x() - curr_w * ratio)
                new_y = int(event.globalPosition().y() - event.position().y())
                self.window.move(new_x, new_y)
                self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            else:
                self.window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child not in (self.min_btn, self.max_btn, self.close_btn):
                self._on_maximize()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
