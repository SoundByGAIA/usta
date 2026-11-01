import threading

import pytest

from test_api import AUTH, make_client, new_ws
from usta.modelctl import ModelControl, ModelSwitchError
from usta.models import ModelResponse, ToolCall


class Gated:
    """İlk çağrıda bekler; sonraki çağrılarda gördüğü kullanıcı mesajlarını kaydeder."""

    def __init__(self):
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.n = 0
        self.users: list[str] = []

    def chat(self, messages, tools=None):
        self.n += 1
        self.users = [m.content for m in messages if m.role == "user"]
        if self.n == 1:
            self.entered.set()
            self.gate.wait(10)
            return ModelResponse(None, [ToolCall("c1", "list_dir", {"path": "."})])
        return ModelResponse("bitti", [])


def test_message_during_task_reaches_model(tmp_path):
    model = Gated()
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    tid = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "başla"}, headers=AUTH).json()["id"]
    assert model.entered.wait(5)
    r = c.post(f"/tasks/{tid}/messages", json={"text": "aslında şunu yap"}, headers=AUTH)
    assert r.status_code == 202
    model.gate.set()
    assert mgr.get(tid).finished.wait(10)
    assert any("aslında şunu yap" in u for u in model.users)
    assert any(e["type"] == "user_message" for e in mgr.get(tid).events)
    # bitmiş göreve mesaj gönderilemez, kimlik gerekir
    assert c.post(f"/tasks/{tid}/messages", json={"text": "x"}, headers=AUTH).status_code == 409
    assert c.post(f"/tasks/{tid}/messages", json={"text": "x"}).status_code == 401
    assert c.post("/tasks/yok/messages", json={"text": "x"}, headers=AUTH).status_code == 404


def test_message_posted_while_finishing_is_not_lost(tmp_path):
    """Model son yanıtı verirken gelen mesaj görevi bitirmez, ajan ona da bakar."""

    class Late:
        def __init__(self, task):
            self.n, self.task, self.seen = 0, task, []

        def chat(self, messages, tools=None):
            self.n += 1
            self.seen = [m.content for m in messages if m.role == "user"]
            if self.n == 1:
                self.task[0].post("son dakika")
            return ModelResponse(f"yanıt {self.n}", [])

    holder: list = []
    model = Late(holder)
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    orig = mgr.start

    def start(*a, **k):
        t = orig(*a, **k)
        holder.append(t)
        return t

    mgr.start = start
    tid = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "p"}, headers=AUTH).json()["id"]
    assert mgr.get(tid).finished.wait(10)
    assert model.n == 2 and any("son dakika" in u for u in model.seen)


class FakeClient:
    def __init__(self, name):
        self.name = name


def control(tmp_path, models=("a", "b"), **kw):
    built = []

    def build(ep, nm, pr, key=None):
        built.append((nm, pr, key))
        return FakeClient(nm)

    ctl = ModelControl(
        tmp_path, "http://x/v1", "a", "native", build, lambda ep, key=None: list(models), **kw
    )
    return ctl, built


def test_switch_changes_client_and_persists(tmp_path):
    from usta import settings

    ctl, _ = control(tmp_path, explicit_protocol="json")
    out = ctl.switch("b")
    assert out["model"] == "b" and ctl.current().name == "b" and ctl.protocol == "json"
    assert settings.load(tmp_path).model == "b"


def test_switch_rejects_unlisted_model(tmp_path):
    ctl, _ = control(tmp_path, explicit_protocol="native")
    with pytest.raises(ModelSwitchError):
        ctl.switch("../etc")
    assert ctl.name == "a"


def test_model_api(tmp_path):
    c, mgr = make_client(tmp_path, Gated())
    assert c.get("/model", headers=AUTH).status_code == 404  # kontrol yoksa
    ctl, _ = control(tmp_path, explicit_protocol="native")
    mgr.model_control = ctl
    assert c.get("/model", headers=AUTH).json()["models"] == ["a", "b"]
    assert c.get("/model").status_code == 401
    assert c.put("/model", json={"model": "b"}, headers=AUTH).json()["model"] == "b"
    assert c.put("/model", json={"model": "zzz"}, headers=AUTH).status_code == 400


def test_model_switch_blocked_while_task_runs(tmp_path):
    model = Gated()
    c, mgr = make_client(tmp_path, model)
    mgr.model_control = control(tmp_path, explicit_protocol="native")[0]
    ws = new_ws(c)
    c.post(f"/workspaces/{ws}/tasks", json={"prompt": "p"}, headers=AUTH)
    assert model.entered.wait(5)
    assert c.put("/model", json={"model": "b"}, headers=AUTH).status_code == 409
    model.gate.set()


class Rec:
    def __init__(self, *answers):
        self.answers, self.users = list(answers), []

    def chat(self, messages, tools=None):
        self.users.append([m.content for m in messages if m.role == "user"])
        return ModelResponse(self.answers.pop(0), [])


def test_apply_plan_sends_plan_once_by_id_without_repeating_the_task(tmp_path):
    big_task = "ÇOK UZUN GÖREV " * 200
    model = Rec("PLAN: 1) a 2) b", "uygulandı")
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    plan = c.post(
        f"/workspaces/{ws}/tasks", json={"prompt": big_task, "mode": "plan"}, headers=AUTH
    ).json()["id"]
    assert mgr.get(plan).finished.wait(10)
    r = c.post(
        f"/workspaces/{ws}/tasks",
        json={"prompt": "Planı uygula", "mode": "manual", "apply_plan": plan},
        headers=AUTH,
    )
    assert r.status_code == 202 and r.json()["plan_of"] == plan
    tid = r.json()["id"]
    assert mgr.get(tid).finished.wait(10)
    sent = model.users[1][0]
    assert sent.count("PLAN: 1) a 2) b") == 1 and "ÇOK UZUN GÖREV" not in sent
    assert "ONAYLI-PLAN id=" in sent and len(sent) < 600
    # görünen/saklanan istem kısa kalır; plan metni tekrar saklanmaz
    assert mgr.get(tid).prompt == "Planı uygula"
    sess = c.get(f"/workspaces/{ws}/sessions", headers=AUTH).json()
    assert sess[0]["prompt"] == "Planı uygula"


def test_apply_plan_rejects_non_plan_unknown_and_other_workspace(tmp_path):
    model = Rec("normal yanıt", "x", "y")
    c, mgr = make_client(tmp_path, model)
    ws, ws2 = new_ws(c), new_ws(c, "baska")
    normal = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "p"}, headers=AUTH).json()["id"]
    assert mgr.get(normal).finished.wait(10)
    for plan_id, wsx in [(normal, ws), ("0" * 12, ws)]:
        r = c.post(
            f"/workspaces/{wsx}/tasks",
            json={"prompt": "Planı uygula", "apply_plan": plan_id},
            headers=AUTH,
        )
        assert r.status_code == 404
    p = c.post(
        f"/workspaces/{ws}/tasks", json={"prompt": "q", "mode": "plan"}, headers=AUTH
    ).json()["id"]
    assert mgr.get(p).finished.wait(10)
    r = c.post(
        f"/workspaces/{ws2}/tasks", json={"prompt": "Planı uygula", "apply_plan": p}, headers=AUTH
    )
    assert r.status_code == 404  # başka çalışma alanının planı uygulanamaz
    assert (
        c.post(
            f"/workspaces/{ws}/tasks", json={"prompt": "x", "apply_plan": "../x"}, headers=AUTH
        ).status_code
        == 422
    )


def test_apply_plan_survives_restart(tmp_path):
    model = Rec("kalıcı plan metni")
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    p = c.post(
        f"/workspaces/{ws}/tasks", json={"prompt": "q", "mode": "plan"}, headers=AUTH
    ).json()["id"]
    assert mgr.get(p).finished.wait(10)
    model2 = Rec("uygulandı")
    c2, mgr2 = make_client(tmp_path, model2)  # aynı home, yeni süreç
    r = c2.post(
        f"/workspaces/{ws}/tasks", json={"prompt": "Planı uygula", "apply_plan": p}, headers=AUTH
    )
    assert r.status_code == 202
    assert mgr2.get(r.json()["id"]).finished.wait(10)
    assert "kalıcı plan metni" in model2.users[0][0]
