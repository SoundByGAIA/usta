"""Servis model listesi düzeltmeleri: OpenCode süzmesi ve Anthropic için sabit liste."""

import httpx

from usta import cli, services

OPENCODE = [
    {
        "id": "deepseek-v4-pro",
        "api": {"chat-completions": {}},
        "cost": {"text": {"input": {"price": 1.74}}},
    },
    {"id": "glm-5.3", "api": {"chat-completions": {}}},
    {
        "id": "deepseek-v4.1-flash-free",
        "api": {"chat-completions": {}},
    },  # yalnız OpenCode'da çalışır
    {"id": "gpt-5.2", "api": {"responses": {}}},  # chat/completions değil
    {"id": "claude-sonnet-5-5", "api": {"messages": {}}},
    {"id": "gemini-3.6-flash", "api": {"generate-content": {}}},
]


def test_opencode_list_keeps_only_paid_chat_completions_models():
    assert services.usable_ids(OPENCODE) == ["deepseek-v4-pro", "glm-5.3"]


def test_plain_openai_style_entries_are_untouched():
    assert services.usable_ids(
        [{"id": "gpt-4o"}, {"id": "x", "object": "model"}, {"nope": 1}, "str"]
    ) == [
        "gpt-4o",
        "x",
    ]


def _get(payload=None, fail=False):
    def get(url, headers=None, timeout=None):
        req = httpx.Request("GET", url)
        if fail:
            raise httpx.ConnectError("kapalı", request=req)
        return httpx.Response(200, json=payload, request=req)

    return get


def test_discover_filters_opencode_through_cli(monkeypatch):
    monkeypatch.setattr(httpx, "get", _get({"data": OPENCODE}))
    assert cli._discover_models("https://opencode.ai/inference/openai/v1") == [
        "deepseek-v4-pro",
        "glm-5.3",
    ]


def test_discover_falls_back_to_preset_for_anthropic_when_models_endpoint_fails(monkeypatch):
    monkeypatch.setattr(httpx, "get", _get(fail=True))
    got = cli._discover_models("https://api.anthropic.com/v1/", key="k")
    assert (
        "claude-sonnet-5-5" in got and got == services.PRESET_MODELS["https://api.anthropic.com/v1"]
    )


def test_discover_has_no_preset_for_unknown_services(monkeypatch):
    monkeypatch.setattr(httpx, "get", _get(fail=True))
    assert cli._discover_models("https://bilinmeyen.example/v1") == []
