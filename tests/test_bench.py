import json
import shutil
import subprocess
from pathlib import Path

import pytest

from usta import bench
from usta.models import ModelResponse, ToolCall

SOL = Path(__file__).parent / "bench_solutions"
TASKS = bench.load_tasks()

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


def test_tasks_are_well_formed():
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids)) >= 5
    for t in TASKS:
        assert t.prompt.strip() and t.repo.is_dir() and t.check.is_dir()
        assert t.check_cmd and all(isinstance(c, str) for c in t.check_cmd)
        assert any(t.check.iterdir()), "doğrulama dosyası olmalı"
        assert (SOL / t.id).is_dir(), "her görevin çözümlü referansı olmalı"


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)

    def chat(self, messages, tools=None):
        return self.responses.pop(0) if self.responses else ModelResponse("bitti")


def write(path, content, i=1):
    return ModelResponse(
        None, [ToolCall(f"c{i}", "write_file", {"path": path, "content": content})]
    )


def solution_calls(task_id):
    calls = [
        write(p.name, p.read_text(), i)
        for i, p in enumerate(sorted((SOL / task_id).iterdir()), 1)
        if not p.name.startswith("test_")
    ]
    return [*calls, ModelResponse("düzelttim")]


def by_id(task_id):
    return next(t for t in TASKS if t.id == task_id)


# --- görevlerin geçerliliği: çözülmemiş KALIR, referans çözümle GEÇER (gerçek sandbox) --------
@needs_docker
@pytest.mark.docker
@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_task_fails_unsolved_and_passes_with_reference_solution(task, tmp_path):
    unsolved = tmp_path / "a"
    shutil.copytree(task.repo, unsolved)
    ok, _ = bench.verify(task, unsolved)
    assert not ok, "çözülmemiş görev doğrulamayı geçmemeli"
    solved = tmp_path / "b"
    shutil.copytree(task.repo, solved)
    for f in (SOL / task.id).iterdir():
        if not f.name.startswith("test_"):
            shutil.copy(f, solved / f.name)
    ok, out = bench.verify(task, solved)
    assert ok, out


# --- çalıştırıcı ---------------------------------------------------------------------------
@needs_docker
@pytest.mark.docker
def test_run_task_solved_counts_steps_and_calls():
    r = bench.run_task(by_id("off-by-one"), Scripted(*solution_calls("off-by-one")))
    assert r.passed and r.error == "" and r.tool_calls == 1 and r.tool_errors == 0
    assert r.steps == 2 and r.seconds > 0


@needs_docker
@pytest.mark.docker
def test_run_task_unsolved_fails_and_reports_check_output():
    r = bench.run_task(by_id("off-by-one"), Scripted(ModelResponse("yaptım sandım")))
    assert not r.passed and r.tool_calls == 0
    assert "FAIL" in r.check_output or "Error" in r.check_output


@needs_docker
@pytest.mark.docker
def test_cheating_by_editing_tests_does_not_pass():
    cheat = Scripted(
        write(
            "test_stats.py",
            "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n",
        ),
        ModelResponse("testleri geçirdim"),
    )
    r = bench.run_task(by_id("off-by-one"), cheat)
    assert not r.passed  # gizli doğrulama dosyası ajanın testini ezer


@needs_docker
@pytest.mark.docker
def test_tool_errors_and_denials_are_counted():
    m = Scripted(
        ModelResponse(None, [ToolCall("a", "read_file", {"path": "yok.txt"})]),
        ModelResponse(None, [ToolCall("b", "web_search", {"query": "x"})]),
        ModelResponse("bitti"),
    )
    r = bench.run_task(by_id("off-by-one"), m)
    assert r.tool_calls == 2 and r.tool_errors == 1 and r.denied == 1


@needs_docker
@pytest.mark.docker
def test_step_limit_marks_truncated():
    loop = Scripted(
        *[ModelResponse(None, [ToolCall(str(i), "list_dir", {"path": "."})]) for i in range(10)]
    )
    r = bench.run_task(by_id("off-by-one"), loop, max_steps=3)
    assert r.truncated and not r.passed and r.steps == 3


@needs_docker
@pytest.mark.docker
def test_time_limit_stops_runaway_model():
    import time

    class Slow:
        def chat(self, messages, tools=None):
            time.sleep(0.3)
            return ModelResponse(None, [ToolCall("x", "list_dir", {"path": "."})])

    t0 = time.monotonic()
    r = bench.run_task(by_id("off-by-one"), Slow(), time_limit=1.0, max_steps=100)
    assert time.monotonic() - t0 < 30 and "zaman" in r.error and not r.passed


def test_model_error_is_a_failed_run_not_a_crash(monkeypatch):
    from usta.models import ModelError

    class Broken:
        def chat(self, messages, tools=None):
            raise ModelError("uç nokta kapalı")

    monkeypatch.setattr(bench, "verify", lambda *a, **k: (False, ""))
    r = bench.run_task(by_id("off-by-one"), Broken())
    assert not r.passed and "uç nokta kapalı" in r.error


# --- özet ----------------------------------------------------------------------------------
def test_summarize_and_report_are_json_serializable():
    rs = [
        bench.TaskResult("a", True, steps=4, tool_calls=4, tool_errors=1, seconds=2.0),
        bench.TaskResult("a", False, steps=6, tool_calls=6, tool_errors=2, seconds=4.0),
        bench.TaskResult("b", True, steps=2, tool_calls=2, seconds=3.0),
    ]
    s = bench.summarize(rs)
    assert s["runs"] == 3 and s["passed"] == 2 and s["pass_rate"] == 0.667
    assert s["mean_steps"] == 4.0 and s["mean_seconds"] == 3.0
    assert s["tool_error_rate"] == 0.25
    assert s["per_task"] == {
        "a": {"passed": 1, "runs": 2, "infra": 0},
        "b": {"passed": 1, "runs": 1, "infra": 0},
    }
    assert json.loads(json.dumps(bench.report("m", "native", rs)))["summary"]["runs"] == 3
    assert bench.summarize([])["pass_rate"] == 0.0


# --- ölçüm doğruluğu: altyapı hatası ≠ başarısızlık, token, kanıtsız bildirim ----------------
def run_call(i=1, cmd="python -m unittest -q"):
    return ModelResponse(None, [ToolCall(f"r{i}", "run", {"command": cmd})])


@needs_docker
@pytest.mark.docker
def test_infra_error_is_retried_then_reported_as_infra_not_failure(monkeypatch):
    from usta.models import ModelError

    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    calls = []

    class Flaky:
        def chat(self, messages, tools=None):
            calls.append(1)
            raise ModelError("ReadTimeout", infra=True)

    r = bench.run_task(by_id("off-by-one"), Flaky(), infra_retries=2)
    assert r.outcome == "infra" and not r.passed and r.attempts == 3 and len(calls) == 3


@needs_docker
@pytest.mark.docker
def test_infra_error_then_success_counts_as_pass(monkeypatch):
    from usta.models import ModelError

    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    solved = Scripted(*solution_calls("off-by-one"))
    state = {"n": 0}

    class FlakyOnce:
        def chat(self, messages, tools=None):
            state["n"] += 1
            if state["n"] == 1:
                raise ModelError("HTTPStatusError", infra=True)
            return solved.chat(messages, tools)

    r = bench.run_task(by_id("off-by-one"), FlakyOnce(), infra_retries=2)
    assert r.outcome == "pass" and r.passed and r.attempts == 2


@needs_docker
@pytest.mark.docker
def test_protocol_error_is_a_model_failure_not_infra():
    from usta.models import ModelError

    class Garbage:
        def chat(self, messages, tools=None):
            raise ModelError("araç çağrısı çözümlenemedi")

    r = bench.run_task(by_id("off-by-one"), Garbage(), infra_retries=2)
    assert r.outcome == "fail" and r.attempts == 1 and "çözümlenemedi" in r.error


@needs_docker
@pytest.mark.docker
def test_tokens_are_recorded_per_task_from_client_usage():
    from usta.models import Usage

    class Counting(Scripted):
        usage = Usage()

        def chat(self, messages, tools=None):
            self.usage.prompt += 100
            self.usage.completion += 10
            self.usage.requests += 1
            return super().chat(messages, tools)

    m = Counting(ModelResponse("bitti"))
    m.usage.prompt = 5000  # önceki görevlerden birikmiş sayaç: fark alınmalı
    r = bench.run_task(by_id("off-by-one"), m)
    assert (r.prompt_tokens, r.completion_tokens, r.requests) == (100, 10, 1)


@needs_docker
@pytest.mark.docker
def test_unverified_claim_detected_when_edit_not_followed_by_run():
    calls = solution_calls("off-by-one")
    r = bench.run_task(by_id("off-by-one"), Scripted(*calls))
    assert r.passed and r.edits == 1 and not r.verified and r.unverified_claim


@needs_docker
@pytest.mark.docker
def test_verified_when_run_follows_last_edit():
    calls = solution_calls("off-by-one")
    seq = [calls[0], run_call(), calls[1]]
    r = bench.run_task(by_id("off-by-one"), Scripted(*seq))
    assert r.passed and r.verified and not r.unverified_claim


@needs_docker
@pytest.mark.docker
def test_edit_after_last_run_voids_verification():
    calls = solution_calls("off-by-one")
    r = bench.run_task(by_id("off-by-one"), Scripted(run_call(), calls[0], calls[1]))
    assert r.edits == 1 and not r.verified and r.unverified_claim


@needs_docker
@pytest.mark.docker
def test_modifying_existing_tests_is_flagged():
    weaken = write(
        "test_stats.py",
        "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n",
    )
    r = bench.run_task(by_id("off-by-one"), Scripted(weaken, ModelResponse("bitti")))
    assert r.tests_modified and not r.passed
    clean = bench.run_task(by_id("off-by-one"), Scripted(*solution_calls("off-by-one")))
    assert not clean.tests_modified


def test_summary_separates_infra_and_reports_cost_per_solved():
    rs = [
        bench.TaskResult(
            "a",
            True,
            steps=3,
            prompt_tokens=1000,
            completion_tokens=200,
            seconds=10.0,
            verified=True,
        ),
        bench.TaskResult(
            "a",
            False,
            steps=5,
            prompt_tokens=3000,
            completion_tokens=400,
            seconds=20.0,
            unverified_claim=True,
            edits=2,
        ),
        bench.TaskResult("b", False, outcome="infra", error="ReadTimeout", attempts=3),
    ]
    s = bench.summarize(rs)
    assert s["runs"] == 3 and s["valid_runs"] == 2 and s["infra_errors"] == 1
    assert s["passed"] == 1 and s["pass_rate"] == 0.5  # altyapı hatası paydada yok
    assert s["mean_tokens"] == 2300.0  # (1200 + 3400) / 2 geçerli koşu
    assert s["tokens_per_solved"] == 4600  # toplam geçerli token / çözülen görev
    assert s["unverified_claims"] == 1 and s["claimed_but_failed"] == 1
    assert s["tests_modified"] == 0
    assert s["per_task"]["b"] == {"passed": 0, "runs": 0, "infra": 1}
    allinfra = bench.summarize([bench.TaskResult("a", False, outcome="infra")])
    assert allinfra["pass_rate"] == 0.0 and allinfra["tokens_per_solved"] is None


# --- deney kolları ------------------------------------------------------------------------
def test_arms_are_defined_and_minimal_arm_is_shell_only():
    assert set(bench.ARMS) >= {"A", "B"}
    a, b = bench.ARMS["A"], bench.ARMS["B"]
    assert a.tools == frozenset({"run"}) and a.system_prompt and "run" in a.system_prompt
    assert b.tools is None and b.system_prompt is None  # B: mevcut Usta varsayılanları
    assert len(a.system_prompt) < 600


class Spy:
    def __init__(self):
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append((messages[0].content, [t["name"] for t in tools or []]))
        return ModelResponse("bitti")


@needs_docker
@pytest.mark.docker
def test_arm_a_gives_model_only_shell_and_short_prompt():
    spy = Spy()
    bench.run_task(by_id("off-by-one"), spy, arm=bench.ARMS["A"])
    prompt, tools = spy.seen[0]
    assert tools == ["run"] and prompt == bench.ARMS["A"].system_prompt


@needs_docker
@pytest.mark.docker
def test_arm_b_gives_full_default_toolset_and_prompt():
    from usta.agent import SYSTEM_PROMPT

    spy = Spy()
    bench.run_task(by_id("off-by-one"), spy, arm=bench.ARMS["B"])
    prompt, tools = spy.seen[0]
    assert prompt == SYSTEM_PROMPT and {"read_file", "write_file", "edit_file", "run"} <= set(tools)


def test_report_records_arm():
    assert bench.report("m", "native", [], arm="A")["arm"] == "A"


def test_registry_subset_keeps_only_named_tools_and_rejects_unknown(tmp_path):
    from usta.tools import ToolContext, ToolError, build_registry

    reg = build_registry(ToolContext(root=tmp_path))
    sub = reg.subset({"run"})
    assert [s["name"] for s in sub.schemas()] == ["run"]
    with pytest.raises(ToolError):
        sub.call("read_file", {"path": "a"})
    with pytest.raises(ValueError):
        reg.subset({"yok-boyle-arac"})


# --- C kolu: doğrulama döngüsü ---------------------------------------------------------------
def test_arm_c_is_b_plus_verification():
    c = bench.ARMS["C"]
    assert c.verify and c.tools is None and c.system_prompt is None
    assert not bench.ARMS["A"].verify and not bench.ARMS["B"].verify


@needs_docker
@pytest.mark.docker
def test_arm_c_gate_catches_wrong_fix_and_model_recovers():
    wrong = write(
        "stats.py",
        "def moving_average(values, window):\n    return [sum(values[:window]) / window]\n",
    )
    fixed, final = solution_calls("off-by-one")
    model = Scripted(wrong, ModelResponse("düzelttim"), fixed, final)
    r = bench.run_task(by_id("off-by-one"), model, arm=bench.ARMS["C"])
    assert r.passed and r.gate == "passed" and r.gate_rounds == 1
    assert r.verified and not r.unverified_claim


@needs_docker
@pytest.mark.docker
def test_arm_c_gate_gives_up_with_honest_failure_not_loop():
    wrong = write("stats.py", "def moving_average(values, window):\n    return []\n")
    model = Scripted(
        wrong, ModelResponse("bitti"), ModelResponse("bitti yine"), ModelResponse("hâlâ bitti")
    )
    r = bench.run_task(by_id("off-by-one"), model, arm=bench.ARMS["C"])
    assert not r.passed and r.gate == "failed" and 1 <= r.gate_rounds <= 3
    assert r.steps <= 6  # sonsuz düzeltme döngüsü yok


@needs_docker
@pytest.mark.docker
def test_arm_c_without_repo_tests_nudges_model_to_write_its_own():
    sol = solution_calls("implement-slugify")
    own_test = write(
        "test_own.py",
        "import unittest\nfrom slug import slugify\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(slugify('A b'), 'a-b')\n",
        9,
    )
    model = Scripted(sol[0], ModelResponse("bitti"), own_test, ModelResponse("test yazdım"))
    r = bench.run_task(by_id("implement-slugify"), model, arm=bench.ARMS["C"])
    assert r.gate == "passed" and r.verified and r.edits == 2


# --- katmanlı karşılaştırma raporu (zayıf / orta / büyük) -----------------------------------
def write_report(path, model, arm, outcomes, tokens=1000):
    rs = [
        bench.TaskResult(f"t{i % 3}", ok, steps=4, prompt_tokens=tokens, seconds=10.0, tool_calls=4)
        for i, ok in enumerate(outcomes)
    ]
    path.write_text(json.dumps(bench.report(model, "native", rs, arm)))
    return path


def test_wilson_interval_properties():
    lo, hi = bench.wilson(0, 15)
    assert lo == 0.0 and 0.15 < hi < 0.25
    lo, hi = bench.wilson(15, 15)
    assert hi == 1.0 and lo > 0.75
    lo, hi = bench.wilson(8, 15)
    assert lo < 8 / 15 < hi and hi - lo > 0.4  # 15 koşuda aralık geniştir
    assert bench.wilson(0, 0) == (0.0, 0.0)


def test_compare_groups_by_tier_and_arm_and_marks_overlap(tmp_path):
    weak = [
        write_report(tmp_path / "w-a.json", "kucuk", "A", [True] + [False] * 14),
        write_report(tmp_path / "w-b.json", "kucuk", "B", [False] * 15),
        write_report(tmp_path / "w-c.json", "kucuk", "C", [True] + [False] * 14, tokens=3500),
    ]
    api = [write_report(tmp_path / "a-b.json", "buyuk", "B", [True] * 14 + [False])]
    md = bench.compare_markdown({"zayıf": weak, "büyük (API)": api})
    assert "## zayıf" in md and "## büyük (API)" in md
    assert "kucuk" in md and "buyuk" in md
    assert "| A |" in md and "| B |" in md and "| C |" in md
    assert "1/15" in md and "0/15" in md and "14/15" in md
    assert "%95 aralık" in md or "95%" in md
    assert "3500" in md  # C kolunun token maliyeti görünür
    assert "belirgin fark yok" in md  # zayıf katmanda aralıklar örtüşüyor


def test_compare_says_clear_difference_when_intervals_do_not_overlap(tmp_path):
    files = [
        write_report(tmp_path / "x.json", "m", "B", [False] * 30),
        write_report(tmp_path / "y.json", "m", "C", [True] * 30),
    ]
    md = bench.compare_markdown({"orta": files})
    assert "C, B'den belirgin şekilde yüksek" in md


def test_compare_cli_prints_and_writes(tmp_path, capsys):
    from usta.cli import main

    a = write_report(tmp_path / "a.json", "m", "A", [True, False, False])
    b = write_report(tmp_path / "b.json", "m", "B", [True, True, False])
    out = tmp_path / "rapor.md"
    assert main(["bench", "compare", f"zayıf={a}", f"zayıf={b}", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert (
        "## zayıf" in printed
        and out.read_text() == printed.rstrip("\n") + "\n"
        or "## zayıf" in out.read_text()
    )
    assert main(["bench", "compare", "bozuk-arguman"]) == 2
    assert main(["bench", "compare", f"x={tmp_path / 'yok.json'}"]) == 2


def test_compare_accepts_old_reports_without_arm_field(tmp_path):
    p = write_report(tmp_path / "eski.json", "m", "B", [True, False])
    data = json.loads(p.read_text())
    del data["arm"]
    p.write_text(json.dumps(data))
    assert "| B |" in bench.compare_markdown({"orta": [p]})


# --- D kolu: devre kesici -----------------------------------------------------------------
def test_arm_d_is_c_plus_breaker():
    d = bench.ARMS["D"]
    assert d.verify and d.breaker and not bench.ARMS["C"].breaker


def test_summary_counts_breaker_trips_and_blocked():
    rs = [
        bench.TaskResult("a", False, breaker_trips=2, blocked=True),
        bench.TaskResult("b", True, breaker_trips=0),
    ]
    s = bench.summarize(rs)
    assert s["breaker_trips"] == 2 and s["blocked"] == 1


@needs_docker
@pytest.mark.docker
def test_arm_d_records_trip_and_blocked_in_result():
    wrong = lambda i, body: write(
        "stats.py", f"def moving_average(values, window):\n    return {body}\n", i
    )
    seq = [wrong(1, "[]"), run_call(1), wrong(2, "list()"), run_call(2), ModelResponse("bitti")]
    r = bench.run_task(by_id("off-by-one"), Scripted(*seq), arm=bench.ARMS["D"])
    assert r.breaker_trips >= 1


# --- durdurma: dış taraf dosya koyarak ölçümü kesebilir ---------------------------------------
def test_run_bench_stops_between_runs_when_asked(monkeypatch):
    calls = []

    def fake_run(task, model, **kw):
        calls.append(task.id)
        return bench.TaskResult(task.id, True)

    monkeypatch.setattr(bench, "run_task", fake_run)
    tasks = bench.load_tasks()[:4]
    stop_after = {"n": 0}

    def should_stop():
        stop_after["n"] += 1
        return stop_after["n"] > 2  # iki koşudan sonra dur

    results = bench.run_bench(lambda: None, tasks, repeat=3, should_stop=should_stop)
    assert len(results) == 2 and len(calls) == 2


def test_cli_stop_file_halts_bench_and_reports(tmp_path, monkeypatch, capsys, endpoint):
    from usta.cli import main

    stop = tmp_path / "DUR"
    stop.write_text("")
    code = main(
        [
            "bench",
            "run",
            "--task",
            "off-by-one",
            "--endpoint",
            endpoint.url,
            "--model",
            "m",
            "--stop-file",
            str(stop),
        ]
    )
    assert code == 0 and "durduruldu" in capsys.readouterr().out
