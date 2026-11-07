"""Bench teşhisi: başarısızlık sınıflandırması, görev bölümleri, iz/tekrar oynatma, eşleştirilmiş karşılaştırma."""

import json
import shutil
import subprocess

import pytest

from test_bench import Scripted, by_id, solution_calls, write
from usta import bench, taxonomy
from usta.cli import main
from usta.models import ModelResponse, ToolCall

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


def facts(**kw):
    base = {"passed": False, "tool_calls": 5, "edits": 1, "steps": 6, "max_steps": 30}
    return taxonomy.Facts(**(base | kw))


# --- sınıflandırma (deterministik, Docker yok) -----------------------------------------------
@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"infra": True}, taxonomy.INFRA),
        ({"timed_out": True}, taxonomy.TIMEOUT),
        ({"model_error": True}, taxonomy.MODEL_ERROR),
        (
            {"tool_calls": 0, "edits": 0, "answer": '{"name": "write_file", "arguments": {}}'},
            taxonomy.TOOL_CALL_AS_TEXT,
        ),
        ({"tool_calls": 0, "edits": 0, "answer": "Tamamlandı."}, taxonomy.NO_TOOL_CALLS),
        ({"tests_modified": True}, taxonomy.TESTS_TAMPERED),
        (
            {"tool_calls": 6, "tool_errors": ["hata: eksik argüman: path"] * 4},
            taxonomy.TOOL_ARGUMENT_ERROR,
        ),
        (
            {"tool_calls": 4, "tool_errors": ["hata: FileNotFoundError: x"] * 3},
            taxonomy.WRONG_FILE_OR_SYMBOL,
        ),
        (
            {"tool_calls": 4, "tool_errors": ["hata: eşleşme bulunamadı (old)"] * 3},
            taxonomy.EDIT_FAILURE,
        ),
        ({"truncated": True, "gate_rounds": 9, "breaker_trips": 2}, taxonomy.HARNESS_LOOP),
        (
            {"truncated": True, "compactions": 2, "context_window": 8192, "context_peak": 7800},
            taxonomy.CONTEXT_EXHAUSTED,
        ),
        ({"calls": [("run", "{}")] * 4}, taxonomy.REPEATED_APPROACH),
        ({"truncated": True}, taxonomy.STEP_LIMIT),
        ({"syntax_warnings": 2}, taxonomy.SYNTAX_ERROR_INTRODUCED),
        ({"edits": 0}, taxonomy.NO_CHANGE),
        ({"unverified_claim": True}, taxonomy.UNVERIFIED_CLAIM),
        ({}, taxonomy.WRONG_SOLUTION),
    ],
)
def test_failure_categories(kw, expected):
    assert taxonomy.classify(facts(**kw)).primary == expected


def test_successful_run_has_no_failure_category_but_keeps_signals():
    v = taxonomy.classify(facts(passed=True, calls=[("run", "{}")] * 4))
    assert v.primary == "" and taxonomy.REPEATED_APPROACH in v.signals


def test_classification_is_deterministic_and_every_category_is_known():
    f = facts(tool_errors=["hata: FileNotFoundError"], tool_calls=2)
    assert taxonomy.classify(f) == taxonomy.classify(f)
    assert taxonomy.classify(f).primary in taxonomy.CATEGORIES
    assert len(set(taxonomy.CATEGORIES)) == len(taxonomy.CATEGORIES)


# --- bölümler ve gizli test ayrımı ------------------------------------------------------------
def test_every_task_has_exactly_one_split_and_splits_are_disjoint():
    tasks = bench.load_tasks()
    assert all(t.split in bench.SPLITS for t in tasks)
    by = {s: {t.id for t in tasks if t.split == s} for s in bench.SPLITS}
    assert sum(len(v) for v in by.values()) == len(tasks) and all(by.values())
    assert by["train"].isdisjoint(by["dev"]) and by["dev"].isdisjoint(by["final"])
    assert {t.id for t in bench.select_tasks(tasks, "dev-all")} == by["train"] | by["dev"]
    assert {t.id for t in bench.select_tasks(tasks, "final")} == by["final"]
    assert len(bench.select_tasks(tasks, "all")) == len(tasks)
    with pytest.raises(ValueError):
        bench.select_tasks(tasks, "yok")


def test_default_bench_run_excludes_the_final_split(monkeypatch, capsys):
    seen = {}

    def fake(model_factory, tasks, **kw):
        seen["ids"] = {t.id for t in tasks}
        return []

    monkeypatch.setattr(bench, "run_bench", fake)
    monkeypatch.setattr("usta.cli._make_model", lambda a: object())
    main(["bench", "run", "--model", "m", "--endpoint", "http://x"])
    final = {t.id for t in bench.load_tasks() if t.split == "final"}
    assert seen["ids"] and seen["ids"].isdisjoint(final)
    seen.clear()
    main(["bench", "run", "--model", "m", "--endpoint", "http://x", "--split", "final"])
    assert seen["ids"] == final
    assert "final bölümü yalnız sürüm ölçümü" in capsys.readouterr().err


def test_splits_command_lists_partitions(capsys):
    assert main(["bench", "splits"]) == 0
    out = capsys.readouterr().out
    assert "train:" in out and "dev:" in out and "final:" in out


@needs_docker
@pytest.mark.docker
def test_hidden_checks_are_not_visible_to_the_agent_during_the_run(tmp_path):
    repo, check = tmp_path / "repo", tmp_path / "check"
    repo.mkdir()
    check.mkdir()
    (repo / "f.py").write_text("X = 1\n")
    (check / "gizli_test.py").write_text("GIZLI-DOGRULAMA\n")
    task = bench.BenchTask(
        "sentetik",
        "f.py içindeki X'i 2 yap",
        repo,
        check,
        ("python", "-c", "import os,sys; sys.exit(0 if os.path.exists('gizli_test.py') else 1)"),
    )
    peek = Scripted(
        ModelResponse(None, [ToolCall("c1", "read_file", {"path": "gizli_test.py"})]),
        ModelResponse(None, [ToolCall("c2", "list_dir", {"path": "."})]),
        ModelResponse("bakamadım"),
    )
    r = bench.run_task(task, peek, trace_dir=tmp_path / "t")
    assert r.tool_errors == 1  # çalışma alanında gizli doğrulama dosyası yoktu
    doc = json.loads((tmp_path / "t" / r.trace).read_text())
    listing = next(
        e["head"] for e in doc["events"] if e["kind"] == "tool_result" and "f.py" in e["head"]
    )
    assert "gizli_test.py" not in listing
    assert r.passed  # doğrulama dosyaları koşudan SONRA yazıldı ve komut onları gördü


def test_arms_a_to_d_unchanged_and_new_arms_are_labelled_experimental():
    assert not any(bench.ARMS[k].experimental for k in "ABCD")
    assert bench.ARMS["C"].verify and not bench.ARMS["C"].breaker
    assert bench.ARMS["D"].verify and bench.ARMS["D"].breaker
    exp = {k for k, a in bench.ARMS.items() if a.experimental}
    assert exp == {"X-BRK", "X-CTX", "X-ALL", "X-FULL", "X-SYM", "X-TAINT"}
    assert bench.ARMS["X-TAINT"].taint and bench.ARMS["X-TAINT"].verify  # C + kaynak izi kapısı
    assert not any(bench.ARMS[k].taint for k in "ABCD")  # A-D anlamı değişmez
    assert bench.ARMS["X-BRK"].breaker and not bench.ARMS["X-BRK"].verify
    assert bench.ARMS["X-CTX"].context_window and not bench.ARMS["X-CTX"].verify
    assert (
        bench.ARMS["X-ALL"].verify
        and bench.ARMS["X-ALL"].breaker
        and bench.ARMS["X-ALL"].context_window
    )


# --- koşu kaydı, izler, tekrar oynatma (gerçek sandbox) ----------------------------------------
@needs_docker
@pytest.mark.docker
def test_run_records_failure_category_and_resource_fields():
    task = by_id("off-by-one")
    r = bench.run_task(task, Scripted(ModelResponse("yaptım sandım")))
    assert (
        not r.passed and r.failure == taxonomy.NO_TOOL_CALLS and taxonomy.NO_TOOL_CALLS in r.signals
    )
    text = bench.run_task(
        task,
        Scripted(
            ModelResponse('{"name": "write_file", "arguments": {"path": "a", "content": "b"}}')
        ),
    )
    assert text.failure == taxonomy.TOOL_CALL_AS_TEXT
    ok = bench.run_task(task, Scripted(*solution_calls("off-by-one")))
    assert ok.passed and ok.failure == "" and ok.repair_attempts == 0


@needs_docker
@pytest.mark.docker
def test_repair_attempts_count_edits_after_first_test_run():
    task = by_id("off-by-one")
    sol = solution_calls("off-by-one")
    run = ModelResponse(None, [ToolCall("r1", "run", {"command": "python -m unittest -q"})])
    r = bench.run_task(
        task, Scripted(run, sol[0], run, write("yedek.txt", "x", 9), ModelResponse("bitti"))
    )
    assert r.repair_attempts == 2 and r.tool_calls == 4


@needs_docker
@pytest.mark.docker
def test_trace_records_steps_and_replay_reproduces_the_result(tmp_path):
    task = by_id("off-by-one")
    r = bench.run_task(task, Scripted(*solution_calls("off-by-one")), trace_dir=tmp_path)
    assert r.passed and r.trace
    doc = json.loads((tmp_path / r.trace).read_text())
    assert doc["version"] == bench.TRACE_VERSION and doc["task"] == "off-by-one" and doc["replies"]
    kinds = [e["kind"] for e in doc["events"]]
    assert (
        "tool_call" in kinds and "tool_result" in kinds and all("t_ms" in e for e in doc["events"])
    )
    new, old = bench.replay_trace(tmp_path / r.trace)
    assert new.passed == old["passed"] is True and new.tool_calls == r.tool_calls
    # kayıtlı yanıtlar bozulursa (ör. çözüm silinirse) yeniden oynatma farkı yakalar
    doc["replies"] = [{"content": "boş", "tool_calls": []}]
    (tmp_path / "bozuk.json").write_text(json.dumps(doc))
    bad, _ = bench.replay_trace(tmp_path / "bozuk.json")
    assert not bad.passed


def test_replay_rejects_traces_without_recorded_replies(tmp_path):
    (tmp_path / "t.json").write_text(
        json.dumps({"version": bench.TRACE_VERSION, "task": "x", "replies": []})
    )
    with pytest.raises(ValueError, match="yeniden oynatılabilir"):
        bench.replay_trace(tmp_path / "t.json")


@needs_docker
@pytest.mark.docker
def test_traces_mask_secrets(tmp_path):
    secret = "sk-" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr"
    task = by_id("off-by-one")
    r = bench.run_task(
        task,
        Scripted(write("not.txt", f"anahtar {secret}"), ModelResponse(f"bitti {secret}")),
        trace_dir=tmp_path,
    )
    blob = (tmp_path / r.trace).read_text()
    assert secret not in blob and "[GİZLİ]" in blob


# --- eşleştirilmiş karşılaştırma ve rapor ----------------------------------------------------
def results(outcomes, tasks=("a", "b", "c"), failure="WRONG_SOLUTION"):
    return [
        bench.TaskResult(
            tasks[i % len(tasks)],
            ok,
            outcome="pass" if ok else "fail",
            failure="" if ok else failure,
            tool_calls=4,
            repair_attempts=1,
        )
        for i, ok in enumerate(outcomes)
    ]


def test_paired_counts_and_infra_pairs_are_skipped():
    a = results([True, True, False, False, True, False])
    b = results([True, False, True, False, True, False])
    b[5] = bench.TaskResult("c", False, outcome="infra")
    p = bench.paired(a, b)
    assert p == {"pairs": 5, "both": 2, "a_only": 1, "b_only": 1, "neither": 1}


def test_paired_verdict_never_claims_significance_on_small_samples():
    v = bench.paired_verdict(
        {"pairs": 10, "both": 3, "a_only": 0, "b_only": 5, "neither": 2}, "B", "C"
    )
    assert "C lehine" in v and "yalnız yön" in v and "anlamlı" not in v
    assert "aynı sonuç" in bench.paired_verdict(
        {"pairs": 4, "both": 2, "a_only": 0, "b_only": 0, "neither": 2}, "B", "C"
    )
    assert "yön yok" in bench.paired_verdict(
        {"pairs": 4, "both": 0, "a_only": 2, "b_only": 2, "neither": 0}, "B", "C"
    )
    assert "eşleşen çift yok" in bench.paired_verdict(
        {"pairs": 0, "both": 0, "a_only": 0, "b_only": 0, "neither": 0}, "B", "C"
    )


def test_compare_and_diagnose_reports_include_failures_infra_and_paired_table(tmp_path):
    def rep(arm, outcomes, **kw):
        path = tmp_path / f"{arm}.json"
        path.write_text(json.dumps(bench.report("m7b", "json", results(outcomes, **kw), arm)))
        return path

    b = rep("B", [False, False, True, False, False, False])
    c = rep("C", [True, False, True, False, False, False], failure="NO_CHANGE")
    md = bench.compare_markdown({"orta": [b, c]})
    assert "Başarısızlık nedenleri" in md and "WRONG_SOLUTION" in md and "NO_CHANGE" in md
    assert "Eşleştirilmiş karşılaştırma" in md and "Yalnız B" in md
    assert "Altyapı hatası" in md and "anlamlılık iddia edilmez" in md
    diag = bench.diagnose_markdown([b, c])
    assert "Neden | Koşu | Pay" in diag and "onarım denemesi" in diag and "m7b" in diag


def test_old_reports_without_new_fields_still_load_and_compare(tmp_path):
    old = {
        "arm": "B",
        "model": "eski",
        "protocol": "native",
        "summary": {},
        "results": [{"task": "t", "passed": False, "steps": 3, "outcome": "fail"}],
    }
    (tmp_path / "o.json").write_text(json.dumps(old))
    assert "eski" in bench.compare_markdown({"x": [tmp_path / "o.json"]})
    assert "eski" in bench.diagnose_markdown([tmp_path / "o.json"])


def test_cli_diagnose_and_replay_errors(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(bench.report("m", "native", results([True, False]), "B")))
    assert (
        main(["bench", "diagnose", str(p)]) == 0 and "USTA Bench teşhisi" in capsys.readouterr().out
    )
    assert main(["bench", "diagnose", str(tmp_path / "yok.json")]) == 2
    assert main(["bench", "replay", str(tmp_path / "yok.json")]) == 2


def test_regress_report_lists_regressions_improvements_and_cost_shift(tmp_path):
    def rep(name, passed_by_task, model="m", arm="B"):
        rs = [
            bench.TaskResult(
                t,
                ok,
                outcome="pass" if ok else "fail",
                failure="" if ok else "WRONG_SOLUTION",
                prompt_tokens=100 * (1 + i),
                seconds=10.0,
                tool_calls=3,
            )
            for i, (t, oks) in enumerate(passed_by_task.items())
            for ok in oks
        ]
        path = tmp_path / name
        path.write_text(json.dumps(bench.report(model, "json", rs, arm)))
        return path

    old = rep("old.json", {"a": [True, True], "b": [False, False], "c": [True, False]})
    new = rep("new.json", {"a": [True, False], "b": [True, True], "c": [True, False]})
    md = bench.regress_markdown(old, new)
    assert "Regresyonlar (1)" in md and "- a: 2/2 → 1/2" in md
    assert "İyileşmeler (1)" in md and "- b: 0/2 → 2/2" in md
    assert "Başarısızlık nedeni kayması" in md and "WRONG_SOLUTION" in md and "Token/görev" in md
    assert "UYARI" not in md
    other = rep("o.json", {"a": [True, True]}, model="baska", arm="C")
    warn = bench.regress_markdown(old, other)
    assert "model farklı" in warn and "kol farklı" in warn and "görev kümeleri farklı" in warn


def test_cli_regress(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(bench.report("m", "json", results([True, False]), "B")))
    assert main(["bench", "regress", str(p), str(p)]) == 0
    assert "Regresyonlar (0)" in capsys.readouterr().out
    assert main(["bench", "regress", str(p), str(tmp_path / "yok.json")]) == 2
