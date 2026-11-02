"""The Search tab (Phase 4): find a streamer, pick one of their VODs.

Port of ``build_search_tab``, ``update_search_state``, ``refresh_search_empty_states``, ``refresh_recent``,
``add_recent``, ``clear_recent``, ``on_search``, ``on_search_ok``, ``on_search_err``, ``on_pick_channel``,
``load_channel``, ``load_more``, ``on_videos_ok``, ``on_videos_err``, ``on_thumb`` and ``use_selected_vod``.

The tab owns the lists (models), the state of the search (``sv_*``, the generation counter ``sv_gen`` that makes
answers of an older request harmless) and the thumbnail workers. What belongs to the whole window it asks for:
  ``get_client()``     the Twitch client (or None: nobody is signed in)
  ``reload_client()``  make the client again from what is saved (a saved session that expired)
Signals: ``status_message(str)`` (status line), ``signin_requested()`` («Sign in…»), ``vod_chosen(url)`` («Use this
VOD»: the window fills the VOD entry, selects the Plan tab and presses «Get info»).

Workers (a search, a page of VODs) are plain daemon threads that report through the Bridge
(``search_ok``, ``search_err``, ``videos_ok``, ``videos_err``, ``thumb``); the slots below run on the GUI thread.
``search_channels`` and ``fetch_videos`` are looked up in this module when a worker runs, so tests replace them.
"""

from __future__ import annotations

import threading
import types

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QPushButton,
    QSizePolicy, QStackedWidget, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from core.recent import load_recent, save_recent, load_recent_searches, save_recent_searches
from core.providers import get_browsable_providers
from core.paths import MAX_RECENT
from core.search import VIDEO_KINDS
from core.i18n import N_, t, tn
from qt_ui.i18n_qt import language_bus
from luckytwitch_engine import fetch_thumbnail, fetch_videos, search_channels
from qt_ui import dialogs
from qt_ui.bridge import Bridge
from qt_ui.icons import icon
from qt_ui.search_models import (
    CHANNEL_ROW_HEIGHT, ChannelDelegate, GRID_CARD_H, GRID_CARD_W, ROW_HEIGHT, THUMB_COLUMN_WIDTH, VOD_COLUMNS,
    ChannelModel, ThumbDelegate, VodGridDelegate, VodModel,
)
from qt_ui.thumbs import ThumbFetcher
from qt_ui.widgets import Card, ComboBox, EmptyState, ScrollFrame, WrapLabel

HEADER_HEIGHT = 34  # the column headings of the VOD table; its empty-state message starts under them
LEFT_WIDTH = 242  # the two streamer cards (tkinter: lists 216 px wide inside a 12 px padding)
START_TITLE = N_("Search for a streamer, or pick one from your recent list.")
SIGNIN_TEXT = N_("Sign in with Twitch to search streamers and list their VODs.")


class VodTable(QTableView):
    """The VOD table. Double-click on a row or Enter/Return uses the VOD (``use_requested``)."""

    use_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doubleClicked.connect(self._on_double_clicked)

    def _on_double_clicked(self, index) -> None:
        if index.isValid():
            self.use_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.use_requested.emit()
            return
        super().keyPressEvent(event)


class VodGridView(QListView):
    """Grid of 16:9 VOD cards (Phase 9g, C2). Shares ``VodModel`` and ``selectionModel`` with ``VodTable``."""

    use_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("vodGrid")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setGridSize(VodGridDelegate().sizeHint(None, None))
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.doubleClicked.connect(self._on_double_clicked)

    def _on_double_clicked(self, index) -> None:
        if index.isValid():
            self.use_requested.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.use_requested.emit()
            return
        super().keyPressEvent(event)


def _channel_list(model: ChannelModel, rows: int, live_marker: bool = False) -> QListView:
    view = QListView()
    view.setModel(model)
    view.setItemDelegate(ChannelDelegate(live_marker=live_marker, parent=view))
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setUniformItemSizes(True)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    view.setMinimumHeight(rows * CHANNEL_ROW_HEIGHT + 2)  # tkinter: height=6 and 8 rows
    return view


class SearchTab(QWidget):
    status_message = Signal(str)
    signin_requested = Signal()
    vod_chosen = Signal(str)
    avatar_ready = Signal(str, str)

    def __init__(self, bridge: Bridge | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SearchTab")
        self.bridge = bridge if bridge is not None else Bridge(self)
        self.get_client = lambda: None
        self.reload_client = lambda: None
        # state of the search (names as in the tkinter app)
        self.recent = load_recent()
        self.recent_yt = load_recent_searches()
        self.sv_channel: dict | None = None
        self.sv_results: list[dict] = []
        self.sv_query = ""  # what the last search looked for (to say «no streamers found for …»)
        self.sv_loading = False  # a page of VODs is being fetched
        self.sv_cursor: str | None = None
        self.results_model = ChannelModel(live_marker=True, parent=self)
        self.recent_model = ChannelModel(parent=self)
        self.vod_model = VodModel(parent=self)
        self._gen = types.SimpleNamespace(value=0)  # the generation lives in a small object of its own, so the
        self.thumbs = ThumbFetcher(self.bridge, lambda gen=self._gen: gen.value)  # workers hold no reference to the tab

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = ScrollFrame(8, self)  # scrolls when the window is too short, like the tkinter ScrollFrame
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # nothing decorative in the Tab order
        self.scroll.body_layout.setSpacing(0)
        outer.addWidget(self.scroll)
        self._build_search_row()
        self._build_signin_bar()
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 10, 0, 0)
        columns.setSpacing(12)
        columns.addWidget(self._build_left())
        columns.addWidget(self._build_right(), 1)
        self.scroll.body_layout.addLayout(columns, 1)
        self._tab_order()

        self.bridge.search_ok.connect(self.on_search_ok)
        self.bridge.search_err.connect(self.on_search_err)
        self.bridge.videos_ok.connect(self.on_videos_ok)
        self.bridge.videos_err.connect(self.on_videos_err)
        self.bridge.thumb.connect(self.on_thumb)
        self.avatar_ready.connect(self._on_avatar_ready)
        self.results_view.selectionModel().selectionChanged.connect(self._results_selected)
        self.recent_view.selectionModel().selectionChanged.connect(self._recent_selected)
        self.refresh_recent()  # fills the recent list and shows the empty-state messages
        self.update_search_state()
        language_bus().changed.connect(self.refresh_language)

    # ---------------------------- building ---------------------------- #
    def _build_search_row(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.provider_label = QLabel(t("Provider:"))
        row.addWidget(self.provider_label)
        self.provider_combo = ComboBox()
        for prov in get_browsable_providers():
            self.provider_combo.addItem(prov.display_name, prov.name)
        self.provider_combo.setSizeAdjustPolicy(ComboBox.SizeAdjustPolicy.AdjustToContents)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        row.addWidget(self.provider_combo)

        has_multiple_browsable = len(get_browsable_providers()) > 1
        self.provider_label.setVisible(has_multiple_browsable)
        self.provider_combo.setVisible(has_multiple_browsable)

        self.streamer_label = QLabel(t("Streamer:"))
        row.addWidget(self.streamer_label)
        self.search_edit = QLineEdit()
        self.search_edit.returnPressed.connect(self.on_search)
        row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton(t("Search"))
        self.search_btn.setProperty("variant", "accent")
        self.search_btn.clicked.connect(self.on_search)
        row.addWidget(self.search_btn)
        self.scroll.body_layout.addLayout(row)

    def _build_signin_bar(self) -> None:
        """Shown while not signed in: a tinted banner with the way out."""
        self.signin_bar = QFrame()
        self.signin_bar.setObjectName("signinBar")
        self.signin_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self.signin_bar)
        row.setContentsMargins(14, 8, 14, 8)
        self.signin_label = QLabel(t(SIGNIN_TEXT))
        row.addWidget(self.signin_label, 1)
        self.signin_btn = QPushButton(t("Sign in…"))
        self.signin_btn.setProperty("variant", "accent")
        self.signin_btn.clicked.connect(self.signin_requested.emit)
        row.addWidget(self.signin_btn)
        holder = QVBoxLayout()
        holder.setContentsMargins(0, 8, 0, 0)
        holder.addWidget(self.signin_bar)
        self.scroll.body_layout.addLayout(holder)

    def _build_left(self) -> QWidget:
        """Found channels and recent streamers."""
        left = QWidget()
        left.setFixedWidth(LEFT_WIDTH)
        box = QVBoxLayout(left)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        self.results_card = Card(t("Results"), t("● = live now"), padding=12)
        self.results_view = _channel_list(self.results_model, 6, live_marker=True)
        self.results_card.add_widget(self.results_view)
        box.addWidget(self.results_card)
        self.recent_card = Card(t("Recent streamers"), t("The ones you opened lately"), padding=12)
        self.recent_view = _channel_list(self.recent_model, 8)
        self.recent_card.add_widget(self.recent_view)
        self.recent_card.body_layout.setStretchFactor(self.recent_view, 1)
        self.clear_recent_btn = QPushButton(t("Clear recent"))
        self.clear_recent_btn.setProperty("variant", "ghost")
        self.clear_recent_btn.clicked.connect(self.clear_recent)
        clear_row = QHBoxLayout()
        clear_row.setContentsMargins(0, 6, 0, 0)
        clear_row.addStretch(1)
        clear_row.addWidget(self.clear_recent_btn)
        self.recent_card.body_layout.addLayout(clear_row)
        box.addWidget(self.recent_card, 1)
        self.ch_empty = EmptyState(self.results_view, compact=True)
        self.recent_empty = EmptyState(self.recent_view, compact=True)
        return left

    def _build_right(self) -> QWidget:
        """The VODs of the picked streamer."""
        self.view_mode = "list"
        self.vod_filter_text = ""
        right = QWidget()
        box = QVBoxLayout(right)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 6)
        head.setSpacing(6)
        self.title_label = WrapLabel(t(START_TITLE))
        self.title_label.setProperty("role", "heading")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)
        head.addWidget(self.title_label, 1)  # at the minimum window width the title wraps, the list never gets cut

        self.vod_filter_edit = QLineEdit()
        self.vod_filter_edit.setPlaceholderText(t("Filter titles…"))
        self.vod_filter_edit.setClearButtonEnabled(True)
        self.vod_filter_edit.setMaximumWidth(170)
        self.vod_filter_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.vod_filter_edit.textChanged.connect(self.set_vod_filter)
        head.addWidget(self.vod_filter_edit, 0, Qt.AlignmentFlag.AlignTop)

        self.pin_btn = QToolButton()
        self.pin_btn.setIcon(icon("flag", 16))
        self.pin_btn.setToolTip(t("Pin streamer to Watch List"))
        self.pin_btn.setAccessibleName(t("Toggle watch list pin for streamer"))
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_btn.clicked.connect(self._toggle_pin)
        head.addWidget(self.pin_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.list_mode_btn = QToolButton()
        self.list_mode_btn.setIcon(icon("list-view", 16))
        self.list_mode_btn.setToolTip(t("List view"))
        self.list_mode_btn.setAccessibleName(t("Switch to list table view"))
        self.list_mode_btn.setCheckable(True)
        self.list_mode_btn.setChecked(True)
        self.list_mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_mode_btn.clicked.connect(lambda: self.set_view_mode("list"))
        head.addWidget(self.list_mode_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.grid_mode_btn = QToolButton()
        self.grid_mode_btn.setIcon(icon("grid", 16))
        self.grid_mode_btn.setToolTip(t("Grid view"))
        self.grid_mode_btn.setAccessibleName(t("Switch to grid card view"))
        self.grid_mode_btn.setCheckable(True)
        self.grid_mode_btn.setChecked(False)
        self.grid_mode_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_mode_btn.clicked.connect(lambda: self.set_view_mode("grid"))
        head.addWidget(self.grid_mode_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.type_combo = ComboBox()
        for k in VIDEO_KINDS:
            self.type_combo.addItem(t(k), k)
        self.type_combo.setMinimumContentsLength(16)
        self.type_combo.setSizeAdjustPolicy(ComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.type_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.type_combo.activated.connect(self._on_kind_chosen)
        head.addWidget(self.type_combo, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(head)

        self.vod_stack = QStackedWidget()
        self.vod_table = VodTable()
        self.vod_table.setObjectName("vodTable")
        self.vod_table.setModel(self.vod_model)
        self.vod_table.setItemDelegateForColumn(0, ThumbDelegate(self.vod_table))
        self.vod_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vod_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.vod_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vod_table.setShowGrid(False)
        self.vod_table.setWordWrap(False)
        self.vod_table.verticalHeader().hide()
        self.vod_table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        head_view = self.vod_table.horizontalHeader()
        head_view.setFixedHeight(HEADER_HEIGHT)
        head_view.setHighlightSections(False)
        head_view.setSectionsClickable(False)
        for col, (_key, _text, width, _anchor, stretch) in enumerate(VOD_COLUMNS):
            head_view.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch if stretch else QHeaderView.ResizeMode.Fixed)
            if not stretch:
                head_view.resizeSection(col, width)
        self.vod_table.setMinimumHeight(HEADER_HEIGHT + 5 * ROW_HEIGHT // 2)  # tkinter: height=5 rows, then it grows
        self.vod_table.use_requested.connect(self.use_selected_vod)
        self.vod_table.verticalScrollBar().valueChanged.connect(self._on_vod_scroll)

        self.vod_grid = VodGridView()
        self.vod_grid.setModel(self.vod_model)
        self.vod_grid.setSelectionModel(self.vod_table.selectionModel())
        self.vod_grid.setItemDelegate(VodGridDelegate(self.vod_grid))
        self.vod_grid.use_requested.connect(self.use_selected_vod)
        self.vod_grid.verticalScrollBar().valueChanged.connect(self._on_vod_scroll)

        self.vod_stack.addWidget(self.vod_table)
        self.vod_stack.addWidget(self.vod_grid)
        box.addWidget(self.vod_stack, 1)
        self.sv_empty = EmptyState(self.vod_table, top=HEADER_HEIGHT)  # under the column headings

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.setSpacing(12)
        self.more_btn = QPushButton(t("Load more"))
        self.more_btn.setEnabled(False)
        self.more_btn.clicked.connect(self.load_more)
        buttons.addWidget(self.more_btn)
        buttons.addStretch(1)
        self.use_hint = QLabel(t("Double-click a VOD to use it"))
        self.use_hint.setProperty("role", "muted")
        buttons.addWidget(self.use_hint)
        self.use_btn = QPushButton(t("Use this VOD"))
        self.use_btn.setProperty("variant", "accent")
        self.use_btn.clicked.connect(self.use_selected_vod)
        buttons.addWidget(self.use_btn)
        box.addLayout(buttons)
        return right

    def _tab_order(self) -> None:
        """The order the widgets were made in is the order of the keyboard: nothing decorative takes focus."""
        chain = [self.search_edit, self.search_btn]
        if hasattr(self, "provider_combo") and self.provider_combo.isVisible():
            chain.insert(0, self.provider_combo)
        chain.extend([self.signin_btn, self.results_view, self.recent_view,
                      self.clear_recent_btn, self.type_combo, self.vod_table, self.more_btn, self.use_btn])
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

    # ---------------------------- state ---------------------------- #
    def current_provider_name(self) -> str:
        if hasattr(self, "provider_combo"):
            data = self.provider_combo.currentData()
            if data:
                return str(data)
        return "twitch"

    def set_provider(self, name: str) -> None:
        if not hasattr(self, "provider_combo"):
            return
        idx = self.provider_combo.findData(name)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

    def _on_provider_changed(self, _idx: int = 0) -> None:
        prov = self.current_provider_name()
        is_twitch = (prov == "twitch")
        if hasattr(self, "streamer_label") and self.streamer_label:
            self.streamer_label.setText(t("Streamer:") if is_twitch else t("Search:"))
        if hasattr(self, "search_edit") and self.search_edit:
            self.search_edit.setPlaceholderText("" if is_twitch else t("Search videos or enter @channel…"))
        if hasattr(self, "type_combo") and self.type_combo:
            self.type_combo.setVisible(is_twitch)
        if hasattr(self, "results_card") and self.results_card:
            self.results_card.setVisible(is_twitch)
        if hasattr(self, "recent_card") and self.recent_card and self.recent_card.title_label:
            self.recent_card.title_label.setText(t("Recent streamers") if is_twitch else t("Recent searches"))
        if hasattr(self, "use_btn") and self.use_btn:
            self.use_btn.setText(t("Use this VOD") if is_twitch else t("Use this video"))
        if hasattr(self, "use_hint") and self.use_hint:
            self.use_hint.setText(t("Double-click a VOD to use it") if is_twitch else t("Double-click a video to use it"))

        self.vod_model.clear()
        self.sv_channel = None
        self.sv_cursor = None
        self.sv_query = ""

        if is_twitch:
            self.recent_model.set_channels(self.recent)
            self.update_search_state()
            self.set_title(t(START_TITLE))
        else:
            self.recent_model.set_channels(self.recent_yt)
            self.signin_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            self.set_title(t("Search YouTube for videos or channels."))
            self.refresh_search_empty_states()

    @property
    def client(self):
        return self.get_client()

    @property
    def sv_gen(self) -> int:
        """Bumped on every new channel / kind: answers of older requests are ignored."""
        return self._gen.value

    @sv_gen.setter
    def sv_gen(self, value: int) -> None:
        self._gen.value = value

    @property
    def sv_videos(self) -> list[dict]:
        return self.vod_model.videos

    @property
    def sv_type(self) -> str:
        return self.type_combo.currentData() or self.type_combo.currentText()

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def update_search_state(self) -> None:
        """Show the «sign in» warning (and disable searching) while there is no Twitch session."""
        if self.current_provider_name() != "twitch":
            self.signin_bar.setVisible(False)
            self.search_btn.setEnabled(True)
            self.refresh_search_empty_states()
            return
        signed_in = bool(self.client)
        self.signin_bar.setVisible(not signed_in)
        self.search_btn.setEnabled(signed_in)
        self.refresh_search_empty_states()
        if signed_in:
            if self.recent:
                self._spawn_avatar_fetch(self.recent, for_results=False)
            if self.sv_results:
                self._spawn_avatar_fetch(self.sv_results, for_results=True)

    def refresh_search_empty_states(self) -> None:
        """Show a friendly message over each list of the tab that has nothing in it (and only then)."""
        is_twitch = (self.current_provider_name() == "twitch")
        # the VODs of the picked streamer / search
        if self.sv_videos:
            self.sv_empty.hide_message()
        elif self.sv_loading:
            msg = t("Loading VODs…") if is_twitch else t("Searching YouTube…")
            self.sv_empty.show_message(msg, t("One moment."))
        elif is_twitch and not self.client and self.sv_channel is None:
            self.sv_empty.show_message(
                t("Sign in to browse VODs"),
                t("Use the «Sign in…» button above. Or paste a VOD link at the top and press «Get info»: that works without signing in."))
        elif is_twitch and self.sv_channel is None:
            self.sv_empty.show_message(
                t("Pick a streamer"),
                t("Search for a name above, or choose one from your recent streamers. You can also paste a VOD link at the top and press «Get info»."))
        elif not is_twitch and self.sv_channel is None:
            self.sv_empty.show_message(
                t("Search YouTube"),
                t("Search for videos or enter a channel name or handle above."))
        else:
            if is_twitch:
                self.sv_empty.show_message(
                    t("No {kind} found", kind=t(self.sv_type).lower()),
                    t("Twitch deletes VODs after a while, and some streamers don't save them. Try another kind of video in the list above."))
            else:
                self.sv_empty.show_message(
                    t("No videos found"),
                    t("Try a different search query or check the channel handle."))

        # the search results
        if is_twitch:
            if self.sv_results:
                self.ch_empty.hide_message()
            elif self.sv_query:
                self.ch_empty.show_message(t("No streamers found for «{query}»", query=self.sv_query), t("Check the spelling."))
            else:
                self.ch_empty.show_message("", t("Search results show up here."))

        # the recent streamers / searches
        active_recent = self.recent if is_twitch else self.recent_yt
        if active_recent:
            self.recent_empty.hide_message()
        else:
            hint = t("Streamers you open show up here.") if is_twitch else t("Searches you run show up here.")
            self.recent_empty.show_message("", hint)
        self.clear_recent_btn.setEnabled(bool(active_recent))

    # ---------------------------- recent streamers ---------------------------- #
    def refresh_recent(self) -> None:
        if self.current_provider_name() == "twitch":
            self.recent_model.set_channels(self.recent)
            if self.client and self.recent:
                self._spawn_avatar_fetch(self.recent, for_results=False)
        else:
            self.recent_model.set_channels(self.recent_yt)
        self.refresh_search_empty_states()

    def add_recent(self, ch: dict) -> None:
        entry = {"id": ch["id"], "login": ch.get("login", ""), "name": ch.get("name") or ch.get("login", "")}
        self.recent = ([entry] + [c for c in self.recent if c["id"] != entry["id"]])[:MAX_RECENT]
        save_recent(self.recent)
        self.refresh_recent()

    def add_recent_yt(self, query: str) -> None:
        entry = {"id": query, "login": query, "name": query}
        self.recent_yt = ([entry] + [c for c in self.recent_yt if c["id"] != entry["id"]])[:MAX_RECENT]
        save_recent_searches(self.recent_yt)
        if self.current_provider_name() == "youtube":
            self.refresh_recent()

    def clear_recent(self) -> None:
        if self.current_provider_name() == "twitch":
            self.recent = []
            save_recent(self.recent)
        else:
            self.recent_yt = []
            save_recent_searches(self.recent_yt)
        self.refresh_recent()

    # ---------------------------- searching ---------------------------- #
    def on_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        if self.current_provider_name() == "youtube":
            self.sv_gen += 1
            gen = self.sv_gen
            self.sv_loading = True
            self.sv_channel = {"id": query, "name": query}
            self.vod_model.clear()
            self.search_btn.setEnabled(False)
            self.refresh_search_empty_states()
            self.status_message.emit(t("Searching YouTube for «{query}»…", query=query))
            self.set_title(t("YouTube: searching «{query}»…", query=query))
            self.add_recent_yt(query)
            bridge = self.bridge

            def work_yt():
                try:
                    from core.providers import YOUTUBE_PROVIDER
                    if query.startswith(("@", "http://", "https://", "youtube.com/")):
                        videos, cursor = YOUTUBE_PROVIDER.fetch_channel_videos(query)
                    else:
                        videos = YOUTUBE_PROVIDER.search_videos(query)
                        cursor = None
                except Exception as e:
                    bridge.videos_err.emit(gen, str(e))
                    return
                bridge.videos_ok.emit(gen, videos, cursor)

            threading.Thread(target=work_yt, daemon=True).start()
            return

        if not self.client:
            self.update_search_state()
            self.status_message.emit(t("Sign in with Twitch to search (use the «Sign in…» button)."))
            return
        self.search_btn.setEnabled(False)
        self.status_message.emit(t("Searching for «{query}»…", query=query))
        client, bridge = self.client, self.bridge

        def work():
            try:
                results = search_channels(client, query)
            except Exception as e:  # noqa: BLE001
                bridge.search_err.emit(str(e))
                return
            bridge.search_ok.emit(query, results)

        threading.Thread(target=work, daemon=True).start()

    def on_search_ok(self, query: str, results: list[dict]) -> None:
        self.search_btn.setEnabled(bool(self.client))
        self.sv_results = results
        self.sv_query = query
        self.results_model.set_channels(results)
        self.refresh_search_empty_states()
        if not results:
            self.status_message.emit(t("No streamers found for «{query}».", query=query))
            return
        self.status_message.emit(tn("{n} streamer found. Pick one to see their VODs.", "{n} streamers found. Pick one to see their VODs.", len(results)))
        if results[0]["login"].lower() == query.lstrip("@").lower():
            self.select_channel(self.results_view, 0)  # exact match: open it straight away
        self._spawn_avatar_fetch(results, for_results=True)

    def on_search_err(self, msg: str) -> None:
        self.search_btn.setEnabled(bool(self.client))
        self.status_message.emit(t("Search failed."))
        if "sign in" in msg.lower():  # the saved session expired: refresh what the tab shows
            self.reload_client()
            self.update_search_state()
        dialogs.error(self, t("Search"), msg)

    # ---------------------------- picking a streamer ---------------------------- #
    @staticmethod
    def select_channel(view: QListView, row: int) -> None:
        """Select a row like a click does (this loads that streamer's VODs through ``_on_pick``)."""
        index = view.model().index(row, 0)
        view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        view.setCurrentIndex(index)

    def _results_selected(self, *_args) -> None:
        self._on_pick(True)

    def _recent_selected(self, *_args) -> None:
        self._on_pick(False)

    def _on_pick(self, from_results: bool) -> None:
        view, other = (self.results_view, self.recent_view) if from_results else (self.recent_view, self.results_view)
        rows = view.selectionModel().selectedRows()
        if not rows:
            return
        if self.current_provider_name() == "youtube":
            ch = self.recent_yt[rows[0].row()]
            self.search_edit.setText(ch["name"])
            self.on_search()
            return
        ch = (self.sv_results if from_results else self.recent)[rows[0].row()]
        other.selectionModel().clearSelection()
        self.load_channel(ch)

    def _on_kind_chosen(self, _index: int) -> None:
        if self.sv_channel:
            self.load_channel(self.sv_channel, remember=False)

    def load_channel(self, ch: dict, remember: bool = True, more: bool = False) -> None:
        """Load the first page of a streamer's VODs (or the next page when ``more``)."""
        if not self.client:
            self.update_search_state()
            self.status_message.emit(t("Sign in with Twitch to list VODs (use the «Sign in…» button)."))
            return
        if more:
            gen = self.sv_gen
        else:
            self.sv_gen += 1
            gen = self.sv_gen
            self.sv_channel = ch
            self._sync_pin()
            self.sv_cursor = None
            self.vod_model.clear()
            if remember:
                self.add_recent(ch)
        kind = VIDEO_KINDS.get(self.sv_type, "archive")
        after = self.sv_cursor if more else None
        self.more_btn.setEnabled(False)
        self.sv_loading = True
        self.refresh_search_empty_states()
        self.set_title(t("{name}: loading…", name=ch['name']))
        client, bridge = self.client, self.bridge

        def work():
            try:
                videos, cursor = fetch_videos(client, ch["id"], kind, after=after)
            except Exception as e:  # noqa: BLE001
                bridge.videos_err.emit(gen, str(e))
                return
            bridge.videos_ok.emit(gen, videos, cursor)

        threading.Thread(target=work, daemon=True).start()

    def load_more(self) -> None:
        if self.sv_channel and self.sv_cursor:
            self.load_channel(self.sv_channel, more=True)

    def set_view_mode(self, mode: str) -> None:
        """Switch between ``'list'`` (table) and ``'grid'`` (16:9 cards) (Phase 9g, C2)."""
        if mode not in ("list", "grid"):
            return
        self.view_mode = mode
        is_grid = mode == "grid"
        self.list_mode_btn.setChecked(not is_grid)
        self.grid_mode_btn.setChecked(is_grid)
        self.vod_stack.setCurrentWidget(self.vod_grid if is_grid else self.vod_table)

    def set_vod_filter(self, text: str) -> None:
        """Filter loaded VOD rows client-side by title or date substring (Phase 9g, C4)."""
        self.vod_filter_text = text.strip().lower()
        self._apply_vod_filter()

    def _apply_vod_filter(self) -> None:
        q = self.vod_filter_text
        for row, v in enumerate(self.sv_videos):
            hay = f"{v.get('title', '')} {v.get('date', '')}".lower()
            hide = bool(q and q not in hay)
            self.vod_table.setRowHidden(row, hide)
            self.vod_grid.setRowHidden(row, hide)

    def visible_vod_rows(self) -> list[int]:
        return [r for r in range(self.vod_model.rowCount()) if not self.vod_table.isRowHidden(r)]

    def _on_vod_scroll(self, value: int) -> None:
        """Infinite scroll (C4): when the user scrolls to the bottom of the VOD view, automatically load more."""
        bar = self.vod_grid.verticalScrollBar() if self.view_mode == "grid" else self.vod_table.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 8 and self.sv_cursor and not self.sv_loading:
            self.load_more()

    def on_videos_ok(self, gen: int, videos: list[dict], cursor: str | None) -> None:
        if gen != self.sv_gen or not self.sv_channel:
            return  # the user already picked something else
        self.sv_loading = False
        start = self.vod_model.append(videos)
        for i, v in enumerate(videos):
            if v["thumb"]:
                self.thumbs.submit(gen, str(start + i), v["thumb"])
        self._apply_vod_filter()
        self.sv_cursor = cursor
        self.more_btn.setEnabled(bool(cursor))
        name = self.sv_channel["name"]
        self.refresh_search_empty_states()
        if self.current_provider_name() == "youtube":
            self.search_btn.setEnabled(True)
            self.status_message.emit(t("YouTube search complete."))
            n = len(self.sv_videos)
            if n == 0:
                self.set_title(t("No videos found for «{query}»", query=name))
            else:
                vid_txt = tn("{n} video", "{n} videos", n)
                self.set_title(f"{name}  ·  {vid_txt}")
            return
        if not self.sv_videos:
            self.set_title(t("{name}: no {kind} found", name=name, kind=t(self.sv_type).lower()))
        else:
            n = len(self.sv_videos)
            vod_txt = tn("{n} VOD", "{n} VODs", n)
            more_txt = f"  ·  {t('more available')}" if cursor else ""
            self.set_title(f"{name}  ·  {vod_txt}{more_txt}")

    def on_videos_err(self, gen: int, msg: str) -> None:
        if gen != self.sv_gen:
            return
        self.sv_loading = False
        if self.current_provider_name() == "youtube":
            self.search_btn.setEnabled(True)
        self.refresh_search_empty_states()
        self.set_title(t("Could not load the VODs."))
        self.status_message.emit(t("Could not load the VODs."))
        if "sign in" in msg.lower():
            self.reload_client()
            self.update_search_state()
        dialogs.error(self, t("Search"), msg)

    def on_thumb(self, gen: int, iid: str, path: str) -> None:
        """A thumbnail was fetched to disk: build its pixmap here, on the GUI thread."""
        if gen != self.sv_gen:
            return
        self.vod_model.set_thumb(iid, path)

    # ---------------------------- using a VOD ---------------------------- #
    def selected_video(self) -> dict | None:
        idxs = self.vod_table.selectionModel().selectedIndexes()
        return self.sv_videos[idxs[0].row()] if idxs else None

    def select_vod(self, row: int) -> None:
        index = self.vod_model.index(row, 0)
        self.vod_table.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        self.vod_table.setCurrentIndex(index)

    def use_selected_vod(self) -> None:
        video = self.selected_video()
        if video is None:
            is_twitch = (self.current_provider_name() == "twitch")
            title = t("Select a VOD") if is_twitch else t("Select a video")
            msg = t("Select a VOD in the list first.") if is_twitch else t("Select a video in the list first.")
            dialogs.info(self, title, msg)
            return
        self.vod_chosen.emit(video["url"])


    def _on_avatar_ready(self, cid: str, path: str) -> None:
        """Invoked on the GUI thread when a channel avatar image is ready on disk."""
        if getattr(self, "_closing", False):
            return
        from qt_ui.search_models import load_avatar
        pix = load_avatar(path)
        if pix is not None and not pix.isNull():
            self.results_model.set_avatar(cid, pix)
            self.recent_model.set_avatar(cid, pix)

    def _spawn_avatar_fetch(self, channels: list[dict], for_results: bool = True) -> None:
        if not self.client or not channels:
            return
        client = self.client
        model = self.results_model if for_results else self.recent_model
        needed = [c for c in channels if c.get("id") and not model.has_avatar(str(c["id"]))]
        if not needed:
            return

        threading.Thread(target=_fetch_channel_avatars,
                         args=(client, list(needed), self.avatar_ready.emit, lambda: not getattr(self, "_closing", False)),
                         daemon=True).start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        from PySide6.QtCore import QTimer
        def focus_search():
            if not getattr(self, "_closing", False) and hasattr(self, "search_edit"):
                self.search_edit.setFocus()
                self.search_edit.selectAll()
        QTimer.singleShot(0, focus_search)

    def shutdown(self) -> None:
        """The window is closing: the thumbnail threads end."""
        self._closing = True
        self.thumbs.stop()

    def _toggle_pin(self) -> None:
        from core import watchlist
        if not self.sv_channel:
            return
        login = str(self.sv_channel.get("login") or "").lower().strip()
        name = str(self.sv_channel.get("name") or login)
        if watchlist.is_watched(login):
            watchlist.remove_from_watchlist(login)
        else:
            watchlist.add_to_watchlist(login, name)
        self._sync_pin()

    def _sync_pin(self) -> None:
        if not hasattr(self, "pin_btn"):
            return
        from core import watchlist
        login = str(self.sv_channel.get("login") or "").lower().strip() if self.sv_channel else ""
        watched = bool(login and watchlist.is_watched(login))
        self.pin_btn.setChecked(watched)
        self.pin_btn.setToolTip(t("Unpin streamer from Watch List") if watched else t("Pin streamer to Watch List"))

    def refresh_language(self) -> None:
        """Update SearchTab text labels dynamically when language changes."""
        if hasattr(self, "provider_label") and self.provider_label:
            self.provider_label.setText(t("Provider:"))
        is_twitch = (self.current_provider_name() == "twitch")
        if hasattr(self, "streamer_label") and self.streamer_label:
            self.streamer_label.setText(t("Streamer:") if is_twitch else t("Search:"))
        if hasattr(self, "search_edit") and self.search_edit:
            self.search_edit.setPlaceholderText("" if is_twitch else t("Search videos or enter @channel…"))
        if hasattr(self, "search_btn") and self.search_btn:
            self.search_btn.setText(t("Search"))
        if hasattr(self, "signin_label") and self.signin_label:
            self.signin_label.setText(t(SIGNIN_TEXT))
        if hasattr(self, "signin_btn") and self.signin_btn:
            self.signin_btn.setText(t("Sign in…"))
        if hasattr(self, "results_card") and self.results_card:
            if self.results_card.title_label:
                self.results_card.title_label.setText(t("Results"))
            if self.results_card.subtitle_label:
                self.results_card.subtitle_label.setText(t("● = live now"))
        if hasattr(self, "recent_card") and self.recent_card:
            if self.recent_card.title_label:
                self.recent_card.title_label.setText(t("Recent streamers") if is_twitch else t("Recent searches"))
            if self.recent_card.subtitle_label:
                self.recent_card.subtitle_label.setText(t("The ones you opened lately"))
        if hasattr(self, "clear_recent_btn") and self.clear_recent_btn:
            self.clear_recent_btn.setText(t("Clear recent"))
        if hasattr(self, "vod_filter_edit") and self.vod_filter_edit:
            self.vod_filter_edit.setPlaceholderText(t("Filter titles…"))
        if hasattr(self, "pin_btn") and self.pin_btn:
            self.pin_btn.setAccessibleName(t("Toggle watch list pin for streamer"))
            self._sync_pin()
        if hasattr(self, "list_mode_btn") and self.list_mode_btn:
            self.list_mode_btn.setToolTip(t("List view"))
            self.list_mode_btn.setAccessibleName(t("Switch to list table view"))
        if hasattr(self, "grid_mode_btn") and self.grid_mode_btn:
            self.grid_mode_btn.setToolTip(t("Grid view"))
            self.grid_mode_btn.setAccessibleName(t("Switch to grid card view"))
        if hasattr(self, "more_btn") and self.more_btn:
            self.more_btn.setText(t("Load more"))
        if hasattr(self, "use_hint") and self.use_hint:
            self.use_hint.setText(t("Double-click a VOD to use it") if is_twitch else t("Double-click a video to use it"))
        if hasattr(self, "use_btn") and self.use_btn:
            self.use_btn.setText(t("Use this VOD") if is_twitch else t("Use this video"))
        if hasattr(self, "type_combo") and self.type_combo:
            cur_data = self.type_combo.currentData()
            self.type_combo.blockSignals(True)
            self.type_combo.clear()
            for k in VIDEO_KINDS:
                self.type_combo.addItem(t(k), k)
            idx = self.type_combo.findData(cur_data)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
            self.type_combo.blockSignals(False)
        if hasattr(self, "vod_model") and self.vod_model:
            self.vod_model.refresh_language()
        if self.sv_channel is None and not self.sv_videos:
            self.set_title(t(START_TITLE) if is_twitch else t("Search YouTube for videos or channels."))
        elif self.sv_channel and not self.sv_videos and not self.sv_loading:
            if is_twitch:
                self.set_title(t("{name}: no {kind} found", name=self.sv_channel["name"], kind=t(self.sv_type).lower()))
            else:
                self.set_title(t("No videos found for «{query}»", query=self.sv_channel["name"]))
        elif self.sv_channel and self.sv_videos:
            n = len(self.sv_videos)
            if is_twitch:
                vod_txt = tn("{n} VOD", "{n} VODs", n)
                more_txt = f"  ·  {t('more available')}" if self.sv_cursor else ""
                self.set_title(f"{self.sv_channel['name']}  ·  {vod_txt}{more_txt}")
            else:
                vid_txt = tn("{n} video", "{n} videos", n)
                self.set_title(f"{self.sv_channel['name']}  ·  {vid_txt}")
        self.refresh_search_empty_states()
        if hasattr(self, "vod_grid") and self.vod_grid:
            self.vod_grid.viewport().update()
        if hasattr(self, "vod_table") and self.vod_table:
            self.vod_table.viewport().update()



def _fetch_channel_avatars(client, channels: list[dict], on_avatar_cb, is_active_cb) -> None:
    """Background worker: fetches Twitch profile pictures for channels and invokes on_avatar_cb(cid, path)."""
    if not client or not channels:
        return
    uids = [str(c.get("id")) for c in channels if c.get("id")]
    if not uids:
        return
    try:
        # Helix /users endpoint accepts multiple id params: ?id=1&id=2...
        # In requests, passing params={"id": [u1, u2, ...]} produces ?id=u1&id=u2...
        # Twitch Helix accepts up to 100 IDs per request.
        for i in range(0, len(uids), 100):
            if not is_active_cb():
                return
            batch = uids[i:i + 100]
            data = client.get("users", {"id": batch}).get("data", [])
            for u in data:
                if not is_active_cb():
                    return
                uid = str(u.get("id", ""))
                pic_url = u.get("profile_image_url")
                if uid and pic_url:
                    path = fetch_thumbnail(pic_url)
                    if path and is_active_cb():
                        on_avatar_cb(uid, str(path))
    except Exception:
        pass


BrowseTab = SearchTab
__all__ = ["BrowseTab", "SearchTab"]



