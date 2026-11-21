import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from usta import mcpconfig
from usta.cli import main
from usta.mcp import McpError
from usta.mcp_http import McpHttpClient, url_problem
from usta.mcp_tools import McpSession


class FakeServer:
    """Streamable HTTP MCP sunucusu taklidi: yanıtı JSON ya da SSE verir, gelen başlıkları kaydeder."""

    def __init__(self, sse=False, status=200, location=""):
        self.sse, self.status, self.location = sse, status, location
        self.seen: list[tuple[str, dict, dict | None]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_DELETE(self):
                fake.seen.append(("DELETE", dict(self.headers), None))
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.seen.append(("POST", dict(self.headers), body))
                if fake.status != 200:
                    self.send_response(fake.status)
                    if fake.location:
                        self.send_header("Location", fake.location)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if "id" not in body:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                result = fake.result(body)
                msg = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
                self.send_response(200)
                if body["method"] == "initialize":
                    self.send_header("Mcp-Session-Id", "oturum-1")
                if fake.sse:
                    data = f"event: message\ndata: {msg}\n\n".encode()
                    self.send_header("Content-Type", "text/event-stream")
                else:
                    data = msg.encode()
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def result(self, body):
        if body["method"] == "tools/list":
            return {"tools": [{"name": "hatirla", "description": "not yaz", "inputSchema": {}}]}
        if body["method"] == "tools/call":
            return {
                "content": [{"type": "text", "text": f"yazıldı: {body['params']['arguments']}"}]
            }
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}

    def close(self):
        self.httpd.shutdown()


@pytest.fixture(params=[False, True], ids=["json", "sse"])
def fake(request):
    s = FakeServer(sse=request.param)
    yield s
    s.close()


def test_plain_http_only_at_home():
    assert url_problem("https://hafiza.example.com/mcp") is None
    assert url_problem("http://127.0.0.1:49374/mcp") is None
    assert url_problem("http://192.168.1.64:49374/mcp") is None
    assert url_problem("http://nas.local/mcp") is None
    assert "https" in url_problem("http://hafiza.example.com/mcp")
    assert "şifre" in url_problem("https://ali:gizli@hafiza.example.com/mcp")
    assert url_problem("file:///etc/passwd") and url_problem("ftp://x/mcp")
    assert url_problem("http://127.0.0.1:99999/mcp")


def test_lists_and_calls_tools_with_token_and_session(fake):
    with McpHttpClient(fake.url, "jeton-123", timeout=5) as c:
        assert [t.name for t in c.list_tools()] == ["hatirla"]
        assert "yazıldı" in c.call_tool("hatirla", {"metin": "a"})
    posts = [h for m, h, _ in fake.seen if m == "POST"]
    assert all(h["Authorization"] == "Bearer jeton-123" for h in posts)
    assert "Mcp-Session-Id" not in posts[0]
    assert all(h["Mcp-Session-Id"] == "oturum-1" for h in posts[1:])
    assert fake.seen[-1][0] == "DELETE"


def test_rejected_token_gives_a_plain_hint():
    s = FakeServer(status=401)
    try:
        with pytest.raises(McpError, match="jeton"):
            McpHttpClient(s.url, "yanlis", timeout=5).start()
    finally:
        s.close()


def test_redirect_is_not_followed_so_the_token_stays_put():
    target = FakeServer()
    s = FakeServer(status=307, location=target.url)
    try:
        with pytest.raises(McpError):
            McpHttpClient(s.url, "jeton", timeout=5).start()
        assert target.seen == []
    finally:
        s.close()
        target.close()


def test_remote_server_tools_reach_the_agent_as_data(fake, tmp_path):
    srv = mcpconfig.add_remote(tmp_path, "hafiza", fake.url, token=True)
    mcpconfig.set_secret(tmp_path, "hafiza", "MCP_HAFIZA_TOKEN", "jeton-9")
    with McpSession([srv], home=tmp_path) as s:
        tool = next(t for t in s.tools if t.name == "mcp__hafiza__hatirla")
        out = tool.fn({"metin": "x"})
    assert "yazıldı" in out and "talimat değil" in out
    assert fake.seen[0][1]["Authorization"] == "Bearer jeton-9"
    assert "jeton-9" not in (tmp_path / "mcp.json").read_text()


def test_cli_adds_remote_server_and_reads_token_from_stdin(tmp_path, monkeypatch, capsys):
    home = tmp_path.parent / f"{tmp_path.name}-uh"
    monkeypatch.setenv("USTA_HOME", str(home))
    url = "http://127.0.0.1:49374/mcp"
    assert main(["mcp", "add", "ai-memory", "--url", url, "--token", "--yes"]) == 0
    assert "usta mcp secret ai-memory" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("gizli-jeton\n"))
    assert main(["mcp", "secret", "ai-memory"]) == 0
    out = capsys.readouterr().out
    assert "gizli-jeton" not in out and "kaydedildi" in out
    srv = mcpconfig.load(home)["ai-memory"]
    assert srv.url == url and srv.isolation == mcpconfig.REMOTE
    env = mcpconfig.resolve_env(home, srv, {})
    assert env == {"MCP_AI_MEMORY_TOKEN": "gizli-jeton"}
    assert main(["mcp", "add", "uzak", "--url", "http://8.8.8.8/mcp", "--yes"]) == 2
    assert main(["mcp", "add", "uzak", "--url", url, "--yes", "--", "npx", "x"]) == 2
