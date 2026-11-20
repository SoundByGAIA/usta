"""Tek görevin durumu: olay günlüğü, gelen mesajlar, onay bekleyenler, dizi (seri) görev bilgisi ve görevin hataları."""

from __future__ import annotations

import itertools
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from usta.sessions import SessionStore
from usta.workspace import Snapshot

_SEQ = itertools.count()

CHECKBOX = re.compile(r"^[ \t]*[-*][ \t]*\[( |x|X)\][ \t]*(.*)$", re.MULTILINE)  # \s değil: ReDoS


MAX_PHASES = 40


@dataclass
class Series:
    """Aşamalı uygulama: her aşama taze bağlamlı ayrı görev; sıra PLAN.md'deki `- [ ]` satırlarıyla izlenir."""

    max_phases: int = MAX_PHASES
    phase: int = 0  # biten görev sayısı (kurulum dahil)
    last_unchecked: int | None = None
    stalls: int = 0
    active: bool = True


def plan_checklist(root: Path) -> tuple[int, list[str]] | None:
    """PLAN.md'deki (işaretli sayısı, işaretsiz madde başlıkları); dosya yoksa None."""
    p = Path(root) / "PLAN.md"
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 400_000:
            return None
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    done, todo = 0, []
    for m in CHECKBOX.finditer(text):
        if m.group(1) == " ":
            todo.append(m.group(2).strip())
        else:
            done += 1
    return done, todo


class RevertRefused(Exception):
    """Geri alma yapılamaz (daha yeni bir görev var ya da anlık görüntü artık tutulmuyor)."""


class PlanNotFound(Exception):
    """Uygulanacak plan yok: görev yok, plan modunda değil ya da başarıyla bitmemiş."""


class TaskFinished(Exception):
    """Biten göreve mesaj gönderilemez."""


class WorkspaceBusy(Exception):
    """Çalışma alanında zaten çalışan bir görev var."""


class _Approval:
    def __init__(self, tool: str, args: dict):
        self.tool, self.args = tool, args
        self.event = threading.Event()
        self.allow = False


class Task:
    def __init__(
        self,
        workspace_id: str,
        root: Path,
        prompt: str,
        context_window: int | None = None,
        mode: str = "manual",
        guard: bool = False,
        files: tuple[tuple[str, str], ...] = (),
    ):
        self.files = files
        self.model_prompt: str | None = (
            None  # modele giden metin; yoksa prompt (plan uygulamada farklıdır)
        )
        self.plan_of: str | None = None
        self.series: Series | None = None
        self.design_skill = (
            False  # kullanıcı "yeni bir iş öğret" dedi: propose_skill aracı bu görevde var
        )
        self.blocked = False
        self.terminal = ""  # yürütme aşamaları terminal durumu (phases.TERMINALS)
        self.diff_failed = False
        self.store: SessionStore | None = None
        self.mode = mode
        self.guard = guard
        self.id = uuid.uuid4().hex[:12]
        self.seq = next(_SEQ)  # saat aynı değeri verse de (Windows ~15 ms) görev sırası kesin
        self.usage: dict | None = None
        self.context_window = context_window
        self.workspace_id, self.root, self.prompt = workspace_id, root, prompt
        self.status = "running"
        self.answer = ""
        self.diff = ""
        self.events: list[dict] = []
        self.finished = threading.Event()
        self.cancel = threading.Event()
        self.snapshot: Snapshot | None = None
        self.approvals: dict[str, _Approval] = {}
        self._inbox: list[str] = []
        self._cond = threading.Condition()

    def emit(self, type_: str, data: dict | None = None) -> None:
        if type_ == "usage" and data:
            self.usage = dict(data)
        with self._cond:
            ev = {"i": len(self.events), "ts": time.time(), "type": type_, "data": data or {}}
            self.events.append(ev)
            self._cond.notify_all()
        if self.store is not None:
            self.store.append(self.workspace_id, self.id, ev)

    def post(self, text: str) -> None:
        with self._cond:
            if self.finished.is_set():
                raise TaskFinished(self.id)
            self._inbox.append(text)
        self.emit("user_message", {"text": text})

    def drain(self) -> list[str]:
        with self._cond:
            out, self._inbox = self._inbox, []
            return out

    def set_status(self, status: str) -> None:
        with self._cond:
            self.status = status

    def wait_events(self, start: int, timeout: float) -> tuple[list[dict], bool]:
        with self._cond:
            self._cond.wait_for(lambda: len(self.events) > start or self.finished.is_set(), timeout)
            return self.events[start:], self.finished.is_set()

    def public(self) -> dict:
        return {
            "id": self.id,
            "workspace": self.workspace_id,
            "prompt": self.prompt,
            "status": self.status,
            "answer": self.answer,
            "mode": self.mode,
            "guard": self.guard,
            "usage": self.usage,
            "context_window": self.context_window,
            "files": [n for n, _ in self.files],
            "plan_of": self.plan_of,
            "series": self.series is not None,
        }
