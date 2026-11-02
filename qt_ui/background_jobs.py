"""Background jobs: the tools setup, the overlay of a saved chat, «Get info» and the timeline frames.

Ports of ``App.start_tools_setup``, ``App.start_saved_chat_render``, ``App.on_get_info`` and ``App._load_frames``. Each
starts ONE daemon thread that reports only through the Bridge (``log``, ``progress``, ``tools_info``, ``tools_done``,
``saved_chat_done``, ``info_ok``, ``error``, ``frames``); nothing here touches a widget. The engine functions are looked
up in this module when the thread runs, so tests replace ``qt_ui.background_jobs.ensure_tools`` / ``describe_tools`` /
``ensure_tdcli`` / ``render_existing_chat`` / ``get_source_info`` / ``fetch_clips_for_vod`` / ``load_storyboard_frames``
with fakes (nothing is downloaded).

``tools_done`` and ``saved_chat_done`` carry ``""`` where the tkinter message carried ``None``.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from luckytwitch_engine import (
    Cancelled, Ctx, JobOptions, describe_tools, ensure_tdcli, ensure_tools, fetch_clips_for_vod, get_source_info,
    load_storyboard_frames, render_existing_chat,
)
from core.i18n import t
from qt_ui.bridge import Bridge


def _emit(signal_name: str, bridge: Bridge, *args) -> None:
    """``bridge.<signal_name>.emit(*args)``, but a Bridge that was deleted meanwhile (the window closed while the
    thread was still working) is not an error: nobody is left to listen, so the thread just ends."""
    try:
        getattr(bridge, signal_name).emit(*args)
    except RuntimeError:  # «Signal source has been deleted»
        pass


def _make_ctx(bridge: Bridge) -> Ctx:
    return Ctx(log=lambda m: _emit("log", bridge, m), progress=lambda f, t: _emit("progress", bridge, f, t))


class ToolsRunner:
    """Download missing tools / update yt-dlp in the background."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, update: bool, force: bool) -> Ctx:
        """Start the setup and return its context at once (the window keeps it to cancel the setup when it closes)."""
        bridge = self.bridge
        ctx = _make_ctx(bridge)

        def work():
            error = ""
            try:
                ensure_tools(ctx, update_ytdlp=update, force=force)
            except Cancelled:
                error = "Cancelled."
            except Exception as e:  # noqa: BLE001
                error = str(e)
            try:
                text = describe_tools()
            except Exception as e:  # noqa: BLE001 (the status text is not worth losing the «done» message for)
                text = f"Could not read the tools: {e}"
            _emit("tools_info", bridge, text)
            _emit("tools_done", bridge, error)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return ctx


class SavedChatRunner:
    """Draw the overlay of a chat file the person already has (no download)."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, chat: Path, opts: JobOptions) -> Ctx:
        bridge = self.bridge
        ctx = _make_ctx(bridge)

        def work():
            out, error = None, ""
            try:
                ctx.stage(0.0, 1.0, t("Chat overlay"))
                tool = ensure_tdcli(ctx)
                with tempfile.TemporaryDirectory(prefix="luckytwitch_chat_") as cache:
                    out = render_existing_chat(ctx, tool, chat, opts, Path(cache))
            except Cancelled:
                error = "Cancelled."
            except Exception as e:  # noqa: BLE001
                error = str(e)
            _emit("saved_chat_done", bridge, str(out) if out else "", error)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return ctx


class InfoRunner:
    """Read the VOD info (and its Twitch clips when signed in) in the background (``App.on_get_info``)."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, text: str, client=None) -> None:
        bridge = self.bridge

        def work():
            try:
                info = get_source_info(text)
                clips, warn, loaded = [], "", False
                vod_id = getattr(info, "twitch_vod_id", None)
                if vod_id and client:
                    try:
                        clips = fetch_clips_for_vod(client, vod_id)
                        loaded = True
                    except Exception as e:  # noqa: BLE001
                        warn = f"Could not fetch clips: {e}"
                elif vod_id:
                    warn = "Not signed in to Twitch: clips are not available (optional, see the Twitch API… button)."
                _emit("info_ok", bridge, info, clips, loaded, warn)
            except Exception as e:  # noqa: BLE001
                _emit("error", bridge, str(e))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


class FramesRunner:
    """Download the storyboard preview frames of a VOD in the background (``App._load_frames``)."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, src) -> None:
        sb = getattr(src, "storyboard", None)
        if sb is None:
            return
        bridge = self.bridge

        def work():
            try:
                frames = load_storyboard_frames(sb)
            except Exception:  # noqa: BLE001 (the timeline works without thumbnails)
                frames = None
            _emit("frames", bridge, src, frames)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


class UpdateCheckRunner:
    """Check for LuckyTwitch updates on GitHub in the background."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, force: bool = False) -> None:
        bridge = self.bridge

        def work():
            from datetime import datetime, timezone
            from core import paths, updates

            try:
                state = updates.load_state()
                if not force and not updates.should_check(state):
                    cached = state.get("cached")
                    info = updates.UpdateInfo.from_dict(cached) if cached else None
                    if info and updates.is_newer(info.tag, paths.BUNDLED_VERSION):
                        _emit("update_checked", bridge, info, "")
                    else:
                        _emit("update_checked", bridge, None, "")
                    return

                info = updates.fetch_latest()
                now_str = datetime.now(timezone.utc).isoformat()
                state["last_check"] = now_str
                if info:
                    state["latest_tag"] = info.tag
                    state["cached"] = info.to_dict()
                updates.save_state(state)

                if info and updates.is_newer(info.tag, paths.BUNDLED_VERSION):
                    _emit("update_checked", bridge, info, "")
                else:
                    _emit("update_checked", bridge, None, "")
            except Exception as e:  # noqa: BLE001
                _emit("update_checked", bridge, None, str(e))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


class UpdateDownloadRunner:
    """Download the update installer in the background."""

    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.thread: threading.Thread | None = None

    def start(self, info, dest: Path) -> Ctx:
        bridge = self.bridge
        ctx = _make_ctx(bridge)

        def work():
            from core import updates
            error = ""
            try:
                ctx.stage(0.0, 1.0, t("Downloading {tag}").format(tag=info.tag))
                updates.download_installer(ctx, info, dest)
                if not updates.verify_download(dest, info.asset_size, info.sha256):
                    try:
                        dest.unlink(missing_ok=True)
                    except OSError:
                        pass
                    error = "The download did not pass the integrity check."
            except Cancelled:
                error = "Cancelled."
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
            except Exception as e:  # noqa: BLE001
                error = str(e)
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
            _emit("progress", bridge, 1.0 if not error else 0.0, "Ready." if not error else error)
            _emit("update_download_done", bridge, str(dest) if not error else "", error)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        return ctx
