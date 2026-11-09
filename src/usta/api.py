"""HTTP API (FastAPI): çalışma alanları, görevler, SSE olay akışı, onaylar, diff, denetim."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
from collections import deque
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from usta import (
    apis,
    attachments,
    filetree,
    localmodels,
    mcp_runtime,
    mcpcatalog,
    mcpconfig,
    memory,
    skills,
)
from usta import settings as usta_settings
from usta.audit import AuditLog
from usta.auth import LoginCodes
from usta.mcp import McpClient, McpError
from usta.modelctl import ModelSwitchError
from usta.policy import PathEscapeError, resolve_path
from usta.tasks import PlanNotFound, RevertRefused, TaskFinished, TaskManager, WorkspaceBusy

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"
MAX_FILE = 1_000_000
KEEPALIVE = 15.0

WEB_DIR = Path(__file__).parent / "web"
UI_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/logic.js": ("logic.js", "text/javascript; charset=utf-8"),
    "/office-logic.js": ("office-logic.js", "text/javascript; charset=utf-8"),
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

WorkspaceId = Annotated[str, PathParam(pattern=ID_PATTERN)]
ServerName = Annotated[str, PathParam(pattern=r"^[a-z0-9][a-z0-9_-]{0,29}$")]


class WorkspaceIn(BaseModel):
    name: str = Field(pattern=ID_PATTERN)


class AttachIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=attachments.MAX_FILE * 2)


class TaskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    mode: Literal["manual", "auto", "plan"] = "manual"
    guard: bool | None = None  # None: sunucu varsayılanı
    files: list[AttachIn] = Field(default_factory=list, max_length=attachments.MAX_FILES)
    apply_plan: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{12}$"
    )  # bitmiş plan görevinin kimliği
    phased: bool = (
        False  # planı PLAN.md aşamalarına bölüp her aşamayı taze bağlamla ayrı görev koştur
    )


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ModelIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    api: str | None = Field(default=None, max_length=30)


class ApiIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    endpoint: str = Field(min_length=1, max_length=500)
    key: str | None = Field(default=None, max_length=8192)


class KeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=8192)


class ImportFile(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    b64: str = Field(max_length=filetree.MAX_IMPORT_FILE * 2)


class ImportIn(BaseModel):
    files: list[ImportFile] = Field(max_length=filetree.MAX_IMPORT_FILES)
    overwrite: bool = False


class FsOp(BaseModel):
    op: Literal["create_file", "create_dir", "rename", "delete"]
    path: str = Field(min_length=1, max_length=500)
    to: str | None = Field(default=None, max_length=500)


class SkillIn(BaseModel):
    content: str = Field(min_length=1, max_length=skills.MAX_SIZE * 2)


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


class SettingsIn(BaseModel):
    """Portaldan yalnız görünüm ve mod değiştirilebilir; uç nokta/model/sırlar buradan değişmez."""

    theme: Literal["beyaz", "gri", "siyah"] | None = None
    mode: Literal["manual", "auto", "plan"] | None = None
    guard: bool | None = None
    zoom: Literal["auto", "0.9", "1", "1.1", "1.25", "1.5", "1.75"] | None = None
    think: Literal["auto", "off", "low", "medium", "high"] | None = None
    context_window: int | None = Field(default=None, ge=0, le=2_000_000)  # 0: otomatik (sınır yok)


class LocalScanIn(BaseModel):
    port: int | None = Field(default=None, ge=1, le=65535)


class LocalCtxIn(BaseModel):
    port: int = Field(ge=1, le=65535)
    model: str = Field(min_length=1, max_length=120)
    num_ctx: int = Field(ge=256, le=2_000_000)


class CodeIn(BaseModel):
    code: str = Field(max_length=200)


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class EnabledIn(BaseModel):
    enabled: bool


class FileIn(BaseModel):
    content: str = Field(max_length=MAX_FILE)


class ApprovalIn(BaseModel):
    decision: Literal["allow", "deny"]


def load_or_create_token(home: Path) -> str:
    """Yönetici jetonu home/token dosyasında (0600) tutulur; repoya girmez."""
    path = Path(home) / "token"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
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

    @api.get("/workspaces/{workspace}/tree")
    def tree(workspace: WorkspaceId, path: str = "") -> dict:
        root = ws_root(workspace)
        try:
            full = resolve_path(root, path or ".")
        except PathEscapeError:
            raise HTTPException(400, "geçersiz yol") from None
        if not full.is_dir():
            raise HTTPException(404, "klasör yok")
        try:
            return {"path": path, "entries": filetree.list_dir(full)}
        except OSError:
            raise HTTPException(400, "klasör okunamadı") from None

    @api.post("/workspaces/{workspace}/import")
    def import_files(workspace: WorkspaceId, body: ImportIn) -> dict:
        root = idle_ws(workspace)
        try:
            decoded = filetree.decode_files([(f.path, f.b64) for f in body.files])
        except filetree.ImportError_ as e:
            raise HTTPException(400, str(e)) from None
        written, skipped = [], []
        for rel, data in decoded:
            try:
                full = resolve_path(root, rel)
            except PathEscapeError:
                raise HTTPException(400, f"geçersiz yol: {rel}") from None
            if full.exists() and not body.overwrite:
                skipped.append(rel)
                continue
            try:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(data)
            except OSError:
                raise HTTPException(400, f"yazılamadı: {rel}") from None
            written.append(rel)
        return {"written": written, "skipped": skipped}

    @api.post("/workspaces/{workspace}/fs")
    def fs_op(workspace: WorkspaceId, body: FsOp) -> dict:
        root = idle_ws(workspace)
        try:
            if body.op == "create_file":
                filetree.create(root, body.path, is_dir=False)
            elif body.op == "create_dir":
                filetree.create(root, body.path, is_dir=True)
            elif body.op == "rename":
                if not body.to:
                    raise HTTPException(400, "yeni ad gerekli")
                filetree.rename(root, body.path, body.to)
            else:
                filetree.delete(root, body.path)
        except filetree.FsError as e:
            raise HTTPException(e.status, str(e)) from None
        with contextlib.suppress(OSError):
            AuditLog(home / "audit" / f"{workspace}.jsonl").record(
                "fs_op", op=body.op, path=body.path, to=body.to
            )
        return {"ok": True}

    @api.get("/skills")
    def list_skills() -> list[dict]:
        return skills.list_skills(home)

    @api.put("/skills/{name}")
    def put_skill(name: str, body: SkillIn) -> dict:
        try:
            skills.put(home, name, body.content)
        except skills.SkillError as e:
            raise HTTPException(400, str(e)) from None
        return {"name": name}

    @api.delete("/skills/{name}")
    def delete_skill(name: str) -> dict:
        try:
            skills.delete(home, name)
        except skills.SkillError as e:
            raise HTTPException(404, str(e)) from None
        return {"removed": name}

    @api.get("/workspaces/{workspace}/files")
    def read_file(workspace: WorkspaceId, path: str) -> dict:
        root = ws_root(workspace)
        try:
            full = resolve_path(root, path)
        except PathEscapeError:
            raise HTTPException(400, "geçersiz yol") from None
        if not full.exists():
            raise HTTPException(404, "dosya yok")
        if not full.is_file():
            raise HTTPException(400, "dosya değil")
        if full.stat().st_size > MAX_FILE:
            raise HTTPException(413, "dosya çok büyük")
        raw = full.read_bytes()
        if b"\x00" in raw[:8192]:
            raise HTTPException(415, "ikili dosya gösterilemez")
        return {"path": path, "content": raw.decode(errors="replace")}

    @api.put("/workspaces/{workspace}/files")
    def write_file(workspace: WorkspaceId, path: str, body: FileIn) -> dict:
        root = ws_root(workspace)
        try:
            full = resolve_path(root, path)
        except PathEscapeError:
            raise HTTPException(400, "geçersiz yol") from None
        if manager.is_busy(workspace):
            raise HTTPException(409, "çalışma alanında görev sürüyor")
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(body.content)
        except OSError:
            raise HTTPException(400, "yazılamadı") from None
        return {"path": path, "bytes": len(body.content.encode())}

    def idle_ws(workspace: str) -> Path:
        root = ws_root(workspace)
        if manager.is_busy(workspace):
            raise HTTPException(409, "çalışma alanında görev sürüyor")
        return root

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

    @api.get("/settings")
    def get_settings() -> dict:
        cur = usta_settings.load(home)
        return {
            "theme": cur.theme,
            "mode": cur.mode,
            "guard": cur.guard,
            "zoom": cur.zoom,
            "think": cur.think,
            "context_window": cur.context_window or 0,
            "workspace": workspace,
        }

    @api.put("/settings")
    def put_settings(body: SettingsIn) -> dict:
        import dataclasses

        cur = usta_settings.load(home)
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if "context_window" in changes:
            cw = changes["context_window"]
            if cw == 0:
                changes["context_window"] = None
            elif cw < 256:
                raise HTTPException(422, "bağlam en az 256 token olmalı")
        try:
            new = dataclasses.replace(cur, **changes)
            usta_settings.save(home, new)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except OSError:
            raise HTTPException(500, "ayar kaydedilemedi") from None
        if "context_window" in changes:
            manager.context_window = new.context_window  # bir sonraki görevden itibaren
        if "think" in changes and manager.model_control is not None:
            manager.model_control.rebuild()
        return {
            "theme": new.theme,
            "mode": new.mode,
            "guard": new.guard,
            "zoom": new.zoom,
            "think": new.think,
            "context_window": new.context_window or 0,
        }

    # --- MCP: yalnız katalogdan ekleme; serbest komut yok (bkz. mcpcatalog) -------------------
    def mcp_servers() -> dict[str, mcpconfig.Server]:
        try:
            return mcpconfig.load(home)
        except mcpconfig.McpConfigError as e:
            raise HTTPException(500, f"MCP yapılandırması: {e}") from None

    def mcp_server(name: str) -> mcpconfig.Server:
        server = mcp_servers().get(name)
        if server is None:
            raise HTTPException(404, "sunucu yok")
        return server

    @api.get("/mcp")
    def mcp_list() -> dict:
        servers = mcp_servers()
        out = []
        for s in servers.values():
            have = mcpconfig.resolve_env(home, s, os.environ)
            out.append(
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "approve": s.approve,
                    "command": list(s.command),
                    "env": [{"name": k, "set": k in have} for k in s.env],
                    "isolation": s.isolation,
                    "image": s.image,
                    "allow_hosts": list(s.allow_hosts),
                    "pinned": bool(s.pin_image and s.pin_cache),
                }
            )
        catalog = [
            {
                "id": e.id,
                "title": e.title,
                "description": e.description,
                "homepage": e.homepage,
                "command": list(e.command),
                "env": list(e.env),
                "image": e.image,
                "allow_hosts": list(e.allow_hosts),
                "added": e.id in servers,
            }
            for e in mcpcatalog.CATALOG
        ]
        return {"servers": out, "catalog": catalog}

    @api.post("/mcp/catalog/{entry_id}", status_code=201)
    def mcp_add_from_catalog(entry_id: str) -> dict:
        entry = mcpcatalog.get(entry_id)
        if entry is None:
            raise HTTPException(404, "katalogda yok")
        try:
            mcpconfig.add_server(
                home,
                entry.id,
                list(entry.command),
                list(entry.env),
                "ask",
                isolation="container",  # katalog sunucuları her zaman yalıtılmış çalışır
                image=entry.image,
                allow_hosts=list(entry.allow_hosts),
            )
        except mcpconfig.McpConfigError as e:
            raise HTTPException(409 if "zaten" in str(e) else 400, str(e)) from None
        return {"name": entry.id}

    @api.put("/mcp/{name}/secrets/{key}")
    def mcp_set_secret(name: ServerName, key: str, body: SecretIn) -> dict:
        mcp_server(name)
        try:
            mcpconfig.set_secret(home, name, key, body.value)
        except mcpconfig.McpConfigError as e:
            raise HTTPException(404 if "tanımlı değil" in str(e) else 400, str(e)) from None
        return {"set": True}

    @api.post("/mcp/{name}/enabled")
    def mcp_enable(name: ServerName, body: EnabledIn) -> dict:
        mcp_server(name)
        mcpconfig.set_enabled(home, name, body.enabled)
        return {"enabled": body.enabled}

    @api.delete("/mcp/{name}")
    def mcp_remove(name: ServerName) -> dict:
        mcp_server(name)
        mcpconfig.remove_server(home, name)
        return {"removed": name}

    @api.post("/mcp/{name}/test")
    def mcp_test(name: ServerName) -> dict:
        server = mcp_server(name)
        env = mcpconfig.resolve_env(home, server, os.environ)
        try:
            if server.isolation == "host":  # yalnız CLI'dan açıkça eklenmiş uyumluluk modu
                with McpClient(list(server.command), env, timeout=90) as client:
                    tools = client.list_tools()
            else:
                handle = mcp_runtime.start(server, home=home, env=env, workspace=None, timeout=90)
                try:
                    tools = handle.client.list_tools()
                finally:
                    handle.close()
        except McpError as e:
            raise HTTPException(502, str(e)) from None
        return {"tools": [{"name": t.name, "description": t.description[:200]} for t in tools]}

    @api.post("/mcp/{name}/prepare")
    def mcp_prepare(name: ServerName) -> dict:
        server = mcp_server(name)
        if server.isolation != "container":
            raise HTTPException(400, "yalnız konteyner izolasyonlu sunucular hazırlanır")
        try:
            iid, digest = mcp_runtime.prepare(
                server, home=home, env=mcpconfig.resolve_env(home, server, os.environ)
            )
            mcpconfig.set_pin(home, name, iid, digest)
        except McpError as e:
            raise HTTPException(502, str(e)) from None
        return {"pinned": True}

    @api.post("/workspaces/{workspace}/tasks", status_code=202)
    def create_task(workspace: WorkspaceId, body: TaskIn) -> dict:
        root = ws_root(workspace)
        try:
            files = [(f.name, f.content) for f in body.files]
            prompt = body.prompt if body.apply_plan else skills.expand(home, body.prompt)
            return manager.start(
                workspace, root, prompt, body.mode, body.guard, files, body.apply_plan, body.phased
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

    @api.get("/model")
    def get_model() -> dict:
        ctl = manager.model_control
        if ctl is None:
            raise HTTPException(404, "model değiştirme bu sunucuda yok")
        return ctl.info()

    @api.put("/model")
    def put_model(body: ModelIn) -> dict:
        ctl = manager.model_control
        if ctl is None:
            raise HTTPException(404, "model değiştirme bu sunucuda yok")
        if manager.any_busy():
            raise HTTPException(409, "görev sürerken model değiştirilemez")
        try:
            return ctl.switch(body.model, body.api)
        except ModelSwitchError as e:
            raise HTTPException(e.status, e.message) from None

    # --- bağlı API'ler (anahtarlar geri verilmez) --------------------------------------------
    def api_rows() -> list[dict]:
        ctl = manager.model_control
        rows = (
            [
                {
                    "name": "varsayılan",
                    "endpoint": ctl.default.endpoint if ctl else "",
                    "has_key": bool(ctl and ctl.default.key),
                    "builtin": True,
                }
            ]
            if ctl
            else []
        )
        try:
            stored = apis.load(home)
        except apis.ApiError as e:
            raise HTTPException(500, str(e)) from None
        rows += [
            {"name": a.name, "endpoint": a.endpoint, "has_key": bool(a.key), "builtin": False}
            for a in stored.values()
        ]
        return rows

    @api.get("/apis")
    def list_apis() -> list[dict]:
        return api_rows()

    @api.post("/apis", status_code=201)
    def add_api(body: ApiIn) -> dict:
        try:
            a = apis.add(home, body.name, body.endpoint, body.key)
        except apis.ApiError as e:
            raise HTTPException(409 if "zaten" in str(e) else 400, str(e)) from None
        return {"name": a.name}

    @api.post("/local/scan")
    def local_scan(body: LocalScanIn) -> list[dict]:
        try:
            return localmodels.scan(body.port)
        except localmodels.LocalError as e:
            raise HTTPException(400, str(e)) from None

    @api.post("/local/context")
    def local_context(body: LocalCtxIn) -> dict:
        try:
            return {"model": localmodels.context_variant(body.port, body.model, body.num_ctx)}
        except localmodels.LocalError as e:
            raise HTTPException(502 if "oluşturulamadı" in str(e) else 400, str(e)) from None

    @api.put("/apis/{name}/key")
    def set_api_key(name: ServerName, body: KeyIn) -> dict:
        try:
            apis.set_key(home, name, body.key)
        except apis.ApiError as e:
            raise HTTPException(404 if "yok" in str(e) else 400, str(e)) from None
        return {"has_key": bool(body.key)}

    @api.delete("/apis/{name}")
    def delete_api(name: ServerName) -> dict:
        ctl = manager.model_control
        if ctl is not None and ctl.api == name:
            raise HTTPException(409, "kullanılan API silinemez; önce başka bir model seç")
        try:
            apis.remove(home, name)
        except apis.ApiError as e:
            raise HTTPException(404, str(e)) from None
        return {"removed": name}

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
        with path.open() as f:
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

    if login is not None:  # terminalin açtığı portal: tek kullanımlık kodu jetonla takas eder

        @app.post("/auth/exchange")
        def exchange(body: CodeIn) -> dict:
            if not login.redeem(body.code):
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
