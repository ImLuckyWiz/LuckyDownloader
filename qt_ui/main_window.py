"""The main window (Phase 1 frame, upgraded in Phase 9b to the Left Navigation Rail + Command Bar +
VOD Strip + Compact Status Bar + Toasts + Keyboard Layer + UI State shell).

Mirrors ``App.build_ui`` of the tkinter app (window 1040x860, minimum 950x560, same texts, same order).
"""

from __future__ import annotations

import os
import sys
import weakref
from dataclasses import replace

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

import weblink
from core import paths, updates
from core.config import make_client
from core.i18n import LANG_AUTO, N_, t
from core.options import build_filter, build_options, flag
from core.providers import Capability, detect_source
from core.settings import DEFAULTS, save_settings
from core.ui_state import UIState, load_ui_state, save_ui_state
from luckytwitch_engine import EngineError, Job, clean_title, fmt_hms, make_plan
from qt_ui import dialogs, i18n_qt, notify
from qt_ui.background_jobs import InfoRunner, SavedChatRunner, ToolsRunner, UpdateCheckRunner, UpdateDownloadRunner
from qt_ui.bridge import Bridge
from qt_ui.session_persistence import (
    _CHANNEL_HANDLE_RE,
    _CHANNEL_URL_RE,
    _VOD_URL_RE,
    RESERVED_TWITCH,
    SessionPersistenceMixin,
    extract_channel_input,
    extract_vod_input,
    is_valid_url,
)
from qt_ui.shell import CommandBar, NavRail, PageStack, ShortcutsDialog, VodStrip
from qt_ui.tabs import BrowseTab, OptionsTab, PlanTab, QueueTab, SearchTab
from qt_ui.theme import dark_titlebar
from qt_ui.titlebar import CustomTitleBar
from qt_ui.twitch_dialog import TwitchDialog
from qt_ui.update_controller import UpdateControllerMixin
from qt_ui.watchlist_controller import WatchlistControllerMixin

WINDOW_TITLE = "LuckyDownloader"
START_SIZE = (1040, 860)
MIN_SIZE = (950, 560)
TAB_NAMES = (N_("Browse"), N_("Plan"), N_("Options"), N_("Queue & log"))
READY_TEXT = "Ready. Paste a VOD URL or ID and press «Get info»."


def _weak(method):
    """A function that calls ``method`` while its object lives, and does nothing (returns None) afterwards."""
    ref = weakref.WeakMethod(method)

    def call(*args):
        fn = ref()
        return fn(*args) if fn is not None else None

    return call


def _tab_text(name: str) -> str:
    """Qt reads '&' in a tab title as a keyboard-shortcut mark; '&&' shows a real ampersand."""
    return t(name).replace("&", "&&")


class MainWindow(SessionPersistenceMixin, UpdateControllerMixin, WatchlistControllerMixin, QMainWindow):
    """``client`` is the Twitch client (or None when nobody is signed in): without one the app starts on the Plan
    tab, as the tkinter app does. ``settings`` is the dict from ``core.settings.load_settings()``."""

    def __init__(
        self,
        bridge: Bridge | None = None,
        settings: dict | None = None,
        client=None,
        show_welcome: bool | None = None,
    ):
        super().__init__()
        self.bridge = bridge if bridge is not None else Bridge(self)
        self.settings = settings if settings is not None else {}
        self._client = client
        self._show_welcome = show_welcome
        self.welcome_overlay = None
        ui_path = getattr(paths, "UI_STATE_PATH", paths.DATA_DIR / "luckytwitch_ui.json")
        has_saved = ui_path.is_file()
        self._ui_state = load_ui_state(ui_path)
        # the language must be active before any widget is built, so every t() below is already in it
        i18n_qt.apply_language(
            (getattr(self._ui_state, "language", None) or LANG_AUTO) if has_saved else LANG_AUTO,
            announce=False,
        )
        self._login_dialog: TwitchDialog | None = None
        self._shortcuts_dialog: ShortcutsDialog | None = None
        self._last_clipboard_offer: str = ""
        # the background jobs: the tools setup, the overlay of a saved chat, and «Get info»
        self.tools_busy = False
        self.tools_ctx = None
        self.saved_chat_busy = False
        self.saved_chat_ctx = None
        self.tools_runner = ToolsRunner(self.bridge)
        self.saved_chat_runner = SavedChatRunner(self.bridge)
        self.info_runner = InfoRunner(self.bridge)
        self.update_check_runner = UpdateCheckRunner(self.bridge)
        updates.cleanup_stale_installer()
        self._update_info = None
        self._checking_updates_manually = False
        self._info_busy = False
        self._info_before = ""
        self._info_tick = 0
        self._info_own_bar = False
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(350)
        self._info_timer.timeout.connect(self._info_animate)
        self._link_pending: str | None = None
        self._info_from_link: str | None = None
        self._link_tick = 0
        self._link_timer = QTimer(self)
        self._link_timer.setInterval(500)
        self._link_timer.timeout.connect(self.poll_links)
        self._link_retry_timer = QTimer(self)
        self._link_retry_timer.setSingleShot(True)
        self._link_retry_timer.setInterval(1000)
        self._link_retry_timer.timeout.connect(self._retry_link)
        self._link_retry_args: tuple[str, int] | None = None
        self._progress_mode = "determinate"
        self._job_prefix = ""

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*START_SIZE)
        self.setMinimumSize(*MIN_SIZE)
        self.setAcceptDrops(True)

        use_custom_frame = (
            "--native-frame" not in sys.argv
            and os.environ.get("LUCKYDOWNLOADER_NATIVE_FRAME") != "1"
            and os.environ.get("LUCKYTWITCH_NATIVE_FRAME") != "1"
            and self.settings.get("custom_titlebar", True)
        )
        self.use_custom_titlebar = use_custom_frame
        central = QWidget(self)
        if use_custom_frame:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            from qt_ui.frameless import FrameController
            self.frame_controller = FrameController(self)
            outer_lay = QVBoxLayout(central)
            outer_lay.setContentsMargins(0, 0, 0, 0)
            outer_lay.setSpacing(0)
            self.title_bar = CustomTitleBar(self, WINDOW_TITLE)
            outer_lay.addWidget(self.title_bar)
            body = QWidget(central)
            root_lay = QHBoxLayout(body)
            root_lay.setContentsMargins(0, 0, 0, 0)
            root_lay.setSpacing(0)
            outer_lay.addWidget(body)
            parent_container = body
        else:
            self.title_bar = None
            self.frame_controller = None
            root_lay = QHBoxLayout(central)
            root_lay.setContentsMargins(0, 0, 0, 0)
            root_lay.setSpacing(0)
            parent_container = central
        self.setCentralWidget(central)

        # Right: Main content pane (constructed first to preserve top-to-bottom tab order)
        main_pane = QWidget(parent_container)
        main_lay = QVBoxLayout(main_pane)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # Top command bar + loaded-VOD strip (Phase 9b, B2, B3, B4)
        top_wrap = QWidget(main_pane)
        top_lay = QVBoxLayout(top_wrap)
        top_lay.setContentsMargins(10, 8, 10, 4)
        top_lay.setSpacing(6)

        self.command_bar = CommandBar(top_wrap)
        self.vod_entry: QLineEdit = self.command_bar.vod_entry
        self.vod_action_btn: QPushButton = self.command_bar.vod_action_btn
        self.info_btn: QPushButton = self.command_bar.info_btn
        self.api_btn: QPushButton = self.command_bar.api_btn
        self.info_label: QLabel = self.command_bar.info_label
        self.vod_entry.returnPressed.connect(self.on_get_info)
        self.info_btn.clicked.connect(self.on_get_info)
        self.api_btn.clicked.connect(self.ask_credentials)
        self.command_bar.history_btn.clicked.connect(self.open_history_dialog)
        self.command_bar.set_signed_in(self._client is not None)
        top_lay.addWidget(self.command_bar)

        self.vod_strip = VodStrip(top_wrap)
        self.vod_strip.clicked.connect(self.show_plan_tab)
        self.vod_strip.clear_requested.connect(self.clear_vod)
        self.vod_strip.thumbnail_loaded.connect(self._on_strip_thumbnail_loaded)
        top_lay.addWidget(self.vod_strip)
        main_lay.addWidget(top_wrap)

        # Left: Navigation Rail (spans full window height)
        self.rail = NavRail(expanded=False, parent=parent_container)

        # Middle shell: PageStack
        tabs_box = QWidget(main_pane)
        tabs_lay = QVBoxLayout(tabs_box)
        tabs_lay.setContentsMargins(10, 0, 10, 4)
        tabs_lay.setSpacing(0)

        self.tabs = PageStack(self.rail, parent=tabs_box)
        self.tab_browse, self.tab_plan, self.tab_options, self.tab_queue = (
            BrowseTab(self.bridge), PlanTab(self.settings, self.bridge), OptionsTab(self.settings), QueueTab(self.bridge),
        )
        self.tab_search = self.tab_browse
        for widget, name in zip((self.tab_browse, self.tab_plan, self.tab_options, self.tab_queue), TAB_NAMES):
            self.tabs.addTab(widget, _tab_text(name))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tabs_lay.addWidget(self.tabs)
        main_lay.addWidget(tabs_box, 1)

        # Bottom compact status bar: 3 px progress bar along top edge + status line + activity pill (Phase 9b, B7)
        bottom = QFrame(main_pane)
        bottom.setObjectName("statusBar")
        bot = QVBoxLayout(bottom)
        bot.setContentsMargins(0, 0, 0, 0)
        bot.setSpacing(0)
        self.progress = QProgressBar(bottom)
        self.progress.setObjectName("shellProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        bot.addWidget(self.progress)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(10, 4, 10, 5)
        status_row.setSpacing(8)
        self.status_label = QLabel(bottom)
        status_row.addWidget(self.status_label, 1)

        self.update_pill = QPushButton("", bottom)
        self.update_pill.setProperty("variant", "pill")
        self.update_pill.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.update_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_pill.setToolTip(t("A new version of LuckyDownloader is available."))
        self.update_pill.setVisible(False)
        self.update_pill.clicked.connect(self.open_update_dialog)
        status_row.addWidget(self.update_pill)

        self.activity_pill = QPushButton("", bottom)
        self.activity_pill.setProperty("variant", "pill")
        self.activity_pill.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.activity_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.activity_pill.setToolTip(t("Open Queue & log"))
        self.activity_pill.setVisible(False)
        self.activity_pill.clicked.connect(self.show_queue_tab)
        status_row.addWidget(self.activity_pill)
        bot.addLayout(status_row)
        main_lay.addWidget(bottom)

        # Layout placements: NavRail on the far left, main pane on the right
        root_lay.addWidget(self.rail)
        root_lay.addWidget(main_pane, 1)

        # Keyboard order of the top bar, then the tabs/rail
        self.setTabOrder(self.vod_entry, self.info_btn)
        self.setTabOrder(self.info_btn, self.api_btn)
        self.setTabOrder(self.api_btn, self.tabs.tabBar())

        # The queue tab and the window talk through signals and two hooks
        queue = self.tab_queue
        queue.status_message.connect(self.set_status)
        queue.plan_requested.connect(self.show_plan_tab)
        queue.show_requested.connect(self.show_queue_tab)
        queue.model.rowsInserted.connect(self._sync_queue_badge)
        queue.model.rowsRemoved.connect(self._sync_queue_badge)
        queue.model.modelReset.connect(self._sync_queue_badge)
        queue.blocked_reason = _weak(self.queue_blocked_reason)
        queue.output_dir = _weak(self.output_dir)
        search = self.tab_browse
        search.get_client = _weak(self.get_client)
        search.reload_client = _weak(self.reload_client)
        search.status_message.connect(self.set_status)
        search.signin_requested.connect(self.ask_credentials)
        search.vod_chosen.connect(self.use_vod)
        search.update_search_state()  # the client is known only now
        queue.cancel_other = _weak(self.cancel_saved_chat)  # «Cancel current» also stops a chat overlay
        options = self.tab_options
        options.source_provider = _weak(self.get_source)
        options.status_message.connect(self.set_status)
        options.refresh_clips_requested.connect(self.refresh_clips)
        options.preview_requested.connect(self.update_preview)
        options.output_folder_requested.connect(queue.open_output_folder)
        options.update_tools_requested.connect(self.update_tools_now)
        options.saved_chat_requested.connect(self.render_saved_chat)
        options.check_app_updates_requested.connect(lambda: self.start_update_check(force=True))
        plan = self.tab_plan
        plan.add_requested.connect(self.add_to_queue)
        plan.clip_download_requested.connect(self.download_clips)
        plan.search_requested.connect(self.show_browse_tab)
        plan.paste_requested.connect(self.paste_vod_from_clipboard)
        plan.strategy_changed.connect(self._on_plan_strategy_changed)
        plan.title_changed.connect(self._on_plan_title_changed)
        self.bridge.info_ok.connect(self.on_info_ok)
        self.bridge.error.connect(self.on_info_error)
        self.bridge.frames.connect(self._on_frames_for_strip)
        self.bridge.tools_info.connect(options.set_tools_info)
        self.bridge.tools_done.connect(self.on_tools_done)
        self.bridge.saved_chat_done.connect(self.on_saved_chat_done)
        self.bridge.progress.connect(self.set_progress)
        self.bridge.job.connect(self.on_job)
        self.bridge.queue_done.connect(self.on_queue_done)
        self.bridge.update_checked.connect(self.on_update_checked)

        i18n_qt.language_bus().changed.connect(self.refresh_language)
        self._setup_shortcuts()
        self._restore_ui_state()
        self._restore_queue_state()
        self.start_link_listener()
        self.set_status(t("Ready. Paste a VOD URL or ID and press «Get info»."))
        dark_titlebar(self)

    def refresh_language(self, _language: str = "") -> None:
        """Re-translate what was built by hand; runs on every language change (``i18n_qt.language_bus().changed``)."""
        if hasattr(self, "rail"):
            self.rail._refresh_labels()
        if hasattr(self, "command_bar"):
            self.command_bar.retranslate_ui()
        self.set_status(t("Ready. Paste a VOD URL or ID and press «Get info»."))
        if hasattr(self, "tabs"):
            for i, name in enumerate(TAB_NAMES):
                self.tabs.setTabText(i, _tab_text(name))
        if hasattr(self, "tab_plan") and hasattr(self.tab_plan, "refresh_language"):
            self.tab_plan.refresh_language()
        if hasattr(self, "tab_queue") and hasattr(self.tab_queue, "refresh_language"):
            self.tab_queue.refresh_language()
        if hasattr(self, "tab_options") and hasattr(self.tab_options, "refresh_language"):
            self.tab_options.refresh_language()
        if hasattr(self, "tab_browse") and hasattr(self.tab_browse, "refresh_language"):
            self.tab_browse.refresh_language()

    # ---------------------------- keyboard & window events ---------------------------- #
    def _setup_shortcuts(self) -> None:
        self.shortcuts: dict[str, QShortcut] = {}

        def bind(seq: str, slot) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            self.shortcuts[seq] = sc

        bind("Ctrl+L", self.focus_vod_bar)
        bind("Ctrl+1", lambda: self.tabs.setCurrentIndex(0))
        bind("Ctrl+2", lambda: self.tabs.setCurrentIndex(1))
        bind("Ctrl+3", lambda: self.tabs.setCurrentIndex(2))
        bind("Ctrl+4", lambda: self.tabs.setCurrentIndex(3))
        bind("Ctrl+,", self.show_options_tab)
        bind("Ctrl+Return", lambda: self._plan_shortcut_add(start=True))
        bind("Ctrl+Shift+Return", lambda: self._plan_shortcut_add(start=False))
        bind("F1", self.show_shortcuts)
        bind("F2", self.show_welcome_overlay)

    def _plan_shortcut_add(self, start: bool) -> None:
        if self.tabs.currentWidget() is self.tab_plan:
            self.add_to_queue(start=start)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "frame_controller", None) is not None:
            self.frame_controller.on_show()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            is_max = self.isMaximized()
            if getattr(self, "title_bar", None) is not None:
                self.title_bar.update_maximized_state(is_max)
            if getattr(self, "frame_controller", None) is not None:
                self.frame_controller.on_state_change(is_max)
        super().changeEvent(event)

    def setWindowTitle(self, title: str) -> None:  # noqa: N802
        super().setWindowTitle(title)
        if getattr(self, "title_bar", None) is not None:
            self.title_bar.set_title(title)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "frame_controller", None) is not None:
            self.frame_controller.on_resize(self.width(), self.height(), self.isMaximized())
        if getattr(self, "welcome_overlay", None) is not None:
            self.welcome_overlay.setGeometry(0, 0, self.width(), self.height())

    def nativeEvent(self, event_type, message):  # noqa: N802
        if getattr(self, "frame_controller", None) is not None:
            handled, result = self.frame_controller.handle_native_event(event_type, message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def focus_vod_bar(self) -> None:
        self.vod_entry.setFocus()
        self.vod_entry.selectAll()

    def show_shortcuts(self) -> ShortcutsDialog:
        if self._shortcuts_dialog is not None:
            self._shortcuts_dialog.close()
            self._shortcuts_dialog.deleteLater()
        self._shortcuts_dialog = ShortcutsDialog(self)
        self._shortcuts_dialog.open()
        return self._shortcuts_dialog

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            app = QApplication.instance()
            if app is not None and app.platformName() != "offscreen":
                self.check_clipboard_for_vod()
        return super().event(event)

    # ---------------------------- helpers ---------------------------- #
    @property
    def client(self):
        """The Twitch client, or None when nobody is signed in. Setting it refreshes the Search tab and account chip."""
        return self._client

    @client.setter
    def client(self, value) -> None:
        self._client = value
        if hasattr(self, "command_bar"):
            self.command_bar.set_signed_in(value is not None)
        if getattr(self, "welcome_overlay", None) is not None:
            self.welcome_overlay.set_signed_in(value is not None)
        self.update_search_state()

    def output_dir(self) -> str:
        return self.settings.get("out_dir", "")

    def _on_tab_changed(self, index: int) -> None:
        if index == 0 and hasattr(self, "tab_browse"):
            self.tab_browse.search_edit.setFocus()
            self.tab_browse.search_edit.selectAll()

    def show_browse_tab(self) -> None:
        self.tabs.setCurrentWidget(self.tab_browse)
        if hasattr(self, "tab_browse"):
            self.tab_browse.search_edit.setFocus()
            self.tab_browse.search_edit.selectAll()

    def show_search_tab(self) -> None:
        self.show_browse_tab()

    def show_plan_tab(self) -> None:
        self.tabs.setCurrentWidget(self.tab_plan)

    def show_options_tab(self) -> None:
        self.tabs.setCurrentWidget(self.tab_options)

    def show_queue_tab(self) -> None:
        self.tabs.setCurrentWidget(self.tab_queue)

    def _sync_queue_badge(self, *_args) -> None:
        if hasattr(self, "rail") and hasattr(self, "tab_queue"):
            self.rail.set_queue_count(len(self.tab_queue.items))

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def log(self, msg: str) -> None:
        self.tab_queue.log(msg)

    def _set_activity_pill_visible(self, visible: bool) -> None:
        from qt_ui.motion import DURATION_FAST, Motion, animate_opacity

        if not Motion.enabled() or not self.isVisible():
            self.activity_pill.setVisible(visible)
            return

        if visible:
            if not self.activity_pill.isVisible():
                self.activity_pill.setVisible(True)
                animate_opacity(self.activity_pill, 0.0, 1.0, DURATION_FAST)
        else:
            if self.activity_pill.isVisible():
                animate_opacity(
                    self.activity_pill, 1.0, 0.0, DURATION_FAST,
                    on_finished=lambda: self.activity_pill.setVisible(False),
                )

    def set_progress(self, frac: float, text: str) -> None:
        """A negative ``frac`` means «unknown»: the bar moves back and forth instead of filling."""
        if frac < 0:
            if self._progress_mode != "indeterminate":
                self.progress.setRange(0, 0)
                self._progress_mode = "indeterminate"
            self.set_status(f"{self._job_prefix}{text}")
            if self._job_prefix:
                self.activity_pill.setText(self._job_prefix.rstrip(": "))
                self._set_activity_pill_visible(True)
        else:
            if self._progress_mode != "determinate":
                self.progress.setRange(0, 100)
                self._progress_mode = "determinate"
            pct = round(frac * 100)
            from qt_ui.motion import DURATION_FAST, Motion, animate_value
            if Motion.enabled() and self.isVisible():
                animate_value(
                    self.progress,
                    start_val=float(self.progress.value()),
                    end_val=float(pct),
                    duration_ms=DURATION_FAST,
                    on_update=lambda v: self.progress.setValue(int(round(v))),
                )
            else:
                self.progress.setValue(pct)
            self.set_status(f"{self._job_prefix}{text}  \u2014  {frac * 100:.0f}%")
            if frac > 0 or self._job_prefix:
                prefix = self._job_prefix.rstrip(": ") or t("Running")
                self.activity_pill.setText(f"{prefix} \u00b7 {pct}%")
                self._set_activity_pill_visible(True)
            else:
                self._set_activity_pill_visible(False)

    def on_job(self, n: int, total: int) -> None:
        self._job_prefix = t("Job {n}/{total}: ", n=n, total=total) if total > 1 else ""
        self.activity_pill.setText(t("Job {n}/{total}", n=n, total=total))
        self._set_activity_pill_visible(True)

    def on_queue_done(self) -> None:
        self.set_progress(0, "")
        self._job_prefix = ""
        self._set_activity_pill_visible(False)
        self.set_status(t("Queue finished."))
        notify.system_notify(
            self, t("Queue finished"), t("All queued downloads have finished."),
            action=(t("Open folder"), self.tab_queue.open_output_folder),
        )

    def queue_blocked_reason(self) -> str:
        """Why «Start queue» must wait (a status-line sentence), or ''."""
        if self.tools_busy:
            return "Still preparing yt-dlp / ffmpeg, start the queue again in a moment."
        if self.saved_chat_busy:
            return "A chat overlay is being drawn, start the queue when it finishes."
        return ""

    # ---------------------------- options & plan state ---------------------------- #
    @property
    def source(self):
        return self.tab_plan.source

    @source.setter
    def source(self, value) -> None:
        self.tab_plan.source = value
        if hasattr(self, "rail"):
            self.rail.set_vod_loaded(value is not None)
        if hasattr(self, "tab_plan") and hasattr(self.tab_plan, "onboarding_card"):
            self.tab_plan.onboarding_card.setVisible(value is None)
        if value is None and hasattr(self, "vod_strip"):
            self.vod_strip.clear()

    @property
    def clips(self) -> list[dict]:
        return self.tab_plan.clips

    @clips.setter
    def clips(self, value: list[dict]) -> None:
        self.tab_plan.clips = value

    @property
    def clips_loaded(self) -> bool:
        return self.tab_plan.clips_loaded

    @clips_loaded.setter
    def clips_loaded(self, value: bool) -> None:
        self.tab_plan.clips_loaded = value

    def get_source(self):
        return self.tab_plan.source

    def clear_vod(self) -> None:
        """Clear the currently loaded VOD from the strip and Plan tab (Phase 9b, B3)."""
        self.source, self.clips, self.clips_loaded = None, [], False
        self.tab_plan.set_title("", raw_title="")
        self.tab_plan.set_formats([], "")
        self.command_bar.show_no_vod()
        self.tab_plan.set_mode(True)
        self.vod_strip.clear()
        self.update_preview()
        self.refresh_clips()
        self.tab_options.refresh_name_examples()
        self.set_status(t("Ready. Paste a VOD URL or ID and press «Get info»."))

    def _on_plan_title_changed(self, new_title: str) -> None:
        if self.source:
            self.source.title = new_title
            extra = f" \u00b7 {len(self.clips)} clips" if self.clips_loaded else ""
            self.info_label.setText(
                f"{self.source.uploader} \u00b7 {new_title} \u00b7 {fmt_hms(self.source.duration)} \u00b7 {self.source.date}{extra}"
            )
            self.vod_strip.title_label.setText(new_title or f"VOD {getattr(self.source, 'vod_id', '')}")
            self.tab_options.refresh_name_examples()

    def _on_frames_for_strip(self, src, frames) -> None:
        if src is self.source and frames:
            self.vod_strip.set_thumbnail_from_pil(frames[0])
            pm = self.vod_strip.thumb_label.pixmap()
            if pm is not None and not pm.isNull():
                for it in self.tab_queue.items:
                    if getattr(it.job, "source", None) is src and it.thumb is None:
                        self.tab_queue.model.set_thumbnail(it.iid, pm)

    def _on_strip_thumbnail_loaded(self, pm: QPixmap) -> None:
        if pm is not None and not pm.isNull() and self.source:
            for it in self.tab_queue.items:
                if getattr(it.job, "source", None) is self.source and it.thumb is None:
                    self.tab_queue.model.set_thumbnail(it.iid, pm)

    def cut_text(self) -> str:
        """The text of the Plan tab's cut points box."""
        return self.tab_plan.cut_text()

    def build_options(self):
        """The engine's ``JobOptions`` from the settings and the cut points (``App.build_options``)."""
        return build_options(self.settings, self.cut_text(), quality=self.tab_plan.current_quality())

    def build_filter(self):
        return build_filter(self.settings)

    def refresh_clips(self) -> None:
        """A setting the clip list depends on changed."""
        self.tab_plan.refresh_clips()

    def update_preview(self) -> None:
        """The strategy or threshold changed."""
        self.tab_plan.update_preview()

    def _on_plan_strategy_changed(self, _value: str) -> None:
        self.tab_options.binder.reload()
        self.tab_options.refresh_changed_markers()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt name)
        if self.tools_ctx:
            self.tools_ctx.cancel()
        if self.saved_chat_ctx:
            self.saved_chat_ctx.cancel()  # no orphan ffmpeg / TwitchDownloaderCLI after the window is gone
        runner = self.tab_queue.runner
        if runner.is_running():
            if not dialogs.ask_yes_no(self, t("Quit"), t("A job is running. Cancel it and quit?")):
                event.ignore()
                return
            if hasattr(runner, "cancel"):
                runner.cancel()
            elif getattr(runner, "ctx", None):
                runner.ctx.cancel()
        self._info_timer.stop()
        self._link_timer.stop()
        self._link_retry_timer.stop()
        if self._login_dialog is not None:
            self._login_dialog.close()  # cancels a sign-in that is waiting for the person
        if self._shortcuts_dialog is not None:
            self._shortcuts_dialog.close()
        self.tab_search.shutdown()
        self.tab_queue.shutdown()
        if self.settings:  # a window made without settings must not overwrite the saved file with nothing
            save_settings(self.settings)
        self._save_ui_state()
        try:
            paths.BEAT_PATH.unlink()  # a launch right after this one must not hand its link to a window that is gone
        except OSError:
            pass
        event.accept()

    def tab_names(self) -> list[str]:
        """The titles as the person reads them (with the '&' of «Queue & log» unescaped)."""
        return [self.tabs.tabText(i).replace("&&", "&") for i in range(self.tabs.count())]

    # ---------------------------- Get info ---------------------------- #
    def on_get_info(self) -> None:
        text = self.vod_entry.text().strip()
        if not text:
            return
        channel = extract_channel_input(text)
        if channel:
            self.show_search_tab()
            self.tab_search.search_edit.setText(channel)
            self.tab_search.search_edit.setFocus()
            self.tab_search.search_edit.selectAll()
            self.tab_search.on_search()
            return
        prov, cleaned = detect_source(text)
        if prov is None and not is_valid_url(text):
            self.set_status(t("Please enter a valid video URL, a VOD ID, or a streamer name."))
            dialogs.warning(
                self,
                t("Invalid input"),
                t("Please enter a valid video URL, a VOD ID, or a streamer name."),
            )
            return
        if self.tools_busy:
            self.set_status(t("Still preparing yt-dlp / ffmpeg, one moment…"))
            return
        self.set_info_busy(True)
        self.set_status(t("Reading VOD info…"))
        self._info_from_link, self._link_pending = self._link_pending, None
        self.info_runner.start(cleaned or text, self.client)

    def set_info_busy(self, busy: bool) -> None:
        """Feedback while «Get info» works: the button and the line under it show «Loading…» with moving dots, and the
        bar at the bottom runs, unless a download owns it."""
        if busy == self._info_busy:
            return
        self._info_busy = busy
        if busy:
            self._info_before = self.info_label.text()
            self._info_tick = 0
            self.info_btn.setEnabled(False)
            self._info_own_bar = not self.tab_queue.runner.is_running()
            if self._info_own_bar:
                self.set_progress(-1, t("Reading VOD info…"))
            self._info_animate()
            self._info_timer.start()
            return
        self._info_timer.stop()
        self.info_btn.setText(t("Get info"))
        self.info_btn.setEnabled(True)
        if self._info_own_bar:
            self.set_progress(0, "")
        self.info_label.setText(self._info_before)

    def _info_animate(self) -> None:
        if not self._info_busy:
            return
        dots = "." * (self._info_tick % 3 + 1)
        self.info_btn.setText("Loading" + dots)
        self.info_label.setText("Reading VOD info" + dots)
        self._info_tick += 1

    def on_info_ok(self, info, clips, loaded: bool, warn: str) -> None:
        self.set_info_busy(False)
        from core.source_info import PlaylistInfo
        if isinstance(info, PlaylistInfo):
            self._handle_playlist_loaded(info)
            return
        raw_title = info.title
        if flag(self.settings, "clean_title"):
            info.title = clean_title(info.title)
        info.raw_title = raw_title
        self.source, self.clips, self.clips_loaded = info, list(clips), bool(loaded)
        has_timeline = getattr(info, "has_capability", lambda c: True)(Capability.TIMELINE)
        self.tab_plan.set_mode(has_timeline)
        self.tab_plan.set_formats(
            getattr(info, "formats", []), str(self.settings.get("default_quality", DEFAULTS["default_quality"]))
        )
        self.tab_plan.set_title(info.title, raw_title=raw_title)
        if not has_timeline:
            self.tab_plan.update_generic_card(info)
        extra = f" \u00b7 {len(self.clips)} clips" if loaded else ""
        self.info_label.setText(
            f"{info.uploader} \u00b7 {info.title} \u00b7 {fmt_hms(info.duration)} \u00b7 {info.date}{extra}"
        )
        self.vod_strip.set_vod(info, self.clips if loaded else [], warn)
        if not self.cut_text() and has_timeline:
            self.tab_plan.set_cut_text("0:00:00 - end")
        self.update_preview()
        if has_timeline:
            self.refresh_clips()
        self.tab_options.refresh_name_examples()
        if has_timeline:
            self.set_status(t("VOD loaded. Set your cut points and add it to the queue."))
        else:
            self.set_status(t("Video loaded. Choose your options and add it to the queue."))
        if self._info_from_link is not None:
            what = f" ({self._info_from_link})" if self._info_from_link else ""
            self.set_status(
                t("VOD opened from a link{details}. Check the cut points, then add it to the queue.", details=what)
            )
            self._info_from_link = None
        if warn:
            self.log(warn)

    def on_info_error(self, msg: str) -> None:
        self._info_from_link = None
        self.set_info_busy(False)
        self.info_btn.setEnabled(True)
        self.set_status(t("Error."))
        if "extractor" in msg.lower() or "updating yt-dlp" in msg.lower():
            if dialogs.ask_yes_no(
                self,
                t("Extractor error"),
                msg + "\n\n" + t("Would you like to update yt-dlp now and try again?"),
            ):
                self._pending_retry_url = self.vod_entry.text().strip()
                self.update_tools_now()
                return
        dialogs.error(self, t("Error"), msg)

    # ---------------------------- adding to the queue ---------------------------- #
    def _current_vod_thumb(self):
        if hasattr(self, "vod_strip"):
            pm = self.vod_strip.thumb_label.pixmap()
            if pm is not None and not pm.isNull():
                return pm
        return None

    def add_to_queue(self, start: bool = False) -> None:
        if not self.source:
            dialogs.info(self, t("No VOD"), t("Paste a VOD and press «Get info» first."))
            return
        has_timeline = getattr(self.source, "has_capability", lambda c: True)(Capability.TIMELINE)
        if not has_timeline:
            card_title = self.tab_plan.card_title()
            if card_title:
                self.source.title = card_title
            opts = self.build_options()
            container = self.tab_plan.current_container()
            audio_only = self.tab_plan.is_audio_only()
            quality = "audio" if audio_only else self.tab_plan.current_quality()
            out_dir = self.tab_plan.current_output_dir() or opts.out_dir
            cookies_browser = opts.cookies_browser if self.tab_plan.is_cookies_enabled() else ""
            cut_text = self.tab_plan.cut_text()
            if cut_text:
                try:
                    plan = make_plan(cut_text, self.source.duration, opts.strategy, opts.full_threshold)
                except EngineError as e:
                    dialogs.warning(self, t("Cut points"), str(e))
                    return
                part_count = len(plan.parts)
                strat = {"full": "full video + split", "sections": "only the parts"}[plan.strategy]
                job_strategy = plan.strategy
            else:
                part_count = 1
                strat = "full video"
                job_strategy = "full"
            opts = replace(
                opts,
                cut_text=cut_text,
                quality=quality,
                container=container,
                out_dir=out_dir,
                cookies_browser=cookies_browser,
                strategy=job_strategy,
                keep_full=False,
                sidecar=False,
                chapters=False,
                game_markers=False,
                muted_markers=False,
                chat=False,
                chat_render=False,
                premiere_xml=False,
                premiere_plugin=False,
            )
            job = Job(self.source, opts, clips=None, client=self.client)
            label = f"{self.source.uploader or self.source.site} \u00b7 {self.source.title}"[:70]
            self.tab_queue.enqueue(job, label, part_count, strat, thumb=self._current_vod_thumb())
            self._sync_queue_badge()
            if self.settings:
                save_settings(self.settings)
            if start:
                self.tab_queue.start_queue()
            else:
                msg = t("Added to queue ({count} item(s)).", count=len(self.tab_queue.items))
                self.set_status(msg)
                notify.success(self, t("Added to queue"), label, action=(t("Go to Queue"), self.show_queue_tab))
            return

        opts = self.build_options()
        try:
            plan = make_plan(opts.cut_text, self.source.duration, opts.strategy, opts.full_threshold)
        except EngineError as e:
            dialogs.warning(self, t("Cut points"), str(e))
            return
        job = Job(self.source, opts, clips=self.clips if self.clips_loaded else None, client=self.client)
        label = f"{self.source.uploader} \u00b7 {self.source.title}"[:70]
        strat = {"full": "full VOD + split", "sections": "only the parts"}[plan.strategy]
        self.tab_queue.enqueue(job, label, len(plan.parts), strat, thumb=self._current_vod_thumb())
        self._sync_queue_badge()
        if self.settings:
            save_settings(self.settings)
        if start:
            self.tab_queue.start_queue()
        else:
            msg = t("Added to queue ({count} item(s)).", count=len(self.tab_queue.items))
            self.set_status(msg)
            notify.success(self, t("Added to queue"), label, action=(t("Go to Queue"), self.show_queue_tab))
