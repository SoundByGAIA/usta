"""Dosya izni denetimleri. Windows'ta izin bitleri yoktur; gizliliği kullanıcı profilinin erişim listesi sağlar."""

import os
import stat
from pathlib import Path

POSIX = os.name != "nt"


def mode_is(path, mode: int) -> bool:
    return not POSIX or stat.S_IMODE(Path(path).stat().st_mode) == mode


def private(path) -> bool:
    """Yalnız sahibi okuyup yazabilir mi?"""
    return not POSIX or stat.S_IMODE(Path(path).stat().st_mode) & 0o077 == 0
