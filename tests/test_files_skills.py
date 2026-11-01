import base64

import pytest

from test_api import AUTH, make_client, new_ws
from usta import skills
from usta.models import ModelResponse


def b64(s: str | bytes) -> str:
    return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()


def setup(tmp_path):
    c, mgr = make_client(tmp_path, object())
    ws = new_ws(c)
    return c, mgr, ws, tmp_path / "home" / "workspaces" / ws


def test_tree_lists_dirs_first_and_hides_internals(tmp_path):
    c, _, ws, root = setup(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x")
    (root / "b.md").write_text("yy")
    (root / ".git").mkdir()
    (root / ".usta").mkdir()
    (root / "node_modules").mkdir()
    names = [e["name"] for e in c.get(f"/workspaces/{ws}/tree", headers=AUTH).json()["entries"]]
    assert names == ["src", "b.md"]
    sub = c.get(f"/workspaces/{ws}/tree?path=src", headers=AUTH).json()["entries"]
    assert sub == [{"name": "a.py", "dir": False, "size": 1, "link": False}]
    assert c.get(f"/workspaces/{ws}/tree?path=../..", headers=AUTH).status_code == 400
    assert c.get(f"/workspaces/{ws}/tree?path=yok", headers=AUTH).status_code == 404
    assert c.get(f"/workspaces/{ws}/tree").status_code == 401


def test_symlink_out_of_workspace_is_not_readable(tmp_path):
    c, _, ws, root = setup(tmp_path)
    secret = tmp_path / "sir.txt"
    secret.write_text("gizli")
    (root / "kisayol").symlink_to(secret)
    ents = c.get(f"/workspaces/{ws}/tree", headers=AUTH).json()["entries"]
    assert ents[0]["link"] is True
    assert c.get(f"/workspaces/{ws}/files?path=kisayol", headers=AUTH).status_code == 400


def test_binary_file_not_shown(tmp_path):
    c, _, ws, root = setup(tmp_path)
    (root / "x.bin").write_bytes(b"\x00\x01\x02")
    assert c.get(f"/workspaces/{ws}/files?path=x.bin", headers=AUTH).status_code == 415


def test_import_writes_skips_existing_and_blocks_escape(tmp_path):
    c, _, ws, root = setup(tmp_path)
    (root / "var.txt").write_text("eski")
    body = {
        "files": [
            {"path": "klasor/a.md", "b64": b64("# a")},
            {"path": "var.txt", "b64": b64("yeni")},
        ]
    }
    r = c.post(f"/workspaces/{ws}/import", json=body, headers=AUTH).json()
    assert r == {"written": ["klasor/a.md"], "skipped": ["var.txt"]}
    assert (root / "var.txt").read_text() == "eski" and (
        root / "klasor" / "a.md"
    ).read_text() == "# a"
    body["overwrite"] = True
    assert c.post(f"/workspaces/{ws}/import", json=body, headers=AUTH).json()["skipped"] == []
    assert (root / "var.txt").read_text() == "yeni"
    for bad in ["../disari.txt", "/etc/x", ".git/config", ".usta/memory/NOTES.md", "a/../../b"]:
        r = c.post(
            f"/workspaces/{ws}/import",
            json={"files": [{"path": bad, "b64": b64("x")}]},
            headers=AUTH,
        )
        assert r.status_code == 400, bad
    assert not (tmp_path / "home" / "disari.txt").exists()
    assert (
        c.post(
            f"/workspaces/{ws}/import", json={"files": [{"path": "k", "b64": "!!"}]}, headers=AUTH
        ).status_code
        == 400
    )


def test_import_refused_while_task_running(tmp_path):
    import threading

    gate = threading.Event()

    class Slow:
        def chat(self, messages, tools=None):
            gate.wait(10)
            return ModelResponse("ok", [])

    c, _ = make_client(tmp_path, Slow())
    ws = new_ws(c)
    c.post(f"/workspaces/{ws}/tasks", json={"prompt": "p"}, headers=AUTH)
    r = c.post(
        f"/workspaces/{ws}/import", json={"files": [{"path": "a", "b64": b64("x")}]}, headers=AUTH
    )
    gate.set()
    assert r.status_code == 409


def test_skills_crud_and_expand(tmp_path):
    c, _, _, _ = setup(tmp_path)
    home = tmp_path / "home"
    assert (
        c.put(
            "/skills/inceleme", json={"content": "# Kod incele\nHataları ara."}, headers=AUTH
        ).status_code
        == 200
    )
    assert c.get("/skills", headers=AUTH).json()[0] == {
        "name": "inceleme",
        "description": "Kod incele",
        "size": 26,
    }
    assert (
        skills.expand(home, "/inceleme src/a.py")
        == "# Kod incele\nHataları ara.\n\nGörev: src/a.py"
    )
    assert skills.expand(home, "/bilinmez x") == "/bilinmez x"
    assert skills.expand(home, "normal istem") == "normal istem"
    assert c.put("/skills/Kotu Ad", json={"content": "x"}, headers=AUTH).status_code in (400, 404)
    assert c.put("/skills/..%2Fx", json={"content": "x"}, headers=AUTH).status_code in (400, 404)
    assert c.delete("/skills/inceleme", headers=AUTH).status_code == 200
    assert c.delete("/skills/inceleme", headers=AUTH).status_code == 404
    assert c.get("/skills").status_code == 401


def test_skill_used_when_task_started(tmp_path):
    seen = []

    class Rec:
        def chat(self, messages, tools=None):
            seen.append(next(m for m in messages if m.role == "user").content)
            return ModelResponse("tamam", [])

    c, mgr = make_client(tmp_path, Rec())
    ws = new_ws(c)
    c.put("/skills/ozet", json={"content": "Kısa özet yaz."}, headers=AUTH)
    tid = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "/ozet README"}, headers=AUTH).json()[
        "id"
    ]
    assert mgr.get(tid).finished.wait(10)
    assert "Kısa özet yaz." in seen[0] and "README" in seen[0]


def test_skill_name_traversal_rejected(tmp_path):
    with pytest.raises(skills.SkillError):
        skills.put(tmp_path, "../kotu", "x")
    assert skills.read(tmp_path, "../kotu") is None


def fs(c, ws, **body):
    return c.post(f"/workspaces/{ws}/fs", json=body, headers=AUTH)


def test_fs_create_rename_delete(tmp_path):
    c, _, ws, root = setup(tmp_path)
    assert fs(c, ws, op="create_file", path="yeni/not.md").status_code == 200
    assert (root / "yeni" / "not.md").is_file()
    assert fs(c, ws, op="create_file", path="yeni/not.md").status_code == 409
    assert fs(c, ws, op="create_dir", path="bos").status_code == 200 and (root / "bos").is_dir()
    assert fs(c, ws, op="rename", path="yeni/not.md", to="yeni/not2.md").status_code == 200
    assert (root / "yeni" / "not2.md").is_file() and not (root / "yeni" / "not.md").exists()
    (root / "var.txt").write_text("x")
    assert fs(c, ws, op="rename", path="yeni/not2.md", to="var.txt").status_code == 409
    assert fs(c, ws, op="rename", path="yok", to="baska").status_code == 404
    assert fs(c, ws, op="delete", path="yeni").status_code == 200 and not (root / "yeni").exists()
    assert fs(c, ws, op="delete", path="yeni").status_code == 404
    audit = (tmp_path / "home" / "audit" / f"{ws}.jsonl").read_text()
    assert '"fs_op"' in audit and "create_dir" in audit


@pytest.mark.parametrize(
    "path",
    ["../x", "/etc/passwd", ".git/config", ".usta/memory/NOTES.md", "a/../../b", ".", ""],
)
def test_fs_blocks_escapes_and_internals(tmp_path, path):
    c, _, ws, _ = setup(tmp_path)
    for op in ("create_file", "create_dir", "delete"):
        r = fs(c, ws, op=op, path=path)
        assert r.status_code in (400, 422), (op, path)
    assert fs(c, ws, op="rename", path="a", to=path).status_code in (400, 404, 422)


def test_fs_delete_symlink_never_touches_target(tmp_path):
    c, _, ws, root = setup(tmp_path)
    outside = tmp_path / "disarida"
    outside.mkdir()
    (outside / "onemli.txt").write_text("kalmali")
    (root / "kisayol").symlink_to(outside)
    assert fs(c, ws, op="delete", path="kisayol").status_code == 200
    assert (outside / "onemli.txt").read_text() == "kalmali" and not (root / "kisayol").is_symlink()
    # bağın içinden dışarıya yazma/oluşturma da olmaz
    (root / "kisayol2").symlink_to(outside)
    assert fs(c, ws, op="create_file", path="kisayol2/yeni.txt").status_code == 400
    assert not (outside / "yeni.txt").exists()


def test_fs_requires_auth_and_idle(tmp_path):
    c, _, ws, _ = setup(tmp_path)
    assert c.post(f"/workspaces/{ws}/fs", json={"op": "delete", "path": "a"}).status_code == 401


def preview_base(c, ws):
    return c.get(f"/workspaces/{ws}/preview", headers=AUTH).json()["base"]


def test_preview_serves_static_files_sandboxed(tmp_path):
    c, _, ws, root = setup(tmp_path)
    (root / "index.html").write_text("<h1>Selam</h1>")
    (root / "s.css").write_text("body{}")
    (root / "app.js").write_text("1")
    base = preview_base(c, ws)
    r = c.get(base)  # dizin → index.html, kimlik başlığı gerekmez (anahtar yeter)
    assert (
        r.status_code == 200
        and "Selam" in r.text
        and r.headers["content-type"].startswith("text/html")
    )
    assert "sandbox" in r.headers["content-security-policy"]
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert c.get(base + "s.css").headers["content-type"].startswith("text/css")
    assert c.get(base + "app.js").headers["content-type"].startswith("text/javascript")
    assert c.get(base + "yok.html").status_code == 404
    assert c.get(f"/workspaces/{ws}/preview").status_code == 401  # anahtarı almak kimlik ister


def test_preview_key_bound_to_workspace_and_blocks_escapes(tmp_path):
    c, _, ws, root = setup(tmp_path)
    ws2 = new_ws(c, "baska")
    (root / "index.html").write_text("a")
    (tmp_path / "home" / "workspaces" / ws2 / "index.html").write_text("b")
    base = preview_base(c, ws)
    key = base.split("/")[3]
    assert c.get(f"/preview/{ws2}/{key}/index.html").status_code == 403  # başka alana taşınamaz
    assert c.get(f"/preview/{ws}/yanlis/index.html").status_code == 403
    (tmp_path / "sir.txt").write_text("gizli")
    (root / "kisayol.txt").symlink_to(tmp_path / "sir.txt")
    assert c.get(base + "kisayol.txt").status_code == 404
    assert c.get(base + "..%2F..%2Fsir.txt").status_code in (400, 404)
    (root / ".usta").mkdir()
    (root / ".usta" / "x.txt").write_text("hafiza")
    assert c.get(base + ".usta/x.txt").status_code == 404
    (root / ".git").mkdir()
    assert c.get(base + ".git/config").status_code == 404


def test_preview_size_cap(tmp_path, monkeypatch):
    from usta import api as api_mod

    monkeypatch.setattr(api_mod, "PREVIEW_MAX", 10)
    c, _, ws, root = setup(tmp_path)
    (root / "big.txt").write_text("x" * 50)
    assert c.get(preview_base(c, ws) + "big.txt").status_code == 413


def test_preview_index_html_symlink_cannot_leak_outside_files(tmp_path):
    c, _, ws, root = setup(tmp_path)
    secret = tmp_path / "sir.txt"
    secret.write_text("DISARIDAKI-SIR")
    (root / "site").mkdir()
    (root / "site" / "index.html").symlink_to(secret)
    r = c.get(preview_base(c, ws) + "site/")
    assert r.status_code == 404 and "DISARIDAKI-SIR" not in r.text


def test_preview_csp_has_no_forms_or_popups(tmp_path):
    c, _, ws, root = setup(tmp_path)
    (root / "index.html").write_text("<p>x</p>")
    csp = c.get(preview_base(c, ws)).headers["content-security-policy"]
    assert "allow-forms" not in csp and "allow-popups" not in csp and "form-action 'none'" in csp
