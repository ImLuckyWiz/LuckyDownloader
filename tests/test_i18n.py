"""Tests for the i18n layer (Phase I0): gettext runtime, catalog hygiene, and the coverage ratchets.

The tooling lives in ``tools/i18n.py`` (``python tools/i18n.py check`` runs the same checks from the command line).
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

from core import i18n
from core.i18n import (
    DEFAULT_LANGUAGE,
    LANG_EN,
    LANG_ES,
    SUPPORTED_LANGUAGES,
    N_,
    extract_placeholders,
    get_language,
    get_system_language,
    set_language,
    t,
    tc,
    tn,
)

ROOT = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location("lt_i18n_tool", ROOT / "tools" / "i18n.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load_tool()


@pytest.fixture(autouse=True)
def _english_after_each_test():
    yield
    i18n.set_locale_dir(ROOT / "locale")
    set_language(LANG_EN)


# --------------------------------------------------------------------------------------------------------------------
# Runtime API
# --------------------------------------------------------------------------------------------------------------------


def test_supported_languages():
    assert LANG_EN in SUPPORTED_LANGUAGES
    assert LANG_ES in SUPPORTED_LANGUAGES
    assert SUPPORTED_LANGUAGES[LANG_ES] == "Español"
    assert SUPPORTED_LANGUAGES[LANG_EN] == "English"


def test_set_and_get_language():
    set_language(LANG_ES)
    assert get_language() == LANG_ES
    set_language(LANG_EN)
    assert get_language() == LANG_EN
    set_language("fr")  # unsupported code falls back to the default
    assert get_language() == DEFAULT_LANGUAGE


def test_t_function_translates_and_formats():
    set_language(LANG_ES)
    assert t("Plan") == "Plan"
    assert t("Search") == "Buscar"
    assert t("Queue & log") == "Cola y registros"
    assert t("Start queue") == "Iniciar cola"
    assert t("Cancel current") == "Cancelar actual"
    assert t("Signed in as {user}", user="Lucky") == "Sesión iniciada como Lucky"
    # a message that is not in the catalog falls back to the original text (also with placeholders)
    assert t("Untranslated message") == "Untranslated message"
    assert t("Untranslated {x}", x=3) == "Untranslated 3"

    set_language(LANG_EN)
    assert t("Search") == "Search"
    assert t("Signed in as {user}", user="Lucky") == "Signed in as Lucky"


def test_t_never_returns_the_catalog_header():
    set_language(LANG_ES)
    assert t("") == ""


def test_t_survives_wrong_placeholders():
    set_language(LANG_ES)
    assert t("Signed in as {user}") == "Sesión iniciada como {user}"  # missing parameter: shown as is
    assert t("Search", unused=1) == "Buscar"


def test_tn_plural_forms():
    for lang in (LANG_EN, LANG_ES):
        set_language(lang)
        assert tn("{n} clip", "{n} clips", 1) == "1 clip"
        assert tn("{n} clip", "{n} clips", 0) == "0 clips"
        assert tn("{n} clip", "{n} clips", 2) == "2 clips"
    # a message may use its own placeholder name (for example to show a locale-formatted number)
    assert tn("{count} clip", "{count} clips", 2, count="dos") == "dos clips"


def test_tc_context_passes_through_and_formats():
    for lang in (LANG_EN, LANG_ES):
        set_language(lang)
        assert tc("verb", "Plan") == "Plan"
        assert tc("tab", "Hello {who}", who="x") == "Hello x"


def test_n_marks_without_translating():
    set_language(LANG_ES)
    assert N_("Search") == "Search"
    assert t(N_("Search")) == "Buscar"


def test_missing_catalog_falls_back_to_english(tmp_path):
    i18n.set_locale_dir(tmp_path)  # an empty locale folder
    set_language(LANG_ES)
    assert get_language() == LANG_ES
    assert t("Search") == "Search"
    assert tn("{n} item", "{n} items", 2) == "2 items"


def test_corrupt_catalog_falls_back_to_english(tmp_path):
    bad = tmp_path / "es" / "LC_MESSAGES"
    bad.mkdir(parents=True)
    (bad / f"{i18n.DOMAIN}.mo").write_bytes(b"not a catalog")
    i18n.set_locale_dir(tmp_path)
    set_language(LANG_ES)
    assert t("Search") == "Search"


def test_catalog_with_plural_forms_is_used(tmp_path):
    """A hand-made .mo with a plural entry proves ngettext works through our loader (not only the English fallback)."""
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo

    cat = Catalog(locale="es", domain=i18n.DOMAIN)
    cat.add(("{n} clip", "{n} clips"), string=("{n} clip (uno)", "{n} clips (varios)"))
    cat.add("Plan", string="Plan", context="verb")
    cat.add("Plan", string="Plano", context="tab")
    target = tmp_path / "es" / "LC_MESSAGES"
    target.mkdir(parents=True)
    with open(target / f"{i18n.DOMAIN}.mo", "wb") as fh:
        write_mo(fh, cat)
    i18n.set_locale_dir(tmp_path)
    set_language(LANG_ES)
    assert tn("{n} clip", "{n} clips", 1) == "1 clip (uno)"
    assert tn("{n} clip", "{n} clips", 3) == "3 clips (varios)"
    assert tc("tab", "Plan") == "Plano"
    assert tc("verb", "Plan") == "Plan"


def test_extract_placeholders():
    assert extract_placeholders("{a} and {b_2} but not {} or { x }") == {"a", "b_2"}


def test_get_system_language_detects_es(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert get_system_language() == LANG_ES

    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert get_system_language() == LANG_EN


def test_old_dictionary_is_gone():
    assert not hasattr(i18n, "TRANSLATIONS_ES")


# --------------------------------------------------------------------------------------------------------------------
# The shipped Spanish catalog
# --------------------------------------------------------------------------------------------------------------------


def test_spanish_catalog_is_not_empty_and_every_entry_is_translated():
    cat = tool.read_catalog("es")
    entries = [m for m in cat if m.id]
    assert len(entries) > 100
    for m in entries:
        assert tool._is_translated(m), f"{m.id!r} has no translation"


def test_every_message_in_the_code_is_in_the_catalog_and_translated():
    cat = tool.read_catalog("es")
    po = tool._po_keys(cat)
    baseline = tool.load_baseline()
    for key in (tool._key(m) for m in tool.build_pot_catalog() if m.id):
        assert key in po, f"{key[1]!r} is in the code but not in the .po (run tools/i18n.py update)"
        if key[1] not in baseline["untranslated"]:
            assert tool._is_translated(po[key]), f"{key[1]!r} is not translated"


def test_placeholders_match_across_all_translations():
    """Every translated string keeps exactly the placeholders of the English text."""
    problems = [p for p in tool.catalog_problems("es") if "placeholders" in p]
    assert not problems, "\n".join(problems)


def test_catalog_hygiene_has_no_problems():
    """Placeholders, accelerators, ellipsis, final punctuation, spaces, glossary, ratchets and the compiled .mo."""
    problems = tool.catalog_problems("es")
    assert not problems, "\n".join(problems)


def test_pot_is_up_to_date():
    problems = tool.pot_problems()
    assert not problems, "\n".join(problems)


def test_compiled_mo_matches_po():
    problems = tool.mo_problems("es")
    assert not problems, "\n".join(problems)


def test_plural_forms_header_is_two_forms_for_spanish():
    cat = tool.read_catalog("es")
    assert cat.num_plurals == 2
    assert cat.plural_expr == "(n != 1)"


def test_mo_has_the_gettext_magic_number():
    data = (ROOT / "locale" / "es" / "LC_MESSAGES" / f"{i18n.DOMAIN}.mo").read_bytes()
    assert struct.unpack("<I", data[:4])[0] == 0x950412DE


def test_glossary_is_readable_and_has_terms():
    terms, keep = tool.load_glossary()
    words = dict(terms)
    assert words["queue"] == ["cola"]
    assert "VOD" in keep and "yt-dlp" in keep


# --------------------------------------------------------------------------------------------------------------------
# The guard rails really bite (synthetic messages)
# --------------------------------------------------------------------------------------------------------------------


def _problems(msgid, msgstr, **extra):
    from babel.messages.catalog import Message

    m = Message(msgid, msgstr, **extra)
    base = {"identical_ok": [], "glossary_exempt": []}
    terms, keep = tool.load_glossary()
    return tool.message_problems("es", m, base) + tool.glossary_problems("es", m, base, terms, keep)


def test_guard_placeholder_mismatch():
    assert any("placeholders" in p for p in _problems("Hello {user}", "Hola {usuario}"))
    assert any("placeholders" in p for p in _problems("Hello {user}", "Hola"))
    assert not _problems("Hello {user}", "Hola {user}")


def test_guard_accelerator_ellipsis_punctuation_spaces():
    assert any("accelerator" in p for p in _problems("&Open", "Abrir"))
    assert not any("accelerator" in p for p in _problems("&Open", "&Abrir"))
    assert not any("accelerator" in p for p in _problems("Queue & log", "Cola y registros"))  # conjunction, not an accelerator
    assert any("ellipsis" in p for p in _problems("Save log…", "Guardar registro..."))
    assert any("ellipsis" in p for p in _problems("Save log…", "Guardar registro"))
    assert any("punctuation" in p for p in _problems("Nothing queued.", "Nada en cola"))
    assert any("punctuation" in p for p in _problems("Hello:", "Hola"))
    assert not any("punctuation" in p for p in _problems("Really?", "¿De verdad?"))
    assert any("spaces" in p for p in _problems("Hello ", "Hola"))
    assert any("line breaks" in p for p in _problems("a\nb", "a b"))


def test_guard_identical_text_needs_an_allow_list_entry():
    assert any("equals the English" in p for p in _problems("Cancel", "Cancel"))
    from babel.messages.catalog import Message

    ok = tool.message_problems("es", Message("Plan", "Plan"), {"identical_ok": ["Plan"], "glossary_exempt": []})
    assert not ok


def test_guard_glossary_and_keep_as_is():
    assert any("glossary" in p for p in _problems("Start queue", "Iniciar fila"))
    assert not any("glossary" in p for p in _problems("Start queue", "Iniciar cola"))
    assert any("must stay unchanged" in p for p in _problems("Open the VOD", "Abre el vídeo"))
    assert not _problems("Open the VOD", "Abre el VOD")


def test_guard_plural_entries_need_all_forms():
    from babel.messages.catalog import Message

    base = {"identical_ok": [], "glossary_exempt": []}
    one = Message(("{n} clip", "{n} clips"), ("{n} clip",))
    assert any("plural forms" in p for p in tool.message_problems("es", one, base))
    two = Message(("{n} clip", "{n} clips"), ("un clip", "{n} clips"))
    assert not tool.message_problems("es", two, base)  # the singular form may drop {n}
    bad = Message(("{n} clip", "{n} clips"), ("un clip", "clips"))
    assert any("placeholders" in p for p in tool.message_problems("es", bad, base))


def test_merge_adds_missing_messages_and_never_deletes():
    from babel.messages.catalog import Catalog

    pot = Catalog()
    pot.add("Brand new text", string="", locations=[("qt_ui/x.py", 0)])
    pot.add(("{n} thing", "{n} things"), string=("", ""), locations=[("qt_ui/x.py", 0)])
    cat, added, missing = tool.merge_into("es", pot)
    assert added == ["Brand new text", "{n} thing"]
    assert cat.get("Brand new text").string == ""
    assert len(cat.get(("{n} thing", "{n} things")).string) == 2
    assert cat.get("Search").string == "Buscar"  # existing translations survive
    assert "Search" in missing  # not in this tiny template: reported, but never removed


# --------------------------------------------------------------------------------------------------------------------
# Coverage ratchet: wrapped messages and unwrapped literals
# --------------------------------------------------------------------------------------------------------------------


def test_scanner_finds_unwrapped_ui_text_and_ignores_wrapped_and_technical_strings():
    src = (
        "from core.i18n import t\n"
        "def build(self, n):\n"
        "    QPushButton('Save all')\n"            # gap
        "    QPushButton(t('Save all'))\n"         # wrapped
        "    self.label.setText(f'Added {n} clips')\n"  # gap (f-string)
        "    self.label.setToolTip('queued')\n"    # single lowercase word: a key, not prose
        "    self.setObjectName('SearchTab')\n"    # not a sink
        "    self.setStyleSheet('color: red; font-weight: bold')\n"  # not a sink
        "    some_helper('Loading VODs…')\n"       # not a known sink name: ignored on purpose
    )
    found = tool.scan_source(src, "qt_ui/example.py")
    assert found == {"Added {} clips": 1, "Save all": 1}


def test_scanner_finds_engine_errors_and_ctx_log():
    src = (
        "def go(ctx):\n"
        "    ctx.log('Chapters: skipping.')\n"
        "    raise PlanError('Write the cut points first.')\n"
        "    raise PlanError(t('Already wrapped.'))\n"
        "    other.log('not the job log')\n"
    )
    found = tool.scan_source(src, "core/example.py")
    assert found == {"Chapters: skipping.": 1, "Write the cut points first.": 1}


def test_unwrapped_literals_ratchet_has_no_new_gaps():
    """A new user-facing literal without t() fails here. Wrap it in t() (or N_() if it is translated later)."""
    problems = tool.unwrapped_problems()
    assert not problems, "\n".join(problems[:25])


def test_ratchet_detects_a_new_gap(monkeypatch):
    now = tool.scan_unwrapped()
    first_file = next(iter(now)) if now else "core/chat.py"
    current_entries = now.get(first_file, {})
    fake = {**now, first_file: {**current_entries, "A brand new English sentence": 1}}
    monkeypatch.setattr(tool, "scan_unwrapped", lambda: fake)
    problems = tool.unwrapped_problems()
    assert any("A brand new English sentence" in p for p in problems)


def test_ratchet_demands_shrinking_when_a_gap_is_fixed(monkeypatch):
    now = tool.scan_unwrapped()
    if not now:
        real_load = tool.load_baseline
        monkeypatch.setattr(tool, "load_baseline", lambda: {**real_load(), "unwrapped": {"core/chat.py": {"Old fixed string": 1}}})
        problems = tool.unwrapped_problems()
        assert any("tools/i18n.py baseline" in p for p in problems)
        return
    first_file = next(iter(now))
    text = next(iter(now[first_file]))
    shrunk = {**now, first_file: {k: v for k, v in now[first_file].items() if k != text}}
    monkeypatch.setattr(tool, "scan_unwrapped", lambda: shrunk)
    problems = tool.unwrapped_problems()
    assert any("tools/i18n.py baseline" in p for p in problems)


def test_baseline_refuses_to_grow(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(tool, "BASELINE_PATH", tmp_path / "baseline.json")
    tool.BASELINE_PATH.write_text('{"identical_ok": [], "unwrapped": {}, "dead": [], "untranslated": []}', encoding="utf-8")
    monkeypatch.setattr(tool, "scan_unwrapped", lambda: {"core/chat.py": {"Some new gap": 1}})
    assert tool.cmd_baseline(allow_growth=False) == 1  # the gaps are not in this empty baseline
    assert "may only shrink" in capsys.readouterr().out
    assert tool.cmd_baseline(allow_growth=True) == 0


def test_dead_entries_are_known_and_not_growing():
    baseline = tool.load_baseline()
    cat = tool.read_catalog("es")
    pot_keys = {tool._key(m) for m in tool.build_pot_catalog() if m.id}
    dead = {k[1] for k in set(tool._po_keys(cat)) - pot_keys}
    assert dead <= set(baseline["dead"]), sorted(dead - set(baseline["dead"]))


def test_variable_reached_messages_are_kept_in_the_pot():
    """Tab names and option titles reach t() through variables; they must still be in the template."""
    pot = {m.id for m in tool.build_pot_catalog() if m.id}
    for text in ("Search", "Queue & log", "Output", "Past broadcasts", "Check now"):
        assert text in pot, text


def test_pseudo_localization():
    set_language(i18n.LANG_PSEUDO)
    assert get_language() == i18n.LANG_PSEUDO
    res = t("Download VOD")
    assert res.startswith("[") and res.endswith("]")
    # Ensure placeholders format cleanly in pseudo mode
    formatted = t("Downloading {tag}", tag="v1.0")
    assert "v1.0" in formatted
    # Plural form
    plural_res = tn("{n} file", "{n} files", 3)
    assert "3" in plural_res
    set_language(i18n.LANG_EN)
