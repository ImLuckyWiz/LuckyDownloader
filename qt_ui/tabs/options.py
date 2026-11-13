"""The Options tab (Phase 5): a sidebar with one section visible at a time (Output, Cuts, Chapters, Premiere Pro,
Chat, Clips, Tools). Port of ``ui/options_tab.py`` (same texts, same order, same split between up-front and Advanced).

Each setting is a row (bold name, one-line hint, the control on the right); on/off settings are switches, long
explanations live in the little «i» tooltips, and settings that are set once and rarely touched sit in a collapsed
«Advanced» area inside their section. Template fields (file name, stream folder, clip name, chapter title) get
clickable ``{token}`` chips and a live example computed by the engine's own naming functions (``core.examples``).

Every control is bound to a key of the settings dictionary by a ``SettingsBinder`` (the key names are the ones the
tkinter app saved). The tab edits the dictionary and tells the window what it needs through signals:

  ``refresh_clips_requested``   a setting the Plan tab's clip list depends on changed (tkinter ``refresh_clips``)
  ``preview_requested``         the strategy or threshold changed (tkinter ``update_preview``)
  ``output_folder_requested``   «Open folder» next to the output folder
  ``update_tools_requested``    «Update yt-dlp now»
  ``saved_chat_requested``      «Choose chat file…»
  ``status_message(str)``       a sentence for the status line

and the window tells the tab, through methods: ``set_tools_info(text)``, ``set_tools_running(bool)``,
``set_saved_chat_running(bool)``, ``refresh_name_examples()`` (also when a VOD is loaded, to use its real name) and
the hook ``source_provider`` (returns the loaded ``SourceInfo`` or None; Phase 6 sets it).
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

import weblink
from core import examples
from core.files import open_in_file_manager
from core.options import (
    COOKIES_BROWSER_NAMES, COOKIES_SCOPE_NAMES, AUDIO_FORMAT_NAMES, CHAT_RENDER_FPS_NAMES, CHAT_RENDER_LOOK_NAMES, CHAT_RENDER_TYPE_NAMES, QUALITY_NAMES,
    STRATEGY_NAMES, flag,
)
from core.settings import DEFAULTS
from core.i18n import N_, t, tn
from luckytwitch_engine import APP_DIR, CHAT_FORMATS, TOOLS_DIR
from qt_ui import dialogs, i18n_qt
from qt_ui.binder import SettingsBinder
from qt_ui.icons import icon
from qt_ui.widgets import Card, Collapsible, ComboBox, ScrollFrame, SettingRow, SideNav, SpinBox, Toggle, TokenChips, WrapLabel

SECTIONS = [
    ("output", N_("Output")),
    ("cuts", N_("Cuts")),
    ("chapters", N_("Chapters")),
    ("premiere", N_("Premiere Pro")),
    ("chat", N_("Chat")),
    ("clips", N_("Clips")),
    ("interface", N_("Interface")),
    ("tools", N_("Tools")),
]

# changing one of these redraws every «Example:» line
EXAMPLE_KEYS = {"name_template", "folder_template", "clip_name_template", "title_tpl", "container"}


def _no_source():
    return None


class OptionsTab(QWidget):
    refresh_clips_requested = Signal()
    preview_requested = Signal()
    output_folder_requested = Signal()
    update_tools_requested = Signal()
    saved_chat_requested = Signal()
    check_app_updates_requested = Signal()
    about_requested = Signal()
    status_message = Signal(str)

    def __init__(self, settings: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("OptionsTab")
        self.settings = settings if settings is not None else {}
        self.binder = SettingsBinder(self.settings, self)
        self.source_provider = _no_source
        self.sections: dict[str, QWidget] = {}
        self.advanced: dict[str, Collapsible] = {}
        self.toggles: dict[str, Toggle] = {}
        self.template_entries: dict[str, QLineEdit] = {}
        self.chip_rows: dict[str, TokenChips] = {}
        self.example_labels: dict[str, QLabel] = {}  # setting name -> its «Example:» line
        self.rows_by_key: dict[str, tuple[SettingRow, str]] = {}
        self.searchable_rows: list[dict] = []
        self.registered_cards: list[tuple[Card, str | None, str | None]] = []
        self.registered_headings: list[tuple[QLabel, WrapLabel, str, str]] = []
        self.registered_advanced: list[tuple[Collapsible, str]] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        left = QVBoxLayout()
        left.setContentsMargins(0, 8, 0, 0)
        self.nav = SideNav([(k, t(label)) for k, label in SECTIONS])
        left.addWidget(self.nav)
        left.addStretch(1)
        outer.addLayout(left)
        self.scroll = ScrollFrame(4, self)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # nothing decorative in the Tab order
        outer.addWidget(self.scroll, 1)
        body = self.scroll.body_layout
        body.setSpacing(0)

        # G1: Settings search bar at the top of the options view
        search_row = QHBoxLayout()
        search_row.setContentsMargins(4, 4, 4, 12)
        search_row.setSpacing(8)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(t("Search settings…"))
        self.search_entry.setClearButtonEnabled(True)
        self.search_entry.textChanged.connect(self._on_search_query_changed)
        search_row.addWidget(self.search_entry, 1)

        self.match_counter = QLabel("")
        self.match_counter.setProperty("role", "muted")
        self.match_counter.setVisible(False)
        search_row.addWidget(self.match_counter)
        body.addLayout(search_row)

        for key, _label in SECTIONS:
            section = QWidget()
            lay = QVBoxLayout(section)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            self.sections[key] = section
            body.addWidget(section)
        body.addStretch(1)  # spare height goes below the section, never into its cards

        self._section_output(self.sections["output"])
        self._section_cuts(self.sections["cuts"])
        self._section_chapters(self.sections["chapters"])
        self._section_premiere(self.sections["premiere"])
        self._section_chat(self.sections["chat"])
        self._section_clips(self.sections["clips"])
        self._section_interface(self.sections["interface"])
        self._section_tools(self.sections["tools"])

        self.nav.selected.connect(self.show_section)
        self.nav.select("output")
        self.binder.changed.connect(self._on_setting_changed)
        self._sync_folder_template()
        self.refresh_name_examples()
        self.refresh_changed_markers()
        i18n_qt.language_bus().changed.connect(self.refresh_language)

    # ------------------------------------------------------------------ sections
    def show_section(self, key: str) -> None:
        for k, section in self.sections.items():
            section.setVisible(k == key)
        self.scroll.scroll_to_top()

    def visible_sections(self) -> list[str]:
        return [k for k, w in self.sections.items() if not w.isHidden()]

    # ------------------------------------------------------------------ small builders
    def _heading(self, section: QWidget, title: str, subtitle: str) -> None:
        lay = section.layout()
        head = QLabel(t(title))
        head.setProperty("role", "title")
        head.setContentsMargins(4, 0, 0, 0)
        lay.addWidget(head)
        sub = WrapLabel(t(subtitle))
        sub.setProperty("role", "muted")
        sub.setMaximumWidth(640)
        sub.setContentsMargins(4, 2, 0, 10)
        lay.addWidget(sub)
        self.registered_headings.append((head, sub, title, subtitle))

    def _card(self, section: QWidget, title: str | None = None, subtitle: str | None = None) -> Card:
        card = Card(t(title) if title else None, t(subtitle) if subtitle else None)
        lay = section.layout()
        lay.addWidget(card)
        lay.addSpacing(12)
        self.registered_cards.append((card, title, subtitle))
        return card

    def _advanced(self, key: str, card: Card, hint: str) -> Collapsible:
        """The collapsed «Advanced» area at the bottom of a card."""
        adv = Collapsible(t("Advanced"), t(hint))
        card.add_widget(adv)
        self.advanced[key] = adv
        self.registered_advanced.append((adv, hint))
        return adv

    def _switch(self, row, key: str, refresh_clips: bool = False) -> Toggle:
        toggle = Toggle()
        self.binder.bind(key, toggle)
        if refresh_clips:
            toggle.clicked.connect(self.refresh_clips_requested)  # only a click by the person, like the old command
        row.add_control(toggle)
        self.toggles[key] = toggle
        return toggle

    def _entry(self, key: str, chars: int = 0) -> QLineEdit:
        entry = QLineEdit()
        if chars:
            entry.setFixedWidth(round(entry.fontMetrics().horizontalAdvance("0") * chars) + 20)
        self.binder.bind(key, entry)
        return entry

    def _spin(self, key: str, low: int, high: int, chars: int = 6) -> SpinBox:
        spin = SpinBox(low, high, chars)
        self.binder.bind(key, spin)
        return spin

    def _combo(self, key: str, values: list[str], chars: int) -> ComboBox:
        combo = ComboBox()
        combo.addItems(values)
        combo.setMinimumWidth(round(combo.fontMetrics().horizontalAdvance("0") * chars) + 40)
        self.binder.bind(key, combo)
        return combo

    def _unit(self, row, text: str) -> None:
        row.add_control(QLabel(text))

    def _template_row(self, holder, title: str, hint: str, key: str, tokens: list[str], info: str = "",
                      divider: bool = True, per_row: int = 6, section_key: str = "",
                      card: Card | None = None, adv: Collapsible | None = None) -> QLineEdit:
        """A name template: entry + clickable token chips + a live example. Returns the entry."""
        row = holder.add_row(t(title), t(hint), t(info) if info else "", divider=divider)
        entry = self._entry(key)
        chips = TokenChips(entry, tokens, per_row=per_row)
        example = WrapLabel()
        example.setProperty("role", "muted")
        example.setMaximumWidth(640)
        example.setContentsMargins(0, 2, 0, 0)
        lay = row.below_layout
        lay.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(entry)
        lay.addSpacing(8)
        lay.addWidget(chips, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(example)
        self.template_entries[key] = entry
        self.chip_rows[key] = chips
        self.example_labels[key] = example
        if section_key and card:
            self._register_setting(row, key, section_key, card, adv, raw_title=title, raw_hint=hint, raw_info=info)
        return entry

    def _register_setting(self, row: SettingRow, key: str, section_key: str, card: Card,
                          adv: Collapsible | None = None,
                          raw_title: str = "", raw_hint: str = "", raw_info: str = "") -> None:
        self.rows_by_key[key] = (row, section_key)
        info_text = row.info.text if getattr(row, "info", None) is not None else ""
        hint_text = row.hint_label.text() if getattr(row, "hint_label", None) is not None else ""
        title_text = row.title_label.text() if getattr(row, "title_label", None) is not None else ""
        search_text = f"{title_text} {hint_text} {info_text}".lower()
        en_text = f"{raw_title or title_text} {raw_hint or hint_text} {raw_info or info_text}".lower()
        self.searchable_rows.append({
            "row": row,
            "key": key,
            "section_key": section_key,
            "card": card,
            "adv": adv,
            "text": search_text,
            "en_text": en_text,
            "raw_title": raw_title or title_text,
            "raw_hint": raw_hint or hint_text,
            "raw_info": raw_info or info_text,
        })

    def _add_setting_row(self, card_or_adv, key: str, title: str, hint: str, section_key: str, card: Card,
                         adv: Collapsible | None = None, info: str = "", divider: bool = True) -> SettingRow:
        row = card_or_adv.add_row(t(title), t(hint), t(info) if info else "", divider=divider)
        self._register_setting(row, key, section_key, card, adv, raw_title=title, raw_hint=hint, raw_info=info)
        return row

    # ------------------------------------------------------------------ live examples & preview (G3)
    def example_for(self, key: str) -> str:
        """The text of the example under the template ``key`` (without «Example:»). A half-typed template never
        raises: the answer is then «(can't be shown: ...)»."""
        source = self.source_provider()
        try:
            if key == "name_template":
                return examples.example_file_name(self.settings, source)
            if key == "folder_template":
                return examples.example_folder_name(self.settings, source)
            if key == "clip_name_template":
                return examples.example_clip_name(self.settings, source)
            return examples.example_chapter(self.settings)
        except Exception as e:  # noqa: BLE001  (a half-typed template must never break the tab)
            return f"(can't be shown: {e})"

    def refresh_name_examples(self) -> None:
        """Redraw every «Example:» line (also called when a VOD is loaded, to use its real name)."""
        for key, label in self.example_labels.items():
            label.setText(t("Example:") + "  " + self.example_for(key))
        self._refresh_save_preview()

    def _refresh_save_preview(self) -> None:
        """Update the 'Files will be saved as' card (G3) with the fully resolved sample path and disk space."""
        if not hasattr(self, "save_preview_path"):
            return
        out_dir = str(self.settings.get("out_dir") or DEFAULTS["out_dir"])
        container = str(self.settings.get("container") or "mp4")
        folder_tpl = self.example_for("folder_template")
        name_tpl = self.example_for("name_template")
        subfolders = flag(self.settings, "subfolders")
        file_name = name_tpl if name_tpl.endswith(f".{container}") else f"{name_tpl}.{container}"
        if subfolders and folder_tpl and not folder_tpl.startswith("("):
            full_path = Path(out_dir) / folder_tpl / file_name
        else:
            full_path = Path(out_dir) / file_name
        self.save_preview_path.setText(str(full_path))

        try:
            target_dir = Path(out_dir)
            while not target_dir.exists() and target_dir.parent != target_dir:
                target_dir = target_dir.parent
            if target_dir.exists():
                free_bytes = shutil.disk_usage(target_dir).free
                free_gb = free_bytes / (1024 ** 3)
                self.disk_space_label.setText(t("Drive free space: {space} GB", space=i18n_qt.format_number(free_gb, 1)))
            else:
                self.disk_space_label.setText(t("Destination folder will be created on first download"))
        except Exception:
            self.disk_space_label.setText("")

    def _on_setting_changed(self, key: str) -> None:
        if key in EXAMPLE_KEYS:
            self.refresh_name_examples()
        if key == "subfolders":
            self._sync_folder_template()
        if key == "out_dir":
            self._refresh_save_preview()
        self.refresh_changed_markers()

    def refresh_changed_markers(self) -> None:
        """G2: update 'Changed from default' accent dots and SideNav count badges."""
        counts: dict[str, int] = {k: 0 for k, _ in SECTIONS}
        for key, (row, section_key) in self.rows_by_key.items():
            curr = self.settings.get(key)
            default = DEFAULTS.get(key)
            is_changed = curr is not None and default is not None and str(curr) != str(default)
            if is_changed:
                counts[section_key] = counts.get(section_key, 0) + 1

            def _make_reset(k=key, def_val=default):
                return lambda: self.binder.set(k, def_val)

            row.set_changed(is_changed, on_reset=_make_reset())

        for section_key, count in counts.items():
            self.nav.set_badge(section_key, count)

    def _on_search_query_changed(self, text: str) -> None:
        """G1: Search settings across all sections, expanding matches and updating match counter."""
        query = text.strip().lower()
        if not query:
            self.match_counter.setVisible(False)
            for item in self.searchable_rows:
                item["row"].setVisible(True)
                item["card"].setVisible(True)
            for card, _t, _s in self.registered_cards:
                card.setVisible(True)
            self.show_section(self.nav.current or "output")
            return

        matched = 0
        sections_with_matches: set[str] = set()
        cards_with_matches: set[Card] = set()

        for item in self.searchable_rows:
            matches = query in item["text"] or query in item.get("en_text", "")
            item["row"].setVisible(matches)
            if matches:
                matched += 1
                sections_with_matches.add(item["section_key"])
                cards_with_matches.add(item["card"])
                if item["adv"] is not None:
                    item["adv"].set_opened(True)

        for s_key, section_widget in self.sections.items():
            section_widget.setVisible(s_key in sections_with_matches)

        for item in self.searchable_rows:
            item["card"].setVisible(item["card"] in cards_with_matches)
        for card, _t, _s in self.registered_cards:
            card.setVisible(card in cards_with_matches)

        self.match_counter.setText(tn("{n} match", "{n} matches", matched))
        self.match_counter.setVisible(True)


    def _sync_provider_dir_display(self) -> None:
        p_key = self.provider_select_combo.currentData() or "youtube"
        pod = self.settings.get("provider_out_dirs") or {}
        custom = pod.get(p_key, "")
        self.provider_dir_entry.setText(custom)
        def_dir = str(self.settings.get("out_dir") or DEFAULTS["out_dir"])
        self.provider_dir_entry.setPlaceholderText(t("Default ({dir})", dir=def_dir))

    def _browse_provider_dir(self) -> None:
        p_key = self.provider_select_combo.currentData() or "youtube"
        pod = dict(self.settings.get("provider_out_dirs") or {})
        from core import paths
        current = pod.get(p_key, "") or str(self.settings.get("out_dir") or paths.DOWNLOADS_DIR)
        from PySide6.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(self, t("Select folder for {provider}", provider=self.provider_select_combo.currentText()), current)
        if chosen:
            pod[p_key] = chosen
            self.settings["provider_out_dirs"] = pod
            self.provider_dir_entry.setText(chosen)
            from core.settings import save_settings
            save_settings(self.settings)

    def _clear_provider_dir(self) -> None:
        p_key = self.provider_select_combo.currentData() or "youtube"
        pod = dict(self.settings.get("provider_out_dirs") or {})
        if p_key in pod:
            del pod[p_key]
            self.settings["provider_out_dirs"] = pod
            self.provider_dir_entry.setText("")
            from core.settings import save_settings
            save_settings(self.settings)

    def _sync_folder_template(self) -> None:
        """«Stream folder name» is greyed out while «Organize in subfolders» is off."""
        on = flag(self.settings, "subfolders")
        entry = self.template_entries.get("folder_template")
        if entry is not None:
            entry.setEnabled(on)
            self.chip_rows["folder_template"].set_enabled(on)

    # ------------------------------------------------------------------ Output
    def _section_output(self, f: QWidget) -> None:
        self._heading(f, N_("Output"), N_("Where the finished files go and how they are named."))

        # G3: Files will be saved as preview card
        self.save_preview_card = self._card(f, N_("Files will be saved as"), N_("Full destination path of your next download."))
        self.save_preview_card_row = self.save_preview_card.add_row(t("Destination preview"), "")
        self._register_setting(
            self.save_preview_card_row, "_preview_dest", "output", self.save_preview_card,
            raw_title="Destination preview", raw_hint="Full destination path of your next download.",
        )
        self.save_preview_path = WrapLabel("")
        self.save_preview_path.setProperty("role", "accent")
        self.save_preview_path.setMaximumWidth(640)
        self.disk_space_label = QLabel("")
        self.disk_space_label.setProperty("role", "muted")
        self.save_preview_card_row.below_layout.setContentsMargins(0, 4, 0, 0)
        self.save_preview_card_row.below_layout.addWidget(self.save_preview_path)
        self.save_preview_card_row.below_layout.addWidget(self.disk_space_label)

        card = self._card(f)

        row = self._add_setting_row(card, "out_dir", N_("Output folder"), N_("Where the finished files are saved."), "output", card)
        self.browse_btn = QPushButton(t("Browse…"))
        self.browse_btn.clicked.connect(self.pick_folder)
        row.add_control(self.browse_btn)
        self.open_folder_btn = QPushButton(t("Open folder"))
        self.open_folder_btn.clicked.connect(self.output_folder_requested)
        row.add_control(self.open_folder_btn)
        row.below_layout.setContentsMargins(0, 8, 0, 0)
        row.below_layout.addWidget(self._entry("out_dir"))

        row = self._add_setting_row(card, "container", N_("Format"), N_("Container of the finished files."), "output", card, divider=False)
        row.add_control(self._combo("container", ["mp4", "mkv"], 5))

        adv = self._advanced("output", card, N_("download threads, file and folder names"))
        row = self._add_setting_row(adv, "threads", N_("Download threads"), N_("Parallel connections per download. 8 is a good default."), "output", card, adv)
        row.add_control(self._spin("threads", 1, 32, 5))

        self._template_row(
            adv, N_("File name"), N_("How each part is called. Click a token to add it."), "name_template",
            [
                "streamer", "stream_date", "download_date", "date", "year", "month", "day", "game",
                "quality", "id", "title", "duration", "n", "total", "start", "end",
            ],
            per_row=8,
            info=N_("{stream_date} is when the stream aired, {download_date} today's date, {date} alias for stream date. "
                 "{year}, {month}, {day} are broadcast dates. {game} is the dominant game played. {duration} is the part length. "
                 "{quality} is the video quality. {n} is part number, {total} total parts, {start} and {end} part timestamps."),
            section_key="output", card=card, adv=adv)

        row = self._add_setting_row(adv, "clean_title", N_("Auto-clean titles"), N_("Strip bot commands (!links, !gsupps) and promo tags from stream titles."), "output", card, adv)
        self._switch(row, "clean_title")

        row = self._add_setting_row(adv, "subfolders", N_("Organize in subfolders"), N_("Folder / Streamer / Stream / parts."), "output", card, adv)
        self._switch(row, "subfolders")

        row = self._add_setting_row(adv, "provider_subfolders", N_("Group by provider subfolder"), N_("Save into out_dir/<Provider>/... (e.g. Downloads/YouTube/, Downloads/Twitch/)."), "output", card, adv)
        self._switch(row, "provider_subfolders")

        self.folder_entry = self._template_row(
            adv, N_("Stream folder name"), N_("Name of the folder that holds one stream's files."), "folder_template",
            [
                "streamer", "stream_date", "download_date", "date", "year", "month",
                "day", "game", "quality", "id", "title", "duration", "site", "provider",
            ],
            divider=True, per_row=7,
            info=N_("{stream_date} is when the stream aired, {download_date} today's date, {date} alias for stream date. "
                 "{year}, {month}, {day} are broadcast dates. {game} is the dominant stream game. "
                 "{duration} is the total stream length. {quality} is the video quality. "
                 "{site} or {provider} is the platform name (YouTube, Twitch, etc.)."),
            section_key="output", card=card, adv=adv)

        # Custom folder per provider
        p_row = adv.add_row(
            t("Custom folder per provider"),
            t("Override the base download directory for a specific provider (YouTube, Twitch, TikTok, etc.)."),
            divider=False,
        )
        p_box = QWidget()
        p_lay = QHBoxLayout(p_box)
        p_lay.setContentsMargins(0, 0, 0, 0)
        p_lay.setSpacing(8)

        self.provider_select_combo = ComboBox()
        for p_name, p_key in [("YouTube", "youtube"), ("Twitch", "twitch"), ("TikTok", "tiktok"), ("Instagram", "instagram"), ("Twitter / X", "twitter")]:
            self.provider_select_combo.addItem(p_name, p_key)

        self.provider_dir_entry = QLineEdit()
        self.provider_dir_entry.setPlaceholderText(t("Default ({dir})", dir=str(self.settings.get("out_dir") or DEFAULTS["out_dir"])))
        self.provider_dir_entry.setReadOnly(True)

        self.provider_dir_browse = QPushButton(t("Browse…"))
        self.provider_dir_browse.setProperty("variant", "ghost")
        self.provider_dir_browse.clicked.connect(self._browse_provider_dir)

        self.provider_dir_clear = QPushButton(t("Reset"))
        self.provider_dir_clear.setProperty("variant", "ghost")
        self.provider_dir_clear.clicked.connect(self._clear_provider_dir)

        self.provider_select_combo.currentIndexChanged.connect(self._sync_provider_dir_display)

        p_lay.addWidget(self.provider_select_combo)
        p_lay.addWidget(self.provider_dir_entry, 1)
        p_lay.addWidget(self.provider_dir_browse)
        p_lay.addWidget(self.provider_dir_clear)
        p_row.add_control(p_box)
        self._register_setting(
            p_row, "_naming_preview", "naming", card, adv,
            raw_title="Preview", raw_hint="How filenames look with the current settings.",
        )
        self._sync_provider_dir_display()

        qcard = self._card(f, N_("Quality"), N_("What to download when a VOD offers several qualities (Twitch VODs)."))
        row = self._add_setting_row(
            qcard, "default_quality", N_("Default quality"), N_("Used when you load a VOD. You can change it for each VOD on the Plan tab."), "output", qcard,
            info=N_("Best available is the highest quality Twitch offers. If a VOD does not have the chosen quality, the "
                 "closest lower one is used. Audio only downloads just the sound."))
        row.add_control(self._combo("default_quality", QUALITY_NAMES, 16))
        row = self._add_setting_row(
            qcard, "audio_format", N_("Audio-only file"), N_("How the sound is saved when the quality is Audio only."), "output", qcard, divider=False,
            info=N_("m4a keeps Twitch's own audio exactly as it is (no re-encoding). mp3 converts it with ffmpeg "
                 "(192 kbit/s) and plays everywhere."))
        row.add_control(self._combo("audio_format", AUDIO_FORMAT_NAMES, 26))

    # ------------------------------------------------------------------ Cuts
    def _section_cuts(self, f: QWidget) -> None:
        self._heading(f, N_("Cuts"), N_("How the VOD is downloaded and cut into parts."))
        card = self._card(f)

        row = self._add_setting_row(
            card, "strategy", N_("Strategy"), N_("How the VOD is downloaded."), "cuts", card,
            info=N_("Auto: downloads the full VOD once and splits it when the parts cover at least the "
                 "threshold (see Advanced), otherwise downloads only the parts.\nOr force one of the two."))
        combo = self._combo("strategy", STRATEGY_NAMES, 30)
        combo.activated.connect(self.preview_requested)  # only a choice by the person, like <<ComboboxSelected>>
        row.add_control(combo)

        row = self._add_setting_row(
            card, "exact", N_("Frame-exact cuts"), N_("Slow and CPU heavy. Off = lossless, ~2 s precision."), "cuts", card,
            info=N_("Off (default): the cuts are lossless and land on keyframes, about 2 seconds "
                 "of precision.\nOn: the video is re-encoded so every cut is frame-exact. "
                 "That is slow and uses a lot of CPU."))
        self._switch(row, "exact")

        row = self._add_setting_row(card, "keep_full", N_("Keep the full VOD"), N_("Also keep the full file when the full-VOD strategy is used."), "cuts", card,
                           divider=False)
        self._switch(row, "keep_full")

        adv = self._advanced("cuts", card, N_("auto threshold"))
        row = self._add_setting_row(
            adv, "threshold", N_("Auto threshold"), N_("Auto uses the full VOD above this share."), "cuts", card, adv, divider=False,
            info=N_("Auto downloads the full VOD (and splits it) when the parts cover at least this "
                 "percentage of it; below that it downloads only the parts."))
        spin = self._spin("threshold", 1, 100, 5)
        spin.valueChanged.connect(self.preview_requested)
        row.add_control(spin)
        self._unit(row, "%")

    # ------------------------------------------------------------------ Chapters
    def _section_chapters(self, f: QWidget) -> None:
        self._heading(f, N_("Chapters"),
                      N_("How the chapters look. Switch them on with «Add clips as chapters» in the Plan tab."))
        card = self._card(f)

        entry = self._template_row(
            card, N_("Chapter title"), N_("Name of each clip's chapter."), "title_tpl",
            ["title", "creator", "views", "duration"], per_row=4,
            section_key="chapters", card=card)
        entry.textEdited.connect(self.refresh_clips_requested)

        row = self._add_setting_row(card, "pad_after", N_("Tail"), N_("Seconds the chapter lasts after the clip ends."), "chapters", card)
        spin = self._spin("pad_after", 0, 600, 6)
        spin.valueChanged.connect(self.refresh_clips_requested)
        row.add_control(spin)
        self._unit(row, "s")

        row = self._add_setting_row(
            card, "gap_title", N_("Gap chapter name"), N_("Name for the stretches between clips."), "chapters", card, divider=False,
            info=N_("MP4 needs every stretch to have a name, so don't leave this empty for MP4. "
                 "Empty is fine only for MKV."))
        row.add_control(self._entry("gap_title", 18))

    # ------------------------------------------------------------------ Premiere Pro
    def _section_premiere(self, f: QWidget) -> None:
        self._heading(f, N_("Premiere Pro"), N_("Markers you can bring into Adobe Premiere Pro next to each part."))
        card = self._card(f)

        row = self._add_setting_row(
            card, "premiere_plugin", N_("LuckyDownloader Premiere plugin"), N_("Saves a .markers.json with colors and clip details."), "premiere", card,
            info=N_("One .markers.json next to each part, for the LuckyDownloader Premiere plugin. "
                 "It works even if chapters are off."))
        self._switch(row, "premiere_plugin", refresh_clips=True)

        row = self._add_setting_row(
            card, "game_markers", N_("Game / category changes"), N_("Also marks every time the game changes."), "premiere", card,
            info=N_("Adds markers named «GAME: ...» to the .markers.xml and as game markers in the "
                 ".markers.json. Works for full VODs and for parts, even if chapters are off."))
        self._switch(row, "game_markers")

        row = self._add_setting_row(
            card, "muted_markers", N_("Muted audio"), N_("Also marks the stretches Twitch silenced."), "premiere", card, divider=False,
            info=N_("Twitch mutes copyrighted audio in a VOD. Those stretches are added to the "
                 ".markers.json as «muted» markers (the plugin decides the color), so you can see "
                 "them in Premiere. It needs the plugin file above to be on. The same stretches "
                 "show in red on the Plan tab's timeline."))
        self._switch(row, "muted_markers")

        adv = self._advanced("premiere", card, N_("plain markers and clip list"))
        row = self._add_setting_row(adv, "premiere_xml", N_("Plain Premiere markers"), N_("Saves a .markers.xml you can import without the plugin."), "premiere", card, adv,
                          info=N_("Plain import, without colors. Works even if chapters are off."))
        self._switch(row, "premiere_xml", refresh_clips=True)
        row = self._add_setting_row(adv, "sidecar", N_("Clip list"), N_("Saves a .clips.json (clip titles, creators, links) next to each part."), "premiere", card, adv,
                          divider=False)
        self._switch(row, "sidecar")

    # ------------------------------------------------------------------ Chat
    def _section_chat(self, f: QWidget) -> None:
        self._heading(f, N_("Chat"), N_("Download the chat that went with the stream, or turn it into a video you can put "
                                 "over the footage in your editor (Twitch VODs only)."))
        card = self._card(f)

        row = self._add_setting_row(
            card, "chat", N_("Download the chat"), N_("Saves the chat of each part next to it."), "chat", card,
            info=N_("Uses TwitchDownloaderCLI, downloaded the first time. Saved next to each part "
                 "as «name.chat.json». Inside the .json the message times count from the start of "
                 "the VOD, not from the start of the part; the file's start/end say which stretch "
                 "it covers.\nTwitchDownloader is MIT licensed (github.com/lay295/TwitchDownloader)."))
        self._switch(row, "chat")

        row = self._add_setting_row(
            card, "chat_render", N_("Chat as a video (overlay)"), N_("Draws the chat of each part as a video for your editor."), "chat", card,
            info=N_("Saved next to each part as «name.chat-overlay.mov» (or .mp4). It works even if the "
                 "stream had no chat on screen: put it on the track above the video, at the start of "
                 "the part, and place it where you want it. It begins together with the part and can "
                 "run up to a second longer at the end.\nIt takes a while: a long part can take "
                 "from minutes to hours to draw, depending on the type. Emotes and badges are "
                 "fetched from Twitch, BTTV, FFZ and 7TV when it is drawn, so it needs internet.\n"
                 "Size on disk for a very busy chat (3 messages a second, 400 x 1080): about 3.4 GB "
                 "per hour with Animation, 28 GB with ProRes 4444, 0.4 GB with H.264."))
        self._switch(row, "chat_render")

        row = card.add_row(
            t("Draw the overlay from a saved chat"), t("Pick a «.chat.json» you already have. Nothing is downloaded."),
            divider=False,
            info=t("Uses the overlay settings below (type, look, size, text size, frame rate). The video is "
                 "not touched. If «name.mp4» (or .mkv…) is next to the chat, the overlay takes its size "
                 "and frame rate; if «name.markers.json» is there too, it is lined up to the fraction of "
                 "a second. The result is saved next to the chat as «name.chat-overlay.mov» (or .mp4)."))
        self.saved_chat_row = row
        self._register_setting(
            self.saved_chat_row, "_saved_chat_render", "chat", card,
            raw_title="Draw the overlay from a saved chat",
            raw_hint="Pick a «.chat.json» you already have. Nothing is downloaded.",
        )
        self.saved_chat_btn = QPushButton(t("Choose chat file…"))
        self.saved_chat_btn.clicked.connect(self.saved_chat_requested)
        row.add_control(self.saved_chat_btn)

        adv = self._advanced("chat", card, N_("file format, embedded emotes and how the overlay looks"))
        row = self._add_setting_row(adv, "chat_format", N_("Format"), N_("File type of the saved chat."), "chat", card, adv)
        row.add_control(self._combo("chat_format", list(CHAT_FORMATS), 6))
        row = self._add_setting_row(adv, "chat_embed", N_("Embed emotes and badges"), N_("Bigger file, but it works offline."), "chat", card, adv)
        self._switch(row, "chat_embed")

        row = self._add_setting_row(
            adv, "chat_render_mode", N_("Overlay type"), N_("How the chat video is saved."), "chat", card, adv,
            info=N_("Transparent · Animation: QuickTime Animation with an alpha channel. Lossless, "
                 "much smaller and faster to draw than ProRes, and read by Premiere Pro and After "
                 "Effects.\nTransparent · ProRes 4444: the same idea with the codec almost every "
                 "editor knows, but very big files. Use it if your editor does not read "
                 "Animation.\nBlack background · H.264: small and quick, but not see-through. In the "
                 "editor, set the clip's blend mode to Screen and the black disappears."))
        row.add_control(self._combo("chat_render_mode", CHAT_RENDER_TYPE_NAMES, 36))
        row = self._add_setting_row(adv, "chat_render_look", N_("Look"), N_("What is behind the text (not used by the black background type)."), "chat", card, adv)
        row.add_control(self._combo("chat_render_look", CHAT_RENDER_LOOK_NAMES, 28))
        row = self._add_setting_row(adv, "chat_render_width", N_("Size"), N_("Width × height in pixels. Height 0 = the same as the video."), "chat", card, adv)
        row.add_control(self._spin("chat_render_width", 100, 3840, 6))
        times = QLabel("×")
        times.setProperty("role", "muted")
        row.add_control(times)
        self._register_setting(row, "chat_render_height", "chat", card, adv, raw_title=N_("Size"), raw_hint=N_("Width × height in pixels. Height 0 = the same as the video."))
        row.add_control(self._spin("chat_render_height", 0, 4320, 6))
        row = self._add_setting_row(adv, "chat_render_font_size", N_("Text size"), N_("Size of the letters, in points."), "chat", card, adv)
        row.add_control(self._spin("chat_render_font_size", 6, 96, 5))
        row = self._add_setting_row(adv, "chat_render_fps", N_("Frame rate"), N_("Frames per second of the chat video."), "chat", card, adv)
        row.add_control(self._combo("chat_render_fps", CHAT_RENDER_FPS_NAMES, 14))
        row = self._add_setting_row(adv, "chat_render_smooth", N_("Smooth scrolling"), N_("Redraws on every frame instead of 5 times a second. Slower."), "chat", card, adv,
                          divider=False)
        self._switch(row, "chat_render_smooth")

    # ------------------------------------------------------------------ Clips
    def _section_clips(self, f: QWidget) -> None:
        self._heading(f, N_("Clips"), N_("Used by the «Download only selected clip» button in the Plan tab."))
        card = self._card(f)

        self._template_row(
            card, N_("File name"), N_("How a single downloaded clip is called."), "clip_name_template",
            ["clip_title", "creator", "views", "clip_id", "clip_duration",
             "streamer", "date", "id", "title", "start", "end"],
            info=N_("Clip tokens: {clip_title} {creator} {views} {clip_id} {clip_duration}.\nYou can also use the "
                 "VOD's: {streamer} {date} {id} {title} {start} {end}. ({id} and {title} are the VOD's, not the clip's.)"),
            section_key="clips", card=card)

        row = self._add_setting_row(card, "clip_pad_before", N_("Extra time before"), N_("Seconds added before the clip starts."), "clips", card)
        row.add_control(self._spin("clip_pad_before", 0, 600, 6))
        self._unit(row, "s")
        row = self._add_setting_row(card, "clip_pad_after", N_("Extra time after"), N_("Seconds added after the clip ends."), "clips", card, divider=False)
        row.add_control(self._spin("clip_pad_after", 0, 600, 6))
        self._unit(row, "s")

    # ------------------------------------------------------------------ Interface
    def _section_interface(self, f: QWidget) -> None:
        self._heading(f, N_("Interface"), N_("Language and appearance settings."))

        self.interface_card = self._card(f, N_("Interface"), N_("Language and appearance settings."))
        self.lang_row = self.interface_card.add_row(t("Language"), t("Select interface language (English / Español)."), divider=False)
        from core.ui_state import load_ui_state, save_ui_state
        self.lang_combo = ComboBox()
        for code, label in i18n_qt.language_choices():
            self.lang_combo.addItem(label, code)
        self.select_language_setting(i18n_qt.current_setting())

        def _on_lang_changed(i: int):
            code = self.lang_combo.itemData(i)
            if code and code != i18n_qt.current_setting():
                i18n_qt.apply_language(code)  # live: no restart; windows refresh through the language bus
                st = load_ui_state()
                st.language = code
                save_ui_state(st)
                if not hasattr(self.window(), "refresh_language"):  # an Options tab used on its own
                    self.refresh_language()

        self.lang_combo.currentIndexChanged.connect(_on_lang_changed)
        self.lang_row.add_control(self.lang_combo)
        self._register_setting(
            self.lang_row, "language", "interface", self.interface_card,
            raw_title="Language", raw_hint="Select interface language (English / Español)."
        )

    # ------------------------------------------------------------------ Tools
    def _section_tools(self, f: QWidget) -> None:
        self._heading(f, N_("Tools"), N_("yt-dlp and ffmpeg do the downloading and cutting."))

        # G5 Dedicated tools status card
        tools_status_card = self._card(f, N_("Download & processing tools"))
        self.ytdlp_row = tools_status_card.add_row("yt-dlp", t("Twitch stream downloader engine"))
        self._register_setting(self.ytdlp_row, "_tool_ytdlp", "tools", tools_status_card, raw_title="yt-dlp", raw_hint="Twitch stream downloader engine")
        self.ytdlp_status_label = QLabel(t("Checking…"))
        self.ytdlp_status_label.setProperty("role", "muted")
        self.ytdlp_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ytdlp_status_label.setMaximumWidth(280)
        self.ytdlp_row.add_control(self.ytdlp_status_label)

        self.ffmpeg_row = tools_status_card.add_row("ffmpeg", t("Audio/video muxing, cutting, and stitching"), divider=False)
        self._register_setting(self.ffmpeg_row, "_tool_ffmpeg", "tools", tools_status_card, raw_title="ffmpeg", raw_hint="Audio/video muxing, cutting, and stitching")
        self.ffmpeg_status_label = QLabel(t("Checking…"))
        self.ffmpeg_status_label.setProperty("role", "muted")
        self.ffmpeg_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ffmpeg_status_label.setMaximumWidth(280)
        self.ffmpeg_row.add_control(self.ffmpeg_status_label)

        card = self._card(f)

        self.tools_info_row = card.add_row(t("Installed tools"), "")
        self._register_setting(self.tools_info_row, "_tools_info", "tools", card, raw_title="Installed tools", raw_hint="")
        self.tools_info_label = WrapLabel(t("Checking…"))
        self.tools_info_label.setProperty("role", "muted")
        self.tools_info_label.setMaximumWidth(640)
        self.tools_info_row.below_layout.setContentsMargins(0, 4, 0, 0)
        self.tools_info_row.below_layout.addWidget(self.tools_info_label)

        row = self._add_setting_row(card, "auto_update", N_("Check for yt-dlp updates on startup"), N_("Recommended: Twitch changes often."), "tools", card)
        self._switch(row, "auto_update")

        row = self._add_setting_row(
            card,
            "cookies_from_browser",
            N_("Cookies from browser"),
            N_("Pass browser cookies to yt-dlp for age-restricted or login-required content (YouTube, TikTok, Instagram)."),
            "tools",
            card,
        )
        row.add_control(self._combo("cookies_from_browser", COOKIES_BROWSER_NAMES, 10))

        row_scope = self._add_setting_row(
            card,
            "cookies_scope",
            N_("Cookies scope"),
            N_("Restrict browser cookies to known platforms (YouTube, TikTok, Instagram, X) or allow on all sites."),
            "tools",
            card,
        )
        row_scope.add_control(self._combo("cookies_scope", COOKIES_SCOPE_NAMES, 26))

        self.update_row = card.add_row(t("Update yt-dlp"), t("Download the latest version now."))
        self._register_setting(self.update_row, "_update_ytdlp", "tools", card, raw_title="Update yt-dlp", raw_hint="Download the latest version now.")
        self.update_btn = QPushButton(t("Update yt-dlp now"))
        self.update_btn.clicked.connect(self.update_tools_requested)
        self.update_row.add_control(self.update_btn)

        self.tools_folder_row = card.add_row(t("Tools folder"), t("Where yt-dlp, ffmpeg and TwitchDownloaderCLI are kept."))
        self._register_setting(self.tools_folder_row, "_tools_folder", "tools", card, raw_title="Tools folder", raw_hint="Where yt-dlp, ffmpeg and TwitchDownloaderCLI are kept.")
        self.tools_folder_btn = QPushButton(t("Open tools folder"))
        self.tools_folder_btn.clicked.connect(self.open_tools_folder)
        self.tools_folder_row.add_control(self.tools_folder_btn)

        self.clean_temp_row = card.add_row(t("Temporary files"), t("Remove incomplete temporary download directories from the output folder."), divider=False)
        self._register_setting(self.clean_temp_row, "_clean_temp", "tools", card, raw_title="Temporary files", raw_hint="Remove incomplete temporary download directories from the output folder.")
        self.clean_temp_btn = QPushButton(t("Clean temporary files"))
        self.clean_temp_btn.clicked.connect(self.clean_temp_files)
        self.clean_temp_row.add_control(self.clean_temp_btn)

        privacy_card = self._card(f, N_("Privacy & Data"), N_("Control local history and clear stored URLs or searches."))
        row_hist = self._add_setting_row(
            privacy_card, "save_history", N_("Save download history & recent URLs"),
            N_("Record downloaded VODs, recent channels, and search queries locally."), "tools", privacy_card,
        )
        self._switch(row_hist, "save_history")
        self.clear_data_row = privacy_card.add_row(t("Private data"), t("Clear download history, recent channels, searches, and finished queue items."), divider=False)
        self._register_setting(self.clear_data_row, "_clear_private_data", "tools", privacy_card, raw_title="Private data", raw_hint="Clear download history, recent channels, searches, and finished queue items.")
        self.clear_data_btn = QPushButton(t("Clear Private Data…"))
        self.clear_data_btn.clicked.connect(self.clear_private_data)
        self.clear_data_row.add_control(self.clear_data_btn)

        app_update_card = self._card(f, N_("LuckyDownloader updates"), N_("Check for new versions of LuckyDownloader."))
        row = self._add_setting_row(
            app_update_card, "check_app_updates", N_("Check for new versions of LuckyDownloader"),
            N_("Notifies you when a new release is available on GitHub."), "tools", app_update_card)
        self._switch(row, "check_app_updates")

        self.app_version_row = app_update_card.add_row(t("Version"), "")
        self._register_setting(self.app_version_row, "_app_version", "tools", app_update_card, raw_title="Version", raw_hint="")
        self.app_version_label = QLabel()
        self.app_version_label.setProperty("role", "muted")
        self.app_version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.app_version_label.setMaximumWidth(280)
        self.app_version_row.add_control(self.app_version_label)

        self.check_now_row = app_update_card.add_row(t("Check now"), t("Check GitHub releases for updates now."))
        self._register_setting(self.check_now_row, "_check_now", "tools", app_update_card, raw_title="Check now", raw_hint="Check GitHub releases for updates now.")
        self.check_app_updates_btn = QPushButton(t("Check now"))
        self.check_app_updates_btn.clicked.connect(self.check_app_updates_requested.emit)
        self.check_now_row.add_control(self.check_app_updates_btn)

        self.about_row = app_update_card.add_row(t("About & Diagnostics"), t("View version info or export a redacted diagnostics bundle."), divider=False)
        self._register_setting(self.about_row, "_about_diag", "tools", app_update_card, raw_title="About & Diagnostics", raw_hint="View version info or export a redacted diagnostics bundle.")
        self.about_btn = QPushButton(t("About & Diagnostics…"))
        self.about_btn.clicked.connect(self.about_requested.emit)
        self.about_row.add_control(self.about_btn)
        self.refresh_app_update_state()

        link_card = self._card(
            f, N_("Links from web pages"),
            N_("A page can offer a luckytwitch:// link that opens a VOD here with the cut points already "
            "filled in. A link only fills in the Plan tab: it never starts a download."))
        self.link_row = link_card.add_row(t("Open luckytwitch:// links"), "", divider=False)
        self._register_setting(self.link_row, "_web_links", "tools", link_card, raw_title="Open luckytwitch:// links", raw_hint="")
        self.link_info_label = WrapLabel("")
        self.link_info_label.setProperty("role", "muted")
        self.link_info_label.setMaximumWidth(640)
        self.link_row.below_layout.setContentsMargins(0, 4, 0, 0)
        self.link_row.below_layout.addWidget(self.link_info_label)
        self.link_btn = QPushButton("")
        self.link_btn.clicked.connect(self.register_links)
        self.link_row.add_control(self.link_btn)
        self.refresh_link_state()

    def refresh_app_update_state(self) -> None:
        """Update the version row in the updates card with current version and last checked date."""
        if not hasattr(self, "app_version_label"):
            return
        from datetime import datetime
        from core import paths, updates
        ver = paths.BUNDLED_VERSION
        if not updates.is_valid_app_version(ver):
            self.app_version_label.setText(t("Development build"))
            self.app_version_label.setToolTip(t("Development build (updates not checked automatically)"))
            return
        state = updates.load_state()
        last = state.get("last_check")
        if last:
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                last_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                last_str = last
        else:
            last_str = t("never")
        self.app_version_label.setText(t("{ver} · checked: {last}", ver=ver, last=last_str))
        self.app_version_label.setToolTip(t("Installed: {ver}\nLast checked: {last}", ver=ver, last=last_str))

    # ------------------------------------------------------------------ actions of the tab
    def pick_folder(self) -> None:
        start = str(self.binder.get("out_dir") or "") or str(APP_DIR)
        folder = dialogs.choose_folder(self, t("Output folder"), start)
        if folder:
            self.binder.set("out_dir", folder)

    def open_tools_folder(self) -> None:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            open_in_file_manager(TOOLS_DIR)
        except OSError as e:
            dialogs.info(self, t("Tools folder"), f"{TOOLS_DIR}\n\n{e}")

    def is_queue_active(self) -> bool:
        hook = getattr(self, "queue_busy_hook", None)
        if callable(hook):
            try:
                return bool(hook())
            except Exception:
                pass
        win = self.window()
        if win is not None and hasattr(win, "tab_queue") and hasattr(win.tab_queue, "runner"):
            try:
                return bool(win.tab_queue.runner.is_running())
            except Exception:
                pass
        return False

    def clear_private_data(self) -> bool:
        if not dialogs.ask_yes_no(
            self,
            t("Clear Private Data"),
            t("Clear download history, recent channels, recent searches, and finished queue items?"),
        ):
            return False
        from core import history, recent
        history.save_history([])
        recent.save_recent([])
        recent.save_recent_searches([])
        win = self.window()
        if win is not None and hasattr(win, "tab_queue") and hasattr(win.tab_queue, "clear_finished"):
            win.tab_queue.clear_finished()
        if win is not None and hasattr(win, "tab_browse"):
            win.tab_browse.recent = []
            win.tab_browse.recent_yt = []
            if hasattr(win.tab_browse, "refresh_recent"):
                win.tab_browse.refresh_recent()
        self.status_message.emit(t("Private data cleared."))
        return True

    def clean_temp_files(self) -> int:
        from core.finalize import cleanup_stale_workdirs
        if self.is_queue_active():
            dialogs.info(self, t("Temporary files"), t("Cannot clean temporary files while downloads are running."))
            return 0
        out_dir = str(self.binder.get("out_dir") or DEFAULTS.get("out_dir") or APP_DIR)
        removed = cleanup_stale_workdirs(out_dir, max_age_hours=0.0)
        self.status_message.emit(t("Cleaned {count} temporary folder(s).", count=removed))
        return removed

    def refresh_link_state(self) -> None:
        """Say whether this computer sends luckytwitch:// links to this app (Windows can be set up from here)."""
        st = weblink.registration()
        if not st.supported:
            self.link_btn.setVisible(False)
            if sys.platform == "darwin":
                self.link_info_label.setText(
                    t("macOS sends these links to the app by itself once it is in Applications. If a link "
                      "does nothing, open LuckyDownloader from Applications once and try again."))
            else:
                self.link_info_label.setText(t("Links are not supported on this system."))
        elif st.state == "ok":
            self.link_btn.setVisible(True)
            self.link_info_label.setText(t("Set up: these links open this app."))
            self.link_btn.setText(t("Set up again"))
        elif st.state == "other":
            self.link_btn.setVisible(True)
            self.link_info_label.setText(
                t("These links currently open another copy of LuckyDownloader. Press the button to use this one."))
            self.link_btn.setText(t("Use this copy"))
        else:
            self.link_btn.setVisible(True)
            self.link_info_label.setText(t("Not set up: these links do nothing on this computer yet."))
            self.link_btn.setText(t("Set up links"))

    def register_links(self) -> None:
        try:
            weblink.register()
        except OSError as e:
            dialogs.error(self, t("Links"), t("Windows did not accept the setting:\n{error}", error=e))
            return
        self.refresh_link_state()
        self.status_message.emit(t("Links are set up: luckytwitch:// links now open this app."))

    # ------------------------------------------------------------------ what the window tells the tab
    def set_tools_info(self, text: str) -> None:
        self.tools_info_label.setText(text)
        parts = [p.strip() for p in text.replace("\n", " · ").split(" · ") if p.strip()]
        for p in parts:
            head = p.split("(")[0].strip()
            head_lower = head.lower()
            if head_lower.startswith("yt-dlp") and hasattr(self, "ytdlp_status_label"):
                tokens = head.split()
                if len(tokens) > 1:
                    ver = " ".join(tokens[1:])
                    self.ytdlp_status_label.setText(t("Not installed") if "not installed" in head_lower else ver)
                else:
                    self.ytdlp_status_label.setText(t("Installed"))
                self.ytdlp_status_label.setToolTip(p)
            elif head_lower.startswith("ffmpeg") and hasattr(self, "ffmpeg_status_label"):
                tokens = head.split()
                if len(tokens) > 1:
                    ver = " ".join(tokens[1:])
                    self.ffmpeg_status_label.setText(t("Not installed") if "not installed" in head_lower else ver)
                else:
                    self.ffmpeg_status_label.setText(t("Installed"))
                self.ffmpeg_status_label.setToolTip(p)

    def set_tools_running(self, running: bool) -> None:
        self.update_btn.setEnabled(not running)

    def set_saved_chat_running(self, running: bool) -> None:
        self.saved_chat_btn.setEnabled(not running)

    def select_language_setting(self, setting: str) -> None:
        """Show ``setting`` ('auto', 'en', 'es') in the language picker without triggering a switch."""
        idx = self.lang_combo.findData(setting)
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.lang_combo.blockSignals(False)

    def refresh_language(self) -> None:
        """Update OptionsTab text labels dynamically when language changes."""
        self.search_entry.setPlaceholderText(t("Search settings…"))
        for key, base_lbl in SECTIONS:
            btn = self.nav.buttons.get(key)
            if btn is not None:
                tr = t(base_lbl)
                count = getattr(btn, "_badge_count", 0)
                btn.setText(f"{tr} ({count})" if count > 0 else tr)

        for card, raw_title, raw_sub in self.registered_cards:
            if raw_title and card.title_label:
                card.title_label.setText(t(raw_title))
            if raw_sub and card.subtitle_label:
                card.subtitle_label.setText(t(raw_sub))

        for head, sub, raw_title, raw_sub in self.registered_headings:
            head.setText(t(raw_title))
            sub.setText(t(raw_sub))

        for adv, raw_hint in self.registered_advanced:
            adv.title = t("Advanced")
            adv.hint = t(raw_hint)
            adv._apply(animate=False)

        for item in self.searchable_rows:
            row = item["row"]
            rt = item.get("raw_title")
            if rt and row.title_label:
                row.title_label.setText(t(rt))
            rh = item.get("raw_hint")
            if rh and row.hint_label:
                row.hint_label.setText(t(rh))
            ri = item.get("raw_info")
            if ri and row.info:
                info_txt = t(ri)
                row.info.text = info_txt
                row.info.setAccessibleDescription(info_txt)
                if hasattr(row.info, "tooltip") and row.info.tooltip:
                    row.info.tooltip.text = info_txt
            info_text = row.info.text if getattr(row, "info", None) is not None else ""
            hint_text = row.hint_label.text() if getattr(row, "hint_label", None) is not None else ""
            title_text = row.title_label.text() if getattr(row, "title_label", None) is not None else ""
            item["text"] = f"{title_text} {hint_text} {info_text}".lower()

        if hasattr(self, "browse_btn") and self.browse_btn:
            self.browse_btn.setText(t("Browse…"))
        if hasattr(self, "open_folder_btn") and self.open_folder_btn:
            self.open_folder_btn.setText(t("Open folder"))
        if hasattr(self, "saved_chat_btn") and self.saved_chat_btn:
            self.saved_chat_btn.setText(t("Choose chat file…"))
        if hasattr(self, "update_btn") and self.update_btn:
            self.update_btn.setText(t("Update yt-dlp now"))
        if hasattr(self, "tools_folder_btn") and self.tools_folder_btn:
            self.tools_folder_btn.setText(t("Open tools folder"))
        if hasattr(self, "clean_temp_btn") and self.clean_temp_btn:
            self.clean_temp_btn.setText(t("Clean temporary files"))
        if hasattr(self, "clean_temp_row") and self.clean_temp_row:
            self.clean_temp_row.title_label.setText(t("Temporary files"))
            self.clean_temp_row.hint_label.setText(t("Remove incomplete temporary download directories from the output folder."))
        if hasattr(self, "check_app_updates_btn") and self.check_app_updates_btn:
            self.check_app_updates_btn.setText(t("Check now"))
        if hasattr(self, "save_preview_card_row") and self.save_preview_card_row:
            self.save_preview_card_row.title_label.setText(t("Destination preview"))
        if hasattr(self, "ytdlp_row") and self.ytdlp_row:
            self.ytdlp_row.hint_label.setText(t("Twitch stream downloader engine"))
        if hasattr(self, "ffmpeg_row") and self.ffmpeg_row:
            self.ffmpeg_row.hint_label.setText(t("Audio/video muxing, cutting, and stitching"))
        if hasattr(self, "tools_info_row") and self.tools_info_row:
            self.tools_info_row.title_label.setText(t("Installed tools"))
        if hasattr(self, "update_row") and self.update_row:
            self.update_row.title_label.setText(t("Update yt-dlp"))
            self.update_row.hint_label.setText(t("Download the latest version now."))
        if hasattr(self, "tools_folder_row") and self.tools_folder_row:
            self.tools_folder_row.title_label.setText(t("Tools folder"))
            self.tools_folder_row.hint_label.setText(t("Where yt-dlp, ffmpeg and TwitchDownloaderCLI are kept."))
        if hasattr(self, "app_version_row") and self.app_version_row:
            self.app_version_row.title_label.setText(t("Version"))
        if hasattr(self, "check_now_row") and self.check_now_row:
            self.check_now_row.title_label.setText(t("Check now"))
            self.check_now_row.hint_label.setText(t("Check GitHub releases for updates now."))
        if hasattr(self, "lang_row") and self.lang_row:
            self.lang_row.title_label.setText(t("Language"))
            self.lang_row.hint_label.setText(t("Select interface language (English / Español)."))
        if hasattr(self, "link_row") and self.link_row:
            self.link_row.title_label.setText(t("Open luckytwitch:// links"))
        if hasattr(self, "saved_chat_row") and self.saved_chat_row:
            self.saved_chat_row.title_label.setText(t("Draw the overlay from a saved chat"))
            self.saved_chat_row.hint_label.setText(t("Pick a «.chat.json» you already have. Nothing is downloaded."))
            saved_chat_info = t("Uses the overlay settings below (type, look, size, text size, frame rate). The video is not touched. If «name.mp4» (or .mkv…) is next to the chat, the overlay takes its size and frame rate; if «name.markers.json» is there too, it is lined up to the fraction of a second. The result is saved next to the chat as «name.chat-overlay.mov» (or .mp4).")
            self.saved_chat_row.info.text = saved_chat_info
            self.saved_chat_row.info.setAccessibleDescription(saved_chat_info)
            if hasattr(self.saved_chat_row.info, "tooltip") and self.saved_chat_row.info.tooltip:
                self.saved_chat_row.info.tooltip.text = saved_chat_info

        if hasattr(self, "lang_combo"):
            self.lang_combo.setItemText(0, t("Auto (system)"))
        self.refresh_link_state()
        self.refresh_app_update_state()
        self.refresh_name_examples()
