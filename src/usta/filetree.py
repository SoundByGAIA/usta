"""Çalışma alanı dosya gezgini ve toplu içe aktarma için yardımcılar."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path

HIDDEN = frozenset(
    {
        ".git",
        ".usta",
        ".venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)
MAX_ENTRIES = 500
MAX_IMPORT_FILES = 500
MAX_IMPORT_FILE = 5_000_000
MAX_IMPORT_TOTAL = 20_000_000


class ImportError_(ValueError):
    pass


def list_dir(path: Path) -> list[dict]:
    out = []
    with os.scandir(path) as it:
        for e in it:
            if e.name in HIDDEN:
                continue
            link = e.is_symlink()
            is_dir = e.is_dir(follow_symlinks=False)
            try:
                size = 0 if is_dir else e.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
            out.append({"name": e.name, "dir": is_dir, "size": size, "link": link})
    out.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return out[:MAX_ENTRIES]


def decode_files(items: list[tuple[str, str]]) -> list[tuple[str, bytes]]:
    if len(items) > MAX_IMPORT_FILES:
        raise ImportError_(f"en çok {MAX_IMPORT_FILES} dosya yüklenebilir")
    out, total = [], 0
    for rel, b64 in items:
        parts = Path(rel).parts
        if not rel or rel.startswith("/") or ".." in parts or any(p in HIDDEN for p in parts):
            raise ImportError_(f"geçersiz yol: {rel!r}")
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise ImportError_(f"{rel}: içerik çözülemedi") from None
        if len(data) > MAX_IMPORT_FILE:
            raise ImportError_(f"{rel}: çok büyük (en çok {MAX_IMPORT_FILE // 1_000_000} MB)")
        total += len(data)
        if total > MAX_IMPORT_TOTAL:
            raise ImportError_(f"toplam en çok {MAX_IMPORT_TOTAL // 1_000_000} MB olabilir")
        out.append((rel, data))
    return out


class FsError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _locate(root: Path, rel: str) -> Path:
    """Yolun kendisini döndürür (son bileşen sembolik bağ ise izlenmez); üst klasör çalışma alanında kalmalı."""
    from usta.policy import PathEscapeError, resolve_path

    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\x00" in rel:
        raise FsError("geçersiz yol")
    parts = Path(rel).parts
    if not parts or ".." in parts or "." in parts or any(p in HIDDEN for p in parts):
        raise FsError("bu yola dokunulamaz")
    try:
        parent = resolve_path(root, str(Path(*parts[:-1])) if len(parts) > 1 else ".")
    except PathEscapeError:
        raise FsError("çalışma alanı dışı") from None
    return parent / parts[-1]


def create(root: Path, rel: str, *, is_dir: bool) -> None:
    target = _locate(root, rel)
    if target.exists() or target.is_symlink():
        raise FsError("bu ad zaten var", 409)
    try:
        if is_dir:
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=False)
    except OSError:
        raise FsError("oluşturulamadı") from None


def rename(root: Path, src: str, dst: str) -> None:
    a, b = _locate(root, src), _locate(root, dst)
    if not (a.exists() or a.is_symlink()):
        raise FsError("kaynak yok", 404)
    if b.exists() or b.is_symlink():
        raise FsError("hedef zaten var", 409)
    try:
        b.parent.mkdir(parents=True, exist_ok=True)
        a.rename(b)
    except OSError:
        raise FsError("yeniden adlandırılamadı") from None


def delete(root: Path, rel: str) -> None:
    import shutil

    target = _locate(root, rel)
    if target.is_symlink() or target.is_file():
        try:
            target.unlink()
        except OSError:
            raise FsError("silinemedi") from None
        return
    if not target.is_dir():
        raise FsError("yok", 404)
    try:
        shutil.rmtree(target)  # içindeki sembolik bağlar izlenmez, yalnız bağ silinir
    except OSError:
        raise FsError("silinemedi") from None
