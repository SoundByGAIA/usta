"""Eklemeli JSONL denetim kaydı; sır desenleri yazmadan önce maskelenir."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_SECRET = re.compile(
    # PEM: BEGIN..END (başlıklar, ':' ',' ve JSON'daki ters bölülü \\n dahil); END yoksa başlık + bitişik base64 bloğu
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[A-Za-z0-9+/=:,.\-\s\\]*?-----END [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9+/=\r\n\\]*)"
    r"|(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"  # JWT
    r"|nvapi-[A-Za-z0-9_-]{20,}"
    r"|[Bb]earer [A-Za-z0-9._~+/=-]{24,}",
    re.DOTALL,
)


def mask(text: str) -> str:
    return _SECRET.sub("[GİZLİ]", text)


def mask_deep(value):
    """Metinleri özyinelemeli maskeler (JSON'a çevirmeden önce: satır sonları gerçek karakter olarak görünür)."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {k: mask_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_deep(v) for v in value]
    return value


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path.resolve()), threading.Lock())


def _hash(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()


def file_hash(path: Path) -> str | None:
    """Dosya içeriğinin sha256'sı; dosya yoksa ya da okunamıyorsa None."""
    try:
        return _hash(Path(path).read_bytes())
    except OSError:
        return None


def _last_line(path: Path) -> bytes | None:
    """Dosyanın son satırı (satır sonu olmadan); kayıt satırı uzun olabileceği için geriye doğru okunur."""
    try:
        f = path.open("rb")
    except FileNotFoundError:
        return None
    with f:
        end = f.seek(0, os.SEEK_END)
        buf = b""
        pos = end
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
            body = buf.rstrip(b"\r\n")
            if b"\n" in body:
                return body.rsplit(b"\n", 1)[1]
        body = buf.rstrip(b"\r\n")
        return body or None


class AuditLog:
    """Her satır önceki satırın sha256'sını (`prev`) taşır: aradan satır silmek ya da değiştirmek `verify` ile görülür."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, event: str, **fields) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _lock(self.path):
            last = _last_line(self.path)
            prev = _hash(last) if last is not None else ""
            record = mask_deep({"ts": time.time(), "event": event, **fields, "prev": prev})
            line = mask(json.dumps(record, ensure_ascii=False)).encode("utf-8")
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line + b"\n")
            finally:
                os.close(fd)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int  # zincirli satır
    legacy: int  # zincirden önceki, `prev` taşımayan eski satır
    last_hash: str  # dışarıda saklanırsa sondan silme ve son satırın değişmesi de görülür
    bad_line: int | None = None
    reason: str = ""


def verify(path: Path, anchor: str | None = None) -> VerifyResult:
    """`anchor`: daha önce dışarıda saklanan son hash; sondan silinen satırları yalnız bu gösterir."""
    records = legacy = 0
    prev = ""
    seen = anchor is None
    with Path(path).open("rb") as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip(b"\r\n")
            try:
                rec = json.loads(line)
            except ValueError:
                return VerifyResult(False, records, legacy, prev, n, "satır JSON değil")
            if "prev" in rec:
                if rec["prev"] != prev:
                    return VerifyResult(
                        False, records, legacy, prev, n, "önceki satırın hash'i uymuyor"
                    )
                records += 1
            elif records:
                return VerifyResult(
                    False, records, legacy, prev, n, "zincir başladıktan sonra zincirsiz satır"
                )
            else:
                legacy += 1
            prev = _hash(line)
            seen = seen or prev == anchor
    if not seen:
        return VerifyResult(False, records, legacy, prev, None, "saklanan hash zincirde yok")
    return VerifyResult(True, records, legacy, prev)
