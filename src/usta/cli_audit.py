"""Komut satırı: denetim kaydını göster ve zincirini doğrula (usta audit)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

from usta import audit

_SKIP = {"ts", "event", "prev"}


def add_parser(sub) -> None:
    au = sub.add_parser("audit", help="denetim kaydını göster ve zincirini doğrula")
    aus = au.add_subparsers(dest="audit_cmd", required=True)
    v = aus.add_parser("verify", help="kayıt zincirini doğrula; son hash'i dışarıda sakla")
    v.add_argument("logs", nargs="*", help="kayıt adı ya da dosya yolu (verilmezse hepsi)")
    v.add_argument("--anchor", help="daha önce saklanan son hash: zincirde hâlâ geçmeli")
    s = aus.add_parser("show", help="son kayıtları göster")
    s.add_argument("log", nargs="?", help="kayıt adı ya da dosya yolu (verilmezse en son değişen)")
    s.add_argument("-n", type=int, default=20, help="kaç satır")


def _resolve(home: Path, name: str) -> Path | None:
    for p in (Path(name), home / "audit" / f"{name}.jsonl"):
        if p.is_file():
            return p
    print(f"hata: denetim kaydı yok: {name}", file=sys.stderr)
    return None


def audit_cmd(args: argparse.Namespace, home: Path) -> int:
    if args.audit_cmd == "show":
        logs = sorted((home / "audit").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if args.log is None and not logs:
            print("hata: henüz denetim kaydı yok", file=sys.stderr)
            return 2
        path = _resolve(home, args.log) if args.log else logs[-1]
        if path is None:
            return 2
        with path.open(encoding="utf-8") as f:
            for line in deque(f, maxlen=max(1, args.n)):
                rec = json.loads(line)
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.get("ts", 0)))
                rest = {k: v for k, v in rec.items() if k not in _SKIP}
                print(f"{when}  {rec.get('event')}  {json.dumps(rest, ensure_ascii=False)[:300]}")
        return 0
    paths = [_resolve(home, n) for n in args.logs] or sorted((home / "audit").glob("*.jsonl"))
    if None in paths:
        return 2
    if args.anchor and len(paths) != 1:
        print("hata: --anchor tek bir kayıtla kullanılır", file=sys.stderr)
        return 2
    bad = False
    for path in paths:
        r = audit.verify(path, args.anchor)
        old = f", {r.legacy} eski zincirsiz satır" if r.legacy else ""
        if r.ok:
            print(f"tamam  {path.stem}: {r.records} kayıt{old}; son hash {r.last_hash}")
        else:
            bad = True
            where = f"satır {r.bad_line}: " if r.bad_line else ""
            print(f"BOZUK  {path.stem}: {where}{r.reason}")
    return 1 if bad else 0
