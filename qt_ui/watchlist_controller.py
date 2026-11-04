"""Channel/watchlist, Twitch credentials, history/about dialogs, and saved-chat overlay controller mixin."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.config import make_client
from core.i18n import t
from core.options import num
from core.settings import save_settings
from luckytwitch_engine import EngineError, Job, clip_cut_text, describe_chat_overlay, make_plan
from qt_ui import dialogs, notify
from qt_ui.twitch_dialog import TwitchDialog


class WatchlistControllerMixin:
    """Mixin for ``MainWindow`` handling Twitch client, saved-chat rendering, playlist/clip queuing, and dialogs."""

    def get_client(self):
        return self.client

    def reload_client(self) -> None:
        """A saved session expired: make the client again from what is saved (the Search tab asks for this)."""
        self.client = make_client()

    def update_search_state(self) -> None:
        tab = getattr(self, "tab_search", None)
        if tab is not None:
            tab.update_search_state()

    # ---------------------------- the overlay of a saved chat ---------------------------- #
    def render_saved_chat(self) -> None:
        """Options → Chat → «Draw the overlay from a saved chat»: pick a «.chat.json», confirm, draw it (no download)."""
        if self.tab_queue.runner.is_running() or self.tools_busy or self.saved_chat_busy:
            dialogs.info(self, t("Busy"), t("Wait for the running job (or the tools setup) to finish first."))
            return
        opts = self.build_options()
        folder = Path(opts.out_dir)
        path = dialogs.open_file(
            self, t("Choose a saved chat (.chat.json)"), str(folder) if folder.is_dir() else "",
            t("Chat files (*.json);;All files (*.*)"),
        )
        if not path:
            return
        chat = Path(path)
        try:
            summary = describe_chat_overlay(chat, opts)
        except EngineError as e:
            dialogs.error(self, t("Chat overlay"), str(e))
            return
        if not dialogs.ask_ok_cancel(
            self, t("Draw the chat overlay?"), summary + "\n\n" + t("It can take a while for a long chat."),
        ):
            return
        self.start_saved_chat_render(chat, opts)

    def start_saved_chat_render(self, chat: Path, opts) -> None:
        self.saved_chat_busy = True
        self.tab_queue.set_running(True)  # «Start queue» off, «Cancel current» on (the log and the button live there)
        self.tab_options.set_saved_chat_running(True)
        self.show_queue_tab()
        self.set_status(t("Chat overlay…"))
        self.saved_chat_ctx = self.saved_chat_runner.start(chat, opts)

    def cancel_saved_chat(self) -> bool:
        """«Cancel current» while an overlay is being drawn. False when there is none."""
        if self.saved_chat_ctx is None:
            return False
        self.saved_chat_ctx.cancel()
        return True

    def on_saved_chat_done(self, out: str, error: str) -> None:
        self.saved_chat_busy = False
        self.saved_chat_ctx = None
        self.tab_queue.set_running(False)
        self.tab_options.set_saved_chat_running(False)
        self.set_progress(0, "")
        if error:
            cancelled = error == "Cancelled."
            self.log("Cancelled." if cancelled else f"Chat overlay: {error}")
            self.set_status(t("Chat overlay cancelled.") if cancelled else t("Chat overlay failed. See the log."))
            if not cancelled:
                dialogs.error(self, t("Chat overlay"), error)
        else:
            self.set_status(t("Chat overlay ready: {file}", file=Path(out).name))

    def _handle_playlist_loaded(self, pl) -> None:
        from qt_ui.playlist_dialog import PlaylistPickerDialog
        dlg = PlaylistPickerDialog(pl, settings=self.settings, parent=self)
        if dlg.exec():
            jobs = dlg.build_jobs()
            if not jobs:
                return
            for job in jobs:
                label = f"{job.source.uploader or job.source.site} · {job.source.title}"[:70]
                self.tab_queue.enqueue(job, label, 1, "full video")
            self._sync_queue_badge()
            self.set_status(t("Added {count} playlist items to queue.", count=len(jobs)))
            notify.success(
                self,
                t("Playlist queued"),
                t("Added {count} videos from «{title}».", count=len(jobs), title=pl.title),
                action=(t("Go to Queue"), self.show_queue_tab),
            )
        else:
            self.set_status(t("Playlist selection cancelled."))

    def download_clips(self) -> None:
        """Queue each selected clip as its own download (just that clip, named after the clip)."""
        sel = self.tab_plan.selected_clip_rows()
        if not sel:
            dialogs.info(self, t("Select a clip"), t("Select a clip in the table first."))
            return
        if not self.source:
            dialogs.info(self, t("No VOD"), t("Press «Get info» first."))
            return
        base = self.build_options()
        before = num(self.settings, "clip_pad_before", float, 3)
        after = num(self.settings, "clip_pad_after", float, 3)
        added = 0
        thumb = self._current_vod_thumb()
        for row in sel:
            clip = self.clips[row]
            title = clip.get("title") or t("Clip")
            try:
                cut = clip_cut_text(clip, self.source.duration, before, after)
                opts = replace(
                    base, cut_text=cut, strategy="sections", chapters=False, keep_full=False, sidecar=False,
                    premiere_xml=False, premiere_plugin=False, game_markers=False, muted_markers=False, chat=False,
                    chat_render=False,
                )
                make_plan(opts.cut_text, self.source.duration, opts.strategy, opts.full_threshold)
            except EngineError as e:
                dialogs.warning(self, t("Clip"), f"«{title}»: {e}")
                continue
            job = Job(self.source, opts, single_clip=clip)
            label = f"{self.source.uploader} \u00b7 Clip: {title}"[:70]
            self.tab_queue.enqueue(job, label, 1, "only the clip", thumb=thumb)
            added += 1
        if added:
            self._sync_queue_badge()
            if self.settings:
                save_settings(self.settings)
            self.set_status(
                t(
                    "Added {clips} clip(s) to the queue ({items} item(s)). Open «Queue & log» and press «Start queue».",
                    clips=added,
                    items=len(self.tab_queue.items),
                )
            )
            notify.success(
                self, t("Clips added"), t("Added {n} clip(s) to the queue.", n=added),
                action=(t("Go to Queue"), self.show_queue_tab),
            )

    def use_vod(self, url: str) -> None:
        """«Use this VOD» in the Search tab: the link goes into the entry, the Plan tab opens, «Get info» runs."""
        self.vod_entry.setText(url)
        self.tabs.setCurrentWidget(self.tab_plan)
        self.on_get_info()

    def open_history_dialog(self) -> None:
        from qt_ui.dialogs import HistoryDialog
        dlg = HistoryDialog(self)
        dlg.vod_requested.connect(self.use_vod)
        dlg.exec()

    def open_about_dialog(self) -> None:
        from qt_ui.dialogs import AboutDialog
        dlg = AboutDialog(self)
        dlg.exec()

    def load_vod_from_url(self, url: str) -> None:
        self.use_vod(url)

    def ask_credentials(self) -> None:
        """The Twitch API dialog (modal; this returns at once, like the tkinter one)."""
        if self._login_dialog is not None:
            self._login_dialog.close()
            self._login_dialog.deleteLater()
        self._login_dialog = TwitchDialog(self, self)
        self._login_dialog.open()
