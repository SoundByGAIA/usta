"""Yardım raporu: bir şey bozulduğunda kullanıcının gönderebileceği kısa özet.

Hiçbir yere gönderilmez: metni kullanıcı ekranda görür, isterse kendisi paylaşır. İstemler, dosya içerikleri ve
anahtarlar rapora girmez; denetim günlüğünden yalnız hata satırlarının türü ve saati alınır, günlük dosyasının sonu
gizli bilgi desenlerinden, bağlantı kodlarından ve kullanıcı adını taşıyan ev klasörü yolundan arındırılır.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import sys
import time
from collections import deque
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

from usta import localmodels
from usta.audit import mask

_URL_TAIL = re.compile(r"(https?://[^\s#?\"']+)[#?][^\s\"']*")
# Denetim günlüğünden rapora girebilen olaylar ve alanları. Diğer olaylar (istem, araç çağrısı, sonuç) kullanıcının
# yazdıklarını taşır; rapora ALINMAZ.
_ERROR_FIELDS = {"task_error": "error_type", "task_failed": "error"}
_SAFE_ERROR = re.compile(
    r"model isteği başarısız: (?:HTTP \d{3}|[A-Za-z]+)|model protokolü bozdu|araç çağrısı çözümlenemedi"
    r"|beklenmeyen hata|[A-Za-z_]+(?:Error|Exception|Timeout)"
)


def _short(detail: str) -> str:
    """Hata metninden yalnız bilinen, içerik taşımayan kısmı bırakır (model çıktısı rapora sızmasın)."""
    m = _SAFE_ERROR.match(detail.strip())
    return m.group(0) if m else "bilinmeyen hata"


def version() -> str:
    try:
        return metadata.version("usta")
    except metadata.PackageNotFoundError:
        return "?"


def tidy(text: str, user_home: Path | None = None) -> str:
    """Gizli bilgi desenlerini, bağlantı kodlarını ve ev klasörü yolunu (kullanıcı adı) metinden çıkarır."""
    text = _URL_TAIL.sub(r"\1", mask(text))
    base = str(user_home or Path.home())
    for form in {base, base.replace("\\", "/"), base.replace("\\", "\\\\")}:
        if len(form) > 3:  # "/" ya da "C:\" gibi bir kökü her yerde değiştirme
            text = re.sub(re.escape(form), "~", text, flags=re.IGNORECASE)
    return text


def recent_errors(home: Path, limit: int = 15) -> list[str]:
    """Son hatalar: yalnız saat, olay adı ve hata türü. Görev metni ve dosya içeriği yoktur."""
    rows: list[tuple[float, str]] = []
    try:
        files = sorted(
            (Path(home) / "audit").glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return []
    for path in files[:5]:
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                lines = list(deque(f, maxlen=400))
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            field = _ERROR_FIELDS.get(rec.get("event"))
            if not field:
                continue
            detail = _short(str(rec.get(field) or ""))
            try:
                ts = float(rec.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            rows.append((ts, f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}  {detail}"))
    rows.sort()
    return [text for _, text in rows[-limit:]]


def log_tail(home: Path, lines: int = 30) -> list[str]:
    """Arka plan günlüğünün (usta.log) son satırları; yoksa boş liste."""
    try:
        with (Path(home) / "usta.log").open(encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n")[:300] for line in deque(f, maxlen=lines)]
    except OSError:
        return []


def report(
    home: Path,
    *,
    model: str | None = None,
    api: str | None = None,
    endpoint: str | None = None,
    settings: dict | None = None,
    background: bool = False,
    lan: bool = False,
) -> str:
    ram = localmodels.memory_gb()
    host = (urlsplit(endpoint).hostname or "?") if endpoint else None
    s = settings or {}
    lines = [
        f"Usta yardım raporu ({time.strftime('%Y-%m-%d %H:%M')})",
        "(İçinde yazdıkların, dosyaların ve anahtarın yok. Usta bunu kendiliğinden kimseye göndermez.)",
        "",
        f"Usta sürümü: {version()}",
        f"Python: {platform.python_version()}",
        f"İşletim sistemi: {platform.platform()} ({sys.platform})",
        f"Bellek: {'bilinmiyor' if ram is None else f'{ram:.0f} GB'}",
        f"Docker: {'kurulu' if shutil.which('docker') else 'kurulu değil'}",
        f"Ollama: {'kurulu' if shutil.which('ollama') else 'kurulu değil'}",
        f"Çalışma şekli: {'arka planda (masaüstü simgesi)' if background else 'pencerede'}"
        + (", tablet bağlantısı açık" if lan else ""),
        f"Yapay zekâ: {model or 'seçilmedi'}"
        + (f" (servis: {api or '?'}, adres: {host})" if model else ""),
        "Ayarlar: " + (", ".join(f"{k}={v}" for k, v in s.items()) or "bilinmiyor"),
        "",
        "Son hatalar:",
    ]
    errors = recent_errors(home)
    lines += [f"  {e}" for e in errors] or ["  (kayıtlı hata yok)"]
    tail = log_tail(home)
    if tail:
        lines += ["", "Günlüğün sonu:", *(f"  {t}" for t in tail)]
    return tidy("\n".join(lines)) + "\n"
