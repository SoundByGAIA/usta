"""MCP Runtime: MCP sunucularını yalıtılmış bir konteynerde başlatır (docs/design.md §5.3).

Neden: bir MCP sunucusu kullanıcının eklediği, üçüncü taraf koddur ve ana makinede çalışırsa kullanıcının
tüm yetkileriyle (ev dizini, jetonlar, ssh anahtarları) çalışır. Burada sunucu şu koşullarla başlar:

- kök dosya sistemi salt okunur, yazma yalnız sınırlı `tmpfs`; root olmayan kullanıcı, `cap_drop=ALL`,
  `no-new-privileges`, CPU/RAM/PID sınırı, `--init` (artık süreçler toplanır);
- ağ kapalı; `allow_hosts` verilirse yalnız o alan adlarına allowlist proxy (sandbox ile aynı) üzerinden çıkar;
- Docker soketi, ev dizini ve ana makine ortamı BAĞLANMAZ; çalışma alanı yalnız açıkça istenirse (`ro`/`rw`);
- sunucuya yalnız kendi tanımlı sır adları verilir (değerler komut satırına değil, docker istemcisinin
  ortamına yazılır; `ps` çıktısında görünmez);
- izolasyon kurulamazsa (Docker yok, imaj yok, sabitleme tutmuyor) sunucu BAŞLAMAZ; sessizce ana makineye
  düşülmez. Ana makine yürütmesi ayrı, açık bir uyumluluk modudur (`isolation: host`).

Paket sabitleme: `prepare`, sunucu komutunu ağ allowlist'i (yalnız paket kayıtları) altında bir kez çalıştırıp
paketleri bir önbelleğe indirir; çalışma anında ağ olmadan, önbellek salt okunur bağlanarak çalışır. İmaj kimliği
ve önbelleğin içerik özeti kaydedilir, her başlatmada doğrulanır; değişmişse başlatma reddedilir.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from usta import compat, mcpconfig
from usta.mcp import McpClient, McpError
from usta.sandbox import ProxyNetwork, SandboxConfig, SandboxError
from usta.workspace import find_protected

PREPARE_HOSTS = ("registry.npmjs.org", "pypi.org", "files.pythonhosted.org")
CACHE_DIR = "mcp-cache"
CONTAINER_HOME = "/tmp/home"
# docker istemci sürecinin (sunucu değil) çalışabilmesi için gereken ana makine ortamı
DOCKER_CLIENT_ENV = ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR")
OFFLINE_ENV = {
    "npm_config_cache": "/cache/npm",
    "npm_config_offline": "true",
    "npm_config_ignore_scripts": "true",  # paket kurulum betikleri çalışmaz
    "npm_config_update_notifier": "false",
    "npm_config_fund": "false",
    "UV_CACHE_DIR": "/cache/uv",
    "UV_OFFLINE": "1",
    "PIP_NO_INDEX": "1",
}


class McpIsolationError(McpError):
    """İzolasyon kurulamadı; sunucu başlatılmaz (ana makineye geri düşülmez)."""


def docker_problem() -> str | None:
    """Docker kullanılabilir değilse nedenini, kullanılabilirse None döner."""
    if shutil.which("docker") is None:
        return "Docker bulunamadı"
    p = subprocess.run(
        ["docker", "version", "-f", "{{.Server.Version}}"], capture_output=True, check=False
    )
    return None if p.returncode == 0 else "Docker hizmetine erişilemiyor"


def image_id(image: str) -> str | None:
    p = subprocess.run(
        ["docker", "image", "inspect", "-f", "{{.Id}}", image],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def cache_path(home: Path, name: str) -> Path:
    return Path(home) / CACHE_DIR / name


def cache_digest(root: Path) -> str:
    """Önbellek dizininin içerik özeti (yol + içerik); değişiklik/ekleme/silme farklı özet üretir."""
    h = hashlib.sha256()
    root = Path(root)
    if not root.is_dir():
        return ""
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix().encode()
        if p.is_symlink():
            h.update(b"L\0" + rel + b"\0" + os.readlink(p).encode() + b"\0")
        elif p.is_file():
            h.update(b"F\0" + rel + b"\0")
            with p.open("rb") as f:
                while chunk := f.read(1 << 20):
                    h.update(chunk)
            h.update(b"\0")
        elif p.is_dir():
            h.update(b"D\0" + rel + b"\0")
    return "sha256:" + h.hexdigest()


def build_run_args(
    srv: mcpconfig.Server,
    *,
    name: str,
    network: str | None = None,
    workspace: Path | None = None,
    cache: Path | None = None,
    cache_rw: bool = False,
    secret_names: tuple[str, ...] = (),
    extra_env: Mapping[str, str] | None = None,
    interactive: bool = True,
) -> list[str]:
    """`docker run` argümanları. Değerler argv'ye yazılmaz: `-e ADI` değeri istemci ortamından alır."""
    if srv.isolation != "container" or not srv.image:
        raise McpIsolationError("konteyner izolasyonu için imaj gerekli (usta mcp add --image ...)")
    args = ["docker", "run", "--rm", "--pull", "never", "--name", name, "--init"]
    if interactive:
        args.append("-i")
    args += ["--network", network or "none", "--read-only"]
    args += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    args += ["--pids-limit", str(srv.pids), "--memory", srv.memory, "--memory-swap", srv.memory]
    args += ["--cpus", srv.cpus, *compat.user_args()]
    args += ["--tmpfs", "/tmp:rw,nosuid,size=64m", "-e", f"HOME={CONTAINER_HOME}"]
    for key, value in {**OFFLINE_ENV, **(extra_env or {})}.items():
        args += ["-e", f"{key}={value}"]
    for key in secret_names:
        args += ["-e", key]  # değer docker istemcisinin ortamından gelir
    if cache is not None:
        args += ["-v", f"{Path(cache).resolve()}:/cache:{'rw' if cache_rw else 'ro'}"]
    workdir = "/tmp"
    if srv.workspace != "none":
        if workspace is None:
            raise McpIsolationError("sunucu çalışma alanı istiyor ama çalışma alanı verilmedi")
        ws = Path(workspace).resolve()
        if ":" in str(ws) or "," in str(ws):
            raise McpIsolationError("çalışma klasörü adında ':' ya da ',' olamaz")
        args += ["-v", f"{ws}:/workspace:{srv.workspace}"]
        if srv.workspace == "rw":  # yazılabilirse de .git/.usta ajan gibi salt okunur kalır
            for rel in sorted({".git", ".usta"} | find_protected(ws)):
                p = ws / rel
                if p.exists() and not p.is_symlink() and ":" not in rel and "," not in rel:
                    args += ["-v", f"{p.resolve()}:/workspace/{rel}:ro"]
        workdir = "/workspace"
    args += ["-w", workdir, srv.image, *srv.command]
    return args


@dataclass
class Handle:
    """Başlatılmış bir izole sunucu: istemci + temizlik + (varsa) proxy ağı."""

    client: McpClient
    name: str
    net: ProxyNetwork | None = None
    notes: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)  # proxy'nin ağ kararları (kapanışta dolar)
    scratch: Path | None = None  # bu çalıştırmaya özel önbellek kopyası (kapanışta silinir)

    def close(self) -> None:
        self.client.close()
        _rm(self.name)
        if self.scratch is not None:
            shutil.rmtree(self.scratch, ignore_errors=True)
            self.scratch = None
        if self.net is not None:
            net, self.net = self.net, None
            net.__exit__(None, None, None)
            self.decisions = list(net.decisions())


def _rm(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def _no_image_msg(name: str) -> str:
    return (
        f"'{name}' için imaj tanımlı değil (v0.2.0 öncesi kayıt). MCP sunucuları artık yalıtılmış konteynerde çalışır: "
        f"`usta mcp add {name} --image <imaj> ...` ile yeniden kaydet "
        "(ana makinede çalıştırmak yalnız `--isolation host --i-understand-host-risk` ile)"
    )


def _verify_pins(home: Path, srv: mcpconfig.Server) -> list[str]:
    notes = []
    if not srv.image:
        raise McpIsolationError(_no_image_msg(srv.name))
    current = image_id(srv.image)
    if current is None:
        raise McpIsolationError(
            f"imaj yerelde yok: {srv.image} (Usta imajı kendiliğinden çekmez: docker pull {srv.image})"
        )
    if srv.pin_image and current != srv.pin_image:
        raise McpIsolationError(
            "imaj sabitlemesi tutmuyor (imaj değişmiş). Güveniyorsan yeniden hazırla: "
            f"usta mcp prepare {srv.name}"
        )
    if not srv.pin_image:
        notes.append(f"'{srv.name}': imaj sabitlenmemiş (usta mcp prepare {srv.name})")
    return notes


def start(
    srv: mcpconfig.Server,
    *,
    home: Path,
    env: Mapping[str, str],
    workspace: Path | None,
    timeout: float,
    on_event: Callable[[str, dict], None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Handle:
    """Sunucuyu konteynerde başlatır, el sıkışmayı yapar. Başarısızlıkta hiçbir şey çalışır halde kalmaz."""
    emit = on_event or (lambda *_: None)
    problem = docker_problem()
    if problem:
        emit("mcp_blocked", {"server": srv.name, "reason": problem})
        raise McpIsolationError(
            f"{problem}: izole MCP başlatılamaz (ana makineye geri düşülmez; ana makinede "
            "çalıştırmak için açıkça: usta mcp add --isolation host --i-understand-host-risk)"
        )
    try:
        notes = _verify_pins(Path(home), srv)
    except McpIsolationError as e:
        emit("mcp_blocked", {"server": srv.name, "reason": str(e)})
        raise
    cache = cache_path(Path(home), srv.name)
    scratch: Path | None = None
    if srv.pin_cache and not cache.is_dir():
        reason = f"sabitlenmiş paket önbelleği yok. Yeniden hazırla: usta mcp prepare {srv.name}"
        emit("mcp_blocked", {"server": srv.name, "reason": reason})
        raise McpIsolationError(reason)
    if cache.is_dir():
        # npm, ağ kapalıyken bile önbelleğe yazmak ister (`:ro` bağlamada ENOTCACHED verir). Sabitlenmiş önbelleğin
        # bu çalıştırmaya özel bir kopyası yazılabilir bağlanır; kopyanın özeti doğrulanır (TOCTOU yok) ve
        # kapanışta silinir. Asıl önbellek sunucu tarafından değiştirilemez.
        scratch = Path(tempfile.mkdtemp(prefix="usta-mcp-cache-"))
        copy = scratch / "c"
        shutil.copytree(cache, copy, symlinks=True)
        if srv.pin_cache and cache_digest(copy) != srv.pin_cache:
            shutil.rmtree(scratch, ignore_errors=True)
            reason = f"paket önbelleği sabitlemesi tutmuyor. Yeniden hazırla: usta mcp prepare {srv.name}"
            emit("mcp_blocked", {"server": srv.name, "reason": reason})
            raise McpIsolationError(reason)
        cache = copy
    name = f"usta-mcp-{uuid.uuid4().hex[:12]}"
    net: ProxyNetwork | None = None
    if srv.allow_hosts:
        net = ProxyNetwork(
            SandboxConfig(workdir=Path(workspace or home), allowed_hosts=srv.allow_hosts)
        )
        try:
            net.__enter__()
        except SandboxError as e:
            raise McpIsolationError(f"ağ allowlist proxy'si başlamadı: {e}") from None
    try:
        args = build_run_args(
            srv,
            name=name,
            network=net.network if net else None,
            workspace=workspace,
            cache=cache if scratch is not None else None,
            cache_rw=True,
            secret_names=tuple(env),
            extra_env=net.env if net else None,
        )
    except McpIsolationError as e:
        if net:
            net.__exit__(None, None, None)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        emit("mcp_blocked", {"server": srv.name, "reason": str(e)})
        raise
    client_env = {k: os.environ[k] for k in DOCKER_CLIENT_ENV if k in os.environ} | dict(env)
    client = McpClient(args, client_env, timeout=timeout, on_close=lambda: _rm(name))
    handle = Handle(client, name, net, notes, scratch=scratch)
    try:
        client.start()
    except McpError:
        handle.close()
        raise
    emit(
        "mcp_start",
        {
            "server": srv.name,
            "isolation": "container",
            "image": srv.image,
            "network": list(srv.allow_hosts) or "none",
            "workspace": srv.workspace,
            "limits": {"memory": srv.memory, "cpus": srv.cpus, "pids": srv.pids},
            "pinned": bool(srv.pin_image and srv.pin_cache),
        },
    )
    return handle


def prepare(
    srv: mcpconfig.Server,
    *,
    home: Path,
    env: Mapping[str, str],
    timeout: float = 600.0,
    cancel: threading.Event | None = None,
) -> tuple[str, str]:
    """Paketleri ağ allowlist'i (yalnız paket kayıtları) altında önbelleğe indirir; (imaj kimliği, özet)."""
    problem = docker_problem()
    if problem:
        raise McpIsolationError(f"{problem}: sunucu hazırlanamaz")
    if not srv.image:
        raise McpIsolationError(_no_image_msg(srv.name))
    iid = image_id(srv.image)
    if iid is None:
        raise McpIsolationError(
            f"imaj yerelde yok: {srv.image} (docker pull {srv.image}; Usta kendiliğinden çekmez)"
        )
    cache = cache_path(Path(home), srv.name)
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(parents=True, mode=0o700)
    os.chmod(cache.parent, 0o700)
    # hazırlık kipi: çevrimiçi (allowlist proxy), kurulum betikleri kapalı, önbellek yazılabilir
    offline_off = {
        "npm_config_offline": "false",
        "UV_OFFLINE": "0",
        "PIP_NO_INDEX": "0",
    }
    name = f"usta-mcp-prep-{uuid.uuid4().hex[:10]}"
    prep_srv = mcpconfig.Server(
        srv.name,
        srv.command,
        srv.env,
        srv.approve,
        True,
        isolation="container",
        image=srv.image,
        allow_hosts=PREPARE_HOSTS,
        workspace="none",
        memory=srv.memory,
        cpus=srv.cpus,
        pids=srv.pids,
    )
    with ProxyNetwork(SandboxConfig(workdir=cache, allowed_hosts=PREPARE_HOSTS)) as net:
        args = build_run_args(
            prep_srv,
            name=name,
            network=net.network,
            cache=None,
            secret_names=(),
            extra_env={**net.env, **offline_off},
            interactive=False,
        )
        # önbelleği yazılabilir bağla (çalışma anında salt okunur)
        i = args.index("--tmpfs")
        args[i:i] = ["-v", f"{cache.resolve()}:/cache:rw"]
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if (cancel is not None and cancel.is_set()) or time.monotonic() > deadline:
                _rm(name)
                proc.wait(timeout=10)
                raise McpIsolationError("hazırlık zaman aşımına uğradı ya da iptal edildi")
            time.sleep(0.2)
        _rm(name)
    digest = cache_digest(cache)
    if not any(cache.rglob("*")):
        raise McpIsolationError(
            "hazırlık hiçbir paket indirmedi (komut paket önbelleği kullanmıyor olabilir)"
        )
    return iid, digest
