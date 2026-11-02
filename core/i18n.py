"""Internationalization (i18n): gettext catalogs with English as the message ID.

The call sites are ``t("English text")``; the English text is the key of the catalog, so English needs no catalog
at all. Other languages live in ``locale/<lang>/LC_MESSAGES/luckytwitch.mo`` (compiled from the ``.po`` next to it)
and are loaded with the standard library ``gettext`` (no extra runtime dependency, no Qt: ``core/`` may call
``t()`` too). A message that is missing from a catalog falls back to the English text instead of failing.

Helpers:

* ``t(text, **params)``: translate and fill ``{placeholders}``.
* ``tn(singular, plural, n, **params)``: plural forms (``n`` is also available as ``{n}``).
* ``tc(context, text, **params)``: same word, different meaning (``tc("verb", "Plan")``).
* ``N_(text)``: marks a string for extraction and returns it unchanged; translate it later with ``t(variable)``.

Tooling (extract / update / compile / check) lives in ``tools/i18n.py`` and needs Babel (dev only).
"""

from __future__ import annotations

import gettext
import locale
import os
import re
from pathlib import Path
from typing import Any

from core.resources import resource_path

LANG_AUTO = "auto"  # a setting, not a language: follow the system
LANG_EN = "en"
LANG_ES = "es"
LANG_PSEUDO = "pseudo"

_PSEUDO_ACCENTS: dict[str, str] = {
    "a": "ä", "b": "ƀ", "c": "ç", "d": "đ", "e": "ë", "f": "ƒ", "g": "ğ", "h": "ħ",
    "i": "ï", "j": "ĵ", "k": "ķ", "l": "ŀ", "m": "m", "n": "ñ", "o": "ö", "p": "þ",
    "q": "q", "r": "ř", "s": "ş", "t": "ţ", "u": "ü", "v": "v", "w": "ŵ", "x": "ẋ",
    "y": "ÿ", "z": "ž",
    "A": "Ä", "B": "Ɓ", "C": "Ç", "D": "Đ", "E": "Ë", "F": "Ƒ", "G": "Ğ", "H": "Ħ",
    "I": "Ï", "J": "Ĵ", "K": "Ķ", "L": "Ŀ", "M": "M", "N": "Ñ", "O": "Ö", "P": "Þ",
    "Q": "Q", "R": "Ř", "S": "Ş", "T": "Ţ", "U": "Ü", "V": "V", "W": "Ŵ", "X": "Ẋ",
    "Y": "Ÿ", "Z": "Ž",
}


def pseudo_localize(text: str) -> str:
    """Transform text for QA layout/truncation testing: accents characters and expands length by ~30%."""
    if not text or not text.strip():
        return text
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"\{[a-zA-Z0-9_:]*\}", text):
        pre = text[last : m.start()]
        parts.append("".join(_PSEUDO_ACCENTS.get(c, c) for c in pre))
        parts.append(m.group(0))
        last = m.end()
    post = text[last:]
    parts.append("".join(_PSEUDO_ACCENTS.get(c, c) for c in post))
    transformed = "".join(parts)
    pad_len = max(2, int(len(text) * 0.3))
    pad = "~" * pad_len
    return f"[{transformed} {pad}]"


class PseudoTranslations(gettext.NullTranslations):
    def gettext(self, message: str) -> str:
        return pseudo_localize(message)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        msg = singular if n == 1 else plural
        return pseudo_localize(msg)

SUPPORTED_LANGUAGES = {
    LANG_EN: "English",
    LANG_ES: "Español",
}

DEFAULT_LANGUAGE = LANG_EN

DOMAIN = "luckydownloader"
LEGACY_DOMAIN = "luckytwitch"
LOCALE_DIR: Path = resource_path("locale")

_current_language = DEFAULT_LANGUAGE
_translations: gettext.NullTranslations = gettext.NullTranslations()
_cache: dict[str, gettext.NullTranslations] = {}


def set_locale_dir(path: str | os.PathLike[str]) -> None:
    """Point the loader at another ``locale`` folder (used by tests) and re-load the active language."""
    global LOCALE_DIR
    LOCALE_DIR = Path(path)
    _cache.clear()
    set_language(_current_language)


def _load(lang: str) -> gettext.NullTranslations:
    """Return the translations object of ``lang`` (English or a missing catalog: the null object, keys pass through)."""
    if lang == LANG_PSEUDO:
        return PseudoTranslations()
    if lang == LANG_EN:
        return gettext.NullTranslations()
    cached = _cache.get(lang)
    if cached is not None:
        return cached
    try:
        tr: gettext.NullTranslations = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[lang])
    except OSError:
        try:
            tr = gettext.translation(LEGACY_DOMAIN, localedir=str(LOCALE_DIR), languages=[lang])
        except OSError:
            tr = gettext.NullTranslations()
    


    _cache[lang] = tr
    return tr


def language_from_locale_name(name: str | None) -> str:
    """Map a locale name (``es_UY.UTF-8``, ``es-ES``, ``Spanish_Uruguay``, ``en_US``, ``C``) to a supported language."""
    if not name:
        return LANG_EN
    low = name.strip().lower()
    for code in SUPPORTED_LANGUAGES:
        if low == code or low.startswith((code + "_", code + "-", code + ".", code + "@")):
            return code
    if low.startswith("spanish"):  # Windows' C runtime reports English names ("Spanish_Uruguay")
        return LANG_ES
    return LANG_EN


def get_system_language() -> str:
    """Detect the system language from the environment or the C locale. Returns a supported code ('en' or 'es').

    The Qt layer prefers ``QLocale.system()`` (see ``qt_ui/i18n_qt.py``), which is the reliable source on Windows and
    macOS; this is the Qt-free fallback used by ``core`` and by the command line.
    """
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            return language_from_locale_name(value)
    try:
        return language_from_locale_name(locale.getlocale()[0])
    except (ValueError, TypeError):
        return LANG_EN


def resolve_language(setting: str | None, system: str | None = None) -> str:
    """Turn the saved setting ('auto', 'en', 'es', 'pseudo' or garbage) into the language to show."""
    if setting == LANG_PSEUDO:
        return LANG_PSEUDO
    if setting in SUPPORTED_LANGUAGES:
        return str(setting)
    return system if system in SUPPORTED_LANGUAGES else get_system_language()


def set_language(lang: str) -> None:
    """Set active interface language ('en', 'es', or 'pseudo'); an unsupported code falls back to English."""
    global _current_language, _translations
    _current_language = lang if (lang == LANG_PSEUDO or lang in SUPPORTED_LANGUAGES) else DEFAULT_LANGUAGE
    _translations = _load(_current_language)


def get_language() -> str:
    """Get active interface language code ('en' or 'es')."""
    return _current_language


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def extract_placeholders(text: str) -> set[str]:
    """Extract format placeholders like {name} or {0} from text."""
    return set(_PLACEHOLDER_RE.findall(text))


def _fill(text: str, params: dict[str, Any]) -> str:
    """Fill ``{placeholders}``; a catalog entry with a wrong placeholder must not crash the UI, so it is shown as is."""
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def t(text: str, **kwargs: Any) -> str:
    """Translate user-facing text to the active language and format placeholders."""
    # gettext("") returns the catalog header, so the empty string must never reach it
    result = _translations.gettext(text) if text else text
    return _fill(result, kwargs)


def tn(singular: str, plural: str, n: int, **kwargs: Any) -> str:
    """Plural-aware translation: ``tn("{n} clip", "{n} clips", count)``; ``{n}`` is always filled with ``n``."""
    kwargs["n"] = n
    return _fill(_translations.ngettext(singular, plural, n), kwargs)


def tc(context: str, text: str, **kwargs: Any) -> str:
    """Translation with a context, for words that mean different things: ``tc("verb", "Plan")`` vs the tab name."""
    return _fill(_translations.pgettext(context, text), kwargs)


def N_(text: str) -> str:
    """Mark ``text`` for extraction without translating it now (``TABS = (N_("Plan"), ...)``; later ``t(name)``)."""
    return text
