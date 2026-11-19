"""Ortak hafızanın ev sahibi tarafı: eşleşme ve şifreli istekler için ayrı, küçük dinleyici (tasarım: docs/ortak-hafiza.md).

Eşleşme iki adımdır. `baslat`: bağlanan bilgisayarın SPAKE2 mesajı alınır, ev sahibi kendi mesajıyla cevap verir ve
ortak anahtarı türetir; her başlatma bir deneme sayılır. `onay`: bağlanan bilgisayar anahtarı bildiğini önce kanıtlar,
ancak doğruysa ev sahibi kendi onayını verir ve bilgisayarı kaydeder. Yanlış kodla türetilen anahtar uyuşmaz.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from spake2 import SPAKE2_B, SPAKEError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from usta import kisi, localmodels
from usta.auth import LoginCodes
from usta.ortak import (
    _ID_A,
    _ID_B,
    MAX_BODY,
    NONCE_TTL,
    PORT,
    RATE,
    SKEW,
    OrtakError,
    Store,
    _unb64,
    confirm,
    reply_aad,
    request_aad,
    seal,
    session_secret,
    unseal,
)

PAIR_TTL = 60.0  # sn: yarım kalmış eşleşme bu kadar bekler
PAIR_TRIES = 3  # adres başına eşleşme denemesi; sonra kilit
PAIR_LOCK = 900.0  # sn
MAX_PENDING = 20


class _StartIn(BaseModel):
    msg: str = Field(min_length=2, max_length=200)
    ad: str = Field(default="", max_length=80)


class _ConfirmIn(BaseModel):
    sid: str = Field(min_length=1, max_length=64)
    onay: str = Field(min_length=1, max_length=128)


class _NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def private_source(ip: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and addr.is_private and not addr.is_unspecified


def make_app(
    home: Path,
    codes: LoginCodes,
    *,
    allowed_hosts: list[str],
    source_ok: Callable[[str], bool] = private_source,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    store = Store(home)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)  # DNS rebinding
    seen: dict[str, float] = {}
    hits: dict[str, deque] = {}
    pending: dict[str, dict] = {}  # sid -> yarım eşleşme (anahtar, kod, ad, adres, süre)
    tries: dict[str, list[float]] = {}  # adres -> [deneme sayısı, kilit bitişi]
    lock = threading.Lock()

    def gate(request: Request) -> str:
        """Her istekte: özel ağ kaynağı, `Origin` yok, hız sınırı. Kaynak adresi döndürür."""
        ip = request.client.host if request.client else ""
        if not source_ok(ip):
            raise HTTPException(403, "yalnız evdeki ağdan")
        if "origin" in request.headers:  # tarayıcı sayfası başka bir siteden istek attıramaz
            raise HTTPException(403, "tarayıcıdan erişilemez")
        n, window = RATE
        now = clock()
        with lock:
            q = hits.setdefault(ip, deque())
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= n:
                raise HTTPException(429, "çok fazla istek")
            q.append(now)
        return ip

    async def read_body(request: Request) -> bytes:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY:
            raise HTTPException(413, "istek çok büyük")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY:
                raise HTTPException(413, "istek çok büyük")
        return body

    async def verified(request: Request) -> tuple[dict, bytes, str]:
        """Şifreyi çözer ve doğrular: (eşleşmiş bilgisayar, açık gövde, istek kimliği). Hata hep aynı 401."""
        gate(request)
        body = await read_body(request)
        h = request.headers
        key_id, ts, nonce = (h.get(k, "") for k in ("x-usta-key", "x-usta-ts", "x-usta-nonce"))
        bad = HTTPException(401, "istek doğrulanamadı")
        peer = store.peer(key_id) if key_id else None
        if peer is None or len(nonce) != 24:
            raise bad
        try:
            if abs(clock() - float(ts)) > SKEW:
                raise bad
            secret = _unb64(peer["secret"])
            plain = unseal(
                secret, nonce, request_aad(request.method, request.url.path, ts, key_id), body
            )
        except ValueError:
            raise bad from None
        now = clock()
        with lock:  # doğrulandıktan sonra: aynı kimlik ikinci kez kabul edilmez
            for k in [k for k, t in seen.items() if t < now - NONCE_TTL]:
                del seen[k]
            if f"{key_id}:{nonce}" in seen:
                raise bad
            seen[f"{key_id}:{nonce}"] = now
        return peer, plain, nonce

    def reply(peer: dict, nonce: str, payload: dict) -> Response:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        rnonce, sealed = seal(_unb64(peer["secret"]), reply_aad(nonce), body)
        return Response(
            content=sealed, media_type="application/octet-stream", headers={"X-Usta-Nonce": rnonce}
        )

    @app.post("/ortak/eslesme/baslat")
    async def pair_start(request: Request) -> JSONResponse:
        ip = gate(request)
        try:
            data = _StartIn.model_validate_json(await read_body(request))
            inbound = bytes.fromhex(data.msg)
        except ValueError:
            raise HTTPException(422, "istek geçersiz") from None
        now = clock()
        with lock:
            for k in [k for k, p in pending.items() if p["until"] < now]:
                del pending[k]
            count, until = tries.get(ip, [0, 0.0])
            if until > now:
                raise HTTPException(429, "çok fazla deneme")
            code = codes.peek()
            if code is None:
                raise HTTPException(401, "kod yok ya da süresi dolmuş")
            if len(pending) >= MAX_PENDING:
                raise HTTPException(429, "çok fazla deneme")
            count += 1  # her başlatma bir tahmin hakkıdır: onaylanmasa da sayılır
            tries[ip] = [0, now + PAIR_LOCK] if count >= PAIR_TRIES else [count, 0.0]
            side = SPAKE2_B(code.encode(), idA=_ID_A, idB=_ID_B)
            outbound = side.start()
            try:
                key = side.finish(inbound)
            except SPAKEError:
                raise HTTPException(422, "istek geçersiz") from None
            sid = secrets.token_hex(16)
            pending[sid] = {
                "key": key,
                "code": code,
                "ad": data.ad,
                "ip": ip,
                "until": now + PAIR_TTL,
            }
        return JSONResponse({"sid": sid, "msg": outbound.hex(), "ad": store.name})

    @app.post("/ortak/eslesme/onay")
    async def pair_confirm(request: Request) -> JSONResponse:
        ip = gate(request)
        try:
            data = _ConfirmIn.model_validate_json(await read_body(request))
        except ValueError:
            raise HTTPException(422, "istek geçersiz") from None
        bad = HTTPException(401, "kod geçersiz, süresi dolmuş veya kullanılmış")
        with lock:
            p = pending.pop(data.sid, None)
        if p is None or p["ip"] != ip or p["until"] < clock():
            raise bad
        if not secrets.compare_digest(data.onay, confirm(p["key"], "bagli", data.sid)):
            codes.fail()
            raise bad
        if not codes.consume(p["code"]):
            raise bad
        with lock:
            tries.pop(ip, None)
        try:
            key_id = store.add_peer(p["ad"], session_secret(p["key"]))
        except OrtakError as e:
            raise HTTPException(409, str(e)) from None
        return JSONResponse({"key_id": key_id, "onay": confirm(p["key"], "ev", data.sid)})

    @app.get("/ortak/hafiza")
    async def memory(request: Request) -> Response:
        peer, _, nonce = await verified(request)
        notes = [
            {"id": n["id"], "text": n["text"], "kaynak": n["kaynak"]} for n in store.approved()
        ]
        return reply(
            peer, nonce, {"profil": asdict(kisi.load(home)), "notlar": notes, "ad": store.name}
        )

    @app.post("/ortak/not")
    async def add_note(request: Request) -> Response:
        peer, body, nonce = await verified(request)
        try:
            data = _NoteIn.model_validate_json(body)
            note = store.add(data.text, peer["ad"], approved=False)  # dışarıdan: onay bekler
        except ValueError:
            raise HTTPException(422, "istek geçersiz") from None
        except OrtakError as e:
            raise HTTPException(422, str(e)) from None
        return reply(peer, nonce, {"id": note["id"], "durum": note["durum"]})

    return app


class HostServer:
    """Ev sahibinin ikinci dinleyicisi (uvicorn, ayrı iş parçacığı). Yalnız özel ağ adresine bağlanır."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.store = Store(home)
        self.codes = LoginCodes(ttl=300.0, digits=6)
        self._server = None
        self._thread: threading.Thread | None = None
        self.address: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, bind: str | None = None, port: int = PORT) -> str:
        import uvicorn

        if self.running:
            return self.address or ""
        ip = bind or localmodels.own_ip() or ""
        if not private_source(ip):
            raise OrtakError(
                "Bu bilgisayarın evdeki ağ adresini bulamadım. Wi-Fi ya da kabloya bağlı mısın?"
            )
        for p in range(port, port + 10):  # meşgulse sıradaki port
            with socket.socket() as s, contextlib.suppress(OSError):
                # uvicorn da böyle bağlanır; yoksa kapanan bağlantıların bekleme süresi kapıyı dolu gösterir.
                # Windows'ta bu seçenek başka programın kapısını ele geçirmeye izin verir, orada açılmaz.
                if os.name != "nt":
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((ip, p))
                break
        else:
            raise OrtakError("Ortak hafıza için boş bir kapı bulamadım.")
        name = socket.gethostname().lower()
        hosts = [ip, name, f"{name}.local", "localhost"]
        app = make_app(self.home, self.codes, allowed_hosts=hosts)
        self._server = uvicorn.Server(uvicorn.Config(app, host=ip, port=p, log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise OrtakError("Ortak hafıza dinleyicisi başlatılamadı.")
            time.sleep(0.05)
        self.address = f"{ip}:{p}"
        return self.address

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server, self._thread, self.address = None, None, None

    def start_if_enabled(self) -> None:
        if self.store.enabled and not self.running:
            with contextlib.suppress(OrtakError):  # ağ yoksa Usta yine açılır
                self.start()
