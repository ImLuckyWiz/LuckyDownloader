"""The application shell (Phase 9b): Left Navigation Rail + PageStack shim (B1),
Command Bar with inline Paste/Clear and Twitch Account Status (B2, B4),
Loaded-VOD Strip with 16:9 thumbnail (B3), Compact Status Bar with Activity Pill (B7),
and Keyboard Shortcuts Cheat-Sheet Dialog (B8).

Note on icons (decision D10): ``qt_ui/icons.py`` is reserved for Claude. Every place in the shell
where an SVG icon will attach has an explicit ``# ICON NEEDED: <name>`` seam and ``set_icon_seam``
hook so icons drop in without restructuring any widget.
"""

from __future__ import annotations

from pathlib import Path
import webbrowser
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSizePolicy,
    QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from core.palette import ACCENT, MUTED, OK
from core.i18n import t
from qt_ui.i18n_qt import language_bus
from luckytwitch_engine import fmt_hms
from qt_ui.icons import icon
from qt_ui.motion import Motion, animate_width

# Logical tab order stays identical to Phases 1-8 so all 28 ``win.tabs`` call sites work unchanged:
# 0 = Browse (formerly Search), 1 = Plan, 2 = Options, 3 = Queue & log.
# Visually on the rail: Browse (0), Plan (1), Queue & log (3) sit at the top; Options (2) sits at the bottom.
RAIL_VISUAL_ORDER = (0, 1, 3, 2)

RAIL_ITEMS: dict[int, tuple[str, str, str, str]] = {
    # index: (key, glyph, label, icon_name)
    0: ("browse", "\u2315", "Browse", "search"),
    1: ("plan", "\u2702", "Plan", "scissors"),
    2: ("options", "\u2699", "Options", "sliders"),
    3: ("queue", "\u2630", "Queue & log", "list"),
}


def _polish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


class _RailButton(QPushButton):
    """A navigation rail button that supports Up/Down arrow key stepping."""

    def __init__(self, rail: "NavRail", index: int, key: str, icon_name: str):
        super().__init__(rail)
        self._rail = rail
        self.page_index = index
        self.key = key
        self.icon_name = icon_name
        self.setIcon(icon(icon_name, 18))
        self.setIconSize(QSize(18, 18))
        self.setProperty("variant", "rail")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMinimumHeight(40)
        self.setAccessibleName(RAIL_ITEMS.get(index, ("", "", "", ""))[2] or key.capitalize())
        self.setAccessibleDescription(t("Navigate to {tab} tab", tab=self.accessibleName()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Down:
            self._rail.step(self.page_index, 1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Up:
            self._rail.step(self.page_index, -1)
            event.accept()
            return
        super().keyPressEvent(event)


class NavRail(QFrame):
    """Left vertical navigation rail (46 px collapsed, 134 px expanded; Phase 9b, B1)."""

    currentChanged = Signal(int)
    expandedChanged = Signal(bool)

    COLLAPSED_WIDTH = 46
    EXPANDED_WIDTH = 134

    def __init__(self, expanded: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._expanded = bool(expanded)
        self._current_index = 0
        self.vod_loaded = False
        self.queue_count = 0
        self.search_badge = False

        self.setFixedWidth(self.EXPANDED_WIDTH if self._expanded else self.COLLAPSED_WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(4)

        self.buttons: dict[int, _RailButton] = {}
        self.buttons_by_key: dict[str, _RailButton] = {}

        for idx in (0, 1, 3):
            btn = self._make_button(idx)
            lay.addWidget(btn)

        lay.addStretch(1)

        btn_opt = self._make_button(2)
        lay.addWidget(btn_opt)

        # Collapse / expand button at the very bottom
        # ICON NEEDED: chevron-right / chevron-left
        self.toggle_btn = QPushButton(self)
        self.toggle_btn.setProperty("variant", "rail")
        self.toggle_btn.setProperty("selected", False)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggle_btn.setMinimumHeight(36)
        self.toggle_btn.setToolTip(t("Expand or collapse navigation rail"))
        self.toggle_btn.setAccessibleName(t("Toggle navigation sidebar"))
        self.toggle_btn.setAccessibleDescription(t("Expand or collapse the sidebar navigation rail"))
        language_bus().changed.connect(self._refresh_labels)
        self.toggle_btn.clicked.connect(self.toggle_expanded)
        lay.addWidget(self.toggle_btn)

        self._refresh_labels()
        self.set_current_index(0, emit=False)

    def _make_button(self, idx: int) -> _RailButton:
        key, _glyph, label, icon_name = RAIL_ITEMS[idx]
        btn = _RailButton(self, idx, key, icon_name)
        btn.setToolTip(t(label))
        btn.clicked.connect(lambda _checked=False, i=idx: self.set_current_index(i, emit=True))
        self.buttons[idx] = btn
        self.buttons_by_key[key] = btn
        if key == "browse":
            self.buttons_by_key["search"] = btn
        return btn

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        expanded = bool(expanded)
        target_w = self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
        if expanded == self._expanded and self.width() == target_w:
            return
        self._expanded = expanded
        if animate and Motion.enabled() and self.isVisible():
            if expanded:
                self._refresh_labels()
                animate_width(self, self.width(), target_w, Motion.NORMAL_MS)
            else:
                def _after_collapse():
                    self._refresh_labels()
                animate_width(self, self.width(), target_w, Motion.NORMAL_MS, on_finished=_after_collapse)
        else:
            self._refresh_labels()
            self.setFixedWidth(target_w)
        self.expandedChanged.emit(self._expanded)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded, animate=True)

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int, emit: bool = True) -> None:
        if index not in self.buttons:
            return
        self._current_index = index
        for idx, btn in self.buttons.items():
            sel = idx == index
            if btn.property("selected") != sel:
                btn.setProperty("selected", sel)
                _polish(btn)
        if emit:
            self.currentChanged.emit(index)

    def step(self, from_index: int, delta: int) -> None:
        if from_index not in RAIL_VISUAL_ORDER:
            return
        pos = RAIL_VISUAL_ORDER.index(from_index)
        nxt_pos = pos + delta
        if 0 <= nxt_pos < len(RAIL_VISUAL_ORDER):
            target = RAIL_VISUAL_ORDER[nxt_pos]
            self.set_current_index(target, emit=True)
            self.buttons[target].setFocus()

    def set_vod_loaded(self, loaded: bool) -> None:
        self.vod_loaded = bool(loaded)
        self._refresh_labels()

    def set_queue_count(self, count: int) -> None:
        self.queue_count = max(0, int(count))
        self._refresh_labels()

    def set_browse_badge(self, active: bool) -> None:
        self.browse_badge = bool(active)
        self.search_badge = bool(active)
        self._refresh_labels()

    def set_search_badge(self, active: bool) -> None:
        self.set_browse_badge(active)

    def _refresh_labels(self) -> None:
        for idx, btn in self.buttons.items():
            _key, _glyph, label, _icon = RAIL_ITEMS[idx]
            display_label = t(label).replace("&", "&&")
            btn.setToolTip(t(label))
            badge = ""
            if idx == 0 and (getattr(self, "browse_badge", False) or getattr(self, "search_badge", False)):
                badge = " \u25cf"
            elif idx == 1 and self.vod_loaded:
                badge = " \u25cf"
            elif idx == 3 and self.queue_count > 0:
                badge = f" ({self.queue_count})" if self._expanded else f" {self.queue_count}"

            if self._expanded:
                btn.setText(f"{display_label}{badge}")
            else:
                btn.setText(badge.strip())
        self.toggle_btn.setIcon(icon("chevron-left" if self._expanded else "chevron-right", 16))
        self.toggle_btn.setText(t("Collapse") if self._expanded else "")
        self.toggle_btn.setToolTip(t("Expand or collapse navigation rail"))
        self.toggle_btn.setAccessibleName(t("Toggle navigation sidebar"))
        self.toggle_btn.setAccessibleDescription(t("Expand or collapse the sidebar navigation rail"))


class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget subclass that smoothly crossfades between pages when Motion is enabled."""

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if index == self.currentIndex() or not (0 <= index < self.count()):
            return
        from qt_ui.motion import DURATION_FAST, Motion, animate_opacity

        if not Motion.enabled() or not self.isVisible():
            super().setCurrentIndex(index)
            return

        super().setCurrentIndex(index)
        new_w = self.currentWidget()
        if new_w is not None:
            def _cleanup():
                if new_w is not None:
                    new_w.setGraphicsEffect(None)

            animate_opacity(new_w, 0.0, 1.0, DURATION_FAST, on_finished=_cleanup)


class PageStack(QWidget):
    """QStackedWidget + synced QTabBar shim exposing the QTabWidget API used across ``MainWindow`` and tests (B1)."""

    currentChanged = Signal(int)

    def __init__(self, rail: NavRail | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pageStack")
        self.rail = rail
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Hidden / zero-height QTabBar kept in sync for keyboard tab order and ``win.tabs.tabBar()`` compatibility
        self._tab_bar = QTabBar(self)
        self._tab_bar.setFixedHeight(0)
        self._tab_bar.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._tab_bar.currentChanged.connect(self._on_tabbar_changed)
        lay.addWidget(self._tab_bar)

        self.stack = AnimatedStackedWidget(self)
        self.stack.currentChanged.connect(self._on_stack_changed)
        lay.addWidget(self.stack, 1)

        if self.rail is not None:
            self.rail.currentChanged.connect(self.setCurrentIndex)

    def addTab(self, widget: QWidget, label: str) -> int:  # noqa: N802
        idx = self.stack.addWidget(widget)
        self._tab_bar.blockSignals(True)
        try:
            self._tab_bar.addTab(label)
        finally:
            self._tab_bar.blockSignals(False)
        return idx

    def count(self) -> int:
        return self.stack.count()

    def widget(self, index: int) -> QWidget | None:
        return self.stack.widget(index)

    def indexOf(self, widget: QWidget) -> int:  # noqa: N802
        return self.stack.indexOf(widget)

    def currentIndex(self) -> int:  # noqa: N802
        return self.stack.currentIndex()

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def currentWidget(self) -> QWidget | None:  # noqa: N802
        return self.stack.currentWidget()

    def setCurrentWidget(self, widget: QWidget) -> None:  # noqa: N802
        self.stack.setCurrentWidget(widget)

    def tabText(self, index: int) -> str:  # noqa: N802
        return self._tab_bar.tabText(index)

    def setTabText(self, index: int, text: str) -> None:  # noqa: N802
        self._tab_bar.setTabText(index, text)

    def tabBar(self) -> QTabBar:  # noqa: N802
        return self._tab_bar

    def _on_tabbar_changed(self, index: int) -> None:
        if 0 <= index < self.stack.count() and self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)

    def _on_stack_changed(self, index: int) -> None:
        if self._tab_bar.currentIndex() != index:
            self._tab_bar.blockSignals(True)
            try:
                self._tab_bar.setCurrentIndex(index)
            finally:
                self._tab_bar.blockSignals(False)
        if self.rail is not None and self.rail.current_index() != index:
            self.rail.set_current_index(index, emit=False)
        self.currentChanged.emit(index)


class CommandBar(QFrame):
    """Top command bar with VOD entry, inline Paste/Clear action, Get info CTA, and Twitch account status (B2, B4)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("commandBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        # ICON NEEDED: link
        self.prompt_label = QLabel(t("VOD URL or ID:"), self)
        self.prompt_label.setProperty("role", "muted")
        row.addWidget(self.prompt_label)

        self.vod_entry = QLineEdit(self)
        self.vod_entry.setPlaceholderText(t("Paste a Twitch VOD link or ID…"))
        self.vod_entry.textChanged.connect(self._sync_action_btn)
        row.addWidget(self.vod_entry, 1)

        # Inline Paste / Clear button (NoFocus so Tab goes vod_entry -> info_btn -> api_btn)
        # ICON NEEDED: clipboard / x
        self.vod_action_btn = QPushButton(t("Paste"), self)
        self.vod_action_btn.setProperty("variant", "ghost")
        self.vod_action_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vod_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vod_action_btn.setToolTip(t("Paste from clipboard"))
        self.vod_action_btn.setAccessibleName(t("Paste VOD URL or clear input"))
        self.vod_action_btn.clicked.connect(self._on_vod_action)
        row.addWidget(self.vod_action_btn)

        self.info_btn = QPushButton(t("Get info"), self)
        self.info_btn.setProperty("variant", "accent")
        row.addWidget(self.info_btn)

        # Twitch Account Status dot + button (B4)
        # ICON NEEDED: twitch / user-check
        self.account_dot = QLabel("\u25cb", self)
        self.account_dot.setObjectName("accountDot")
        self.account_dot.setToolTip(t("Not signed in to Twitch API"))
        row.addWidget(self.account_dot)

        self.api_btn = QPushButton(t("Twitch API…"), self)
        self.api_btn.setObjectName("apiBtn")
        self.api_btn.setIcon(icon("user", 14))
        row.addWidget(self.api_btn)

        self.history_btn = QPushButton(t("History"), self)
        self.history_btn.setObjectName("historyBtn")
        self.history_btn.setIcon(icon("check", 14))
        self.history_btn.setToolTip(t("View download history"))
        row.addWidget(self.history_btn)

        outer.addLayout(row)

        self._no_vod_text = ""  # the "no VOD" sentence currently shown (empty when the label shows something else)
        self.info_label = QLabel("", self)
        self.show_no_vod()
        self.info_label.setProperty("role", "muted")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self.info_label)

        self._signed_in = False
        self.set_signed_in(False)

    def retranslate_ui(self) -> None:
        self.prompt_label.setText(t("VOD URL or ID:"))
        self.vod_entry.setPlaceholderText(t("Paste a Twitch VOD link or ID…"))
        self.vod_action_btn.setAccessibleName(t("Paste VOD URL or clear input"))
        self.info_btn.setText(t("Get info"))
        self.history_btn.setText(t("History"))
        self.history_btn.setToolTip(t("View download history"))
        self.api_btn.setText(t("Twitch API…"))
        self._sync_action_btn(self.vod_entry.text())
        self.set_signed_in(self._signed_in)
        if self._no_vod_text and self.info_label.text() == self._no_vod_text:
            self.show_no_vod()

    def show_no_vod(self) -> None:
        """Show the empty-state sentence; it is re-translated on a language change while it is still shown."""
        self._no_vod_text = t("No VOD loaded.")
        self.info_label.setText(self._no_vod_text)

    @property
    def signed_in(self) -> bool:
        return self._signed_in

    def set_signed_in(self, signed_in: bool) -> None:
        self._signed_in = bool(signed_in)
        self.api_btn.setProperty("signed_in", "true" if self._signed_in else "false")
        if self._signed_in:
            self.account_dot.setText("\u25cf")
            self.account_dot.setStyleSheet(f"color: {OK}; font-weight: bold;")
            self.account_dot.setToolTip(t("Signed in to Twitch API"))
            self.api_btn.setToolTip(t("Signed in to Twitch API (click to manage credentials)"))
        else:
            self.account_dot.setText("\u25cb")
            self.account_dot.setStyleSheet(f"color: {MUTED};")
            self.account_dot.setToolTip(t("Not signed in to Twitch API"))
            self.api_btn.setToolTip(t("Sign in with Twitch API credentials"))
        _polish(self.api_btn)

    def _sync_action_btn(self, text: str) -> None:
        if text.strip():
            self.vod_action_btn.setText("\u2715")
            self.vod_action_btn.setToolTip(t("Clear VOD field"))
        else:
            self.vod_action_btn.setText(t("Paste"))
            self.vod_action_btn.setToolTip(t("Paste from clipboard"))

    def _on_vod_action(self) -> None:
        if self.vod_entry.text().strip():
            self.vod_entry.clear()
            self.vod_entry.setFocus()
        else:
            clip = QApplication.clipboard()
            if clip is not None:
                text = clip.text().strip()
                if text:
                    self.vod_entry.setText(text)
                    self.vod_entry.setFocus()


class VodStrip(QFrame):
    """44 px loaded-VOD summary strip with 16:9 thumbnail, title, metadata, Open on Twitch, and Clear (B3)."""

    clicked = Signal()
    clear_requested = Signal()
    thumbnail_loaded = Signal(QPixmap)
    _thumb_loaded = Signal(str)

    HEIGHT = 48

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("vodStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vod_url: str = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(10)

        self.thumb_label = QLabel(t("VOD"), self)
        self.thumb_label.setObjectName("vodThumb")
        self.thumb_label.setFixedSize(64, 36)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setScaledContents(False)
        lay.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self.title_label = QLabel("", self)
        self.title_label.setProperty("role", "rowtitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_col.addWidget(self.title_label)

        self.meta_label = QLabel("", self)
        self.meta_label.setProperty("role", "caption")
        self.meta_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_col.addWidget(self.meta_label)
        lay.addLayout(text_col, 1)

        self.downloaded_badge = QLabel(t("✓ Downloaded"), self)
        self.downloaded_badge.setObjectName("vodDownloadedBadge")
        self.downloaded_badge.setStyleSheet("color: #4fbf80; font-weight: bold; padding: 2px 6px; border-radius: 4px; background: rgba(79, 191, 128, 0.15);")
        self.downloaded_badge.setVisible(False)
        lay.addWidget(self.downloaded_badge)



        self.open_btn = QPushButton(t("Open on Twitch"), self)
        self.open_btn.setIcon(icon("external-link", 14))
        self.open_btn.setProperty("variant", "ghost")
        self.open_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_btn.setAccessibleName(t("Open VOD on Twitch in browser"))
        self.open_btn.clicked.connect(self.open_on_twitch)
        lay.addWidget(self.open_btn)

        self.clear_btn = QPushButton(t("Clear"), self)
        self.clear_btn.setIcon(icon("x", 14))
        self.clear_btn.setProperty("variant", "ghost")
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.setAccessibleName(t("Clear loaded VOD"))
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        lay.addWidget(self.clear_btn)

        self._thumb_loaded.connect(self._on_thumb_file)
        self.setVisible(False)

    def set_vod(self, src, clips: list | None = None, warn: str = "") -> None:
        if src is None:
            self.clear()
            return
        clips = clips or []
        self.vod_url = getattr(src, "url", "") or f"https://www.twitch.tv/videos/{getattr(src, 'vod_id', '')}"
        self.title_label.setText(str(getattr(src, "title", "") or f"VOD {getattr(src, 'vod_id', '')}"))
        bits = [
            str(getattr(src, "uploader", "")),
            str(getattr(src, "upload_date", "")),
            fmt_hms(getattr(src, "duration", 0)),
        ]
        if clips:
            bits.append(f"{len(clips)} clips")
        muted = getattr(src, "muted", None) or []
        if muted:
            total_m = sum(r.duration for r in muted)
            bits.append(f"{len(muted)} muted ({fmt_hms(total_m)})")
        if warn:
            bits.append(f"({warn})")
        self.meta_label.setText("  \u00b7  ".join(b for b in bits if b))

        vod_id = str(getattr(src, "twitch_vod_id", "") or getattr(src, "id", "") or getattr(src, "vod_id", "") or "")
        from core import history
        hist = history.is_downloaded(vod_id)
        if hist and hasattr(self, "downloaded_badge"):
            self.downloaded_badge.setToolTip(t("Downloaded on {date}", date=hist.downloaded_at))
            self.downloaded_badge.setVisible(True)
        elif hasattr(self, "downloaded_badge"):
            self.downloaded_badge.setVisible(False)

        site = str(getattr(src, "site", "twitch") or "twitch")
        if site == "twitch":
            self.open_btn.setText(t("Open on Twitch"))
            self.open_btn.setAccessibleName(t("Open VOD on Twitch in browser"))
        else:
            site_title = site.capitalize()
            self.open_btn.setText(t("Open on {site}", site=site_title))
            self.open_btn.setAccessibleName(t("Open video on {site} in browser", site=site_title))

        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(site.upper()[:4] if site != "twitch" else t("VOD"))
        thumb_url = getattr(src, "thumbnail", "")
        if thumb_url:
            self._fetch_thumbnail(thumb_url)
        from qt_ui.motion import DURATION_NORMAL, Motion, animate_height
        if Motion.enabled() and self.parentWidget() and self.parentWidget().isVisible():
            self.setMaximumHeight(0)
            self.setVisible(True)
            animate_height(self, 0, self.HEIGHT, DURATION_NORMAL, on_finished=lambda: self.setFixedHeight(self.HEIGHT))
        else:
            self.setFixedHeight(self.HEIGHT)
            self.setVisible(True)

    def set_thumbnail_from_pixmap(self, pm: QPixmap) -> None:
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(
                self.thumb_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_label.setPixmap(scaled)
            self.thumb_label.setText("")

    def _fetch_thumbnail(self, url: str) -> None:
        import threading
        self._expected_thumb_url = url
        def work():
            try:
                from luckytwitch_engine import fetch_thumbnail
                p = fetch_thumbnail(url)
                if p and Path(p).is_file():
                    self._thumb_loaded.emit(f"{url}:::{p}")
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_thumb_file(self, payload: str) -> None:
        if ":::" in payload:
            url, path_str = payload.split(":::", 1)
        else:
            url, path_str = "", payload
        if url and url != getattr(self, "_expected_thumb_url", None):
            return
        pm = QPixmap(path_str)
        if not pm.isNull():
            self.set_thumbnail_from_pixmap(pm)
            self.thumbnail_loaded.emit(pm)

    def set_thumbnail_from_pil(self, pil_img) -> None:
        """Convert a PIL image (e.g. first storyboard frame) into a 16:9 QPixmap on the strip."""
        if pil_img is None:
            return
        try:
            rgb = pil_img.convert("RGB")
            w, h = rgb.size
            raw = rgb.tobytes("raw", "RGB")
            qimg = QImage(raw, w, h, w * 3, QImage.Format.Format_RGB888).copy()
            pix = QPixmap.fromImage(qimg)
            self.thumb_label.setText("")
            self.set_thumbnail_from_pixmap(pix)
        except Exception:  # noqa: BLE001
            pass

    def clear(self) -> None:
        self.vod_url = ""
        self.title_label.setText("")
        self.meta_label.setText("")
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(t("VOD"))
        from qt_ui.motion import DURATION_NORMAL, Motion, animate_height
        if Motion.enabled() and self.isVisible():
            def _after_clear():
                self.setVisible(False)
                self.setFixedHeight(self.HEIGHT)
            animate_height(self, self.height(), 0, DURATION_NORMAL, on_finished=_after_clear)
        else:
            self.setFixedHeight(self.HEIGHT)
            self.setVisible(False)

    def open_on_twitch(self) -> None:
        if self.vod_url:
            webbrowser.open(self.vod_url)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ShortcutsDialog(QDialog):
    """Compact keyboard shortcut reference sheet opened with ``F1`` (Phase 9b, B8)."""

    @classmethod
    def get_shortcuts(cls) -> list[tuple[str, str]]:
        return [
            ("Ctrl+L", t("Focus and select the VOD URL / ID bar")),
            ("Ctrl+1 / 2 / 3 / 4", t("Switch to Browse, Plan, Options, or Queue & log")),
            ("Ctrl+,", t("Open Options (Settings)")),
            ("Ctrl+Enter", t("Add current VOD to queue and start (on Plan)")),
            ("Ctrl+Shift+Enter", t("Add current VOD to queue without starting (on Plan)")),
            ("S / Del / ← → / + - 0", t("Cut at cursor / remove cut / nudge / zoom (on Timeline)")),
            ("Ctrl+Z / Ctrl+Y", t("Undo / redo timeline edit")),
            ("F1", t("Show this keyboard shortcuts sheet")),
            ("F2", t("Show welcome overview")),
        ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("Keyboard shortcuts"))
        self.setObjectName("shortcutsDialog")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        heading = QLabel(t("Keyboard shortcuts"), self)
        heading.setProperty("role", "heading")
        lay.addWidget(heading)

        card = QFrame(self)
        card.setObjectName("card")
        clay = QVBoxLayout(card)
        clay.setContentsMargins(12, 10, 12, 10)
        clay.setSpacing(6)

        for keys, desc in self.get_shortcuts():
            row = QHBoxLayout()
            row.setSpacing(12)
            k_lbl = QLabel(keys, card)
            k_lbl.setProperty("role", "rowtitle")
            k_lbl.setMinimumWidth(145)
            d_lbl = QLabel(desc, card)
            d_lbl.setProperty("role", "muted")
            row.addWidget(k_lbl)
            row.addWidget(d_lbl, 1)
            clay.addLayout(row)

        lay.addWidget(card)

        brow = QHBoxLayout()
        brow.addStretch(1)
        self.close_btn = QPushButton(t("Close"), self)
        self.close_btn.setProperty("variant", "accent")
        self.close_btn.clicked.connect(self.accept)
        brow.addWidget(self.close_btn)
        lay.addLayout(brow)
