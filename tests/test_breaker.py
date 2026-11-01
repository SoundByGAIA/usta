import pytest

from usta.agent import Agent
from usta.audit import AuditLog
from usta.breaker import CircuitBreaker
from usta.models import ModelResponse, ToolCall
from usta.policy import Policy
from usta.tools import ToolContext, build_registry

FAIL = 'exit_code: 1\nTraceback (most recent call last):\n  File "t.py", line 3\nAssertionError: 1 != 2\n'
FAIL_OTHER = "exit_code: 1\nTypeError: x\n"


def br(tmp_path, **kw):
    b = CircuitBreaker(tmp_path, **kw)
    b.start()
    return b


def edit(path, content):
    return ("write_file", {"path": path, "content": content}, f"yazıldı: {path}")


def run(cmd, out):
    return ("run", {"command": cmd}, out)


def feed(b, *events):
    trips = []
    for tool, args, result in events:
        if tool == "write_file":
            (b.root / args["path"]).write_text(args["content"])
        trips.append(b.observe(tool, args, result))
    return trips


def test_different_failures_do_not_trip(tmp_path):
    b = br(tmp_path)
    trips = feed(
        b,
        edit("a.py", "1"),
        run("python t.py", FAIL),
        edit("a.py", "2"),
        run("python t.py", FAIL_OTHER),
    )
    assert trips == [None] * 4


def test_same_failure_after_an_edit_trips(tmp_path):
    b = br(tmp_path)
    trips = feed(b, edit("a.py", "1"), run("t", FAIL), edit("a.py", "2"), run("t", FAIL))
    assert trips[:3] == [None] * 3 and trips[3] is not None
    assert "aynı hata" in trips[3].reason and not trips[3].final


def test_rerunning_without_edit_is_not_counted_as_failed_fix(tmp_path):
    b = br(tmp_path)
    trips = feed(b, edit("a.py", "1"), run("t", FAIL), run("t", FAIL))
    assert trips == [None] * 3  # düzeltme denenmedi; yalnız yeniden çalıştırıldı


def test_success_clears_failure_memory(tmp_path):
    b = br(tmp_path)
    trips = feed(
        b,
        edit("a.py", "1"),
        run("t", FAIL),
        edit("a.py", "2"),
        run("t", "exit_code: 0\nOK"),
        edit("a.py", "3"),
        run("t", FAIL),
    )
    assert trips == [None] * 6


def test_revisiting_an_earlier_file_state_trips_as_oscillation(tmp_path):
    b = br(tmp_path)
    trips = feed(b, edit("a.py", "A"), edit("a.py", "B"), edit("a.py", "A"))
    assert trips[:2] == [None, None] and trips[2] is not None and "geri dön" in trips[2].reason


def test_identical_call_and_result_three_times_trips(tmp_path):
    b = br(tmp_path)
    call = ("list_dir", {"path": "."}, "a.py")
    trips = feed(b, call, call, call)
    assert trips[:2] == [None, None] and trips[2] is not None and "tekrar" in trips[2].reason


def test_trip_rewinds_workspace_to_last_checkpoint_and_lists_attempts(tmp_path):
    (tmp_path / "keep.txt").write_text("ilk\n")
    b = br(tmp_path)
    (tmp_path / "keep.txt").write_text("bozuldu\n")
    trips = feed(b, edit("a.py", "1"), run("t", FAIL), edit("a.py", "2"), run("t", FAIL))
    t = trips[-1]
    assert t is not None
    b.rewind()
    assert (tmp_path / "keep.txt").read_text() == "ilk\n" and not (tmp_path / "a.py").exists()
    assert any("a.py" in x for x in t.tried) and any("t" in x for x in t.tried)


def test_checkpoint_after_verified_good_state_is_the_rewind_target(tmp_path):
    b = br(tmp_path)
    feed(b, edit("a.py", "iyi"))
    b.checkpoint()
    feed(b, edit("a.py", "kötü"), run("t", FAIL), edit("a.py", "kötü2"), run("t", FAIL))
    b.rewind()
    assert (tmp_path / "a.py").read_text() == "iyi"


def test_second_trip_is_final_by_default(tmp_path):
    b = br(tmp_path, max_trips=1)
    t1 = feed(b, edit("a.py", "1"), run("t", FAIL), edit("a.py", "2"), run("t", FAIL))[-1]
    assert t1 is not None and not t1.final
    b.rewind()
    t2 = feed(b, edit("a.py", "3"), run("t", FAIL_OTHER), edit("a.py", "4"), run("t", FAIL_OTHER))[
        -1
    ]
    assert t2 is not None and t2.final


def test_tried_list_is_bounded(tmp_path):
    b = br(tmp_path)
    for i in range(40):
        feed(b, edit(f"f{i}.py", str(i)))
    t = feed(b, run("t", FAIL), edit("z.py", "1"), run("t", FAIL))[-1]
    assert t is not None and len(t.tried) <= 8


# --- ajan entegrasyonu ---------------------------------------------------------------------
class Seq:
    def __init__(self, *r):
        self.r, self.seen = list(r), []

    def chat(self, messages, tools=None):
        self.seen.append(list(messages))
        return self.r.pop(0) if self.r else ModelResponse("bitti")


def w(path, content, i):
    return ModelResponse(
        None, [ToolCall(f"w{i}", "write_file", {"path": path, "content": content})]
    )


def sh(cmd, i):
    return ModelResponse(None, [ToolCall(f"s{i}", "run", {"command": cmd})])


def agent(tmp_path, model, events, **kw):
    return Agent(
        model,
        build_registry(ToolContext(root=tmp_path)),
        Policy(tmp_path),
        AuditLog(tmp_path.parent / f"{tmp_path.name}-br.jsonl"),
        breaker=CircuitBreaker(tmp_path, **kw),
        on_event=lambda t, d: events.append((t, d)),
        max_steps=20,
    )


@pytest.fixture
def docker_free(monkeypatch):
    """Ajan testlerinde `run` aracını sahte çıktıyla değiştir (sandbox gerekmez)."""
    from usta import tools

    state = {"out": FAIL}

    class R:
        def __init__(self, out):
            self.exit_code = 0 if out.startswith("exit_code: 0") else 1
            self.stdout, self.stderr = out.split("\n", 1)[1] if "\n" in out else "", ""
            self.timed_out = self.cancelled = False
            self.network_log = ()

    monkeypatch.setattr(
        tools, "run_command", lambda cfg, cmd, cancel=None, session=None: R(state["out"])
    )
    return state


def test_agent_rewinds_and_tells_model_what_failed(tmp_path, docker_free):
    (tmp_path / "base.txt").write_text("temiz\n")
    events = []
    model = Seq(
        w("a.py", "1", 1), sh("t", 1), w("a.py", "2", 2), sh("t", 2), ModelResponse("yeni yaklaşım")
    )
    a = agent(tmp_path, model, events)
    r = a.run("düzelt")
    assert [t for t, _ in events].count("breaker") == 1
    assert not (tmp_path / "a.py").exists()  # geri sarıldı
    msg = next(
        m for m in model.seen[-1] if m.role == "user" and "Devre kesici" in (m.content or "")
    )
    assert (
        "Denenenler" in msg.content
        and "a.py" in msg.content
        and "tekrarlama" in msg.content.lower()
    )
    assert r.answer == "yeni yaklaşım" and not getattr(r, "blocked", False)


def test_agent_stops_and_hands_over_on_final_trip(tmp_path, docker_free):
    events = []
    model = Seq(
        w("a.py", "1", 1), sh("t", 1), w("a.py", "2", 2), sh("t", 2),  # 1. kesilme
        w("b.py", "3", 3), sh("t", 3), w("b.py", "4", 4), sh("t", 4),  # 2. kesilme: son
        ModelResponse("buraya gelmemeli"),
    )  # fmt: skip
    r = agent(tmp_path, model, events, max_trips=1).run("düzelt")
    assert getattr(r, "blocked", False) is True
    assert "Durdum" in r.answer and "kullanıcı" in r.answer.lower()
    assert [d.get("final") for t, d in events if t == "breaker"] == [False, True]
    assert model.r == [ModelResponse("buraya gelmemeli")]  # son yanıta hiç gidilmedi


def test_agent_without_loops_is_untouched(tmp_path, docker_free):
    docker_free["out"] = "exit_code: 0\nOK"
    events = []
    model = Seq(w("a.py", "1", 1), sh("t", 1), ModelResponse("tamam"))
    r = agent(tmp_path, model, events).run("yaz")
    assert r.answer == "tamam" and "breaker" not in [t for t, _ in events]
    assert (tmp_path / "a.py").exists()
