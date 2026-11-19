"""Çalışma alanındaki dosyaların HTTP uçları: ağaç, okuma, yazma, içe aktarma, dosya işlemleri."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import filetree
from usta.api_models import MAX_FILE, FileIn, FsOp, ImportIn, WorkspaceId
from usta.audit import AuditLog, file_hash
from usta.policy import PathEscapeError, resolve_path
from usta.tasks import TaskManager


def register(
    api: APIRouter,
    home: Path,
    manager: TaskManager,
    ws_root: Callable[[str], Path],
    idle_ws: Callable[[str], Path],
) -> None:
    """Dosya uçlarını `api` yönlendiricisine ekler; panelden yapılan değişiklikler denetim kaydına girer."""

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
            before = file_hash(full)
            try:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(data)
            except OSError:
                raise HTTPException(400, f"yazılamadı: {rel}") from None
            written.append(rel)
            with contextlib.suppress(OSError):
                AuditLog(home / "audit" / f"{workspace}.jsonl").record(
                    "file_change",
                    path=rel,
                    before=before,
                    after=file_hash(full),
                    trigger="kullanıcı",
                )
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
                "fs_op", op=body.op, path=body.path, to=body.to, trigger="kullanıcı"
            )
        return {"ok": True}

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
        before = file_hash(full)
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(body.content, encoding="utf-8")
        except OSError:
            raise HTTPException(400, "yazılamadı") from None
        with contextlib.suppress(OSError):
            AuditLog(home / "audit" / f"{workspace}.jsonl").record(
                "file_change", path=path, before=before, after=file_hash(full), trigger="kullanıcı"
            )
        return {"path": path, "bytes": len(body.content.encode())}
