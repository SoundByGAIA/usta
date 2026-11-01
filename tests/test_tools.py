import shutil
import subprocess

import pytest

from usta.tools import ToolContext, ToolError, build_registry

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


@pytest.fixture
def reg(tmp_path):
    return build_registry(ToolContext(root=tmp_path))


def test_schemas_are_openai_function_specs(reg):
    names = {s["name"] for s in reg.schemas()}
    assert names == {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "run",
        "fetch_url",
        "remember",
        "outline",
        "read_symbol",
    }
    for s in reg.schemas():
        assert s["parameters"]["type"] == "object" and s["description"]


def test_write_then_read(reg, tmp_path):
    reg.call("write_file", {"path": "d/a.txt", "content": "selam"})
    assert (tmp_path / "d" / "a.txt").read_text() == "selam"
    assert reg.call("read_file", {"path": "d/a.txt"}) == "selam"


def test_read_missing_raises(reg):
    with pytest.raises(ToolError):
        reg.call("read_file", {"path": "yok.txt"})


def test_read_truncates_large_files(tmp_path):
    reg = build_registry(ToolContext(root=tmp_path, max_read=10))
    (tmp_path / "b.txt").write_text("x" * 100)
    out = reg.call("read_file", {"path": "b.txt"})
    assert out.startswith("x" * 10) and "kırpıldı" in out


def test_edit_replaces_unique_match(reg, tmp_path):
    (tmp_path / "a.txt").write_text("bir iki üç")
    reg.call("edit_file", {"path": "a.txt", "old": "iki", "new": "2"})
    assert (tmp_path / "a.txt").read_text() == "bir 2 üç"


def test_edit_requires_exactly_one_match(reg, tmp_path):
    (tmp_path / "a.txt").write_text("x x")
    with pytest.raises(ToolError):
        reg.call("edit_file", {"path": "a.txt", "old": "x", "new": "y"})
    with pytest.raises(ToolError):
        reg.call("edit_file", {"path": "a.txt", "old": "z", "new": "y"})
    assert (tmp_path / "a.txt").read_text() == "x x"


def test_list_dir(reg, tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "alt").mkdir()
    assert reg.call("list_dir", {"path": "."}).splitlines() == ["a.txt", "alt/"]


def test_tools_refuse_escape_even_if_called_directly(reg, tmp_path):
    with pytest.raises(ToolError):
        reg.call("read_file", {"path": "../x"})
    with pytest.raises(ToolError):
        reg.call("write_file", {"path": "/tmp/x", "content": "z"})


def test_bad_arguments_raise_toolerror(reg):
    with pytest.raises(ToolError):
        reg.call("write_file", {"path": "a"})
    with pytest.raises(ToolError):
        reg.call("nope", {})
    with pytest.raises(ToolError):
        reg.call("write_file", {"path": "a", "content": 5})
    with pytest.raises(ToolError):
        reg.call("edit_file", {"path": "a", "old": 1, "new": 2})


@needs_docker
@pytest.mark.docker
def test_run_in_sandbox(reg, tmp_path):
    (tmp_path / "m.txt").write_text("dosya")
    out = reg.call("run", {"command": "cat m.txt; echo err >&2; exit 3"})
    assert "dosya" in out and "err" in out and "exit_code: 3" in out


@needs_docker
@pytest.mark.docker
def test_run_honors_cancel(tmp_path):
    import threading
    import time

    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    reg = build_registry(ToolContext(root=tmp_path, cancel=cancel))
    t0 = time.monotonic()
    assert "(iptal)" in reg.call("run", {"command": "sleep 30"})
    assert time.monotonic() - t0 < 10


@needs_docker
@pytest.mark.docker
def test_run_reports_blocked_hosts_to_the_model(tmp_path):
    reg = build_registry(ToolContext(root=tmp_path, allowed_hosts=("example.com",), run_timeout=60))
    code = "import urllib.request;urllib.request.urlopen('http://evil.example/', timeout=10)"
    out = reg.call("run", {"command": f'python -c "{code}"'})
    assert "ağ: engellendi: evil.example" in out and "exit_code: 1" in out


def test_toolcontext_defaults_to_no_network(tmp_path):
    assert ToolContext(root=tmp_path).allowed_hosts == ()


def test_fetch_url_tool_delegates_with_context(tmp_path, monkeypatch):
    import threading

    import usta.tools as tools_mod

    cancel, seen = threading.Event(), {}

    def fake(url, **kw):
        seen.update(url=url, **kw)
        return "SAYFA"

    monkeypatch.setattr(tools_mod.fetch, "fetch_url", fake)
    ctx = ToolContext(
        root=tmp_path, allowed_hosts=("pypi.org",), cancel=cancel, fetch_max_chars=123
    )
    assert build_registry(ctx).call("fetch_url", {"url": "https://example.com/"}) == "SAYFA"
    assert seen == {
        "url": "https://example.com/",
        "allowed_hosts": ("pypi.org",),
        "cancel": cancel,
        "max_chars": 123,
    }


def test_fetch_url_tool_turns_errors_into_toolerror(tmp_path):
    reg = build_registry(ToolContext(root=tmp_path))
    with pytest.raises(ToolError, match="http/https"):
        reg.call("fetch_url", {"url": "file:///etc/passwd"})
    with pytest.raises(ToolError):
        reg.call("fetch_url", {})
    with pytest.raises(ToolError):
        reg.call("fetch_url", {"url": 5})


def test_fifo_is_refused_instead_of_hanging(tmp_path):
    import os

    import pytest

    from usta.tools import ToolContext, ToolError, build_registry

    os.mkfifo(tmp_path / "boru")
    reg = build_registry(ToolContext(root=tmp_path))
    for tool, args in (
        ("read_file", {"path": "boru"}),
        ("edit_file", {"path": "boru", "old": "a", "new": "b"}),
    ):
        with pytest.raises(ToolError):
            reg.call(tool, args)


def test_snapshot_and_diff_skip_fifo(tmp_path):
    import os

    from usta.workspace import diff, snapshot

    (tmp_path / "a.txt").write_text("x")
    os.mkfifo(tmp_path / "boru")
    snap = snapshot(tmp_path)  # takılmadan döner
    assert list(snap.files) == ["a.txt"] and diff(snap, tmp_path) == ""
