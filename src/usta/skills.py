"""Beceriler: `~/.usta/skills/<ad>.md`. `/ad metin` yazınca beceri metni + metin istem olur.

Dosyalar kullanıcının kendi ev dizinindedir (çalışma alanı dışı); ajan yazamaz. İlk satır açıklamadır.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from usta import compat, memory

NAME = re.compile(r"[a-z0-9çğıöşü][a-z0-9çğıöşü_-]{0,29}")
MAX_SIZE = 20_000
MAX_PROPOSAL = 4_000  # Usta'nın önerdiği beceri: kullanıcı baştan sona okuyabilsin
MAX_DESCRIPTION = 120


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
    fd = os.open(d / f"{name}.md", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
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


def _clean_lines(text: str) -> str:
    """Denetim/biçim (bidi, sıfır genişlik) karakterlerini atar; satır sonlarını korur, satırdaki boşlukları teke indirir."""
    kept = "".join(
        c if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf") else " " for c in text
    )
    lines = [
        " ".join(ln.split()) for ln in kept.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return "\n".join(lines).strip("\n")


def validate_proposal(name: object, description: object, instructions: object) -> dict:
    """Usta'nın önerdiği becerinin temizlenmiş hâli: {name, content}. Yazmaz; geçersizse SkillError.

    `content` ilk satırı açıklama olan beceri dosyasıdır (mevcut biçim).
    """
    if not all(isinstance(x, str) for x in (name, description, instructions)):
        raise SkillError("ad, açıklama ve yönerge metin olmalı")
    n = name.strip().casefold()
    if not NAME.fullmatch(n):
        raise SkillError("ad küçük harf/rakam/-/_ olmalı (en çok 30 karakter)")
    desc = " ".join(_clean_lines(description).split())
    if not desc:
        raise SkillError("açıklama boş olamaz")
    if len(desc) > MAX_DESCRIPTION:
        raise SkillError(f"açıklama en çok {MAX_DESCRIPTION} karakter olabilir")
    body = _clean_lines(instructions)
    if not body:
        raise SkillError("yönerge boş olamaz")
    content = f"{desc}\n\n{body}"
    if len(content) > MAX_PROPOSAL:
        raise SkillError(
            f"beceri en çok {MAX_PROPOSAL} karakter olabilir (kullanıcı hepsini okuyabilsin)"
        )
    return {"name": n, "content": content}


def check_proposal(home: Path, name: object, description: object, instructions: object) -> dict:
    """Öneri kartı için: temizlenmiş içerik + UYARILAR (riskli desenler, üzerine yazma). Yazmaz."""
    d = validate_proposal(name, description, instructions)
    warnings = [f"Metinde {why} var." for why in memory.suspicious_all(d["content"])]
    overwrites = read(home, d["name"]) is not None
    if overwrites:
        warnings.append(f"/{d['name']} adında bir beceri zaten var; kaydedersen üzerine yazılır.")
    return {**d, "warnings": warnings, "overwrites": overwrites, "risky": bool(warnings)}
