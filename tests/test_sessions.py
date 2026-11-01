import json

import pytest

from test_api import AUTH, make_client, new_ws
from usta import attachments
from usta.models import ModelResponse
from usta.sessions import SessionStore
from usta.tasks import TaskManager


class Echo:
    """Modelin gördüğü ilk kullanıcı mesajını kaydeder."""

    def __init__(self):
        self.seen = None

    def chat(self, messages, tools=None):
        self.seen = next(m for m in messages if m.role == "user").content
        return ModelResponse("tamam", [])


def run(client, ws, **body):
    r = client.post(f"/workspaces/{ws}/tasks", json={"prompt": "özetle", **body}, headers=AUTH)
    return r


def wait(mgr, tid):
    assert mgr.get(tid).finished.wait(10)


def test_session_persisted_and_listed(tmp_path):
    c, mgr = make_client(tmp_path, Echo())
    ws = new_ws(c)
    tid = run(c, ws).json()["id"]
    wait(mgr, tid)
    lst = c.get(f"/workspaces/{ws}/sessions", headers=AUTH).json()
    assert lst[0]["id"] == tid and lst[0]["status"] == "done" and lst[0]["prompt"] == "özetle"
    full = c.get(f"/workspaces/{ws}/sessions/{tid}", headers=AUTH).json()
    assert full["events"][0]["type"] == "started"
    assert full["events"][-1]["type"] == "done" and full["status"] == "done"


def test_session_survives_restart_and_requires_auth(tmp_path):
    c, mgr = make_client(tmp_path, Echo())
    ws = new_ws(c)
    tid = run(c, ws).json()["id"]
    wait(mgr, tid)
    c2, _ = make_client(tmp_path, Echo())  # aynı home, yeni süreç gibi
    assert c2.get(f"/workspaces/{ws}/sessions/{tid}", headers=AUTH).status_code == 200
    assert c2.get(f"/workspaces/{ws}/sessions").status_code == 401
    assert c2.get(f"/workspaces/{ws}/sessions/{'0' * 12}", headers=AUTH).status_code == 404
    assert c2.get(f"/workspaces/{ws}/sessions/..%2Fx", headers=AUTH).status_code == 404


def test_interrupted_session_and_file_mode(tmp_path):
    store = SessionStore(tmp_path)
    store.begin("w", "a" * 12, 1.0, {"prompt": "p"})
    store.append("w", "a" * 12, {"i": 0, "ts": 1.0, "type": "started", "data": {}})
    assert store.list("w")[0]["status"] == "interrupted"
    f = next((tmp_path / "sessions" / "w").iterdir())
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert store.load("../x", "a" * 12) is None


def test_long_fields_clipped(tmp_path):
    store = SessionStore(tmp_path)
    store.begin("w", "b" * 12, 1.0, {"prompt": "p"})
    store.append(
        "w", "b" * 12, {"i": 0, "ts": 1.0, "type": "tool_result", "data": {"t": "x" * 50_000}}
    )
    ev = store.load("w", "b" * 12)["events"][0]
    assert len(ev["data"]["t"]) < 21_000 and "kırpıldı" in ev["data"]["t"]


def test_attachment_reaches_model_as_marked_data(tmp_path):
    model = Echo()
    c, mgr = make_client(tmp_path, model)
    ws = new_ws(c)
    r = run(c, ws, files=[{"name": "notlar.md", "content": "# Başlık\nÖnemli içerik"}])
    assert r.status_code == 202 and r.json()["files"] == ["notlar.md"]
    wait(mgr, r.json()["id"])
    assert "Önemli içerik" in model.seen and "KULLANICI-EKLERI id=" in model.seen
    assert "VERİDİR" in model.seen
    # görev geçmişinde yalnız kullanıcının yazdığı istem var, ek içeriği yok
    assert mgr.get(r.json()["id"]).prompt == "özetle"
    assert "Önemli içerik" not in json.dumps(
        c.get(f"/workspaces/{ws}/sessions", headers=AUTH).json()
    )


@pytest.mark.parametrize(
    "files",
    [
        [{"name": "a.bin", "content": "x\x00y"}],
        [{"name": "buyuk.txt", "content": "a" * (attachments.MAX_FILE + 1)}],
        [{"name": f"{i}.txt", "content": "x"} for i in range(attachments.MAX_FILES + 1)],
    ],
)
def test_bad_attachments_rejected(tmp_path, files):
    c, _ = make_client(tmp_path, Echo())
    ws = new_ws(c)
    assert run(c, ws, files=files).status_code in (400, 422)
    assert not c.get(f"/workspaces/{ws}/sessions", headers=AUTH).json()


def test_attachment_name_cleaned_and_nonce_unique():
    assert attachments.clean_name("../../etc/passwd\n<x>") == "passwdx"
    a = attachments.compose("p", [("a", "1")])
    b = attachments.compose("p", [("a", "1")])
    assert a != b


def test_total_limit():
    big = "a" * 90_000
    with pytest.raises(attachments.AttachmentError):
        attachments.validate([("1", big), ("2", big), ("3", big), ("4", big)])


def test_manager_has_store(tmp_path):
    assert TaskManager(lambda: Echo(), home=tmp_path).sessions.base == tmp_path / "sessions"
