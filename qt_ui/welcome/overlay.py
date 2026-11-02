"""Full-bleed First-Run Welcome & Quick Setup Overlay."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.i18n import t
from core.palette import ACCENT, ACCENT_HOVER, ACCENT_PRESS, FG, MUTED, WHITE
from core.resources import resource_path
from qt_ui.icons import icon, pixmap
from qt_ui.motion import (
    DURATION_ENTER, DURATION_FAST, DURATION_MICRO, DURATION_NORMAL, DURATION_PULSE,
    EASING_OUT, EASING_SNAP, Motion, animate_opacity, animate_slide_and_fade,
)
from qt_ui.welcome.background import AnimatedCanvas
from qt_ui.welcome.setup_card import QuickSetupCard


class WelcomeOverlay(QWidget):
    """Full-bleed immersive welcome canvas with choreographed entrance and quick-setup."""

    finished = Signal(str, str)  # (out_dir, container)
    signin_requested = Signal()

    def __init__(
        self,
        initial_out_dir: str,
        initial_container: str = "mp4",
        is_signed_in: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("welcomeOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 1. Background atmospheric canvas
        self.bg = AnimatedCanvas(self)

        # 2. Centered content container inside a smooth scroll area (in case window height is small)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        center_lay = QVBoxLayout(scroll_widget)
        center_lay.setContentsMargins(24, 32, 24, 32)
        center_lay.setSpacing(14)
        center_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Hero Icon (🍀 Clover / App branding)
        self.icon_lbl = QLabel(scroll_widget)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico_path = resource_path("assets", "icon.png")
        if ico_path.exists():
            pm = QPixmap(str(ico_path)).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.icon_lbl.setPixmap(pm)
        else:
            self.icon_lbl.setPixmap(pixmap("scissors", 64, ACCENT))
        center_lay.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        # Title
        self.title_lbl = QLabel(t("LuckyDownloader"), scroll_widget)
        self.title_lbl.setStyleSheet(f"color: {WHITE}; font-size: 26pt; font-weight: 800; letter-spacing: -0.5px;")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_lay.addWidget(self.title_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        # Subtitle / Tagline
        self.subtitle_lbl = QLabel(t(t("Fast Twitch VODs, precision clip cutting, and animated chat overlays.")), scroll_widget)
        self.subtitle_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11pt;")
        self.subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_lay.addWidget(self.subtitle_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        center_lay.addSpacing(6)

        # Quick Setup Card
        self.setup_card = QuickSetupCard(
            initial_out_dir=initial_out_dir,
            initial_container=initial_container,
            is_signed_in=is_signed_in,
            parent=scroll_widget,
        )
        self.setup_card.signin_requested.connect(self.signin_requested.emit)
        center_lay.addWidget(self.setup_card, 0, Qt.AlignmentFlag.AlignCenter)

        center_lay.addSpacing(8)

        # Primary Call-To-Action (CTA) Button
        self.start_btn = QPushButton(t("Start Using LuckyDownloader →"), scroll_widget)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setMinimumWidth(320)
        self.start_btn.setStyleSheet(
            f"QPushButton {{ "
            f"background-color: {ACCENT}; color: {WHITE}; font-size: 13pt; font-weight: bold; "
            f"border: 1px solid rgba(255, 255, 255, 0.22); border-radius: 8px; padding: 11px 28px; "
            f"}} "
            f"QPushButton:hover {{ "
            f"background-color: {ACCENT_HOVER}; border: 1px solid rgba(255, 255, 255, 0.4); "
            f"}} "
            f"QPushButton:pressed {{ "
            f"background-color: {ACCENT_PRESS}; padding: 12px 28px 10px 28px; "
            f"}} "
            f"QPushButton:focus {{ "
            f"border: 2px solid {WHITE}; outline: none; "
            f"}}"
        )
        self.start_btn.clicked.connect(self.dismiss)
        center_lay.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # Skip hint
        self.skip_lbl = QLabel(t("Press Esc or Enter to launch"), scroll_widget)
        self.skip_lbl.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        self.skip_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_lay.addWidget(self.skip_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        self.scroll.setWidget(scroll_widget)

        # Root layout for overlay
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(self.scroll)

        self._dismissing = False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.bg.setGeometry(0, 0, self.width(), self.height())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.setFocus()
        self.start_entrance_sequence()

    def start_entrance_sequence(self) -> None:
        """Choreographed entrance animation for hero, card, and CTA."""
        if not Motion.enabled():
            return
        self.bg.start_bloom(300)
        # Smoothly reveal content container
        animate_opacity(self.scroll, 0.0, 1.0, duration_ms=DURATION_ENTER, easing=EASING_OUT)

    def dismiss(self) -> None:
        """Save settings and dismiss overlay with smooth exit transition."""
        if self._dismissing:
            return
        self._dismissing = True

        out_dir = self.setup_card.selected_out_dir
        container = self.setup_card.selected_container

        def _complete() -> None:
            self.finished.emit(out_dir, container)
            self.hide()
            self.deleteLater()

        if Motion.enabled() and self.isVisible():
            animate_opacity(self, 1.0, 0.0, duration_ms=DURATION_FAST, on_finished=_complete)
        else:
            _complete()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.dismiss()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_signed_in(self, signed_in: bool) -> None:
        self.setup_card.set_signed_in(signed_in)
