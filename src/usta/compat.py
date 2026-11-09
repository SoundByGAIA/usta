"""Windows uyumu: POSIX'e özgü çağrıların bulunmadığı yerde güvenli karşılıklar.

İşlevler çağrı anında bakar (içe aktarma anında değil); böylece Windows'ta bulunmayan özellikler testte
taklit edilebilir. Windows'ta sembolik bağ ve süreç grubu korumaları zayıflar: sembolik bağ oluşturmak orada
yönetici yetkisi ister, sert sınır Docker yalıtımıdır (bkz. docs/baslangic.md).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys


def nofollow() -> int:
    """`os.open` için O_NOFOLLOW; yoksa 0 (Windows)."""
    return getattr(os, "O_NOFOLLOW", 0)


def nonblock() -> int:
    """`os.open` için O_NONBLOCK; yoksa 0 (Windows)."""
    return getattr(os, "O_NONBLOCK", 0)


def fchmod(fd: int, mode: int) -> None:
    """Açık dosyanın izinlerini ayarlar; Windows'ta (Python 3.13 öncesi) yok, orada yok sayılır."""
    fn = getattr(os, "fchmod", None)
    if fn is not None:
        fn(fd, mode)


def user_args() -> list[str]:
    """Docker `--user uid:gid` bağımsız değişkenleri; kullanıcı kimliği yoksa (Windows) boş."""
    getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return []
    return ["--user", f"{getuid()}:{getgid()}"]


def owns(path) -> bool:
    """Dizin bu kullanıcıya mı ait? Sahiplik kavramı yoksa (Windows) evet sayılır."""
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return True
    return path.stat().st_uid == getuid()


def kill_group(pid: int) -> None:
    """Süreci ve alt süreçlerini sonlandırır; zaten yoksa sessizce geçer."""
    killpg, sigkill = getattr(os, "killpg", None), getattr(signal, "SIGKILL", None)
    if killpg is not None and sigkill is not None:
        try:
            killpg(pid, sigkill)
        except (ProcessLookupError, PermissionError):
            pass
        return
    try:  # Windows: süreç ağacını sonlandır
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        pass


def utf8_console() -> None:
    """Windows konsolunun varsayılan kod sayfası Türkçe karakterleri ve işaretleri basamayabilir; UTF-8'e çevirir."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
