from fastapi.testclient import TestClient

from test_api import AUTH, TOKEN, Scripted
from usta import projects
from usta.api import create_app
from usta.tasks import TaskManager


def client_with_default(tmp_path):
    home = tmp_path / "home"
    user_dir = tmp_path / "Usta"
    user_dir.mkdir()
    wid = projects.register(home, user_dir)
    mgr = TaskManager(lambda: Scripted(), home=home)
    return TestClient(create_app(mgr, home, TOKEN, workspace=wid)), user_dir


def test_new_job_opens_a_named_folder_inside_the_users_usta_folder(tmp_path):
    c, user_dir = client_with_default(tmp_path)
    r = c.post(
        "/workspaces/yeni", json={"title": "Basit bir yılan oyunu web sayfası yap."}, headers=AUTH
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["name"] == "basit-bir-yilan-oyunu"
    assert (user_dir / "basit-bir-yilan-oyunu").is_dir()
    again = c.post("/workspaces/yeni", json={"title": "basit bir yılan oyunu"}, headers=AUTH).json()
    assert again["name"] == "basit-bir-yilan-oyunu-2" and again["id"] != d["id"]
    listed = {w["id"]: w["name"] for w in c.get("/workspaces", headers=AUTH).json()}
    assert listed[d["id"]] == "basit-bir-yilan-oyunu" and "Usta" in listed.values()


def test_new_job_without_words_gets_a_plain_name_and_bad_input_is_refused(tmp_path):
    c, _ = client_with_default(tmp_path)
    assert (
        c.post("/workspaces/yeni", json={"title": "???"}, headers=AUTH).json()["name"] == "yeni-is"
    )
    assert c.post("/workspaces/yeni", json={"title": ""}, headers=AUTH).status_code == 422
    assert c.post("/workspaces/yeni", json={"title": "x"}).status_code == 401
