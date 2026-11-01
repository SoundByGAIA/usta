"""Model yetenek sondası: modele küçük, kontrollü istekler gönderip hangi araç çağrısı protokolünün
güvenilir çalıştığını ölçer (tahmin değil kalibrasyon). Sonuç `~/.usta/profiles.json`'da önbelleğe alınır;
kullanıcının elle verdiği protokol her zaman önceliklidir.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from usta.jsonproto import JsonProtocolClient
from usta.models import Message, ModelClient, ModelError
from usta.textproto import TextProtocolClient

PROBES = (
    ("a.txt dosyasını read_file aracıyla oku.", "read_file", {"path"}),
    ("Çalışma dizinindeki dosyaları listelemek için komut çalıştır (run aracı, ls).", "run", {"command"}),
    ('not.txt dosyasına iki satır yaz: birinci satır `satır 1`, ikinci satır `"tırnaklı" satır 2`. write_file kullan.', "write_file", {"path", "content"}),
)  # fmt: skip
TOOLS = [
    {"name": "read_file", "description": "Dosya okur.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run", "description": "Komut çalıştırır.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "write_file", "description": "Dosya yazar.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]  # fmt: skip
SYSTEM = "Araçları kullanarak görevi yap. Önce araç çağır."
PROTOCOLS = ("native", "json", "text")


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    model: str
    protocol: str  # native | text
    native_ok: int
    text_ok: int
    rescued: int
    total: int
    note: str = ""
    ts: float = 0.0
    json_ok: int = 0


def _ok(reply, expect_tool: str, keys: set[str]) -> bool:
    return any(
        c.name == expect_tool and keys <= set(c.arguments) and all(isinstance(c.arguments[k], str) and c.arguments[k] for k in keys)
        for c in reply.tool_calls
    )  # fmt: skip


def _run(client: ModelClient, tools: list[dict] | None) -> tuple[int, int]:
    ok, rescued = 0, 0
    usage = getattr(client, "usage", None)
    for prompt, tool, keys in PROBES:
        before = usage.rescued if usage is not None else 0
        try:
            reply = client.chat([Message("system", SYSTEM), Message("user", prompt)], tools)
        except ModelError as e:
            if e.infra:
                raise ProfileError(f"model uç noktasına ulaşılamadı: {e}") from e
            continue  # protokol bozuldu: bu yetenek başarısız sayılır
        if _ok(reply, tool, keys):
            ok += 1
            if usage is not None and usage.rescued > before:
                rescued += 1
    return ok, rescued


def _supports_extra(client: object) -> bool:
    try:
        return "extra" in inspect.signature(client.chat).parameters  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return False


def probe(client: ModelClient, model: str) -> Profile:
    total = len(PROBES)
    native_ok, rescued = _run(client, TOOLS)
    json_ok = (
        _run(JsonProtocolClient(client, retries=0), TOOLS)[0] if _supports_extra(client) else 0
    )
    text_ok, _ = _run(TextProtocolClient(client, retries=0), TOOLS)
    counts = {"native": native_ok, "json": json_ok, "text": text_ok}
    order = ("native", "json", "text")  # eşitlikte en basit/güvenilir olan önce
    best = max(order, key=lambda k: (counts[k], -order.index(k)))
    if counts[best] >= 2:
        protocol = best
        note = f"{best} protokolü {counts[best]}/{total}"
        if best == "native" and rescued:
            note += f" (bunların {rescued}'i içerikten kurtarıldı)"
        elif best != "native":
            note += f"; yerel araç çağrısı güvenilmez ({native_ok}/{total})"
    else:
        protocol = "text"
        note = (
            f"hiçbir protokol güvenilir değil (yerel {native_ok}/{total}, json {json_ok}/{total}, "
            f"metin {text_ok}/{total}); metin protokolü denenecek"
        )
    return Profile(model, protocol, native_ok, text_ok, rescued, total, note, time.time(), json_ok)


def _key(endpoint: str, model: str) -> str:
    return f"{endpoint.rstrip('/')}|{model}"


def load(home: Path, endpoint: str, model: str) -> Profile | None:
    path = Path(home) / "profiles.json"
    try:
        data = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
        raw = data.get(_key(endpoint, model)) if isinstance(data, dict) else None
        if not isinstance(raw, dict) or raw.get("protocol") not in PROTOCOLS:
            return None
        return Profile(**{k: raw[k] for k in Profile.__dataclass_fields__ if k in raw})
    except (OSError, ValueError, TypeError):
        return None


def save(home: Path, endpoint: str, model: str, p: Profile) -> None:
    home = Path(home)
    path = home / "profiles.json"
    try:
        data = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[_key(endpoint, model)] = asdict(p)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("profiles.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def resolve_protocol(
    home: Path, endpoint: str, model: str, make_client: Callable[[], ModelClient]
) -> Profile:
    """Önbellekte varsa onu, yoksa sondayı çalıştırıp kaydederek profili döndürür."""
    cached = load(home, endpoint, model)
    if cached is not None:
        return cached
    p = probe(make_client(), model)
    try:
        save(home, endpoint, model, p)
    except OSError:
        pass
    return p
