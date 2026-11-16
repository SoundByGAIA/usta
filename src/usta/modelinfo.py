"""Model uç noktasından model kimliği bilgisi (revizyon/özet). Profil ve deney kayıtları bunu kullanır."""

from __future__ import annotations

import httpx


def detect_revision(endpoint: str, model: str) -> str:
    """Ollama uç noktasında model özetini (digest) bulmaya çalışır; bulunamazsa boş (profil 'revizyonsuz' anahtarlanır)."""
    base = endpoint.rstrip("/")
    base = base.removesuffix("/v1")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        for m in r.json().get("models", []):
            if model in (m.get("name"), m.get("model")):
                return str(m.get("digest", ""))[:12]
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return ""


def detect_size_b(endpoint: str, model: str) -> float | None:
    """Ollama'nın bildirdiği parametre sayısı (milyar; "4.0B" → 4.0). Bulut ya da bilinmiyorsa None."""
    base = endpoint.rstrip("/").removesuffix("/v1")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        for m in r.json().get("models", []):
            if model in (m.get("name"), m.get("model")) or f"{model}:latest" == m.get("name"):
                size = str((m.get("details") or {}).get("parameter_size", "")).strip().upper()
                if size.endswith("B"):
                    return float(size[:-1])
                if size.endswith("M"):
                    return float(size[:-1]) / 1000
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return None
