"""Projeye özel doğrulama ayarları: `~/.usta/projects.json` (çalışma alanının DIŞINDA).

Kullanıcı doğrulama komutunu (ör. `pytest -q`, `make test`) ve isteğe bağlı sandbox imajını burada verir.
Dosya çalışma alanında olmadığı için ajan testi gevşetemez; komut kabuksuz çalışır (kabuk gerekiyorsa
`["sh", "-c", "..."]` yazılır).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from usta import compat

IMAGE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/:@-]{0,199}")
MAX_ARG = 4096


class ProjectConfigError(Exception):
    pass


@dataclass(frozen=True)
class ProjectConfig:
    verify: tuple[str, ...] | None = None
    image: str | None = None


def _key(root: Path) -> str:
    return str(Path(root).resolve())


def _read(home: Path) -> dict:
    path = Path(home) / "projects.json"
    try:
        data = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_command(cmd: object) -> bool:
    return (
        isinstance(cmd, (list, tuple))
        and bool(cmd)
        and all(isinstance(c, str) and c and "\x00" not in c and len(c) <= MAX_ARG for c in cmd)
    )


def load(home: Path, root: Path) -> ProjectConfig:
    raw = _read(home).get(_key(root))
    if not isinstance(raw, dict):
        return ProjectConfig()
    verify = raw.get("verify")
    image = raw.get("image")
    return ProjectConfig(
        tuple(verify) if _valid_command(verify) else None,
        image if isinstance(image, str) and IMAGE.fullmatch(image) else None,
    )


def _write(home: Path, data: dict) -> None:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "projects.json"
    tmp = path.with_name("projects.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def set_verify(home: Path, root: Path, command: list[str], image: str | None = None) -> None:
    if not _valid_command(command):
        raise ProjectConfigError("doğrulama komutu boş olmayan metinlerden oluşan bir liste olmalı")
    if image is not None and not IMAGE.fullmatch(image):
        raise ProjectConfigError(f"geçersiz imaj adı: {image!r}")
    data = _read(home)
    entry: dict = {"verify": list(command)}
    if image:
        entry["image"] = image
    data[_key(root)] = entry
    _write(home, data)


def clear(home: Path, root: Path) -> None:
    data = _read(home)
    if data.pop(_key(root), None) is not None:
        _write(home, data)
