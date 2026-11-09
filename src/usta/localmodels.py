"""Yerel model sunucularını bulma ve Ollama'da bağlam varyantı oluşturma.

Yalnız `127.0.0.1` sorgulanır (adres kullanıcıdan alınmaz, yalnız port): portaldan dışarıya ya da iç ağa
istek atılamaz. Bulunan sunucu yine kullanıcı onayıyla `apis.json`'a eklenir.
"""

from __future__ import annotations

import re

import httpx

HOST = "127.0.0.1"
COMMON_PORTS = {11434: "Ollama", 1234: "LM Studio", 8080: "llama.cpp", 8000: "vLLM"}
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,119}$")
MIN_CTX, MAX_CTX = 256, 2_000_000


class LocalError(Exception):
    """Kullanıcıya gösterilebilir yerel model hatası."""


def check_port(port: object) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise LocalError("port 1-65535 arasında olmalı")
    return port


def probe(port: int, timeout: float = 0.8) -> dict | None:
    """Port bir OpenAI-uyumlu sunucuysa {port, name, endpoint, models}; değilse None."""
    check_port(port)
    endpoint = f"http://{HOST}:{port}/v1"
    try:
        r = httpx.get(f"{endpoint}/models", timeout=timeout)
        r.raise_for_status()
        models = [m["id"] for m in r.json().get("data", []) if isinstance(m.get("id"), str)]
    except (httpx.HTTPError, ValueError, AttributeError, TypeError, KeyError):
        return None
    return {
        "port": port,
        "name": COMMON_PORTS.get(port, "yerel sunucu"),
        "endpoint": endpoint,
        "models": models,
    }


def scan(port: int | None = None) -> list[dict]:
    """`port` verilirse yalnız onu, verilmezse yaygın portları dener."""
    ports = [check_port(port)] if port is not None else list(COMMON_PORTS)
    return [found for p in ports if (found := probe(p))]


def context_variant(port: int, base: str, num_ctx: int, timeout: float = 120.0) -> str:
    """Ollama'da `base` modelinden `num_ctx` parametreli yeni bir model oluşturur; yeni adı döndürür.

    Ollama'nın `/v1` ucu istekteki `num_ctx`'i yok sayar; gerçek pencereyi değiştirmenin yolu budur.
    Ağırlıklar kopyalanmaz, yalnız bir üst veri katmanı eklenir.
    """
    check_port(port)
    if not isinstance(base, str) or not _MODEL_NAME.match(base):
        raise LocalError("model adı geçersiz")
    if (
        not isinstance(num_ctx, int)
        or isinstance(num_ctx, bool)
        or not MIN_CTX <= num_ctx <= MAX_CTX
    ):
        raise LocalError(f"bağlam {MIN_CTX}-{MAX_CTX} arasında olmalı")
    stem, _, tag = base.partition(":")
    new = f"{stem}-ctx{num_ctx}" + (f":{tag}" if tag else "")
    try:
        r = httpx.post(
            f"http://{HOST}:{port}/api/create",
            json={"model": new, "from": base, "parameters": {"num_ctx": num_ctx}, "stream": False},
            timeout=timeout,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        raise LocalError(
            "model varyantı oluşturulamadı (bu bir Ollama sunucusu mu, model yüklü mü?)"
        ) from None
    return new
