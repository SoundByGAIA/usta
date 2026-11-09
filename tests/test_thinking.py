"""Düşünme ayarı: seçimin isteğe çevrilmesi ve tanımayan uç noktada geri çekilme."""

import httpx

from usta import thinking
from usta.models import Message, OpenAICompatClient


def test_extra_for_maps_choices():
    assert thinking.extra_for("auto") == {}
    assert thinking.extra_for("off") == {"reasoning_effort": "none"}
    assert thinking.extra_for("high") == {"reasoning_effort": "high"}


def test_client_drops_reasoning_field_once_when_endpoint_rejects_it(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        has = "reasoning_effort" in request.content.decode()
        seen.append(has)
        if has:
            return httpx.Response(400, json={"error": "unknown field"}, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "tamam"}}]},
            request=request,
        )

    def fake_post(url, json=None, headers=None, timeout=None):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OpenAICompatClient("http://x/v1", "m", extra_body=thinking.extra_for("off"))
    assert client.chat([Message(role="user", content="selam")]).content == "tamam"
    assert seen == [True, False]
    client.chat([Message(role="user", content="tekrar")])
    assert seen == [True, False, False]  # alan kalıcı olarak bırakıldı
