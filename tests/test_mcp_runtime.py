"""MCP Runtime: konteyner izolasyonu, kapalı başarısızlık, sabitleme, denetim kaydı.

Docker gerektirenler `needs_docker` ile işaretlidir (python:3.12-slim yerelde olmalı). Gerçek hassas dosya yerine
test klasöründe üretilmiş "canary" dosyalar ve sahte sırlar kullanılır.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from probe_mcp_src import SRC
from usta import mcp_runtime, mcpconfig
from usta.audit import AuditLog
from usta.mcp import McpError
from usta.mcp_runtime import McpIsolationError
from usta.mcp_tools import McpSession
from usta.policy import Decision, Policy

IMAGE = "python:3.12-slim"
needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", IMAGE], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


def probe(**kw) -> mcpconfig.Server:
    base = {
        "isolation": "container",
        "image": IMAGE,
        "memory": "128m",
        "cpus": "0.5",
        "pids": 64,
    }
    return mcpconfig.Server("probe", ("python", "-c", SRC), (), "allow", True, **(base | kw))


def containers() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", "name=usta-mcp-"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [n for n in out.split() if n]


def start(srv, tmp_path, *, env=None, workspace=None, events=None, timeout=30.0):
    return mcp_runtime.start(
        srv,
        home=tmp_path / "home",
        env=env or {},
        workspace=workspace,
        timeout=timeout,
        on_event=(lambda k, d: events.append((k, d))) if events is not None else None,
    )


# --- birim testleri (Docker gerekmez) ----------------------------------------------------------
def test_run_args_are_hardened_and_never_carry_secret_values(tmp_path):
    args = mcp_runtime.build_run_args(
        probe(), name="usta-mcp-x", secret_names=("DECLARED_KEY",), workspace=None
    )
    pre = args[: args.index(IMAGE)]  # docker seçenekleri (sunucu komutu/kaynağı hariç)
    joined = " ".join(pre)
    assert args[:3] == ["docker", "run", "--rm"] and "--init" in args
    for flag in ("--read-only", "--cap-drop", "no-new-privileges", "--pids-limit", "--memory"):
        assert flag in joined
    assert args[args.index("--network") + 1] == "none"  # ağ varsayılan kapalı
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "--pull" in args and args[args.index("--pull") + 1] == "never"
    assert "DECLARED_KEY" in args and "declared-value" not in joined  # yalnız ad, değer yok
    assert "-v" not in pre  # çalışma alanı/önbellek yoksa hiçbir bağlama yok
    assert "docker.sock" not in joined and str(Path.home()) not in joined


def test_run_args_workspace_modes_and_protected_paths(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    ro = mcp_runtime.build_run_args(probe(workspace="ro"), name="n", workspace=ws)
    assert f"{ws.resolve()}:/workspace:ro" in ro
    rw = mcp_runtime.build_run_args(probe(workspace="rw"), name="n", workspace=ws)
    assert f"{ws.resolve()}:/workspace:rw" in rw
    assert f"{(ws / '.git').resolve()}:/workspace/.git:ro" in rw  # rw bağlansa da .git korunur
    with pytest.raises(McpIsolationError, match="çalışma alanı"):
        mcp_runtime.build_run_args(probe(workspace="ro"), name="n", workspace=None)


def test_run_args_reject_mount_syntax_injection(tmp_path):
    bad = tmp_path / "a:b"
    bad.mkdir()
    with pytest.raises(McpIsolationError):
        mcp_runtime.build_run_args(probe(workspace="ro"), name="n", workspace=bad)


def test_container_without_image_cannot_be_built():
    srv = mcpconfig.Server("x", ("cmd",), (), "ask", True)  # varsayılan: container, imaj yok
    with pytest.raises(McpIsolationError, match="imaj"):
        mcp_runtime.build_run_args(srv, name="n")


def test_legacy_config_without_isolation_defaults_to_container_and_never_runs_on_host(tmp_path):
    (tmp_path / "mcp.json").write_text(
        json.dumps({"servers": {"eski": {"command": ["touch", str(tmp_path / "HOST-RAN")]}}})
    )
    srv = mcpconfig.load(tmp_path)["eski"]
    assert srv.isolation == "container" and srv.image is None
    with McpSession([srv], tmp_path) as s:
        assert s.tools == [] and any("imaj" in w for w in s.warnings)
        if mcp_runtime.docker_problem() is None:  # eski kayıt: anlaşılır yönlendirme, "None" yok
            assert all("None" not in w for w in s.warnings)
            assert any("usta mcp add eski --image" in w for w in s.warnings)
    assert not (tmp_path / "HOST-RAN").exists()  # sessizce ana makinede çalışmadı


def test_fails_closed_when_docker_missing_and_does_not_fall_back_to_host(tmp_path, monkeypatch):
    marker = tmp_path / "HOST-RAN"
    srv = mcpconfig.Server(
        "x",
        ("sh", "-c", f"touch {marker}"),
        (),
        "ask",
        True,
        isolation="container",
        image=IMAGE,
    )
    monkeypatch.setattr(mcp_runtime, "docker_problem", lambda: "Docker bulunamadı")
    events: list = []
    with McpSession([srv], tmp_path, on_event=lambda k, d: events.append((k, d))) as s:
        assert s.tools == []
        assert any("Docker bulunamadı" in w and "geri düşülmez" in w for w in s.warnings)
    assert not marker.exists()
    assert ("mcp_blocked", {"server": "x", "reason": "Docker bulunamadı"}) in events


def test_cache_digest_detects_change_addition_and_removal(tmp_path):
    d = tmp_path / "c"
    (d / "a").mkdir(parents=True)
    (d / "a" / "f").write_text("1")
    base = mcp_runtime.cache_digest(d)
    assert base.startswith("sha256:") and base == mcp_runtime.cache_digest(d)
    (d / "a" / "f").write_text("2")
    changed = mcp_runtime.cache_digest(d)
    assert changed != base
    (d / "a" / "g").write_text("x")
    added = mcp_runtime.cache_digest(d)
    assert added not in (base, changed)
    (d / "a" / "g").unlink()
    (d / "a" / "f").unlink()
    assert mcp_runtime.cache_digest(d) not in (base, changed, added)
    assert mcp_runtime.cache_digest(tmp_path / "yok") == ""


def test_policy_remains_the_central_authority_for_mcp_calls(tmp_path):
    pol = Policy(tmp_path, mcp_modes={"mcp__probe__read_file": "ask", "mcp__probe__echo": "allow"})
    assert pol.check("mcp__probe__read_file", {"path": "/etc/passwd"}) is Decision.ASK
    assert pol.check("mcp__probe__echo", {}) is Decision.ALLOW
    assert pol.check("mcp__probe__gizli_arac", {}) is Decision.DENY  # sunucunun bildirmediği araç
    assert pol.check("mcp__baska__echo", {}) is Decision.DENY


def test_config_validation_for_runtime_fields(tmp_path):
    ok = {"image": "node:22-slim", "allow_hosts": ["api.example.com"], "workspace": "ro"}
    mcpconfig.add_server(tmp_path, "a", ["cmd"], **ok)
    s = mcpconfig.load(tmp_path)["a"]
    assert (s.isolation, s.image, s.allow_hosts, s.workspace) == (
        "container",
        "node:22-slim",
        ("api.example.com",),
        "ro",
    )
    for bad in (
        {"image": "-v/x:/y"},
        {"image": "a b"},
        {"image": "x:1", "allow_hosts": ["a b"]},
        {"image": "x:1", "workspace": "rwx"},
        {"image": "x:1", "memory": "9"},
        {"image": "x:1", "cpus": "64"},
        {"image": "x:1", "pids": 100000},
        {"isolation": "host", "allow_hosts": ["a.com"]},  # host'ta ağ listesi anlamsız
        {"isolation": "vm"},
    ):
        with pytest.raises(mcpconfig.McpConfigError):
            mcpconfig.add_server(tmp_path, "b", ["cmd"], replace=True, **bad)
    with pytest.raises(mcpconfig.McpConfigError, match="imaj"):
        mcpconfig.add_server(tmp_path, "c", ["cmd"])  # container + imaj yok


def test_host_mode_is_explicit_and_warns(tmp_path):
    marker = tmp_path / "m"
    srv = mcpconfig.Server(
        "h", ("true",), (), "ask", True, isolation="host"
    )  # başlatma başarısız olur ama uyarı + olay önce gelir
    events: list = []
    with McpSession([srv], None, on_event=lambda k, d: events.append((k, d))) as s:
        assert any("uyumluluk modu" in w for w in s.warnings)
    assert events[0][0] == "mcp_start" and events[0][1]["isolation"] == "host"
    assert not marker.exists()


# --- Docker ile gerçek izolasyon ---------------------------------------------------------------
@needs_docker
@pytest.mark.docker
def test_container_server_works_and_is_cleaned_up(tmp_path):
    h = start(probe(), tmp_path)
    try:
        names = [t.name for t in h.client.list_tools()]
        assert "echo" in names
        assert h.client.call_tool("echo", {"text": "merhaba"}) == "merhaba"
    finally:
        h.close()
    assert containers() == []


@needs_docker
@pytest.mark.docker
def test_cannot_read_host_files_or_secrets(tmp_path, monkeypatch):
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY-HOST-DOSYASI-İÇERİĞİ")
    monkeypatch.setenv("USTA_PORTAL_TOKEN", "portal-jetonu-canary")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "model-anahtari-canary")
    monkeypatch.setenv("HOST_ONLY_SECRET", "yalniz-host-canary")
    h = start(probe(), tmp_path, env={"DECLARED_KEY": "bildirilen-deger"})
    try:
        with pytest.raises(McpError) as e:
            h.client.call_tool("read_file", {"path": str(canary)})
        assert "CANARY" not in str(e.value) and "FileNotFoundError" in str(e.value)
        env = json.loads(h.client.call_tool("env_dump", {}))
        assert env.get("DECLARED_KEY") == "bildirilen-deger"  # yalnız tanımlı sır geçti
        blob = json.dumps(env)
        for leak in ("portal-jetonu-canary", "model-anahtari-canary", "yalniz-host-canary"):
            assert leak not in blob
        ident = json.loads(h.client.call_tool("identity", {}))
        assert ident["home"] == "/tmp/home" and ident["cwd"] == "/tmp"
        assert h.client.call_tool("exists", {"path": "/var/run/docker.sock"}) == "False"
        assert h.client.call_tool("exists", {"path": str(Path.home())}) == "False"
    finally:
        h.close()


@needs_docker
@pytest.mark.docker
def test_unprivileged_readonly_rootfs_and_no_capabilities(tmp_path):
    h = start(probe(), tmp_path)
    try:
        ident = json.loads(h.client.call_tool("identity", {}))
        assert ident["uid"] != 0 and int(ident["capeff"], 16) == 0
        with pytest.raises(McpError, match="(Read-only|OSError|Permission)"):
            h.client.call_tool("write_file", {"path": "/etc/usta-saldiri"})
        assert h.client.call_tool("write_file", {"path": "/tmp/gecici"}) == "yazıldı"
    finally:
        h.close()


@needs_docker
@pytest.mark.docker
def test_network_is_off_by_default(tmp_path):
    h = start(probe(), tmp_path)
    try:
        for host in ("1.1.1.1", "127.0.0.1", "host.docker.internal"):
            with pytest.raises(McpError):
                h.client.call_tool("connect", {"host": host, "port": 443})
    finally:
        h.close()


@needs_docker
@pytest.mark.docker
def test_workspace_is_not_mounted_unless_requested(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "gizli.txt").write_text("ÇALIŞMA-ALANI-CANARY")
    none = start(probe(), tmp_path, workspace=ws)
    try:
        assert none.client.call_tool("exists", {"path": "/workspace"}) == "False"
    finally:
        none.close()
    ro = start(probe(workspace="ro"), tmp_path, workspace=ws)
    try:
        assert "ÇALIŞMA-ALANI-CANARY" in ro.client.call_tool(
            "read_file", {"path": "/workspace/gizli.txt"}
        )
        with pytest.raises(McpError):
            ro.client.call_tool("write_file", {"path": "/workspace/yeni.txt"})
    finally:
        ro.close()
    assert not (ws / "yeni.txt").exists()


@needs_docker
@pytest.mark.docker
def test_rw_workspace_still_protects_git_and_usta(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / ".git" / "config").write_text("[core]\n")
    h = start(probe(workspace="rw"), tmp_path, workspace=ws)
    try:
        assert h.client.call_tool("write_file", {"path": "/workspace/ok.txt"}) == "yazıldı"
        with pytest.raises(McpError):
            h.client.call_tool("write_file", {"path": "/workspace/.git/hooks-saldirisi"})
    finally:
        h.close()
    assert (ws / "ok.txt").exists() and not (ws / ".git" / "hooks-saldirisi").exists()


@needs_docker
@pytest.mark.docker
def test_timeout_and_background_children_are_cleaned_up(tmp_path):
    h = start(probe(), tmp_path)
    try:
        assert h.client.call_tool("spawn", {}).isdigit()  # arka plan süreci bırakır
        with pytest.raises(McpError, match="zaman aşımı"):
            h.client.call_tool("hang", {}, timeout=2)
    finally:
        h.close()
    assert containers() == []  # sunucu ve tüm alt süreçleri (konteyner) gitti


@needs_docker
@pytest.mark.docker
def test_pin_mismatch_blocks_start_and_is_audited(tmp_path):
    srv = probe(pin_image="sha256:" + "0" * 64)
    events: list = []
    with pytest.raises(McpIsolationError, match="sabitlemesi tutmuyor"):
        start(srv, tmp_path, events=events)
    assert events and events[0][0] == "mcp_blocked"
    assert containers() == []


@needs_docker
@pytest.mark.docker
def test_cache_pin_mismatch_blocks_start(tmp_path):
    home = tmp_path / "home"
    cache = mcp_runtime.cache_path(home, "probe")
    cache.mkdir(parents=True)
    (cache / "paket").write_text("v1")
    pin = mcp_runtime.cache_digest(cache)
    srv = probe(pin_image=mcp_runtime.image_id(IMAGE), pin_cache=pin)
    h = start(srv, tmp_path)  # özet tutuyor: başlar
    h.close()
    (cache / "paket").write_text("v2-kurcalandi")
    with pytest.raises(McpIsolationError, match="önbelleği"):
        start(srv, tmp_path)
    assert containers() == []


@needs_docker
@pytest.mark.docker
def test_prepare_pins_image_and_cache_then_runs_offline(tmp_path):
    home = tmp_path / "home"
    srv = mcpconfig.Server(
        "hazir",
        ("sh", "-c", "mkdir -p /cache/npm && echo paket > /cache/npm/a"),
        (),
        "allow",
        True,
        isolation="container",
        image=IMAGE,
    )
    iid, digest = mcp_runtime.prepare(srv, home=home, env={}, timeout=120)
    assert iid == mcp_runtime.image_id(IMAGE) and digest.startswith("sha256:")
    assert (mcp_runtime.cache_path(home, "hazir") / "npm" / "a").read_text() == "paket\n"
    assert containers() == []
    run = mcpconfig.Server(
        "hazir",
        ("python", "-c", SRC),
        (),
        "allow",
        True,
        isolation="container",
        image=IMAGE,
        pin_image=iid,
        pin_cache=digest,
    )
    h = mcp_runtime.start(run, home=home, env={}, workspace=None, timeout=30)
    try:
        assert h.client.call_tool("read_file", {"path": "/cache/npm/a"}).strip() == "paket"
        # önbellek bu çalıştırmaya özel yazılabilir KOPYA olarak bağlanır (npm ağsızken de yazar)
        assert h.client.call_tool("write_file", {"path": "/cache/npm/b"}) == "yazıldı"
        with pytest.raises(McpError):  # çalışma anında ağ yok
            h.client.call_tool("connect", {"host": "1.1.1.1", "port": 443})
    finally:
        h.close()
    # sunucu kopyaya yazdı ama asıl önbellek ve sabitleme aynı kaldı; kopya silindi
    assert not (mcp_runtime.cache_path(home, "hazir") / "npm" / "b").exists()
    assert mcp_runtime.cache_digest(mcp_runtime.cache_path(home, "hazir")) == digest
    assert not list(Path(tempfile.gettempdir()).glob("usta-mcp-cache-*"))
    shutil.rmtree(
        mcp_runtime.cache_path(home, "hazir")
    )  # sabitlenmiş önbellek silinirse başlatma reddedilir
    with pytest.raises(McpIsolationError, match="önbelleği yok"):
        mcp_runtime.start(run, home=home, env={}, workspace=None, timeout=30)


@needs_docker
@pytest.mark.docker
def test_session_records_start_and_blocked_network_in_audit(tmp_path):
    # allowlist proxy: izinli alan adı dışına çıkış engellenir ve denetim kaydına "mcp_network" olarak girer
    srv = probe(allow_hosts=("izinli.test",))
    audit = AuditLog(tmp_path / "audit.jsonl")
    with McpSession([srv], tmp_path / "home", on_event=lambda k, d: audit.record(k, **d)) as s:
        assert [t.name for t in s.tools][:1] == ["mcp__probe__echo"]
        call = next(t for t in s.tools if t.name == "mcp__probe__connect")
        with pytest.raises(Exception):  # noqa: B017 - doğrudan bağlantı (proxy'siz) engellenir
            call.run({"host": "1.1.1.1", "port": 443})
    rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    kinds = [r["event"] for r in rows]
    assert "mcp_start" in kinds
    start_row = next(r for r in rows if r["event"] == "mcp_start")
    assert start_row["isolation"] == "container" and start_row["network"] == ["izinli.test"]
    assert containers() == []
