"""Docker sandbox: tek komutu yalıtılmış, ağsız bir konteynerde çalıştırır."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Self

from usta import compat
from usta.workspace import find_protected

MAX_OUTPUT = 1_000_000  # bayt; fazlası kırpılır
PIN_FILE = "sandbox-pin.json"
_PIN_OK: set[tuple[str, str]] = set()  # bu süreçte doğrulanmış (imaj, kimlik) çiftleri


def _home() -> Path:
    return Path(os.environ.get("USTA_HOME") or Path.home() / ".usta")


def local_image_id(image: str) -> str | None:
    p = subprocess.run(
        ["docker", "image", "inspect", "-f", "{{.Id}}", image],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def load_pins(home: Path | None = None) -> dict[str, str]:
    path = (home or _home()) / PIN_FILE
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() and not path.is_symlink()
            else {}
        )
    except (OSError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(data, dict)
        else {}
    )


def pin_image(image: str, home: Path | None = None) -> str:
    """Yerel imajın kimliğini (sha256) kaydeder; sonraki her çalıştırmada doğrulanır (tedarik zinciri)."""
    iid = local_image_id(image)
    if iid is None:
        raise SandboxError(
            f"imaj yerelde yok: {image} (docker pull {image}; Usta kendiliğinden çekmez)"
        )
    home = home or _home()
    pins = load_pins(home) | {image: iid}
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = home / (PIN_FILE + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(pins, f, indent=2)
    os.replace(tmp, home / PIN_FILE)
    _PIN_OK.clear()
    return iid


def verify_pin(image: str) -> None:
    """Sabitlenmiş imajın yerel kimliği değiştiyse çalıştırmayı reddeder (sabitleme yoksa serbest)."""
    want = load_pins().get(image)
    if want is None:
        return
    if (image, want) in _PIN_OK:
        return
    have = local_image_id(image)
    if have != want:
        raise SandboxError(
            f"imaj sabitlemesi tutmuyor: {image} değişmiş (beklenen {want[:19]}…, yerel {(have or 'yok')[:19]}…). "
            "Güveniyorsan yeniden sabitle: usta sandbox pin"
        )
    _PIN_OK.add((image, want))


@dataclass(frozen=True)
class SandboxConfig:
    workdir: Path
    image: str = "python:3.12-slim"
    timeout: float = 60.0
    memory: str = "512m"
    cpus: str = "1"
    pids: int = 128
    # Ağ varsayılan kapalı. Alan adı verilirse sandbox `--internal` ağa girer ve yalnız bu
    # alan adlarına izin veren proxy üzerinden çıkar (HTTPS içeriği opaktır; bkz. docs/design.md).
    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = (80, 443)
    proxy_image: str = "python:3.12-slim"
    proxy_allow_private: bool = False  # yalnız testler: özel adreslere çözülen hedefe izin ver
    ro_mounts: tuple[tuple[Path, str], ...] = ()  # (ana makine yolu, konteyner yolu), salt okunur


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    network_log: tuple[dict, ...] = ()


class SandboxError(Exception):
    pass


_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def unsafe_mount_path(path: str, windows: bool | None = None) -> bool:
    """`-v kaynak:hedef` sözdizimini bozabilecek ':' ya da ',' var mı? Windows'ta yalnız sürücü harfi iki noktası serbesttir."""
    if windows is None:
        windows = sys.platform == "win32"
    if windows and _DRIVE.match(path):
        path = path[2:]
    return ":" in path or "," in path


def build_docker_args(
    cfg: SandboxConfig,
    command: list[str],
    name: str | None = None,
    network: str | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    if not command:
        raise ValueError("komut boş")
    workdir = Path(cfg.workdir).resolve()
    if not workdir.is_dir():
        raise ValueError(f"çalışma dizini yok: {workdir}")
    args = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        network or "none",
        "--read-only",
    ]
    args += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    args += ["--pids-limit", str(cfg.pids), "--memory", cfg.memory, "--cpus", cfg.cpus]
    args += [*compat.user_args(), "--tmpfs", "/tmp:rw,size=64m"]
    if name:
        args += ["--name", name]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    for src, dst in cfg.ro_mounts:
        src = Path(src).resolve()
        if not src.exists() or not dst.startswith("/") or ":" in dst:
            raise ValueError(f"geçersiz salt okunur bağlama: {src} -> {dst}")
        args += ["-v", f"{src}:{dst}:ro"]
    if unsafe_mount_path(str(workdir)):  # -v sözdizimini bozar / seçenek enjekte eder
        raise ValueError(f"çalışma klasörü adında ':' ya da ',' olamaz: {workdir}")
    args += ["-v", f"{workdir}:/workspace:rw"]
    protected = {".git", ".usta"} | find_protected(
        Path(workdir)
    )  # her derinlikteki .git, iç içe .usta, çıplak depo
    for rel in sorted(protected):  # sandbox içinden değiştirilemez (hook/config, hafıza)
        p = Path(workdir) / rel
        if not p.exists() or p.is_symlink():
            continue
        if ":" in rel or "," in rel:
            raise ValueError(f"korumalı yol adında ':' ya da ',' olamaz: {rel}")
        args += ["-v", f"{p.resolve()}:/workspace/{rel}:ro"]
    args += ["-w", "/workspace", cfg.image]
    return args + command


def _text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        data = data.encode()
    return data[:MAX_OUTPUT].decode(errors="replace")


def _kill_and_collect(proc: subprocess.Popen, name: str) -> tuple[bytes, bytes]:
    # Konteyner henüz yaratılmamış olabilir (yarış): öldürmeyi çıkana kadar tekrarla.
    for _ in range(20):
        subprocess.run(["docker", "kill", name], check=False, capture_output=True)
        try:
            return proc.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            continue
    proc.kill()
    return proc.communicate()


def _run_container(
    cfg: SandboxConfig,
    command: list[str],
    cancel: threading.Event | None,
    network: str | None = None,
    env: dict[str, str] | None = None,
) -> RunResult:
    verify_pin(cfg.image)
    name = f"usta-{uuid.uuid4().hex[:12]}"
    args = build_docker_args(cfg, command, name=name, network=network, env=env)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + cfg.timeout
    timed_out = cancelled = False
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            cancelled = cancel is not None and cancel.is_set()
            timed_out = not cancelled and time.monotonic() >= deadline
            if cancelled or timed_out:
                out, err = _kill_and_collect(proc, name)
                break
    code = 124 if timed_out else 130 if cancelled else proc.returncode
    return RunResult(code, _text(out), _text(err), timed_out=timed_out, cancelled=cancelled)


def run_command(
    cfg: SandboxConfig,
    command: list[str],
    cancel: threading.Event | None = None,
    session: ProxyNetwork | None = None,
) -> RunResult:
    if cancel is not None and cancel.is_set():
        return RunResult(130, "", "", cancelled=True)
    if shutil.which("docker") is None:
        raise SandboxError(
            "Docker bu bilgisayarda kurulu değil, bu yüzden komut çalıştırılamıyor. "
            "Dosya okuyup yazarak devam et; yazdığın kodu çalıştırarak deneyemezsin."
        )
    if not cfg.allowed_hosts:
        return _run_container(cfg, command, cancel)
    if session is not None:
        r = _run_container(cfg, command, cancel, session.network, session.env)
        return replace(r, network_log=tuple(session.decisions()))
    with ProxyNetwork(cfg) as net:
        r = _run_container(cfg, command, cancel, net.network, net.env)
        return replace(r, network_log=tuple(net.decisions()))


# --- allowlist proxy ağı -------------------------------------------------------------------

PROXY_PORT = 3128
LABELS = ["--label", "usta.managed=1", "--label", f"usta.pid={os.getpid()}"]


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(
        ["docker", *args], check=False, capture_output=True, encoding="utf-8", errors="replace"
    )
    if check and p.returncode != 0:
        raise SandboxError((p.stderr.strip().splitlines() or ["docker hatası"])[-1])
    return p


class ProxyNetwork:
    """`--internal` ağ + allowlist proxy konteyneri. Çıkışta ikisi de silinir."""

    def __init__(self, cfg: SandboxConfig):
        self.cfg = cfg
        tag = uuid.uuid4().hex[:10]
        self.network, self.proxy = f"usta-net-{tag}", f"usta-proxy-{tag}"
        self._cached: list[dict] | None = None

    @property
    def env(self) -> dict[str, str]:
        url = f"http://{self.proxy}:{PROXY_PORT}"
        return {k: url for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}

    def __enter__(self) -> Self:
        try:
            self._start()
        except BaseException:
            self._stop()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._cached = self._read_decisions()
        self._stop()

    def _start(self) -> None:
        cfg = self.cfg
        verify_pin(cfg.proxy_image)
        _docker("network", "create", "--internal", *LABELS, self.network)
        run = [
            "run",
            "-d",
            "--pull",
            "never",
            "--name",
            self.proxy,
            "--network",
            self.network,
            *LABELS,
        ]
        run += ["--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        run += ["--pids-limit", "64", "--memory", "128m", "--cpus", "0.5"]
        run += compat.user_args()
        run += ["-e", f"USTA_ALLOW={','.join(cfg.allowed_hosts)}"]
        run += ["-e", f"USTA_PORTS={','.join(map(str, cfg.allowed_ports))}"]
        if cfg.proxy_allow_private:
            run += ["-e", "USTA_ALLOW_PRIVATE=1"]
        script = Path(__file__).with_name("proxy.py")
        run += [
            "-v",
            f"{script}:/proxy.py:ro",
            cfg.proxy_image,
            "python",
            "/proxy.py",
            f"0.0.0.0:{PROXY_PORT}",
        ]
        _docker(*run)
        _docker("network", "connect", "bridge", self.proxy)  # dış çıkış yalnız proxy'de
        for _ in range(60):
            if '"listening"' in _docker("logs", self.proxy, check=False).stdout:
                return
            if (
                _docker(
                    "inspect", "-f", "{{.State.Running}}", self.proxy, check=False
                ).stdout.strip()
                != "true"
            ):
                break
            time.sleep(0.2)
        tail = (_docker("logs", self.proxy, check=False).stderr.strip().splitlines() or ["?"])[-1]
        raise SandboxError(f"proxy başlamadı: {tail}")

    def _stop(self) -> None:
        _docker("rm", "-f", self.proxy, check=False)
        _docker("network", "rm", self.network, check=False)

    def _read_decisions(self) -> list[dict]:
        out = _docker("logs", self.proxy, check=False).stdout
        rows = []
        for line in out.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") == "decision":
                rows.append({k: v for k, v in row.items() if k != "event"})
        return rows

    def decisions(self) -> list[dict]:
        return self._cached if self._cached is not None else self._read_decisions()


def _pid_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def cleanup_orphans() -> int:
    """Sahibi (usta.pid) ölmüş proxy konteynerlerini ve ağlarını siler; silinen sayısını döner."""
    removed = 0
    for kind, fmt, rm in (
        (["ps", "-a"], '{{.Names}} {{.Label "usta.pid"}}', ["rm", "-f"]),
        (["network", "ls"], '{{.Name}} {{.Label "usta.pid"}}', ["network", "rm"]),
    ):
        p = _docker(*kind, "--filter", "label=usta.managed=1", "--format", fmt, check=False)
        for line in p.stdout.splitlines():
            name, _, pid = line.partition(" ")
            if name and not _pid_alive(pid.strip()):
                removed += _docker(*rm, name, check=False).returncode == 0
    return removed
