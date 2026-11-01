"""Devre kesici: ajan aynı hatayı ya da aynı yaklaşımı tekrarlıyorsa akışı keser.

Küçük modellerin tipik hastalığı: A'yı dener patlar, B'yi dener patlar, bağlam kaydığı için tekrar A'yı
dener. Burada zekâ modelden alınıp deterministik kurallara bırakılır:

- aynı hata imzası, arada bir düzenleme denendikten sonra yeniden görülürse (düzeltme çözmedi),
- bir dosya daha önce görülmüş bir içeriğe geri dönerse (A→B→A salınımı),
- aynı araç çağrısı aynı sonuçla art arda 3 kez gelirse

devre açılır: çalışma alanı son güvenli duruma (başlangıç ya da son doğrulanmış kontrol noktası) geri
sarılır ve modele "denenenler" listesi verilir. `max_trips` aşılırsa akış durur ve konu kullanıcıya bırakılır.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from usta.verify import failure_signature
from usta.workspace import Snapshot, revert, snapshot

EDIT_TOOLS = ("write_file", "edit_file")
MAX_TRIED = 8


@dataclass(frozen=True)
class Trip:
    reason: str
    tried: list[str]
    final: bool = False


def _h(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:10]


class CircuitBreaker:
    def __init__(self, root: Path, *, max_trips: int = 2, identical_calls: int = 3):
        self.root, self.max_trips, self.identical_calls = Path(root), max_trips, identical_calls
        self._snap: Snapshot | None = None
        self.trips = 0
        self._reset_state()

    def _reset_state(self) -> None:
        self._seen: dict[str, set[str]] = {}  # dosya → görülen içerik parmak izleri
        self._latest: dict[str, str] = {}
        self._fail_edits: dict[
            str, int
        ] = {}  # hata imzası → o imza görüldüğünde toplam düzenleme sayısı
        self._edits = 0
        self._tried: list[str] = []
        self._last_call: tuple[str, str] | None = None
        self._repeat = 0

    def start(self) -> None:
        self._snap = snapshot(self.root)
        self.trips = 0
        self._reset_state()

    def checkpoint(self) -> None:
        """Doğrulanmış iyi durum: devre açılırsa buraya dönülür; hata hafızası temizlenir."""
        self._snap = snapshot(self.root)
        self._fail_edits.clear()

    def rewind(self) -> None:
        if self._snap is not None:
            revert(self._snap, self.root)
        self._seen.clear()
        self._latest.clear()
        self._fail_edits.clear()
        self._edits = 0
        self._last_call, self._repeat = None, 0

    def _trip(self, reason: str) -> Trip:
        self.trips += 1
        return Trip(reason, self._tried[-MAX_TRIED:], final=self.trips > self.max_trips)

    def observe(self, tool: str, args: dict, result: str) -> Trip | None:
        call = (tool, _h(json.dumps(args, sort_keys=True, default=str)))
        self._repeat = self._repeat + 1 if self._last_call == (*call, _h(result)) else 1
        self._last_call = (*call, _h(result))  # type: ignore[assignment]
        if self._repeat >= self.identical_calls:
            self._tried.append(f"{tool} aynı sonuçla {self._repeat} kez")
            return self._trip(f"aynı çağrı aynı sonuçla {self._repeat} kez tekrarlandı")
        if tool in EDIT_TOOLS and isinstance(args.get("path"), str):
            return self._on_edit(tool, args)
        if tool == "run":
            return self._on_run(args, result)
        return None

    def _on_edit(self, tool: str, args: dict) -> Trip | None:
        path = args["path"]
        try:
            text = (self.root / path).read_text(errors="replace")
        except OSError:
            text = str(args.get("content") or args.get("new") or "")
        fp = _h(text)
        self._edits += 1
        self._tried.append(f"{tool} {path} (#{fp})")
        seen = self._seen.setdefault(path, set())
        revisit = fp in seen and self._latest.get(path) != fp
        seen.add(fp)
        self._latest[path] = fp
        if revisit:
            return self._trip(f"{path} daha önce denenmiş bir içeriğe geri döndü")
        return None

    def _on_run(self, args: dict, result: str) -> Trip | None:
        cmd = str(args.get("command", ""))[:80]
        body = result.split("\n", 1)
        code_line = body[0]
        if code_line.startswith("exit_code: 0"):
            self._fail_edits.clear()
            self._tried.append(f"run: {cmd} → geçti")
            return None
        sig = failure_signature(body[1] if len(body) > 1 else result)
        first = next(
            (
                ln.strip()
                for ln in reversed((body[1] if len(body) > 1 else "").splitlines())
                if ln.strip()
            ),
            code_line,
        )
        self._tried.append(f"run: {cmd} → hata: {first[:100]}")
        prev = self._fail_edits.get(sig)
        self._fail_edits[sig] = self._edits
        if prev is not None and self._edits > prev:  # arada düzeltme denendi ama aynı hata sürüyor
            return self._trip("aynı hata, bir düzeltme denemesinden sonra yeniden görüldü")
        return None
