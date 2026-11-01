import re
import stat

import pytest

from usta import settings, theme

ANSI = re.compile(r"\x1b\[[0-9;]*m")
DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,3 +1,3 @@
 ayni
-eski
+yeni
 son
"""


def test_exactly_three_themes_with_turkish_names_and_all_roles():
    assert set(theme.THEMES) == {"beyaz", "gri", "siyah"}
    for name, palette in theme.THEMES.items():
        assert set(palette) >= set(theme.ROLES), name


def test_aliases_resolve():
    assert theme.resolve("white") == "beyaz" and theme.resolve("GRAY") == "gri"
    assert theme.resolve("Siyah") == "siyah" and theme.resolve("dark") == "siyah"
    with pytest.raises(ValueError):
        theme.resolve("pembe")


def test_plain_painter_never_emits_escape_codes():
    p = theme.Painter("siyah", color=False)
    assert p("add", "x") == "x" and p.diff(DIFF) == DIFF


@pytest.mark.parametrize("name", sorted(theme.THEMES))
def test_colored_painter_wraps_and_resets_and_strips_back(name):
    p = theme.Painter(name, color=True)
    out = p("error", "hata")
    assert out.startswith("\x1b[") and out.endswith("\x1b[0m") and ANSI.sub("", out) == "hata"
    assert ANSI.sub("", p.diff(DIFF)) == DIFF


def test_diff_lines_get_distinct_roles():
    p = theme.Painter("siyah", color=True)
    code = lambda ln: re.match(r"\x1b\[([0-9;]*)m", ln).group(1)
    lines = {ANSI.sub("", ln): ln for ln in p.diff(DIFF).splitlines()}
    add, rem, ctx = code(lines["+yeni"]), code(lines["-eski"]), code(lines[" ayni"])
    hunk, meta = code(lines["@@ -1,3 +1,3 @@"]), code(lines["--- a/a.py"])
    assert len({add, rem, hunk, meta, ctx}) == 5
    # üst bilgi satırları (+++/---) ekleme/silme gibi değil, meta olarak boyanır
    assert code(lines["+++ b/a.py"]) == meta and code(lines["diff --git a/a.py b/a.py"]) == meta


def test_themes_differ_from_each_other():
    outs = {n: theme.Painter(n, color=True)("add", "x") for n in theme.THEMES}
    assert len(set(outs.values())) == 3


def test_auto_respects_no_color_and_non_tty(monkeypatch):
    class Tty:
        def isatty(self):
            return True

    class NotTty:
        def isatty(self):
            return False

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert theme.Painter.auto("siyah", Tty()).color is True
    assert theme.Painter.auto("siyah", NotTty()).color is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert theme.Painter.auto("siyah", Tty()).color is False


def test_diff_summary_counts_files_and_lines():
    two = DIFF + "diff --git a/b.py b/b.py\n--- /dev/null\n+++ b/b.py\n@@ -0,0 +1,2 @@\n+x\n+y\n"
    s = theme.diff_summary(two)
    assert s == {"files": 2, "added": 3, "removed": 1}
    assert theme.diff_summary("") == {"files": 0, "added": 0, "removed": 0}


# --- ayarlar ------------------------------------------------------------------------------
def test_settings_defaults_and_roundtrip(tmp_path):
    s = settings.load(tmp_path)
    assert s.theme == "siyah" and s.mode == "manual" and s.portal is True and s.model is None
    settings.save(
        tmp_path,
        settings.Settings(
            theme="gri", mode="plan", model="m", endpoint="http://x/v1", portal=False
        ),
    )
    got = settings.load(tmp_path)
    assert (got.theme, got.mode, got.model, got.portal) == ("gri", "plan", "m", False)
    assert stat.S_IMODE((tmp_path / "config.json").stat().st_mode) == 0o600


def test_settings_validation_rejects_bad_values():
    with pytest.raises(ValueError):
        settings.Settings(theme="pembe")
    with pytest.raises(ValueError):
        settings.Settings(mode="tehlikeli")
    with pytest.raises(ValueError):
        settings.Settings(endpoint="ftp://x")
    with pytest.raises(ValueError):
        settings.Settings(context_window=-5)


def test_corrupt_or_hostile_config_falls_back_to_defaults(tmp_path):
    for text in ("{bozuk", "[]", '{"theme": "pembe", "mode": 5}', '{"endpoint": "file:///etc"}'):
        (tmp_path / "config.json").write_text(text)
        s = settings.load(tmp_path)
        assert s.theme == "siyah" and s.mode == "manual" and s.endpoint is None


def test_settings_never_store_secrets(tmp_path):
    settings.save(tmp_path, settings.Settings(model="m"))
    text = (tmp_path / "config.json").read_text()
    assert "key" not in text.lower() and "token" not in text.lower()


def test_unknown_keys_are_dropped_on_save(tmp_path):
    (tmp_path / "config.json").write_text('{"theme": "gri", "api_key": "sir-deger", "x": 1}')
    s = settings.load(tmp_path)
    settings.save(tmp_path, s)
    assert "sir-deger" not in (tmp_path / "config.json").read_text()


def test_settings_guard_default_false_and_roundtrip(tmp_path):
    assert settings.load(tmp_path).guard is False
    settings.save(tmp_path, settings.Settings(guard=True))
    assert settings.load(tmp_path).guard is True
    with pytest.raises(TypeError):
        settings.Settings(guard="evet")
