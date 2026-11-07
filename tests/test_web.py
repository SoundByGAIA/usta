import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_api import AUTH, Scripted, make_client

WEB = Path(__file__).resolve().parent.parent / "src" / "usta" / "web"


def client(tmp_path):
    return make_client(tmp_path, Scripted())[0]


@pytest.mark.parametrize(
    ("path", "ctype"),
    [
        ("/", "text/html"),
        ("/app.js", "text/javascript"),
        ("/app.css", "text/css"),
        ("/logic.js", "text/javascript"),
        ("/office-logic.js", "text/javascript"),
        ("/office.js", "text/javascript"),
    ],
)
def test_ui_files_are_public_with_right_type(tmp_path, path, ctype):
    r = client(tmp_path).get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)
    assert len(r.content) > 100


def test_security_headers_on_ui(tmp_path):
    h = client(tmp_path).get("/").headers
    csp = h["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store"


def test_no_path_traversal_or_extra_static_files(tmp_path):
    c = client(tmp_path)
    for p in [
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/index.html",
        "/token",
        "/web/app.js",
    ]:
        assert c.get(p).status_code in (401, 404), p


def test_api_still_requires_token_and_json_errors_stay(tmp_path):
    c = client(tmp_path)
    assert c.get("/workspaces").status_code == 401
    assert c.get("/workspaces", headers=AUTH).status_code == 200


def test_html_has_no_inline_script_or_handlers():
    html = (WEB / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE)
    assert 'src="/app.js"' in html and "<title>" in html


@pytest.mark.parametrize(
    "banned",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "document.write", "new Function"],
)
def test_js_never_uses_html_injection_sinks(banned):
    assert banned not in (WEB / "app.js").read_text()


OFFICE_JS = ("office-logic.js", "office.js")


@pytest.mark.parametrize("name", OFFICE_JS)
@pytest.mark.parametrize(
    "banned",
    [
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "eval(",
        "document.write",
        "new Function",
        "localStorage",
    ],
)
def test_office_js_never_uses_html_injection_sinks(name, banned):
    assert banned not in (WEB / name).read_text()


def test_office_logic_exports_for_browser_and_node():
    js = (WEB / "office-logic.js").read_text()
    assert "module.exports" in js and "OfficeLogic" in js
    assert "interactive" not in js


def test_office_js_draws_pixels_and_respects_motion_and_visibility():
    js = (WEB / "office.js").read_text()
    assert "image-rendering" in (WEB / "app.css").read_text()
    assert "prefers-reduced-motion" in js and "visibilitychange" in js
    assert "matchMedia" in js and "requestAnimationFrame" in js
    assert "font=" not in js.replace("ctx.font", ""), "harici font yüklenmez"


def test_office_tab_present_and_default_stays_stream():
    html = (WEB / "index.html").read_text()
    assert 'id="tab-office"' in html and 'id="office-canvas"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="Usta ofis animasyonu' in html
    stream = re.search(r'<button id="tab-stream"[^>]*>', html).group(0)
    assert 'aria-selected="true"' in stream
    office = re.search(r'<button id="tab-office"[^>]*>', html).group(0)
    assert 'aria-selected="false"' in office


def test_app_forwards_events_to_office_and_resets():
    js = (WEB / "app.js").read_text()
    assert "O.onEvent(type, data)" in js and "Office.onEvent(type, data)" in js
    # yeni görev, geçmiş oturum (aç/kapat), alan değişimi, yeniden bağlanma
    assert js.count("officeReset()") >= 4
    assert 'src="/office-logic.js"' in (WEB / "index.html").read_text()
    assert 'src="/office.js"' in (WEB / "index.html").read_text()


def test_js_does_not_persist_token_in_localstorage():
    js = (WEB / "app.js").read_text()
    assert "localStorage" not in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_js_logic_unit_tests():
    files = sorted(str(f) for f in (Path(__file__).parent / "web").glob("*.test.cjs"))
    assert files
    r = subprocess.run(
        ["node", "--test", *files],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_favicon_is_quiet_204(tmp_path):
    r = client(tmp_path).get("/favicon.ico")
    assert r.status_code == 204 and not r.content


def test_html_has_theme_and_mode_selectors_with_expected_values():
    html = (WEB / "index.html").read_text()
    for value in ("siyah", "gri", "beyaz", "manual", "auto", "plan"):
        assert f'value="{value}"' in html


def test_js_exchanges_login_code_and_cleans_url():
    js = (WEB / "app.js").read_text()
    assert "/auth/exchange" in js and "history.replaceState" in js
    assert js.index("history.replaceState") < js.index("exchangeCode(loginCode)")


def test_html_has_guard_checkbox_and_js_sends_it():
    assert 'id="guard"' in (WEB / "index.html").read_text()
    assert 'guard: $("guard").checked' in (WEB / "app.js").read_text()
