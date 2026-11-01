import pytest

from fake_endpoint import text_reply
from usta.models import Message, ModelError, ModelResponse, OpenAICompatClient, ToolCall
from usta.textproto import ProtocolError, TextProtocolClient, parse_reply

OPEN, CLOSE = "<<<İÇERİK", "İÇERİK>>>"


def test_plain_text_is_final_answer():
    r = parse_reply("Bitti, dosyayı yazdım.")
    assert r.content == "Bitti, dosyayı yazdım." and r.tool_calls == []


def test_json_object_without_tool_key_is_plain_answer():
    assert parse_reply('{"sonuc": 1}').tool_calls == []


def test_simple_call():
    r = parse_reply('{"tool": "read_file", "arguments": {"path": "a.txt"}}')
    assert r.tool_calls == [ToolCall("t1", "read_file", {"path": "a.txt"})]
    assert r.content is None


def test_call_without_arguments():
    assert parse_reply('{"tool": "list_dir"}').tool_calls[0].arguments == {}


def test_content_block_carries_code_without_json_escaping():
    code = 'def f():\n    return "kaçış \\n yok" # {"a": 1}\n'
    text = f'{{"tool": "write_file", "arguments": {{"path": "a.py"}}}}\n{OPEN}\n{code}{CLOSE}'
    call = parse_reply(text).tool_calls[0]
    assert call.arguments == {"path": "a.py", "content": code.rstrip("\n")}


def test_named_blocks_for_edit():
    text = (
        '{"tool": "edit_file", "arguments": {"path": "a"}}\n'
        f"{OPEN} old\nx = 1\n{CLOSE}\n{OPEN} new\nx = 2\n{CLOSE}"
    )
    assert parse_reply(text).tool_calls[0].arguments == {
        "path": "a",
        "old": "x = 1",
        "new": "x = 2",
    }


def test_empty_block_and_closer_text_inside_body_line():
    text = f'{{"tool": "write_file", "arguments": {{"path": "a"}}}}\n{OPEN}\n{CLOSE}'
    assert parse_reply(text).tool_calls[0].arguments["content"] == ""
    text = f'{{"tool": "write_file", "arguments": {{"path": "a"}}}}\n{OPEN}\nsatır {CLOSE} devam\n{CLOSE}'
    assert parse_reply(text).tool_calls[0].arguments["content"] == f"satır {CLOSE} devam"


@pytest.mark.parametrize(
    "bad",
    [
        '{"tool": "write_file", "arguments": {"path": "a"}}\n<<<İÇERİK\nyarım kod',  # kesik blok
        '{"tool": "write_file", "arguments": {"path": "a"',  # kesik JSON
        '{"tool": "read_file", "arguments": [1]}',  # arguments dict değil
        '{"tool": 5}',  # tool str değil
        '{"tool": "write_file", "arguments": {"content": "x"}}\n<<<İÇERİK\ny\nİÇERİK>>>',  # çakışma
        '{"tool": "a"}\n<<<İÇERİK\nx\nİÇERİK>>>\n<<<İÇERİK\ny\nİÇERİK>>>',  # aynı ad iki kez
        '{"tool": "a"}\nfazladan konuşma',  # çağrıdan sonra serbest metin
        "<<<İÇERİK\nçağrısız blok\nİÇERİK>>>",  # çağrısız blok
        '{"tool": "a"} {"tool": "b"}',  # iki çağrı
    ],
)
def test_malformed_replies_are_rejected(bad):
    with pytest.raises(ProtocolError):
        parse_reply(bad)


class Scripted:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.seen = []
        self.tools_seen = []

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        self.tools_seen.append(tools)
        return ModelResponse(self.texts.pop(0))


TOOLS = [{"name": "write_file", "description": "yazar", "parameters": {"type": "object"}}]


def test_client_injects_protocol_and_hides_native_tools():
    inner = Scripted("bitti")
    TextProtocolClient(inner).chat([Message("system", "Sen Usta."), Message("user", "x")], TOOLS)
    sent = inner.seen[0]
    assert inner.tools_seen[0] is None
    assert sent[0].role == "system" and "Sen Usta." in sent[0].content
    assert "write_file" in sent[0].content and OPEN in sent[0].content


def test_client_flattens_history_for_models_without_tool_roles():
    inner = Scripted("ok")
    hist = [
        Message("user", "yaz"),
        Message(
            "assistant", None, [ToolCall("t1", "write_file", {"path": "a", "content": "l1\nl2"})]
        ),
        Message("tool", "yazıldı", tool_call_id="t1"),
    ]
    TextProtocolClient(inner).chat(hist, TOOLS)
    wire = inner.seen[0]
    assert all(m.role in {"system", "user", "assistant"} and not m.tool_calls for m in wire)
    assert OPEN in wire[2].content and "l1\nl2" in wire[2].content  # çok satırlı değer blokta
    assert wire[3].role == "user" and "yazıldı" in wire[3].content
    # geri çevrilince aynı çağrı çıkar
    assert parse_reply(wire[2].content).tool_calls[0].arguments["content"] == "l1\nl2"


def test_client_retries_on_protocol_error_then_succeeds():
    inner = Scripted(
        '{"tool": "write_file", "arguments": {"path": "a"}}\n<<<İÇERİK\nyarım', "tamam"
    )
    r = TextProtocolClient(inner, retries=1).chat([Message("user", "x")], TOOLS)
    assert r.content == "tamam" and len(inner.seen) == 2
    assert "protokol hatası" in inner.seen[1][-1].content


def test_client_gives_up_after_retries():
    inner = Scripted('{"tool": "x"', '{"tool": "x"')
    with pytest.raises(ModelError):
        TextProtocolClient(inner, retries=1).chat([Message("user", "x")], TOOLS)


def test_works_over_http(endpoint):
    endpoint.responses = [text_reply('{"tool": "list_dir", "arguments": {"path": "."}}')]
    client = TextProtocolClient(OpenAICompatClient(endpoint.url, "m"))
    r = client.chat([Message("user", "x")], TOOLS)
    assert r.tool_calls[0].name == "list_dir"
    assert "tools" not in endpoint.requests[0]["body"]
