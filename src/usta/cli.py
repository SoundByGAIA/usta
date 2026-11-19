"""Komut satırı istemcisi: `usta run "görev" -w ÇALIŞMA_ALANI`."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from usta import (
    capability,
    cli_audit,
    cli_chat,
    cli_mcp,
    cli_olcum,
    cli_parser,
    compat,
    mcpconfig,
    memory,
    ortak,
    profile,
    projects,
    skillprobe,
    symbols,
    thinking,
)
from usta.agent import Agent
from usta.api import create_app, load_or_create_token
from usta.audit import AuditLog
from usta.jsonproto import JsonProtocolClient
from usta.mcp_tools import McpSession
from usta.modelinfo import detect_size_b
from usta.models import ModelClient, ModelError, OpenAICompatClient
from usta.policy import Policy
from usta.proxy import validate_allowed_host
from usta.sandbox import cleanup_orphans
from usta.tasks import TaskManager
from usta.textproto import TextProtocolClient
from usta.tools import ToolContext, build_registry
from usta.workspace import find_protected, remove_new_protected

DEFAULT_ENDPOINT = "http://localhost:11434/v1"  # Ollama
PROTOCOLS = ("native", "json", "text")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _home() -> Path:
    home = Path(os.environ.get("USTA_HOME") or Path.home() / ".usta")
    with contextlib.suppress(OSError):  # yalnız sahibi okuyabilsin (jeton, anahtarlar, oturumlar)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if compat.owns(home):
            os.chmod(home, 0o700)
    return home


_ENV_KEY: object = (
    object()
)  # api_key verilmediyse USTA_API_KEY; kayıtlı API'ler ortam anahtarını görmez


def _build_model(
    endpoint: str,
    name: str,
    protocol: str,
    timeout: float = 120.0,
    extra_body: dict | None = None,
    api_key: object = _ENV_KEY,
) -> ModelClient:
    client: ModelClient = OpenAICompatClient(
        endpoint,
        name,
        api_key=os.environ.get("USTA_API_KEY") if api_key is _ENV_KEY else api_key,  # type: ignore[arg-type]
        timeout=timeout,
        extra_body=extra_body,
    )
    if protocol == "text":
        return TextProtocolClient(client)
    if protocol == "json":
        return JsonProtocolClient(client)
    return client


def _extra_body(args: argparse.Namespace) -> dict | None:
    """--extra-body JSON nesnesi (ör. düşünmeyi kapatma); bozuksa None ve hata mesajı."""
    raw = getattr(args, "extra_body", None)
    if not raw:
        return thinking.extra_for(getattr(args, "think", None) or "auto")
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        print("hata: --extra-body bir JSON nesnesi olmalı", file=sys.stderr)
        return None
    if "think" in data:
        # Ollama'nın OpenAI-uyumlu ucu bu alanı sessizce yok sayar; düşünmeyi kapatan reasoning_effort'tur
        print(
            'uyarı: "think" alanını OpenAI-uyumlu uçlar yok sayabilir; düşünmeyi kapatmak için --think off kullan',
            file=sys.stderr,
        )
    return {**thinking.extra_for(getattr(args, "think", None) or "auto"), **data}


def _make_model(args: argparse.Namespace) -> ModelClient | None:
    name = args.model or os.environ.get("USTA_MODEL")
    if not name:
        print("hata: model belirtilmedi (--model veya USTA_MODEL)", file=sys.stderr)
        return None
    protocol = args.protocol or os.environ.get("USTA_PROTOCOL") or "native"
    if protocol not in (*PROTOCOLS, "auto"):
        print(f"hata: protokol native|json|text|auto olmalı: {protocol}", file=sys.stderr)
        return None
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or DEFAULT_ENDPOINT
    extra = _extra_body(args)
    if extra is None:
        return None
    if protocol == "auto":
        # Profil koşu başında BİR KEZ çözülür ve sabitlenir (rapora çözülmüş protokol yazılır); koşu sırasında değişmez.
        try:
            prof = profile.resolve_protocol(
                _home(),
                endpoint,
                name,
                lambda: _build_model(endpoint, name, "native", args.model_timeout, extra),
                revision=capability.detect_revision(endpoint, name)
                if (_home() / "capabilities.json").exists()
                else "",
                config=_capability_config(args, extra),
            )
        except profile.ProfileError as e:
            print(f"hata: {e}", file=sys.stderr)
            return None
        protocol = prof.protocol
        args.protocol = protocol
        print(f"Protokol (otomatik, sabitlendi): {protocol} — {prof.note}", flush=True)
    return _build_model(endpoint, name, protocol, args.model_timeout, extra)


def _capability_config(args: argparse.Namespace, extra: dict | None) -> dict:
    """Profili geçersiz kılan sunucu/istek yapılandırması: bağlam penceresi + ek gövde alanları."""
    return {
        "context_window": getattr(args, "context_window", None) or None,
        "extra_body": extra or {},
    }


def _strong_model(args: argparse.Namespace) -> ModelClient:
    key = os.environ.get(args.strong_api_key_env) if args.strong_api_key_env else _ENV_KEY
    return _build_model(
        args.strong_endpoint
        or args.endpoint
        or os.environ.get("USTA_ENDPOINT")
        or DEFAULT_ENDPOINT,
        args.strong_model,
        args.strong_protocol or args.protocol or os.environ.get("USTA_PROTOCOL") or "native",
        args.model_timeout,
        api_key=key,
    )


def _taint_gate(args: argparse.Namespace) -> bool:
    """Kaynak izi kapısı: varsayılan açık; --no-taint-gate ya da USTA_TAINT_GATE=0 kapatır."""
    flag = getattr(args, "taint_gate", None)
    if flag is not None:
        return bool(flag)
    return os.environ.get("USTA_TAINT_GATE") != "0"


def _site_level(args: argparse.Namespace, model: ModelClient) -> int:
    """Bölüm bölüm site kurmada iş ne kadar küçük parçalara bölünsün (DENEYSEL). USTA_SITE_LEVEL=1|2|3 sabitler;
    verilmezse modelin beceri profili kullanılır, yoksa kısa beceri testi yapılıp saklanır (skillprobe.py)."""
    fixed = os.environ.get("USTA_SITE_LEVEL", "")
    if fixed in ("1", "2", "3"):
        return int(fixed)
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or DEFAULT_ENDPOINT
    name = args.model or os.environ.get("USTA_MODEL") or ""
    revision = capability.detect_revision(endpoint, name)
    prof = skillprobe.load(_home(), endpoint, name, revision)
    if prof is None:
        print(
            "Usta bu modeli ilk kez site işinde kullanıyor: kısa beceri testi yapılıyor…",
            file=sys.stderr,
        )
        prof = skillprobe.probe(model, detect_size_b(endpoint, name), revision)
        skillprobe.save(_home(), endpoint, name, prof)
    print(
        f"beceri seviyesi: {prof.level} ({', '.join(k for k, v in prof.passed.items() if v) or 'hiçbiri'} geçti)",
        file=sys.stderr,
    )
    return prof.level


def _finish_check(args: argparse.Namespace) -> bool:
    """Söz–eylem denetimi: varsayılan açık (ölçüm: docs/olcumler/soz-eylem.md); --no-finish-check ya da USTA_FINISH_CHECK=0."""
    flag = getattr(args, "finish_check", None)
    if flag is not None:
        return bool(flag)
    return os.environ.get("USTA_FINISH_CHECK") != "0"


def _symbol_tools(args: argparse.Namespace) -> bool:
    """Deneysel sembol araçları: bayrak ya da USTA_SYMBOL_TOOLS=1. Paket yoksa kapalı kalır ve söyler."""
    on = bool(getattr(args, "symbol_tools", False)) or os.environ.get("USTA_SYMBOL_TOOLS") == "1"
    if on and not symbols.available():
        print(
            "uyarı: sembol araçları için `pip install 'usta[symbols]'` gerekli; kapalı.",
            file=sys.stderr,
        )
        return False
    return on


def _allowed_hosts(args: argparse.Namespace) -> tuple[str, ...] | None:
    raw = [h for h in os.environ.get("USTA_ALLOW_HOSTS", "").split(",") if h.strip()]
    raw += args.allow_host or []
    try:
        return tuple(dict.fromkeys(validate_allowed_host(h) for h in raw))
    except ValueError as e:
        print(f"hata: --allow-host / USTA_ALLOW_HOSTS: {e}", file=sys.stderr)
        return None


def _serve(app, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _approver(tool: str, args: dict) -> bool:
    if not compat.is_tty():
        return False
    return input(f"onay: {tool} {args} — izin verilsin mi? [e/H] ").strip().lower() in {"e", "y"}


def _mcp_servers(home: Path) -> list[mcpconfig.Server] | None:
    try:
        return list(mcpconfig.load(home).values())
    except mcpconfig.McpConfigError as e:
        print(f"hata: MCP yapılandırması: {e}", file=sys.stderr)
        return None


def _serve_cmd(args: argparse.Namespace) -> int:
    if args.host not in LOOPBACK and not args.allow_remote:
        print("hata: loopback dışında dinlemek için --allow-remote gerekir", file=sys.stderr)
        return 2
    model = _make_model(args)
    hosts = _allowed_hosts(args)
    if model is None or hosts is None:
        return 2
    try:
        cleanup_orphans()
    except OSError:  # docker yok
        pass
    home = _home()
    servers = _mcp_servers(home)
    if servers is None:
        return 2
    token = load_or_create_token(home)
    manager = TaskManager(
        lambda: model,
        home=home,
        max_steps=args.max_steps,
        allowed_hosts=hosts,
        symbol_tools=_symbol_tools(args),
        taint_gate=_taint_gate(args),
        finish_check=_finish_check(args),
        mcp_servers=lambda: (
            _mcp_servers(home) or []
        ),  # panelden eklenenler yeniden başlatmadan gelir
    )
    print(f"Usta API: http://{args.host}:{args.port}  jeton dosyası: {home / 'token'}", flush=True)
    app = create_app(manager, home, token)
    app.state.ortak_host.start_if_enabled()  # portaldaki gibi: ev sahibiyse bağlı bilgisayarlar ulaşabilsin
    _serve(app, args.host, args.port)
    return 0


def _shortcut_cmd() -> int:
    try:
        path = compat.create_desktop_shortcut()
    except OSError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f'Masaüstüne "Usta" simgesi koydum: {path}\nBundan sonra o simgeye çift tıklaman yeter.')
    return 0


def _crash(exc: BaseException) -> int:
    """Beklenmeyen hata: ham Python çıktısı yerine kısa açıklama + gizli bilgi içermeyen rapor dosyası."""
    import platform
    import traceback
    from datetime import datetime
    from importlib import metadata

    from usta.audit import mask

    try:
        ver = metadata.version("usta")
    except metadata.PackageNotFoundError:
        ver = "?"
    tb = mask("".join(traceback.format_exception(exc)))
    report = (
        f"Usta hata raporu ({datetime.now():%Y-%m-%d %H:%M:%S})\n"
        f"sürüm: {ver} | Python {platform.python_version()} | {platform.platform()}\n"
        "(Bu dosyada anahtar ya da şifre yoktur; yine de göndermeden önce gözden geçirebilirsin.)\n\n"
        f"{tb}"
    )
    where = ""
    try:
        d = _home()
        path = d / f"rapor-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.write_text(report, encoding="utf-8")
        where = str(path)
    except OSError:
        pass
    if isinstance(exc, PermissionError) and ".usta" in str(getattr(exc, "filename", "") or exc):
        print(
            'Usta kendi klasörüne (.usta) erişemedi. Usta\'yı daha önce "yönetici olarak" açtıysan bu klasör '
            "yönetici adına oluşmuş olabilir.\nÇözüm: Dosya Gezgini'nde kullanıcı klasöründeki `.usta` klasörünü "
            "sil ve Usta'yı normal şekilde yeniden başlat.",
            file=sys.stderr,
        )
    else:
        print(
            f"Beklenmeyen bir sorun oldu: {type(exc).__name__}. Üzgünüm.\n"
            + (
                f"Rapor dosyası hazırladım: {where}\nBu dosyayı bana gönder, bakayım."
                if where
                else report[-400:]
            ),
            file=sys.stderr,
        )
    return 1


def main(argv: list[str] | None = None) -> int:
    compat.utf8_console()
    if not compat.enable_ansi():  # renk kodları çözülemiyorsa düz yazı
        os.environ.setdefault("NO_COLOR", "1")
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nÇıkılıyor.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 - kullanıcıya ham iz yerine açıklama
        return _crash(e)


def _main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if (
        argv[:2] in (["mcp", "add"], ["verify", "set"]) and "--" in argv
    ):  # `--` sonrası sunucu komutudur
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    args = cli_parser.build().parse_args(argv)
    if args.cmd is None and getattr(args, "shortcut", False):
        return _shortcut_cmd()
    if args.cmd is None:
        return cli_chat.chat_cmd(args)
    if args.cmd == "mcp":
        return cli_mcp.mcp_cmd(args, command)
    if args.cmd == "audit":
        return cli_audit.audit_cmd(args, _home())
    if args.cmd == "sandbox":
        return cli_mcp.sandbox_cmd(args)
    if args.cmd == "lab":
        return cli_olcum.lab_cmd(args)
    if args.cmd == "bench":
        return cli_olcum.bench_cmd(args)
    if args.cmd == "probe":
        return cli_olcum.probe_cmd(args)
    if args.cmd == "verify":
        return cli_olcum.verify_cmd(args, command)
    if args.cmd == "serve":
        return _serve_cmd(args)
    model = _make_model(args)
    hosts = _allowed_hosts(args)
    if model is None or hosts is None:
        return 2
    root = Path(args.workspace).resolve()
    if not root.is_dir():
        print(f"hata: çalışma alanı yok: {root}", file=sys.stderr)
        return 2
    try:
        projects.check_root(_home(), root)
    except ValueError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    servers = _mcp_servers(_home())
    if servers is None:
        return 2
    # Denetim kaydı çalışma alanının dışında: sandbox içindeki komutlar ona yazamaz.
    audit = AuditLog(
        _home() / "audit" / f"{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.jsonl"
    )
    audit.record("mode", mode="manual")  # komut satırında her onay sorulur
    with McpSession(
        servers, _home(), workspace=root, on_event=lambda k, d: audit.record(k, **d)
    ) as mcp:
        for warning in mcp.warnings:
            print(f"uyarı: {warning}", file=sys.stderr)
        agent = Agent(
            model,
            build_registry(
                ToolContext(root=root, allowed_hosts=hosts, symbol_tools=_symbol_tools(args)),
                extra=mcp.tools,
            ),
            Policy(root, set(hosts), mcp_modes=mcp.modes),
            audit,
            approver=_approver,
            max_steps=args.max_steps,
            memory_context="\n\n".join(
                c for c in (ortak.context(_home()), memory.render_context(root)) if c
            ),
            taint=_taint_gate(args),
            finish_check=_finish_check(args),
            # deneysel ayarlar (docs/ayarlar.md)
            workspace_hint=os.environ.get("USTA_WORKSPACE_HINT") == "1",
            site_steps=os.environ.get("USTA_SITE_STEPS") == "1",
            site_level=_site_level(args, model) if os.environ.get("USTA_SITE_STEPS") == "1" else 2,
        )
        protected = find_protected(root)
        try:
            result = agent.run(args.prompt)
        except ModelError as e:
            print(f"hata: {e}", file=sys.stderr)
            return 1
        finally:
            # portaldaki gibi: görevde oluşturulan .git/çıplak depo (hook/config ile ana makinede kod çalıştırma
            # yolu) çalışma alanından karantinaya alınır
            quarantine = _home() / "quarantine" / f"run-{time.strftime('%Y%m%d-%H%M%S')}"
            gone = remove_new_protected(root, protected, quarantine)
            if gone:
                audit.record("protected_quarantined", paths=gone)
                print(
                    f"uyarı: görevde oluşturulan {', '.join(gone[:5])} karantinaya alındı ({quarantine})",
                    file=sys.stderr,
                )
    print(result.answer)
    return 1 if result.truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())
