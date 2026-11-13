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


# --- bellek, öneri, indirme -------------------------------------------------------------------
def test_recommend_by_memory_tiers():
    assert localmodels.recommend(4)["model"] is None  # çok az bellek: yerel önerilmez
    assert "internet servisi" in localmodels.recommend(4)["reason"]
    assert localmodels.recommend(8)["model"] == localmodels.MODEL_SMALL["name"]
    assert localmodels.recommend(16)["model"] == localmodels.MODEL_MEDIUM["name"]
    assert (
        localmodels.recommend(None)["model"] == localmodels.MODEL_SMALL["name"]
    )  # bilinmiyor: güvenli taraf


def test_memory_gb_reads_meminfo(monkeypatch):
    import builtins
    import io

    monkeypatch.setattr(localmodels.sys, "platform", "linux")
    real_open = builtins.open
    monkeypatch.setattr(
        builtins,
        "open",
        lambda p, *a, **k: (
            io.StringIO("MemTotal:       16777216 kB\nMemFree: 1 kB\n")
            if p == "/proc/meminfo"
            else real_open(p, *a, **k)
        ),
    )
    assert localmodels.memory_gb() == 16.0


class _FakeStream:
    def __init__(self, lines, status=200):
        self.lines, self.status_code = lines, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self.lines)


def _wait(job):
    import time

    for _ in range(100):
        if not job.snapshot()["active"]:
            return job.snapshot()
        time.sleep(0.02)
    raise AssertionError("indirme bitmedi")


def test_pull_reports_progress_and_success(monkeypatch):
    lines = [
        '{"status":"pulling manifest"}',
        '{"status":"pulling abc","total":1000,"completed":250}',
        '{"status":"pulling abc","total":1000,"completed":1000}',
        '{"status":"success"}',
    ]
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _FakeStream(lines))
    job = localmodels.PullJob()
    job.start(11434, "qwen2.5-coder:7b")
    s = _wait(job)
    assert s["done"] is True and s["error"] is None and (s["completed"], s["total"]) == (1000, 1000)


def test_pull_translates_errors_and_rejects_bad_names_and_parallel_runs(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *a, **k: _FakeStream(['{"error":"pull model manifest: file does not exist"}']),
    )
    job = localmodels.PullJob()
    job.start(11434, "yok:1b")
    assert "bulunamadı" in _wait(job)["error"]
    with pytest.raises(localmodels.LocalError):
        job.start(11434, "../kotu")
    job.state = {"active": True}
    with pytest.raises(localmodels.LocalError, match="sürüyor"):
        job.start(11434, "m:1b")


def test_system_info_and_pull_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(localmodels, "memory_gb", lambda: 8.0)
    monkeypatch.setattr(httpx, "get", _fake_get({}))  # Ollama kapalı
    c, _ = make_client(tmp_path, Scripted())
    assert c.get("/system/info").status_code == 401
    d = c.get("/system/info", headers=AUTH).json()
    assert d["ram_gb"] == 8.0 and d["ollama_running"] is False
    assert isinstance(d["docker_installed"], bool) and isinstance(d["ollama_installed"], bool)
    assert d["recommend"]["model"] == localmodels.MODEL_SMALL["name"]
    assert c.get("/local/pull", headers=AUTH).status_code == 200
    assert c.post("/local/pull", json={"model": "../x"}, headers=AUTH).status_code == 400


# --- evdeki başka bilgisayar ------------------------------------------------------------------
def _fake_lan_get(models_by_host):
    def get(url, timeout=None, **kw):
        host = url.split("//")[1].split(":")[0]
        assert url.endswith("/v1/models")  # yalnız model listesi sorulur
        req = httpx.Request("GET", url)
        if host not in models_by_host:
            raise httpx.ConnectError("kapalı", request=req)
        return httpx.Response(
            200, json={"data": [{"id": m} for m in models_by_host[host]]}, request=req
        )

    return get


@pytest.mark.parametrize(
    "text,expected",
    [
        ("192.168.1.20", ("192.168.1.20", 11434)),
        ("  192.168.1.20:1234 ", ("192.168.1.20", 1234)),
        ("http://evdeki-pc.local:11434/v1", ("evdeki-pc.local", 11434)),
        ("10.0.0.5:8080", ("10.0.0.5", 8080)),
    ],
)
def test_parse_host_accepts_common_forms(text, expected):
    assert localmodels.parse_host(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "https://192.168.1.2",
        "http://u:p@192.168.1.2",
        "192.168.1.2:99999",
        "192.168.1.2:abc",
        "a b",
        "http://192.168.1.2/v1?x=1",
        "x" * 300,
        None,
        5,
    ],
)
def test_parse_host_rejects_bad_input(text):
    with pytest.raises(localmodels.LocalError):
        localmodels.parse_host(text)


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "0.0.0.0", "224.0.0.1"])
def test_probe_host_refuses_addresses_outside_the_home_network(monkeypatch, host):
    def never(*a, **k):
        raise AssertionError("dışarıya istek atılmamalı")

    monkeypatch.setattr(httpx, "get", never)
    with pytest.raises(localmodels.LocalError, match="evdeki ağın dışında"):
        localmodels.probe_host(host)


def test_probe_host_refuses_names_that_resolve_to_public_addresses(monkeypatch):
    monkeypatch.setattr(
        localmodels.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    with pytest.raises(localmodels.LocalError, match="evdeki ağın dışında"):
        localmodels.probe_host("ornek.com")
    # bir tane bile dış adres varsa reddedilir
    monkeypatch.setattr(
        localmodels.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.1.9", 0)), (2, 1, 6, "", ("8.8.8.8", 0))],
    )
    with pytest.raises(localmodels.LocalError):
        localmodels.probe_host("karisik.local")


def test_probe_host_finds_server_and_keeps_the_typed_name(monkeypatch):
    monkeypatch.setattr(
        localmodels.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.168.1.20", 0))]
    )
    monkeypatch.setattr(httpx, "get", _fake_lan_get({"192.168.1.20": ["qwen3:8b"]}))
    found = localmodels.probe_host("evdeki-pc.local")
    assert found["endpoint"] == "http://evdeki-pc.local:11434/v1"  # yazılan ad, IP değil
    assert found["models"] == ["qwen3:8b"] and found["port"] == 11434
    monkeypatch.setattr(httpx, "get", _fake_lan_get({}))
    assert localmodels.probe_host("192.168.1.20") is None


def test_lan_scan_only_walks_the_own_private_24_on_common_ports(monkeypatch):
    seen = []

    def open_(host, port, timeout):
        seen.append((host, port))
        return (host, port) == ("192.168.1.20", 11434)

    monkeypatch.setattr(localmodels, "own_ip", lambda: "192.168.1.7")
    monkeypatch.setattr(localmodels, "_open", open_)
    monkeypatch.setattr(httpx, "get", _fake_lan_get({"192.168.1.20": ["llama3.2"]}))
    found = localmodels.lan_scan()
    assert [(f["host"], f["port"], f["name"]) for f in found] == [("192.168.1.20", 11434, "Ollama")]
    assert all(h.startswith("192.168.1.") and h != "192.168.1.7" for h, _ in seen)
    assert {p for _, p in seen} == set(localmodels.COMMON_PORTS)
    assert len(seen) == 253 * len(localmodels.COMMON_PORTS)


@pytest.mark.parametrize("me", [None, "8.8.8.8", "127.0.0.1", "169.254.3.4", "kötü"])
def test_lan_scan_does_nothing_without_a_private_address(monkeypatch, me):
    monkeypatch.setattr(localmodels, "own_ip", lambda: me)
    monkeypatch.setattr(localmodels, "_open", lambda *a: (_ for _ in ()).throw(AssertionError))
    assert localmodels.lan_scan() == []


def test_lan_endpoints_require_auth_and_explain_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(localmodels, "lan_scan", lambda: [{"host": "192.168.1.20", "port": 11434}])
    monkeypatch.setattr(httpx, "get", _fake_lan_get({"192.168.1.20": ["m"]}))
    c, _ = make_client(tmp_path, Scripted())
    assert c.post("/local/scan-lan").status_code == 401
    assert c.post("/local/probe-host", json={"host": "192.168.1.20"}).status_code == 401
    assert c.post("/local/scan-lan", headers=AUTH).json()[0]["host"] == "192.168.1.20"
    ok = c.post("/local/probe-host", json={"host": "192.168.1.20"}, headers=AUTH)
    assert ok.status_code == 200 and ok.json()["endpoint"] == "http://192.168.1.20:11434/v1"
    out = c.post("/local/probe-host", json={"host": "8.8.8.8"}, headers=AUTH)
    assert out.status_code == 400 and "evdeki ağın dışında" in out.json()["detail"]
    miss = c.post("/local/probe-host", json={"host": "192.168.1.99"}, headers=AUTH)
    assert miss.status_code == 404 and "bulamadım" in miss.json()["detail"]


# --- eksik programı kurmak ----------------------------------------------------------------------
def _wait_job(job, timeout=5.0):
    import time

    end = time.time() + timeout
    while job.snapshot().get("active") and time.time() < end:
        time.sleep(0.01)
    return job.snapshot()


def test_install_only_runs_for_listed_programs_on_windows_with_winget(monkeypatch):
    job = localmodels.InstallJob()
    monkeypatch.setattr(
        localmodels,
        "_winget_install",
        lambda i, cb=None: (_ for _ in ()).throw(AssertionError("çalışmamalı")),
    )
    for bad in ("docker", "rm -rf /", "", None, 5, "ollama; calc"):
        with pytest.raises(localmodels.LocalError, match="bunu kuramam"):
            job.start(bad)
    monkeypatch.setattr(localmodels.sys, "platform", "linux")
    with pytest.raises(localmodels.LocalError, match="kendim kuramıyorum"):
        job.start("ollama")
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: None)  # winget yok
    assert localmodels.can_install("ollama") is False
    with pytest.raises(localmodels.LocalError, match="kendim kuramıyorum"):
        job.start("ollama")


def test_install_runs_a_fixed_winget_command_and_waits_for_ollama(monkeypatch):
    seen = {}
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: "C:/winget.exe")
    monkeypatch.setattr(
        localmodels, "_winget_install", lambda i, cb=None: seen.update(id=i) or (0, "ok")
    )
    monkeypatch.setattr(
        localmodels, "probe", lambda port, timeout=0.8, host="127.0.0.1": {"port": port}
    )
    job = localmodels.InstallJob()
    job.start("ollama")
    done = _wait_job(job)
    assert seen == {"id": "Ollama.Ollama"}  # kimlik sabit listeden, dışarıdan metin yok
    assert done["done"] is True and done["error"] is None and done["active"] is False


def test_install_failure_is_reported_in_plain_words(monkeypatch):
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: "C:/winget.exe")
    monkeypatch.setattr(
        localmodels, "_winget_install", lambda i, cb=None: (1, "ham çıktı gizli ayrıntı")
    )
    job = localmodels.InstallJob()
    job.start("ollama")
    done = _wait_job(job)
    assert done["done"] is False and "kurulamadı" in done["error"]
    assert "gizli ayrıntı" not in done["error"]  # winget çıktısı kullanıcıya ham gösterilmez

    def boom(i, cb=None):
        raise OSError("winget açılamadı")

    monkeypatch.setattr(localmodels, "_winget_install", boom)
    job.start("ollama")
    assert "kurulamadı" in _wait_job(job)["error"]


def test_install_treats_already_installed_as_success_and_blocks_a_second_job(monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: "C:/winget.exe")
    monkeypatch.setattr(
        localmodels, "_winget_install", lambda i, cb=None: gate.wait(5) and (-1978335189, "")
    )
    monkeypatch.setattr(
        localmodels, "probe", lambda port, timeout=0.8, host="127.0.0.1": {"port": port}
    )
    job = localmodels.InstallJob()
    job.start("ollama")
    with pytest.raises(localmodels.LocalError, match="sürüyor"):
        job.start("ollama")
    gate.set()
    assert _wait_job(job)["done"] is True


def test_install_endpoints_require_auth_and_refuse_unlisted(tmp_path, monkeypatch):
    monkeypatch.setattr(localmodels.sys, "platform", "linux")
    c, _ = make_client(tmp_path, Scripted())
    assert c.post("/system/install", json={"what": "ollama"}).status_code == 401
    assert c.get("/system/install").status_code == 401
    assert c.post("/system/install", json={"what": "calc"}, headers=AUTH).status_code == 400
    r = c.post("/system/install", json={"what": "ollama"}, headers=AUTH)
    assert r.status_code == 400 and "kendim kuramıyorum" in r.json()["detail"]
    assert c.get("/system/info", headers=AUTH).json()["can_install"] == {"ollama": False}
    assert c.get("/system/install", headers=AUTH).json()["active"] is False


def test_winget_progress_line_becomes_a_short_sentence():
    assert localmodels.parse_progress("  ██▒▒  140 MB / 1.20 GB") == "indiriliyor: 140 MB / 1.20 GB"
    assert (
        localmodels.parse_progress("a\r  1,5 MB / 1.20 GB\r  900 KB / 1.20 GB")
        == "indiriliyor: 900 KB / 1.20 GB"
    )  # son satır
    assert localmodels.parse_progress("Starting package install...") is None
    assert localmodels.parse_progress("") is None


def test_install_shows_download_progress_and_plain_winget_errors(monkeypatch):
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: "C:/winget.exe")
    seen = []

    def fake(i, cb=None):
        cb("indiriliyor: 140 MB / 1.20 GB")
        seen.append(job.snapshot()["status"])
        cb("kuruluyor")
        seen.append(job.snapshot()["status"])
        return 0x8A15000F, ""  # kaynak verisi eksik

    monkeypatch.setattr(localmodels, "_winget_install", fake)
    job = localmodels.InstallJob()
    job.start("ollama")
    done = _wait_job(job)
    assert seen == ["Ollama indiriliyor: 140 MB / 1.20 GB", "Ollama kuruluyor"]
    assert "program listesi (winget) güncellenemedi" in done["error"] and "kod" not in done["error"]
    monkeypatch.setattr(localmodels, "_winget_install", lambda i, cb=None: (0x8A150008, ""))
    job.start("ollama")
    assert "İndirme olmadı" in _wait_job(job)["error"]
    monkeypatch.setattr(localmodels, "_winget_install", lambda i, cb=None: (7, ""))
    job.start("ollama")
    assert "0x7" in _wait_job(job)["error"]  # bilinmeyen kod: onaltılık, ham çıktı değil


@pytest.mark.skipif(localmodels.sys.platform == "win32", reason="sahte winget bir kabuk betiği")
def test_real_subprocess_streams_progress_before_it_finishes(tmp_path, monkeypatch):
    import os
    import stat
    import threading

    fake = tmp_path / "winget"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '  1.5 MB / 1.20 GB\\r'\n"
        "sleep 1\n"  # süreç bitmeden ilk ilerleme gelmeli
        "printf '  600 MB / 1.20 GB\\r'\n"
        "sleep 1\n"
        "printf 'Starting package install...\\n'\n"
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    first = threading.Event()
    msgs: list[str] = []

    def cb(m):
        msgs.append(m)
        first.set()

    result: list = []
    t = threading.Thread(
        target=lambda: result.append(localmodels._winget_install("Ollama.Ollama", cb))
    )
    t.start()
    assert first.wait(1.5) and t.is_alive()  # ilk ilerleme, süreç hâlâ çalışırken geldi
    t.join(10)
    assert result[0][0] == 0
    assert msgs[0] == "indiriliyor: 1.5 MB / 1.20 GB" and "indiriliyor: 600 MB / 1.20 GB" in msgs
    assert msgs[-1] == "kuruluyor"


def test_install_status_reports_elapsed_time_only_while_active(monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(localmodels.sys, "platform", "win32")
    monkeypatch.setattr(localmodels.shutil, "which", lambda n: "C:/winget.exe")
    monkeypatch.setattr(localmodels, "_winget_install", lambda i, cb=None: gate.wait(5) and (1, ""))
    job = localmodels.InstallJob()
    assert "elapsed" not in job.snapshot()
    job.start("ollama")
    snap = job.snapshot()
    assert snap["active"] and isinstance(snap["elapsed"], int) and snap["elapsed"] >= 0
    assert "started" not in snap  # iç alan dışarı çıkmaz
    gate.set()
    done = _wait_job(job)
    assert "elapsed" not in done and "started" not in done
