"""Eklemeli JSONL denetim kaydı; sır desenleri yazmadan önce maskelenir."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_SECRET = re.compile(
    # PEM: BEGIN..END (başlıklar, ':' ',' ve JSON'daki ters bölülü \\n dahil); END yoksa başlık + bitişik base64 bloğu
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[A-Za-z0-9+/=:,.\-\s\\]*?-----END [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9+/=\r\n\\]*)"
    r"|(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"  # JWT
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


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, event: str, **fields) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = mask_deep({"ts": time.time(), "event": event, **fields})
        line = mask(json.dumps(record, ensure_ascii=False))
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(line + "\n")
