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
from dataclasses import replace as dc_replace
from pathlib import Path

from usta import compat

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
BLOCKED_ENV_PREFIXES = ("LD_", "DYLD_")
APPROVE_MODES = ("ask", "allow")
ISOLATIONS = ("container", "host")  # varsayılan container; host yalnız açık "uyumluluk modu"
WORKSPACE_MODES = ("none", "ro", "rw")  # sunucuya çalışma alanı bağlanır mı
MAX_ARG = 4096
IMAGE = re.compile(
    r"[a-z0-9][a-z0-9._/-]{0,127}(?::[A-Za-z0-9._-]{1,128})?(?:@sha256:[0-9a-f]{64})?"
)
MEMORY = re.compile(r"[1-9][0-9]{1,4}[mg]")
CPUS = re.compile(r"(?:0\.[1-9][0-9]?|[1-4](?:\.[0-9])?)")
HOST = re.compile(r"(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")


class McpConfigError(Exception):
    """Kullanıcıya gösterilebilir yapılandırma hatası."""


@dataclass(frozen=True)
class Server:
    name: str
    command: tuple[str, ...]
    env: tuple[str, ...] = ()
    approve: str = "ask"
    enabled: bool = True
    # İzolasyon (docs/design.md §5.3). Varsayılan: konteyner (ağ kapalı, çalışma alanı bağlı değil,
    # kök dosya sistemi salt okunur, sırlar yalnız tanımlı env adları). `host` açık uyumluluk modudur.
    isolation: str = "container"
    image: str | None = None
    allow_hosts: tuple[str, ...] = ()  # yalnız bu alan adlarına allowlist proxy ile çıkış
    workspace: str = "none"
    memory: str = "256m"
    cpus: str = "0.5"
    pids: int = 64
    pin_image: str = ""  # `usta mcp prepare` anında kaydedilen yerel imaj kimliği (sha256:...)
    pin_cache: str = ""  # hazırlanan paket önbelleğinin içerik özeti (sha256)


def validate_runtime(
    isolation: object,
    image: object,
    allow_hosts: object,
    workspace: object,
    memory: object = "256m",
    cpus: object = "0.5",
    pids: object = 64,
) -> None:
    if isolation not in ISOLATIONS:
        raise McpConfigError("isolation 'container' veya 'host' olmalı")
    if image is not None and (
        not isinstance(image, str) or not IMAGE.fullmatch(image) or ".." in image
    ):
        raise McpConfigError(f"geçersiz imaj adı: {image!r}")
    if isolation == "container" and image is None:
        raise McpConfigError("konteyner izolasyonu için imaj gerekir (--image, ör. node:22-slim)")
    if not isinstance(allow_hosts, (list, tuple)) or not all(
        isinstance(h, str) and HOST.fullmatch(h) for h in allow_hosts
    ):
        raise McpConfigError("allow_hosts, alan adlarının listesi olmalı")
    if isolation == "host" and allow_hosts:
        raise McpConfigError("allow_hosts yalnız konteyner izolasyonunda anlamlıdır")
    if workspace not in WORKSPACE_MODES:
        raise McpConfigError("workspace 'none', 'ro' veya 'rw' olmalı")
    if not isinstance(memory, str) or not MEMORY.fullmatch(memory):
        raise McpConfigError("memory geçersiz (ör. 256m, 1g)")
    if not isinstance(cpus, str) or not CPUS.fullmatch(cpus):
        raise McpConfigError("cpus geçersiz (0.1-4)")
    if not isinstance(pids, int) or isinstance(pids, bool) or not 8 <= pids <= 512:
        raise McpConfigError("pids 8-512 arasında olmalı")


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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise McpConfigError(f"{path.name} okunamadı veya bozuk") from None
    if not isinstance(data, dict):
        raise McpConfigError(f"{path.name} biçimi geçersiz")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
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
        # Eski kayıtlarda isolation yoktur: güvenli varsayılan konteynerdir; imajı olmayan eski
        # kayıt bu yüzden kapalı başarısız olur (sessizce ana makinede çalışmaz).
        rt = {
            "isolation": d.get("isolation", "container"),
            "image": d.get("image"),
            "allow_hosts": d.get("allow_hosts", []),
            "workspace": d.get("workspace", "none"),
            "memory": d.get("memory", "256m"),
            "cpus": d.get("cpus", "0.5"),
            "pids": d.get("pids", 64),
        }
        if rt["isolation"] == "container" and rt["image"] is None:
            runtime = Server(
                name, tuple(command), tuple(env), approve, d.get("enabled", True) is True
            )
            out[name] = runtime  # imajsız: başlatma anında "imaj gerekli" hatası verir
            continue
        validate_runtime(**rt)
        out[name] = Server(
            name,
            tuple(command),
            tuple(env),
            approve,
            d.get("enabled", True) is True,
            isolation=rt["isolation"],
            image=rt["image"],
            allow_hosts=tuple(rt["allow_hosts"]),
            workspace=rt["workspace"],
            memory=rt["memory"],
            cpus=rt["cpus"],
            pids=rt["pids"],
            pin_image=d.get("pin_image", "") if isinstance(d.get("pin_image"), str) else "",
            pin_cache=d.get("pin_cache", "") if isinstance(d.get("pin_cache"), str) else "",
        )
    return out


def _save(home: Path, servers: Mapping[str, Server]) -> None:
    raw = {
        s.name: {
            "command": list(s.command),
            "env": list(s.env),
            "approve": s.approve,
            "enabled": s.enabled,
            "isolation": s.isolation,
            "image": s.image,
            "allow_hosts": list(s.allow_hosts),
            "workspace": s.workspace,
            "memory": s.memory,
            "cpus": s.cpus,
            "pids": s.pids,
            "pin_image": s.pin_image,
            "pin_cache": s.pin_cache,
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
    *,
    isolation: str = "container",
    image: str | None = None,
    allow_hosts: list[str] | tuple[str, ...] = (),
    workspace: str = "none",
    memory: str = "256m",
    cpus: str = "0.5",
    pids: int = 64,
) -> Server:
    env = list(env or [])
    validate(name, command, env, approve)
    validate_runtime(isolation, image, list(allow_hosts), workspace, memory, cpus, pids)
    servers = load(home)
    if name in servers and not replace:
        raise McpConfigError(f"'{name}' zaten var (üzerine yazmak için --replace)")
    servers[name] = Server(
        name,
        tuple(command),
        tuple(env),
        approve,
        True,
        isolation=isolation,
        image=image,
        allow_hosts=tuple(h.lower() for h in allow_hosts),
        workspace=workspace,
        memory=memory,
        cpus=cpus,
        pids=pids,
    )
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
    servers[name] = dc_replace(servers[name], enabled=enabled)
    _save(home, servers)


def set_pin(home: Path, name: str, image_id: str, cache_digest: str) -> None:
    """`usta mcp prepare` sonrası bütünlük sabitlemesi: imaj kimliği ve paket önbelleği özeti."""
    servers = load(home)
    if name not in servers:
        raise McpConfigError(f"'{name}' yok")
    servers[name] = dc_replace(servers[name], pin_image=image_id, pin_cache=cache_digest)
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
