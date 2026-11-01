"""Bağlı model API'leri: `~/.usta/apis.json` (0600). Anahtarlar yalnız burada durur.

Her kayıt bir OpenAI-uyumlu uç noktadır (Ollama, DeepSeek, OpenRouter…). Anahtar arayüze/API'ye
asla geri verilmez, yalnız "var/yok" bilgisi görünür. Dosya çalışma alanının dışındadır; ajan okuyamaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from usta.mcpconfig import McpConfigError, _read_json, _write_json

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")
RESERVED = {"varsayılan"}
MAX_KEY = 8192


class ApiError(Exception):
    """Kullanıcıya gösterilebilir API yapılandırma hatası."""


@dataclass(frozen=True)
class Api:
    name: str
    endpoint: str
    key: str | None = None


def check_endpoint(endpoint: object) -> str:
    if not isinstance(endpoint, str) or len(endpoint) > 500:
        raise ApiError("uç nokta geçersiz")
    u = urlsplit(endpoint.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ApiError(
            "uç nokta http(s)://alan-adı/yol biçiminde olmalı (içinde kullanıcı/şifre olmaz)"
        )
    if u.query or u.fragment:
        raise ApiError("uç noktada sorgu/parça olmaz")
    return endpoint.strip().rstrip("/")


def _load_raw(home: Path) -> dict:
    try:
        data = _read_json(Path(home) / "apis.json", {"apis": {}})
    except McpConfigError as e:
        raise ApiError(str(e)) from None
    apis = data.get("apis", {})
    return apis if isinstance(apis, dict) else {}


def load(home: Path) -> dict[str, Api]:
    out = {}
    for name, v in _load_raw(home).items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(v, dict):
            continue
        try:
            ep = check_endpoint(v.get("endpoint"))
        except ApiError:
            continue
        key = v.get("key")
        out[name] = Api(name, ep, key if isinstance(key, str) and key else None)
    return out


def _save(home: Path, apis: dict[str, Api]) -> None:
    body = {
        n: {"endpoint": a.endpoint, **({"key": a.key} if a.key else {})} for n, a in apis.items()
    }
    _write_json(Path(home) / "apis.json", {"apis": body})


def add(home: Path, name: str, endpoint: str, key: str | None = None) -> Api:
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in RESERVED:
        raise ApiError("ad küçük harf/rakam/-/_ olmalı (en çok 30 karakter)")
    if key is not None and (not key or "\x00" in key or len(key) > MAX_KEY):
        raise ApiError("anahtar geçersiz")
    apis = load(home)
    if name in apis:
        raise ApiError("bu adla bir API zaten var")
    apis[name] = Api(name, check_endpoint(endpoint), key or None)
    _save(home, apis)
    return apis[name]


def set_key(home: Path, name: str, key: str | None) -> None:
    apis = load(home)
    if name not in apis:
        raise ApiError("API yok")
    if key is not None and (not key or "\x00" in key or len(key) > MAX_KEY):
        raise ApiError("anahtar geçersiz")
    a = apis[name]
    apis[name] = Api(a.name, a.endpoint, key or None)
    _save(home, apis)


def remove(home: Path, name: str) -> None:
    apis = load(home)
    if apis.pop(name, None) is None:
        raise ApiError("API yok")
    _save(home, apis)
