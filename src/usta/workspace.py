"""Çalışma alanı anlık görüntüsü: görev sonrası unified diff ve geri alma (git gerektirmez)."""

from __future__ import annotations

import difflib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {".git", ".usta", "__pycache__", "node_modules", ".venv"}


PROTECTED_NAMES = (".git", ".usta")


IGNORED_SCAN_DEPTH = 3  # node_modules/.venv içinde .git aranırken en çok bu kadar iner (dev ağaçlarda maliyet sınırı)


def find_protected(root: Path) -> set[str]:
    """Çalışma alanındaki `.git` (her derinlikte, dizin ya da dosya), kök dışındaki `.usta` ve çıplak depo
    (HEAD + objects/ + refs/ içeren klasör) girdileri.

    Bunlar anlık görüntüye girmez; ajan `run` ile yenisini oluşturup (hook/config) kullanıcı git çalıştırınca
    ana makinede kod çalıştırabilirdi. Görev başında kaydedilir; yenileri görev sonunda karantinaya alınır,
    var olanlar sandbox'ta salt okunur bağlanır. `node_modules`/`.venv` gibi dizinlerin içine yalnız sığ inilir.
    """
    root = Path(root)
    found: set[str] = set()

    def scan(d: Path, ignored_depth: int | None) -> None:
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        names = {e.name for e in entries}
        if {"HEAD", "objects", "refs"} <= names and d != root:
            found.add(d.relative_to(root).as_posix())  # çıplak depo
        for e in entries:
            low = e.name.casefold()
            if low == ".git" or (low == ".usta" and d != root):
                found.add((d / e.name).relative_to(root).as_posix())
                continue  # içine inme
            if not e.is_dir(follow_symlinks=False):
                continue
            if e.name in IGNORED_DIRS:
                scan(d / e.name, IGNORED_SCAN_DEPTH)
            elif ignored_depth is None:
                scan(d / e.name, None)
            elif ignored_depth > 1:
                scan(d / e.name, ignored_depth - 1)

    scan(root, None)
    return found


def remove_new_protected(root: Path, before: set[str], quarantine: Path | None = None) -> list[str]:
    """Görev başında olmayan korumalı girdileri çalışma alanından çıkarır (bağ izlemeden).

    `quarantine` verilirse silinmez, oraya taşınır (kullanıcının meşru `git clone`/taşıma işi kaybolmasın);
    yoksa silinir. Çıkarılanların listesi döner.
    """
    root = Path(root)
    real_root = Path(os.path.realpath(root))
    removed = []
    for rel in sorted(find_protected(root) - before):
        p = root / rel
        # Ara bileşenlerden biri bu arada sembolik bağa çevrildiyse (eşzamanlı yazan) dışarıdaki bir yere dokunma
        if Path(os.path.realpath(p.parent)) != real_root / Path(rel).parent:
            continue
        try:
            if quarantine is not None:
                dest = Path(quarantine) / rel.replace("/", "__")
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if dest.exists() or dest.is_symlink():
                    dest = dest.with_name(f"{dest.name}.{os.getpid()}")
                shutil.move(str(p), dest)
            elif p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            removed.append(rel)
        except OSError:
            continue
    return removed


@dataclass
class Snapshot:
    files: dict[str, bytes] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    dirs: set[str] = field(default_factory=set)
    max_file: int = 1_000_000
    truncated: bool = False  # toplam sınır aşıldı: kalan dosyalar geri alma/diff kapsamı dışında
    protected: set[str] = field(default_factory=set)  # görev başındaki .git/.usta girdileri
    modes: dict[str, int] = field(default_factory=dict)  # dosya izinleri (geri alma bunları korur)


def _walk(root: Path):
    for dirpath, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for n in sorted(names):
            p = Path(dirpath) / n
            try:
                regular = stat.S_ISREG(p.lstat().st_mode)  # sembolik bağ, FIFO, aygıt: atlanır
            except OSError:
                continue
            if regular:
                yield p, p.relative_to(root).as_posix()


MAX_TOTAL_BYTES = 200_000_000
MAX_FILES = 20_000


def snapshot(
    root: Path,
    max_file: int = 1_000_000,
    max_total: int = MAX_TOTAL_BYTES,
    max_files: int = MAX_FILES,
) -> Snapshot:
    """Dosyaları belleğe alır; büyük klasörlerde (ör. Masaüstü) toplam sınırı aşan dosyalar atlanır.

    Atlananlar `skipped` listesindedir: diff'e girmez ve geri alma onlara dokunmaz (silinmez).
    """
    snap = Snapshot(max_file=max_file)
    snap.protected = find_protected(Path(root))
    total = 0
    for dirpath, dirs, _ in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        snap.dirs.update((Path(dirpath) / d).relative_to(root).as_posix() for d in dirs)
    for p, rel in _walk(Path(root)):
        size = p.stat().st_size
        if size > max_file:
            snap.skipped.append(rel)
        elif total + size > max_total or len(snap.files) >= max_files:
            snap.skipped.append(rel)
            snap.truncated = True
        else:
            snap.files[rel] = p.read_bytes()
            snap.modes[rel] = p.lstat().st_mode & 0o7777
            total += size
    return snap


def _lines(b: bytes) -> list[str] | None:
    if b"\x00" in b:
        return None
    try:
        return b.decode().splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def _current(root: Path, snap: Snapshot) -> dict[str, bytes]:
    cur = {}
    skipped = set(snap.skipped)
    for p, rel in _walk(root):
        if rel in skipped or p.stat().st_size > snap.max_file:
            continue
        cur[rel] = p.read_bytes()
    return cur


def diff(snap: Snapshot, root: Path) -> str:
    cur = _current(Path(root), snap)
    out: list[str] = []
    for rel in sorted(set(snap.files) | set(cur)):
        old, new = snap.files.get(rel), cur.get(rel)
        if old == new:
            continue
        a_name = f"a/{rel}" if old is not None else "/dev/null"
        b_name = f"b/{rel}" if new is not None else "/dev/null"
        a, b = _lines(old or b""), _lines(new or b"")
        if a is None or b is None:
            out.append(f"Binary files {a_name} and {b_name} differ\n")
            continue
        chunk = list(difflib.unified_diff(a, b, a_name, b_name))
        out.append(
            "".join(
                line if line.endswith("\n") else line + "\n\\ Dosya sonu satırı yok\n"
                for line in chunk
            )
        )
    return "".join(out)


def _safe_write(root: Path, rel: str, data: bytes, mode: int | None = None) -> None:
    """Dosyayı çalışma alanı içinde, sembolik bağ izlemeden yazar.

    Görev sırasında bir klasör ya da dosya, çalışma alanı dışına işaret eden bir sembolik bağla
    değiştirilmiş olabilir; geri alma o bağın hedefine ASLA yazmaz: bağın kendisi silinir ve yerine
    gerçek klasör/dosya konur (anlık görüntüdeki dosya, o an gerçek klasörlerin içindeydi).
    """
    parts = Path(rel).parts
    cur = root
    for part in parts[:-1]:
        cur = cur / part
        if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
            cur.unlink()
        cur.mkdir(exist_ok=True)
    leaf = cur / parts[-1]
    if leaf.is_dir() and not leaf.is_symlink():
        shutil.rmtree(leaf)  # anlık görüntüde dosyaydı; içindeki bağlar izlenmez
    # Geçici dosya + os.replace: yaprak FIFO/aygıt/sembolik bağ/sabit bağ olsa bile açılmaz, hedefi ezmez;
    # yalnız dizin girdisinin kendisi değişir (FIFO'da bloklanma ve sabit bağlı kardeş dosyayı ezme yok).
    fd, tmp_name = tempfile.mkstemp(dir=cur, prefix=".usta-")  # rastgele, kısa ad; 0600; O_EXCL
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            os.fchmod(f.fileno(), (mode if mode is not None else 0o644) & 0o7777)  # izinleri koru
        os.replace(tmp, leaf)
    finally:
        tmp.unlink(missing_ok=True)


def revert(snap: Snapshot, root: Path) -> None:
    root = Path(root)
    cur = _current(root, snap)
    for rel in cur.keys() - snap.files.keys():
        (root / rel).unlink()
    for rel, data in snap.files.items():
        if cur.get(rel) != data:
            _safe_write(root, rel, data, snap.modes.get(rel))
    # görev sırasında oluşan dizinleri (içten dışa) temizle; önceden var olanlara dokunma
    for dirpath, dirs, _ in os.walk(root, topdown=False):
        d = Path(dirpath)
        if IGNORED_DIRS & set(d.relative_to(root).parts):
            continue
        rel = d.relative_to(root).as_posix()
        if d != root and rel not in snap.dirs and not any(d.iterdir()):
            d.rmdir()
