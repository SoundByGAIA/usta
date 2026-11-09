"""Terminalden başlatılan yerel web portalı: uvicorn'u bir iş parçacığında çalıştırır.

Varsayılan olarak yalnız 127.0.0.1'e bağlanır. Tarayıcı, jeton yerine tek kullanımlık giriş kodu ile açılır
(auth.py). `lan=True` (`usta --lan`) açıkça istenirse yerel ağdaki cihazlar (tablet, telefon) de bağlanabilir;
onlar 6 haneli, kısa ömürlü bir eşleştirme PIN'i ile girer. Trafik şifrelenmez: yalnız güvenilir ağda kullanılır.
"""

from __future__ import annotations

import html
import os
import secrets
import socket
import threading
import time
from pathlib import Path

import uvicorn

from usta.api import create_app
from usta.auth import LoginCodes
from usta.tasks import TaskManager

HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"


def lan_addresses() -> list[str]:
    """Bu bilgisayarın yerel ağ IPv4 adresleri (loopback hariç)."""
    ips: set[str] = set()
    try:  # UDP "bağlanma" paket göndermez; yalnız hangi arayüzün kullanılacağını öğrenir
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            ips.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _free(port: int, host: str = HOST) -> bool:
    with socket.socket() as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


class Portal:
    def __init__(
        self,
        manager: TaskManager,
        home: Path,
        token: str,
        preferred_port: int = 8765,
        workspace: str | None = None,
        lan: bool = False,
    ):
        self.codes = LoginCodes()
        self.lan = lan
        self.pair = LoginCodes(ttl=300.0, digits=6) if lan else None
        self._lan_urls: list[str] = []  # start() portu bilince doldurulur; API aynı listeyi görür
        self._host = LAN_HOST if lan else HOST
        self._home = Path(home)
        trusted = ["127.0.0.1", "localhost"]
        if lan:  # DNS rebinding koruması sürer: yalnız bu makinenin kendi adresleri kabul edilir
            name = socket.gethostname().lower()
            trusted += [*lan_addresses(), name, f"{name}.local"]
        self._app = create_app(
            manager,
            Path(home),
            token,
            login=self.codes,
            workspace=workspace,
            trusted_hosts=trusted,  # DNS rebinding: başka Host başlığı reddedilir
            pair=self.pair,
            lan_urls=self._lan_urls,
        )
        self._preferred = preferred_port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def start(self) -> str:
        port = self._preferred if self._preferred and _free(self._preferred, self._host) else 0
        config = uvicorn.Config(self._app, host=self._host, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("portal başlatılamadı")
            time.sleep(0.05)
        real = self._server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://{HOST}:{real}/"
        if self.lan:
            self._lan_urls[:] = [f"http://{ip}:{real}/" for ip in lan_addresses()]
        return self.url

    def lan_urls(self) -> list[str]:
        return list(self._lan_urls)

    def pairing(self) -> tuple[list[str], str] | None:
        """(tablet adresleri, yeni eşleştirme PIN'i); yerel ağ modu kapalıysa None."""
        if self.pair is None:
            return None
        return self.lan_urls(), self.pair.issue()

    def login_url(self) -> str:
        return f"{self.url}?code={self.codes.issue()}"

    def login_page(self, ttl: float = 90.0) -> str:
        """Tarayıcıya verilecek `file://` adresi: giriş kodu komut satırında (`/proc/*/cmdline`) görünmesin.

        Kod, yalnız sahibinin okuyabildiği (0600) geçici bir yönlendirme sayfasına yazılır ve kısa süre sonra silinir.
        """
        d = self._home / "login"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        for old in d.glob("*.html"):  # önceki oturumlardan kalanlar
            old.unlink(missing_ok=True)
        path = d / f"{secrets.token_hex(8)}.html"
        url = html.escape(self.login_url(), quote=True)
        page = (
            '<!doctype html><meta charset="utf-8"><title>Usta</title>'
            f'<meta http-equiv="refresh" content="0;url={url}"><p>Usta portalına yönlendiriliyor… '
            f'<a href="{url}">Açılmazsa tıkla</a></p>'
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(page)
        timer = threading.Timer(ttl, lambda: path.unlink(missing_ok=True))
        timer.daemon = True
        timer.start()
        return path.as_uri()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
