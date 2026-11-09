"""Düşünme ayarı: kullanıcının seçimini isteğe eklenecek alanlara çevirir.

`auto` modelin kendi varsayılanına dokunmaz. Diğerleri OpenAI-uyumlu `reasoning_effort` alanını gönderir
(Ollama, Gemini ve benzerleri tanır; tanımayan uç nokta 400 verirse istemci alanı bırakıp bir kez yeniden dener).
"""

from __future__ import annotations

THINK = ("auto", "off", "low", "medium", "high")
FIELD = "reasoning_effort"


def extra_for(think: str) -> dict:
    if think == "off":
        return {FIELD: "none"}
    if think in ("low", "medium", "high"):
        return {FIELD: think}
    return {}
