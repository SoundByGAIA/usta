"""Terminal temaları (beyaz / gri / siyah) ve renkli diff. Yalnız ANSI SGR; bağımlılık yok.

Tema, terminalin ARKA PLANINA göre okunabilirlik içindir: `beyaz` açık zeminde koyu tonlar,
`siyah` koyu zeminde parlak tonlar, `gri` ikisinde de yumuşak orta tonlar kullanır.
"""

from __future__ import annotations

import os

ROLES = (
    "prompt", "user", "assistant", "tool", "result", "add", "del", "hunk", "meta", "warn",
    "error", "ok", "dim", "title",
)  # fmt: skip


def _c(n: int, bold: bool = False) -> str:
    return f"{'1;' if bold else ''}38;5;{n}"


THEMES: dict[str, dict[str, str]] = {
    # açık (beyaz) zemin: koyu, doygun tonlar
    "beyaz": {
        "prompt": _c(25, True), "user": _c(235), "assistant": "39;49", "tool": _c(94),
        "result": _c(243), "add": _c(28), "del": _c(160), "hunk": _c(25), "meta": _c(243),
        "warn": _c(130), "error": _c(124, True), "ok": _c(28), "dim": _c(245), "title": _c(235, True),
    },
    # orta tonlar: iki zeminde de yumuşak
    "gri": {
        "prompt": _c(103, True), "user": _c(250), "assistant": "39;49", "tool": _c(180),
        "result": _c(245), "add": _c(108), "del": _c(167), "hunk": _c(103), "meta": _c(245),
        "warn": _c(179), "error": _c(167, True), "ok": _c(108), "dim": _c(243), "title": _c(250, True),
    },
    # koyu (siyah) zemin: parlak tonlar
    "siyah": {
        "prompt": _c(75, True), "user": _c(255), "assistant": "39;49", "tool": _c(215),
        "result": _c(245), "add": _c(78), "del": _c(203), "hunk": _c(111), "meta": _c(245),
        "warn": _c(221), "error": _c(203, True), "ok": _c(78), "dim": _c(243), "title": _c(255, True),
    },
}  # fmt: skip
ALIASES = {
    "white": "beyaz",
    "light": "beyaz",
    "gray": "gri",
    "grey": "gri",
    "black": "siyah",
    "dark": "siyah",
}
RESET = "\x1b[0m"


def resolve(name: str) -> str:
    key = (name or "").strip().casefold()
    key = ALIASES.get(key, key)
    if key not in THEMES:
        raise ValueError(f"bilinmeyen tema: {name!r} (beyaz, gri, siyah)")
    return key


class Painter:
    def __init__(self, name: str = "siyah", color: bool = True):
        self.name, self.color = resolve(name), color
        self._p = THEMES[self.name]

    @classmethod
    def auto(cls, name: str, stream) -> Painter:
        tty = bool(getattr(stream, "isatty", lambda: False)())
        return cls(name, color=tty and not os.environ.get("NO_COLOR"))

    def __call__(self, role: str, text: str) -> str:
        if not self.color or not text:
            return text
        return f"\x1b[{self._p[role]}m{text}{RESET}"

    def diff(self, text: str) -> str:
        """Unified diff'i satır türüne göre boyar; renk kapalıysa metni aynen döndürür."""
        if not self.color:
            return text
        out = []
        for ln in text.splitlines():
            if ln.startswith(("+++", "---", "diff ", "index ", "new file", "deleted file")):
                role = "meta"
            elif ln.startswith("@@"):
                role = "hunk"
            elif ln.startswith("+"):
                role = "add"
            elif ln.startswith("-"):
                role = "del"
            else:
                role = "dim"
            out.append(self(role, ln))
        return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def diff_summary(text: str) -> dict[str, int]:
    files = added = removed = 0
    for ln in text.splitlines():
        if ln.startswith("+++ "):  # her dosyanın tam bir '+++' başlığı vardır
            files += 1
        elif ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    return {"files": files, "added": added, "removed": removed}
