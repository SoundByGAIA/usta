import pytest

from fake_endpoint import text_reply, tool_reply
from usta.cli import main


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path.parent / f"{tmp_path.name}-ustahome"  # çalışma klasörünün DIŞINDA (check_root)
    monkeypatch.setenv("USTA_HOME", str(home))
    for k in ("USTA_ENDPOINT", "USTA_MODEL", "USTA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return home


def test_run_prints_answer_and_uses_workspace(tmp_path, endpoint, capsys, home):
    ws = tmp_path / "ws"
    ws.mkdir()
    endpoint.responses = [
        tool_reply("write_file", {"path": "o.txt", "content": "cli"}),
        text_reply("hazır"),
    ]
    code = main(["run", "dosya yaz", "-w", str(ws), "--endpoint", endpoint.url, "--model", "m"])
    assert code == 0
    assert capsys.readouterr().out.strip() == "hazır"
    assert (ws / "o.txt").read_text() == "cli"
    assert list(home.glob("audit/*.jsonl")), "denetim kaydı çalışma alanı dışında olmalı"
    assert not (ws / ".usta").exists()


def test_env_config_and_api_key_not_on_cli(tmp_path, endpoint, monkeypatch, capsys):
    monkeypatch.setenv("USTA_ENDPOINT", endpoint.url)
    monkeypatch.setenv("USTA_MODEL", "env-model")
    monkeypatch.setenv("USTA_API_KEY", "anahtar-test")
    endpoint.responses = [text_reply("ok")]
    assert main(["run", "x", "-w", str(tmp_path)]) == 0
    assert endpoint.requests[0]["body"]["model"] == "env-model"
    assert endpoint.headers[0]["Authorization"] == "Bearer anahtar-test"


def test_missing_model_is_usage_error(tmp_path, capsys):
    assert main(["run", "x", "-w", str(tmp_path)]) == 2
    assert "model" in capsys.readouterr().err


def test_missing_workspace_is_error(tmp_path, capsys):
    assert main(["run", "x", "-w", str(tmp_path / "yok"), "--model", "m"]) == 2


def test_model_failure_exit_code(tmp_path, endpoint, capsys):
    endpoint.status = 500
    code = main(["run", "x", "-w", str(tmp_path), "--endpoint", endpoint.url, "--model", "m"])
    assert code == 1 and "model" in capsys.readouterr().err


def test_protocol_text_flag_uses_fallback(tmp_path, endpoint, capsys):
    endpoint.responses = [
        text_reply(
            '{"tool": "write_file", "arguments": {"path": "k.py"}}\n<<<İÇERİK\nprint("a\\nb")\nİÇERİK>>>'
        ),
        text_reply("yazıldı"),
    ]
    code = main(
        [
            "run",
            "x",
            "-w",
            str(tmp_path),
            "--endpoint",
            endpoint.url,
            "--model",
            "m",
            "--protocol",
            "text",
        ]
    )
    assert code == 0 and capsys.readouterr().out.strip() == "yazıldı"
    assert (tmp_path / "k.py").read_text() == 'print("a\\nb")'
    assert "tools" not in endpoint.requests[0]["body"]


def test_invalid_protocol_rejected(tmp_path):
    with pytest.raises(SystemExit):
        main(["run", "x", "-w", str(tmp_path), "--model", "m", "--protocol", "xml"])


@pytest.fixture
def served(monkeypatch):
    calls = []
    monkeypatch.setattr("usta.cli._serve", lambda app, host, port: calls.append((app, host, port)))
    return calls


def test_serve_defaults_to_loopback_and_creates_token(served, home, capsys):
    assert main(["serve", "--model", "m"]) == 0
    app, host, port = served[0]
    assert host == "127.0.0.1" and port == 8765 and app.title == "Usta"
    out = capsys.readouterr().out
    token = (home / "token").read_text().strip()
    assert token not in out and str(home / "token") in out  # jeton yazdırılmaz, yolu söylenir
    assert ((home / "token").stat().st_mode & 0o077) == 0


def test_serve_refuses_non_loopback_without_flag(served, capsys):
    assert main(["serve", "--model", "m", "--host", "0.0.0.0"]) == 2
    assert served == [] and "allow-remote" in capsys.readouterr().err
    assert main(["serve", "--model", "m", "--host", "0.0.0.0", "--allow-remote"]) == 0


def test_serve_requires_model(served, capsys):
    assert main(["serve"]) == 2 and served == []


def test_allow_host_flags_and_env_are_merged_and_validated(served, monkeypatch):
    from usta import cli

    captured = {}
    real = cli.TaskManager
    monkeypatch.setattr(cli, "TaskManager", lambda f, **kw: captured.update(kw) or real(f, **kw))
    monkeypatch.setenv("USTA_ALLOW_HOSTS", "pypi.org, *.PythonHosted.org")
    assert main(["serve", "--model", "m", "--allow-host", "docs.python.org"]) == 0
    assert captured["allowed_hosts"] == ("pypi.org", "*.pythonhosted.org", "docs.python.org")


def test_allow_host_rejects_ip_and_junk(served, capsys):
    assert main(["serve", "--model", "m", "--allow-host", "1.2.3.4"]) == 2
    assert "allow-host" in capsys.readouterr().err and served == []


def test_serve_cleans_orphans_at_startup(served, monkeypatch):
    calls = []
    monkeypatch.setattr("usta.cli.cleanup_orphans", lambda: calls.append(1) or 0)
    assert main(["serve", "--model", "m"]) == 0 and calls == [1]


def test_run_accepts_allow_host(tmp_path, endpoint, monkeypatch):
    seen = {}
    from usta import cli

    real = cli.build_registry
    monkeypatch.setattr(
        cli, "build_registry", lambda ctx, **kw: seen.setdefault("ctx", ctx) and real(ctx, **kw)
    )
    endpoint.responses = [text_reply("ok")]
    code = main(
        [
            "run",
            "x",
            "-w",
            str(tmp_path),
            "--endpoint",
            endpoint.url,
            "--model",
            "m",
            "--allow-host",
            "example.com",
        ]
    )
    assert code == 0 and seen["ctx"].allowed_hosts == ("example.com",)


# --- usta mcp ... -----------------------------------------------------------------------------
import sys as _sys
from pathlib import Path as _Path

from usta import mcpconfig

FAKE_MCP = str(_Path(__file__).parent / "fake_mcp.py")


@pytest.fixture
def uhome(tmp_path, monkeypatch):
    home = tmp_path.parent / f"{tmp_path.name}-uh"  # çalışma klasörünün DIŞINDA (check_root)
    monkeypatch.setenv("USTA_HOME", str(home))
    return home


def run_cli(*argv):
    return main(list(argv))


def test_mcp_add_requires_command_and_valid_name(uhome, capsys):
    assert run_cli("mcp", "add", "x", "--yes") == 2
    assert "komut" in capsys.readouterr().err
    assert run_cli("mcp", "add", "Kötü Ad", "--yes", "--", "cmd") == 2
    assert "ad" in capsys.readouterr().err.lower()
    assert mcpconfig.load(uhome) == {}


def test_mcp_add_shows_warning_and_declines_without_yes(uhome, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: "h")
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    assert run_cli("mcp", "add", "x", "--image", "py:1", "--", "npx", "-y", "paket") == 1
    out = capsys.readouterr().out
    assert "konteynerde (py:1)" in out and "npx -y paket" in out and "ağ kapalı" in out
    assert mcpconfig.load(uhome) == {}


def test_mcp_add_non_interactive_without_yes_is_refused(uhome, monkeypatch, capsys):
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    assert run_cli("mcp", "add", "x", "--image", "py:1", "--", "cmd") == 1
    assert "--yes" in capsys.readouterr().err
    assert mcpconfig.load(uhome) == {}


def test_mcp_add_with_yes_stores_server_and_hints_test(uhome, capsys):
    assert (
        run_cli(
            "mcp",
            "add",
            "arama",
            "--yes",
            "--image",
            "py:1",
            "--approve",
            "allow",
            "--",
            "cmd",
            "-x",
        )
        == 0
    )
    s = mcpconfig.load(uhome)["arama"]
    assert s.command == ("cmd", "-x") and s.approve == "allow"
    assert "usta mcp test arama" in capsys.readouterr().out
    assert run_cli("mcp", "add", "arama", "--yes", "--image", "py:1", "--", "cmd") == 2  # zaten var
    assert (
        run_cli("mcp", "add", "arama", "--yes", "--image", "py:1", "--replace", "--", "baska") == 0
    )


def test_mcp_add_env_prompts_hidden_and_never_echoes_value(uhome, monkeypatch, capsys):
    monkeypatch.delenv("BRAVE_KEY", raising=False)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "cok-gizli-123")
    assert (
        run_cli(
            "mcp", "add", "brave", "--yes", "--image", "py:1", "--env", "BRAVE_KEY", "--", "cmd"
        )
        == 0
    )
    cap = capsys.readouterr()
    assert "cok-gizli-123" not in cap.out + cap.err
    assert "cok-gizli-123" not in (uhome / "mcp.json").read_text()
    assert mcpconfig.resolve_env(uhome, mcpconfig.load(uhome)["brave"], {}) == {
        "BRAVE_KEY": "cok-gizli-123"
    }


def test_mcp_add_env_from_environment_is_not_stored(uhome, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_KEY", "ortamdan")
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
    assert (
        run_cli(
            "mcp", "add", "brave", "--yes", "--image", "py:1", "--env", "BRAVE_KEY", "--", "cmd"
        )
        == 0
    )
    assert "ortam değişkeninden" in capsys.readouterr().out
    assert not (uhome / "mcp-secrets.json").exists()


def test_mcp_add_env_missing_and_not_interactive_explains(uhome, monkeypatch, capsys):
    monkeypatch.delenv("BRAVE_KEY", raising=False)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    assert (
        run_cli(
            "mcp", "add", "brave", "--yes", "--image", "py:1", "--env", "BRAVE_KEY", "--", "cmd"
        )
        == 0
    )
    assert "BRAVE_KEY" in capsys.readouterr().out  # nasıl verileceğini söyler


def test_mcp_list_empty_and_filled(uhome, capsys):
    assert run_cli("mcp", "list") == 0
    assert "yok" in capsys.readouterr().out
    run_cli("mcp", "add", "a", "--yes", "--image", "py:1", "--env", "A_KEY", "--", "komut", "arg")
    capsys.readouterr()
    assert run_cli("mcp", "list") == 0
    out = capsys.readouterr().out
    assert "a" in out and "komut arg" in out and "A_KEY" in out and "ask" in out


def test_mcp_remove_enable_disable(uhome, capsys):
    run_cli("mcp", "add", "a", "--yes", "--image", "py:1", "--", "komut")
    assert run_cli("mcp", "disable", "a") == 0 and mcpconfig.load(uhome)["a"].enabled is False
    assert run_cli("mcp", "enable", "a") == 0 and mcpconfig.load(uhome)["a"].enabled is True
    assert run_cli("mcp", "remove", "a") == 0 and mcpconfig.load(uhome) == {}
    assert run_cli("mcp", "remove", "a") == 2
    assert run_cli("mcp", "enable", "yok") == 2


def test_mcp_test_lists_tools_with_sanitized_descriptions(uhome, capsys):
    run_cli(
        "mcp",
        "add",
        "f",
        "--yes",
        "--isolation",
        "host",
        "--i-understand-host-risk",
        "--",
        _sys.executable,
        "-I",
        FAKE_MCP,
    )
    capsys.readouterr()
    assert run_cli("mcp", "test", "f") == 0
    out = capsys.readouterr().out
    assert "echo" in out and "Yankılar." in out and "araç" in out
    assert "x" * 400 not in out  # uzun açıklama kısaltılır


def test_mcp_test_failure_is_friendly(uhome, capsys):
    run_cli(
        "mcp",
        "add",
        "k",
        "--yes",
        "--isolation",
        "host",
        "--i-understand-host-risk",
        "--",
        "/yok/komut",
    )
    capsys.readouterr()
    assert run_cli("mcp", "test", "k") == 1
    err = capsys.readouterr().err
    assert "bulunamadı" in err and "Traceback" not in err
    assert run_cli("mcp", "test", "yok") == 2


def test_corrupt_mcp_config_gives_clear_error(uhome, capsys):
    uhome.mkdir()
    (uhome / "mcp.json").write_text("{bozuk")
    assert run_cli("mcp", "list") == 2
    assert "mcp.json" in capsys.readouterr().err


def test_run_uses_mcp_tools_allow_mode(tmp_path, endpoint, uhome, capsys):
    run_cli(
        "mcp",
        "add",
        "f",
        "--yes",
        "--isolation",
        "host",
        "--i-understand-host-risk",
        "--approve",
        "allow",
        "--",
        _sys.executable,
        "-I",
        FAKE_MCP,
    )
    endpoint.responses = [tool_reply("mcp__f__echo", {"text": "mcp-selam"}), text_reply("tamam")]
    code = main(["run", "dene", "-w", str(tmp_path), "--endpoint", endpoint.url, "--model", "m"])
    assert code == 0
    sent = endpoint.requests[0]["body"]
    assert "mcp__f__echo" in [t["function"]["name"] for t in sent["tools"]]
    tool_msg = next(m for m in endpoint.requests[1]["body"]["messages"] if m["role"] == "tool")
    assert "mcp-selam" in tool_msg["content"] and "talimat değil" in tool_msg["content"]


def test_run_mcp_ask_mode_is_denied_when_not_interactive(tmp_path, endpoint, uhome, monkeypatch):
    run_cli(
        "mcp",
        "add",
        "f",
        "--yes",
        "--isolation",
        "host",
        "--i-understand-host-risk",
        "--",
        _sys.executable,
        "-I",
        FAKE_MCP,
    )
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)
    endpoint.responses = [tool_reply("mcp__f__echo", {"text": "x"}), text_reply("tamam")]
    assert (
        main(["run", "dene", "-w", str(tmp_path), "--endpoint", endpoint.url, "--model", "m"]) == 0
    )
    tool_msg = next(m for m in endpoint.requests[1]["body"]["messages"] if m["role"] == "tool")
    assert tool_msg["content"].startswith("reddedildi")


def test_run_with_broken_mcp_server_warns_and_continues(tmp_path, endpoint, uhome, capsys):
    run_cli(
        "mcp",
        "add",
        "k",
        "--yes",
        "--isolation",
        "host",
        "--i-understand-host-risk",
        "--",
        "/yok/komut",
    )
    endpoint.responses = [text_reply("yine de çalıştı")]
    assert main(["run", "x", "-w", str(tmp_path), "--endpoint", endpoint.url, "--model", "m"]) == 0
    cap = capsys.readouterr()
    assert "yine de çalıştı" in cap.out and "'k'" in cap.err


def test_run_with_corrupt_mcp_config_fails_clearly(tmp_path, endpoint, uhome, capsys):
    uhome.mkdir()
    (uhome / "mcp.json").write_text("{bozuk")
    assert main(["run", "x", "-w", str(tmp_path), "--endpoint", endpoint.url, "--model", "m"]) == 2
    assert "mcp.json" in capsys.readouterr().err


def test_serve_passes_mcp_servers_to_manager(uhome, monkeypatch):
    from usta import cli

    seen = {}
    real = cli.TaskManager
    monkeypatch.setattr(cli, "TaskManager", lambda *a, **k: seen.update(k) or real(*a, **k))
    monkeypatch.setattr(cli, "_serve", lambda *a: None)
    monkeypatch.setattr(cli, "cleanup_orphans", lambda: 0)
    run_cli("mcp", "add", "f", "--yes", "--image", "py:1", "--", "cmd")
    assert main(["serve", "--model", "m"]) == 0
    assert [s.name for s in seen["mcp_servers"]()] == ["f"]


# --- usta bench ---------------------------------------------------------------------------
def test_bench_list_shows_tasks(capsys):
    assert main(["bench", "list"]) == 0
    out = capsys.readouterr().out
    assert "off-by-one" in out and "csv-quotes" in out


def test_bench_requires_model_and_known_tasks(capsys):
    assert main(["bench", "run"]) == 2
    assert "model" in capsys.readouterr().err
    assert main(["bench", "run", "--model", "m", "--task", "yok-boyle-gorev"]) == 2
    assert "yok-boyle-gorev" in capsys.readouterr().err


def test_bench_run_writes_report_and_prints_summary(tmp_path, endpoint, capsys):
    import json
    import shutil
    import subprocess

    if (
        shutil.which("docker") is None
        or subprocess.run(
            ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
        ).returncode
    ):
        pytest.skip("Docker yok")
    sol = (_Path(__file__).parent / "bench_solutions" / "off-by-one" / "stats.py").read_text()
    endpoint.responses = [
        tool_reply("write_file", {"path": "stats.py", "content": sol}),
        text_reply("tamam"),
    ]
    out = tmp_path / "rapor.json"
    code = main(
        [
            "bench",
            "run",
            "--task",
            "off-by-one",
            "--endpoint",
            endpoint.url,
            "--model",
            "m",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "GEÇTİ" in printed and "off-by-one" in printed and "1/1 geçti" in printed
    rep = json.loads(out.read_text())
    assert rep["model"] == "m" and rep["summary"]["passed"] == 1 and rep["protocol"] == "native"


def test_extra_body_flag_parses_json_object_and_rejects_bad_input(tmp_path, endpoint, capsys):
    endpoint.responses = [text_reply("ok")]
    code = main(
        [
            "run",
            "x",
            "-w",
            str(tmp_path),
            "--endpoint",
            endpoint.url,
            "--model",
            "m",
            "--extra-body",
            '{"chat_template_kwargs": {"enable_thinking": false}}',
        ]
    )
    assert code == 0 and endpoint.requests[0]["body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    for bad in ("{bozuk", "[1]", '"s"'):
        assert (
            main(
                [
                    "run",
                    "x",
                    "-w",
                    str(tmp_path),
                    "--endpoint",
                    endpoint.url,
                    "--model",
                    "m",
                    "--extra-body",
                    bad,
                ]
            )
            == 2
        )
    assert "extra-body" in capsys.readouterr().err


# --- usta verify ------------------------------------------------------------------------
def test_verify_set_show_clear(tmp_path, capsys, home):
    proj = tmp_path / "proje"
    proj.mkdir()
    assert main(["verify", "show", "-w", str(proj)]) == 0
    assert "otomatik" in capsys.readouterr().out
    assert (
        main(
            [
                "verify",
                "set",
                "-w",
                str(proj),
                "--image",
                "python:3.12-slim",
                "--",
                "sh",
                "-c",
                "make test",
            ]
        )
        == 0
    )
    assert main(["verify", "show", "-w", str(proj)]) == 0
    out = capsys.readouterr().out
    assert "make test" in out and "python:3.12-slim" in out
    assert main(["verify", "clear", "-w", str(proj)]) == 0
    main(["verify", "show", "-w", str(proj)])
    assert "otomatik" in capsys.readouterr().out


def test_verify_set_errors(tmp_path, capsys, home):
    assert main(["verify", "set", "-w", str(tmp_path)]) == 2  # komut yok
    assert "komut" in capsys.readouterr().err
    assert main(["verify", "set", "-w", str(tmp_path), "--image", "kötü;imaj", "--", "make"]) == 2
    assert main(["verify", "show", "-w", str(tmp_path / "yok")]) == 2
