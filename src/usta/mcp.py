"""MCP istemcisi (stdio): yerel bir MCP sunucusunu alt süreç olarak başlatır, araçlarını listeler/çağırır.

Sunucu çıktısı GÜVENİLMEZDİR: satır/sonuç boyutu ve süre sınırlı, metin dışı içerik atılır,
sunucudan gelen istekler (sampling vb.) reddedilir. Süreç kendi grubunda başlar ve kapanışta
alt süreçleriyle birlikte öldürülür. Tasarım: docs/design.md §5.3.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Self

from usta.fetch import _clean

PROTOCOL_VERSION = "2025-06-18"
BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER")
MAX_TOOLS = 200
MAX_PAGES = 20


class McpError(Exception):
    """MCP hatası; mesajı kullanıcıya/modele gösterilebilir."""


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    schema: dict


class McpClient:
    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        *,
        timeout: float = 30.0,
        max_chars: int = 50_000,
        max_line: int = 1_000_000,
        cwd: str | None = None,
    ):
        if not command or not all(isinstance(c, str) and c for c in command):
            raise McpError("komut boş veya geçersiz")
        self.command, self.env = list(command), dict(env or {})
        self.timeout, self.max_chars, self.max_line, self.cwd = timeout, max_chars, max_line, cwd
        self.pid: int | None = None
        self._proc: subprocess.Popen | None = None
        self._cv = threading.Condition()
        self._send_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._responses: dict[int, dict] = {}
        self._next_id = 0
        self._dead: str | None = None
        self._stderr = b""
        self._threads: list[threading.Thread] = []

    # --- yaşam döngüsü ---------------------------------------------------------------------
    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        env = {k: os.environ[k] for k in BASE_ENV if k in os.environ} | self.env
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self.cwd or tempfile.gettempdir(),
                start_new_session=True,
            )
        except FileNotFoundError:
            raise McpError(f"komut bulunamadı: {self.command[0]}") from None
        except OSError as e:
            raise McpError(
                f"komut çalıştırılamadı: {self.command[0]} ({e.strerror or e})"
            ) from None
        self.pid = self._proc.pid
        for target in (self._read_stdout, self._read_stderr):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "usta", "version": "0.3"},
                },
                self.timeout,
                None,
                what="başlangıç",
            )
            self._notify("notifications/initialized")
        except McpError:
            self.close()
            raise

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        try:  # sunucu ve alt süreçleri (ör. npx → node) kendi grubundan
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        with self._cv:
            self._dead = self._dead or "kapatıldı"
            self._cv.notify_all()

    # --- okuyucu iş parçacıkları -----------------------------------------------------------
    def _mark_dead(self, why: str) -> None:
        with self._cv:
            self._dead = self._dead or why
            self._cv.notify_all()

    def _read_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            while True:
                line = proc.stdout.readline(self.max_line + 1)
                if not line:
                    break
                if len(line) > self.max_line and not line.endswith(b"\n"):
                    self._mark_dead("sunucu çıktısı çok uzun satır gönderdi")
                    self._kill_group()
                    return
                self._dispatch(line)
        except (OSError, ValueError):
            pass
        code = proc.poll()
        if code is None:
            try:
                code = proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                code = None
        self._join_stderr()
        tail = self._stderr.decode(errors="replace").strip().splitlines()
        extra = f": {_clean(tail[-1])[:200]}" if tail else ""
        self._mark_dead(f"sunucu kapandı (kod {code}){extra}")

    def _read_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        try:
            while chunk := proc.stderr.read1(4096):
                self._stderr = (self._stderr + chunk)[-2048:]
        except (OSError, ValueError):
            pass

    def _join_stderr(self) -> None:
        if len(self._threads) > 1:
            self._threads[1].join(timeout=1.0)

    def _kill_group(self) -> None:
        if self.pid is not None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _dispatch(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            return  # günlük satırı vb.
        if not isinstance(msg, dict):
            return
        if "method" in msg:
            if "id" in msg:  # sunucudan istek: ping dışında hiçbirine uyma
                if msg["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                else:
                    err = {"code": -32601, "message": "istemci bu isteği desteklemiyor"}
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "error": err})
            return  # bildirimler yoksayılır
        mid = msg.get("id")
        if isinstance(mid, int) and ("result" in msg or "error" in msg):
            with self._cv:
                self._responses[mid] = msg
                self._cv.notify_all()

    # --- istek/yanıt -----------------------------------------------------------------------
    def _send(self, obj: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpError("sunucu kapalı")
        data = (json.dumps(obj) + "\n").encode()
        with self._send_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (OSError, ValueError):
                raise McpError(self._dead or "sunucuya yazılamadı") from None

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._send(msg)

    def _request(
        self,
        method: str,
        params: dict,
        timeout: float,
        cancel: threading.Event | None,
        what: str = "istek",
    ) -> dict:
        with self._cv:
            self._next_id += 1
            rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        with self._cv:
            while rid not in self._responses:
                if self._dead:
                    raise McpError(self._dead)
                if cancel is not None and cancel.is_set():
                    self._cancelled_note(rid)
                    raise McpError("iptal edildi")
                left = deadline - time.monotonic()
                if left <= 0:
                    self._cancelled_note(rid)
                    raise McpError(
                        f"sunucu yanıt vermedi ({what}, {timeout:g} sn)"
                        if method == "initialize"
                        else f"zaman aşımı ({timeout:g} sn)"
                    )
                self._cv.wait(min(left, 0.1))
            resp = self._responses.pop(rid)
        if "error" in resp:
            err = resp["error"] if isinstance(resp["error"], dict) else {}
            raise McpError(_clean(str(err.get("message", "bilinmeyen hata")))[:200])
        result = resp.get("result")
        return result if isinstance(result, dict) else {}

    def _cancelled_note(self, rid: int) -> None:
        try:
            self._notify("notifications/cancelled", {"requestId": rid})
        except McpError:
            pass

    # --- araçlar ---------------------------------------------------------------------------
    def list_tools(self) -> list[McpTool]:
        tools: list[McpTool] = []
        cursor = None
        for _ in range(MAX_PAGES):
            res = self._request(
                "tools/list", {"cursor": cursor} if cursor else {}, self.timeout, None
            )
            for t in res.get("tools") or []:
                if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"]:
                    desc = t.get("description")
                    schema = t.get("inputSchema")
                    tools.append(
                        McpTool(
                            t["name"][:128],
                            _clean(desc)[:2000] if isinstance(desc, str) else "",
                            schema if isinstance(schema, dict) else {"type": "object"},
                        )
                    )
            cursor = res.get("nextCursor")
            if not isinstance(cursor, str) or not cursor or len(tools) >= MAX_TOOLS:
                break
        return tools[:MAX_TOOLS]

    def call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        timeout: float | None = None,
        cancel: threading.Event | None = None,
    ) -> str:
        with self._call_lock:
            res = self._request(
                "tools/call",
                {"name": name, "arguments": arguments},
                timeout if timeout is not None else self.timeout,
                cancel,
            )
        parts = []
        for item in res.get("content") or []:
            kind = item.get("type") if isinstance(item, dict) else None
            if kind == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif kind == "image":
                parts.append("[görsel atlandı]")
            elif kind:
                parts.append(f"[{_clean(str(kind))[:30]} içeriği atlandı]")
        text = _clean("\n".join(parts))
        if len(text) > self.max_chars:
            text = text[: self.max_chars] + f"\n[... kırpıldı: {len(text)} karakter]"
        if res.get("isError") is True:
            raise McpError(text[:500] or "araç hata döndürdü")
        return text
