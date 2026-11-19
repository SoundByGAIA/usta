"""HTTP API (FastAPI): çalışma alanları, görevler, SSE olay akışı, onaylar, diff, denetim."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from usta import (
    api_files,
    api_llm,
    api_local,
    api_mcp,
    api_ortak,
    api_settings,
    api_skills,
    attachments,
    compat,
    filetree,
    harnesses,
    memory,
    ortak,
    privacy,
    skills,
    support,
)
from usta import settings as usta_settings
from usta.api_models import (
    ID_PATTERN,
    ApprovalIn,
    CodeIn,
    MessageIn,
    TaskIn,
    WorkspaceId,
    WorkspaceIn,
)
from usta.auth import LoginCodes
from usta.policy import PathEscapeError, resolve_path
from usta.tasks import PlanNotFound, RevertRefused, TaskFinished, TaskManager, WorkspaceBusy

KEEPALIVE = 15.0

WEB_DIR = Path(__file__).parent / "web"
UI_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/settings.js": ("settings.js", "text/javascript; charset=utf-8"),
    "/setup.js": ("setup.js", "text/javascript; charset=utf-8"),
    "/logic.js": ("logic.js", "text/javascript; charset=utf-8"),
    "/office-logic.js": ("office-logic.js", "text/javascript; charset=utf-8"),
    "/glossary.js": ("glossary.js", "text/javascript; charset=utf-8"),
    "/office-scene.js": ("office-scene.js", "text/javascript; charset=utf-8"),
    "/office-actors.js": ("office-actors.js", "text/javascript; charset=utf-8"),
    "/office.js": ("office.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
UI_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


PREVIEW_MAX = 5_000_000
PREVIEW_HEADERS = {
    # Ajanın yazdığı içerik güvenilmezdir: opak kaynakta (sandbox, allow-same-origin YOK) çalışır,
    # portalın jetonuna/oturumuna erişemez ve ağa çıkamaz.
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'none'; form-action 'none'; frame-ancestors 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def load_or_create_token(home: Path) -> str:
    """Yönetici jetonu home/token dosyasında (0600) tutulur; repoya girmez."""
    path = Path(home) / "token"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


MAX_BODY = 10_000_000  # varsayılan istek gövdesi sınırı (kimlik doğrulamadan ÖNCE uygulanır)
MAX_BODY_IMPORT = 32_000_000
MAX_BODY_AUTH = 4_096


def _body_limit(path: str) -> int:
    if path == "/auth/exchange":
        return MAX_BODY_AUTH
    return MAX_BODY_IMPORT if re.fullmatch(r"/workspaces/[^/]+/import", path) else MAX_BODY


class BodyLimitMiddleware:
    """İstek gövdesini boyuta göre keser (yetki denetimi gövdeyi okumadan önce çalışsın diye ASGI düzeyinde)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _body_limit(scope.get("path", ""))
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        responded = False

        async def too_large():
            nonlocal responded
            if responded:
                return
            responded = True
            body = b'{"detail":"istek \xc3\xa7ok b\xc3\xbcy\xc3\xbck"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"connection", b"close"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

        if declared.isdigit() and int(declared) > limit:
            await too_large()
            return
        received = 0

        async def limited_receive():
            nonlocal received
            if responded:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    await too_large()
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not responded:
                await send(msg)

        await self.app(scope, limited_receive, guarded_send)


def create_app(
    manager: TaskManager,
    home: Path,
    token: str,
    login: LoginCodes | None = None,
    workspace: str | None = None,
    trusted_hosts: list[str] | None = None,
    pair: LoginCodes | None = None,
    lan_urls: list[str] | None = None,
    on_quit: Callable[[], None] | None = None,
) -> FastAPI:
    home = Path(home)

    def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        given = authorization.removeprefix("Bearer ") if authorization else ""
        if not given or not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "yetkisiz", headers={"WWW-Authenticate": "Bearer"})

    app = FastAPI(title="Usta", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimitMiddleware)
    if trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
    api = APIRouter(dependencies=[Depends(auth)])

    def ws_root(workspace: str) -> Path:
        root = home / "workspaces" / workspace
        if not root.is_dir():
            raise HTTPException(404, "çalışma alanı yok")
        return root

    def get_task(task_id: str):
        try:
            return manager.get(task_id)
        except KeyError:
            raise HTTPException(404, "görev yok") from None

    @api.post("/workspaces", status_code=201)
    def create_workspace(body: WorkspaceIn) -> dict:
        root = home / "workspaces" / body.name
        try:
            root.mkdir(parents=True)
        except FileExistsError:
            raise HTTPException(409, "çalışma alanı zaten var") from None
        return {"id": body.name}

    @api.get("/workspaces")
    def list_workspaces() -> list[dict]:
        base = home / "workspaces"
        return (
            [{"id": p.name} for p in sorted(base.iterdir()) if p.is_dir()] if base.is_dir() else []
        )

    def preview_key(workspace: str) -> str:
        return hmac.new(
            token.encode(), f"preview:{workspace}".encode(), hashlib.sha256
        ).hexdigest()[:32]

    @api.get("/workspaces/{workspace}/preview")
    def preview_info(workspace: WorkspaceId) -> dict:
        ws_root(workspace)
        return {"base": f"/preview/{workspace}/{preview_key(workspace)}/"}

    @api.post("/workspaces/{workspace}/reveal")
    def reveal_workspace(workspace: WorkspaceId) -> dict:
        """Çalışma klasörünü bu bilgisayarın dosya yöneticisinde açar (yalnız o klasör; yol dışarıdan alınmaz)."""
        root = ws_root(workspace).resolve()
        try:
            compat.open_folder(root)
        except OSError:
            raise HTTPException(500, "klasör açılamadı") from None
        return {"opened": str(root)}

    def idle_ws(workspace: str) -> Path:
        root = ws_root(workspace)
        if manager.is_busy(workspace):
            raise HTTPException(409, "çalışma alanında görev sürüyor")
        return root

    api_files.register(api, home, manager, ws_root, idle_ws)
    api_skills.register(api, home)
    api_local.register(api)

    @api.get("/workspaces/{workspace}/memory")
    def get_memory(workspace: WorkspaceId) -> dict:
        root = ws_root(workspace)
        return {"notes": memory.list_notes(root), "history": memory.recent_history(root, 50)}

    @api.delete("/workspaces/{workspace}/memory/notes/{index}")
    def delete_note(workspace: WorkspaceId, index: Annotated[int, PathParam(ge=0)]) -> dict:
        root = idle_ws(workspace)
        try:
            memory.delete_note(root, index)
        except IndexError:
            raise HTTPException(404, "not yok") from None
        except (OSError, ValueError):
            raise HTTPException(400, "hafıza yazılamadı") from None
        return {"deleted": index}

    @api.delete("/workspaces/{workspace}/memory/history")
    def clear_memory_history(workspace: WorkspaceId) -> dict:
        root = idle_ws(workspace)
        try:
            memory.clear_history(root)
        except (OSError, ValueError):
            raise HTTPException(400, "hafıza yazılamadı") from None
        return {"cleared": True}

    ohost = api_ortak.register(api, home)

    api_mcp.register(api, home)
    api_settings.register(api, home, manager, workspace=workspace, background=on_quit is not None)
    api_rows = api_llm.register(api, home, manager)

    @api.post("/workspaces/{workspace}/tasks", status_code=202)
    def create_task(workspace: WorkspaceId, body: TaskIn) -> dict:
        root = ws_root(workspace)
        try:
            files = [(f.name, f.content) for f in body.files]
            prompt = body.prompt if body.apply_plan else skills.expand(home, body.prompt)
            return manager.start(
                workspace,
                root,
                prompt,
                body.mode,
                body.guard,
                files,
                body.apply_plan,
                body.phased,
                design_skill=body.design_skill,
            ).public()
        except PlanNotFound:
            raise HTTPException(
                404, "uygulanacak plan yok (plan modunda başarıyla bitmiş olmalı)"
            ) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except attachments.AttachmentError as e:
            raise HTTPException(400, str(e)) from None
        except WorkspaceBusy:
            raise HTTPException(409, "çalışma alanında görev sürüyor") from None

    @api.get("/workspaces/{workspace}/sessions")
    def list_sessions(workspace: WorkspaceId) -> list[dict]:
        ws_root(workspace)
        return manager.sessions.list(workspace)

    @api.get("/workspaces/{workspace}/sessions/{task_id}")
    def get_session(workspace: WorkspaceId, task_id: str) -> dict:
        ws_root(workspace)
        found = manager.sessions.load(workspace, task_id)
        if found is None:
            raise HTTPException(404, "oturum yok")
        return found

    @api.post("/tasks/{task_id}/messages", status_code=202)
    def task_message(task_id: str, body: MessageIn) -> dict:
        get_task(task_id)
        try:
            manager.post_message(task_id, body.text)
        except TaskFinished:
            raise HTTPException(409, "görev bitti") from None
        return {"queued": True}

    @api.post("/quit")
    def quit_app() -> dict:
        """Arka planda çalışan Usta'yı kapatır (siyah pencere olmadığı için kullanıcının başka yolu yok)."""
        if on_quit is None:
            raise HTTPException(404, "Usta bu modda buradan kapatılamaz (terminalden çık).")
        threading.Timer(0.5, on_quit).start()  # yanıt gitsin, sonra kapan
        return {"quit": True}

    @api.post("/pair")
    def make_pair() -> dict:
        """Tablet/telefon için kısa ömürlü eşleştirme PIN'i. Yalnız `usta --lan` ile açık."""
        if pair is None:
            raise HTTPException(404, "Yerel ağ modu kapalı. Usta'yı `usta --lan` ile başlat.")
        return {"pin": pair.issue(), "ttl": int(pair.ttl), "urls": list(lan_urls or [])}

    @api.get("/privacy")
    def get_privacy() -> dict:
        ctl = manager.model_control
        sources = [{"name": r["name"], "endpoint": r["endpoint"]} for r in api_rows()]
        shared, link = None, ortak.load_link(home)
        if link is not None:
            shared = (
                f"Evdeki ortak hafıza: bu bilgisayar {link['adres']} adresindeki ev sahibi bilgisayarla konuşur. "
                "Kişisel bilgilerin ve ortak notlar oradan alınır ve her görevde yapay zekâya gider. İstekler "
                "imzalıdır ama şifrelenmez; yalnız güvendiğin ev ağında kullan."
            )
        elif ortak.Store(home).enabled:
            shared = (
                f"Bu bilgisayar evdeki ortak hafızayı tutuyor ({ohost.address or 'şu an kapalı'}). Eşleşmiş "
                "bilgisayarlar profilini ve onayladığın notları alır. İstekler imzalıdır ama şifrelenmez."
            )
        return privacy.report(
            home,
            sources,
            ctl.api if ctl else None,
            getattr(manager, "allowed_hosts", None),
            lan_urls=list(lan_urls or []) if pair is not None else None,
            shared=shared,
            delegates=tuple(
                harnesses.CATALOG[i].label
                for i in usta_settings.load(home).delegates
                if i in harnesses.CATALOG
            ),
        )

    @api.get("/support/report")
    def support_report() -> dict:
        """Yardım raporu: kullanıcı görür ve kendisi gönderir; hiçbir yere kendiliğinden gitmez."""
        ctl = manager.model_control
        src = ctl._source(ctl.api) if ctl and ctl.api else None
        cur = usta_settings.load(home)
        text = support.report(
            home,
            model=ctl.name if ctl else None,
            api=ctl.api if ctl else None,
            endpoint=src.endpoint if src else None,
            settings={
                "görünüm": cur.view,
                "mod": cur.mode,
                "düşünme": cur.think,
                "bağlam": cur.context_window or "otomatik",
            },
            background=on_quit is not None,
            lan=pair is not None,
        )
        return {"filename": f"usta-yardim-{time.strftime('%Y%m%d-%H%M')}.txt", "text": text}

    @api.get("/tasks/{task_id}")
    def task_info(task_id: str) -> dict:
        return get_task(task_id).public()

    @api.get("/tasks/{task_id}/events")
    def task_events(task_id: str, last_event_id: Annotated[str | None, Header()] = None):
        task = get_task(task_id)
        try:
            nxt = int(last_event_id) + 1 if last_event_id is not None else 0
        except ValueError:
            raise HTTPException(400, "Last-Event-ID geçersiz") from None

        def stream():
            i = max(nxt, 0)
            while True:
                events, finished = task.wait_events(i, KEEPALIVE)
                for e in events:
                    data = json.dumps(e["data"], ensure_ascii=False)
                    yield f"id: {e['i']}\nevent: {e['type']}\ndata: {data}\n\n"
                i += len(events)
                if finished and not events:
                    return
                if not events:
                    yield ": keepalive\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @api.post("/tasks/{task_id}/cancel", status_code=202)
    def cancel_task(task_id: str) -> dict:
        get_task(task_id)
        manager.cancel(task_id)
        return get_task(task_id).public()

    @api.post("/tasks/{task_id}/revert")
    def revert_task(task_id: str) -> dict:
        task = get_task(task_id)
        if not task.finished.is_set():
            raise HTTPException(409, "görev sürüyor")
        try:
            manager.revert(task_id)
        except WorkspaceBusy:
            raise HTTPException(409, "çalışma alanında görev sürüyor") from None
        except RevertRefused as e:
            raise HTTPException(409, str(e)) from None
        return {"reverted": task_id}

    @api.get("/tasks/{task_id}/diff", response_class=PlainTextResponse)
    def task_diff(task_id: str) -> str:
        task = get_task(task_id)
        if not task.finished.is_set():
            raise HTTPException(409, "görev sürüyor")
        return task.diff

    @api.post("/approvals/{approval_id}")
    def resolve_approval(approval_id: str, body: ApprovalIn) -> dict:
        try:
            manager.resolve_approval(approval_id, body.decision == "allow")
        except KeyError:
            raise HTTPException(404, "onay isteği yok") from None
        return {"decision": body.decision}

    @api.get("/audit")
    def audit(
        workspace: Annotated[str, Query(pattern=ID_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict]:
        path = home / "audit" / f"{workspace}.jsonl"
        if not path.is_file():
            return []
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in deque(f, maxlen=limit)]

    @app.get("/preview/{workspace}/{key}/{path:path}", include_in_schema=False)
    def preview(workspace: WorkspaceId, key: str, path: str = "") -> Response:
        """Çalışma alanındaki statik dosyaları önizler (yalnız GET, anahtar çalışma alanına bağlı)."""
        if not hmac.compare_digest(key.encode(), preview_key(workspace).encode()):
            raise HTTPException(403, "önizleme anahtarı geçersiz")
        root = ws_root(workspace)
        try:
            full = resolve_path(root, path or ".")
        except PathEscapeError:
            raise HTTPException(404, "yok") from None
        if full.is_dir():
            try:  # index.html de yeniden çözülür: sembolik bağ ile dışarı kaçamaz
                full = resolve_path(root, f"{path.rstrip('/') or '.'}/index.html")
            except PathEscapeError:
                raise HTTPException(404, "yok") from None
        parts = full.relative_to(root.resolve()).parts
        if not full.is_file() or any(p in filetree.HIDDEN for p in parts):
            raise HTTPException(404, "yok")
        if full.stat().st_size > PREVIEW_MAX:
            raise HTTPException(413, "dosya çok büyük")
        ctype = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        return Response(full.read_bytes(), media_type=ctype, headers=PREVIEW_HEADERS)

    app.include_router(api)
    app.state.ortak_host = ohost

    if login is not None:  # terminalin açtığı portal: tek kullanımlık kodu jetonla takas eder

        @app.post("/auth/code", dependencies=[Depends(auth)])
        def new_login_code() -> dict:
            """Zaten çalışan Usta'ya ikinci kez tıklanınca yeni tarayıcı oturumu için kod verir (jeton gerekir)."""
            return {"code": login.issue()}

        @app.post("/auth/exchange")
        def exchange(body: CodeIn) -> dict:
            # Tablet/telefon eşleştirme PIN'i (yalnız rakam) ayrı deponun sayacını kullanır; yanlış PIN
            # bilgisayardaki tarayıcının kodunu kilitlemez.
            if (
                pair is not None
                and pair.digits
                and re.fullmatch(rf"\d{{{pair.digits}}}", body.code)
            ):
                ok = pair.redeem(body.code)
            else:
                ok = login.redeem(body.code)
            if not ok:
                raise HTTPException(401, "kod geçersiz, süresi dolmuş veya kullanılmış")
            return {"token": token}

    # Arayüz dosyaları jetonsuz sunulur (içlerinde sır yok); sabit rota listesi, dizin gezinmesi yok.
    for route, (name, ctype) in UI_FILES.items():
        body = (WEB_DIR / name).read_bytes()

        def ui(body: bytes = body, ctype: str = ctype) -> Response:
            return Response(body, media_type=ctype, headers=UI_HEADERS)

        app.add_api_route(route, ui, methods=["GET"], include_in_schema=False)

    app.add_api_route(
        "/favicon.ico",
        lambda: Response(status_code=204, headers=UI_HEADERS),
        methods=["GET"],
        include_in_schema=False,
    )

    return app
