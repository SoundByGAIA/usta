import json
import stat

import pytest

from usta import mcpconfig as cfg


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def test_empty_when_missing(tmp_path):
    assert cfg.load(tmp_path) == {}


def test_add_list_remove_roundtrip_with_private_perms(tmp_path):
    cfg.add_server(tmp_path, "brave", ["npx", "-y", "paket"], env=["BRAVE_API_KEY"], approve="ask")
    s = cfg.load(tmp_path)["brave"]
    assert s == cfg.Server("brave", ("npx", "-y", "paket"), ("BRAVE_API_KEY",), "ask", True)
    assert mode(tmp_path / "mcp.json") == 0o600
    cfg.remove_server(tmp_path, "brave")
    assert cfg.load(tmp_path) == {}
    with pytest.raises(cfg.McpConfigError, match="yok"):
        cfg.remove_server(tmp_path, "brave")


def test_secret_values_never_in_config_file(tmp_path):
    cfg.add_server(tmp_path, "x", ["cmd"], env=["API_KEY"])
    cfg.set_secret(tmp_path, "x", "API_KEY", "çok-gizli-değer-123")
    assert "çok-gizli-değer-123" not in (tmp_path / "mcp.json").read_text()
    assert mode(tmp_path / "mcp-secrets.json") == 0o600
    assert cfg.resolve_env(tmp_path, cfg.load(tmp_path)["x"], {}) == {
        "API_KEY": "çok-gizli-değer-123"
    }


def test_resolve_env_falls_back_to_process_env_and_skips_missing(tmp_path):
    cfg.add_server(tmp_path, "x", ["cmd"], env=["A_KEY", "B_KEY"])
    env = cfg.resolve_env(tmp_path, cfg.load(tmp_path)["x"], {"A_KEY": "a", "BASKA": "z"})
    assert env == {"A_KEY": "a"}  # tanımsız B_KEY verilmez, ilgisiz değişken sızmaz


def test_remove_server_also_removes_its_secrets(tmp_path):
    cfg.add_server(tmp_path, "x", ["cmd"], env=["K"])
    cfg.set_secret(tmp_path, "x", "K", "değer")
    cfg.remove_server(tmp_path, "x")
    assert "değer" not in (tmp_path / "mcp-secrets.json").read_text()


@pytest.mark.parametrize("name", ["", "A", "a b", "a/b", "../x", "a__b", "-x", "x" * 31, "çay"])
def test_bad_server_names(tmp_path, name):
    with pytest.raises(cfg.McpConfigError):
        cfg.add_server(tmp_path, name, ["cmd"])


@pytest.mark.parametrize(
    "kw",
    [
        {"command": []},
        {"command": [""]},
        {"command": ["a", 5]},
        {"command": ["a"], "env": ["küçük"]},
        {"command": ["a"], "env": ["LD_PRELOAD"]},
        {"command": ["a"], "env": ["DYLD_INSERT_LIBRARIES"]},
        {"command": ["a"], "env": ["A", "A"]},
        {"command": ["a"], "approve": "belki"},
        {"command": ["a\x00b"]},
    ],
)
def test_bad_definitions_rejected(tmp_path, kw):
    with pytest.raises(cfg.McpConfigError):
        cfg.add_server(tmp_path, "ok", **kw)


def test_duplicate_name_rejected_unless_replace(tmp_path):
    cfg.add_server(tmp_path, "x", ["a"])
    with pytest.raises(cfg.McpConfigError, match="zaten"):
        cfg.add_server(tmp_path, "x", ["b"])
    cfg.add_server(tmp_path, "x", ["b"], replace=True)
    assert cfg.load(tmp_path)["x"].command == ("b",)


def test_corrupt_or_malicious_file_is_an_error_not_a_crash(tmp_path):
    for text in (
        "{bozuk",
        "[]",
        '{"servers": []}',
        '{"servers": {"A B": {"command": ["x"]}}}',
        '{"servers": {"ok": {"command": "sh -c evil"}}}',
    ):
        (tmp_path / "mcp.json").write_text(text)
        with pytest.raises(cfg.McpConfigError):
            cfg.load(tmp_path)


def test_set_enabled(tmp_path):
    cfg.add_server(tmp_path, "x", ["a"])
    cfg.set_enabled(tmp_path, "x", False)
    assert cfg.load(tmp_path)["x"].enabled is False
    assert json.loads((tmp_path / "mcp.json").read_text())["servers"]["x"]["enabled"] is False


def test_symlinked_config_is_refused(tmp_path):
    target = tmp_path / "baska.json"
    target.write_text('{"servers": {}}')
    home = tmp_path / "home"
    home.mkdir()
    (home / "mcp.json").symlink_to(target)
    with pytest.raises(cfg.McpConfigError):
        cfg.load(home)
