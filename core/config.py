"""Twitch credentials and sign-in tokens in config.json (copied from luckytwitch_downloader.py).

Renamed on purpose: ``_read_config`` -> ``read_config`` and ``_write_config`` -> ``write_config`` (they are used
from other modules now). Behaviour is identical.
"""

from __future__ import annotations

import json

from core import paths
from luckytwitch_engine import TWITCH_CLIENT_ID, TwitchClient


def read_config() -> dict:
    try:
        data = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_config(data: dict) -> None:
    try:
        from core.files import atomic_write_json
        atomic_write_json(paths.CONFIG_PATH, data, chmod_mode=0o600)
    except Exception:
        pass




def load_credentials():
    """Own-app credentials (client id + secret), or None."""
    data = read_config()
    if data.get("client_id") and data.get("client_secret"):
        return data
    return None


def save_credentials(client_id, client_secret):
    data = read_config()
    data.update({"client_id": client_id, "client_secret": client_secret})
    write_config(data)


def clear_credentials():
    data = read_config()
    data.pop("client_id", None)
    data.pop("client_secret", None)
    write_config(data)


def save_login_tokens(access, refresh):
    """Store (or, with None, remove) the tokens of 'Sign in with Twitch'."""
    data = read_config()
    if refresh:
        data.update({"access_token": access, "refresh_token": refresh})
    else:
        data.pop("access_token", None)
        data.pop("refresh_token", None)
    write_config(data)


def make_client() -> "TwitchClient | None":
    """Build the Twitch client from what is saved: own app first, otherwise the signed-in user."""
    creds = load_credentials()
    if creds:
        return TwitchClient(creds["client_id"], creds["client_secret"])
    data = read_config()
    if data.get("refresh_token"):
        return TwitchClient(
            TWITCH_CLIENT_ID,
            access_token=data.get("access_token"),
            refresh_token=data["refresh_token"],
            on_tokens=save_login_tokens,
        )
    return None
