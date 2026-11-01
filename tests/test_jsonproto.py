import json

import pytest

from usta.jsonproto import JsonProtocolClient, build_schema
from usta.models import Message, ModelError, ModelResponse, Usage

TOOLS = [
    {
        "name": "read_file",
        "description": "oku",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "yaz",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
]


class Inner:
    def __init__(self, *replies):
        self.replies, self.calls, self.usage = list(replies), [], Usage()

    def chat(self, messages, tools=None, extra=None):
        self.calls.append({"messages": messages, "tools": tools, "extra": extra})
        r = self.replies.pop(0)
        return r if isinstance(r, ModelResponse) else ModelResponse(r)


def reply(**kw):
    return json.dumps(kw, ensure_ascii=False)


def test_schema_locks_tool_names_and_actions():
    s = build_schema(TOOLS)
    assert s["properties"]["action"]["enum"] == ["tool", "final"]
    assert s["properties"]["tool"]["enum"] == ["read_file", "write_file"]
    assert s["required"] == ["action"] and s["additionalProperties"] is False


def test_request_carries_response_format_and_no_native_tools():
    inner = Inner(reply(action="final", message="tamam"))
    JsonProtocolClient(inner).chat([Message("user", "x")], TOOLS)
    call = inner.calls[0]
    assert call["tools"] is None
    rf = call["extra"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"]["properties"]["tool"][
        "enum"
    ] == ["read_file", "write_file"]
    assert "read_file" in call["messages"][0].content  # araç tarifi sistem istemine eklenir


def test_tool_call_with_multiline_content_and_quotes_roundtrips():
    code = 'def f():\n    return "tırnaklı\\n"\n'
    inner = Inner(
        reply(action="tool", tool="write_file", arguments={"path": "a.py", "content": code})
    )
    r = JsonProtocolClient(inner).chat([Message("user", "yaz")], TOOLS)
    assert (
        r.content is None
        and r.tool_calls[0].name == "write_file"
        and r.tool_calls[0].arguments["content"] == code
    )


def test_final_message():
    r = JsonProtocolClient(Inner(reply(action="final", message="bitti"))).chat(
        [Message("user", "x")], TOOLS
    )
    assert r.content == "bitti" and r.tool_calls == []


@pytest.mark.parametrize(
    "bad",
    [
        "düz metin",
        "{bozuk",
        reply(action="tool", tool="yok_arac", arguments={}),
        reply(action="tool", tool="read_file", arguments={}),  # zorunlu argüman eksik
        reply(action="tool", tool="read_file", arguments={"path": 5}),
        reply(action="tool", tool="read_file"),
        reply(action="final"),
        reply(action="sihir"),
        "[1, 2]",
    ],
)
def test_invalid_replies_are_retried_with_feedback_then_fail(bad):
    inner = Inner(bad, bad, bad)
    with pytest.raises(ModelError, match="protokol"):
        JsonProtocolClient(inner, retries=2).chat([Message("user", "x")], TOOLS)
    assert len(inner.calls) == 3
    assert "protokol hatası" in inner.calls[1]["messages"][-1].content


def test_retry_recovers_after_one_bad_reply():
    inner = Inner("bozuk", reply(action="tool", tool="read_file", arguments={"path": "a"}))
    r = JsonProtocolClient(inner).chat([Message("user", "x")], TOOLS)
    assert r.tool_calls[0].arguments == {"path": "a"} and len(inner.calls) == 2


def test_history_is_flattened_assistant_json_and_user_tool_results():
    from usta.models import ToolCall

    inner = Inner(reply(action="final", message="ok"))
    history = [
        Message("system", "sistem"),
        Message("user", "görev"),
        Message("assistant", None, [ToolCall("c1", "read_file", {"path": "a"})]),
        Message("tool", "içerik", tool_call_id="c1"),
    ]
    JsonProtocolClient(inner).chat(history, TOOLS)
    sent = inner.calls[0]["messages"]
    assert [m.role for m in sent] == ["system", "user", "assistant", "user"]
    assert json.loads(sent[2].content) == {
        "action": "tool",
        "tool": "read_file",
        "arguments": {"path": "a"},
    }
    assert "araç sonucu (read_file)" in sent[3].content and "içerik" in sent[3].content


def test_usage_passthrough_and_ids_unique():
    inner = Inner(
        reply(action="tool", tool="read_file", arguments={"path": "a"}),
        reply(action="tool", tool="read_file", arguments={"path": "b"}),
    )
    c = JsonProtocolClient(inner)
    a = c.chat([Message("user", "x")], TOOLS).tool_calls[0].id
    b = c.chat([Message("user", "y")], TOOLS).tool_calls[0].id
    assert a != b and c.usage is inner.usage


def test_no_tools_still_answers_as_final_text():
    inner = Inner(reply(action="final", message="sohbet"))
    r = JsonProtocolClient(inner).chat([Message("user", "x")], None)
    assert r.content == "sohbet"
