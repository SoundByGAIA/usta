"""Bilgisayarda başka uygulamalara (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf) kurulmuş MCP sunucularını bulur.

Bulunan her sunucu için Usta'nın onu kendi kabında nasıl çalıştırabileceğini söyler: npm (`npx`) ve PyPI (`uvx`)
paketleri kaba taşınır; bilgisayardaki bir programı ya da betiği doğrudan çalıştıranlar ve internetteki sunucular
taşınamaz (nedeniyle gösterilir). Kullanıcı onaylamadan hiçbir şey eklenmez.

Anahtar değerleri bulma sırasında dışarı verilmez (`public()` yalnız "değeri var mı" der); kullanıcı isterse ekleme anında
`secret_values` ile yeniden okunur.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

NPM_IMAGE = "node:22-slim"
PYPI_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
_NPM_SPEC = re.compile(r"(@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*(@[\w.+-]+)?", re.IGNORECASE)
_PYPI_SPEC = re.compile(r"[A-Za-z0-9][\w.-]*((==|@)[\w.+!-]+)?")
_SHELL = re.compile(r"[;&|`$<>]")


@dataclass
class Found:
    app: str  # hangi uygulamada bulundu
    name: str  # o uygulamadaki adı
    config: str  # ayar dosyasının yolu
    usta_name: str  # Usta'da kullanılacak ad
    kind: str | None = None  # "npm" | "pypi"; None: kaba taşınamaz
    package: str = ""
    version: str = ""  # ayar dosyasında sabitlenmişse
    command: tuple[str, ...] = ()
    image: str = ""
    env: dict[str, bool] = field(default_factory=dict)  # ad -> değeri ayarda var mı
    reason: str = ""  # taşınamıyorsa neden

    def public(self) -> dict:
        return {
            "app": self.app,
            "name": self.name,
            "usta_name": self.usta_name,
            "kind": self.kind,
            "package": self.package,
            "version": self.version,
            "command": list(self.command),
            "image": self.image,
            "env": [{"name": k, "has_value": v} for k, v in self.env.items()],
            "reason": self.reason,
        }


def config_files(home: Path, env: Mapping[str, str]) -> list[tuple[str, Path, str]]:
    """(uygulama, ayar dosyası, sunucuların durduğu anahtar)."""
    if sys.platform == "win32":
        appdata = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        appdata = home / "Library" / "Application Support"
    else:
        appdata = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    return [
        ("Claude Desktop", appdata / "Claude" / "claude_desktop_config.json", "mcpServers"),
        ("Claude Code", home / ".claude.json", "mcpServers"),
        ("Cursor", home / ".cursor" / "mcp.json", "mcpServers"),
        ("VS Code", appdata / "Code" / "User" / "mcp.json", "servers"),
        ("Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),
    ]


def _servers(path: Path, key: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = data.get(key) if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


def usta_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")[:26].replace("__", "_") or "mcp"
    base = base if base[0].isalnum() else "m" + base
    out, n = base, 2
    while out in taken:
        out, n = f"{base[:26]}-{n}", n + 1
    taken.add(out)
    return out


def _classify(f: Found, spec: dict) -> None:
    if spec.get("url") or spec.get("type") in ("http", "sse", "streamable-http"):
        f.reason = "internetteki bir sunucu; Usta şimdilik yalnız bilgisayarda çalışan sunucuları ekleyebilir"
        return
    command, args = spec.get("command"), spec.get("args") or []
    if (
        not isinstance(command, str)
        or not isinstance(args, list)
        or not all(isinstance(a, str) for a in args)
    ):
        f.reason = "ayar okunamadı"
        return
    if any(_SHELL.search(a) for a in [command, *args]):
        f.reason = "komutta beklenmeyen kabuk işaretleri var"
        return
    tool = Path(command.replace("\\", "/")).name.lower().removesuffix(".cmd").removesuffix(".exe")
    if tool == "npx":
        rest = [a for a in args if a not in ("-y", "--yes")]
        if not rest or rest[0].startswith("-") or not _NPM_SPEC.fullmatch(rest[0]):
            f.reason = "npx seçenekleri tanınmadı"
            return
        at = rest[0].rfind("@")  # "@scope/paket@1.2" → sürüm sondaki @'den sonra
        name, ver = (rest[0][:at], rest[0][at + 1 :]) if at > 0 else (rest[0], "")
        f.kind, f.package, f.version, f.image = "npm", name, ver, NPM_IMAGE
        f.command = ("npx", "-y", rest[0], *rest[1:])
    elif tool == "uvx":
        if not args or args[0].startswith("-") or not _PYPI_SPEC.fullmatch(args[0]):
            f.reason = "uvx seçenekleri tanınmadı"
            return
        name, ver = (
            re.split(r"==|@", args[0], maxsplit=1) if re.search(r"==|@", args[0]) else (args[0], "")
        )
        f.kind, f.package, f.version, f.image = "pypi", name, ver, PYPI_IMAGE
        f.command = ("uvx", *args)
    else:
        f.reason = (
            "bilgisayarındaki bir programı ya da betiği doğrudan çalıştırıyor; kaba taşınamaz"
        )


def discover(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Found]:
    home = Path(home) if home is not None else Path.home()
    env = os.environ if env is None else env
    found: list[Found] = []
    taken: set[str] = set()
    for app, path, key in config_files(home, env):
        for name, spec in _servers(path, key).items():
            if not isinstance(name, str) or not isinstance(spec, dict):
                continue
            f = Found(app, name, str(path), usta_name(name, taken))
            values = spec.get("env") if isinstance(spec.get("env"), dict) else {}
            # VS Code'un ${input:...} yer tutucuları gerçek değer değildir
            f.env = {
                k: isinstance(v, str) and bool(v) and not v.startswith("${")
                for k, v in values.items()
                if isinstance(k, str)
            }
            _classify(f, spec)
            found.append(f)
    return found


def secret_values(
    f: Found, home: Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Kullanıcı "anahtarları da kopyala" dediğinde: ayar dosyasındaki gerçek değerler."""
    for app, path, key in config_files(
        Path(home) if home is not None else Path.home(), os.environ if env is None else env
    ):
        if app == f.app and str(path) == f.config:
            values = _servers(path, key).get(f.name, {}).get("env") or {}
            return {k: v for k, v in values.items() if f.env.get(k) and isinstance(v, str)}
    return {}


def latest_version(kind: str, package: str, timeout: float = 10.0) -> str:
    """Paket kaydındaki son sürüm (npm ya da PyPI); bulunamazsa OSError/ValueError."""
    import urllib.parse
    import urllib.request

    quoted = urllib.parse.quote(package, safe="@")
    url = (
        f"https://registry.npmjs.org/{quoted}/latest"
        if kind == "npm"
        else f"https://pypi.org/pypi/{quoted}/json"
    )
    with urllib.request.urlopen(url, timeout=timeout) as r:  # sabit https kayıt adresleri
        data = json.load(r)
    ver = data.get("version") if kind == "npm" else (data.get("info") or {}).get("version")
    if not isinstance(ver, str) or not re.fullmatch(r"[\w.+!-]{1,64}", ver):
        raise ValueError(f"sürüm okunamadı: {package}")
    return ver


def pinned_command(f: Found, latest: Callable[[str, str], str]) -> tuple[str, ...]:
    """Sürümü sabitlenmiş komut: ayarda sürüm yoksa paket kaydındaki son sürüm (tedarik zinciri)."""
    ver = f.version or latest(f.kind or "", f.package)
    if f.kind == "npm":
        return ("npx", "-y", f"{f.package}@{ver}", *f.command[3:])
    return ("uvx", f"{f.package}=={ver}", *f.command[2:])
