import asyncio

import pytest

from usta.proxy import AllowlistProxy, host_allowed, is_public_ip


@pytest.mark.parametrize(
    ("host", "allowed", "ok"),
    [
        ("docs.python.org", ["docs.python.org"], True),
        ("DOCS.Python.ORG.", ["docs.python.org"], True),
        ("evil.python.org", ["docs.python.org"], False),
        ("docs.python.org.evil.io", ["docs.python.org"], False),
        ("a.pypi.org", ["*.pypi.org"], True),
        ("a.b.pypi.org", ["*.pypi.org"], True),
        ("pypi.org", ["*.pypi.org"], False),  # joker kök alan adını kapsamaz
        ("xpypi.org", ["*.pypi.org"], False),
        ("x.test", [], False),
        ("1.2.3.4", ["1.2.3.4"], False),  # IP literal hiçbir zaman izinli değil
        ("::1", ["::1"], False),
        ("", ["x.test"], False),
    ],
)
def test_host_allowed(host, allowed, ok):
    assert host_allowed(host, allowed) is ok


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("2606:4700:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("172.16.5.5", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("100.64.0.1", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fc00::1", False),
        ("fe80::1", False),
        ("::ffff:10.0.0.1", False),
        ("::ffff:8.8.8.8", True),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


UPSTREAM_REPLY = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"


class Env:
    """Gerçek soketlerle: sahte yukarı akış + proxy; her şey 127.0.0.1'de."""

    def __init__(self, **proxy_kw):
        self.proxy_kw = proxy_kw
        self.upstream_heads: list[bytes] = []
        self.upstream_bodies: list[bytes] = []
        self.decisions: list[dict] = []

    async def __aenter__(self):
        async def up(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            self.upstream_heads.append(head)
            if b"content-length: 4" in head.lower():
                self.upstream_bodies.append(await reader.readexactly(4))
            writer.write(UPSTREAM_REPLY)
            await writer.drain()
            writer.close()

        self.up = await asyncio.start_server(up, "127.0.0.1", 0)
        self.up_port = self.up.sockets[0].getsockname()[1]
        kw = {
            "allowed": ["allowed.test"],
            "ports": {self.up_port},
            "resolve": lambda h: {
                "allowed.test": ["127.0.0.1"],
                "mixed.test": ["8.8.8.8", "10.0.0.5"],
            }.get(h, []),
            "allow_private": True,
            "on_decision": self.decisions.append,
            "header_timeout": 1.0,
        }
        kw.update(self.proxy_kw)
        self.proxy = AllowlistProxy(**kw)
        self.srv = await asyncio.start_server(self.proxy.handle, "127.0.0.1", 0)
        self.port = self.srv.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        for s in (self.srv, self.up):
            s.close()
            await s.wait_closed()

    async def raw(self, data: bytes, read: int = 4096) -> bytes:
        r, w = await asyncio.open_connection("127.0.0.1", self.port)
        w.write(data)
        await w.drain()
        try:
            return await asyncio.wait_for(r.read(read), 5)
        finally:
            w.close()


def run(coro):
    return asyncio.run(coro)


def status(resp: bytes) -> int:
    return int(resp.split(b" ", 2)[1])


def test_connect_allowed_opens_tunnel():
    async def go():
        async with Env() as e:
            r, w = await asyncio.open_connection("127.0.0.1", e.port)
            w.write(f"CONNECT allowed.test:{e.up_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            head = await r.readuntil(b"\r\n\r\n")
            assert status(head) == 200
            w.write(b"GET / HTTP/1.1\r\nHost: allowed.test\r\n\r\n")
            body = await asyncio.wait_for(r.read(4096), 5)
            w.close()
            assert body.endswith(b"ok") and e.decisions[0]["allowed"] is True
            assert e.decisions[0]["host"] == "allowed.test"

    run(go())


@pytest.mark.parametrize(
    "target", ["evil.test:{p}", "1.2.3.4:{p}", "[::1]:{p}", "allowed.test:22", "allowed.test"]
)
def test_connect_denied(target):
    async def go():
        async with Env() as e:
            resp = await e.raw(
                f"CONNECT {target.format(p=e.up_port)} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
            )
            assert status(resp) in (400, 403), resp
            assert e.upstream_heads == [] and e.decisions[-1]["allowed"] is False

    run(go())


def test_private_resolution_is_blocked_by_default():
    async def go():
        async with Env(allow_private=False, allowed=["allowed.test", "mixed.test"]) as e:
            for host in ("allowed.test", "mixed.test"):  # 127.0.0.1; ve genel+özel karışık
                resp = await e.raw(f"CONNECT {host}:{e.up_port} HTTP/1.1\r\n\r\n".encode())
                assert status(resp) == 403, host
            assert "özel" in e.decisions[0]["reason"]

    run(go())


def test_unresolvable_host_is_502():
    async def go():
        async with Env(allowed=["nxdomain.test"]) as e:
            resp = await e.raw(f"CONNECT nxdomain.test:{e.up_port} HTTP/1.1\r\n\r\n".encode())
            assert status(resp) == 502

    run(go())


def test_plain_http_is_rewritten_to_origin_form_and_proxy_headers_dropped():
    async def go():
        async with Env() as e:
            req = (
                f"GET http://allowed.test:{e.up_port}/a/b?q=1 HTTP/1.1\r\nHost: evil.test\r\n"
                "Proxy-Authorization: x\r\nProxy-Connection: keep-alive\r\nConnection: keep-alive\r\n\r\n"
            )
            resp = await e.raw(req.encode())
            assert status(resp) == 200 and resp.endswith(b"ok")
            head = e.upstream_heads[0].decode().lower()
            assert head.startswith("get /a/b?q=1 http/1.1\r\n")
            assert f"host: allowed.test:{e.up_port}" in head and "evil.test" not in head
            assert "proxy-" not in head and "connection: close" in head and "keep-alive" not in head

    run(go())


def test_plain_http_not_allowed_host_and_origin_form_and_methods():
    async def go():
        async with Env() as e:
            assert (
                status(await e.raw(f"GET http://evil.test:{e.up_port}/ HTTP/1.1\r\n\r\n".encode()))
                == 403
            )
            assert status(await e.raw(b"GET / HTTP/1.1\r\nHost: allowed.test\r\n\r\n")) in (
                400,
                403,
            )
            post = (
                f"POST http://allowed.test:{e.up_port}/ HTTP/1.1\r\nContent-Length: 4\r\n\r\ndata"
            )
            assert status(await e.raw(post.encode())) == 405
            assert e.upstream_heads == []
            assert status(
                await e.raw(f"GET https://allowed.test:{e.up_port}/ HTTP/1.1\r\n\r\n".encode())
            ) in (400, 403)

    run(go())


def test_malformed_and_oversized_requests_are_closed():
    async def go():
        async with Env(max_header=512) as e:
            assert status(await e.raw(b"HELLO\r\n\r\n")) == 400
            assert status(
                await e.raw(
                    b"GET http://allowed.test/ HTTP/1.1\r\n" + b"X: " + b"a" * 2000 + b"\r\n\r\n"
                )
            ) in (400, 431)
            assert (
                await e.raw(b"CONNECT allowed.test:1 HTTP/1.1\r\n") == b""
            )  # başlık bitmez → zaman aşımı, kapanır
            assert e.upstream_heads == []

    run(go())


def test_decision_log_has_no_request_body_or_path():
    async def go():
        async with Env() as e:
            await e.raw(
                f"GET http://allowed.test:{e.up_port}/gizli/yol?token=abc HTTP/1.1\r\n\r\n".encode()
            )
            assert "gizli" not in str(e.decisions) and "token" not in str(e.decisions)

    run(go())


@pytest.mark.parametrize(
    "entry",
    ["example.com", "docs.python.org", "*.pypi.org", "a-b.example.co.uk", "XN--80ak6aa92e.com"],
)
def test_validate_allowed_host_accepts(entry):
    from usta.proxy import validate_allowed_host

    assert validate_allowed_host(entry) == entry.lower()


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "localhost",
        "1.2.3.4",
        "::1",
        "https://example.com",
        "example.com:443",
        "example.com/x",
        "*",
        "*.com",
        "*example.com",
        "ex ample.com",
        "-a.example.com",
        "a..com",
        "*.*.example.com",
        "a@b.com",
    ],
)
def test_validate_allowed_host_rejects(entry):
    from usta.proxy import validate_allowed_host

    with pytest.raises(ValueError):
        validate_allowed_host(entry)


def test_validate_allowed_host_rejects_overlong_labels_and_names():
    from usta.proxy import validate_allowed_host

    with pytest.raises(ValueError):
        validate_allowed_host("a" * 64 + ".com")
    with pytest.raises(ValueError):
        validate_allowed_host(".".join(["abcdefghi"] * 30) + ".com")
    assert validate_allowed_host("a" * 63 + ".com")


@pytest.mark.parametrize(
    "ip,public",
    [
        ("64:ff9b::7f00:1", False),  # NAT64 → 127.0.0.1
        ("64:ff9b::a00:1", False),  # NAT64 → 10.0.0.1
        ("64:ff9b::a9fe:a9fe", False),  # NAT64 → 169.254.169.254 (bulut metadata)
        ("64:ff9b::808:808", True),  # NAT64 → 8.8.8.8
        ("64:ff9b:1::1", False),  # yerel kullanım öneki
    ],
)
def test_nat64_addresses_are_judged_by_their_embedded_ipv4(ip, public):
    assert is_public_ip(ip) is public
