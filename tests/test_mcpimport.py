import json

import pytest

from usta import mcpimport


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(mcpimport.sys, "platform", "linux")
    return tmp_path


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_finds_servers_in_claude_desktop_cursor_and_vscode(home):
    write(
        home / ".config" / "Claude" / "claude_desktop_config.json",
        {
            "mcpServers": {
                "brave": {
                    "command": "npx",
                    "args": ["-y", "@brave/brave-search-mcp-server"],
                    "env": {"BRAVE_API_KEY": "gizli-deger"},
                }
            }
        },
    )
    write(
        home / ".cursor" / "mcp.json",
        {"mcpServers": {"Saat": {"command": "uvx", "args": ["mcp-server-time"]}}},
    )
    write(
        home / ".config" / "Code" / "User" / "mcp.json",
        {"servers": {"uzak": {"type": "http", "url": "https://ornek.com/mcp"}}},
    )
    found = {f.name: f for f in mcpimport.discover(home, {})}
    assert set(found) == {"brave", "Saat", "uzak"}
    b = found["brave"]
    assert (b.app, b.kind, b.package, b.image, b.usta_name) == (
        "Claude Desktop",
        "npm",
        "@brave/brave-search-mcp-server",
        "node:22-slim",
        "brave",
    )
    assert b.command == ("npx", "-y", "@brave/brave-search-mcp-server") and b.env == {
        "BRAVE_API_KEY": True
    }
    assert found["Saat"].kind == "pypi" and found["Saat"].usta_name == "saat"
    assert found["uzak"].kind is None and "internetteki" in found["uzak"].reason


def test_secret_values_never_leave_discovery(home):
    write(
        home / ".cursor" / "mcp.json",
        {
            "mcpServers": {
                "x": {"command": "npx", "args": ["-y", "pkg"], "env": {"TOKEN": "s3cr3t"}}
            }
        },
    )
    (f,) = mcpimport.discover(home, {})
    assert "s3cr3t" not in json.dumps(f.public())
    assert mcpimport.secret_values(f, home, {}) == {"TOKEN": "s3cr3t"}


def test_local_programs_and_scripts_cannot_move_into_the_box(home):
    write(
        home / ".cursor" / "mcp.json",
        {
            "mcpServers": {
                "betik": {"command": "node", "args": ["/home/ben/sunucu/index.js"]},
                "exe": {"command": "C:\\Araclar\\sunucu.exe"},
                "kabuk": {"command": "npx", "args": ["-y", "pkg", "&&", "rm", "-rf", "/"]},
            }
        },
    )
    found = {f.name: f for f in mcpimport.discover(home, {})}
    assert all(f.kind is None for f in found.values())
    assert "bilgisayarındaki" in found["betik"].reason


def test_version_in_spec_is_kept_and_flags_are_skipped(home):
    write(
        home / ".cursor" / "mcp.json",
        {
            "mcpServers": {
                "a": {"command": "npx.cmd", "args": ["--yes", "@scope/pkg@1.2.3", "--port", "1"]},
                "b": {"command": "uvx", "args": ["--from", "x", "y"]},
            }
        },
    )
    found = {f.name: f for f in mcpimport.discover(home, {})}
    assert found["a"].package == "@scope/pkg" and found["a"].version == "1.2.3"
    assert found["a"].command == ("npx", "-y", "@scope/pkg@1.2.3", "--port", "1")
    assert found["b"].kind is None  # --from gibi seçenekleri tahmin etmeyiz


def test_windows_config_locations_use_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(mcpimport.sys, "platform", "win32")
    appdata = tmp_path / "AppData" / "Roaming"
    write(
        appdata / "Claude" / "claude_desktop_config.json",
        {"mcpServers": {"x": {"command": "npx", "args": ["-y", "p"]}}},
    )
    write(
        appdata / "Code" / "User" / "mcp.json",
        {"servers": {"y": {"command": "npx", "args": ["-y", "q"]}}},
    )
    names = {f.name for f in mcpimport.discover(tmp_path, {"APPDATA": str(appdata)})}
    assert names == {"x", "y"}


def test_broken_or_missing_files_are_skipped(home):
    p = home / ".cursor" / "mcp.json"
    p.parent.mkdir(parents=True)
    p.write_text("{bozuk", encoding="utf-8")
    assert mcpimport.discover(home, {}) == []


def test_pin_resolves_latest_version_from_the_registry(home):
    write(
        home / ".cursor" / "mcp.json",
        {"mcpServers": {"x": {"command": "npx", "args": ["-y", "pkg", "--a"]}}},
    )
    (f,) = mcpimport.discover(home, {})
    asked = []

    def latest(kind, package):
        asked.append((kind, package))
        return "4.5.6"

    assert mcpimport.pinned_command(f, latest) == ("npx", "-y", "pkg@4.5.6", "--a")
    assert asked == [("npm", "pkg")]
