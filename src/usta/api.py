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
import shutil
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
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
    compat,
    filetree,
    kisi,
    localmodels,
    mcp_runtime,
    mcpcatalog,
    mcpconfig,
    memory,
    ortak,
    privacy,
    skills,
    support,
)
from usta import settings as usta_settings
from usta.audit import AuditLog
from usta.auth import LoginCodes
from usta.mcp import McpClient, McpError
from usta.modelctl import ModelSwitchError
from usta.models import Message, ModelError
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
    "/glossary.js": ("glossary.js", "text/javascript; charset=utf-8"),
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
    design_skill: bool = (
        False  # "Usta'ya yeni bir iş öğret": propose_skill aracı bu görevde verilir
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


class SkillProposalIn(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    instructions: str = Field(max_length=20_000)


class ProfileIn(BaseModel):
    ad: str = Field(default="", max_length=200)
    uslup: str = "sade"
    hakkimda: str = Field(default="", max_length=2000)
    bilgiler: list[str] = Field(default_factory=list, max_length=100)


class OrtakHostIn(BaseModel):
    acik: bool
    ad: str | None = Field(default=None, max_length=40)


class OrtakConnectIn(BaseModel):
    adres: str = Field(min_length=1, max_length=200)
    kod: str = Field(min_length=1, max_length=20)
    ad: str = Field(default="", max_length=40)


class OrtakNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SettingsIn(BaseModel):
    """Portaldan yalnız görünüm ve mod değiştirilebilir; uç nokta/model/sırlar buradan değişmez."""

    theme: Literal["beyaz", "gri", "siyah"] | None = None
    mode: Literal["manual", "auto", "plan"] | None = None
    guard: bool | None = None
    zoom: Literal["auto", "0.9", "1", "1.1", "1.25", "1.5", "1.75"] | None = None
    accent: Literal["cini", "turkuaz", "nar", "zeytin", "mor"] | None = None
    think: Literal["auto", "off", "low", "medium", "high"] | None = None
    view: Literal["simple", "advanced"] | None = None
    context_window: int | None = Field(default=None, ge=0, le=2_000_000)  # 0: otomatik (sınır yok)


def friendly_model_error(text: str) -> str:
    """Model hatasını kodsuz bir kullanıcıya anlaşılır cümleye çevirir (web/logic.js ile aynı cümleler)."""
    if "HTTP 401" in text or "HTTP 403" in text:
        return (
            "Anahtar kabul edilmedi. Doğru kopyaladığından ve hesabında bakiye olduğundan emin ol."
        )
    if "HTTP 402" in text:
        return "Hesabında bakiye yok görünüyor. Servisin sayfasından bakiye yükle ya da ücretsiz bir model seç."
    if "HTTP 404" in text:
        return "Bu model bulunamadı. Kurulum ekranından başka bir model seç."
    if "HTTP 429" in text:
        return (
            "Bugünkü ücretsiz hakkın doldu ya da çok hızlı istek gönderildi. "
            "Biraz bekle, yarın tekrar dene ya da başka bir servis ekle."
        )
    if re.search(r"HTTP 4\d\d", text):
        return (
            "Model bu isteği kabul etmedi. Konuşma çok uzamış olabilir: "
            "yeni bir görev başlat ya da başka bir model seç."
        )
    if re.search(r"HTTP 5\d\d", text):
        return (
            "Servis şu an cevap veremiyor. Sorun sende değil: "
            "birkaç dakika sonra tekrar dene ya da başka bir model seç."
        )
    if "ConnectError" in text or "ConnectTimeout" in text:
        return (
            "Servise ulaşılamıyor. İnternet bağlantını "
            "(ya da bilgisayarındaki modelin açık olduğunu) kontrol et."
        )
    if "Timeout" in text:
        return "Model zamanında cevap vermedi. Büyük modeller yavaş olabilir; tekrar dene."
    if re.search(r"ReadError|WriteError|RemoteProtocolError|NetworkError", text):
        return "Bağlantı yarıda koptu. İnternet bağlantını kontrol et ve tekrar dene."
    if "protokolü bozdu" in text or "araç çağrısı çözümlenemedi" in text:
        return (
            "Model ne yapacağını düzgün anlatamadı. Küçük modellerde olur: "
            "tekrar dene ya da daha güçlü bir model seç."
        )
    if re.search(r"JSONDecodeError|KeyError|IndexError|ValueError", text):
        return (
            "Servis anlaşılmayan bir cevap gönderdi. Tekrar dene; yine olursa başka bir model seç."
        )
    if "beklenmeyen hata" in text:
        return "Usta'da beklenmeyen bir şey oldu. Tekrar dene; yine olursa Ayarlar'daki \"Yardım iste\" düğmesine bas."
    return "Model cevap vermedi. Ayrıntı: " + text


class LocalScanIn(BaseModel):
    port: int | None = Field(default=None, ge=1, le=65535)


class LocalHostIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)


class SystemInstallIn(BaseModel):
    what: str = Field(min_length=1, max_length=20)


class LocalPullIn(BaseModel):
    port: int = Field(default=11434, ge=1, le=65535)
    model: str = Field(min_length=1, max_length=120)


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

    @api.post("/skills/check")
    def check_skill_proposal(body: SkillProposalIn) -> dict:
        """Usta'nın önerdiği becerinin temizlenmiş hâli ve uyarıları (öneri kartı bunu gösterir). Hiçbir şey yazmaz."""
        try:
            return skills.check_proposal(home, body.name, body.description, body.instructions)
        except skills.SkillError as e:
            raise HTTPException(422, str(e)) from None

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
            full.write_text(body.content, encoding="utf-8")
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

    @api.get("/profile")
    def get_profile() -> dict:
        """Kullanıcının kendi yazdığı tanışma bilgileri (modelin yazabildiği bir yol yoktur)."""
        return asdict(kisi.load(home))

    @api.put("/profile")
    def put_profile(body: ProfileIn) -> dict:
        if ortak.load_link(home) is not None:
            raise HTTPException(
                409,
                "Bu bilgisayar evdeki ortak hafızaya bağlı. Bilgiler ev sahibi bilgisayardan değiştirilir.",
            )
        try:
            k = kisi.check(body.model_dump())
            kisi.save(home, k)
        except kisi.KisiError as e:
            raise HTTPException(422, str(e)) from None
        except OSError:
            raise HTTPException(500, "profil kaydedilemedi") from None
        return asdict(k)

    @api.delete("/profile")
    def delete_profile() -> dict:
        if ortak.load_link(home) is not None:
            raise HTTPException(
                409,
                "Bu bilgisayar evdeki ortak hafızaya bağlı. Bilgiler ev sahibi bilgisayardan değiştirilir.",
            )
        try:
            kisi.delete(home)
        except OSError:
            raise HTTPException(500, "profil silinemedi") from None
        return asdict(kisi.Kisi())

    # --- evdeki ortak hafıza (tasarım: docs/ortak-hafiza-tasarim.md) ---------------------------
    ohost = ortak.HostServer(home)

    def ortak_role() -> str:
        if ortak.load_link(home) is not None:
            return "bagli"
        return "ev-sahibi" if ortak.Store(home).enabled else "yok"

    def ortak_host_only() -> ortak.Store:
        store = ortak.Store(home)
        if ortak_role() != "ev-sahibi":
            raise HTTPException(409, "Bunu yalnız ev sahibi bilgisayar yapabilir.")
        return store

    @api.get("/ortak")
    def ortak_status() -> dict:
        role = ortak_role()
        store = ortak.Store(home)
        out: dict = {"rol": role, "bilgisayar": ortak.pc_name()}
        if role == "ev-sahibi":
            out.update(
                ad=store.name,
                adres=ohost.address,
                calisiyor=ohost.running,
                eslesmeler=store.peers_public(),
                notlar=store.approved(),
                bekleyen=store.pending(),
            )
        elif role == "bagli":
            link = ortak.load_link(home) or {}
            out["baglanti"] = {"ad": link.get("ad"), "adres": link.get("adres")}
            try:
                data = ortak.fetch(home)
                out.update(ulasilamiyor=False, profil=data["profil"], notlar=data["notlar"])
            except ortak.OrtakError as e:
                data = ortak.cached(home) or {"profil": asdict(kisi.Kisi()), "notlar": []}
                out.update(
                    ulasilamiyor=True, hata=str(e), profil=data["profil"], notlar=data["notlar"]
                )
        return out

    @api.post("/ortak/ev-sahibi")
    def ortak_set_host(body: OrtakHostIn) -> dict:
        store = ortak.Store(home)
        if body.acik:
            if ortak.load_link(home) is not None:
                raise HTTPException(
                    409, "Bu bilgisayar başka bir ortak hafızaya bağlı. Önce bağlantıyı kes."
                )
            store.configure(True, body.ad)
            try:
                ohost.start()
            except ortak.OrtakError as e:
                store.configure(False)
                raise HTTPException(409, str(e)) from None
        else:
            store.configure(False)
            ohost.stop()
        return ortak_status()

    @api.post("/ortak/kod")
    def ortak_code() -> dict:
        ortak_host_only()
        if not ohost.running:
            try:
                ohost.start()
            except ortak.OrtakError as e:
                raise HTTPException(409, str(e)) from None
        return {"kod": ohost.codes.issue(), "adres": ohost.address, "sure": 300}

    @api.post("/ortak/baglan")
    def ortak_join(body: OrtakConnectIn) -> dict:
        if ortak.Store(home).enabled:
            raise HTTPException(
                409, "Bu bilgisayar ortak hafızayı kendisi tutuyor. Önce onu kapat."
            )
        try:
            res = ortak.connect(home, body.adres, body.kod, body.ad or ortak.pc_name())
        except ortak.OrtakError as e:
            raise HTTPException(400, str(e)) from None
        return {"ad": res["ad"], "adres": res["adres"]}

    @api.post("/ortak/ayril")
    def ortak_leave() -> dict:
        ortak.disconnect(home)
        return {"rol": ortak_role()}

    @api.delete("/ortak/eslesmeler/{key_id}")
    def ortak_unpair(key_id: str) -> dict:
        store = ortak_host_only()
        try:
            store.remove_peer(key_id)
        except KeyError:
            raise HTTPException(404, "böyle bir bilgisayar yok") from None
        return {"eslesmeler": store.peers_public()}

    @api.post("/ortak/notlar")
    def ortak_add_note(body: OrtakNoteIn) -> dict:
        role = ortak_role()
        try:
            if role == "bagli":
                res = ortak.post_note(home, body.text)
                return {"durum": res.get("durum", "bekliyor")}
            if role == "ev-sahibi":
                note = ortak.Store(home).add(body.text, ortak.Store(home).name, approved=True)
                return {"durum": note["durum"]}
        except ortak.OrtakError as e:
            raise HTTPException(422, str(e)) from None
        raise HTTPException(
            409, "Ortak hafıza kapalı. Önce ev sahibi ol ya da bir ev sahibine bağlan."
        )

    @api.post("/ortak/notlar/{note_id}/onayla")
    def ortak_approve(note_id: str) -> dict:
        try:
            ortak_host_only().approve(note_id)
        except KeyError:
            raise HTTPException(404, "böyle bir not yok") from None
        return {"tamam": True}

    @api.delete("/ortak/notlar/{note_id}")
    def ortak_delete(note_id: str) -> dict:
        try:
            ortak_host_only().delete(note_id)
        except KeyError:
            raise HTTPException(404, "böyle bir not yok") from None
        return {"tamam": True}

    @api.get("/settings")
    def get_settings() -> dict:
        cur = usta_settings.load(home)
        return {
            "theme": cur.theme,
            "mode": cur.mode,
            "guard": cur.guard,
            "zoom": cur.zoom,
            "accent": cur.accent,
            "think": cur.think,
            "view": cur.view,
            "context_window": cur.context_window or 0,
            "background": on_quit is not None,
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
            "accent": new.accent,
            "think": new.think,
            "view": new.view,
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

    @api.post("/setup/ping")
    def setup_ping() -> dict:
        """Sihirbazın son denemesi: seçili modele tek kısa istek atar, anlaşılır bir sonuç döner."""
        ctl = manager.model_control
        if ctl is None or not ctl.ready:
            raise HTTPException(409, "önce bir model seç")
        t0 = time.monotonic()
        try:
            r = ctl.current().chat([Message(role="user", content="Merhaba de, tek kelime yaz.")])
        except ModelError as e:
            return {"ok": False, "error": friendly_model_error(str(e))}
        return {
            "ok": True,
            "seconds": round(time.monotonic() - t0, 1),
            "reply": (r.content or "")[:200],
        }

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

    @api.post("/local/scan")
    def local_scan(body: LocalScanIn) -> list[dict]:
        try:
            return localmodels.scan(body.port)
        except localmodels.LocalError as e:
            raise HTTPException(400, str(e)) from None

    @api.post("/local/scan-lan")
    def local_scan_lan() -> list[dict]:
        """Evdeki ağda (bu bilgisayarın /24'ü) yaygın portlarda model sunucusu arar."""
        return localmodels.lan_scan()

    @api.post("/local/probe-host")
    def local_probe_host(body: LocalHostIn) -> dict:
        """Kullanıcının yazdığı evdeki adreste model sunucusu var mı (yalnız özel ağ adresleri)."""
        try:
            found = localmodels.probe_host(body.host)
        except localmodels.LocalError as e:
            raise HTTPException(400, str(e)) from None
        if not found:
            raise HTTPException(
                404,
                "Bu adreste yapay zekâ bulamadım. Öbür bilgisayar açık mı ve Ollama (ya da LM Studio) "
                "ağa açık mı? Adresi de kontrol et.",
            )
        return found

    @api.get("/system/info")
    def system_info() -> dict:
        """Yerel model sihirbazı için: bellek, Ollama durumu, kurulu modeller ve öneri."""
        ram = localmodels.memory_gb()
        ollama = localmodels.probe(11434, timeout=1.0)
        return {
            "os": sys.platform,
            "ram_gb": None if ram is None else round(ram, 1),
            "ollama_running": ollama is not None,
            "ollama_installed": ollama is not None or shutil.which("ollama") is not None,
            "docker_installed": shutil.which("docker") is not None,
            "can_install": {k: localmodels.can_install(k) for k in localmodels.INSTALLABLE},
            "installed": ollama["models"] if ollama else [],
            "recommend": localmodels.recommend(ram),
        }

    @api.post("/system/install", status_code=202)
    def system_install(body: SystemInstallIn) -> dict:
        """Eksik programı (şimdilik yalnız Ollama, yalnız Windows) kullanıcının düğmesiyle kurar."""
        try:
            localmodels.INSTALL.start(body.what)
        except localmodels.LocalError as e:
            raise HTTPException(409 if "sürüyor" in str(e) else 400, str(e)) from None
        return {"started": True}

    @api.get("/system/install")
    def system_install_progress() -> dict:
        return localmodels.INSTALL.snapshot()

    @api.post("/local/pull", status_code=202)
    def local_pull(body: LocalPullIn) -> dict:
        try:
            localmodels.PULL.start(body.port, body.model)
        except localmodels.LocalError as e:
            raise HTTPException(409 if "sürüyor" in str(e) else 400, str(e)) from None
        return {"started": True}

    @api.get("/local/pull")
    def local_pull_progress() -> dict:
        return localmodels.PULL.snapshot()

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
