"""MCP sunucu yapılandırması: `~/.usta/mcp.json` (komutlar) + `~/.usta/mcp-secrets.json` (değerler).

Yapılandırma çalışma alanının DIŞINDA durur, ajan değiştiremez. Anahtar *değerleri* mcp.json'a
yazılmaz; yalnız ortam değişkeni adları tutulur, değerler 0600 ayrı dosyadadır.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
BLOCKED_ENV_PREFIXES = ("LD_", "DYLD_")
APPROVE_MODES = ("ask", "allow")
MAX_ARG = 4096


class McpConfigError(Exception):
    """Kullanıcıya gösterilebilir yapılandırma hatası."""


@dataclass(frozen=True)
class Server:
    name: str
    command: tuple[str, ...]
    env: tuple[str, ...] = ()
    approve: str = "ask"
    enabled: bool = True


def validate(name: object, command: object, env: object, approve: object) -> None:
    if not isinstance(name, str) or not NAME.fullmatch(name) or "__" in name:
        raise McpConfigError(
            f"sunucu adı küçük harf/rakam/-/_ olmalı (en çok 30 karakter, '__' yok): {name!r}"
        )
    if (
        not isinstance(command, (list, tuple))
        or not command
        or not all(
            isinstance(c, str) and c and "\x00" not in c and len(c) <= MAX_ARG for c in command
        )
    ):
        raise McpConfigError("komut, boş olmayan metinlerden oluşan bir liste olmalı")
    if not isinstance(env, (list, tuple)) or len(set(env)) != len(env):
        raise McpConfigError("env, benzersiz ortam değişkeni adlarının listesi olmalı")
    for e in env:
        if (
            not isinstance(e, str)
            or not ENV_NAME.fullmatch(e)
            or e.startswith(BLOCKED_ENV_PREFIXES)
        ):
            raise McpConfigError(f"geçersiz ortam değişkeni adı: {e!r}")
    if approve not in APPROVE_MODES:
        raise McpConfigError("approve 'ask' veya 'allow' olmalı")


def _read_json(path: Path, default: dict) -> dict:
    if path.is_symlink():
        raise McpConfigError(f"{path.name} sembolik bağ olamaz")
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise McpConfigError(f"{path.name} okunamadı veya bozuk") from None
    if not isinstance(data, dict):
        raise McpConfigError(f"{path.name} biçimi geçersiz")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def _servers_raw(home: Path) -> dict:
    data = _read_json(home / "mcp.json", {"servers": {}})
    servers = data.get("servers", {})
    if not isinstance(servers, dict):
        raise McpConfigError("mcp.json: 'servers' bir nesne olmalı")
    return servers


def load(home: Path) -> dict[str, Server]:
    out = {}
    for name, d in _servers_raw(Path(home)).items():
        if not isinstance(d, dict):
            raise McpConfigError(f"mcp.json: '{name}' geçersiz")
        command, env, approve = d.get("command"), d.get("env", []), d.get("approve", "ask")
        validate(name, command, env, approve)
        out[name] = Server(
            name, tuple(command), tuple(env), approve, d.get("enabled", True) is True
        )
    return out


def _save(home: Path, servers: Mapping[str, Server]) -> None:
    raw = {
        s.name: {
            "command": list(s.command),
            "env": list(s.env),
            "approve": s.approve,
            "enabled": s.enabled,
        }
        for s in servers.values()
    }
    _write_json(Path(home) / "mcp.json", {"servers": raw})


def add_server(
    home: Path,
    name: str,
    command: list[str],
    env: list[str] | None = None,
    approve: str = "ask",
    replace: bool = False,
) -> Server:
    env = list(env or [])
    validate(name, command, env, approve)
    servers = load(home)
    if name in servers and not replace:
        raise McpConfigError(f"'{name}' zaten var (üzerine yazmak için --replace)")
    servers[name] = Server(name, tuple(command), tuple(env), approve, True)
    _save(home, servers)
    return servers[name]


def remove_server(home: Path, name: str) -> None:
    servers = load(home)
    if name not in servers:
        raise McpConfigError(f"'{name}' yok")
    del servers[name]
    _save(home, servers)
    secrets = _secrets(home)
    if secrets.pop(name, None) is not None:
        _write_json(Path(home) / "mcp-secrets.json", secrets)


def set_enabled(home: Path, name: str, enabled: bool) -> None:
    servers = load(home)
    if name not in servers:
        raise McpConfigError(f"'{name}' yok")
    s = servers[name]
    servers[name] = Server(s.name, s.command, s.env, s.approve, enabled)
    _save(home, servers)


def _secrets(home: Path) -> dict:
    data = _read_json(Path(home) / "mcp-secrets.json", {})
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def set_secret(home: Path, server: str, key: str, value: str) -> None:
    servers = load(home)
    if server not in servers or key not in servers[server].env:
        raise McpConfigError(f"'{server}' için '{key}' tanımlı değil")
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 8192:
        raise McpConfigError("değer geçersiz")
    secrets = _secrets(home)
    secrets.setdefault(server, {})[key] = value
    _write_json(Path(home) / "mcp-secrets.json", secrets)


def resolve_env(home: Path, server: Server, environ: Mapping[str, str]) -> dict[str, str]:
    """Sunucuya verilecek ortam: yalnız tanımlı adlar; önce gizli depo, sonra süreç ortamı."""
    stored = _secrets(home).get(server.name, {})
    out = {}
    for key in server.env:
        value = stored.get(key) if isinstance(stored.get(key), str) else environ.get(key)
        if value:
            out[key] = value
    return out
