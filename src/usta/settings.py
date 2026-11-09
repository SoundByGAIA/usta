"""Kullanıcı ayarları: `~/.usta/config.json` (tema, mod, model uç noktası, portal). Sır içermez.

Bozuk ya da düşmanca bir dosya uygulamayı düşürmez: geçersiz alanlar varsayılana döner.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from usta import compat, theme, thinking

MODES = ("manual", "auto", "plan")
VIEWS = ("simple", "advanced")
ZOOMS = ("auto", "0.9", "1", "1.1", "1.25", "1.5", "1.75")
MAX_TEXT = 2048


@dataclass(frozen=True)
class Settings:
    theme: str = "siyah"
    mode: str = "manual"
    endpoint: str | None = None
    model: str | None = None
    api: str | None = None  # kayıtlı API adı (apis.json); None: varsayılan uç nokta
    protocol: str | None = None
    context_window: int | None = None
    think: str = "auto"  # auto | off | low | medium | high (bkz. thinking.py)
    view: str = "simple"  # simple: yeni kullanıcı görünümü | advanced: tüm araçlar
    portal: bool = True
    zoom: str = "auto"  # portal arayüz boyutu: auto ya da çarpan
    guard: bool = (
        False  # koruma: doğrulama kapısı + devre kesici (varsayılan kapalı, ölçüm sonrası açılır)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "theme", theme.resolve(self.theme))
        if self.zoom not in ZOOMS:
            raise ValueError(f"geçersiz zoom: {self.zoom!r}")
        if self.think not in thinking.THINK:
            raise ValueError(f"geçersiz think: {self.think!r}")
        if self.view not in VIEWS:
            raise ValueError(f"geçersiz view: {self.view!r}")
        if self.mode not in MODES:
            raise ValueError(f"geçersiz mod: {self.mode!r}")
        if self.endpoint is not None and (
            not isinstance(self.endpoint, str)
            or not self.endpoint.startswith(("http://", "https://"))
            or len(self.endpoint) > MAX_TEXT
        ):
            raise ValueError("endpoint http(s) olmalı")
        if self.model is not None and (
            not isinstance(self.model, str) or not self.model or len(self.model) > 200
        ):
            raise ValueError("model adı geçersiz")
        if self.api is not None and not (isinstance(self.api, str) and len(self.api) <= 30):
            raise ValueError("api adı geçersiz")
        if self.protocol not in (None, "native", "json", "text"):
            raise ValueError("protocol native|json|text olmalı")
        if self.context_window is not None and (
            not isinstance(self.context_window, int)
            or isinstance(self.context_window, bool)
            or self.context_window < 256
        ):
            raise ValueError("context_window >= 256 olmalı")
        for name in ("portal", "guard"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} true/false olmalı")


def load(home: Path) -> Settings:
    path = Path(home) / "config.json"
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() and not path.is_symlink()
            else {}
        )
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    fields = {}
    for key in Settings.__dataclass_fields__:
        if key in data:
            try:
                Settings(**{**asdict(Settings()), **fields, key: data[key]})
            except (ValueError, TypeError):
                continue  # yalnız bu alan varsayılana döner
            fields[key] = data[key]
    return Settings(**fields)


def save(home: Path, s: Settings) -> None:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "config.json"
    tmp = path.with_name("config.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
