import sys

import pytest

from usta import cli
from usta import settings as st


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    home = tmp_path.parent / f"{tmp_path.name}-ustahome"  # çalışma klasörünün DIŞINDA (check_root)
    monkeypatch.setenv("USTA_HOME", str(home))
    for k in ("USTA_ENDPOINT", "USTA_MODEL", "USTA_API_KEY", "USTA_PROTOCOL", "USTA_ALLOW_HOSTS"):
        monkeypatch.delenv(k, raising=False)
    return home


class Probe:
    """Repl.run ve Portal'ı taklit eder; yapılandırmanın doğru aktarıldığını kaydeder."""

    def __init__(self, monkeypatch):
        self.repl_kwargs, self.portal_started, self.portal_stopped, self.opened = {}, 0, 0, []
        probe = self

        class FakeRepl:
            def __init__(self, manager, root, wid, home, settings, **kw):
                probe.repl_kwargs = {"root": root, "wid": wid, "settings": settings, **kw}
                probe.manager = manager

            def run(self):
                return 0

        class FakePortal:
            def __init__(
                self, manager, home, token, preferred_port=8765, workspace=None, lan=False
            ):
                probe.portal_workspace = workspace
                probe.portal_port = preferred_port
                probe.portal_lan = lan
                self.url = "http://127.0.0.1:9999/"

            def start(self):
                probe.portal_started += 1
                return self.url

            def pairing(self):
                return (["http://192.168.1.5:9999/"], "123456") if probe.portal_lan else None

            def login_url(self):
                return self.url + "?code=abc"

            def login_page(self):
                return "file:///tmp/usta-login-test.html"

            def stop(self):
                probe.portal_stopped += 1

        from usta.profile import Profile

        # testler gerçek model uç noktasına sonda göndermesin
        monkeypatch.setattr(
            cli.profile,
            "resolve_protocol",
            lambda *a, **k: Profile("m", "native", 3, 3, 0, 3, "test", 1.0),
        )
        monkeypatch.setattr(cli, "Repl", FakeRepl)
        monkeypatch.setattr(cli, "Portal", FakePortal)
        monkeypatch.setattr(cli, "cleanup_orphans", lambda: 0)
        monkeypatch.setattr(cli.webbrowser, "open", lambda url: probe.opened.append(url) or True)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)


def test_bare_usta_starts_repl_portal_and_opens_browser(tmp_path, monkeypatch):
    p = Probe(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--model", "m1"]) == 0
    assert p.portal_started == 1 and p.portal_stopped == 1
    assert p.opened == ["file:///tmp/usta-login-test.html"]  # kod komut satırında görünmez
    assert (
        p.repl_kwargs["model_name"] == "m1"
        and p.repl_kwargs["portal_url"] == "http://127.0.0.1:9999/"
    )
    assert p.repl_kwargs["root"] == tmp_path.resolve()


def test_no_portal_flag_and_setting(tmp_path, monkeypatch, env):
    p = Probe(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--model", "m", "--no-portal"]) == 0
    assert p.portal_started == 0 and p.opened == [] and p.repl_kwargs["portal_url"] is None
    st.save(env, st.Settings(portal=False))
    assert cli.main(["--model", "m"]) == 0 and p.portal_started == 0


def test_no_browser_flag_keeps_portal_but_does_not_open(tmp_path, monkeypatch):
    p = Probe(monkeypatch)
    monkeypatch.chdir(tmp_path)
    cli.main(["--model", "m", "--no-browser"])
    assert p.portal_started == 1 and p.opened == []


def test_browser_not_opened_when_not_interactive(tmp_path, monkeypatch):
    p = Probe(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.chdir(tmp_path)
    cli.main(["--model", "m"])
    assert p.opened == []


def test_workspace_is_registered_for_portal(tmp_path, monkeypatch, env):
    Probe(monkeypatch)
    proj = tmp_path / "benim-proje"
    proj.mkdir()
    monkeypatch.chdir(proj)
    cli.main(["--model", "m"])
    links = list((env / "workspaces").iterdir())
    assert len(links) == 1 and links[0].is_symlink() and links[0].resolve() == proj.resolve()


def test_settings_theme_mode_and_flag_overrides(tmp_path, monkeypatch, env):
    p = Probe(monkeypatch)
    st.save(env, st.Settings(theme="gri", mode="plan", model="kayitli", endpoint="http://e/v1"))
    monkeypatch.chdir(tmp_path)
    cli.main([])
    s = p.repl_kwargs["settings"]
    assert (s.theme, s.mode) == ("gri", "plan") and p.repl_kwargs["model_name"] == "kayitli"
    cli.main(["--theme", "beyaz", "--mode", "auto"])
    s = p.repl_kwargs["settings"]
    assert (s.theme, s.mode) == ("beyaz", "auto")


def test_first_run_wizard_lists_models_and_saves_choice(tmp_path, monkeypatch, env, capsys):
    p = Probe(monkeypatch)
    monkeypatch.setattr(cli, "_discover_models", lambda endpoint: ["a-model", "b-model"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    assert p.repl_kwargs["model_name"] == "b-model"
    assert st.load(env).model == "b-model"
    assert "a-model" in capsys.readouterr().out


def test_wizard_unreachable_endpoint_explains(tmp_path, monkeypatch, capsys):
    Probe(monkeypatch)
    monkeypatch.setattr(cli, "_discover_models", lambda endpoint: [])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--no-portal"]) == 2  # portal kapalıyken sihirbaz yok: terminalde açıklama
    err = capsys.readouterr().err
    assert "ulaşılamadı" in err and "--model" in err


def test_no_model_found_in_terminal_starts_setup_mode(tmp_path, monkeypatch, capsys):
    p = Probe(monkeypatch)
    monkeypatch.setattr(cli, "_discover_models", lambda endpoint: [])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    ctl = p.manager.model_control
    assert ctl is not None and not ctl.ready and p.repl_kwargs["model_name"] == ""
    assert "kurulum sihirbazını" in capsys.readouterr().out


def test_setup_flag_forces_setup_mode_even_without_terminal(tmp_path, monkeypatch):
    p = Probe(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--setup"]) == 0
    assert not p.manager.model_control.ready


def test_wizard_bad_choice_is_rejected(tmp_path, monkeypatch, env):
    Probe(monkeypatch)
    monkeypatch.setattr(cli, "_discover_models", lambda endpoint: ["a"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "7")
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 2
    assert st.load(env).model is None


def test_no_model_and_not_interactive_is_usage_error(tmp_path, monkeypatch, capsys):
    Probe(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 2 and "model" in capsys.readouterr().err


def test_subcommands_still_work_and_bare_help_lists_them(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for word in ("run", "serve", "mcp", "bench", "--no-portal"):
        assert word in out


# --- yetenek sondası ve protokol seçimi ----------------------------------------------------
def fake_profile(protocol="text", note="deneme"):
    from usta.profile import Profile

    return Profile("m", protocol, 0, 3, 0, 3, note, 1.0)


def test_chat_probes_model_when_protocol_not_given_and_uses_result(tmp_path, monkeypatch, capsys):
    p = Probe(monkeypatch)
    calls = []
    monkeypatch.setattr(
        cli.profile,
        "resolve_protocol",
        lambda *a, **k: calls.append(a) or fake_profile("text", "yerel çağrı güvenilmez"),
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--model", "m"]) == 0
    assert len(calls) == 1 and p.repl_kwargs["protocol"] == "text"
    assert "yerel çağrı güvenilmez" in capsys.readouterr().out


def test_explicit_protocol_skips_probe(tmp_path, monkeypatch):
    p = Probe(monkeypatch)
    monkeypatch.setattr(
        cli.profile, "resolve_protocol", lambda *a, **k: pytest.fail("sonda çalışmamalı")
    )
    monkeypatch.chdir(tmp_path)
    assert (
        cli.main(["--model", "m", "--protocol", "native"]) == 0
        and p.repl_kwargs["protocol"] == "native"
    )


def test_probe_failure_is_clear_error(tmp_path, monkeypatch, capsys):
    Probe(monkeypatch)

    def boom(*a, **k):
        raise cli.profile.ProfileError("model uç noktasına ulaşılamadı: ReadTimeout")

    monkeypatch.setattr(cli.profile, "resolve_protocol", boom)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--model", "m"]) == 2
    assert "ulaşılamadı" in capsys.readouterr().err


def test_probe_subcommand_prints_profile_and_refresh_ignores_cache(
    tmp_path, monkeypatch, capsys, env
):
    from usta import profile as prof

    monkeypatch.setattr(
        cli.profile, "probe", lambda client, model: fake_profile("text", "yeni sonuç")
    )
    prof.save(env, "http://localhost:11434/v1", "m", fake_profile("native", "eski önbellek"))
    assert cli.main(["probe", "--model", "m"]) == 0
    assert "eski önbellek" in capsys.readouterr().out
    assert cli.main(["probe", "--model", "m", "--refresh"]) == 0
    assert "yeni sonuç" in capsys.readouterr().out
    assert prof.load(env, "http://localhost:11434/v1", "m").note == "yeni sonuç"


def test_portal_receives_terminal_workspace_id(tmp_path, monkeypatch, env):
    p = Probe(monkeypatch)
    proj = tmp_path / "benim-proje"
    proj.mkdir()
    monkeypatch.chdir(proj)
    cli.main(["--model", "m"])
    link = next((env / "workspaces").iterdir())
    assert p.portal_workspace == link.name


def test_lan_flag_reaches_portal_and_prints_pairing_info(tmp_path, monkeypatch, capsys):
    p = Probe(monkeypatch)
    st.save(
        tmp_path.parent / f"{tmp_path.name}-ustahome",
        st.Settings(model="m", endpoint="http://e/v1"),
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--lan"]) == 0
    assert p.portal_lan is True
    out = capsys.readouterr().out
    assert "192.168.1.5" in out and "123456" in out
    cli.main([])
    assert p.portal_lan is False  # varsayılan: yerel ağa kapalı
