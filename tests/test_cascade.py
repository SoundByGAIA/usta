"""Kademeli yönlendirme: ucuz modelle başlar; kapı başarısız olunca ya da devre kesici açılınca güçlüye geçer."""

from usta import bench
from usta.cascade import CascadeModel
from usta.models import ModelResponse, Usage


class Fake:
    def __init__(self, name):
        self.name = name
        self.usage = Usage()
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        self.usage.requests += 1
        self.usage.prompt += 10
        self.usage.completion += 5
        self.usage.last_prompt = 10
        return ModelResponse(self.name)


def test_starts_cheap_and_escalates_after_failed_gate():
    cheap, strong = Fake("ucuz"), Fake("güçlü")
    c = CascadeModel(cheap, strong, empty_handed=False)
    assert c.chat([]).content == "ucuz"
    c.observe("verification", {"status": "passed"})
    assert c.chat([]).content == "ucuz"
    c.observe("verification", {"status": "failed"})
    assert c.escalated and c.chat([]).content == "güçlü"
    assert (cheap.calls, strong.calls) == (2, 1)


def test_breaker_trip_escalates_and_failures_threshold_is_respected():
    c = CascadeModel(Fake("a"), Fake("b"), after_failures=2)
    c.observe("verification", {"status": "failed"})
    assert not c.escalated
    c.observe("verification", {"status": "failed"})
    assert c.escalated
    d = CascadeModel(Fake("a"), Fake("b"), after_failures=3)
    d.observe("breaker", {"final": False})
    assert d.escalated


def test_reset_returns_to_cheap_and_usage_is_summed():
    cheap, strong = Fake("a"), Fake("b")
    c = CascadeModel(cheap, strong, empty_handed=False)
    c.chat([])
    c.observe("verification", {"status": "failed"})
    c.chat([])
    assert c.usage.requests == 2 and c.usage.prompt == 20 and c.usage.completion == 10
    c.reset()
    assert not c.escalated and c.chat([]).content == "a"


def test_x_cascade_arm_is_experimental_cascade_on_top_of_c():
    arm = bench.ARMS["X-CASCADE"]
    assert arm.cascade and arm.experimental and arm.verify
    assert not bench.ARMS["C"].cascade


def test_bench_records_escalation_and_strong_tokens(monkeypatch):
    cheap, strong = Fake("ucuz"), Fake("güçlü")
    c = CascadeModel(cheap, strong)
    task = next(t for t in bench.load_tasks() if t.id == "tiny-greeting")
    # kapı olayı yapay: ajan başlamadan yükseltme tetiklenir (bench kayıt alanlarını sınar)
    orig = c.reset

    def reset_then_fail():
        orig()
        c.observe("verification", {"status": "failed"})

    monkeypatch.setattr(c, "reset", reset_then_fail)
    r = bench.run_task(task, c, arm=bench.ARMS["X-CASCADE"])
    assert r.escalated and r.strong_tokens == strong.usage.prompt + strong.usage.completion > 0
    assert cheap.calls == 0


class Silent(Fake):
    """Araç çağırmadan "bitti" diyen zayıf model."""


def test_empty_handed_finish_is_discarded_and_asked_to_strong():
    cheap, strong = Silent("bitti"), Fake("güçlü")
    c = CascadeModel(cheap, strong)
    assert c.chat([]).content == "güçlü" and c.escalated
    assert (cheap.calls, strong.calls) == (1, 1)


def test_finish_after_an_edit_is_not_second_guessed_and_can_be_disabled():
    c = CascadeModel(Silent("bitti"), Fake("güçlü"))
    c.observe("tool_call", {"tool": "edit_file"})
    assert c.chat([]).content == "bitti" and not c.escalated
    d = CascadeModel(Silent("bitti"), Fake("güçlü"), empty_handed=False)
    assert d.chat([]).content == "bitti" and not d.escalated
