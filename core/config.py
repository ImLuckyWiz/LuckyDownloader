"""Twitch credentials and sign-in tokens in config.json with OS DPAPI / keyring protection."""

from __future__ import annotations

import base64
import sys
from typing import Any

try:
    import keyring  # type: ignore[import-untyped]
except Exception:
    keyring = None

from core import paths
from core.files import JsonStore
from core.twitch_api import TWITCH_CLIENT_ID, TwitchClient

SECRET_KEYS: tuple[str, ...] = ("access_token", "refresh_token", "client_secret")
DPAPI_PREFIX = "dpapi:"
KEYRING_SERVICE = "LuckyDownloader"

_CONFIG_STORE: JsonStore[dict[str, Any]] = JsonStore(
    lambda: paths.CONFIG_PATH,
    dict,
    expected_type=dict,
    chmod_mode=0o600,
)


def _init_dpapi():
    import ctypes
    import ctypes.wintypes as wt

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wt.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wt.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        wt.LPVOID,
        wt.LPVOID,
        wt.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wt.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wt.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        wt.LPVOID,
        wt.LPVOID,
        wt.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wt.BOOL
    kernel32.LocalFree.argtypes = [wt.LPVOID]
    kernel32.LocalFree.restype = wt.LPVOID
    return ctypes, wt, _DATA_BLOB, crypt32, kernel32


def _dpapi_encrypt(plaintext: str) -> str:
    ctypes, wt, _DATA_BLOB, crypt32, kernel32 = _init_dpapi()
    raw = plaintext.encode("utf-8")
    buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        cipher = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return DPAPI_PREFIX + base64.b64encode(cipher).decode("ascii")
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, wt.LPVOID))


def _dpapi_decrypt(token: str) -> str:
    if not token.startswith(DPAPI_PREFIX):
        return token
    ctypes, wt, _DATA_BLOB, crypt32, kernel32 = _init_dpapi()
    raw = base64.b64decode(token[len(DPAPI_PREFIX):])
    buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, wt.LPVOID))


def _keyring_get(key: str) -> str | None:
    if keyring is None:
        return None
    try:
        val = keyring.get_password(KEYRING_SERVICE, key)
        return str(val) if val else None
    except Exception:
        return None


def _keyring_set(key: str, val: str) -> bool:
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, key, val)
        return True
    except Exception:
        return False


def _keyring_delete(key: str) -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except Exception:
        pass


def read_config() -> dict:
    with _CONFIG_STORE.lock():
        raw = _CONFIG_STORE.load()
        if not raw:
            return {}
        used_keyring = bool(raw.get("_keyring"))
        result: dict[str, Any] = {k: v for k, v in raw.items() if k not in SECRET_KEYS and k != "_keyring"}
        needs_migration = False
        for k in SECRET_KEYS:
            raw_val = raw.get(k)
            if raw_val is not None and raw_val != "":
                val_str = str(raw_val)
                if val_str.startswith(DPAPI_PREFIX):
                    if sys.platform == "win32":
                        try:
                            result[k] = _dpapi_decrypt(val_str)
                        except Exception:
                            pass
                else:
                    result[k] = val_str
                    needs_migration = True
            elif sys.platform != "win32" and (used_keyring or keyring is not None):
                kr_val = _keyring_get(k)
                if kr_val:
                    result[k] = kr_val

        if needs_migration:
            if sys.platform == "win32":
                write_config(result)
            elif keyring is not None:
                write_config(result)
        return result


def write_config(data: dict) -> None:
    with _CONFIG_STORE.lock():
        disk_data: dict[str, Any] = {k: v for k, v in data.items() if k not in SECRET_KEYS and k != "_keyring"}
        used_keyring = False
        if sys.platform != "win32":
            for k in SECRET_KEYS:
                val = data.get(k)
                if val is None or val == "":
                    _keyring_delete(k)
        for k in SECRET_KEYS:
            val = data.get(k)
            if val is None or val == "":
                continue
            val_str = str(val)
            if sys.platform == "win32":
                if val_str.startswith(DPAPI_PREFIX):
                    disk_data[k] = val_str
                else:
                    try:
                        disk_data[k] = _dpapi_encrypt(val_str)
                    except Exception:
                        disk_data[k] = val_str
            else:
                if _keyring_set(k, val_str):
                    used_keyring = True
                else:
                    disk_data[k] = val_str
        if used_keyring:
            disk_data["_keyring"] = True
        try:
            _CONFIG_STORE.save(disk_data)
        except Exception:
            pass


load_config = read_config
save_config = write_config


def load_credentials():
    """Own-app credentials (client id + secret), or None."""
    data = read_config()
    if data.get("client_id") and data.get("client_secret"):
        return data
    return None


def save_credentials(client_id, client_secret):
    with _CONFIG_STORE.lock():
        data = read_config()
        data.update({"client_id": client_id, "client_secret": client_secret})
        write_config(data)


def clear_credentials():
    with _CONFIG_STORE.lock():
        data = read_config()
        data.pop("client_id", None)
        data.pop("client_secret", None)
        write_config(data)


def save_login_tokens(access, refresh, user_login: str | None = None):
    """Store (or, with None, remove) the tokens of 'Sign in with Twitch'."""
    with _CONFIG_STORE.lock():
        data = read_config()
        if refresh:
            data.update({"access_token": access, "refresh_token": refresh})
            if user_login is not None:
                data["user_login"] = user_login
        else:
            data.pop("access_token", None)
            data.pop("refresh_token", None)
            data.pop("user_login", None)
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
