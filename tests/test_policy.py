import pytest

from usta.policy import Decision, PathEscapeError, Policy, resolve_path


def test_resolve_inside(tmp_path):
    assert resolve_path(tmp_path, "a/b.txt") == tmp_path.resolve() / "a" / "b.txt"


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", ""])
def test_resolve_rejects_escape(tmp_path, bad):
    with pytest.raises(PathEscapeError):
        resolve_path(tmp_path, bad)


def test_resolve_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "dis"
    outside.mkdir()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(PathEscapeError):
        resolve_path(root, "link/gizli.txt")


def test_sibling_prefix_is_not_inside(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "ws-evil").mkdir()
    with pytest.raises(PathEscapeError):
        resolve_path(root, "../ws-evil/x")


@pytest.mark.parametrize("tool", ["read_file", "write_file", "edit_file", "list_dir"])
def test_file_tools_allowed_inside(tmp_path, tool):
    assert Policy(tmp_path).check(tool, {"path": "a.txt"}) is Decision.ALLOW


@pytest.mark.parametrize("tool", ["read_file", "write_file", "edit_file", "list_dir"])
def test_file_tools_denied_outside(tmp_path, tool):
    assert Policy(tmp_path).check(tool, {"path": "../x"}) is Decision.DENY


def test_run_is_allowed_because_sandboxed(tmp_path):
    assert Policy(tmp_path).check("run", {"command": "ls"}) is Decision.ALLOW


def test_unknown_tool_denied(tmp_path):
    assert Policy(tmp_path).check("rm_rf_everything", {}) is Decision.DENY


def test_missing_or_bad_path_arg_denied(tmp_path):
    p = Policy(tmp_path)
    assert p.check("read_file", {}) is Decision.DENY
    assert p.check("read_file", {"path": 5}) is Decision.DENY


def test_external_tools_ask_unless_allowlisted(tmp_path):
    p = Policy(tmp_path, allowed_hosts={"docs.python.org"})
    assert p.check("fetch_url", {"url": "https://evil.example/x"}) is Decision.ASK
    assert p.check("fetch_url", {"url": "https://docs.python.org/3/"}) is Decision.ALLOW
    assert p.check("fetch_url", {"url": "https://docs.python.org.evil.io/"}) is Decision.ASK
    assert p.check("fetch_url", {}) is Decision.DENY
    assert p.check("web_search", {"query": "x"}) is Decision.ASK


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://localhost/",
        "http://example.com:8080/",
        "http://u:p@example.com/",
        "javascript:alert(1)",
        "example.com",
        "",
        5,
        None,
    ],
)
def test_fetch_url_invalid_targets_are_denied_not_asked(tmp_path, url):
    assert Policy(tmp_path).check("fetch_url", {"url": url}) is Decision.DENY


def test_fetch_url_wildcard_allowlist(tmp_path):
    p = Policy(tmp_path, allowed_hosts={"*.pypi.org", "docs.python.org"})
    assert p.check("fetch_url", {"url": "https://files.pypi.org/x"}) is Decision.ALLOW
    assert (
        p.check("fetch_url", {"url": "https://pypi.org/x"}) is Decision.ASK
    )  # joker kök alanı kapsamaz
    assert p.check("fetch_url", {"url": "HTTPS://Docs.Python.Org./3/"}) is Decision.ALLOW


def test_agent_cannot_write_git_or_usta_but_can_read_them(tmp_path):
    from usta.policy import Decision, Policy

    (tmp_path / ".git").mkdir()
    (tmp_path / ".usta").mkdir()
    p = Policy(tmp_path)
    for tool in ("write_file", "edit_file"):
        for path in (
            ".git/config",
            ".git/hooks/post-checkout",
            ".usta/memory/NOTES.md",
            "a/../.git/config",
        ):
            assert p.check(tool, {"path": path}) == Decision.DENY, (tool, path)
    assert p.check("write_file", {"path": "src/.gitignore"}) == Decision.ALLOW
    assert p.check("write_file", {"path": "gitlike/x"}) == Decision.ALLOW
    assert p.check("read_file", {"path": ".git/config"}) == Decision.ALLOW  # okuma serbest


def test_nul_byte_in_path_is_denied_not_a_crash(tmp_path):
    import pytest

    from usta.policy import Decision, PathEscapeError, Policy, resolve_path

    assert Policy(tmp_path).check("read_file", {"path": "a\x00b"}) == Decision.DENY
    with pytest.raises(PathEscapeError):
        resolve_path(tmp_path, "a\x00b")
