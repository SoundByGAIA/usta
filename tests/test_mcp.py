import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from usta.mcp import McpClient, McpError

FAKE = str(Path(__file__).parent / "fake_mcp.py")


def client(mode="normal", env=None, **kw):
    return McpClient([sys.executable, "-I", FAKE, mode], env or {}, **kw)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # zombi (çocuk sahipsiz) sayılmaz
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def test_handshake_and_tool_listing():
    with client() as c:
        tools = c.list_tools()
    names = [t.name for t in tools]
    assert names[:3] == ["echo", "fail", "big"] and "mixed" in names
    echo = tools[0]
    assert echo.description == "Yankılar." and echo.schema["type"] == "object"


def test_pagination_collects_all_pages():
    with client("paged") as c:
        assert [t.name for t in c.list_tools()] == ["echo", "fail", "big"]


def test_call_returns_text_and_error_flag_raises():
    with client() as c:
        assert c.call_tool("echo", {"text": "selam"}) == "selam"
        with pytest.raises(McpError, match="ters gitti"):
            c.call_tool("fail", {})
        assert c.call_tool("echo", {"text": "hala çalışıyor"}) == "hala çalışıyor"


def test_non_text_content_is_not_passed_through():
    with client() as c:
        out = c.call_tool("mixed", {})
    assert "metin1" in out and "metin2" in out
    assert "AAAA" not in out and "gizli" not in out and "passwd" not in out


def test_result_is_capped():
    with client(max_chars=1000) as c:
        out = c.call_tool("big", {})
    assert len(out) < 1200 and "kırpıldı" in out


def test_server_requests_get_error_or_pong_not_obeyed():
    with client() as c:
        replies = json.loads(c.call_tool("probe", {}))
    by_id = {r["id"]: r for r in replies}
    assert by_id[900]["error"]["code"] == -32601  # sampling reddedilir
    assert by_id[901]["result"] == {}  # ping yanıtlanır


def test_environment_is_minimal_plus_explicit(monkeypatch):
    monkeypatch.setenv("USTA_API_KEY", "model-anahtari")
    monkeypatch.setenv("BASKA_SIR", "x")
    with client(env={"BRAVE_KEY": "k"}) as c:
        names = c.call_tool("env", {}).split(",")
    assert "BRAVE_KEY" in names and "PATH" in names
    assert "USTA_API_KEY" not in names and "BASKA_SIR" not in names


def test_startup_timeout_kills_process():
    t0 = time.monotonic()
    c = client("hang", timeout=1.0)
    with pytest.raises(McpError, match="yanıt vermedi"):
        c.start()
    assert time.monotonic() - t0 < 6
    assert c.pid is not None and not alive(c.pid)


def test_exit_at_startup_reports_stderr_tail():
    with pytest.raises(McpError, match="eksik bağımlılık"):
        client("exit").start()


def test_command_not_found_has_clear_message():
    with pytest.raises(McpError, match="bulunamadı"):
        McpClient(["/yok/bu-komut-yok"], {}).start()


def test_server_death_during_call():
    with client() as c:
        with pytest.raises(McpError, match="kapandı"):
            c.call_tool("die", {})
        with pytest.raises(McpError):
            c.call_tool("echo", {"text": "x"})


def test_call_timeout_keeps_client_usable():
    with client() as c:
        t0 = time.monotonic()
        with pytest.raises(McpError, match="zaman aşımı"):
            c.call_tool("slow", {}, timeout=0.8)
        assert time.monotonic() - t0 < 5


def test_cancel_event_aborts_call():
    ev = threading.Event()
    with client() as c:
        threading.Timer(0.5, ev.set).start()
        t0 = time.monotonic()
        with pytest.raises(McpError, match="iptal"):
            c.call_tool("slow", {}, cancel=ev)
        assert time.monotonic() - t0 < 5


def test_close_kills_children_too():
    c = client()
    c.start()
    child = int(c.call_tool("child", {}))
    assert alive(child)
    c.close()
    time.sleep(0.3)
    try:
        assert not alive(child)
    finally:
        if alive(child):
            os.kill(child, signal.SIGKILL)
    assert not alive(c.pid)


def test_oversized_line_is_fatal():
    c = McpClient(
        [
            sys.executable,
            "-I",
            "-c",
            "print('x'*3_000_000, flush=True); import time; time.sleep(30)",
        ],
        {},
        timeout=3,
        max_line=100_000,
    )
    with pytest.raises(McpError):
        c.start()
    assert not alive(c.pid)
