"""Yürütme aşamaları: durum makinesi, terminal durumlar, onarım bütçesi, ortam hatası ayrımı, geri alma dürüstlüğü."""

import pytest

from usta import bench, phases, verify
from usta.agent import ROLLBACK_NOTE, Agent
from usta.audit import AuditLog
from usta.breaker import CircuitBreaker
from usta.models import ModelResponse, ToolCall
from usta.phases import PhaseTracker
from usta.policy import Decision, Policy
from usta.sandbox import RunResult
from usta.tools import Registry, Tool

FAIL_OUT = "exit_code: 1\nFAIL: test_x\nAssertionError: 1 != 2"
PASS_OUT = "exit_code: 0\nOK"


def drive(tr, *events):
    for kind, data in events:
        tr.observe(kind, data)
    return tr


def call(tool, **args):
    return ("tool_call", {"tool": tool, "args": args})


def result(tool, text):
    return ("tool_result", {"tool": tool, "result": text})


RUN_TEST = call("run", command="python -m unittest -q")


# --- durum makinesi (birim) -------------------------------------------------------------------
def test_happy_path_discover_edit_verify_complete():
    tr = drive(
        PhaseTracker(),
        call("read_file", path="a.py"),
        call("edit_file", path="a.py"),
        RUN_TEST,
        result("run", PASS_OUT),
    )
    assert [t.to for t in tr.transitions] == ["EDIT", "VERIFY"]
    assert tr.finish(answered=True) == "COMPLETE_VERIFIED"
    assert tr.summary()["verify_passes"] == 1 and tr.repairs == 0


def test_text_plan_before_first_edit_adds_a_plan_phase_and_it_can_be_skipped():
    planned = drive(
        PhaseTracker(),
        call("read_file", path="a.py"),
        ("message", {"content": "Plan: önce şunu değiştireceğim"}),
        call("edit_file", path="a.py"),
    )
    assert [t.to for t in planned.transitions] == ["PLAN", "EDIT"]
    skipped = drive(PhaseTracker(), call("edit_file", path="a.py"))
    assert [t.to for t in skipped.transitions] == ["EDIT"]


def test_failed_verification_leads_to_diagnose_then_repair_and_counts_repairs():
    tr = drive(
        PhaseTracker(),
        call("edit_file", path="a.py"),
        RUN_TEST,
        result("run", FAIL_OUT),
        call("read_file", path="a.py"),
        call("edit_file", path="a.py"),
        RUN_TEST,
        result("run", PASS_OUT),
    )
    assert [t.to for t in tr.transitions] == ["EDIT", "VERIFY", "DIAGNOSE", "REPAIR", "VERIFY"]
    assert tr.repairs == 1 and tr.verify_fails == 1 and tr.verify_passes == 1
    assert tr.finish(answered=True) == "COMPLETE_VERIFIED"


def test_non_test_commands_do_not_count_as_verification():
    tr = drive(
        PhaseTracker(),
        call("edit_file", path="a.py"),
        call("run", command="ls -la"),
        result("run", PASS_OUT),
    )
    assert tr.verify_passes == 0 and tr.phase == "EDIT"
    assert tr.finish(answered=True) == "COMPLETE_UNVERIFIED"


@pytest.mark.parametrize(
    ("events", "kw", "expected"),
    [
        ([call("read_file", path="a")], {"answered": True}, "COMPLETE_NO_CHANGE"),
        (
            [call("edit_file", path="a"), RUN_TEST, result("run", FAIL_OUT)],
            {"answered": True},
            "FAILED_VERIFICATION",
        ),
        (
            [
                call("edit_file", path="a"),
                RUN_TEST,
                result("run", PASS_OUT),
                call("edit_file", path="a"),
            ],
            {"answered": True},
            "COMPLETE_UNVERIFIED",
        ),
        ([call("edit_file", path="a")], {"answered": False, "truncated": True}, "EXHAUSTED"),
        ([call("edit_file", path="a")], {"answered": False, "cancelled": True}, "CANCELLED"),
        ([call("edit_file", path="a")], {"answered": False, "error": True}, "ERROR"),
        ([call("edit_file", path="a")], {"answered": False, "blocked": True}, "BLOCKED"),
    ],
)
def test_terminal_states(events, kw, expected):
    tr = drive(PhaseTracker(), *events)
    assert tr.finish(**kw) == expected
    assert tr.terminal in phases.TERMINALS


def test_failed_verification_is_never_reported_as_a_verified_completion():
    tr = drive(PhaseTracker(), call("edit_file", path="a"), ("verification", {"status": "failed"}))
    term = tr.finish(answered=True)
    assert term == "FAILED_VERIFICATION"
    assert term != "COMPLETE_VERIFIED"


def test_same_failure_repeated_is_flagged_and_repair_budget_signal_is_raised():
    tr = PhaseTracker(repair_budget=2)
    drive(tr, call("edit_file", path="a"))
    for _ in range(4):
        drive(tr, RUN_TEST, result("run", FAIL_OUT), call("edit_file", path="a"))
    assert tr.same_failure_repeats >= 2 and "repeated_failure" in tr.signals
    assert (
        tr.repairs > 2
        and "repeated_failure" in tr.summary()["signals"]
        and "repair_budget_exceeded" in tr.signals
    )
    assert tr.stop_reason == ""  # enforce kapalı: yalnız gözlem


def test_breaker_events_drive_phase_and_final_trip_is_blocked():
    tr = drive(
        PhaseTracker(),
        call("edit_file", path="a"),
        ("breaker", {"final": False, "reason": "aynı hata"}),
    )
    assert tr.phase == "DIAGNOSE" and tr.rewinds == 1
    drive(tr, ("breaker", {"final": True, "reason": "döngü"}))
    assert tr.finish(answered=True) == "BLOCKED"


def test_events_after_terminal_are_ignored():
    tr = drive(PhaseTracker(), call("edit_file", path="a"))
    tr.finish(answered=True)
    n = len(tr.transitions)
    drive(tr, RUN_TEST, result("run", FAIL_OUT))
    assert len(tr.transitions) == n and tr.finish(answered=True) == "COMPLETE_UNVERIFIED"


def test_time_in_phase_is_accounted():
    t = [0.0]
    tr = PhaseTracker(clock=lambda: t[0])
    t[0] = 1.0
    drive(tr, call("edit_file", path="a"))
    t[0] = 3.0
    tr.finish(answered=True)
    assert tr.summary()["ms_in"]["DISCOVER"] == 1000 and tr.summary()["ms_in"]["EDIT"] == 2000


# --- ajan entegrasyonu -----------------------------------------------------------------------
class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)

    def chat(self, messages, tools=None):
        return self.responses.pop(0) if self.responses else ModelResponse("bitti")


def tc(i, name, **args):
    return ModelResponse(None, [ToolCall(f"c{i}", name, args)])


def make_agent(
    tmp_path, model, *, run_output, tracker, breaker=None, verifier=None, events=None, max_steps=30
):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)

    def write(a):
        (ws / a["path"]).write_text(a["content"])
        return "yazıldı"

    outputs = run_output if isinstance(run_output, list) else [run_output]
    tools = Registry(
        [
            Tool("write_file", "w", {"type": "object"}, write),
            Tool("read_file", "r", {"type": "object"}, lambda a: (ws / a["path"]).read_text()),
            Tool(
                "run",
                "x",
                {"type": "object"},
                lambda a: outputs.pop(0) if len(outputs) > 1 else outputs[0],
            ),
        ]
    )
    return Agent(
        model, tools, Policy(ws), AuditLog(tmp_path / "audit.jsonl"), approver=lambda *_: False,
        max_steps=max_steps, on_event=(lambda k, d: events.append(k)) if events is not None else None,
        phases=tracker, breaker=breaker, verifier=verifier,
    )  # fmt: skip


def test_agent_reports_terminal_state_logs_phases_but_keeps_event_stream_unchanged(tmp_path):
    events: list[str] = []
    model = Scripted(
        tc(1, "write_file", path="a.py", content="x=1"),
        tc(2, "run", command="python -m unittest -q"),
        ModelResponse("tamam"),
    )
    agent = make_agent(tmp_path, model, run_output=PASS_OUT, tracker=PhaseTracker(), events=events)
    res = agent.run("görev")
    assert res.terminal == "COMPLETE_VERIFIED"
    assert "phase" not in events and "terminal" not in events  # SSE/olay sözleşmesi değişmedi
    rows = [
        r["event"]
        for r in (tmp_path / "audit.jsonl").read_text().splitlines()
        and [
            __import__("json").loads(line)
            for line in (tmp_path / "audit.jsonl").read_text().splitlines()
        ]
    ]
    assert "phase" in rows and rows[-1] == "terminal"


def test_agent_without_tracker_behaves_as_before(tmp_path):
    agent = make_agent(tmp_path, Scripted(ModelResponse("selam")), run_output="", tracker=None)
    res = agent.run("x")
    assert res.terminal == "" and res.answer == "selam"


def test_model_error_marks_error_terminal_and_reraises(tmp_path):
    from usta.models import ModelError

    class Boom:
        def chat(self, m, t=None):
            raise ModelError("kapalı", infra=True)

    tr = PhaseTracker()
    agent = make_agent(tmp_path, Boom(), run_output="", tracker=tr)
    with pytest.raises(ModelError):
        agent.run("x")
    assert tr.terminal == "ERROR"


def fixing_model(n):
    """Her turda farklı bir 'düzeltme' yazıp testi koşan, hiç düzelmeyen model."""
    steps = []
    for i in range(n):
        steps += [
            tc(10 + 2 * i, "write_file", path="a.py", content=f"x={i}"),
            tc(11 + 2 * i, "run", command="python -m unittest -q"),
        ]
    return Scripted(*steps, ModelResponse("düzelttim"))


def test_without_enforcement_runs_to_the_step_limit_but_flags_the_repair_budget(tmp_path):
    tr = PhaseTracker(repair_budget=2)
    agent = make_agent(tmp_path, fixing_model(20), run_output=FAIL_OUT, tracker=tr, max_steps=12)
    res = agent.run("düzelt")
    assert res.truncated and res.terminal == "EXHAUSTED"
    assert "repair_budget_exceeded" in tr.signals and tr.repairs > 2


def test_enforced_repair_budget_stops_with_an_explainable_terminal_state(tmp_path):
    tr = PhaseTracker(repair_budget=2, enforce=True)
    agent = make_agent(tmp_path, fixing_model(20), run_output=FAIL_OUT, tracker=tr, max_steps=30)
    res = agent.run("düzelt")
    assert res.blocked and not res.truncated and res.steps < 30  # sonsuz döngü yok
    assert "onarım bütçesi doldu" in res.answer and res.terminal == "EXHAUSTED"
    assert tr.repairs == 3


def test_circuit_breaker_ends_repeated_failures_without_infinite_loop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    tr = PhaseTracker()
    # aynı yanlış düzeltme aynı hatayı tekrar tekrar üretir → devre kesici
    steps = []
    for i in range(30):
        steps += [
            tc(100 + 2 * i, "write_file", path="a.py", content="x=1"),
            tc(101 + 2 * i, "run", command="python -m unittest -q"),
        ]
    agent = make_agent(
        tmp_path,
        Scripted(*steps),
        run_output=FAIL_OUT,
        tracker=tr,
        breaker=CircuitBreaker(ws),
        max_steps=60,
    )
    res = agent.run("düzelt")
    assert res.blocked and res.steps < 60
    assert res.terminal == "BLOCKED" and "Denenenler" in res.answer
    assert ROLLBACK_NOTE in res.answer  # geri alma yalnız dosyaları kapsar, dış etkileri değil


def test_repair_phase_does_not_widen_permissions(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    pol = Policy(ws)
    before = (
        pol.check("write_file", {"path": ".git/hooks/x"}),
        pol.check("fetch_url", {"url": "http://evil.test/"}),
        dict(vars(pol)),
    )
    tr = PhaseTracker()
    agent = make_agent(tmp_path, fixing_model(4), run_output=FAIL_OUT, tracker=tr, max_steps=12)
    agent.policy = pol
    agent.run("düzelt")
    assert tr.phase == "REPAIR" or tr.repairs >= 1
    after = (
        pol.check("write_file", {"path": ".git/hooks/x"}),
        pol.check("fetch_url", {"url": "http://evil.test/"}),
        dict(vars(pol)),
    )
    assert before == after and before[0] is Decision.DENY and before[1] is Decision.ASK


def test_rollback_note_is_in_the_non_final_trip_message_too(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    agent = make_agent(
        tmp_path, Scripted(), run_output="", tracker=None, breaker=CircuitBreaker(ws)
    )
    msgs = []
    trip = type("T", (), {"reason": "aynı hata", "final": False, "tried": ["a"]})()
    agent.breaker.start()
    assert agent._handle_trip(trip, msgs, 1) is None
    assert ROLLBACK_NOTE in msgs[-1].content and "dosyaları" in msgs[-1].content


# --- doğrulama ortamı hatası ≠ kod hatası ----------------------------------------------------
@pytest.mark.parametrize(
    ("out", "expected"),
    [
        ("ModuleNotFoundError: No module named 'pytest'", "eksik bağımlılık: pytest"),
        ("ImportError: No module named numpy", "eksik bağımlılık: numpy"),
        ("sh: 1: cargo: not found", "eksik komut: cargo"),
        ("FileNotFoundError: [Errno 2] No such file or directory: 'data.txt'", None),
        ("AssertionError: 1 != 2", None),
    ],
)
def test_env_problem_detection(out, expected, tmp_path):
    assert verify.env_problem(out, tmp_path) == expected


def test_projects_own_missing_module_is_a_code_error_not_an_env_problem(tmp_path):
    (tmp_path / "shop").mkdir()
    assert verify.env_problem("ModuleNotFoundError: No module named 'shop.cart'", tmp_path) is None
    (tmp_path / "util.py").write_text("")
    assert verify.env_problem("ModuleNotFoundError: No module named 'util'", tmp_path) is None


def fake_run(out, code=1):
    return lambda cfg, cmd, cancel=None: RunResult(code, "", out)


def test_gate_reports_env_error_without_burning_repair_budget(tmp_path):
    (tmp_path / "test_a.py").write_text("")
    gate = verify.CompletionGate(
        tmp_path, run=fake_run("ModuleNotFoundError: No module named 'numpy'")
    )
    r = gate.check()
    assert r.status == "env_error" and "numpy" in r.reason and gate.failures == 0 and not r.give_up
    iv = verify.Verifier(gate).on_finish()
    assert (
        iv.done
        and iv.status == "env_error"
        and "kod hatası değil" in iv.note
        and "numpy" in iv.note
    )


def test_code_failure_still_counts_and_retries(tmp_path):
    (tmp_path / "test_a.py").write_text("")
    gate = verify.CompletionGate(tmp_path, run=fake_run("AssertionError: 1 != 2"))
    assert gate.check().status == "failed" and gate.failures == 1


def test_bench_treats_hidden_check_env_errors_as_infra_not_model_failure(monkeypatch):
    task = bench.load_tasks()[0]
    monkeypatch.setattr(
        bench,
        "verify",
        lambda t, ws, timeout=60.0: (False, "ModuleNotFoundError: No module named 'numpy'"),
    )
    r = bench.run_task(task, Scripted(ModelResponse("yaptım")), infra_retries=0)
    assert r.outcome == "infra" and "numpy" in r.error and r.failure == "INFRA_ERROR"


def test_bench_records_terminal_state_and_phase_steps(monkeypatch):
    task = bench.load_tasks()[0]
    monkeypatch.setattr(bench, "verify", lambda t, ws, timeout=60.0: (False, "FAIL"))
    r = bench.run_task(task, Scripted(ModelResponse("hiçbir şey yapmadım")))
    assert r.terminal == "COMPLETE_NO_CHANGE" and isinstance(r.phase_steps, dict)
