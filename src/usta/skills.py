"""Beceriler: `~/.usta/skills/<ad>.md`. `/ad metin` yazınca beceri metni + metin istem olur.

Dosyalar kullanıcının kendi ev dizinindedir (çalışma alanı dışı); ajan yazamaz. İlk satır açıklamadır.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

NAME = re.compile(r"[a-z0-9çğıöşü][a-z0-9çğıöşü_-]{0,29}")
MAX_SIZE = 20_000


class SkillError(Exception):
    pass


def _dir(home: Path) -> Path:
    return Path(home) / "skills"


def list_skills(home: Path) -> list[dict]:
    d = _dir(home)
    if not d.is_dir() or d.is_symlink():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        if p.is_symlink() or not NAME.fullmatch(p.stem):
            continue
        try:
            text = p.read_text(encoding="utf-8")[:MAX_SIZE]
        except (OSError, UnicodeDecodeError):
            continue
        first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), "")
        out.append({"name": p.stem, "description": first[:120], "size": len(text)})
    return out


def put(home: Path, name: str, content: str) -> None:
    if not NAME.fullmatch(name):
        raise SkillError("ad küçük harf/rakam/-/_ olmalı (en çok 30 karakter)")
    if not content.strip() or "\x00" in content or len(content.encode()) > MAX_SIZE:
        raise SkillError(f"içerik boş, ikili ya da {MAX_SIZE // 1000} KB'tan büyük")
    d = _dir(home)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(d / f"{name}.md", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def delete(home: Path, name: str) -> None:
    p = _dir(home) / f"{name}.md"
    if not NAME.fullmatch(name) or not p.is_file():
        raise SkillError("beceri yok")
    p.unlink()


def read(home: Path, name: str) -> str | None:
    p = _dir(home) / f"{name}.md"
    if not NAME.fullmatch(name) or p.is_symlink() or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")[:MAX_SIZE]
    except (OSError, UnicodeDecodeError):
        return None


def expand(home: Path, prompt: str) -> str:
    """`/ad ek metin` → beceri metni + ek metin. Beceri yoksa istem olduğu gibi döner."""
    m = re.match(r"^/(\S+)(?:\s+(.*))?$", prompt.strip(), re.DOTALL)
    if not m:
        return prompt
    body = read(home, m.group(1).casefold())
    if body is None:
        return prompt
    extra = (m.group(2) or "").strip()
    return f"{body.strip()}\n\nGörev: {extra}" if extra else body.strip()
