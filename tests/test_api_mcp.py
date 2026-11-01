import sys
from pathlib import Path

from test_api import AUTH, Scripted, make_client
from usta import mcpcatalog, mcpconfig

FAKE = str(Path(__file__).parent / "fake_mcp.py")


def setup(tmp_path):
    c, mgr = make_client(tmp_path, Scripted())
    return c, tmp_path / "home", mgr


def test_requires_auth_everywhere(tmp_path):
    c, _, _ = setup(tmp_path)
    for method, url in [
        ("get", "/mcp"),
        ("post", "/mcp/catalog/brave-search"),
        ("put", "/mcp/x/secrets/KEY"),
        ("post", "/mcp/x/enabled"),
        ("delete", "/mcp/x"),
        ("post", "/mcp/x/test"),
    ]:
        assert getattr(c, method)(url).status_code == 401, url


def test_catalog_entries_are_valid_and_pinned_to_known_commands():
    assert mcpcatalog.CATALOG, "en az bir katalog girdisi olmalı"
    for e in mcpcatalog.CATALOG:
        mcpconfig.validate(e.id, list(e.command), list(e.env), "ask")
        assert e.title and e.description and e.homepage.startswith("https://")


def test_list_shows_catalog_and_empty_servers(tmp_path):
    c, _, _ = setup(tmp_path)
    d = c.get("/mcp", headers=AUTH).json()
    assert d["servers"] == []
    assert {x["id"] for x in d["catalog"]} >= {"brave-search"}
    assert all(set(x) >= {"id", "title", "description", "env", "added"} for x in d["catalog"])


def test_add_from_catalog_only_with_ask_mode_and_no_free_commands(tmp_path):
    c, home, _ = setup(tmp_path)
    r = c.post("/mcp/catalog/brave-search", headers=AUTH)
    assert r.status_code == 201
    s = mcpconfig.load(home)["brave-search"]
    assert s.approve == "ask" and s.enabled
    entry = next(e for e in mcpcatalog.CATALOG if e.id == "brave-search")
    assert s.command == entry.command and s.env == entry.env
    assert c.post("/mcp/catalog/brave-search", headers=AUTH).status_code == 409
    assert c.post("/mcp/catalog/yok", headers=AUTH).status_code == 404
    # serbest komut ekleme yolu YOK
    assert c.post(
        "/mcp", json={"name": "x", "command": ["sh", "-c", "id"]}, headers=AUTH
    ).status_code in (404, 405)
    assert c.post(
        "/mcp/catalog/brave-search", json={"command": ["sh"]}, headers=AUTH
    ).status_code in (201, 409, 422)
    assert mcpconfig.load(home)["brave-search"].command == entry.command


def test_list_reports_secret_state_but_never_values(tmp_path):
    c, home, _ = setup(tmp_path)
    c.post("/mcp/catalog/brave-search", headers=AUTH)
    key = mcpcatalog.CATALOG[0].env[0]
    d = c.get("/mcp", headers=AUTH).json()["servers"][0]
    assert d["env"] == [{"name": key, "set": False}]
    r = c.put(f"/mcp/brave-search/secrets/{key}", json={"value": "cok-gizli-xyz"}, headers=AUTH)
    assert r.status_code == 200 and "cok-gizli-xyz" not in r.text
    got = c.get("/mcp", headers=AUTH)
    assert "cok-gizli-xyz" not in got.text and got.json()["servers"][0]["env"][0]["set"] is True
    assert "cok-gizli-xyz" not in (home / "mcp.json").read_text()


def test_secret_validation(tmp_path):
    c, _, _ = setup(tmp_path)
    c.post("/mcp/catalog/brave-search", headers=AUTH)
    key = mcpcatalog.CATALOG[0].env[0]
    assert c.put(
        f"/mcp/brave-search/secrets/{key}", json={"value": ""}, headers=AUTH
    ).status_code in (400, 422)
    assert (
        c.put(
            "/mcp/brave-search/secrets/BASKA_ANAHTAR", json={"value": "x"}, headers=AUTH
        ).status_code
        == 404
    )
    assert c.put(f"/mcp/yok/secrets/{key}", json={"value": "x"}, headers=AUTH).status_code == 404
    assert c.put(
        f"/mcp/brave-search/secrets/{key}", json={"value": "x" * 9000}, headers=AUTH
    ).status_code in (400, 422)


def test_enable_disable_and_remove(tmp_path):
    c, home, _ = setup(tmp_path)
    c.post("/mcp/catalog/brave-search", headers=AUTH)
    assert (
        c.post("/mcp/brave-search/enabled", json={"enabled": False}, headers=AUTH).status_code
        == 200
    )
    assert mcpconfig.load(home)["brave-search"].enabled is False
    assert c.post("/mcp/yok/enabled", json={"enabled": True}, headers=AUTH).status_code == 404
    assert c.delete("/mcp/brave-search", headers=AUTH).status_code == 200
    assert mcpconfig.load(home) == {}
    assert c.delete("/mcp/brave-search", headers=AUTH).status_code == 404


def test_test_endpoint_lists_tools_or_reports_friendly_error(tmp_path):
    c, home, _ = setup(tmp_path)
    mcpconfig.add_server(home, "fake", [sys.executable, "-I", FAKE])
    mcpconfig.add_server(home, "kirik", ["/yok/komut"])
    ok = c.post("/mcp/fake/test", headers=AUTH)
    assert ok.status_code == 200 and "echo" in [t["name"] for t in ok.json()["tools"]]
    assert all(len(t["description"]) <= 200 for t in ok.json()["tools"])
    bad = c.post("/mcp/kirik/test", headers=AUTH)
    assert bad.status_code == 502 and "bulunamadı" in bad.json()["detail"]
    assert c.post("/mcp/yok/test", headers=AUTH).status_code == 404


def test_bad_server_name_in_path_is_rejected(tmp_path):
    c, _, _ = setup(tmp_path)
    for bad in ["A", "a b", "x" * 40, "a__b"]:
        assert c.delete(f"/mcp/{bad}", headers=AUTH).status_code in (404, 422)


def test_corrupt_config_is_a_clean_error(tmp_path):
    c, home, _ = setup(tmp_path)
    home.mkdir(exist_ok=True)
    (home / "mcp.json").write_text("{bozuk")
    r = c.get("/mcp", headers=AUTH)
    assert r.status_code == 500 and "mcp.json" in r.json()["detail"]


def test_task_manager_picks_up_servers_added_after_startup(tmp_path):
    from usta.models import ModelResponse
    from usta.tasks import TaskManager

    home = tmp_path / "home"
    seen = []

    class Model:
        def chat(self, messages, tools=None):
            seen.append([t["name"] for t in tools or []])
            return ModelResponse("ok")

    m = TaskManager(
        lambda: Model(), home=home, mcp_servers=lambda: list(mcpconfig.load(home).values())
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    assert m.start("w1", ws, "a").finished.wait(10)
    mcpconfig.add_server(home, "fake", [sys.executable, "-I", FAKE])
    assert m.start("w1", ws, "b").finished.wait(15)
    assert "mcp__fake__echo" not in seen[0] and "mcp__fake__echo" in seen[1]
