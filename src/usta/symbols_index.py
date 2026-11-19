"""Proje sembol indeksi: dosyaları tarar, sembol/çağrı/içe aktarma bilgisini toplar, sorguya göre dosya sıralar."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from usta.symbols import (
    MAX_FILE_BYTES,
    MAX_FILES,
    SKIP_DIRS,
    FileSymbols,
    Symbol,
    extract,
    language_for,
)

_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+")
STOP = frozenset({"the", "a", "an", "of", "to", "in", "for", "and", "or", "bir", "ve", "ile", "için", "bu", "şu", "hata", "hatası", "düzelt", "fix", "bug"})  # fmt: skip


def tokens(text: str) -> list[str]:
    """camelCase/snake_case/kebab ayrıştırır, küçük harfe çevirir, kısa/dolgu sözcükleri atar."""
    out = []
    for w in _WORD.findall(text.replace("_", " ")):
        for part in re.sub(r"(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", " ", w).split():
            p = part.lower()
            if len(p) >= 3 and p not in STOP:
                out.append(p)
    return out


@dataclass
class _Entry:
    stamp: tuple[int, int]
    data: FileSymbols | None  # None: desteklenmeyen/ayrıştırılamayan dosya (yalnız yol eşleşmesi)


class SymbolIndex:
    """Çalışma alanının sembol indeksi; her sorguda dosya durumuna göre kendini tazeler."""

    def __init__(self, root: Path, *, max_files: int = MAX_FILES):
        self.root = Path(root).resolve()
        self.max_files = max_files
        self._files: dict[str, _Entry] = {}
        self.parse_count = 0  # test/ölçüm: kaç dosya ayrıştırıldı

    # -- tazeleme --
    def _scan(self) -> dict[str, tuple[int, int]]:
        seen: dict[str, tuple[int, int]] = {}
        stack = [self.root]
        while stack and len(seen) < self.max_files:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in SKIP_DIRS:
                                stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            if st.st_size <= MAX_FILE_BYTES:
                                # Usta her yerde "/" kullanır; Windows'un "\\" yolu modelin verdiği yolla eşleşmez
                                seen[Path(os.path.relpath(e.path, self.root)).as_posix()] = (
                                    st.st_mtime_ns,
                                    st.st_size,
                                )
            except OSError:
                continue
        return seen

    def refresh(self) -> int:
        """Değişen/yeni dosyaları yeniden ayrıştırır, silinenleri düşürür; yeniden ayrıştırılan dosya sayısını döner."""
        seen = self._scan()
        for gone in set(self._files) - set(seen):
            del self._files[gone]
        changed = 0
        for rel, stamp in seen.items():
            cur = self._files.get(rel)
            if cur is not None and cur.stamp == stamp:
                continue
            data = None
            if language_for(rel):
                try:
                    data = extract(
                        rel, (self.root / rel).read_text(encoding="utf-8", errors="replace")
                    )
                except OSError:
                    data = None
                self.parse_count += 1
            self._files[rel] = _Entry(stamp, data)
            changed += 1
        return changed

    # -- sorgular --
    def symbols_of(self, rel: str) -> FileSymbols | None:
        self.refresh()
        e = self._files.get(rel)
        return e.data if e else None

    def definitions(self, name: str) -> list[tuple[str, Symbol]]:
        """Ada göre tanımlar: tam eşleşme (çıplak ya da nitelikli) önce, sonra büyük/küçük harf duyarsız, sonra içerir."""
        self.refresh()
        exact, loose, sub = [], [], []
        low = name.lower()
        for rel, e in sorted(self._files.items()):
            for s in e.data.symbols if e.data else ():
                if name in (s.name, s.qualname):
                    exact.append((rel, s))
                elif low in (s.name.lower(), s.qualname.lower()):
                    loose.append((rel, s))
                elif low in s.qualname.lower():
                    sub.append((rel, s))
        return exact or loose or sub

    def callers(self, name: str) -> list[tuple[str, str]]:
        self.refresh()
        out = []
        for rel, e in sorted(self._files.items()):
            for who, callees in e.data.calls.items() if e.data else ():
                if name in callees:
                    out.append((rel, who))
        return out

    def callees(self, rel: str, qualname: str) -> list[tuple[str, Symbol]]:
        """Bu sembolün çağırdığı, PROJEDE tanımlı sembollerin tanımları."""
        fs = self.symbols_of(rel)
        if fs is None:
            return []
        out, seen = [], set()
        for callee in sorted(fs.calls.get(qualname, ())):
            for drel, sym in self.definitions(callee)[:2]:
                if (drel, sym.qualname) not in seen and not (
                    drel == rel and sym.qualname == qualname
                ):
                    seen.add((drel, sym.qualname))
                    out.append((drel, sym))
        return out

    def rank_files(self, query: str, limit: int = 8) -> list[tuple[str, float, str]]:
        """Görev metnine göre dosya önceliği: sembol adı eşleşmesi > yol eşleşmesi > çağrı/içe aktarma eşleşmesi."""
        self.refresh()
        q = set(tokens(query))
        if not q:
            return []
        scored = []
        for rel, e in self._files.items():
            path_hits = q & set(tokens(rel))
            sym_hits: set[str] = set()
            ref_hits: set[str] = set()
            if e.data:
                for s in e.data.symbols:
                    sym_hits |= q & set(tokens(s.qualname))
                for callees in e.data.calls.values():
                    for c in callees:
                        ref_hits |= q & set(tokens(c))
                for imp in e.data.imports:
                    ref_hits |= q & set(tokens(imp))
            score = 3.0 * len(sym_hits) + 2.0 * len(path_hits) + 1.0 * len(ref_hits)
            if score:
                why = ", ".join(
                    p for p in (
                        f"sembol: {', '.join(sorted(sym_hits))}" if sym_hits else "",
                        f"yol: {', '.join(sorted(path_hits))}" if path_hits else "",
                        f"referans: {', '.join(sorted(ref_hits))}" if ref_hits else "",
                    ) if p
                )  # fmt: skip
                scored.append((rel, score, why))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:limit]

    def file_count(self) -> int:
        self.refresh()
        return len(self._files)
