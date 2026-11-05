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
