"""Yerel model bulma ve bağlam varyantı: yalnız loopback, geçersiz girişler reddedilir."""

import httpx
import pytest

from test_api import AUTH, Scripted, make_client
from usta import localmodels


def _fake_get(models_by_port):
    def get(url, timeout=None, **kw):
        port = int(url.split(":")[2].split("/")[0])
        assert url.startswith("http://127.0.0.1:")  # yalnız loopback
        req = httpx.Request("GET", url)
        if port not in models_by_port:
            raise httpx.ConnectError("kapalı", request=req)
        return httpx.Response(
            200, json={"data": [{"id": m} for m in models_by_port[port]]}, request=req
        )

    return get


def test_scan_finds_only_responding_common_ports(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get({11434: ["qwen2.5-coder:7b"]}))
    found = localmodels.scan()
    assert [(f["port"], f["name"], f["models"]) for f in found] == [
        (11434, "Ollama", ["qwen2.5-coder:7b"])
    ]
    assert found[0]["endpoint"] == "http://127.0.0.1:11434/v1"


def test_scan_single_port_and_invalid_ports(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get({9999: ["x"]}))
    assert localmodels.scan(9999)[0]["name"] == "yerel sunucu"
    for bad in (0, 70000, "80", True):
        with pytest.raises(localmodels.LocalError):
            localmodels.scan(bad)


def test_context_variant_builds_request_and_name(monkeypatch):
    sent = {}

    def post(url, json=None, timeout=None, **kw):
        sent.update(url=url, json=json)
        return httpx.Response(200, json={"status": "success"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    assert localmodels.context_variant(11434, "qwen2.5-coder:7b", 16384) == (
        "qwen2.5-coder-ctx16384:7b"
    )
    assert sent["url"] == "http://127.0.0.1:11434/api/create"
    assert sent["json"]["from"] == "qwen2.5-coder:7b"
    assert sent["json"]["parameters"] == {"num_ctx": 16384}


def test_context_variant_rejects_bad_input_and_reports_failure(monkeypatch):
    with pytest.raises(localmodels.LocalError):
        localmodels.context_variant(11434, "../etc/passwd", 8192)
    with pytest.raises(localmodels.LocalError):
        localmodels.context_variant(11434, "m", 10)

    def boom(url, **kw):
        raise httpx.ConnectError("kapalı", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(localmodels.LocalError, match="oluşturulamadı"):
        localmodels.context_variant(11434, "m", 8192)


def test_local_endpoints_require_auth_and_validate(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get({1234: ["lm"]}))
    c, _ = make_client(tmp_path, Scripted())
    assert c.post("/local/scan", json={}).status_code == 401
    r = c.post("/local/scan", json={}, headers=AUTH)
    assert r.status_code == 200 and r.json()[0]["port"] == 1234
    assert c.post("/local/scan", json={"port": 99999}, headers=AUTH).status_code == 422
    assert (
        c.post(
            "/local/context", json={"port": 11434, "model": "m", "num_ctx": 5}, headers=AUTH
        ).status_code
        == 422
    )
