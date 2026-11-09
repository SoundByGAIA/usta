import json
import threading

import pytest
from fastapi.testclient import TestClient

from usta.api import create_app, load_or_create_token
from usta.models import ModelResponse, ToolCall
from usta.tasks import TaskManager

TOKEN = "test-jetonu-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Scripted:
    def __init__(self, *responses, gate=None):
        self.responses, self.gate = list(responses), gate

    def chat(self, messages, tools=None):
        if self.gate is not None:
            self.gate.wait(10)
        return self.responses.pop(0)


def call(name, args, id="c1"):
    return ModelResponse(None, [ToolCall(id, name, args)])


def make_client(tmp_path, model, **kw):
    home = tmp_path / "home"
    mgr = TaskManager(lambda: model, home=home, **kw)
    return TestClient(create_app(mgr, home, TOKEN)), mgr


def sse(client, url):
    out = []
    with client.stream("GET", url, headers=AUTH) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        cur = {}
        for line in r.iter_lines():
            if line == "":
                if cur:
                    out.append(cur)
                cur = {}
            elif not line.startswith(":"):
                k, _, v = line.partition(": ")
                cur[k] = v
    return out


def new_ws(client, name="proje"):
    r = client.post("/workspaces", json={"name": name}, headers=AUTH)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_auth_required_everywhere(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    for method, url in [
        ("get", "/workspaces"),
        ("post", "/workspaces"),
        ("get", "/tasks/x"),
        ("get", "/tasks/x/events"),
        ("post", "/approvals/x"),
        ("get", "/audit"),
    ]:
        assert getattr(c, method)(url).status_code == 401, url
        assert (
            getattr(c, method)(url, headers={"Authorization": "Bearer yanlis"}).status_code == 401
        )


def test_token_file_is_private_and_stable(tmp_path):
    t1 = load_or_create_token(tmp_path / "h")
    assert len(t1) >= 32 and ((tmp_path / "h" / "token").stat().st_mode & 0o077) == 0
    assert load_or_create_token(tmp_path / "h") == t1


def test_workspace_create_list_and_validation(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert new_ws(c) == "proje"
    assert c.post("/workspaces", json={"name": "proje"}, headers=AUTH).status_code == 409
    for bad in ["../x", "A B", "", "a/b", ".gizli", "x" * 80]:
        assert c.post("/workspaces", json={"name": bad}, headers=AUTH).status_code == 422, bad
    assert c.get("/workspaces", headers=AUTH).json() == [{"id": "proje"}]
    assert (tmp_path / "home" / "workspaces" / "proje").is_dir()


def test_unknown_workspace_404_and_bad_id_is_not_traversal(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.post("/workspaces/yok/tasks", json={"prompt": "x"}, headers=AUTH).status_code == 404
    assert c.get("/workspaces/..%2Fetc/files?path=passwd", headers=AUTH).status_code in (404, 422)


def test_files_get_put_and_escape(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    w = new_ws(c)
    assert (
        c.put(
            f"/workspaces/{w}/files?path=d/a.txt", json={"content": "selam"}, headers=AUTH
        ).status_code
        == 200
    )
    r = c.get(f"/workspaces/{w}/files?path=d/a.txt", headers=AUTH)
    assert r.json() == {"path": "d/a.txt", "content": "selam"}
    assert c.get(f"/workspaces/{w}/files?path=yok", headers=AUTH).status_code == 404
    for bad in ["../x", "/etc/passwd", ""]:
        assert (
            c.get(f"/workspaces/{w}/files", params={"path": bad}, headers=AUTH).status_code == 400
        )
        assert (
            c.put(
                f"/workspaces/{w}/files", params={"path": bad}, json={"content": "z"}, headers=AUTH
            ).status_code
            == 400
        )


def test_task_lifecycle_sse_and_diff(tmp_path):
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "merhaba\n"}), ModelResponse("yazdım")
    )
    c, _ = make_client(tmp_path, model)
    w = new_ws(c)
    r = c.post(f"/workspaces/{w}/tasks", json={"prompt": "yaz"}, headers=AUTH)
    assert r.status_code == 202
    tid = r.json()["id"]
    events = sse(c, f"/tasks/{tid}/events")
    assert [e["event"] for e in events] == [
        "started",
        "tool_call",
        "tool_result",
        "message",
        "done",
    ]
    assert [int(e["id"]) for e in events] == list(range(5))
    assert json.loads(events[-1]["data"])["status"] == "done"
    info = c.get(f"/tasks/{tid}", headers=AUTH).json()
    assert info["status"] == "done" and info["answer"] == "yazdım"
    d = c.get(f"/tasks/{tid}/diff", headers=AUTH)
    assert d.headers["content-type"].startswith("text/plain") and "+merhaba" in d.text


def test_sse_resume_with_last_event_id(tmp_path):
    c, _ = make_client(tmp_path, Scripted(ModelResponse("ok")))
    w = new_ws(c)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    all_events = sse(c, f"/tasks/{tid}/events")
    part = []
    with c.stream("GET", f"/tasks/{tid}/events", headers={**AUTH, "Last-Event-ID": "0"}) as r:
        part = [ln for ln in r.iter_lines() if ln.startswith("id: ")]
    assert part == [f"id: {e['id']}" for e in all_events[1:]]


def test_busy_workspace_409(tmp_path):
    gate = threading.Event()
    c, _ = make_client(tmp_path, Scripted(ModelResponse("a"), gate=gate))
    w = new_ws(c)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    assert c.post(f"/workspaces/{w}/tasks", json={"prompt": "y"}, headers=AUTH).status_code == 409
    assert (
        c.put(f"/workspaces/{w}/files?path=a", json={"content": "z"}, headers=AUTH).status_code
        == 409
    )
    gate.set()
    sse(c, f"/tasks/{tid}/events")


def test_cancel_endpoint(tmp_path):
    gate = threading.Event()
    c, _ = make_client(
        tmp_path, Scripted(call("write_file", {"path": "z", "content": "1"}), gate=gate)
    )
    w = new_ws(c)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    assert c.post(f"/tasks/{tid}/cancel", headers=AUTH).status_code == 202
    assert c.get(f"/tasks/{tid}", headers=AUTH).json()["status"] == "cancelling"
    gate.set()
    events = sse(c, f"/tasks/{tid}/events")
    assert json.loads(events[-1]["data"])["status"] == "cancelled"
    assert c.post("/tasks/yok/cancel", headers=AUTH).status_code == 404


def test_approval_flow_over_api(tmp_path, monkeypatch):
    monkeypatch.setattr("usta.api.KEEPALIVE", 0.3)  # akışı yarıda kesen istemci hızlı düşsün
    c, _ = make_client(tmp_path, Scripted(call("web_search", {"query": "x"}), ModelResponse("ok")))
    w = new_ws(c)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "ara"}, headers=AUTH).json()["id"]
    aid = None
    with c.stream("GET", f"/tasks/{tid}/events", headers=AUTH) as r:
        etype = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: ") and etype == "approval_required":
                aid = json.loads(line[6:])["approval_id"]
                break
    assert aid
    assert c.post(f"/approvals/{aid}", json={"decision": "maybe"}, headers=AUTH).status_code == 422
    assert c.post(f"/approvals/{aid}", json={"decision": "deny"}, headers=AUTH).status_code == 200
    assert c.post(f"/approvals/{aid}", json={"decision": "deny"}, headers=AUTH).status_code == 404
    events = sse(c, f"/tasks/{tid}/events")
    assert "denied" in [e["event"] for e in events]


def test_revert_endpoint(tmp_path):
    c, _ = make_client(
        tmp_path,
        Scripted(call("write_file", {"path": "a.txt", "content": "bozuk"}), ModelResponse("ok")),
    )
    w = new_ws(c)
    c.put(f"/workspaces/{w}/files?path=a.txt", json={"content": "orijinal"}, headers=AUTH)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    sse(c, f"/tasks/{tid}/events")
    assert c.post(f"/tasks/{tid}/revert", headers=AUTH).status_code == 200
    assert c.get(f"/workspaces/{w}/files?path=a.txt", headers=AUTH).json()["content"] == "orijinal"


def test_audit_endpoint_is_scoped_and_limited(tmp_path):
    c, _ = make_client(tmp_path, Scripted(ModelResponse("ok")))
    w = new_ws(c)
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    sse(c, f"/tasks/{tid}/events")
    rows = c.get("/audit", params={"workspace": w}, headers=AUTH).json()
    assert [r["event"] for r in rows] == [
        "task",
        "answer",
        "terminal",
    ]  # v0.2.0: terminal durum kaydı
    assert rows[-1]["state"] == "COMPLETE_NO_CHANGE"
    assert (
        c.get("/audit", params={"workspace": w, "limit": 1}, headers=AUTH).json()[0]["event"]
        == "terminal"
    )
    assert c.get("/audit", params={"workspace": "../x"}, headers=AUTH).status_code == 422
    assert c.get("/audit", params={"workspace": "yok"}, headers=AUTH).json() == []


def test_prompt_validation(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    w = new_ws(c)
    assert c.post(f"/workspaces/{w}/tasks", json={"prompt": ""}, headers=AUTH).status_code == 422
    assert (
        c.post(f"/workspaces/{w}/tasks", json={"prompt": "x" * 30000}, headers=AUTH).status_code
        == 422
    )


@pytest.mark.parametrize("path", ["/openapi.json", "/docs"])
def test_docs_not_exposed(tmp_path, path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.get(path).status_code in (401, 404)


# --- proje hafızası ----------------------------------------------------------------------
def test_memory_list_delete_and_clear(tmp_path):
    from usta import memory

    c, _ = make_client(tmp_path, Scripted())
    w = new_ws(c)
    root = tmp_path / "home" / "workspaces" / w
    assert c.get(f"/workspaces/{w}/memory", headers=AUTH).json() == {"notes": [], "history": []}
    memory.add_note(root, "a <script>x</script>")
    memory.add_note(root, "b")
    memory.append_history(root, task_id="t1", prompt="p", status="done", answer="s")
    d = c.get(f"/workspaces/{w}/memory", headers=AUTH).json()
    assert d["notes"] == ["a <script>x</script>", "b"] and d["history"][0]["task"] == "t1"
    assert c.delete(f"/workspaces/{w}/memory/notes/0", headers=AUTH).json() == {"deleted": 0}
    assert c.get(f"/workspaces/{w}/memory", headers=AUTH).json()["notes"] == ["b"]
    assert c.delete(f"/workspaces/{w}/memory/notes/5", headers=AUTH).status_code == 404
    assert c.delete(f"/workspaces/{w}/memory/notes/-1", headers=AUTH).status_code == 422
    assert c.delete(f"/workspaces/{w}/memory/history", headers=AUTH).status_code == 200
    assert c.get(f"/workspaces/{w}/memory", headers=AUTH).json()["history"] == []


def test_memory_requires_auth_known_workspace_and_idle(tmp_path):
    gate = threading.Event()
    c, _ = make_client(tmp_path, Scripted(ModelResponse("a"), gate=gate))
    w = new_ws(c)
    assert c.get(f"/workspaces/{w}/memory").status_code == 401
    assert c.delete(f"/workspaces/{w}/memory/history").status_code == 401
    assert c.get("/workspaces/yok/memory", headers=AUTH).status_code == 404
    tid = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x"}, headers=AUTH).json()["id"]
    assert c.delete(f"/workspaces/{w}/memory/notes/0", headers=AUTH).status_code == 409
    assert c.delete(f"/workspaces/{w}/memory/history", headers=AUTH).status_code == 409
    gate.set()
    sse(c, f"/tasks/{tid}/events")


def test_memory_unsafe_dir_reads_as_empty_not_500(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    w = new_ws(c)
    root = tmp_path / "home" / "workspaces" / w
    (root / ".usta").write_text("dosya")
    assert c.get(f"/workspaces/{w}/memory", headers=AUTH).json() == {"notes": [], "history": []}


def test_task_mode_accepted_and_validated(tmp_path):
    c, _ = make_client(tmp_path, Scripted(ModelResponse("plan")))
    w = new_ws(c)
    r = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x", "mode": "plan"}, headers=AUTH)
    assert r.status_code == 202 and r.json()["mode"] == "plan"
    sse(c, f"/tasks/{r.json()['id']}/events")
    assert (
        c.post(
            f"/workspaces/{w}/tasks", json={"prompt": "x", "mode": "tehlikeli"}, headers=AUTH
        ).status_code
        == 422
    )
    c2, _ = make_client(tmp_path / "b", Scripted(ModelResponse("a")))
    w2 = new_ws(c2)
    assert (
        c2.post(f"/workspaces/{w2}/tasks", json={"prompt": "x"}, headers=AUTH).json()["mode"]
        == "manual"
    )


# --- ortak ayarlar (terminal ve portal aynı config.json) ----------------------------------
def test_settings_requires_auth_and_has_defaults(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.get("/settings").status_code == 401
    d = c.get("/settings", headers=AUTH).json()
    assert d == {
        "theme": "siyah",
        "mode": "manual",
        "guard": False,
        "zoom": "auto",
        "think": "auto",
        "context_window": 0,
        "workspace": None,
    }


def test_settings_put_validates_persists_and_shares_with_terminal(tmp_path):
    from usta import settings as st

    c, _ = make_client(tmp_path, Scripted())
    assert c.put("/settings", json={"theme": "gri"}, headers=AUTH).json()["theme"] == "gri"
    assert c.put("/settings", json={"mode": "plan"}, headers=AUTH).json() == {
        "theme": "gri",
        "mode": "plan",
        "guard": False,
        "zoom": "auto",
        "think": "auto",
        "context_window": 0,
    }
    got = st.load(tmp_path / "home")
    assert (got.theme, got.mode) == ("gri", "plan")
    assert c.put("/settings", json={"theme": "pembe"}, headers=AUTH).status_code == 422
    assert c.put("/settings", json={"mode": "tehlikeli"}, headers=AUTH).status_code == 422


def test_settings_api_never_exposes_or_changes_endpoint_model_or_secrets(tmp_path):
    from usta import settings as st

    home = tmp_path / "home"
    st.save(home, st.Settings(endpoint="http://x/v1", model="gizli-model-adi"))
    c, _ = make_client(tmp_path, Scripted())
    assert "gizli-model-adi" not in c.get("/settings", headers=AUTH).text
    c.put(
        "/settings",
        json={"theme": "beyaz", "endpoint": "http://evil/v1", "model": "x"},
        headers=AUTH,
    )
    kept = st.load(home)
    assert (
        kept.endpoint == "http://x/v1" and kept.model == "gizli-model-adi" and kept.theme == "beyaz"
    )


def test_task_guard_flag_and_settings_guard(tmp_path):
    c, _ = make_client(tmp_path, Scripted(ModelResponse("a"), ModelResponse("b")))
    w = new_ws(c)
    r = c.post(f"/workspaces/{w}/tasks", json={"prompt": "x", "guard": True}, headers=AUTH)
    assert r.status_code == 202 and r.json()["guard"] is True
    sse(c, f"/tasks/{r.json()['id']}/events")
    assert c.get("/settings", headers=AUTH).json()["guard"] is False
    assert c.put("/settings", json={"guard": True}, headers=AUTH).json()["guard"] is True
    assert c.put("/settings", json={"guard": "evet"}, headers=AUTH).status_code == 422


def test_settings_zoom_roundtrip_and_validation(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.put("/settings", json={"zoom": "1.5"}, headers=AUTH).json()["zoom"] == "1.5"
    assert c.get("/settings", headers=AUTH).json()["zoom"] == "1.5"
    assert c.put("/settings", json={"zoom": "9"}, headers=AUTH).status_code == 422


def test_settings_think_and_context_roundtrip_and_validation(tmp_path):
    from usta import settings as st

    c, _ = make_client(tmp_path, Scripted())
    assert c.put("/settings", json={"think": "off"}, headers=AUTH).json()["think"] == "off"
    assert (
        c.put("/settings", json={"context_window": 16384}, headers=AUTH).json()["context_window"]
        == 16384
    )
    got = st.load(tmp_path / "home")
    assert (got.think, got.context_window) == ("off", 16384)
    assert (
        c.put("/settings", json={"context_window": 0}, headers=AUTH).json()["context_window"] == 0
    )
    assert st.load(tmp_path / "home").context_window is None
    assert c.put("/settings", json={"think": "cok"}, headers=AUTH).status_code == 422
    assert c.put("/settings", json={"context_window": 100}, headers=AUTH).status_code == 422


def test_oversized_bodies_are_rejected_before_auth_and_parsing(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    # kimliksiz bile olsa büyük gövde 413 (gövde okunmadan/ayrıştırılmadan)
    r = c.post("/auth/exchange", content=b"x" * 10_000, headers={"content-type": "text/plain"})
    assert r.status_code in (413, 404)  # login yoksa 404; limit yine de önce uygulanır
    r = c.post(
        "/workspaces",
        content=b"x" * 11_000_000,
        headers=AUTH | {"content-type": "application/json"},
    )
    assert r.status_code == 413
    ok = c.post("/workspaces", json={"name": "kucuk"}, headers=AUTH)
    assert ok.status_code == 201  # normal istekler etkilenmez


def test_chunked_oversized_body_without_content_length_is_cut(tmp_path):
    c, _ = make_client(tmp_path, Scripted())

    def gen():
        for _ in range(12):
            yield b"x" * 1_000_000

    r = c.post("/workspaces", content=gen(), headers=AUTH | {"content-type": "application/json"})
    assert r.status_code == 413
