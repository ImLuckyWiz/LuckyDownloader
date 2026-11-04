#!/usr/bin/env python3
"""Translation tooling for LuckyTwitch (gettext ``.po``/``.mo`` catalogs, English text as the message ID).

Usage (from the repository root; needs Babel, which is a dev-only dependency)::

    python tools/i18n.py extract    # code -> locale/luckytwitch.pot
    python tools/i18n.py update     # extract, then merge new messages into every locale/<lang>/.../luckytwitch.po
    python tools/i18n.py compile    # .po -> .mo (the file the app loads)
    python tools/i18n.py check      # guard rails; exit code 1 when something is wrong (also run by the test suite)
    python tools/i18n.py scan       # user-facing literals that are not wrapped in t() yet (grouped by file)
    python tools/i18n.py baseline   # re-write tools/i18n_baseline.json (refuses to let the gaps grow)
    python tools/i18n.py status     # short coverage report

How strings are found: Babel reads ``t("..")``, ``tn("..", "..", n)``, ``tc("ctx", "..")`` and ``N_("..")`` calls
(mapping in ``babel.cfg``). A string that reaches ``t()`` only through a variable or a helper (tab names, option
titles, ``card.add_row("Label")``) is *indirect*: if the exact text is already in a ``.po`` and appears as a literal in
the code, it is kept in the ``.pot`` marked as indirect. New code should use ``t()`` or ``N_()`` explicitly.

Guard rails (see ``check``): the ``.pot`` is current; no empty/fuzzy/obsolete entries (beyond the ratchet baseline in
``tools/i18n_baseline.json``); placeholders, ``&`` accelerators, ellipsis, trailing punctuation and surrounding spaces
match the English text; Spanish differs from English unless allow-listed; glossary terms are respected; the committed
``.mo`` equals the ``.po``; and the number of user-facing literals without ``t()`` can only shrink.
"""

from __future__ import annotations

import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import ast
import collections
import datetime as _dt
import io
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

try:  # Babel is a dev-only dependency; the app itself never imports this file
    from babel.messages.catalog import Catalog
    from babel.messages.extract import extract_from_dir
    from babel.messages.mofile import read_mo, write_mo
    from babel.messages.pofile import read_po, write_po
except ImportError:  # pragma: no cover - message for humans
    sys.exit("Babel is required for tools/i18n.py: python -m pip install -r requirements-dev.txt")

ROOT = Path(__file__).resolve().parent.parent
LOCALE_DIR = ROOT / "locale"
POT_PATH = LOCALE_DIR / "luckydownloader.pot"
BABEL_CFG = ROOT / "babel.cfg"
BASELINE_PATH = ROOT / "tools" / "i18n_baseline.json"
GLOSSARY_PATH = ROOT / "docs" / "i18n-glossary-es.md"
DOMAIN = "luckydownloader"
PROJECT = "LuckyDownloader"
LANGUAGES = ("es",)
PLURAL_FORMS = {"es": (2, "(n != 1)")}  # forms a language needs; Spanish: 1 = singular, everything else = plural
KEYWORDS: dict[str, Any] = {"t": None, "_t": None, "tn": (1, 2), "tc": ((1, "c"), 2), "N_": None}
COMMENT_TAGS = ("i18n:",)
INDIRECT_COMMENT = "indirect: reached through a variable or a helper (tab names, option titles, add_row...)"

# Source files that are scanned. core/i18n.py only defines the helpers (its docstring shows examples).
SOURCE_DIRS = ("core", "qt_ui")
SOURCE_FILES = ("luckytwitch_qt.py", "luckytwitch_engine.py")
SOURCE_EXCLUDE = {"core/i18n.py"}

Key = tuple  # (context or None, msgid)


# --------------------------------------------------------------------------------------------------------------------
# Paths and small helpers
# --------------------------------------------------------------------------------------------------------------------


def po_path(lang: str) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.po"


def mo_path(lang: str) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"


def source_files() -> list[Path]:
    files: list[Path] = []
    for d in SOURCE_DIRS:
        files.extend(p for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts)
    files.extend(ROOT / f for f in SOURCE_FILES if (ROOT / f).is_file())
    out = [p for p in files if rel(p) not in SOURCE_EXCLUDE]
    return sorted(out, key=rel)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:  # a file outside the repository (tests use temporary folders)
        return path.as_posix()


def _read_mapping() -> tuple[list, dict]:
    from babel.messages import frontend

    parse = getattr(frontend, "parse_mapping_cfg", None)
    with open(BABEL_CFG, encoding="utf-8") as fh:
        if parse is not None:
            return parse(fh, filename=str(BABEL_CFG))
        return frontend.parse_mapping(fh)  # older Babel


def _key(message) -> Key:
    msgid = message.id[0] if isinstance(message.id, (tuple, list)) else message.id
    return (message.context or None, msgid)


def _strings(value) -> tuple[str, ...]:
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


# --------------------------------------------------------------------------------------------------------------------
# Extraction (code -> .pot)
# --------------------------------------------------------------------------------------------------------------------


def extract_calls() -> dict[Key, dict]:
    """Messages found in t/tn/tc/N_ calls: key -> {"plural", "files", "comments"}."""
    mapping, options = _read_mapping()
    found: dict[Key, dict] = {}
    for filename, _lineno, message, comments, context in extract_from_dir(
        str(ROOT), method_map=mapping, options_map=options, keywords=KEYWORDS, comment_tags=COMMENT_TAGS
    ):
        if rel(ROOT / filename) in SOURCE_EXCLUDE:
            continue
        if isinstance(message, (tuple, list)):
            singular, plural = message[0], message[1] if len(message) > 1 else None
        else:
            singular, plural = message, None
        if not singular:
            continue
        entry = found.setdefault((context or None, singular), {"plural": None, "files": set(), "comments": []})
        entry["plural"] = entry["plural"] or plural
        entry["files"].add(Path(filename).as_posix())
        for c in comments:
            if c not in entry["comments"]:
                entry["comments"].append(c)
    return found


def _string_literals() -> dict[str, set[str]]:
    """Every string literal of the source files: text -> {files}."""
    lits: dict[str, set[str]] = collections.defaultdict(set)
    for p in source_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lits[node.value].add(rel(p))
    return lits


def read_catalog(lang: str) -> Catalog | None:
    path = po_path(lang)
    if not path.is_file():
        return None
    with open(path, "rb") as fh:
        return read_po(fh, locale=lang, domain=DOMAIN)


def indirect_keys(found: dict[Key, dict]) -> dict[Key, set[str]]:
    """Existing ``.po`` messages that are not in a call but whose exact text is a literal somewhere in the code."""
    lits = _string_literals()
    out: dict[Key, set[str]] = {}
    for lang in LANGUAGES:
        cat = read_catalog(lang)
        if cat is None:
            continue
        for m in cat:
            if not m.id:
                continue
            key = _key(m)
            if key in found or key[0] is not None or isinstance(m.id, (tuple, list)):
                continue
            if key[1] in lits:
                out.setdefault(key, set()).update(lits[key[1]])
    return out


def build_pot_catalog() -> Catalog:
    found = extract_calls()
    indirect = indirect_keys(found)
    cat = Catalog(project=PROJECT, version="", charset="utf-8", fuzzy=False, msgid_bugs_address="")
    cat.header_comment = (
        "# LuckyTwitch Downloader message template.\n"
        "# Generated by `python tools/i18n.py extract`; do not edit by hand."
    )
    for (ctx, msgid), info in sorted(found.items(), key=lambda kv: (sorted(kv[1]["files"])[0], kv[0][1])):
        locations = [(f, 0) for f in sorted(info["files"])]
        if info["plural"]:
            cat.add((msgid, info["plural"]), string=("", ""), locations=locations, auto_comments=info["comments"], context=ctx)
        else:
            cat.add(msgid, string="", locations=locations, auto_comments=info["comments"], context=ctx)
    for (ctx, msgid), files in sorted(indirect.items(), key=lambda kv: (sorted(kv[1])[0], kv[0][1])):
        cat.add(msgid, string="", locations=[(f, 0) for f in sorted(files)], auto_comments=[INDIRECT_COMMENT], context=ctx)
    return cat


_DATE_LINE = re.compile(r'^"(POT-Creation-Date|PO-Revision-Date):.*$', re.M)


def _normalized(text: str) -> str:
    return _DATE_LINE.sub("", text.replace("\r\n", "\n"))


_HEADER_FIXES = (  # Babel's placeholder values and its version number would only add noise to the diffs
    (re.compile(r'^"Project-Id-Version: (.*?) VERSION\\n"$', re.M), r'"Project-Id-Version: \1\\n"'),
    (re.compile(r'^"Report-Msgid-Bugs-To: .*\\n"$', re.M), r'"Report-Msgid-Bugs-To: \\n"'),
    (re.compile(r'^"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"$', re.M), r'"Last-Translator: \\n"'),
    (re.compile(r'^"Language-Team: LANGUAGE <LL@li.org>\\n"$', re.M), r'"Language-Team: \\n"'),
    (re.compile(r'^"Generated-By: .*\\n"$', re.M), r'"Generated-By: tools/i18n.py (Babel)\\n"'),
)


def _po_text(cat: Catalog, **kwargs: Any) -> str:
    buf = io.BytesIO()
    write_po(buf, cat, width=100, include_lineno=False, **kwargs)
    text = buf.getvalue().decode("utf-8")
    for pattern, repl in _HEADER_FIXES:
        text = pattern.sub(repl, text, count=1)
    return text


def _write_if_changed(path: Path, new_text: str) -> bool:
    """Write ``new_text`` unless only the date headers differ (keeps diffs and the ``.pot`` check quiet)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and _normalized(path.read_text(encoding="utf-8")) == _normalized(new_text):
        return False
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


def cmd_extract() -> int:
    changed = _write_if_changed(POT_PATH, _po_text(build_pot_catalog()))
    print(f"{rel(POT_PATH)}: {'updated' if changed else 'already up to date'}")
    return 0


# --------------------------------------------------------------------------------------------------------------------
# Update (.pot -> .po) and compile (.po -> .mo)
# --------------------------------------------------------------------------------------------------------------------


def new_language_catalog(lang: str) -> Catalog:
    nplurals, expr = PLURAL_FORMS[lang]
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    cat = Catalog(
        locale=lang, domain=DOMAIN, project=PROJECT, version="", charset="utf-8", fuzzy=False,
        last_translator="LuckyTwitch contributors", language_team=lang, msgid_bugs_address="",
        creation_date=now, revision_date=now,
    )
    cat.header_comment = f"# {PROJECT}: translation for '{lang}'.\n# Edit with Poedit or by hand, then run `python tools/i18n.py compile`."
    cat._num_plurals = nplurals  # type: ignore[attr-defined]  # Babel has no public setter
    cat._plural_expr = expr  # type: ignore[attr-defined]
    return cat


def merge_into(lang: str, pot: Catalog) -> tuple[Catalog, list[str], list[str]]:
    """Add the messages of ``pot`` that ``lang`` lacks (empty translation) and refresh locations/comments.

    Nothing is ever deleted or marked fuzzy here: entries that are no longer in the code are only reported.
    """
    cat = read_catalog(lang) or new_language_catalog(lang)
    added: list[str] = []
    pot_keys: set[Key] = set()
    for m in pot:
        if not m.id:
            continue
        key = _key(m)
        pot_keys.add(key)
        existing = cat.get(m.id, m.context)
        if existing is None:
            n = PLURAL_FORMS[lang][0] if isinstance(m.id, (tuple, list)) else 1
            cat.add(m.id, string=("",) * n if n > 1 else "", locations=m.locations, auto_comments=m.auto_comments, context=m.context)
            added.append(key[1])
        else:
            existing.locations = list(m.locations)
            existing.auto_comments = list(m.auto_comments)
    missing = [_key(m)[1] for m in cat if m.id and _key(m) not in pot_keys]
    return cat, added, missing


def cmd_update() -> int:
    pot = build_pot_catalog()
    _write_if_changed(POT_PATH, _po_text(pot))
    for lang in LANGUAGES:
        cat, added, missing = merge_into(lang, pot)
        changed = _write_if_changed(po_path(lang), _po_text(cat))
        print(f"{rel(po_path(lang))}: {'updated' if changed else 'already up to date'}; {len(added)} new, {len(missing)} not in the code")
        for text in added:
            print(f"  + {text!r}")
    return 0


def compile_po(lang: str) -> bytes:
    cat = read_catalog(lang)
    if cat is None:
        raise SystemExit(f"{rel(po_path(lang))} does not exist")
    buf = io.BytesIO()
    write_mo(buf, cat, use_fuzzy=False)
    return buf.getvalue()


def cmd_compile() -> int:
    for lang in LANGUAGES:
        data = compile_po(lang)
        path = mo_path(lang)
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)
            print(f"{rel(path)}: written")
        else:
            print(f"{rel(path)}: already up to date")
    return 0


# --------------------------------------------------------------------------------------------------------------------
# Catalog hygiene
# --------------------------------------------------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_ACCELERATOR = re.compile(r"(?<!&)&(?!&)(?=\w)")  # "&Open" is an accelerator; " & " and "&&" are literal ampersands
_END_PUNCT = ".:!?…"


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


def load_baseline() -> dict[str, Any]:
    if BASELINE_PATH.is_file():
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("untranslated", [])  # extracted messages allowed to have no translation yet (ratchet)
    data.setdefault("dead", [])  # .po entries that are in no source file (kept for upcoming phases; ratchet)
    data.setdefault("unwrapped", {})  # file -> {text: count} of user-facing literals without t() (ratchet)
    data.setdefault("identical_ok", [])  # messages whose Spanish text is legitimately the English text
    data.setdefault("glossary_exempt", [])  # messages exempt from the glossary check
    return data


def load_glossary() -> tuple[list[tuple[str, list[str]]], list[str]]:
    """(terms, keep_as_is) from docs/i18n-glossary-es.md.

    ``terms``: [(english term, [accepted Spanish words])] from the table rows ``| english | español | note |``.
    ``keep_as_is``: tokens that must stay unchanged (``Keep as-is:`` line, backticked words).
    """
    terms: list[tuple[str, list[str]]] = []
    keep: list[str] = []
    if not GLOSSARY_PATH.is_file():
        return terms, keep
    for line in GLOSSARY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.lower().startswith("keep as-is:"):
            keep.extend(re.findall(r"`([^`]+)`", line))
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: ") or cells[0].lower() == "english":
                continue
            es = [w.strip() for w in re.split(r"[/,]", cells[1]) if w.strip()]
            if cells[0] and es:
                terms.append((cells[0].lower(), es))
    return terms, keep


def _term_regex(term: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(term) + r"(?:s|es|d|ed|ing)?\b", re.I)


def _is_translated(m) -> bool:
    return bool(m.string) and all(_strings(m.string)) and not m.fuzzy


def message_problems(lang: str, m, baseline: dict[str, Any]) -> list[str]:
    """Hygiene problems of one translated message (empty/fuzzy messages are handled by the caller)."""
    problems: list[str] = []
    ids = _strings(m.id)
    outs = _strings(m.string)
    label = f"[{lang}] {ids[0]!r}"
    src_ph = set().union(*(placeholders(i) for i in ids))
    n_forms = PLURAL_FORMS[lang][0]
    if len(ids) > 1 and len(outs) != n_forms:
        problems.append(f"{label}: needs {n_forms} plural forms, has {len(outs)}")
    for idx, out in enumerate(outs):
        src = ids[0] if (len(ids) == 1 or idx == 0) else ids[1]  # plural entries: form 0 <-> singular, the rest <-> plural
        out_ph = placeholders(out)
        if len(ids) == 1 or idx == len(outs) - 1:
            if out_ph != src_ph:
                problems.append(f"{label}: placeholders differ (source {sorted(src_ph)}, translation {sorted(out_ph)})")
        elif not out_ph <= src_ph:
            problems.append(f"{label}: translation uses unknown placeholders {sorted(out_ph - src_ph)}")
        if len(_ACCELERATOR.findall(src)) != len(_ACCELERATOR.findall(out)):
            problems.append(f"{label}: keyboard accelerator '&' count differs")
        if src.count("…") != out.count("…") or src.count("...") != out.count("..."):
            problems.append(f"{label}: ellipsis differs (use … exactly as the English text does)")
        if (src[-1:] if src[-1:] in _END_PUNCT else "") != (out[-1:] if out[-1:] in _END_PUNCT else ""):
            problems.append(f"{label}: trailing punctuation differs")
        if (src != src.lstrip()) != (out != out.lstrip()) or (src != src.rstrip()) != (out != out.rstrip()):
            problems.append(f"{label}: leading/trailing spaces differ")
        if src.count("\n") != out.count("\n"):
            problems.append(f"{label}: line breaks differ")
    sources = [ids[0] if (len(ids) == 1 or i == 0) else ids[1] for i in range(len(outs))]
    if lang == "es" and list(outs) == sources and ids[0] not in baseline["identical_ok"] and not m.context:
        problems.append(f"{label}: Spanish text equals the English text (translate it, or add it to identical_ok)")
    return problems


def glossary_problems(lang: str, m, baseline: dict[str, Any], terms, keep) -> list[str]:
    if lang != "es" or _strings(m.id)[0] in baseline["glossary_exempt"]:
        return []
    problems: list[str] = []
    src = " ".join(_strings(m.id))
    out = _fold(" ".join(_strings(m.string)))
    for term, spanish in terms:
        if _term_regex(term).search(src) and not any(re.search(r"\b" + re.escape(_fold(w)), out) for w in spanish):
            problems.append(f"[{lang}] {_strings(m.id)[0]!r}: glossary says '{term}' = {' / '.join(spanish)}")
    for token in keep:
        if re.search(r"(?<![\w-])" + re.escape(token) + r"s?(?![\w-])", src) and _fold(token) not in out:
            problems.append(f"[{lang}] {_strings(m.id)[0]!r}: '{token}' must stay unchanged")
    return problems


def _po_keys(cat: Catalog) -> dict[Key, Any]:
    return {_key(m): m for m in cat if m.id}


def mo_problems(lang: str) -> list[str]:
    path = mo_path(lang)
    if not path.is_file():
        return [f"{rel(path)} is missing: run `python tools/i18n.py compile` and commit it"]
    cat = read_catalog(lang)
    with open(path, "rb") as fh:
        compiled = read_mo(fh)
    want = {k: _strings(m.string) for k, m in _po_keys(cat).items() if _is_translated(m)}
    have = {_key(m): _strings(m.string) for m in compiled if m.id}
    if want != have:
        return [f"{rel(path)} does not match {rel(po_path(lang))}: run `python tools/i18n.py compile`"]
    return []


def catalog_problems(lang: str) -> list[str]:
    """Everything wrong with one language's ``.po`` (including the ratchet baselines and the ``.mo``)."""
    baseline = load_baseline()
    cat = read_catalog(lang)
    if cat is None:
        return [f"{rel(po_path(lang))} is missing"]
    terms, keep = load_glossary()
    problems: list[str] = []
    for m in cat.obsolete.values():
        problems.append(f"[{lang}] obsolete entry {_strings(m.id)[0]!r}: delete it from the .po")
    pot_keys = {_key(m) for m in build_pot_catalog() if m.id}
    po = _po_keys(cat)
    untranslated = set()
    for key, m in po.items():
        if not _is_translated(m):
            untranslated.add(key[1])
            continue
        problems.extend(message_problems(lang, m, baseline))
        problems.extend(glossary_problems(lang, m, baseline, terms, keep))
    # a message found in the code must be in the .po (run `update`) and translated unless it is in the baseline
    for key in sorted(pot_keys - set(po), key=str):
        problems.append(f"[{lang}] {key[1]!r} is in the code but not in the .po: run `python tools/i18n.py update`")
    stuck = {k[1] for k in pot_keys & set(po)} & untranslated
    for text in sorted(stuck - set(baseline["untranslated"])):
        problems.append(f"[{lang}] {text!r} has no translation (empty or fuzzy)")
    for text in sorted(set(baseline["untranslated"]) - stuck):
        problems.append(f"[{lang}] {text!r} is translated now: remove it from 'untranslated' in tools/i18n_baseline.json")
    # entries that are in no source file: only the baseline may have them, and it may only shrink
    dead = {k[1] for k in set(po) - pot_keys}
    for text in sorted(dead - set(baseline["dead"])):
        problems.append(f"[{lang}] {text!r} is in the .po but nowhere in the code (obsolete?); delete it or wire it up")
    for text in sorted(set(baseline["dead"]) - dead):
        problems.append(f"[{lang}] {text!r} is used now (or gone): remove it from 'dead' in tools/i18n_baseline.json")
    problems.extend(mo_problems(lang))
    return problems


def pot_problems() -> list[str]:
    fresh = _normalized(_po_text(build_pot_catalog()))
    if not POT_PATH.is_file():
        return [f"{rel(POT_PATH)} is missing: run `python tools/i18n.py extract`"]
    if _normalized(POT_PATH.read_text(encoding="utf-8")) != fresh:
        return [f"{rel(POT_PATH)} is out of date: run `python tools/i18n.py update`"]
    return []


# --------------------------------------------------------------------------------------------------------------------
# Unwrapped literals (AST scan)
# --------------------------------------------------------------------------------------------------------------------

# Calls that put their text arguments in front of the user. Strings given to them without t() are gaps.
UI_SINK_CALLS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "Card", "WrapLabel", "Collapsible",
    "CaptionButton",
}
UI_SINK_METHODS = {
    "setText", "setToolTip", "setStatusTip", "setPlaceholderText", "setWindowTitle", "setTitle", "setAccessibleName",
    "setAccessibleDescription", "addItem", "addAction", "setHtml", "setPlainText", "add_row", "_heading", "_card",
    "show_message", "set_status", "set_title", "set_progress", "set_preview", "ask_yes_no", "ask_ok_cancel", "info",
    "warning", "error", "success", "_say", "emit", "add_filter_field", "_advanced", "_template_row", "system_notify",
    "open_file", "save_file", "choose_folder", "getExistingDirectory", "stage",
}
CORE_SINK_CALLS = {"PlanError", "EngineError"}


def _literal_text(node: ast.AST) -> str | None:
    """Text of a string literal or f-string (every ``{...}`` becomes ``{}``); None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _looks_like_prose(text: str) -> bool:
    if not re.search(r"[A-Za-z]{3}", text):
        return False
    if text.startswith(("color:", "font", "#", "http", "QToolTip", "luckytwitch:")):
        return False
    if " " not in text and "\n" not in text and not text[:1].isupper() and "…" not in text:
        return False  # identifiers, keys and status words such as "queued"
    return True


def _is_ctx_log(func: ast.AST) -> bool:
    if not (isinstance(func, ast.Attribute) and func.attr == "log"):
        return False
    base = func.value
    return (isinstance(base, ast.Name) and base.id == "ctx") or (isinstance(base, ast.Attribute) and base.attr == "ctx")


def scan_source(source: str, name: str) -> dict[str, int]:
    """Unwrapped user-facing literals of one source text (``name`` decides whether UI or core sinks apply)."""
    is_ui = name.startswith("qt_ui/") or name == "luckytwitch_qt.py"
    counts: collections.Counter[str] = collections.Counter()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if is_ui:
            hit = fname in UI_SINK_CALLS or fname in UI_SINK_METHODS
        else:
            hit = fname in CORE_SINK_CALLS or _is_ctx_log(func)
        if not hit:
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            text = _literal_text(arg)
            if text is not None and _looks_like_prose(text):
                counts[text] += 1
    return dict(sorted(counts.items()))


def scan_unwrapped() -> dict[str, dict[str, int]]:
    """User-facing literals that reach a widget, dialog, log or error without ``t()``: file -> {text: count}."""
    out: dict[str, dict[str, int]] = {}
    for p in source_files():
        counts = scan_source(p.read_text(encoding="utf-8"), rel(p))
        if counts:
            out[rel(p)] = counts
    return out


def unwrapped_problems() -> list[str]:
    base = load_baseline()["unwrapped"]
    now = scan_unwrapped()
    problems: list[str] = []
    for fname in sorted(set(now) | set(base)):
        cur, old = now.get(fname, {}), base.get(fname, {})
        for text in sorted(set(cur) | set(old)):
            if cur.get(text, 0) > old.get(text, 0):
                problems.append(f"{fname}: user-facing text without t(): {text!r} (wrap it in t(), or N_() if it is translated later)")
            elif cur.get(text, 0) < old.get(text, 0):
                problems.append(f"{fname}: {text!r} is wrapped or gone: run `python tools/i18n.py baseline` to shrink the baseline")
    return problems


def total_unwrapped(data: dict[str, dict[str, int]]) -> int:
    return sum(sum(v.values()) for v in data.values())


def cmd_scan() -> int:
    now = scan_unwrapped()
    for fname, texts in now.items():
        print(f"{fname}: {sum(texts.values())}")
    print(f"total: {total_unwrapped(now)} literals ({sum(len(v) for v in now.values())} distinct) without t()")
    return 0


# --------------------------------------------------------------------------------------------------------------------
# Baseline, check, status
# --------------------------------------------------------------------------------------------------------------------


def current_gaps() -> dict[str, Any]:
    """The three ratchet lists as they are right now."""
    pot_keys = {_key(m) for m in build_pot_catalog() if m.id}
    untranslated: set[str] = set()
    dead: set[str] = set()
    for lang in LANGUAGES:
        cat = read_catalog(lang)
        if cat is None:
            continue
        po = _po_keys(cat)
        untranslated |= {k[1] for k, m in po.items() if k in pot_keys and not _is_translated(m)}
        untranslated |= {k[1] for k in pot_keys - set(po)}
        dead |= {k[1] for k in set(po) - pot_keys}
    return {"untranslated": sorted(untranslated), "dead": sorted(dead), "unwrapped": scan_unwrapped()}


def cmd_baseline(allow_growth: bool) -> int:
    old = load_baseline()
    new = current_gaps()
    growth: list[str] = []
    for key in ("untranslated", "dead"):
        extra = set(new[key]) - set(old[key])
        if extra and not allow_growth and old[key] is not None and BASELINE_PATH.is_file():
            growth.append(f"{key}: {len(extra)} new ({', '.join(repr(x) for x in sorted(extra)[:3])}...)")
    for fname, texts in new["unwrapped"].items():
        if sum(texts.values()) > sum(old["unwrapped"].get(fname, {}).values()) and BASELINE_PATH.is_file() and not allow_growth:
            growth.append(f"unwrapped: {fname} grew")
    if growth:
        print("The baseline may only shrink. Fix these instead (or pass --allow-growth deliberately):")
        for g in growth:
            print("  -", g)
        return 1
    data = {**old, **new}
    BASELINE_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{rel(BASELINE_PATH)} written: {len(new['untranslated'])} untranslated, {len(new['dead'])} dead, "
          f"{total_unwrapped(new['unwrapped'])} unwrapped literals")
    return 0


def run_checks() -> list[str]:
    problems = pot_problems()
    for lang in LANGUAGES:
        problems.extend(catalog_problems(lang))
    problems.extend(unwrapped_problems())
    return problems


def cmd_check() -> int:
    problems = run_checks()
    for p in problems:
        print("-", p)
    if problems:
        print(f"{len(problems)} problem(s).")
        return 1
    print("i18n check passed.")
    return 0


def cmd_status() -> int:
    pot = build_pot_catalog()
    total = sum(1 for m in pot if m.id)
    print(f"messages in the code: {total}")
    for lang in LANGUAGES:
        cat = read_catalog(lang)
        if cat is None:
            print(f"[{lang}] no .po")
            continue
        done = sum(1 for m in cat if m.id and _is_translated(m))
        print(f"[{lang}] translated entries: {done}")
    print(f"literals without t(): {total_unwrapped(scan_unwrapped())}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("extract", "update", "compile", "check", "scan", "status"):
        sub.add_parser(name)
    bl = sub.add_parser("baseline")
    bl.add_argument("--allow-growth", action="store_true", help="accept new gaps (only for a deliberate decision)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "baseline":
        return cmd_baseline(args.allow_growth)
    return {
        "extract": cmd_extract, "update": cmd_update, "compile": cmd_compile,
        "check": cmd_check, "scan": cmd_scan, "status": cmd_status,
    }[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
