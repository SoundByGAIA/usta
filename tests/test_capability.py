"""Model Capability Profiler: sondalar, protokol önerisi, revizyon/yapılandırmaya bağlı kalıcı profil, `--protocol auto`."""

import argparse
import json
import stat

import pytest

from usta import capability, cli, profile
from usta.cli import main
from usta.jsonproto import JsonProtocolClient
from usta.models import Message, ModelResponse, ToolCall, Usage


def call(name, **args):
    return ToolCall("c", name, args)


class Perfect:
    """Her sondada doğru araç çağrısını üretir (ikili çağrıyı aynı yanıtta verir)."""

    usage = Usage()

    def chat(self, messages, tools=None, **kw):
        last_tool = next((m.content for m in reversed(messages) if m.role == "tool"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "eksik argüman" in last_tool:
            return ModelResponse(None, [call("read_file", path="a.txt")])
        if "FileNotFoundError" in last_tool:
            return ModelResponse(None, [call("list_dir", path=".")])
        if "ikisini de" in user:
            return ModelResponse(
                None, [call("read_file", path="a.txt"), call("read_file", path="b.txt")]
            )
        if "ne yazdığını söyle" in user:
            return ModelResponse(None, [call("read_file", path="notes.txt")])
        if "hangi dosyalar var" in user:
            return ModelResponse(None, [call("list_dir", path=".")])
        if "write_file kullan" in user:
            return ModelResponse(
                None, [call("write_file", path="not.txt", content='satır 1\n"tırnaklı" satır 2')]
            )
        if "`ls`" in user:
            return ModelResponse(None, [call("run", command="ls")])
        if "GİZLİ DOSYA ADI" in user:
            return ModelResponse(None, [call("read_file", path="rapor-7421.txt")])
        return ModelResponse(None, [call("read_file", path="a.txt")])


class OneAtATime(Perfect):
    """İki dosyayı ardışık turlarda okur (aynı yanıtta tek çağrı)."""

    def chat(self, messages, tools=None, **kw):
        r = super().chat(messages, tools)
        if len(r.tool_calls) == 2:
            had_tool = any(m.role == "tool" for m in messages)
            return ModelResponse(None, [r.tool_calls[1] if had_tool else r.tool_calls[0]])
        return r


class Sloppy:
    """Argümanı unutur ve fazladan argüman ekler; tırnakları bozar."""

    usage = Usage()

    def chat(self, messages, tools=None, **kw):
        return ModelResponse(None, [call("read_file", dosya="a.txt")])


class TextOnly:
    usage = Usage()

    def chat(self, messages, tools=None, **kw):
        return ModelResponse("Tamam, dosyayı okuyacağım.", [])


# --- doğrulama ve sondalar ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("tc", "problem"),
    [
        (call("read_file", path="a"), None),
        (call("read_file"), "eksik argüman"),
        (call("read_file", path="a", x=1), "fazla argüman"),
        (call("read_file", path=5), "yanlış tip"),
        (call("yok", path="a"), "bilinmeyen araç"),
    ],
)
def test_validate_call(tc, problem):
    got = capability.validate_call(tc)
    assert (got is None) if problem is None else (problem in got)


def test_perfect_model_passes_every_probe_with_zero_argument_errors():
    s = capability.run_protocol(Perfect(), "native", {"long_chars": 4000, "e2e": []})
    assert [r.name for r in s.results] == [
        "natural_task", "single_call", "run_command", "args_exact", "multi_call",
        "error_recovery", "bad_output_recovery", "long_context",
    ]  # fmt: skip
    assert all(r.ok for r in s.results) and s.score == 1.0 and s.arg_error_rate == 0.0
    assert all(r.ms >= 0 for r in s.results)


def test_sequential_tool_calls_count_for_multi_call():
    s = capability.run_protocol(OneAtATime(), "native", {"e2e": []})
    multi = next(r for r in s.results if r.name == "multi_call")
    assert multi.ok and "ardışık" in multi.note
    assert s.score == 1.0


def test_sloppy_model_is_measured_on_argument_discipline():
    s = capability.run_protocol(Sloppy(), "native", {"e2e": []})
    assert s.score == 0.0 and s.arg_error_rate == 1.0
    assert all(not r.ok for r in s.results)


def test_model_that_never_calls_tools_scores_zero_with_no_calls():
    s = capability.run_protocol(TextOnly(), "native", {"e2e": []})
    assert s.score == 0.0 and sum(r.calls for r in s.results) == 0 and s.arg_error_rate == 0.0


def test_long_context_probe_buries_the_needle_in_the_middle():
    seen = {}

    class Spy(Perfect):
        def chat(self, messages, tools=None, **kw):
            user = next(m.content for m in messages if m.role == "user")
            if "GİZLİ DOSYA ADI" in user:
                seen["len"] = len(user)
                seen["pos"] = user.index("rapor-7421") / len(user)
            return super().chat(messages, tools)

    capability.probe_long_context(Spy(), {"long_chars": 12000})
    assert seen["len"] > 12000 and 0.3 < seen["pos"] < 0.7


def test_recommend_prefers_highest_score_then_simplest_and_enforces_floor():
    def sc(p, score):
        s = capability.ProtocolScore(p)
        s.score = score
        return s

    assert (
        capability.recommend(
            {"native": sc("native", 0.8), "json": sc("json", 0.9), "text": sc("text", 0.4)}
        )[0]
        == "json"
    )
    assert (
        capability.recommend(
            {"native": sc("native", 0.9), "json": sc("json", 0.9), "text": sc("text", 0.9)}
        )[0]
        == "native"
    )
    proto, why = capability.recommend(
        {"native": sc("native", 0.2), "json": sc("json", 0.3), "text": sc("text", 0.1)}
    )
    assert proto == "text" and "güvenilir değil" in why


# --- profil kalıcılığı ------------------------------------------------------------------------
@pytest.fixture
def per_protocol(monkeypatch):
    clients = {"native": Sloppy(), "json": Perfect(), "text": TextOnly()}
    monkeypatch.setattr(capability, "wrap", lambda base, proto: clients[proto])
    monkeypatch.setattr(capability, "_supports_extra", lambda c: True)
    return clients


def test_profile_model_recommends_best_protocol_and_records_provenance(per_protocol):
    p = capability.profile_model(
        lambda: object(),
        "m7b",
        endpoint="http://x/v1/",
        revision="abc123",
        config={"context_window": 8192},
        e2e=(),
    )
    assert p.recommended == "json" and set(p.protocols) == {"native", "json", "text"}
    assert (
        p.revision == "abc123"
        and p.config == {"context_window": 8192}
        and p.endpoint == "http://x/v1"
    )
    assert p.protocols["json"]["score"] == 1.0 and p.protocols["native"]["arg_error_rate"] == 1.0


def test_profile_is_keyed_by_revision_and_config(per_protocol, tmp_path):
    cfg = {"context_window": 8192}
    p = capability.profile_model(
        lambda: object(), "m", endpoint="http://x", revision="r1", config=cfg, e2e=()
    )
    capability.save(tmp_path, p)
    mode = stat.S_IMODE((tmp_path / "capabilities.json").stat().st_mode)
    assert mode == 0o600
    assert capability.load(tmp_path, "http://x", "m", "r1", cfg).recommended == "json"
    assert capability.load(tmp_path, "http://x", "m", "r2", cfg) is None  # model revizyonu değişti
    assert (
        capability.load(tmp_path, "http://x", "m", "r1", {"context_window": 16384}) is None
    )  # yapılandırma değişti
    assert capability.load(tmp_path, "http://y", "m", "r1", cfg) is None  # başka uç nokta
    assert capability.load(tmp_path, "http://x", "baska", "r1", cfg) is None


def test_load_survives_corrupt_or_wrong_schema_files(tmp_path):
    (tmp_path / "capabilities.json").write_text("{bozuk")
    assert capability.load(tmp_path, "http://x", "m", "", {}) is None
    key = capability.profile_key("http://x", "m", "", {})
    (tmp_path / "capabilities.json").write_text(
        json.dumps({key: {"schema": 99, "recommended": "json"}})
    )
    assert capability.load(tmp_path, "http://x", "m", "", {}) is None


def test_resolve_protocol_prefers_a_matching_deep_profile(per_protocol, tmp_path, monkeypatch):
    p = capability.profile_model(
        lambda: object(), "m", endpoint="http://x", revision="r1", config={}, e2e=()
    )
    capability.save(tmp_path, p)
    monkeypatch.setattr(profile, "probe", lambda *a, **k: pytest.fail("hızlı sonda çalışmamalı"))
    got = profile.resolve_protocol(
        tmp_path, "http://x", "m", lambda: object(), revision="r1", config={}
    )
    assert got.protocol == "json" and "derin profil" in got.note


def test_resolve_protocol_falls_back_to_quick_probe_when_revision_differs(
    per_protocol, tmp_path, monkeypatch
):
    p = capability.profile_model(
        lambda: object(), "m", endpoint="http://x", revision="r1", config={}, e2e=()
    )
    capability.save(tmp_path, p)
    quick = profile.Profile("m", "text", 0, 3, 0, 3, "hızlı", 1.0)
    monkeypatch.setattr(profile, "probe", lambda *a, **k: quick)
    got = profile.resolve_protocol(
        tmp_path, "http://x", "m", lambda: object(), revision="r2", config={}
    )
    assert got.protocol == "text" and got.note == "hızlı"


# --- CLI ---------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path.parent / f"{tmp_path.name}-ustahome"
    monkeypatch.setenv("USTA_HOME", str(home))
    for k in ("USTA_ENDPOINT", "USTA_MODEL", "USTA_API_KEY", "USTA_PROTOCOL"):
        monkeypatch.delenv(k, raising=False)
    return home


def test_probe_deep_prints_table_saves_and_reuses_cache(per_protocol, home, monkeypatch, capsys):
    monkeypatch.setattr(capability, "detect_revision", lambda e, m: "rev9")
    argv = [
        "probe",
        "--deep",
        "--model",
        "m7b",
        "--endpoint",
        "http://x/v1",
        "--context-window",
        "8192",
    ]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "single_call" in out and "Öneri: json" in out and "rev9" in out
    assert (home / "capabilities.json").is_file()
    monkeypatch.setattr(
        capability, "profile_model", lambda *a, **k: pytest.fail("önbellekten gelmeli")
    )
    assert main(argv) == 0 and "Öneri: json" in capsys.readouterr().out


def test_protocol_auto_is_resolved_once_and_pinned(monkeypatch, home, capsys):
    pinned = profile.Profile("m", "json", 0, 0, 0, 3, "test notu", 1.0)
    calls = []
    monkeypatch.setattr(profile, "resolve_protocol", lambda *a, **k: calls.append(1) or pinned)
    args = argparse.Namespace(
        model="m",
        protocol="auto",
        endpoint="http://x/v1",
        model_timeout=5.0,
        extra_body=None,
        context_window=None,
    )
    model = cli._make_model(args)
    assert isinstance(model, JsonProtocolClient) and args.protocol == "json" and len(calls) == 1
    assert "otomatik, sabitlendi" in capsys.readouterr().out
    # sabitlendikten sonra ikinci çağrı aynı protokolü yeniden profillemeden kullanır
    assert isinstance(cli._make_model(args), JsonProtocolClient) and len(calls) == 1


def test_unknown_protocol_is_rejected(monkeypatch, capsys):
    args = argparse.Namespace(
        model="m", protocol="xml", endpoint="http://x", model_timeout=5.0, extra_body=None
    )
    assert cli._make_model(args) is None and "native|json|text|auto" in capsys.readouterr().err


def test_message_helpers_are_plain_data():
    assert (
        Message("user", "x").role == "user"
    )  # içe aktarma kontrolü: profiller Message tipine bağlı


class Flaky(Perfect):
    """Her N. çağrıda yanlış dosya okur: tek örnek gürültülü, tekrarlı ölçüm kararlı."""

    def __init__(self, fail_every):
        self.n = 0
        self.fail_every = fail_every

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n % self.fail_every == 0:
            return ModelResponse(None, [call("read_file", path="yanlis.txt")])
        return super().chat(messages, tools)


def test_repeated_probes_tolerate_one_noisy_sample_and_report_fractions():
    s = capability.run_protocol(Flaky(11), "native", {"repeats": 3, "e2e": []})
    assert all(r.trials == 3 for r in s.results)
    ok = [r for r in s.results if r.ok]
    assert len(ok) >= 6  # tek bir yanlış örnek sondayı düşürmez (2/3 yeterli)
    assert 0.0 < s.score <= 1.0 and any(r.passes < r.trials for r in s.results) or s.score == 1.0


def test_two_of_three_samples_failing_fails_the_probe_and_lowers_the_score():
    flaky = Flaky(2)  # çağrıların yarısı bozuk
    s = capability.run_protocol(flaky, "native", {"repeats": 3, "e2e": []})
    assert s.score < 0.9 and any(not r.ok for r in s.results)
    single = capability.run_protocol(Perfect(), "native", {"repeats": 3, "e2e": []})
    assert single.score == 1.0 and all(r.passes == 3 for r in single.results)


def test_deep_profile_records_repeats_and_realistic_probe_provenance(per_protocol):
    p = capability.profile_model(lambda: object(), "m", endpoint="http://x", repeats=2, e2e=())
    assert p.repeats == 2 and p.realistic and p.probe_tools >= 9
    assert p.config == {}  # profil anahtarı sonda ayrıntısına bağlı değil


class E2EModel:
    """Lab'ın temiz senaryolarını çözen betikli model: ilk kullanıcı mesajına göre senaryoyu seçer."""

    def __init__(self, behavior="compliant"):
        from usta.lab import scenario
        from usta.lab.scripted import ScriptedModel

        self.by_task = {s.task: s for s in scenario.load()}
        self.ScriptedModel, self.behavior, self.cur = ScriptedModel, behavior, None
        self.usage = Usage()

    def chat(self, messages, tools=None, **kw):
        first = next(m.content for m in messages if m.role == "user")
        if len(messages) <= 2 or self.cur is None:
            self.cur = self.ScriptedModel(
                self.by_task[first.split("Görev: ")[-1]], "clean", self.behavior
            )
        return self.cur.chat(messages, tools)


def test_agent_tasks_probe_runs_real_agent_loop_on_lab_scenarios():
    good = capability.probe_agent_tasks(E2EModel("compliant"), {})
    assert (
        good.ok and good.passes == good.trials == len(capability.E2E_SCENARIOS) and good.calls > 0
    )
    bad = capability.probe_agent_tasks(E2EModel("refuser"), {})
    assert not bad.ok and bad.passes == 0 and "başarısız" in bad.note or "FALSE_REFUSAL" in bad.note


def test_agent_tasks_dominates_the_score_so_a_protocol_that_cannot_finish_tasks_loses():
    """Tek çağrı sondalarını geçip çok adımlı görevi bitiremeyen protokol (7B native örneği) artık öne çıkamaz."""

    class SingleShotOnly(Perfect):
        def chat(self, messages, tools=None, **kw):
            user = next((m.content for m in messages if m.role == "user"), "")
            if "dosyasındaki" in user or "çalıştırma komutunu" in user or "ilk kelimesini" in user:
                return ModelResponse(
                    '{"name": "read_file", "arguments": {"path": "x"}}', []
                )  # çağrıyı metne yazar
            return super().chat(messages, tools)

    a = capability.run_protocol(SingleShotOnly(), "native", {"repeats": 1})
    b = capability.probe_agent_tasks(E2EModel("compliant"), {})
    agent = next(r for r in a.results if r.name == "agent_tasks")
    assert not agent.ok and agent.passes == 0
    assert capability.WEIGHTS["agent_tasks"] == max(capability.WEIGHTS.values())
    assert b.name == "agent_tasks" and b.ok


def test_close_scores_are_decided_by_end_to_end_agent_results():
    def sc(proto, score, agent_passes):
        s = capability.ProtocolScore(proto)
        s.score = score
        s.results = [
            capability.ProbeResult("agent_tasks", agent_passes >= 2, 0, 0, "", 0, agent_passes, 3)
        ]
        return s

    # native biraz daha yüksek skorlu ama görev bitiremiyor; json yakın skorla görevleri bitiriyor
    proto, why = capability.recommend(
        {"native": sc("native", 0.80, 0), "json": sc("json", 0.76, 3), "text": sc("text", 0.5, 0)}
    )
    assert proto == "json" and "uçtan uca" in why
    # fark büyükse (skor çok düşükse) uçtan uca kanıt tek başına öne geçirmez
    proto, _ = capability.recommend(
        {"native": sc("native", 0.9, 0), "json": sc("json", 0.6, 3), "text": sc("text", 0.5, 0)}
    )
    assert proto == "native"
