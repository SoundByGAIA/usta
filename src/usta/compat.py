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


_STD_HANDLES = (-11, -12)  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
_VT_FLAG = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


def enable_ansi(kernel32=None, windows: bool | None = None) -> bool:
    """Konsolda renk kodlarını (ANSI) çözmeyi açar. Açılamazsa False döner (renk kapatılmalı).

    Klasik Windows `cmd` penceresi bunu kendiliğinden yapmaz; açılmazsa ekranda `←[1m` gibi çöp karakterler çıkar.
    Konsol olmayan çıktılar (dosyaya yönlendirme) için yapılacak bir şey yoktur.
    """
    if windows is None:
        windows = sys.platform == "win32"
    if not windows:
        return True
    import ctypes

    try:
        k32 = kernel32 if kernel32 is not None else ctypes.windll.kernel32  # type: ignore[attr-defined]
        ok = True
        for std in _STD_HANDLES:
            handle = k32.GetStdHandle(std)
            mode = ctypes.c_ulong()
            if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue  # konsol değil
            if not mode.value & _VT_FLAG and not k32.SetConsoleMode(handle, mode.value | _VT_FLAG):
                ok = False
        return ok
    except (AttributeError, OSError):
        return False


def has_readline() -> bool:
    """`readline` modülü var mı? Windows'ta yok; yokken istem işaret karakterleri ekranda çöp olarak görünür."""
    import importlib.util

    return importlib.util.find_spec("readline") is not None


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def is_dir_link(path) -> bool:
    """Sembolik bağ ya da Windows dizin birleşimi (junction) mi? (Python 3.11'de `is_junction` yok.)"""
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def remove_dir_link(path) -> None:
    """Klasör bağını (hedefine dokunmadan) kaldırır; birleşimlerde `unlink` yetmez, `rmdir` gerekir."""
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


def make_dir_link(target, link, windows: bool | None = None) -> None:
    """`link` adıyla `target` klasörüne bağ kurar.

    Windows'ta sembolik bağ yönetici yetkisi ya da Geliştirici Modu ister (WinError 1314); normal kullanıcıda
    bu yüzden çöküyordu. Ayrıcalık yoksa aynı işi gören dizin birleşimine (junction) düşülür.
    """
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except FileExistsError:
        raise
    except OSError:
        if windows is None:
            windows = sys.platform == "win32"
        if not windows:
            raise
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError):
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        if r.returncode != 0:
            raise OSError(f"klasör bağı oluşturulamadı: {link}") from None
