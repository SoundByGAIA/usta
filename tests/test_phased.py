import threading

import pytest

from test_api import AUTH, make_client, new_ws
from usta.models import ModelError, ModelResponse, ToolCall
from usta.tasks import PHASE_PROMPT, plan_checklist

PLAN_MD = "# Plan\n\n## Aşamalar\n- [ ] A1 — iskelet: test geçer\n- [ ] A2 — ürünler: test geçer\n- [ ] A3 — sepet: test geçer\n"


class Phased:
    """Kurulum görevinde PLAN.md yazar; aşama görevlerinde ilk işaretsiz maddeyi işaretler."""

    def __init__(self, mark=True, fail_on=None):
        self.mark, self.fail_on, self.firsts = mark, fail_on, []
        self.n_phase = 0

    def chat(self, messages, tools=None):
        first = next(m for m in messages if m.role == "user").content
        tool_msgs = [m for m in messages if m.role == "tool"]
        self.firsts.append(first)
        if "AŞAMALARA" in first:
            if not tool_msgs:
                return ModelResponse(
                    None, [ToolCall("w", "write_file", {"path": "PLAN.md", "content": PLAN_MD})]
                )
            return ModelResponse("PLAN.md yazıldı", [])
        if "PLAN.md'yi oku" in first:
            if not tool_msgs:
                self.n_phase += 1
                if self.fail_on == self.n_phase:
                    raise ModelError("sahte hata")
                return ModelResponse(None, [ToolCall("r", "read_file", {"path": "PLAN.md"})])
            if len(tool_msgs) == 1 and self.mark:
                line = next(ln for ln in tool_msgs[0].content.splitlines() if "- [ ]" in ln)
                return ModelResponse(
                    None,
                    [
                        ToolCall(
                            "e",
                            "edit_file",
                            {"path": "PLAN.md", "old": line, "new": line.replace("[ ]", "[x]")},
                        )
                    ],
                )
            return ModelResponse("aşama bitti", [])
        return ModelResponse("PLAN: 1) iskelet 2) ürünler 3) sepet", [])


def chain(mgr, first_id, limit=10):
    ids, cur = [first_id], first_id
    for _ in range(limit):
        t = mgr.get(cur)
        assert t.finished.wait(15)
        done = [e for e in t.events if e["type"] == "done"][-1]["data"]
        if not done.get("next"):
            break
        cur = done["next"]
        ids.append(cur)
    return ids


def start_phased(c, mgr, model_ws):
    plan = c.post(
        f"/workspaces/{model_ws}/tasks",
        json={"prompt": "pet shop yap", "mode": "plan"},
        headers=AUTH,
    ).json()["id"]
    assert mgr.get(plan).finished.wait(10)
    r = c.post(
        f"/workspaces/{model_ws}/tasks",
        json={"prompt": "Planı uygula", "mode": "auto", "apply_plan": plan, "phased": True},
        headers=AUTH,
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_phased_runs_each_phase_as_fresh_task_until_checklist_done(tmp_path):
    model = Phased()
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    first = start_phased(c, mgr, ws)
    ids = chain(mgr, first)
    assert len(ids) == 4  # kurulum + 3 aşama
    root = tmp_path / "home" / "workspaces" / ws
    assert plan_checklist(root) == (3, [])
    last = mgr.get(ids[-1])
    assert last.status == "done"
    assert any(
        e["type"] == "warning" and "Tüm aşamalar tamam" in e["data"]["message"] for e in last.events
    )
    # aşama görevleri taze bağlamla başlar: plan metni yeniden gönderilmez, istem kısadır
    phase_prompts = [f for f in model.firsts if "PLAN.md'yi oku" in f]
    assert len(phase_prompts) >= 3 and all(
        "pet shop" not in p and "PLAN: 1)" not in p for p in phase_prompts
    )
    assert all(PHASE_PROMPT in p for p in phase_prompts)
    # görünen istem aşamayı söyler
    assert mgr.get(ids[1]).prompt.startswith("Aşama 1/3: A1")
    assert mgr.get(ids[-1]).prompt.startswith("Aşama 3/3")


def test_phased_stops_when_no_progress(tmp_path):
    c, mgr = make_client(tmp_path, Phased(mark=False))
    ws = new_ws(c)
    ids = chain(mgr, start_phased(c, mgr, ws))
    last = mgr.get(ids[-1])
    assert len(ids) <= 4
    assert any(
        "İlerleme yok" in e["data"].get("message", "")
        for e in last.events
        if e["type"] == "warning"
    )
    assert not [e for e in last.events if e["type"] == "done"][-1]["data"].get("next")


def test_phased_stops_on_failure(tmp_path):
    c, mgr = make_client(tmp_path, Phased(fail_on=2))
    ws = new_ws(c)
    ids = chain(mgr, start_phased(c, mgr, ws))
    assert (
        mgr.get(ids[-1]).status == "failed" and len(ids) == 3
    )  # kurulum + aşama1 + hata veren aşama2
    assert plan_checklist(tmp_path / "home" / "workspaces" / ws)[0] == 1


def test_phased_cancel_stops_series(tmp_path):
    gate = threading.Event()

    class Slow(Phased):
        def chat(self, messages, tools=None):
            first = next(m for m in messages if m.role == "user").content
            if "PLAN.md'yi oku" in first:
                gate.wait(10)
            return super().chat(messages, tools)

    c, mgr = make_client(tmp_path, Slow())
    ws = new_ws(c)
    setup = start_phased(c, mgr, ws)
    nxt = [e for e in _wait_done(mgr, setup)["events"] if e["type"] == "done"][-1]["data"]["next"]
    mgr.cancel(nxt)
    gate.set()
    ids = chain(mgr, nxt)
    assert len(ids) == 1 and mgr.get(nxt).status == "cancelled"


def _wait_done(mgr, tid):
    t = mgr.get(tid)
    assert t.finished.wait(15)
    return {"events": t.events}


def test_phased_requires_plan_and_normal_apply_unchanged(tmp_path):
    c, mgr = make_client(tmp_path, Phased())
    ws = new_ws(c)
    r = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "x", "phased": True}, headers=AUTH)
    assert r.status_code == 400
    plan = c.post(
        f"/workspaces/{ws}/tasks", json={"prompt": "p", "mode": "plan"}, headers=AUTH
    ).json()["id"]
    assert mgr.get(plan).finished.wait(10)
    r = c.post(
        f"/workspaces/{ws}/tasks",
        json={"prompt": "Planı uygula", "mode": "auto", "apply_plan": plan},
        headers=AUTH,
    )
    t = mgr.get(r.json()["id"])
    assert t.finished.wait(10) and t.series is None  # aşamasız uygulama zincir kurmaz
    assert not [e for e in t.events if e["type"] == "done"][-1]["data"].get("next")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("- [ ] a\n- [x] b\n* [X] c\n  - [ ] d\n", (2, ["a", "d"])),
        ("yok", (0, [])),
    ],
)
def test_plan_checklist_parsing(tmp_path, text, expected):
    (tmp_path / "PLAN.md").write_text(text)
    assert plan_checklist(tmp_path) == expected
    assert plan_checklist(tmp_path / "yok") is None
