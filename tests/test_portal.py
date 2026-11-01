import httpx
import pytest
from fastapi.testclient import TestClient

from usta.api import create_app
from usta.auth import LoginCodes
from usta.models import ModelResponse
from usta.portal import Portal
from usta.tasks import TaskManager


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- tek kullanımlık giriş kodları ---------------------------------------------------------
def test_code_is_single_use():
    c = LoginCodes()
    code = c.issue()
    assert len(code) >= 20
    assert c.redeem(code) is True
    assert c.redeem(code) is False


def test_code_expires():
    clock = Clock()
    c = LoginCodes(ttl=60, clock=clock)
    code = c.issue()
    clock.t += 61
    assert c.redeem(code) is False


def test_new_code_invalidates_previous():
    c = LoginCodes()
    a = c.issue()
    b = c.issue()
    assert c.redeem(a) is False and c.redeem(b) is True


def test_wrong_codes_lock_out_even_the_valid_one():
    c = LoginCodes(max_failures=3)
    code = c.issue()
    for _ in range(3):
        assert c.redeem("yanlis") is False
    assert c.redeem(code) is False and c.locked


def test_non_string_and_empty_codes_rejected():
    c = LoginCodes()
    c.issue()
    for bad in ("", None, 5, "a" * 10_000):
        assert c.redeem(bad) is False


# --- API ucu ------------------------------------------------------------------------------
def client(tmp_path, codes):
    home = tmp_path / "home"
    mgr = TaskManager(
        lambda: type("M", (), {"chat": lambda s, m, t=None: ModelResponse("x")})(), home=home
    )
    return TestClient(create_app(mgr, home, "gizli-jeton-123456", login=codes))


def test_exchange_gives_token_once(tmp_path):
    codes = LoginCodes()
    c = client(tmp_path, codes)
    code = codes.issue()
    r = c.post("/auth/exchange", json={"code": code})
    assert r.status_code == 200 and r.json() == {"token": "gizli-jeton-123456"}
    assert c.post("/auth/exchange", json={"code": code}).status_code == 401
    assert (
        c.get("/workspaces", headers={"Authorization": "Bearer gizli-jeton-123456"}).status_code
        == 200
    )


def test_exchange_rejects_garbage_and_never_leaks_token(tmp_path):
    codes = LoginCodes(max_failures=2)
    c = client(tmp_path, codes)
    codes.issue()
    for body in ({"code": "yanlis"}, {"code": 5}, {}, {"kod": "x"}):
        r = c.post("/auth/exchange", json=body)
        assert r.status_code in (401, 422) and "gizli-jeton" not in r.text


def test_exchange_absent_without_login_object(tmp_path):
    home = tmp_path / "home"
    mgr = TaskManager(lambda: None, home=home)
    c = TestClient(create_app(mgr, home, "t" * 20))
    assert c.post("/auth/exchange", json={"code": "x"}).status_code == 404


# --- gerçek sunucu iş parçacığı ------------------------------------------------------------
def test_portal_serves_and_stops_cleanly(tmp_path):
    mgr = TaskManager(lambda: None, home=tmp_path / "home")
    p = Portal(mgr, tmp_path / "home", "jeton-" + "x" * 20)
    url = p.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        assert httpx.get(url, timeout=5).status_code == 200
        login = p.login_url()
        assert login.startswith(url) and "code=" in login
        code = login.split("code=")[1]
        r = httpx.post(url + "auth/exchange", json={"code": code}, timeout=5)
        assert r.status_code == 200 and r.json()["token"].startswith("jeton-")
        assert httpx.post(url + "auth/exchange", json={"code": code}, timeout=5).status_code == 401
    finally:
        p.stop()
    with pytest.raises(httpx.HTTPError):
        httpx.get(url, timeout=2)


def test_portal_binds_loopback_only_and_falls_back_when_port_busy(tmp_path):
    import socket

    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    mgr = TaskManager(lambda: None, home=tmp_path / "home")
    p = Portal(mgr, tmp_path / "home", "j" * 24, preferred_port=port)
    try:
        url = p.start()
        assert f":{port}/" not in url and "127.0.0.1" in url
    finally:
        p.stop()
        busy.close()


def test_login_page_hides_code_from_argv_and_is_private_and_expires(tmp_path):
    import os
    import stat
    import time
    from pathlib import Path
    from urllib.parse import urlparse

    from test_api import Scripted
    from usta.portal import Portal
    from usta.tasks import TaskManager

    home = tmp_path / "home"
    p = Portal(TaskManager(lambda: Scripted(), home=home), home, "tok")
    p.start()
    try:
        uri = p.login_page(ttl=0.3)
        assert (
            uri.startswith("file://") and "code=" not in uri
        )  # komut satırına giren adreste kod yok
        path = Path(urlparse(uri).path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert "code=" in path.read_text() and 'http-equiv="refresh"' in path.read_text()
        time.sleep(0.8)
        assert not path.exists()  # kısa sürede silinir
    finally:
        p.stop()


def test_portal_rejects_foreign_host_header_dns_rebinding(tmp_path):
    import httpx

    from test_api import Scripted
    from usta.portal import Portal
    from usta.tasks import TaskManager

    home = tmp_path / "home"
    p = Portal(TaskManager(lambda: Scripted(), home=home), home, "tok")
    url = p.start()
    try:
        assert httpx.get(url).status_code == 200
        assert httpx.get(url, headers={"Host": "saldirgan.example"}).status_code == 400
        assert (
            httpx.get(
                url, headers={"Host": "localhost:" + url.split(":")[-1].strip("/")}
            ).status_code
            == 200
        )
    finally:
        p.stop()
