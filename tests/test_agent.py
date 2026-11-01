import json

import pytest

from fake_endpoint import text_reply, tool_reply
from usta.agent import Agent
from usta.audit import AuditLog
from usta.models import Message, ModelResponse, OpenAICompatClient, ToolCall
from usta.policy import Policy
from usta.tools import ToolContext, build_registry


class ScriptedModel:
    def __init__(self, *responses: ModelResponse):
        self.responses = list(responses)
        self.seen: list[list[Message]] = []

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        return self.responses.pop(0)


def call(name, args, id="c1"):
    return ModelResponse(None, [ToolCall(id, name, args)])


def make(tmp_path, model, **kw):
    reg = build_registry(ToolContext(root=tmp_path))
    audit = AuditLog(tmp_path.parent / f"{tmp_path.name}-audit.jsonl")
    return Agent(model, reg, Policy(tmp_path), audit, **kw), audit


def events(audit):
    return [json.loads(x) for x in audit.path.read_text().splitlines()]


def test_plain_answer(tmp_path):
    agent, _ = make(tmp_path, ScriptedModel(ModelResponse("merhaba")))
    r = agent.run("selam")
    assert r.answer == "merhaba" and r.steps == 1 and not r.truncated


def test_tool_loop_executes_and_feeds_result_back(tmp_path):
    model = ScriptedModel(
        call("write_file", {"path": "a.txt", "content": "x"}), ModelResponse("bitti")
    )
    agent, audit = make(tmp_path, model)
    r = agent.run("yaz")
    assert (tmp_path / "a.txt").read_text() == "x"
    assert r.answer == "bitti" and r.steps == 2
    last = model.seen[1][-1]
    assert last.role == "tool" and last.tool_call_id == "c1" and "yazıldı" in last.content
    assert [e["event"] for e in events(audit)] == ["task", "tool_call", "tool_result", "answer"]


def test_denied_call_is_not_executed_and_model_is_told(tmp_path):
    model = ScriptedModel(call("read_file", {"path": "../gizli"}), ModelResponse("tamam"))
    agent, audit = make(tmp_path, model)
    agent.run("oku")
    assert "reddedildi" in model.seen[1][-1].content
    assert any(e.get("decision") == "deny" for e in events(audit))


def test_ask_without_approver_is_denied(tmp_path):
    model = ScriptedModel(call("web_search", {"query": "x"}), ModelResponse("ok"))
    agent, _ = make(tmp_path, model)
    agent.run("ara")
    assert "reddedildi" in model.seen[1][-1].content


def test_ask_with_approver(tmp_path):
    asked = []
    model = ScriptedModel(call("web_search", {"query": "x"}), ModelResponse("ok"))
    agent, _ = make(tmp_path, model, approver=lambda t, a: asked.append((t, a)) or False)
    agent.run("ara")
    assert asked == [("web_search", {"query": "x"})]
    assert "reddedildi" in model.seen[1][-1].content


def test_tool_error_goes_back_to_model(tmp_path):
    model = ScriptedModel(call("read_file", {"path": "yok.txt"}), ModelResponse("neyse"))
    agent, _ = make(tmp_path, model)
    r = agent.run("oku")
    assert model.seen[1][-1].content.startswith("hata:") and r.answer == "neyse"


def test_step_limit(tmp_path):
    model = ScriptedModel(*[call("list_dir", {"path": "."}, f"c{i}") for i in range(5)])
    agent, _ = make(tmp_path, model, max_steps=3)
    r = agent.run("döngü")
    assert r.truncated and r.steps == 3


def test_end_to_end_over_http(tmp_path, endpoint):
    endpoint.responses = [
        tool_reply("write_file", {"path": "n.txt", "content": "http"}),
        text_reply("yazdım"),
    ]
    model = OpenAICompatClient(endpoint.url, "m")
    agent, _ = make(tmp_path, model)
    assert agent.run("yaz").answer == "yazdım"
    assert (tmp_path / "n.txt").read_text() == "http"
    assert endpoint.requests[1]["body"]["messages"][-1]["role"] == "tool"


def test_system_prompt_is_first_and_tools_offered(tmp_path):
    model = ScriptedModel(ModelResponse("a"))
    agent, _ = make(tmp_path, model)
    agent.run("x")
    assert model.seen[0][0].role == "system" and model.seen[0][-1] == Message("user", "x")


@pytest.mark.parametrize("n", [0, -1])
def test_max_steps_must_be_positive(tmp_path, n):
    with pytest.raises(ValueError):
        make(tmp_path, ScriptedModel(), max_steps=n)


def test_on_event_stream(tmp_path):
    seen = []
    model = ScriptedModel(
        ModelResponse("düşünüyorum", [ToolCall("c1", "list_dir", {"path": "."})]),
        ModelResponse("bitti"),
    )
    agent, _ = make(tmp_path, model, on_event=lambda t, d: seen.append((t, d)))
    agent.run("x")
    assert [t for t, _ in seen] == ["message", "tool_call", "tool_result", "message"]
    assert seen[1][1] == {"tool": "list_dir", "args": {"path": "."}}
    assert seen[3][1] == {"content": "bitti"}


def test_denied_event(tmp_path):
    seen = []
    model = ScriptedModel(call("read_file", {"path": "../x"}), ModelResponse("ok"))
    agent, _ = make(tmp_path, model, on_event=lambda t, d: seen.append(t))
    agent.run("x")
    assert "denied" in seen


def test_cancel_before_start_and_between_steps(tmp_path):
    import threading

    cancel = threading.Event()
    cancel.set()
    agent, _ = make(tmp_path, ScriptedModel(), cancel=cancel)
    r = agent.run("x")
    assert r.cancelled and r.steps == 0

    cancel2 = threading.Event()
    model = ScriptedModel(call("list_dir", {"path": "."}), ModelResponse("asla"))
    agent, _ = make(tmp_path, model, cancel=cancel2)
    agent.on_event = lambda t, d: cancel2.set() if t == "tool_result" else None
    r = agent.run("x")
    assert r.cancelled and len(model.seen) == 1


def test_cancel_skips_remaining_tool_calls(tmp_path):
    import threading

    cancel = threading.Event()
    two = ModelResponse(
        None,
        [
            ToolCall("a", "write_file", {"path": "1", "content": "1"}),
            ToolCall("b", "write_file", {"path": "2", "content": "2"}),
        ],
    )
    agent, _ = make(tmp_path, ScriptedModel(two), cancel=cancel)
    agent.on_event = lambda t, d: cancel.set() if t == "tool_result" else None
    r = agent.run("x")
    assert r.cancelled and (tmp_path / "1").exists() and not (tmp_path / "2").exists()
    # her tool_call'a yanıt verilmeli ki mesaj geçmişi tutarlı kalsın
    assert [m.tool_call_id for m in r.messages if m.role == "tool"] == ["a", "b"]


def test_cancel_during_model_call_discards_even_a_final_answer(tmp_path):
    import threading

    cancel = threading.Event()

    class CancelsWhileThinking:
        def chat(self, messages, tools=None):
            cancel.set()  # model beklenirken kullanıcı durdurdu
            return ModelResponse("geç gelen yanıt")

    agent, _ = make(tmp_path, CancelsWhileThinking(), cancel=cancel)
    r = agent.run("x")
    assert r.cancelled and r.answer == "(görev durduruldu)"
    assert not any(m.content == "geç gelen yanıt" for m in r.messages if m.role == "assistant")


def test_system_prompt_declares_external_content_as_data():
    from usta.agent import SYSTEM_PROMPT

    assert "HARİCİ-İÇERİK" in SYSTEM_PROMPT and "talimat" in SYSTEM_PROMPT


# --- token kullanım olayları ---------------------------------------------------------------
def test_agent_emits_usage_deltas_for_this_run_only(tmp_path):
    from usta.models import Usage

    class Counting:
        usage = Usage(prompt=9000, completion=500, requests=40)  # önceki görevlerden birikmiş

        def __init__(self, *responses):
            self.responses = list(responses)

        def chat(self, messages, tools=None):
            self.usage.prompt += 100 * len(messages)
            self.usage.completion += 10
            self.usage.requests += 1
            self.usage.last_prompt = 100 * len(messages)
            return self.responses.pop(0)

    events = []
    model = Counting(call("list_dir", {"path": "."}), ModelResponse("bitti"))
    agent, _ = make(tmp_path, model, on_event=lambda t, d: events.append((t, d)))
    agent.run("x")
    usage = [d for t, d in events if t == "usage"]
    assert len(usage) == 2
    assert usage[0] == {"prompt": 200, "completion": 10, "requests": 1, "context": 200, "cached": 0}
    assert usage[1]["requests"] == 2 and usage[1]["completion"] == 20
    assert usage[1]["prompt"] == 200 + 400 and usage[1]["context"] == 400


def test_agent_without_usage_support_emits_no_usage_events(tmp_path):
    events = []
    agent, _ = make(
        tmp_path, ScriptedModel(ModelResponse("ok")), on_event=lambda t, d: events.append(t)
    )
    agent.run("x")
    assert "usage" not in events
