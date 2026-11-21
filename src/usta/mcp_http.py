"""MCP istemcisi (Streamable HTTP): ağdaki bir MCP sunucusuna (ör. ortak hafıza) bağlanır.

Bekleme, iptal, zaman aşımı ve çıktı sınırları stdio istemcisinden gelir; burada yalnız iletim değişir:
her JSON-RPC mesajı bir POST'tur, yanıt JSON ya da SSE akışı olarak gelir. Jeton yalnız bu adrese gider:
yönlendirme izlenmez, sistem vekil sunucusu kullanılmaz. Düz http yalnız bu bilgisayarda ve ev ağında.
"""

from __future__ import annotations

import ipaddress
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from usta.fetch import _clean
from usta.mcp import PROTOCOL_VERSION, McpClient, McpError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def url_problem(url: str) -> str | None:
    """Adres kabul edilmezse nedeni (kullanıcıya gösterilir), edilirse None."""
    try:
        u = urllib.parse.urlsplit(url)
        host = (u.hostname or "").lower()
        u.port  # noqa: B018 - geçersiz kapı numarası burada ValueError verir
    except ValueError:
        return "adres okunamadı"
    if len(url) > 2048 or u.scheme not in ("http", "https") or not host:
        return "adres http:// ya da https:// ile başlamalı"
    if u.username or u.password:
        return "adrese kullanıcı adı/şifre yazma; jetonu --token ile ver"
    if u.scheme == "http" and not _home_network(host):
        return (
            "internetteki sunucu için https gerekir (düz http yalnız bu bilgisayarda ve ev ağında)"
        )
    return None


def _home_network(host: str) -> bool:
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class McpHttpClient(McpClient):
    def __init__(
        self, url: str, token: str = "", *, timeout: float = 30.0, max_chars: int = 50_000
    ):
        if url_problem(url):
            raise McpError(url_problem(url) or "")
        super().__init__(["http"], timeout=timeout, max_chars=max_chars)
        self.url, self.token = url, token
        self._session = ""
        self._open = False

    def start(self) -> None:
        self._open = True
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
        if not self._open:
            return
        self._open = False
        if self._session:  # oturumu sunucuda da kapat; olmazsa sunucu kendisi zaman aşımıyla siler
            try:
                _opener.open(self._req(None, "DELETE"), timeout=5).close()
            except (OSError, ValueError):
                pass
        self._mark_dead("kapatıldı")

    def _req(self, body: bytes | None, method: str = "POST") -> urllib.request.Request:
        req = urllib.request.Request(self.url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("User-Agent", "usta")
        if self._session:
            req.add_header("Mcp-Session-Id", self._session)
            req.add_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        if self.token:
            req.add_unredirected_header("Authorization", f"Bearer {self.token}")
        return req

    def _send(self, obj: dict) -> None:
        if not self._open:
            raise McpError(self._dead or "sunucu kapalı")
        # Yanıtı arka planda okur; _request'in beklemesi (iptal, zaman aşımı) aynen çalışır.
        rid = obj.get("id") if "method" in obj else None
        t = threading.Thread(target=self._post, args=(obj, rid), daemon=True)
        t.start()
        if obj.get("method") == "initialize":
            t.join(self.timeout)  # oturum kimliği sonraki isteklerden önce gelmeli

    def _post(self, obj: dict, rid: object) -> None:
        try:
            with _opener.open(self._req(json.dumps(obj).encode()), timeout=self.timeout) as r:
                if obj.get("method") == "initialize":
                    self._session = (r.headers.get("Mcp-Session-Id") or "")[:200]
                kind = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if kind == "text/event-stream":
                    self._read_events(r, rid)
                elif kind == "application/json":
                    self._dispatch_body(r.read(self.max_line + 1))
        except urllib.error.HTTPError as e:
            self._fail(rid, _http_message(e.code))
        except ValueError as e:
            self._fail(rid, f"sunucu yanıtı okunamadı ({_clean(str(e))[:120]})")
        except OSError as e:
            reason = getattr(e, "reason", None) or e
            self._fail(rid, f"sunucuya bağlanılamadı ({_clean(str(reason))[:120]})")

    def _dispatch_body(self, data: bytes) -> None:
        if len(data) > self.max_line:
            raise ValueError("sunucu yanıtı çok büyük")
        msg = json.loads(data or b"null")
        for m in msg if isinstance(msg, list) else [msg]:
            self._dispatch(json.dumps(m).encode())

    def _read_events(self, stream, rid: object) -> None:
        data: list[bytes] = []
        total = 0
        while self._open:
            line = stream.readline(self.max_line + 1)
            total += len(line)
            if total > self.max_line:
                raise ValueError("sunucu yanıtı çok büyük")
            if line.startswith(b"data:"):
                data.append(line[5:].strip())
            elif line in (b"\n", b"\r\n", b"") and data:
                self._dispatch(b"".join(data))
                data = []
                with self._cv:
                    if rid is None or rid in self._responses:
                        return
            if not line:
                return

    def _fail(self, rid: object, why: str) -> None:
        if isinstance(rid, int):
            with self._cv:
                self._responses[rid] = {"id": rid, "error": {"message": why}}
                self._cv.notify_all()


def _http_message(code: int) -> str:
    if code in (401, 403):
        return f"sunucu erişimi reddetti (HTTP {code}); jetonu kontrol et: usta mcp secret"
    if code == 404:
        return "adreste MCP sunucusu yok (HTTP 404); adresin sonunda /mcp olabilir"
    return f"sunucu hata döndürdü (HTTP {code})"


def connect(srv, env: dict[str, str], timeout: float) -> McpHttpClient:
    """Kayıtlı uzak sunucuya bağlanır; jeton gizli depodan (`usta mcp secret`)."""
    from usta.mcpconfig import token_env

    client = McpHttpClient(srv.url, env.get(token_env(srv.name), ""), timeout=timeout)
    client.start()
    return client
