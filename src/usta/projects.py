"""Terminalin çalışma dizinini portala görünür kılar: `~/.usta/workspaces/<kimlik>` → proje (sembolik bağ).

Böylece `usta`yı hangi dizinde açtıysan aynı proje portalda da listelenir. Gerçek bir dizinin üzerine
asla yazılmaz; çakışmada başka kimlik seçilir.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
MAX_BASE = 24  # + "-" + 4 hane = en çok 29 karakter (kimlik sınırı 40)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").translate(_TR).casefold()).strip("-_")
    return (s[:MAX_BASE].strip("-_")) or "proje"


def check_root(home: Path, path: Path) -> None:
    """Çalışma alanı olamayacak klasörler: kök, ev dizini ve Usta ev dizinini (jeton, API anahtarları,
    MCP yapılandırması) içeren her üst klasör. Ajan o klasörde bu dosyaları okuyup yazabilirdi."""
    p = Path(path).resolve()
    h = Path(home).resolve()
    try:
        home_dir = Path.home().resolve()
    except RuntimeError:  # ev dizini belirlenemiyor (nadir)
        home_dir = Path(p.anchor)
    if (
        p == Path(p.anchor)
        or p == home_dir
        or home_dir.is_relative_to(p)
        or h == p
        or h.is_relative_to(p)
    ):
        raise ValueError(
            f"{p} çalışma alanı olamaz: Usta ayarlarını ve sırlarını ({h}) kapsıyor. "
            "Bir proje klasörüne girip öyle başlat."
        )


def register(home: Path, path: Path) -> str:
    path = Path(path).resolve()
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    base = Path(home) / "workspaces"
    if path.parent == base.resolve():  # zaten çalışma alanları dizininin içinde
        return path.name
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    for attempt in range(20):
        digest = hashlib.sha1(f"{path}\0{attempt}".encode(), usedforsecurity=False).hexdigest()[:4]
        wid = f"{slug(path.name)}-{digest}"
        link = base / wid
        if link.is_symlink():
            if link.resolve() == path:
                return wid
            if link.exists():
                continue  # başka bir projeye işaret ediyor: başka kimlik dene
            link.unlink()  # kırık bağ
        elif link.exists():
            continue  # gerçek dizin: dokunma
        os.symlink(path, link, target_is_directory=True)
        return wid
    raise OSError("proje kimliği üretilemedi")
