import pytest

from fake_endpoint import text_reply, tool_reply
from usta.models import Message, ModelError, OpenAICompatClient, ToolCall

TOOLS = [{"name": "read_file", "description": "oku", "parameters": {"type": "object"}}]


def client(ep, **kw):
    return OpenAICompatClient(base_url=ep.url, model="m", **kw)


def test_text_reply(endpoint):
    endpoint.responses = [text_reply("selam")]
    r = client(endpoint).chat([Message("user", "merhaba")])
    assert r.content == "selam"
    assert r.tool_calls == []
    sent = endpoint.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["model"] == "m"
    assert sent["body"]["messages"] == [{"role": "user", "content": "merhaba"}]
    assert "tools" not in sent["body"]


def test_tools_are_sent_in_openai_format_and_calls_parsed(endpoint):
    endpoint.responses = [tool_reply("read_file", {"path": "a.txt"}, "k9")]
    r = client(endpoint).chat([Message("user", "x")], tools=TOOLS)
    assert endpoint.requests[0]["body"]["tools"] == [{"type": "function", "function": TOOLS[0]}]
    assert r.tool_calls == [ToolCall("k9", "read_file", {"path": "a.txt"})]


def test_tool_result_and_assistant_call_roundtrip(endpoint):
    endpoint.responses = [text_reply("tamam")]
    msgs = [
        Message("assistant", None, tool_calls=[ToolCall("k9", "read_file", {"path": "a"})]),
        Message("tool", "içerik", tool_call_id="k9"),
    ]
    client(endpoint).chat(msgs)
    wire = endpoint.requests[0]["body"]["messages"]
    assert wire[0]["tool_calls"][0]["function"] == {
        "name": "read_file",
        "arguments": '{"path": "a"}',
    }
    assert wire[1] == {"role": "tool", "content": "içerik", "tool_call_id": "k9"}


def test_api_key_header(endpoint):
    endpoint.responses = [text_reply("a")]
    client(endpoint, api_key="gizli-test").chat([Message("user", "x")])
    assert endpoint.headers[0]["Authorization"] == "Bearer gizli-test"


def test_http_error_raises(endpoint):
    endpoint.status = 500
    endpoint.responses = [{"error": "bozuk"}]
    with pytest.raises(ModelError):
        client(endpoint).chat([Message("user", "x")])


def test_malformed_tool_arguments_raise(endpoint):
    bad = tool_reply("read_file", {})
    bad["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{bozuk"
    endpoint.responses = [bad]
    with pytest.raises(ModelError):
        client(endpoint).chat([Message("user", "x")])


# --- hata sınıfı ve kullanım sayacı (ölçüm için) ---------------------------------------------
def test_http_and_connection_errors_are_infra(endpoint):
    endpoint.responses = []  # sahte uç nokta 500 döner
    with pytest.raises(ModelError) as e:
        client(endpoint).chat([Message("user", "x")])
    assert e.value.infra is True
    with pytest.raises(ModelError) as e2:
        OpenAICompatClient("http://127.0.0.1:1/v1", "m", timeout=2).chat([Message("user", "x")])
    assert e2.value.infra is True


def test_malformed_tool_arguments_are_model_errors_not_infra(endpoint):
    bad = tool_reply("read_file", {"path": "a"})
    bad["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{bozuk"
    endpoint.responses = [bad]
    with pytest.raises(ModelError) as e:
        client(endpoint).chat([Message("user", "x")])
    assert e.value.infra is False


def test_usage_is_accumulated_from_response(endpoint):
    r1 = text_reply("a")
    r1["usage"] = {"prompt_tokens": 100, "completion_tokens": 7}
    r2 = text_reply("b")
    r2["usage"] = {"prompt_tokens": 50, "completion_tokens": 3}
    endpoint.responses = [r1, r2]
    c = client(endpoint)
    c.chat([Message("user", "x")])
    c.chat([Message("user", "y")])
    assert (c.usage.prompt, c.usage.completion, c.usage.requests) == (150, 10, 2)


def test_missing_usage_counts_requests_only(endpoint):
    endpoint.responses = [text_reply("a")]
    c = client(endpoint)
    c.chat([Message("user", "x")])
    assert (c.usage.prompt, c.usage.completion, c.usage.requests) == (0, 0, 1)


def test_text_protocol_client_exposes_inner_usage(endpoint):
    from usta.textproto import TextProtocolClient

    r = text_reply('{"final": "tamam"}')
    r["usage"] = {"prompt_tokens": 9, "completion_tokens": 2}
    endpoint.responses = [r]
    t = TextProtocolClient(client(endpoint))
    try:
        t.chat([Message("user", "x")], TOOLS)
    except ModelError:
        pass  # biçim önemli değil, sayaç sayılır
    assert t.usage.prompt == 9


def test_usage_tracks_last_request_for_context_size(endpoint):
    r1 = text_reply("a")
    r1["usage"] = {"prompt_tokens": 100, "completion_tokens": 7}
    r2 = text_reply("b")
    r2["usage"] = {"prompt_tokens": 180, "completion_tokens": 3}
    endpoint.responses = [r1, r2]
    c = client(endpoint)
    c.chat([Message("user", "x")])
    c.chat([Message("user", "y")])
    assert c.usage.last_prompt == 180 and c.usage.prompt == 280


# --- araç çağrısı kurtarma (içerikte JSON) ------------------------------------------------
def content_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def test_json_call_in_content_is_rescued_when_tools_given(endpoint):
    endpoint.responses = [
        content_reply('```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```')
    ]
    c = client(endpoint)
    r = c.chat([Message("user", "x")], tools=TOOLS)
    assert r.content is None and [(t.name, t.arguments) for t in r.tool_calls] == [
        ("read_file", {"path": "a.txt"})
    ]
    assert c.usage.rescued == 1


def test_rescued_call_ids_are_unique_across_requests(endpoint):
    call = '{"name": "read_file", "arguments": {"path": "a.txt"}}'
    endpoint.responses = [content_reply(call), content_reply(call)]
    c = client(endpoint)
    a = c.chat([Message("user", "x")], tools=TOOLS).tool_calls[0].id
    b = c.chat([Message("user", "y")], tools=TOOLS).tool_calls[0].id
    assert a != b


def test_rescue_off_or_no_tools_or_prose_leaves_content_alone(endpoint):
    call = '{"name": "read_file", "arguments": {"path": "a.txt"}}'
    endpoint.responses = [content_reply(call), content_reply(call), content_reply("normal yanıt")]
    assert client(endpoint, rescue=False).chat([Message("user", "x")], tools=TOOLS).content == call
    assert client(endpoint).chat([Message("user", "x")]).content == call  # araç verilmedi
    r = client(endpoint).chat([Message("user", "x")], tools=TOOLS)
    assert r.content == "normal yanıt" and r.tool_calls == []


def test_real_tool_calls_take_precedence_over_rescue(endpoint):
    endpoint.responses = [tool_reply("read_file", {"path": "gercek.txt"})]
    c = client(endpoint)
    r = c.chat([Message("user", "x")], tools=TOOLS)
    assert r.tool_calls[0].arguments == {"path": "gercek.txt"} and c.usage.rescued == 0


# --- ek gövde alanları (ör. düşünmeyi kapatma) -------------------------------------------------
def test_extra_body_is_merged_but_cannot_override_core_fields(endpoint):
    endpoint.responses = [text_reply("ok")]
    c = client(
        endpoint,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False},
            "model": "kotu",
            "messages": [],
            "tools": [],
        },
    )
    c.chat([Message("user", "x")], tools=TOOLS)
    body = endpoint.requests[0]["body"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert (
        body["model"] == "m"
        and body["messages"][0]["content"] == "x"
        and body["tools"][0]["function"]["name"] == "read_file"
    )


def test_no_extra_body_by_default(endpoint):
    endpoint.responses = [text_reply("ok")]
    client(endpoint).chat([Message("user", "x")])
    assert set(endpoint.requests[0]["body"]) == {"model", "messages"}


def test_chat_extra_merges_per_call_but_never_overrides_core(endpoint):
    endpoint.responses = [text_reply("ok")]
    client(endpoint).chat(
        [Message("user", "x")],
        None,
        extra={"response_format": {"type": "json_object"}, "model": "kotu"},
    )
    body = endpoint.requests[0]["body"]
    assert body["response_format"] == {"type": "json_object"} and body["model"] == "m"


def test_transient_connect_errors_are_retried(monkeypatch):
    import httpx

    from usta import models

    calls = []

    def flaky(url, **kw):
        calls.append(url)
        if len(calls) < 3:
            raise httpx.ConnectTimeout("t")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "tamam"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", flaky)
    c = models.OpenAICompatClient("http://x/v1", "m")
    c.sleep = lambda s: None
    assert c.chat([models.Message("user", "a")]).content == "tamam" and len(calls) == 3


def test_retry_gives_up_and_503_retried_but_400_not(monkeypatch):
    import httpx
    import pytest

    from usta import models

    seq = []

    def always_503(url, **kw):
        seq.append(503)
        return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", always_503)
    c = models.OpenAICompatClient("http://x/v1", "m")
    c.sleep = lambda s: None
    with pytest.raises(models.ModelError):
        c.chat([models.Message("user", "a")])
    assert len(seq) == 3

    seq.clear()
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: (
            seq.append(400) or httpx.Response(400, request=httpx.Request("POST", url))
        ),
    )
    with pytest.raises(models.ModelError):
        c.chat([models.Message("user", "a")])
    assert len(seq) == 1


def test_cached_tokens_are_counted_from_deepseek_and_openai_shapes(monkeypatch):
    import httpx

    from usta import models

    def reply(extra):
        return lambda url, **kw: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 5, **extra},
            },
            request=httpx.Request("POST", url),
        )

    c = models.OpenAICompatClient("http://x/v1", "m")
    monkeypatch.setattr(httpx, "post", reply({"prompt_cache_hit_tokens": 80}))
    c.chat([models.Message("user", "a")])
    monkeypatch.setattr(httpx, "post", reply({"prompt_tokens_details": {"cached_tokens": 10}}))
    c.chat([models.Message("user", "a")])
    assert c.usage.cached == 90 and c.usage.prompt == 200
