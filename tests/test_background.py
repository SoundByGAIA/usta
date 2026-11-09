"""Arka plan kipi: pencere/terminal olmadan çalışma, tek örnek, kapatma ve masaüstü simgesi."""

import json
import sys
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from test_api import AUTH, TOKEN, Scripted, make_client
from usta import cli, compat
from usta.api import create_app
from usta.auth import LoginCodes
from usta.tasks import TaskManager


def test_is_tty_is_false_without_stdin_like_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert compat.is_tty() is False

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    assert compat.is_tty() is True


def _app(tmp_path, on_quit=None):
    mgr = TaskManager(lambda: None, home=tmp_path / "home")
    return TestClient(
        create_app(mgr, tmp_path / "home", TOKEN, login=LoginCodes(), on_quit=on_quit)
    )


def test_quit_endpoint_closes_only_in_background_mode(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.post("/quit", headers=AUTH).status_code == 404  # terminal kipi: uzaktan kapatma yok
    assert c.get("/settings", headers=AUTH).json()["background"] is False
    ev = threading.Event()
    c = _app(tmp_path, on_quit=ev.set)
    assert c.post("/quit").status_code == 401  # jetonsuz kimse kapatamaz
    assert c.get("/settings", headers=AUTH).json()["background"] is True
    assert c.post("/quit", headers=AUTH).json() == {"quit": True}
    assert ev.wait(3)  # yanıttan kısa süre sonra olay kurulur


def test_auth_code_endpoint_gives_a_redeemable_code_only_with_the_token(tmp_path):
    c = _app(tmp_path)
    assert c.post("/auth/code").status_code == 401
    code = c.post("/auth/code", headers=AUTH).json()["code"]
    assert c.post("/auth/exchange", json={"code": code}).json() == {"token": TOKEN}
    assert c.post("/auth/exchange", json={"code": code}).status_code == 401  # tek kullanım


def test_reuse_running_opens_browser_with_a_fresh_code(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "token").write_text("tok\n")
    (home / "running.json").write_text(json.dumps({"pid": 1, "port": 8765}))
    opened = []
    monkeypatch.setattr(cli, "_open_browser", lambda u: opened.append(u))

    def post(url, headers=None, timeout=None):
        assert url == "http://127.0.0.1:8765/auth/code" and headers == {
            "Authorization": "Bearer tok"
        }
        return httpx.Response(200, json={"code": "KOD123"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    assert cli._reuse_running(home, no_browser=False) is True
    assert opened == ["http://127.0.0.1:8765/?code=KOD123"]


def test_reuse_running_returns_false_when_nothing_is_running_or_it_does_not_answer(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    assert cli._reuse_running(home, no_browser=True) is False  # running.json yok
    (home / "token").write_text("tok")
    (home / "running.json").write_text(json.dumps({"pid": 1, "port": 8765}))

    def boom(url, headers=None, timeout=None):
        raise httpx.ConnectError("kapalı", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", boom)
    assert cli._reuse_running(home, no_browser=True) is False  # eski kayıt: yeni örnek başlatılır


def test_background_loop_runs_until_quit_and_cleans_up(tmp_path):
    class FakePortal:
        def __init__(self):
            self.quit, self.stopped = threading.Event(), False

        def stop(self):
            self.stopped = True

    home = tmp_path / "home"
    home.mkdir()
    p = FakePortal()
    p.quit.set()
    assert cli._background_loop(home, p, "http://127.0.0.1:8765/") == 0
    assert p.stopped and not (home / "running.json").exists()
    assert cli._background_loop(home, None, None) == 2  # portal yoksa arka planda çalışılamaz


def test_shortcut_creates_a_desktop_file_on_linux(tmp_path, monkeypatch):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux .desktop yolu")
    monkeypatch.setenv("HOME", str(tmp_path))
    path = compat.create_desktop_shortcut()
    text = (tmp_path / "Desktop" / "Usta.desktop").read_text(encoding="utf-8")
    assert (
        path.endswith("Usta.desktop") and "-m usta --arka-plan" in text and "Terminal=false" in text
    )
    assert (tmp_path / "Usta").is_dir()  # çalışma klasörü de kurulur


def test_shortcut_flag_runs_without_starting_usta(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(compat, "create_desktop_shortcut", lambda: "/masaustu/Usta.lnk")
    assert cli.main(["--kisayol"]) == 0
    assert "Usta" in capsys.readouterr().out
    monkeypatch.setattr(
        compat, "create_desktop_shortcut", lambda: (_ for _ in ()).throw(OSError("desteklenmiyor"))
    )
    assert cli.main(["--shortcut"]) == 2
