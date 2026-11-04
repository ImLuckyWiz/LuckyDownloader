"""Session persistence, clipboard watcher, drag-and-drop, and deep-link handling for ``MainWindow``."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

import weblink
from core import paths
from core.i18n import LANG_AUTO, N_, t
from core.settings import DEFAULTS, save_settings
from core.ui_state import UIState, load_ui_state, save_ui_state
from qt_ui import dialogs, i18n_qt, notify

MIN_SIZE = (950, 560)
TAB_NAMES = (N_("Browse"), N_("Plan"), N_("Options"), N_("Queue & log"))

_VOD_URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.|m\.)?twitch\.tv/(?:videos/\d+|\w+/v/\d+)|luckydownloader://\S+|luckytwitch://\S+)",
    re.I,
)
_CHANNEL_URL_RE = re.compile(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([a-zA-Z0-9_]{3,30})(?:[/?#].*)?$", re.I)
_CHANNEL_HANDLE_RE = re.compile(r"^@?([a-zA-Z0-9_]{3,30})$")
RESERVED_TWITCH = {
    "videos", "video", "directory", "p", "settings", "inventory", "downloads", "subscriptions", "wallet",
}


def extract_vod_input(text: str) -> str | None:
    """Return a Twitch VOD URL / luckydownloader:// / luckytwitch:// link / numeric VOD ID from ``text``, or None."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return None
    m = _VOD_URL_RE.search(s)
    if m:
        url = m.group(0)
        if url.lower().startswith(("twitch.tv", "www.twitch.tv", "m.twitch.tv")):
            url = f"https://{url}"
        return url
    if s.isdigit() and 7 <= len(s) <= 12:
        return s
    return None


def extract_channel_input(text: str) -> str | None:
    """Return a Twitch channel/streamer name if text looks like a handle or channel URL, else None."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s or extract_vod_input(s):
        return None
    m_url = _CHANNEL_URL_RE.match(s)
    if m_url:
        user = m_url.group(1).lower()
        if user not in RESERVED_TWITCH:
            return user
    m_handle = _CHANNEL_HANDLE_RE.match(s)
    if m_handle:
        user = m_handle.group(1).lower()
        if not user.isdigit():
            return user
    return None


def is_valid_url(text: str) -> bool:
    """Return True if text is a valid web URL or VOD ID, else False."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return False
    if s.isdigit():
        return True
    if extract_vod_input(s):
        return True
    if s.lower().startswith(("http://", "https://", "luckydownloader://", "luckytwitch://")):
        try:
            parsed = urlsplit(s)
            return bool(parsed.scheme and parsed.netloc and " " not in s)
        except Exception:
            return False
    if "." in s and "/" in s and " " not in s:
        try:
            parsed = urlsplit(f"https://{s}")
            return bool(parsed.netloc and "." in parsed.netloc)
        except Exception:
            return False
    return False


class SessionPersistenceMixin:
    """Mixin for ``MainWindow`` covering UI state save/restore, queue restore, drag-and-drop, clipboard, and links."""

    def show_welcome_overlay(self):
        if getattr(self, "welcome_overlay", None) is not None:
            self.welcome_overlay.raise_()
            self.welcome_overlay.show()
            return self.welcome_overlay

        out_dir = self.settings.get("out_dir", DEFAULTS["out_dir"])
        container = self.settings.get("container", DEFAULTS["container"])
        from qt_ui.welcome.overlay import WelcomeOverlay
        overlay = WelcomeOverlay(
            initial_out_dir=out_dir,
            initial_container=container,
            is_signed_in=bool(self.client),
            parent=self,
        )
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.finished.connect(self._on_welcome_finished)
        overlay.signin_requested.connect(self.ask_credentials)
        self.welcome_overlay = overlay
        overlay.show()
        overlay.raise_()
        if getattr(self, "title_bar", None) is not None:
            self.title_bar.raise_()
        return overlay

    def _on_welcome_finished(self, out_dir: str, container: str) -> None:
        self.settings["out_dir"] = out_dir
        self.settings["container"] = container
        save_settings(self.settings)
        if hasattr(self, "_ui_state"):
            self._ui_state.has_completed_onboarding = True
            self._save_ui_state()
        self.welcome_overlay = None

    def _restore_ui_state(self) -> None:
        ui_path = getattr(paths, "UI_STATE_PATH", paths.DATA_DIR / "luckytwitch_ui.json")
        has_saved = ui_path.is_file()
        state = load_ui_state(ui_path)
        self._ui_state = state
        setting = (getattr(state, "language", None) or LANG_AUTO) if has_saved else LANG_AUTO
        i18n_qt.apply_language(setting, announce=False)
        self.refresh_language()
        if hasattr(self, "tab_options") and hasattr(self.tab_options, "select_language_setting"):
            self.tab_options.select_language_setting(setting)
        self.rail.set_expanded(state.rail_expanded, animate=False)
        if has_saved:
            w = max(state.window_w, MIN_SIZE[0])
            h = max(state.window_h, MIN_SIZE[1])
            self.resize(w, h)
            if state.window_x is not None and state.window_y is not None:
                from PySide6.QtGui import QGuiApplication
                screens = QGuiApplication.screens()
                on_screen = any(
                    s.availableGeometry().intersects(QRect(state.window_x, state.window_y, w, h))
                    for s in screens
                ) if screens else True
                if on_screen:
                    self.move(state.window_x, state.window_y)
            if getattr(state, "window_maximized", False):
                self.showMaximized()
                if getattr(self, "title_bar", None) is not None:
                    self.title_bar.update_maximized_state(True)
        if self.client is None:
            if has_saved and state.active_tab in (*TAB_NAMES, "Search") and state.active_tab not in ("Browse", "Search"):
                self.tabs.setCurrentIndex(TAB_NAMES.index(state.active_tab))
            else:
                self.tabs.setCurrentWidget(self.tab_plan)

        should_welcome = (
            self._show_welcome is True
            or (self._show_welcome is None and not state.has_completed_onboarding and not os.environ.get("PYTEST_CURRENT_TEST"))
        )
        if should_welcome:
            self.show_welcome_overlay()

    def _restore_queue_state(self) -> None:
        """Restore unfinished queue items from disk and clean stale temporary workdirs on startup."""
        try:
            from core.finalize import cleanup_stale_workdirs
            out_dir = self.output_dir()
            if out_dir:
                cleanup_stale_workdirs(out_dir, max_age_hours=48.0)
        except Exception:  # noqa: BLE001
            pass

        try:
            restored = self.tab_queue.model.load_state(client=self.client, only_unfinished=True)
        except Exception:  # noqa: BLE001
            restored = []
        if restored:
            self.tab_queue.refresh_summary()
            self._sync_queue_badge()
            waiting_count = sum(1 for it in restored if it.status == "queued")
            if waiting_count > 0:
                notify.info(
                    self,
                    t("Queue restored"),
                    t("Restored {count} unfinished download(s) from the previous session.", count=waiting_count),
                    action=(t("Go to Queue"), self.show_queue_tab),
                )

    def _save_ui_state(self) -> None:
        idx = self.tabs.currentIndex()
        active_name = TAB_NAMES[idx] if 0 <= idx < len(TAB_NAMES) else "Plan"
        has_onboard = self._ui_state.has_completed_onboarding if hasattr(self, "_ui_state") else False
        is_max = self.isMaximized()
        geom = self.normalGeometry() if is_max else self.geometry()
        state = UIState(
            window_x=geom.x(),
            window_y=geom.y(),
            window_w=geom.width(),
            window_h=geom.height(),
            window_maximized=is_max,
            active_tab=active_name,
            rail_expanded=self.rail.expanded,
            has_completed_onboarding=has_onboard,
            custom_titlebar=self.use_custom_titlebar,
            language=i18n_qt.current_setting(),
        )
        save_ui_state(state)

    # ---------------------------- drag & drop / clipboard ---------------------------- #
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is not None and (mime.hasUrls() or mime.hasText()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is None:
            return
        raw = ""
        if mime.hasUrls() and mime.urls():
            raw = mime.urls()[0].toString()
        elif mime.hasText():
            raw = mime.text()
        raw = raw.strip()
        if not raw:
            return
        event.acceptProposedAction()
        if raw.lower().startswith(("luckydownloader://", "luckytwitch://")):
            self.open_link(raw)
            return

        vod = extract_vod_input(raw)
        channel = extract_channel_input(raw)
        if vod:
            self.vod_entry.setText(vod)
            self.on_get_info()
        elif channel:
            self.vod_entry.setText(channel)
            self.on_get_info()
        elif is_valid_url(raw):
            self.vod_entry.setText(raw)
            self.on_get_info()
        else:
            self.set_status(t("Please drop a valid video URL, a VOD ID, or a streamer name."))
            dialogs.warning(
                self,
                t("Invalid input"),
                t("The dropped text is not a valid video URL, a VOD ID, or a streamer name."),
            )

    def paste_vod_from_clipboard(self) -> None:
        clip = QApplication.clipboard()
        if clip is None:
            return
        text = clip.text().strip()
        if not text:
            return
        vod = extract_vod_input(text) or text
        self.vod_entry.setText(vod)
        self.vod_entry.setFocus()
        if extract_vod_input(text):
            self.on_get_info()

    def check_clipboard_for_vod(self) -> bool:
        """If the VOD entry is empty and a new Twitch VOD link is on the clipboard, offer a one-click toast."""
        if self.vod_entry.text().strip() or self.source is not None:
            return False
        clip = QApplication.clipboard()
        if clip is None:
            return False
        raw = clip.text().strip()
        vod = extract_vod_input(raw)
        if not vod or not vod.lower().startswith("http") or vod == self._last_clipboard_offer:
            return False
        self._last_clipboard_offer = vod

        def _load() -> None:
            self.vod_entry.setText(vod)
            self.on_get_info()

        notify.info(self, t("Twitch VOD in clipboard"), vod, action=(t("Load VOD"), _load))
        return True

    # ---------------------------- luckytwitch:// links ---------------------------- #
    def start_link_listener(self) -> None:
        """Poll ``LINKS_DIR`` every 500 ms and touch ``BEAT_PATH`` about every two seconds (first beat right away)."""
        self.poll_links()
        self._link_timer.start()

    def poll_links(self) -> None:
        try:
            self._link_tick += 1
            if self._link_tick % 4 == 1:  # about every two seconds
                weblink.beat(paths.BEAT_PATH)
            for text in weblink.take_links(paths.LINKS_DIR):
                self.open_link(text)
        except Exception as e:  # noqa: BLE001 - never let a bad link stop the loop that watches for the next one
            self.log(f"Links: {e}")

    def bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _retry_link(self) -> None:
        if self._link_retry_args is not None:
            text, waits = self._link_retry_args
            self._link_retry_args = None
            self.open_link(text, waits)

    def open_link(self, text: str, waits: int = 0) -> None:
        """Fill in the Plan tab from a ``luckytwitch://`` link and read the VOD. Never queues or starts anything."""
        try:
            req = weblink.parse_link(text)
        except weblink.LinkError as e:
            self.bring_to_front()
            self.log(f"Link not opened: {e}")
            dialogs.warning(self, t("Link"), str(e))
            return
        self.bring_to_front()
        if self.tools_busy or self._info_busy:
            if waits >= 180:
                self.log("Link not opened: the app stayed busy for too long.")
                dialogs.warning(self, t("Link"), t("The app was busy for too long to open that link. Try it again."))
                return
            self.set_status(t("The link will open in a moment…"))
            self._link_retry_args = (text, waits + 1)
            self._link_retry_timer.start()
            return
        self.tabs.setCurrentWidget(self.tab_plan)
        # forget the VOD that was loaded: if reading the new one fails, its cut points must not be applied to the old one
        self.source, self.clips, self.clips_loaded = None, [], False
        self.command_bar.show_no_vod()
        self.vod_entry.setText(req.url)
        self.tab_plan.set_cut_text(req.cuts or "")
        self.update_preview()
        self.refresh_clips()
        self.tab_options.refresh_name_examples()
        self.log(f"Link: {req.url}" + (f" ({req.label})" if req.label else "") + (f", cut points: {req.cuts}" if req.cuts else ""))
        self._link_pending = req.label
        from core.providers.detect import detect_provider
        if detect_provider(req.url).site != "generic":
            self.on_get_info()
