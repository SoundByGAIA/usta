"""Yerel model sunucularını bulma ve Ollama'da bağlam varyantı oluşturma.

Varsayılan olarak yalnız `127.0.0.1` sorgulanır. Evdeki başka bilgisayar için iki yol var ve ikisi de dardır:
`lan_scan` yalnız bu bilgisayarın kendi özel /24 ağında, yalnız yaygın 4 portta, yalnız `GET /v1/models` ile bakar;
`probe_host` kullanıcının yazdığı adrese yalnız adres özel ağdaysa (RFC 1918 / yerel) bakar, yönlendirme izlemez.
İnternetteki bir adrese ya da rastgele bir porta portaldan istek atılamaz. Bulunan sunucu yine kullanıcı onayıyla
`apis.json`'a eklenir.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

HOST = "127.0.0.1"
COMMON_PORTS = {11434: "Ollama", 1234: "LM Studio", 8080: "llama.cpp", 8000: "vLLM"}
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,119}$")
MIN_CTX, MAX_CTX = 256, 2_000_000


class LocalError(Exception):
    """Kullanıcıya gösterilebilir yerel model hatası."""


def check_port(port: object) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise LocalError("port 1-65535 arasında olmalı")
    return port


def probe(port: int, timeout: float = 0.8, host: str = HOST) -> dict | None:
    """Port bir OpenAI-uyumlu sunucuysa {port, name, endpoint, models}; değilse None.

    `host` yalnız bu modülün kendi çağrılarından gelir (`127.0.0.1` ya da `private_address` ile doğrulanmış adres).
    """
    check_port(port)
    endpoint = f"http://{host}:{port}/v1"
    try:
        r = httpx.get(
            f"{endpoint}/models", timeout=timeout
        )  # yönlendirme izlenmez (httpx varsayılanı)
        r.raise_for_status()
        models = [m["id"] for m in r.json().get("data", []) if isinstance(m.get("id"), str)]
    except (httpx.HTTPError, ValueError, AttributeError, TypeError, KeyError):
        return None
    return {
        "port": port,
        "name": COMMON_PORTS.get(port, "yerel sunucu"),
        "endpoint": endpoint,
        "models": models,
    }


def scan(port: int | None = None) -> list[dict]:
    """`port` verilirse yalnız onu, verilmezse yaygın portları dener."""
    ports = [check_port(port)] if port is not None else list(COMMON_PORTS)
    return [found for p in ports if (found := probe(p))]


# --- evdeki başka bilgisayar ---------------------------------------------------------------------
_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,61}[A-Za-z0-9])?")
DEFAULT_LAN_PORT = 11434


def parse_host(text: object, default_port: int = DEFAULT_LAN_PORT) -> tuple[str, int]:
    """'192.168.1.20', '192.168.1.20:1234' ya da 'http://pc.local:11434/v1' → (adres, port)."""
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise LocalError("adres boş olamaz (örnek: 192.168.1.20)")
    raw = text.strip()
    if "://" not in raw:
        raw = "http://" + raw
    u = urlsplit(raw)
    if u.scheme != "http" or u.username or u.password or u.query or u.fragment:
        raise LocalError("adres 192.168.1.20 ya da 192.168.1.20:11434 biçiminde olmalı")
    try:
        port = u.port or default_port
    except ValueError:
        raise LocalError("port geçersiz") from None
    host = u.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME.fullmatch(host):
            raise LocalError("adres geçersiz") from None
    else:
        if (
            ip.version != 4
        ):  # IPv6 (ör. ::ffff:8.8.8.8) "özel" denetimini şaşırtabilir; evde IPv4 yeter
            raise LocalError("adres 192.168.1.20 gibi (IPv4) olmalı")
    return host, check_port(port)


def private_address(host: str) -> str:
    """Adres evdeki (özel/yerel) bir bilgisayara çıkıyorsa IPv4 adresini döndürür; değilse LocalError."""
    try:
        ips = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
        except OSError:
            raise LocalError(f"{host} adresi bulunamadı") from None
        ips = {ipaddress.ip_address(i[4][0]) for i in infos}
    if not ips or not all(
        ip.is_private and not ip.is_unspecified and not ip.is_multicast for ip in ips
    ):
        raise LocalError(
            "Bu adres evdeki ağın dışında görünüyor. Yalnız evdeki bilgisayarlar aranır."
        )
    return str(min(ips))


def probe_host(text: object, timeout: float = 2.0) -> dict | None:
    """Kullanıcının yazdığı evdeki adreste bir model sunucusu var mı? Yoksa None; adres dışarıdaysa LocalError."""
    host, port = parse_host(text)
    ip = private_address(host)
    found = probe(port, timeout=timeout, host=ip)
    if found:
        found["endpoint"] = (
            f"http://{host}:{port}/v1"  # kullanıcının yazdığı ad kalsın (IP değişebilir)
        )
        found["host"] = host
    return found


def own_ip() -> str | None:
    """Bu bilgisayarın ağdaki adresi (paket göndermeden: UDP "bağlanma" yalnız yönlendirme tablosuna bakar)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def lan_scan(timeout: float = 0.35) -> list[dict]:
    """Bu bilgisayarın özel /24 ağındaki yaygın model sunucularını bulur (kendisi hariç)."""
    me = own_ip()
    try:
        ip = ipaddress.ip_address(me or "")
    except ValueError:
        return []
    if not ip.is_private or ip.is_loopback or ip.is_link_local:
        return []
    net = ipaddress.ip_network(f"{ip}/24", strict=False)
    targets = [(str(h), p) for h in net.hosts() if h != ip for p in COMMON_PORTS]

    def one(t: tuple[str, int]) -> dict | None:
        host, port = t
        if not _open(host, port, timeout):
            return None
        found = probe(port, timeout=2.0, host=host)
        if found:
            found["host"] = host
        return found

    with ThreadPoolExecutor(max_workers=64) as ex:
        return [f for f in ex.map(one, targets) if f]


def context_variant(port: int, base: str, num_ctx: int, timeout: float = 120.0) -> str:
    """Ollama'da `base` modelinden `num_ctx` parametreli yeni bir model oluşturur; yeni adı döndürür.

    Ollama'nın `/v1` ucu istekteki `num_ctx`'i yok sayar; gerçek pencereyi değiştirmenin yolu budur.
    Ağırlıklar kopyalanmaz, yalnız bir üst veri katmanı eklenir.
    """
    check_port(port)
    if not isinstance(base, str) or not _MODEL_NAME.match(base):
        raise LocalError("model adı geçersiz")
    if (
        not isinstance(num_ctx, int)
        or isinstance(num_ctx, bool)
        or not MIN_CTX <= num_ctx <= MAX_CTX
    ):
        raise LocalError(f"bağlam {MIN_CTX}-{MAX_CTX} arasında olmalı")
    stem, _, tag = base.partition(":")
    new = f"{stem}-ctx{num_ctx}" + (f":{tag}" if tag else "")
    try:
        r = httpx.post(
            f"http://{HOST}:{port}/api/create",
            json={"model": new, "from": base, "parameters": {"num_ctx": num_ctx}, "stream": False},
            timeout=timeout,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        raise LocalError(
            "model varyantı oluşturulamadı (bu bir Ollama sunucusu mu, model yüklü mü?)"
        ) from None
    return new


# --- bellek, model önerisi ve model indirme (Ollama) ----------------------------------------------


def memory_gb() -> float | None:
    """Bu bilgisayarın toplam fiziksel belleği (GB); öğrenilemezse None."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                return None
            return st.ullTotalPhys / 2**30
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            return int(out.stdout.strip()) / 2**30
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 2**20  # kB -> GB
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError, IndexError):
        pass
    return None


# Önerilen modeller: bu depoda gerçekten çalıştırdığımız, Ollama kütüphanesinde bulunan etiketler.
# Büyük modeller denenmediği için önerilmez (bkz. docs/bench-orta-olcum.md).
MODEL_SMALL = {"name": "qwen3:4b-instruct-2507-q4_K_M", "size_gb": 2.5}
MODEL_MEDIUM = {"name": "qwen2.5-coder:7b", "size_gb": 4.7}
MIN_RAM_LOCAL = 6.0  # bunun altında yerel model önerilmez
MIN_RAM_MEDIUM = 12.0


def recommend(ram_gb: float | None) -> dict:
    """Belleğe göre yerel model önerisi. `model` None ise yerel model önerilmez (internet servisi)."""
    if ram_gb is not None and ram_gb < MIN_RAM_LOCAL:
        return {
            "model": None,
            "reason": f"Bu bilgisayarın belleği az ({ram_gb:.0f} GB). Yerel model yavaş ve zayıf kalır; internet servisini öneririz.",
        }
    if ram_gb is None:
        return {
            **MODEL_SMALL,
            "model": MODEL_SMALL["name"],
            "reason": "Belleğini öğrenemedik; en küçük öneriyle başlamak güvenli.",
        }
    pick = MODEL_MEDIUM if ram_gb >= MIN_RAM_MEDIUM else MODEL_SMALL
    return {
        **pick,
        "model": pick["name"],
        "reason": (
            f"Belleğin {ram_gb:.0f} GB. Bu model yaklaşık {pick['size_gb']} GB indirir ve rahat çalışır."
            + (
                ""
                if ram_gb >= MIN_RAM_MEDIUM
                else " Daha büyük modeller bu bellekte yavaşlar ya da hiç çalışmaz."
            )
        ),
    }


def _friendly_pull_error(text: str) -> str:
    low = text.lower()
    if "does not exist" in low or "not found" in low:
        return "Bu isimde bir model bulunamadı. Adı doğru yazdığından emin ol."
    if "no space" in low or "disk" in low:
        return "Diskte yeterli boş yer yok. Yer açıp tekrar dene."
    if "connection" in low or "timeout" in low or "dial" in low:
        return "İndirme sırasında internet bağlantısı koptu. Tekrar dene."
    return f"Model indirilemedi: {text[:160]}"


class PullJob:
    """Ollama'ya model indirir (`/api/pull`); tek seferde bir indirme, ilerleme sorgulanabilir."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict = {"active": False}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    def start(self, port: int, model: str) -> None:
        check_port(port)
        if not isinstance(model, str) or not _MODEL_NAME.match(model):
            raise LocalError("model adı geçersiz")
        with self._lock:
            if self.state.get("active"):
                raise LocalError("zaten bir indirme sürüyor")
            self.state = {
                "active": True,
                "model": model,
                "status": "başlıyor",
                "completed": 0,
                "total": 0,
                "done": False,
                "error": None,
            }
        threading.Thread(target=self._run, args=(port, model), daemon=True).start()

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    def _run(self, port: int, model: str) -> None:
        try:
            with httpx.stream(
                "POST",
                f"http://{HOST}:{port}/api/pull",
                json={"model": model, "stream": True},
                timeout=httpx.Timeout(30.0, read=None),
            ) as r:
                if r.status_code != 200:
                    self._set(active=False, error="Ollama modeli indiremedi (model adı doğru mu?)")
                    return
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("error"):
                        self._set(active=False, error=_friendly_pull_error(str(ev["error"])))
                        return
                    upd: dict = {"status": str(ev.get("status", ""))[:60]}
                    if ev.get("total"):
                        upd.update(total=int(ev["total"]), completed=int(ev.get("completed") or 0))
                    self._set(**upd)
                    if ev.get("status") == "success":
                        self._set(active=False, done=True)
                        return
            self._set(active=False, error="indirme beklenmedik şekilde bitti")
        except httpx.HTTPError:
            self._set(active=False, error="Ollama'ya ulaşılamadı (program açık mı?)")


PULL = PullJob()


# --- eksik programı kurmak ---------------------------------------------------------------------------
# Kurulacaklar sabit bir listedir; komuta kullanıcıdan ya da modelden hiçbir metin girmez. Yalnız Windows'ta ve
# Windows'un kendi paket yöneticisi (winget) varsa çalışır; başka yerde kullanıcı resmî indirme sayfasına yönlenir.
INSTALLABLE = {"ollama": {"label": "Ollama", "winget_id": "Ollama.Ollama"}}
INSTALL_TIMEOUT = 1800  # sn: Ollama yaklaşık 1 GB indirir
# winget çıkış kodları: 0 = kuruldu; 0x8A15002B = zaten kurulu, yükseltme yok; 0x8A150061 = zaten kurulu (işaretli int)
_INSTALL_OK = (0, -1978335189, -1978335135)


def can_install(what: str) -> bool:
    return what in INSTALLABLE and sys.platform == "win32" and shutil.which("winget") is not None


def _ollama_exe() -> str | None:
    """Kurulumdan hemen sonra PATH henüz yenilenmemiş olabilir; bilinen kurulum yerine de bakılır."""
    found = shutil.which("ollama")
    if found:
        return found
    base = os.environ.get("LOCALAPPDATA")
    cand = os.path.join(base, "Programs", "Ollama", "ollama.exe") if base else None
    return cand if cand and os.path.exists(cand) else None


_PROGRESS = re.compile(r"(\d+(?:[.,]\d+)?)\s*([KMG]B)\s*/\s*(\d+(?:[.,]\d+)?)\s*([KMG]B)")
# winget çıkış kodları (işaretsiz): kullanıcıya anlaşılır karşılıklar
_INSTALL_ERRORS = {
    0x8A15000F: "Windows'un program listesi (winget) güncellenemedi. Biraz sonra tekrar dene ya da kendin indir.",
    0x8A150008: "İndirme olmadı. İnternet bağlantını kontrol edip tekrar dene ya da kendin indir.",
}


def parse_progress(chunk: str) -> str | None:
    """winget'in "140 MB / 1.20 GB" biçimindeki ilerleme satırını kısa bir cümleye çevirir; yoksa None."""
    found = _PROGRESS.findall(chunk)
    if not found:
        return None
    a, ua, b, ub = found[-1]
    return f"indiriliyor: {a} {ua} / {b} {ub}"


def _winget_install(winget_id: str, on_progress=None) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(  # kimlik sabit listeden gelir
        [
            "winget", "install", "--id", winget_id, "--exact", "--silent",
            "--accept-source-agreements", "--accept-package-agreements",
            "--disable-interactivity",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    tail: list[str] = []

    def handle(seg: str) -> None:
        if not on_progress:
            return
        msg = parse_progress(seg)
        if msg:
            on_progress(msg)
        elif "Starting package install" in seg or "Paket yüklemesi başlatılıyor" in seg:
            on_progress("kuruluyor")

    def pump() -> None:
        assert proc.stdout is not None
        pending = ""
        while chunk := proc.stdout.read1(256):  # eldeki kadarını okur, 256 bayt dolmasını beklemez
            text = chunk.decode("utf-8", errors="replace")
            tail[:] = [("".join(tail) + text)[-400:]]
            *done, pending = re.split(
                r"[\r\n]", pending + text
            )  # winget ilerlemeyi \r ile günceller
            for seg in done:
                handle(seg)
        handle(pending)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = -1
    reader.join(timeout=5)
    return code, "".join(tail)


def _start_ollama() -> None:
    exe = _ollama_exe()
    if exe:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        subprocess.Popen(
            [exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )


class InstallJob:
    """Sabit listedeki bir programı kurar; tek seferde bir kurulum, durum sorgulanabilir."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict = {"active": False}

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self.state)
        started = snap.pop("started", None)
        if snap.get("active") and started:
            # winget, çıktı boruya yazılırken indirme ilerlemesi basmaz (Windows'ta denendi): her zaman doğru olan
            # tek şey geçen süredir.
            snap["elapsed"] = int(time.time() - started)
        return snap

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)

    def start(self, what: object) -> None:
        if not isinstance(what, str) or what not in INSTALLABLE:
            raise LocalError("bunu kuramam")
        if not can_install(what):
            raise LocalError(
                f"{INSTALLABLE[what]['label']}'ı bu bilgisayarda kendim kuramıyorum. "
                "Resmî sayfadan indirip kurman gerekiyor."
            )
        with self._lock:
            if self.state.get("active"):
                raise LocalError("zaten bir kurulum sürüyor")
            self.state = {
                "active": True,
                "what": what,
                "status": "başlıyor",
                "done": False,
                "error": None,
                "started": time.time(),
            }
        threading.Thread(target=self._run, args=(what,), daemon=True).start()

    def _run(self, what: str) -> None:
        label = INSTALLABLE[what]["label"]
        try:
            self._set(status=f"{label} indiriliyor ve kuruluyor")
            code, _out = _winget_install(
                INSTALLABLE[what]["winget_id"], lambda msg: self._set(status=f"{label} {msg}")
            )
            if code not in _INSTALL_OK:  # "zaten kurulu" da başarıdır
                why = _INSTALL_ERRORS.get(
                    code & 0xFFFFFFFF, f"{label} kurulamadı (kod {code & 0xFFFFFFFF:#x})."
                )
                self._set(active=False, error=f"{why} Resmî sayfadan da indirebilirsin.")
                return
            if what == "ollama":
                self._set(status="Ollama başlatılıyor")
                for i in range(40):
                    if probe(11434, timeout=1.0):
                        break
                    if i == 5:
                        _start_ollama()  # kurucu kendiliğinden açmadıysa
                    time.sleep(1.5)
                else:
                    self._set(
                        active=False,
                        error='Ollama kuruldu ama açılmadı. Başlat menüsünden "Ollama"yı bir kez aç.',
                    )
                    return
            self._set(active=False, done=True, status=f"{label} hazır")
        except (OSError, subprocess.SubprocessError) as e:
            self._set(
                active=False,
                error=f"{label} kurulamadı ({type(e).__name__}). Resmî sayfadan kendin indirebilirsin.",
            )


INSTALL = InstallJob()
