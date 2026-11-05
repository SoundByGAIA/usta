"""İzin motoru: okuma/yazma çalışma alanıyla sınırlı, dış dünya onaylı, bilinmeyen yasak."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from usta import memory
from usta.fetch import validate_url
from usta.proxy import host_allowed

FILE_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "outline", "read_symbol"}
WRITE_TOOLS = {"write_file", "edit_file"}
SYMBOL_TOOLS = {
    "find_symbol",
    "symbol_context",
    "related_files",
}  # salt okunur, yalnız çalışma alanı indeksi
# Ajanın yazamayacağı yollar: .git (hook/config ile kullanıcı git çalıştırınca ana makinede kod çalışır),
# .usta (proje hafızası yalnız `remember` aracıyla ve temizlenerek yazılır).
PROTECTED_DIRS = frozenset({".git", ".usta"})


class Decision(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PathEscapeError(ValueError):
    pass


def resolve_path(root: Path, path: str) -> Path:
    """Yolu çözer (symlink dahil); çalışma alanı kökünün dışına çıkıyorsa reddeder."""
    if not isinstance(path, str) or not path or "\x00" in path or Path(path).is_absolute():
        raise PathEscapeError(f"geçersiz yol: {path!r}")
    root = Path(root).resolve()
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise PathEscapeError(f"çalışma alanı dışı: {path!r}")
    return full


class Policy:
    def __init__(
        self,
        root: Path,
        allowed_hosts: set[str] | None = None,
        mcp_modes: dict[str, str] | None = None,
    ):
        self.root = Path(root).resolve()
        self.mcp_modes = dict(mcp_modes or {})
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}

    def check(self, tool: str, args: dict) -> Decision:
        if tool.startswith("mcp__"):  # yalnız kullanıcının eklediği sunucuların bilinen araçları
            mode = self.mcp_modes.get(tool)
            return (
                Decision.DENY
                if mode is None
                else Decision.ALLOW
                if mode == "allow"
                else Decision.ASK
            )
        if tool in SYMBOL_TOOLS:
            path = args.get("path")
            if (
                path is not None
            ):  # symbol_context'te isteğe bağlı dosya yolu: çalışma alanı dışına çıkamaz
                try:
                    resolve_path(self.root, path)
                except PathEscapeError:
                    return Decision.DENY
            return Decision.ALLOW
        if tool in FILE_TOOLS:
            try:
                full = resolve_path(self.root, args.get("path"))
            except PathEscapeError:
                return Decision.DENY
            if tool in WRITE_TOOLS:
                parts = {
                    p.casefold()
                    for p in (*full.relative_to(self.root).parts, *Path(args["path"]).parts)
                }
                if PROTECTED_DIRS & parts:
                    return (
                        Decision.DENY
                    )  # .git / .usta'ya yazılamaz (okuma serbest); `.GIT` ve bağ biçimleri dahil
            return Decision.ALLOW
        if tool == "run":
            return Decision.ALLOW  # sandbox içinde: ağ kapalı, yalnız çalışma alanı bağlı
        if tool == "fetch_url":
            try:
                _, host = validate_url(args.get("url"))
            except ValueError:
                return Decision.DENY  # geçersiz/IP/yerel hedef: onaya bile sunulmaz
            return Decision.ALLOW if host_allowed(host, self.allowed_hosts) else Decision.ASK
        if tool == "remember":
            # kalıcı hafıza sonraki görevleri etkiler: komut/URL/gizli bilgi/onay iddiası içeren not kullanıcı onayı ister
            return Decision.ASK if memory.suspicious(args.get("text")) else Decision.ALLOW
        if tool == "web_search":
            return Decision.ASK
        return Decision.DENY
