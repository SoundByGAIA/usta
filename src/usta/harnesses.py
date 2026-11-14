"""Orkestra şefi: bilgisayardaki diğer yapay zekâ programlarını (Claude Code, Codex, OpenCode, DeepSeek Harness, Hermes)
Usta'nın gözetiminde yardıma çağırma. Tasarım: `docs/c-orkestra-tasarim.md`.

Güvenlik duruşu:

- **Katalog sabittir.** Çağrılabilecek programlar ve komut şablonları burada yazılıdır; ne model ne kullanıcı keyfi komut
  verebilir. Kullanıcı yalnız hangi kataloğu AÇACAĞINI seçer (varsayılan hepsi kapalı).
- **Kabuk yok.** `shell=False`; istem mümkünse komuta değil STDIN'e yazılır (bayrak sanılamaz, süreç listesinde görünmez).
  İstemi argüman olarak isteyen programlarda istem sabit bir önekle başlar (asla `-` ile başlamaz) ve Windows'ta bu
  programlar desteklenmez (`.cmd` sarmalayıcıları kabuk karakterlerini yorumlar).
- **Ortam süzülür.** Çocuk sürece yalnız bir izin listesindeki değişkenler gider; Usta'nın anahtarları ve `USTA_*` gitmez.
  `USTA_DELEGATED=1` verilir: çağrılan program Usta'yı çağıramaz (döngü yok).
- **Sınırlar:** zaman aşımı, çıktı üst sınırı, görev başına çağrı sınırı (tools.py). Çıktı güvenilmez VERİ olarak sarılır.
- **Dürüst sınır:** çağrılan program kullanıcının hesabıyla çalışır ve kendi izin sistemine sahiptir; Usta onun içini
  denetleyemez. Bu yüzden varsayılan "yalnız okuma" (destekleyenlerde), her çağrıda onay ve çıktının veri sayılması şarttır.
"""

from __future__ import annotations

import contextlib
import functools
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from usta.audit import mask
from usta.fetch import wrap_external

MAX_TASK = 8_000  # istem uzunluğu (harf)
MAX_OUTPUT = 20_000  # modele dönen çıktı (harf)
MAX_READ_BYTES = 400_000  # sınırı aşan çıktı okunmadan süreç durdurulur
TIMEOUT = 600.0  # sn
MAX_CALLS_PER_TASK = 3
DELEGATED_ENV = "USTA_DELEGATED"
ARG_PREFIX = "Task: "  # argümanla verilen istem asla "-" ile başlamasın

# Çocuk sürece geçen ortam değişkenleri (başka hiçbiri geçmez).
ENV_ALLOW = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "NO_COLOR",
        "TMPDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "COMSPEC", "PATHEXT",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
    }
)  # fmt: skip


class HarnessError(Exception):
    """Kullanıcıya/modele gösterilebilir delege hatası."""


@dataclass(frozen=True)
class Harness:
    id: str
    label: str
    binary: str
    read_args: (
        tuple[str, ...] | None
    )  # yalnız okuma kipinin argümanları; None: bu program yalnız okuma kipi sunmuyor
    write_args: tuple[str, ...]  # dosya yazabilen kipin argümanları
    prompt_via: str  # "stdin" | "arg"
    note: str = ""  # kullanıcıya gösterilen dürüst not
    needs_node: tuple[int, int] | None = (
        None  # (ana, alt): Node.js sürüm şartı (programın package.json'u)
    )

    @property
    def read_only_supported(self) -> bool:
        return self.read_args is not None


# Her satırın bayrakları programın kendi `--help` çıktısından/belgesinden doğrulandı (docs/c-orkestra-tasarim.md).
CATALOG: dict[str, Harness] = {
    h.id: h
    for h in (
        Harness(
            "claude", "Claude Code", "claude",
            ("-p", "--permission-mode", "plan", "--no-session-persistence"),
            ("-p", "--permission-mode", "acceptEdits", "--no-session-persistence"),
            "stdin",
        ),
        Harness(
            "codex", "Codex", "codex",
            ("exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-"),
            ("exec", "-s", "workspace-write", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-"),
            "stdin",
        ),
        Harness(
            "opencode", "OpenCode", "opencode",
            ("run", "--agent", "plan"),
            ("run", "--agent", "build"),
            "arg",
        ),
        Harness(
            "dsh", "DeepSeek Harness", "dsh",
            None,
            ("headless", "--permission-mode", "workspace-write", "--approval-policy", "never", "-"),
            "stdin",
            "Yalnız okuma kipi yok: bu program her çağrıda dosya yazabilir. Geliştirici önizlemesidir; kendi güvenlik notu "
            "denetlenmediğini söyler.",
            needs_node=(24, 9),
        ),
        Harness(
            "hermes", "Hermes", "hermes",
            None,
            ("-z",),
            "arg",
            "Yalnız okuma kipi yok: bu program dosya yazabilir ve komut çalıştırabilir.",
        ),
    )
}  # fmt: skip


def _which(h: Harness) -> str | None:
    return shutil.which(h.binary)


def _platform() -> str:
    return (
        sys.platform
    )  # testler yalnız bunu değiştirir (sys.platform'u yamalamak shutil'i de bozar)


@functools.lru_cache(maxsize=1)
def _node_version() -> tuple[int, int] | None:
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v?(\d+)\.(\d+)", (r.stdout or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def usable_here(h: Harness) -> str | None:
    """Bu bilgisayarda güvenle çağrılamıyorsa nedeni (düz Türkçe); çağrılabiliyorsa None."""
    if h.prompt_via == "arg" and _platform() == "win32":
        return "Windows'ta henüz desteklenmiyor (komut satırı güvenliği)."
    if h.needs_node is not None:
        have = _node_version()
        if have is None:
            return f"Node.js {h.needs_node[0]}.{h.needs_node[1]} ya da daha yenisi gerekli (bu bilgisayarda Node.js yok)."
        if have < h.needs_node:
            # Eski Node'da program hata vermeden sessizce çıkar (denendi); kullanıcı gerçek nedeni bilsin
            return f"Node.js {h.needs_node[0]}.{h.needs_node[1]} ya da daha yenisi gerekli (sende {have[0]}.{have[1]})."
    return None


def probe_version(h: Harness, timeout: float = 15.0) -> str:
    """`--version` çıktısının ilk satırı; çalışmazsa boş."""
    exe = _which(h)
    if not exe:
        return ""
    try:
        r = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
            env=child_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return mask(out[0])[:80] if out else ""


_VERSIONS: dict[
    str, tuple[float, str, str]
] = {}  # kimlik -> (zaman, ikili yol, sürüm); ayarlar her açılışta yeniden yoklamasın
VERSION_TTL = 300.0


def detect(enabled: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """Katalogdaki her program için durum (arayüz listesi). Sürüm yoklamaları paralel çalışır ve 5 dk önbelleğe alınır."""
    results: dict[str, str] = {}

    def probe(h: Harness) -> None:
        exe, now = _which(h) or "", time.monotonic()
        hit = _VERSIONS.get(h.id)
        if hit and hit[1] == exe and now - hit[0] < VERSION_TTL:
            results[h.id] = hit[2]
            return
        results[h.id] = probe_version(h)
        _VERSIONS[h.id] = (now, exe, results[h.id])

    threads = [
        threading.Thread(target=probe, args=(h,), daemon=True)
        for h in CATALOG.values()
        if _which(h)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    return [
        {
            "id": h.id,
            "label": h.label,
            "installed": _which(h) is not None,
            "version": results.get(h.id, ""),
            "read_only": h.read_only_supported,
            "note": h.note,
            "unsupported": usable_here(h),
            "enabled": h.id in enabled,
        }
        for h in CATALOG.values()
    ]


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Çocuk süreç ortamı: yalnız izin listesi + `USTA_DELEGATED=1`. Usta'nın anahtarları ve USTA_* geçmez."""
    src = os.environ if base is None else base
    env = {k: v for k, v in src.items() if k.upper() in ENV_ALLOW}
    env[DELEGATED_ENV] = "1"
    return env


def build_command(h: Harness, task: str, write: bool) -> tuple[list[str], bytes | None]:
    """(argv, stdin baytları). Kabuk yok; istem ya stdin'e ya da sabit önekli son argümana gider."""
    exe = _which(h)
    if not exe:
        raise HarnessError(f"{h.label} bu bilgisayarda kurulu değil.")
    reason = usable_here(h)
    if reason:
        raise HarnessError(f"{h.label}: {reason}")
    if not write and h.read_args is None:
        raise HarnessError(
            f"{h.label} yalnız okuma kipi sunmuyor; çağırmak için dosya yazma izni gerekir."
        )
    args = list(h.write_args if write else h.read_args or ())
    if h.prompt_via == "stdin":
        return [exe, *args], task.encode("utf-8")
    return [exe, *args, ARG_PREFIX + task], None


def _kill_tree(proc: subprocess.Popen) -> None:
    with contextlib.suppress(OSError, ProcessLookupError):
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # çocuğun çocukları da (yeni oturum açıldı)


def run(
    h: Harness,
    task: str,
    *,
    write: bool,
    root: Path,
    cancel: threading.Event | None = None,
    timeout: float = TIMEOUT,
    max_chars: int = MAX_OUTPUT,
    base_env: dict[str, str] | None = None,
) -> str:
    """Programı çalıştırır; çıktıyı güvenilmez veri olarak sarılmış metin olarak döndürür. Hata: HarnessError."""
    if os.environ.get(DELEGATED_ENV):
        raise HarnessError(
            "Bu Usta başka bir programdan çağrılmış; tekrar başka programa devredemez."
        )
    task = str(task or "").strip()
    if not task:
        raise HarnessError("iş metni boş")
    if len(task) > MAX_TASK:
        raise HarnessError(f"iş metni en çok {MAX_TASK} harf olabilir")
    argv, stdin = build_command(h, task, write)
    popen_kw: dict = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    else:
        popen_kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(Path(root).resolve()),
            env=child_env(base_env),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kw,
        )
    except OSError as e:
        raise HarnessError(f"{h.label} başlatılamadı ({type(e).__name__}).") from None

    out, err = bytearray(), bytearray()
    over = threading.Event()

    def pump(stream, buf: bytearray, cap: int) -> None:
        while chunk := stream.read(4096):
            if len(buf) < cap:
                buf.extend(chunk[: cap - len(buf)])
            if len(buf) >= cap:
                over.set()  # sınır aşıldı: süreç durdurulur, çıktı kesilir

    readers = [
        threading.Thread(target=pump, args=(proc.stdout, out, MAX_READ_BYTES), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, err, 20_000), daemon=True),
    ]
    for t in readers:
        t.start()
    if stdin is not None:

        def feed() -> None:
            with contextlib.suppress(OSError, ValueError):
                assert proc.stdin is not None
                proc.stdin.write(stdin)
                proc.stdin.close()

        threading.Thread(target=feed, daemon=True).start()

    deadline = time.monotonic() + timeout
    status = ""
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            status = "iptal"
        elif time.monotonic() >= deadline:
            status = "zaman aşımı"
        elif over.is_set():
            status = "çıktı sınırı"
        if status:
            _kill_tree(proc)
            break
        time.sleep(0.05)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
    for t in readers:
        t.join(timeout=2)

    text = out.decode("utf-8", errors="replace").strip()
    truncated = status == "çıktı sınırı" or len(text) > max_chars
    text = text[:max_chars]
    if status == "iptal":
        raise HarnessError("görev durduruldu; program kapatıldı.")
    if status == "zaman aşımı":
        raise HarnessError(f"{h.label} {int(timeout)} saniyede bitmedi; kapatıldı.")
    code = proc.returncode
    if status != "çıktı sınırı" and code not in (
        0,
        None,
    ):  # sınırı aşınca programı BİZ durdurduk: hata sayılmaz
        tail = mask(err.decode("utf-8", errors="replace").strip()[-400:])
        hint = " Programın kendi girişini/ayarını yaptığından emin ol." if not text else ""
        raise HarnessError(f"{h.label} hata verdi (kod {code}).{hint} {tail}".strip())
    if not text:
        raise HarnessError(f"{h.label} boş cevap verdi.")
    note = "\n[çıktı kesildi]" if truncated else ""
    return wrap_external(f"Başka program: {h.label}", text + note, origin=f"{h.label} programından")
