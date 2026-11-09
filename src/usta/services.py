"""Bilinen servisler için model listesi düzeltmeleri.

Çoğu uç nokta `GET /models` ile OpenAI biçiminde liste verir. İki istisna var:
- OpenCode ağ geçidi her modelin hangi yolla çalıştığını `api` alanında yazar; GPT/Claude/Gemini modelleri
  `chat/completions` ile değil kendi yollarıyla çalışır, "-free" modeller yalnız OpenCode uygulamasında çalışır
  (resmî sayfa: "Free-tier chat models require OpenCode"). Usta yalnız `chat/completions` konuştuğundan bunlar süzülür.
- Anthropic'in OpenAI-uyumlu ucunda `/models` desteği doğrulanamadı; liste boş dönerse bilinen modeller kullanılır.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Kaynak: platform.claude.com OpenAI-uyumluluk sayfası ve OpenCode model listesi (2026-11-09).
PRESET_MODELS: dict[str, list[str]] = {
    "https://api.anthropic.com/v1": [
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
    ],
}


def _norm(endpoint: str) -> str:
    u = urlsplit(endpoint.strip())
    return f"{u.scheme}://{u.netloc}{u.path}".rstrip("/").lower()


def _is_free(entry: dict) -> bool:
    """OpenCode kaydında metin girişi fiyatı 0 ise ücretsiz katmandır (ör. `big-pickle`; adı `-free` ile bitmez)."""
    cost = entry.get("cost")
    try:
        return float(cost["text"]["input"]["price"]) == 0.0
    except (KeyError, TypeError, ValueError):
        return str(entry.get("id", "")).endswith("-free")


def usable_ids(entries: list) -> list[str]:
    """`/models` kayıtlarından Usta'nın kullanabileceği kimlikler (yalnız metadata varsa süzer)."""
    out = []
    for m in entries:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            continue
        api = m.get("api")
        opencode_style = isinstance(api, dict)  # modelin konuştuğu protokoller yazılı
        if opencode_style and ("chat-completions" not in api or _is_free(m)):
            continue
        out.append(m["id"])
    return out


def fallback_models(endpoint: str) -> list[str]:
    return list(PRESET_MODELS.get(_norm(endpoint), []))
