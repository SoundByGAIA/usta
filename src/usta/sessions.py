"""Kalıcı oturum geçmişi: her görevin olayları `~/.usta/sessions/<alan>/<görev>.jsonl` dosyasına yazılır.

Çalışma alanının dışında, kullanıcının ev dizininde tutulur (0600); portal ve terminal aynı kayıtları
okur. İlk satır üst bilgi, sonrakiler olaylardır. Yarıda kalan görev (sunucu kapandı) "kesildi" sayılır.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path

from usta.audit import mask

ID_RE = re.compile(r"^[a-f0-9]{12}$")
WS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_EVENTS = 5_000  # oturum başına
MAX_FIELD = 20_000  # tek alan değeri (uzun araç çıktıları kırpılır)
KEPT = 200  # çalışma alanı başına saklanan oturum


def _clip(v):
    if isinstance(v, str):
        v = mask(
            v
        )  # oturum kayıtlarına bilinen sır desenleri girmez (denetim günlüğüyle aynı maske)
        return (
            v
            if len(v) <= MAX_FIELD
            else v[:MAX_FIELD] + f"\n… [{len(v) - MAX_FIELD} karakter kırpıldı]"
        )
    if isinstance(v, dict):
        return {k: _clip(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clip(x) for x in v[:200]]
    return v


class SessionStore:
    def __init__(self, home: Path):
        self.base = Path(home) / "sessions"

    def _path(self, workspace: str, task_id: str) -> Path | None:
        if not WS_RE.fullmatch(workspace) or not ID_RE.fullmatch(task_id):
            return None
        return self.base / workspace / f"{task_id}.jsonl"

    def _append(self, path: Path, rec: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def begin(self, workspace: str, task_id: str, ts: float, meta: dict) -> None:
        path = self._path(workspace, task_id)
        if path is None:
            return
        with contextlib.suppress(OSError):
            self._append(path, {"meta": {"id": task_id, "ts": ts, **_clip(meta)}, "n": 0})
            self._prune(path.parent)

    def append(self, workspace: str, task_id: str, event: dict) -> None:
        path = self._path(workspace, task_id)
        if path is None or event["i"] >= MAX_EVENTS:
            return
        with contextlib.suppress(OSError):
            self._append(path, {"e": _clip(event)})

    def _prune(self, d: Path) -> None:
        files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        for p in files[: max(0, len(files) - KEPT)]:
            with contextlib.suppress(OSError):
                p.unlink()

    def load(self, workspace: str, task_id: str) -> dict | None:
        path = self._path(workspace, task_id)
        if path is None or not path.is_file():
            return None
        meta: dict = {}
        events: list[dict] = []
        try:
            with path.open(encoding="utf-8") as f:
                for ln in f:
                    try:
                        rec = json.loads(ln)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and "meta" in rec:
                        meta = rec["meta"]
                    elif isinstance(rec, dict) and isinstance(rec.get("e"), dict):
                        events.append(rec["e"])
        except OSError:
            return None
        done = next((e for e in reversed(events) if e.get("type") == "done"), None)
        status = (done or {}).get("data", {}).get("status", "interrupted")
        return {"meta": meta, "status": status, "events": events}

    def list(self, workspace: str, limit: int = 50) -> list[dict]:
        d = self.base / workspace
        if not WS_RE.fullmatch(workspace) or not d.is_dir():
            return []
        files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        out = []
        for p in files:
            s = self.load(workspace, p.stem)
            if s and s["meta"]:
                m = s["meta"]
                out.append(
                    {
                        "id": m.get("id", p.stem),
                        "ts": m.get("ts"),
                        "prompt": str(m.get("prompt", ""))[:300],
                        "mode": m.get("mode"),
                        "status": s["status"],
                        "events": len(s["events"]),
                    }
                )
        return out
