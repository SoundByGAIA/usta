"""Resmî MCP kayıt defterinden (registry.modelcontextprotocol.io) sunucu bulma: "şu repo iyiymiş" → kurulabilir sunucu.

Kayıt, sunucunun paketini (npm/PyPI), sabit sürümünü ve gereken anahtarları makinece okunur verir; Usta tahmin yürütmez.
GitHub bağlantısı verilince yalnız deposu birebir eşleşen kayıtlar gösterilir (benzer adlı sahte paket araya girmesin).
`io.github.<hesap>/` adları kayıtta GitHub hesabıyla doğrulanır; depo da aynı hesaptaysa "doğrulanmış yayıncı" denir.
Kullanıcıdan değer isteyen argümanları olan paketler ve internetteki (uzak) sunucular şimdilik eklenmez.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from usta.mcpimport import NPM_IMAGE, PYPI_IMAGE

REGISTRY = "https://registry.modelcontextprotocol.io/v0.1"
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)", re.IGNORECASE)
_SAFE_ARG = re.compile(r"[\w./:@=+,-]{1,200}")


@dataclass
class RegEntry:
    name: str
    description: str = ""
    version: str = ""
    repository: str = ""
    verified: bool = False
    kind: str | None = None
    package: str = ""
    command: tuple[str, ...] = ()
    image: str = ""
    env: list[dict] = field(default_factory=list)
    reason: str = ""

    def public(self) -> dict:
        return {
            "name": self.name,
            "description": self.description[:300],
            "version": self.version,
            "repository": self.repository,
            "verified": self.verified,
            "kind": self.kind,
            "package": self.package,
            "command": list(self.command),
            "image": self.image,
            "env": self.env,
            "reason": self.reason,
        }


def _repo_key(url: str) -> str:
    m = _GITHUB.match(url or "")
    return f"{m.group(1)}/{m.group(2).removesuffix('.git')}".lower() if m else ""


def _args(pkg: dict) -> list[str] | None:
    """Paketin sabit argümanları; kullanıcıdan değer isteyen varsa None."""
    if pkg.get("runtimeArguments"):
        return None
    out: list[str] = []
    for a in pkg.get("packageArguments") or []:
        value = a.get("value") if isinstance(a, dict) else None
        if not isinstance(value, str) or "{" in value or not _SAFE_ARG.fullmatch(value):
            return None
        if a.get("type") == "named":
            name = a.get("name")
            if not isinstance(name, str) or not _SAFE_ARG.fullmatch(name):
                return None
            out.append(name)
        out.append(value)
    return out


def parse(server: dict) -> RegEntry:
    repo = (server.get("repository") or {}).get("url") or ""
    e = RegEntry(
        name=str(server.get("name", "")),
        description=str(server.get("description", "")),
        version=str(server.get("version", "")),
        repository=repo,
    )
    owner = _repo_key(repo).split("/")[0]
    e.verified = bool(owner) and e.name.lower().startswith(f"io.github.{owner}/")
    for pkg in server.get("packages") or []:
        kind = pkg.get("registryType")
        if kind not in ("npm", "pypi") or (pkg.get("transport") or {}).get("type") != "stdio":
            continue
        ident, ver = str(pkg.get("identifier", "")), str(pkg.get("version", ""))
        if not _SAFE_ARG.fullmatch(ident) or not _SAFE_ARG.fullmatch(ver):
            continue
        args = _args(pkg)
        e.kind, e.package = kind, ident
        e.env = [
            {
                "name": v.get("name"),
                "required": bool(v.get("isRequired")),
                "secret": bool(v.get("isSecret")),
                "description": str(v.get("description", ""))[:200],
            }
            for v in pkg.get("environmentVariables") or []
            if isinstance(v, dict) and isinstance(v.get("name"), str)
        ]
        if args is None:
            e.reason = "kurulurken senden değer isteyen ayarları var; şimdilik otomatik kurulamıyor"
            return e
        if kind == "npm":
            e.command, e.image = ("npx", "-y", f"{ident}@{ver}", *args), NPM_IMAGE
        else:
            e.command, e.image = ("uvx", f"{ident}=={ver}", *args), PYPI_IMAGE
        return e
    e.reason = (
        "internetteki bir sunucu; Usta şimdilik yalnız bilgisayarda çalışan sunucuları ekleyebilir"
        if server.get("remotes")
        else "npm ya da PyPI paketi yok; otomatik kurulamıyor"
    )
    return e


def _get_json(path: str) -> dict:
    with urllib.request.urlopen(REGISTRY + path, timeout=15) as r:  # sabit https kayıt adresi
        return json.load(r)


def search(query: str, get: Callable[[str], dict] | None = None) -> list[RegEntry]:
    """GitHub bağlantısı, paket adı ya da kayıt adı → eşleşen kayıtlar (en çok 10)."""
    get = get or _get_json
    query = query.strip()
    repo = _repo_key(query)
    term = repo.split("/")[1] if repo else query.rsplit("/", 1)[-1]
    params = urllib.parse.urlencode({"search": term[:100], "version": "latest", "limit": 50})
    servers = [s.get("server", s) for s in get(f"/servers?{params}").get("servers", [])]
    out = []
    for s in servers:
        e = parse(s)
        if repo:
            keep = _repo_key(e.repository) == repo
        else:
            idents = {p.get("identifier") for p in s.get("packages") or []}
            keep = query in idents or e.name == query
        if keep:
            out.append(e)
    return out[:10]


def fetch(name: str, version: str, get: Callable[[str], dict] | None = None) -> RegEntry:
    """Kaydı sunucudan yeniden okur (eklerken tarayıcıdan gelen komuta güvenilmez)."""
    get = get or _get_json
    path = f"/servers/{urllib.parse.quote(name, safe='')}/versions/{urllib.parse.quote(version, safe='')}"
    data = get(path)
    return parse(data.get("server", data))
