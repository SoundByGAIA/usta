"""Allowlist HTTP(S) proxy: yalnız izinli alan adlarına tünel açar. Yalnız stdlib; konteynerde de çalışır.

- HTTPS: `CONNECT host:port` (içerik opak). Düz HTTP: yalnız GET/HEAD/OPTIONS, mutlak URI.
- IP literal hedefler ve özel/yerel/link-local adreslere çözülen alan adları reddedilir (SSRF,
  DNS rebinding: çözülen IP'ye bağlanılır, yeniden çözülmez).
- Karar günlüğü yalnız {yöntem, host, port, karar, neden} içerir; yol, sorgu ve gövde kaydedilmez.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import sys
from collections.abc import Callable, Iterable

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CTRL = re.compile(r"[\x00-\x20\x7f]")
_STATUS = {
    400: "Bad Request",
    403: "Forbidden",
    405: "Method Not Allowed",
    431: "Request Header Fields Too Large",
    502: "Bad Gateway",
}


def _norm(host: str) -> str:
    return host.strip().lower().rstrip(".").removeprefix("[").removesuffix("]")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_ENTRY = re.compile(rf"(?:\*\.)?{_LABEL}(?:\.{_LABEL})+")


def validate_allowed_host(entry: str) -> str:
    """İzin listesi girdisini doğrular ve küçük harfe çevirir: alan adı veya `*.alan.adı`."""
    e = entry.strip().lower()
    labels = e.removeprefix("*.").split(".")
    if (
        not _ENTRY.fullmatch(e)
        or len(e) > 253
        or any(len(label) > 63 for label in labels)
        or e.count("*") > 1
        or _is_ip(e)
        or (e.startswith("*.") and e.count(".") < 2)
    ):
        raise ValueError(f"geçersiz alan adı girdisi: {entry!r}")
    return e


def host_allowed(host: str, allowed: Iterable[str]) -> bool:
    host = _norm(host)
    if not host or _is_ip(host):
        return False
    for entry in allowed:
        entry = _norm(entry)
        if entry.startswith("*."):
            suffix = entry[1:]  # ".pypi.org"
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif entry and host == entry:
            return True
    return False


NAT64 = ipaddress.ip_network("64:ff9b::/96")
NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        elif addr in NAT64:  # 64:ff9b::/96 ağ geçidi içindeki IPv4'e çevirir: asıl hedef o adrestir
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        elif addr in NAT64_LOCAL:  # 64:ff9b:1::/48 yerel kullanım: asla genel sayılmaz
            return False
    return addr.is_global and not (
        addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or addr.is_loopback
        or addr.is_link_local
    )


def _default_resolve(host: str) -> list[str]:
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except OSError:
        return []


class Denied(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


class AllowlistProxy:
    def __init__(
        self,
        allowed: Iterable[str],
        ports: Iterable[int] = (80, 443),
        resolve: Callable[[str], list[str]] = _default_resolve,
        allow_private: bool = False,
        on_decision: Callable[[dict], None] | None = None,
        max_header: int = 16_384,
        header_timeout: float = 10.0,
        connect_timeout: float = 10.0,
        idle_timeout: float = 60.0,
    ):
        self.allowed, self.ports = list(allowed), set(ports)
        self.resolve, self.allow_private, self.on_decision = resolve, allow_private, on_decision
        self.max_header, self.header_timeout = max_header, header_timeout
        self.connect_timeout, self.idle_timeout = connect_timeout, idle_timeout

    def _log(self, **d) -> None:
        if self.on_decision:
            self.on_decision(d)

    async def _read_head(self, reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
        buf = b""
        try:
            async with asyncio.timeout(self.header_timeout):
                while b"\r\n\r\n" not in buf:
                    chunk = await reader.read(4096)
                    if not chunk:
                        raise Denied(0, "bağlantı kapandı")
                    buf += chunk
                    if len(buf) > self.max_header:
                        raise Denied(431, "başlık çok büyük")
        except TimeoutError:
            raise Denied(0, "başlık zaman aşımı") from None
        head, _, rest = buf.partition(b"\r\n\r\n")
        return head, rest

    def _parse(self, head: bytes) -> tuple[str, str, str, list[tuple[str, str]]]:
        try:
            lines = head.decode("ascii").split("\r\n")
        except UnicodeDecodeError:
            raise Denied(400, "geçersiz istek") from None
        parts = lines[0].split(" ")
        if len(parts) != 3 or not parts[2].startswith("HTTP/1.") or _CTRL.search(parts[1]):
            raise Denied(400, "geçersiz istek satırı")
        headers = []
        for ln in lines[1:]:
            name, sep, value = ln.partition(":")
            if not sep or not name or name != name.strip() or "\n" in ln or "\r" in ln:
                raise Denied(400, "geçersiz başlık")
            headers.append((name, value.strip()))
        return parts[0].upper(), parts[1], parts[2], headers

    @staticmethod
    def _split_hostport(target: str, default: int | None) -> tuple[str, int]:
        m = re.fullmatch(r"(\[[0-9a-fA-F:.]+\]|[^:\[\]]+)(?::(\d{1,5}))?", target)
        if not m:
            raise Denied(400, "geçersiz hedef")
        port = int(m.group(2)) if m.group(2) else default
        if port is None or not 0 < port < 65536:
            raise Denied(400, "port gerekli")
        return _norm(m.group(1)), port

    async def _open(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if _is_ip(host) or not host_allowed(host, self.allowed):
            raise Denied(403, "alan adı izinli değil")
        if port not in self.ports:
            raise Denied(403, "port izinli değil")
        loop = asyncio.get_running_loop()
        ips = await loop.run_in_executor(None, self.resolve, host)
        if not ips:
            raise Denied(502, "alan adı çözümlenemedi")
        if not self.allow_private and not all(is_public_ip(ip) for ip in ips):
            raise Denied(403, "özel/yerel adrese çözülüyor")
        for ip in ips:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(ip, port), self.connect_timeout
                )
            except (OSError, TimeoutError):
                continue
        raise Denied(502, "bağlanılamadı")

    async def _pipe(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while data := await asyncio.wait_for(r.read(65536), self.idle_timeout):
                w.write(data)
                await w.drain()
        except (TimeoutError, OSError):
            pass

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        method, host, port, up_w = "?", "", 0, None
        try:
            head, _rest = await self._read_head(reader)
            method, target, _ver, headers = self._parse(head)
            if method == "CONNECT":
                host, port = self._split_hostport(target, None)
                up_r, up_w = await self._open(host, port)
                self._log(method=method, host=host, port=port, allowed=True, reason="")
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await self._tunnel(reader, writer, up_r, up_w)
                return
            if method not in SAFE_METHODS:
                host = _norm(re.sub(r"^\w+://", "", target).split("/")[0].split(":")[0])
                raise Denied(405, "yöntem izinli değil (düz HTTP yalnız GET/HEAD/OPTIONS)")
            if not target.lower().startswith("http://"):
                raise Denied(400, "mutlak http:// URI gerekli (HTTPS için CONNECT kullan)")
            authority, _, path = target[7:].partition("/")
            host, port = self._split_hostport(authority, 80)
            names = {n.lower() for n, _ in headers}
            if "transfer-encoding" in names or any(
                n.lower() == "content-length" and v != "0" for n, v in headers
            ):
                raise Denied(400, "gövdeli istek izinli değil")
            up_r, up_w = await self._open(host, port)
            self._log(method=method, host=host, port=port, allowed=True, reason="")
            drop = {
                "host",
                "connection",
                "keep-alive",
                "proxy-authorization",
                "proxy-connection",
                "te",
                "upgrade",
            }
            out = [f"{method} /{path} HTTP/1.1", f"Host: {authority}", "Connection: close"]
            out += [f"{n}: {v}" for n, v in headers if n.lower() not in drop]
            up_w.write(("\r\n".join(out) + "\r\n\r\n").encode("ascii"))
            await up_w.drain()
            await self._pipe(up_r, writer)  # yalnız yanıt yönü
        except Denied as d:
            if d.status:
                self._log(method=method, host=host, port=port, allowed=False, reason=d.reason)
                body = f"usta proxy: {d.reason}\n".encode()
                writer.write(
                    f"HTTP/1.1 {d.status} {_STATUS.get(d.status, 'Error')}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                try:
                    await writer.drain()
                except OSError:
                    pass
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            for w in (writer, up_w):
                if w is not None:
                    w.close()

    async def _tunnel(self, cr, cw, ur, uw) -> None:
        tasks = {
            asyncio.ensure_future(self._pipe(cr, uw)),
            asyncio.ensure_future(self._pipe(ur, cw)),
        }
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()


async def serve(host: str, port: int, proxy: AllowlistProxy) -> None:
    server = await asyncio.start_server(proxy.handle, host, port)
    print(json.dumps({"event": "listening", "port": port}), flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    allowed = [h for h in os.environ.get("USTA_ALLOW", "").split(",") if h.strip()]
    ports = {int(p) for p in os.environ.get("USTA_PORTS", "80,443").split(",") if p.strip()}
    listen = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0:3128"
    host, _, port = listen.rpartition(":")
    proxy = AllowlistProxy(
        allowed,
        ports,
        allow_private=os.environ.get("USTA_ALLOW_PRIVATE") == "1",
        on_decision=lambda d: print(
            json.dumps({"event": "decision", **d}, ensure_ascii=False), flush=True
        ),
    )
    asyncio.run(serve(host, int(port), proxy))


if __name__ == "__main__":
    main()
