from usta import verify
from usta.sandbox import RunResult


# --- sözdizimi geri bildirimi ----------------------------------------------------------------
def test_syntax_check_python_ok_and_error():
    assert verify.syntax_check("a.py", "x = 1\n") is None
    msg = verify.syntax_check("a.py", "def f(:\n    pass\n")
    assert msg and "satır 1" in msg and "a.py" in msg


def test_syntax_check_ignores_non_python_and_huge_input():
    assert verify.syntax_check("a.txt", "def f(:") is None
    assert verify.syntax_check("a.py", "x=1\n" * 400_000) is None  # çok büyük: atla


def test_syntax_check_does_not_execute_code(tmp_path):
    marker = tmp_path / "isaret"
    code = f"open({str(marker)!r}, 'w').write('x')\n"
    assert verify.syntax_check("a.py", code) is None
    assert not marker.exists()


# --- test komutu keşfi -----------------------------------------------------------------------
def test_detect_command_python_tests(tmp_path):
    assert verify.detect_test_command(tmp_path) is None
    (tmp_path / "mod.py").write_text("x=1\n")
    assert verify.detect_test_command(tmp_path) is None
    (tmp_path / "test_mod.py").write_text("import unittest\n")
    assert verify.detect_test_command(tmp_path) == ["python", "-m", "unittest", "discover", "-q"]


def test_detect_command_finds_nested_and_suffix_style(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "mod_test.py").write_text("")
    assert verify.detect_test_command(tmp_path) is not None


def test_detect_command_ignores_vendored_dirs(tmp_path):
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "test_a.py").write_text("")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "test_b.py").write_text("")
    assert verify.detect_test_command(tmp_path) is None


# --- hata özeti ve "aynı hata" imzası -------------------------------------------------------
def test_summarize_keeps_the_tail_and_caps_size():
    out = "satır\n" * 2000 + "AssertionError: beklenen 3\n"
    s = verify.summarize_failure(out, limit=500)
    assert len(s) <= 600 and s.rstrip().endswith("AssertionError: beklenen 3")


def test_signature_ignores_timings_addresses_and_counts():
    a = "Ran 5 tests in 0.002s\nFAILED (failures=2)\n0x7f3a12 obj\n"
    b = "Ran 5 tests in 0.131s\nFAILED (failures=2)\n0x7f99ff obj\n"
    c = "Ran 5 tests in 0.002s\nFAILED (failures=3)\nTypeError: x\n"
    assert verify.failure_signature(a) == verify.failure_signature(b)
    assert verify.failure_signature(a) != verify.failure_signature(c)


# --- kapı -----------------------------------------------------------------------------------
class FakeRun:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, cfg, command, cancel=None, session=None):
        self.calls.append((cfg, command))
        code, out = self.results.pop(0) if self.results else (0, "OK")
        return RunResult(code, out, "")


def gate(tmp_path, *results, **kw):
    (tmp_path / "test_a.py").write_text("import unittest\n")
    return verify.CompletionGate(tmp_path, run=FakeRun(*results), **kw)


def test_gate_pass_returns_evidence(tmp_path):
    g = gate(tmp_path, (0, "Ran 3 tests in 0.01s\n\nOK"))
    r = g.check()
    assert r.status == "passed" and "unittest" in r.command and "OK" in r.output


def test_gate_fail_then_pass_within_budget(tmp_path):
    g = gate(tmp_path, (1, "FAIL: test_x\nAssertionError: 1 != 2"), (0, "OK"), max_rounds=3)
    r1 = g.check()
    assert r1.status == "failed" and "AssertionError" in r1.output and not r1.give_up
    assert g.check().status == "passed"


def test_gate_gives_up_when_budget_exhausted(tmp_path):
    g = gate(tmp_path, (1, "E1"), (1, "E2 farklı"), (1, "E3 başka"), max_rounds=2)
    assert not g.check().give_up
    r = g.check()
    assert r.status == "failed" and r.give_up and "bütçe" in r.reason


def test_gate_gives_up_on_repeated_identical_failure(tmp_path):
    g = gate(
        tmp_path,
        (1, "Ran 3 tests in 0.1s\nTypeError: x"),
        (1, "Ran 3 tests in 0.5s\nTypeError: x"),
        max_rounds=5,
    )
    assert not g.check().give_up
    r = g.check()
    assert r.give_up and "aynı hata" in r.reason


def test_gate_unavailable_without_tests_or_when_zero_tests_ran(tmp_path):
    g = verify.CompletionGate(tmp_path, run=FakeRun())
    assert g.check().status == "unavailable"  # test dosyası yok, komut da çalıştırılmadı
    g2 = gate(tmp_path, (0, "Ran 0 tests in 0.000s\n\nOK"))
    assert g2.check().status == "unavailable"  # keşif hiç test bulamadı


def test_gate_runs_in_networkless_sandbox_on_workspace(tmp_path):
    run = FakeRun((0, "OK"))
    (tmp_path / "test_a.py").write_text("")
    verify.CompletionGate(tmp_path, run=run).check()
    cfg, _ = run.calls[0]
    assert cfg.workdir == tmp_path and cfg.allowed_hosts == () and cfg.timeout <= 120


def test_gate_sandbox_error_is_unavailable_not_crash(tmp_path):
    from usta.sandbox import SandboxError

    def boom(*a, **k):
        raise SandboxError("docker yok")

    (tmp_path / "test_a.py").write_text("")
    r = verify.CompletionGate(tmp_path, run=boom).check()
    assert r.status == "unavailable" and "docker" in r.reason


# --- ajan entegrasyonu ---------------------------------------------------------------------
from usta.agent import Agent
from usta.audit import AuditLog
from usta.models import ModelResponse, ToolCall
from usta.policy import Policy
from usta.tools import ToolContext, build_registry


class Seq:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        return self.responses.pop(0)


def w(path, content, i=1):
    return ModelResponse(
        None, [ToolCall(f"w{i}", "write_file", {"path": path, "content": content})]
    )


def make_agent(tmp_path, model, *results, **gate_kw):
    events = []
    (tmp_path / "test_a.py").write_text("import unittest\n")
    run = FakeRun(*results)
    verifier = verify.Verifier(verify.CompletionGate(tmp_path, run=run, **gate_kw))
    agent = Agent(
        model,
        build_registry(ToolContext(root=tmp_path)),
        Policy(tmp_path),
        AuditLog(tmp_path.parent / f"{tmp_path.name}-audit.jsonl"),
        verifier=verifier,
        on_event=lambda t, d: events.append((t, d)),
        max_steps=12,
    )
    return agent, run, events


def test_syntax_error_is_reported_in_the_write_result_but_file_is_written(tmp_path):
    model = Seq(w("a.py", "def f(:\n"), ModelResponse("bitti"))
    agent, _, _ = make_agent(tmp_path, model, (0, "OK"))
    agent.run("yaz")
    tool_msg = next(m for m in model.seen[1] if m.role == "tool")
    assert "yazıldı" in tool_msg.content and "sözdizimi hatası" in tool_msg.content
    assert (tmp_path / "a.py").read_text() == "def f(:\n"


def test_valid_write_has_no_warning_and_edit_file_is_checked_too(tmp_path):
    (tmp_path / "b.py").write_text("x = 1\n")
    edit = ModelResponse(
        None, [ToolCall("e1", "edit_file", {"path": "b.py", "old": "x = 1", "new": "x = ("})]
    )
    model = Seq(w("a.py", "x = 1\n"), edit, ModelResponse("bitti"))
    agent, _, _ = make_agent(tmp_path, model, (0, "OK"))
    agent.run("yaz")
    results = [m.content for m in model.seen[-1] if m.role == "tool"]
    assert "sözdizimi" not in results[0] and "sözdizimi hatası" in results[1]


def test_gate_passes_final_answer_carries_evidence(tmp_path):
    model = Seq(w("a.py", "x = 1\n"), ModelResponse("düzelttim"))
    agent, run, events = make_agent(tmp_path, model, (0, "Ran 2 tests in 0.1s\n\nOK"))
    r = agent.run("yaz")
    assert r.answer.startswith("düzelttim") and "Doğrulama: geçti" in r.answer
    assert len(run.calls) == 1
    assert [d["status"] for t, d in events if t == "verification"] == ["passed"]


def test_gate_failure_is_fed_back_and_model_can_fix(tmp_path):
    model = Seq(
        w("a.py", "x = 1\n"),
        ModelResponse("bitti"),  # gate: başarısız
        w("a.py", "x = 2\n", 2),
        ModelResponse("şimdi düzeldi"),  # gate: geçti
    )
    agent, run, events = make_agent(
        tmp_path, model, (1, "FAIL: test_x\nAssertionError: 1 != 2"), (0, "OK")
    )
    r = agent.run("yaz")
    assert "Doğrulama: geçti" in r.answer and len(run.calls) == 2
    feedback = [
        m for m in model.seen[2] if m.role == "user" and "Doğrulama başarısız" in (m.content or "")
    ]
    assert feedback and "AssertionError: 1 != 2" in feedback[0].content
    assert [d["status"] for t, d in events if t == "verification"] == ["failed", "passed"]


def test_same_failure_twice_stops_with_honest_report(tmp_path):
    model = Seq(w("a.py", "x = 1\n"), ModelResponse("bitti"), ModelResponse("yine bitti"))
    agent, run, _ = make_agent(tmp_path, model, (1, "TypeError: x"), (1, "TypeError: x"))
    r = agent.run("yaz")
    assert (
        "Doğrulama başarısız" in r.answer and "aynı hata" in r.answer and "TypeError: x" in r.answer
    )
    assert len(run.calls) == 2 and not r.truncated


def test_no_edits_means_no_gate(tmp_path):
    agent, run, events = make_agent(tmp_path, Seq(ModelResponse("sadece cevap")))
    assert agent.run("soru").answer == "sadece cevap"
    assert run.calls == [] and not [e for e in events if e[0] == "verification"]


def test_without_tests_model_is_nudged_once_then_accepted(tmp_path):
    (tmp_path / "test_a.py").unlink(missing_ok=True)
    events = []
    run = FakeRun()
    verifier = verify.Verifier(verify.CompletionGate(tmp_path, run=run))
    model = Seq(w("s.py", "x = 1\n"), ModelResponse("bitti"), ModelResponse("test yazmadan bitti"))
    agent = Agent(
        model,
        build_registry(ToolContext(root=tmp_path)),
        Policy(tmp_path),
        AuditLog(tmp_path.parent / "n-audit.jsonl"),
        verifier=verifier,
        on_event=lambda t, d: events.append((t, d)),
    )
    r = agent.run("yaz")
    nudge = [
        m
        for m in model.seen[2]
        if m.role == "user" and "test" in (m.content or "") and "yaz" in m.content
    ]
    assert nudge, "ilk bitirmede test yazma dürtmesi gelmeli"
    assert "Doğrulama: yapılamadı" in r.answer
    assert (
        sum(
            1
            for m in model.seen[-1]
            if m.role == "user" and "küçük bir unittest" in (m.content or "")
        )
        == 1
    )


def test_cancellation_is_not_blocked_by_gate(tmp_path):
    import threading

    cancel = threading.Event()
    cancel.set()
    agent, run, _ = make_agent(tmp_path, Seq(ModelResponse("x")))
    agent.cancel = cancel
    assert agent.run("yaz").cancelled and run.calls == []


# --- uygulanmamış kod dürtmesi ---------------------------------------------------------------
CODE_ANSWER = "Şöyle yapabilirsin:\n```python\ndef f():\n    return 1\n```"


def test_code_in_answer_without_any_edit_is_nudged_once_then_accepted(tmp_path):
    model = Seq(ModelResponse(CODE_ANSWER), ModelResponse(CODE_ANSWER))
    agent, run, _ = make_agent(tmp_path, model)
    r = agent.run("f fonksiyonunu ekle")
    nudges = [m for m in model.seen[1] if m.role == "user" and "write_file" in (m.content or "")]
    assert len(nudges) == 1 and r.answer == CODE_ANSWER and run.calls == []


def test_nudge_leads_to_applied_edit_then_gate(tmp_path):
    model = Seq(
        ModelResponse(CODE_ANSWER),
        w("f.py", "def f():\n    return 1\n"),
        ModelResponse("uyguladım"),
    )
    agent, _run, events = make_agent(tmp_path, model, (0, "OK"))
    r = agent.run("f ekle")
    assert (tmp_path / "f.py").exists() and "Doğrulama: geçti" in r.answer
    assert [d["status"] for t, d in events if t == "verification"] == ["unapplied", "passed"]


def test_no_nudge_for_plain_answers_or_after_edits(tmp_path):
    model = Seq(ModelResponse("kısa metin yanıt"))
    agent, _, _ = make_agent(tmp_path, model)
    assert agent.run("soru").answer == "kısa metin yanıt" and len(model.seen) == 1
    sub = tmp_path / "b"
    sub.mkdir()
    model2 = Seq(w("a.py", "x = 1\n"), ModelResponse(CODE_ANSWER))
    agent2, _, _ = make_agent(sub, model2, (0, "OK"))
    agent2.run("yaz")
    assert not [
        m for m in model2.seen[-1] if m.role == "user" and "write_file" in (m.content or "")
    ]
