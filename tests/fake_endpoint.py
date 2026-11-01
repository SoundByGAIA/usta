"""Sahte OpenAI-uyumlu uç nokta: yazılı yanıtları sırayla döndürür, gelen istekleri kaydeder."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeEndpoint:
    def __init__(self, responses: list[dict] | None = None, status: int = 200):
        self.responses = list(responses or [])
        self.status = status
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body})
                outer.headers.append(dict(self.headers))
                payload = outer.responses.pop(0) if outer.responses else {"error": "bitti"}
                data = json.dumps(payload).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def text_reply(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def tool_reply(name: str, arguments: dict, call_id: str = "c1") -> dict:
    call = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}
