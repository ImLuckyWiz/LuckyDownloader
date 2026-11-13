"""
Twitch API client and Device Code Flow OAuth.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

from core.errors import Cancelled, EngineError
from core.i18n import t
from core.timeutil import parse_twitch_duration

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
DEVICE_URL = "https://id.twitch.tv/oauth2/device"
API_URL = "https://api.twitch.tv/helix"

# Client ID of LuckyTwitch's own *public* Twitch app (Device Code Flow, no secret).
# Client IDs are public by design, so it is fine to ship it inside the app.
TWITCH_CLIENT_ID = "i00ldktkshoyftnytyijdwtjofhcq9"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# Fetching clips needs no scope. Twitch documents `scopes` as required, so we first try an
# empty list and, if Twitch refuses, fall back to the least invasive scope.
_FALLBACK_SCOPE = "user:read:subscriptions"


class TwitchClient:
    """
    Twitch API client with two ways to authenticate:
      * own app:   TwitchClient(client_id, client_secret)         (client credentials)
      * signed in: TwitchClient(client_id, access_token=..., refresh_token=..., on_tokens=...)
        (user token from the Device Code Flow; no secret needed). Twitch refresh tokens are
        single use, so every refresh reports the new pair through `on_tokens(access, refresh)`.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str = "",
        access_token: str | None = None,
        refresh_token: str | None = None,
        on_tokens: Callable[[str | None, str | None], None] | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: str | None = access_token
        self.user_refresh: str | None = refresh_token
        self.on_tokens = on_tokens

    @property
    def uses_login(self) -> bool:
        return not self.client_secret

    def refresh_token(self) -> None:
        """Get a fresh access token (named like this for backwards compatibility)."""
        if self.client_secret:
            r = requests.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=20,
            )
            if r.status_code in (400, 401, 403):
                raise ValueError("Invalid Client ID or Client Secret.")
            r.raise_for_status()
            self.token = r.json()["access_token"]
            return
        if not self.user_refresh:
            raise ValueError("Not signed in to Twitch.")
        r = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self.user_refresh,
            },
            timeout=20,
        )
        if r.status_code in (400, 401, 403):
            self.token = self.user_refresh = None
            if self.on_tokens:
                self.on_tokens(None, None)
            raise ValueError("Your Twitch session expired. Sign in again (Twitch API… button).")
        r.raise_for_status()
        data = r.json()
        self.token = data["access_token"]
        self.user_refresh = data.get("refresh_token", self.user_refresh)
        if self.on_tokens:
            self.on_tokens(self.token, self.user_refresh)

    def get(self, endpoint: str, params: dict) -> dict:
        if self.token is None:
            self.refresh_token()
        for _ in range(2):
            r = requests.get(
                f"{API_URL}/{endpoint}",
                params=params,
                headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self.token}"},
                timeout=20,
            )
            if r.status_code == 401:
                self.refresh_token()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Could not authenticate with Twitch.")


def device_login_start(client_id: str = TWITCH_CLIENT_ID) -> dict:
    """Ask Twitch for a code. Returns device_code, user_code, verification_uri, expires_in, interval, scopes."""
    last = ""
    for scopes in ("", _FALLBACK_SCOPE):
        try:
            r = requests.post(DEVICE_URL, data={"client_id": client_id, "scopes": scopes}, timeout=20)
        except requests.RequestException as e:
            raise EngineError(t("Could not reach Twitch:\n{error}", error=e)) from e
        if r.ok:
            data = r.json()
            data["scopes"] = scopes
            return data
        last = r.text[:300]
    raise EngineError(t("Twitch refused the sign-in request:\n{last}", last=last))


def device_login_poll(start: dict, client_id: str = TWITCH_CLIENT_ID,
                      cancel: threading.Event | None = None) -> tuple[str, str]:
    """Wait until the user approves the code on twitch.tv/activate. Returns (access_token, refresh_token)."""
    interval = max(int(start.get("interval") or 5), 1)
    deadline = time.monotonic() + int(start.get("expires_in") or 1800)
    while time.monotonic() < deadline:
        for _ in range(interval * 4):  # sleep in small steps so cancelling is quick
            if cancel is not None and cancel.is_set():
                raise Cancelled("Sign-in cancelled.")
            time.sleep(0.25)
        try:
            r = requests.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "scopes": start.get("scopes", ""),
                    "device_code": start["device_code"],
                    "grant_type": DEVICE_GRANT,
                },
                timeout=20,
            )
        except requests.RequestException:
            continue  # network blip: keep waiting
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.ok and body.get("access_token"):
            return body["access_token"], body.get("refresh_token", "")
        msg = str(body.get("message") or body.get("error_description") or body.get("error") or "")
        if "pending" in msg.lower():
            continue
        if "slow" in msg.lower():
            interval += 5
            continue
        raise EngineError(t("Twitch sign-in failed: {error}", error=msg or r.status_code))
    raise EngineError(t("The sign-in code expired. Start again."))


def _iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clip_start(clip: dict) -> float | None:
    """
    Where the clip STARTS in the VOD, in seconds (None if Twitch gave no position).

    Twitch's `vod_offset` is where the clip ENDS in the VOD, not where it starts
    (despite what the API docs say), so the start is `vod_offset - duration`.
    """
    off = clip.get("vod_offset")
    if off is None:
        return None
    return max(0.0, float(off) - float(clip.get("duration") or 0))


def clip_end(clip: dict) -> float | None:
    """Where the clip ENDS in the VOD, in seconds (None if Twitch gave no position)."""
    off = clip.get("vod_offset")
    return None if off is None else float(off)


def fetch_clips_for_vod(client: TwitchClient, vod_id: str) -> list[dict]:
    """All clips that belong to this VOD, sorted by position in the VOD."""
    data = client.get("videos", {"id": vod_id}).get("data", [])
    if not data:
        raise EngineError(t("Twitch API: VOD not found (deleted or private?)."))
    video = data[0]
    start = datetime.strptime(video["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    end = start + timedelta(seconds=parse_twitch_duration(video["duration"]) + 300)

    clips, cursor = [], None
    while True:
        params = {
            "broadcaster_id": video["user_id"],
            "started_at": _iso_z(start),
            "ended_at": _iso_z(end),
            "first": 100,
        }
        if cursor:
            params["after"] = cursor
        page = client.get("clips", params)
        clips.extend(c for c in page.get("data", []) if c.get("video_id") == vod_id)
        cursor = page.get("pagination", {}).get("cursor")
        if not cursor:
            break
    clips.sort(key=lambda c: (clip_start(c) is None, clip_start(c) or 0))
    return clips
