"""Komut satırı istemcisi: `usta run "görev" -w ÇALIŞMA_ALANI`."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import functools
import getpass
import hashlib
import json
import os
import sys
import webbrowser
from pathlib import Path

import httpx

from usta import apis, bench, mcpconfig, memory, profile, projectcfg, projects, settings, theme
from usta.agent import Agent
from usta.api import create_app, load_or_create_token
from usta.audit import AuditLog
from usta.jsonproto import JsonProtocolClient
from usta.mcp import McpClient, McpError
from usta.mcp_tools import McpSession
from usta.modelctl import ModelControl
from usta.models import ModelClient, ModelError, OpenAICompatClient
from usta.policy import Policy
from usta.portal import Portal
from usta.proxy import validate_allowed_host
from usta.repl import MODE_ALIASES, Repl
from usta.sandbox import cleanup_orphans
from usta.tasks import TaskManager
from usta.textproto import TextProtocolClient
from usta.tools import ToolContext, build_registry

DEFAULT_ENDPOINT = "http://localhost:11434/v1"  # Ollama
PROTOCOLS = ("native", "json", "text")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _home() -> Path:
    home = Path(os.environ.get("USTA_HOME") or Path.home() / ".usta")
    with contextlib.suppress(OSError):  # yalnız sahibi okuyabilsin (jeton, anahtarlar, oturumlar)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if home.stat().st_uid == os.getuid():
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
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        print("hata: --extra-body bir JSON nesnesi olmalı", file=sys.stderr)
        return None
    return data


def _make_model(args: argparse.Namespace) -> ModelClient | None:
    name = args.model or os.environ.get("USTA_MODEL")
    if not name:
        print("hata: model belirtilmedi (--model veya USTA_MODEL)", file=sys.stderr)
        return None
    protocol = args.protocol or os.environ.get("USTA_PROTOCOL") or "native"
    if protocol not in PROTOCOLS:
        print(f"hata: protokol native|json|text olmalı: {protocol}", file=sys.stderr)
        return None
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or DEFAULT_ENDPOINT
    extra = _extra_body(args)
    if extra is None:
        return None
    return _build_model(endpoint, name, protocol, args.model_timeout, extra)


def _add_model_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--endpoint", help=f"OpenAI-uyumlu uç nokta (USTA_ENDPOINT; varsayılan {DEFAULT_ENDPOINT})"
    )
    p.add_argument("--model", help="model adı (USTA_MODEL)")
    p.add_argument(
        "--extra-body",
        help='isteğe eklenecek JSON alanları, ör. \'{"chat_template_kwargs": {"enable_thinking": false}}\'',
    )
    p.add_argument(
        "--model-timeout",
        type=float,
        default=120.0,
        help="tek model isteği için saniye (yavaş yerel modellerde artır)",
    )
    p.add_argument(
        "--allow-host",
        action="append",
        help="sandbox'ın proxy ile erişebileceği alan adı; tekrarlanabilir, *.örnek.com olabilir "
        "(USTA_ALLOW_HOSTS, virgüllü). Varsayılan: ağ kapalı",
    )
    p.add_argument(
        "--protocol",
        choices=PROTOCOLS,
        help="native: yerel araç çağrısı; json: şemayla kısıtlı JSON; text: JSON-metin yedek protokolü (USTA_PROTOCOL)",
    )


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
    if not sys.stdin.isatty():
        return False
    return input(f"onay: {tool} {args} — izin verilsin mi? [e/H] ").strip().lower() in {"e", "y"}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="usta",
        description="Argümansız `usta`: etkileşimli terminal + web portalı. Alt komutlar aşağıda.",
    )
    p.add_argument(
        "-w", "--workspace", default=".", help="proje dizini (varsayılan: bulunduğun dizin)"
    )
    p.add_argument("--no-portal", action="store_true", help="web portalını başlatma")
    p.add_argument("--no-browser", action="store_true", help="portalı başlat ama tarayıcıyı açma")
    p.add_argument("--port", type=int, help="portal portu (varsayılan 8765, doluysa boş bir port)")
    p.add_argument("--mode", help="başlangıç modu: manuel | oto | plan")
    p.add_argument("--theme", help="renk teması: beyaz | gri | siyah")
    p.add_argument("--context-window", type=int, help="modelin bağlam penceresi (token)")
    p.add_argument("--guard", action="store_true", help="koruma: doğrulama kapısı + devre kesici")
    _add_model_args(p)
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="bir görevi çalıştır")
    r.add_argument("prompt")
    r.add_argument("-w", "--workspace", default=".", help="çalışma alanı dizini")
    _add_model_args(r)
    r.add_argument("--max-steps", type=int, default=20)
    sv = sub.add_parser("serve", help="HTTP API sunucusunu başlat")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument(
        "--allow-remote", action="store_true", help="loopback dışında dinlemeye izin ver"
    )
    sv.add_argument("--max-steps", type=int, default=20)
    sv.add_argument("--guard", action="store_true", help="görevlerde varsayılan olarak koruma aç")
    sv.add_argument(
        "--context-window",
        type=int,
        help="modelin bağlam penceresi (token); arayüzde doluluk göstergesi için (ör. 8192)",
    )
    _add_model_args(sv)
    bn = sub.add_parser(
        "bench", help="modeli küçük yazılım görevlerinde ölç (harness değerlendirmesi)"
    )
    bs = bn.add_subparsers(dest="bench_cmd", required=True)
    bs.add_parser("list", help="ölçüm görevlerini listele")
    bc = bs.add_parser(
        "compare", help="rapor dosyalarını katman (zayıf/orta/büyük) başına karşılaştır"
    )
    bc.add_argument("pairs", nargs="+", metavar="KATMAN=RAPOR.json")
    bc.add_argument("--out", help="Markdown çıktı dosyası")
    br = bs.add_parser("run", help="görevleri modelle çalıştır, gizli testle doğrula")
    br.add_argument("--task", action="append", help="yalnız bu görev(ler); tekrarlanabilir")
    br.add_argument("--repeat", type=int, default=1, help="her görevi kaç kez dene")
    br.add_argument("--max-steps", type=int, default=30)
    br.add_argument("--time-limit", type=float, default=600.0, help="görev başına saniye")
    br.add_argument("--out", help="JSON rapor dosyası")
    br.add_argument(
        "--arm", choices=sorted(bench.ARMS), default="B", help="deney kolu (A: minimal, B: Usta)"
    )
    br.add_argument(
        "--stop-file",
        help="bu dosya var olursa ölçüm geçerli koşudan sonra durur (paylaşılan sunucuyu korumak için)",
    )
    br.add_argument("--infra-retries", type=int, default=2, help="altyapı hatasında yeniden deneme")
    br.add_argument(
        "--shrink-writes",
        type=int,
        metavar="N",
        help="deney: son N dosya yazması tam kalır, eskilerin içeriği bağlamdan atılır",
    )
    _add_model_args(br)
    mcp = sub.add_parser("mcp", help="MCP sunucularını yönet (arama, takvim vb. ek araçlar)")
    vf = sub.add_parser(
        "verify", help="projeye özel doğrulama komutu (çalışma alanı dışında saklanır)"
    )
    vs = vf.add_subparsers(dest="verify_cmd", required=True)
    vset = vs.add_parser("set", help="usta verify set [--image İMAJ] -- KOMUT [ARG...]")
    vset.add_argument("--image", help="sandbox imajı (yerelde çekilmiş olmalı)")
    vs.add_parser("show", help="geçerli ayarı göster")
    vs.add_parser("clear", help="ayarı sil (otomatik keşif)")
    for v in vs.choices.values():
        v.add_argument("-w", "--workspace", default=".", help="proje dizini")
    pr = sub.add_parser("probe", help="modelin araç çağrısı yeteneğini ölç ve önbelleğe al")
    pr.add_argument("--refresh", action="store_true", help="önbelleği yok say, yeniden ölç")
    _add_model_args(pr)
    ms = mcp.add_subparsers(dest="mcp_cmd", required=True)
    add = ms.add_parser("add", help="sunucu ekle: usta mcp add AD [seçenekler] -- KOMUT [ARG...]")
    add.add_argument("name")
    add.add_argument("--env", action="append", default=[], help="sunucunun istediği anahtar adı")
    add.add_argument(
        "--approve", choices=mcpconfig.APPROVE_MODES, default="ask", help="ask: her çağrıda sor"
    )
    add.add_argument("--yes", action="store_true", help="onay sormadan ekle")
    add.add_argument("--replace", action="store_true", help="aynı adlıyı değiştir")
    ms.add_parser("list", help="ekli sunucuları göster")
    for name, text in (
        ("test", "sunucuyu başlat ve araçlarını listele"),
        ("remove", "sunucuyu ve anahtarlarını sil"),
        ("enable", "sunucuyu aç"),
        ("disable", "sunucuyu kapat (silmeden)"),
    ):
        ms.add_parser(name, help=text).add_argument("name")
    return p


def _mcp_servers(home: Path) -> list[mcpconfig.Server] | None:
    try:
        return list(mcpconfig.load(home).values())
    except mcpconfig.McpConfigError as e:
        print(f"hata: MCP yapılandırması: {e}", file=sys.stderr)
        return None


def _mcp_add(args: argparse.Namespace, command: list[str], home: Path) -> int:
    if not command:
        print("hata: komut eksik. Örnek: usta mcp add arama -- npx -y paket-adi", file=sys.stderr)
        return 2
    try:
        mcpconfig.validate(args.name, command, args.env, args.approve)
        if args.name in mcpconfig.load(home) and not args.replace:
            raise mcpconfig.McpConfigError(f"'{args.name}' zaten var (değiştirmek için --replace)")
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    interactive = sys.stdin.isatty()
    print(
        f"Bu komut bilgisayarında SENİN yetkilerinle çalışacak:\n  {' '.join(command)}\n"
        "Yalnız güvendiğin kaynaklardan ekle. "
        + (
            "Araçları her çağrıda onayına sunulur (onay: ask)."
            if args.approve == "ask"
            else "Araçları SORMADAN çalışır (onay: allow)."
        )
    )
    if not args.yes:
        if not interactive:
            print("hata: etkileşimli değil; onaylamak için --yes ekle", file=sys.stderr)
            return 1
        if input("Eklensin mi? [e/H] ").strip().lower() not in {"e", "y"}:
            print("iptal edildi")
            return 1
    try:
        mcpconfig.add_server(home, args.name, command, args.env, args.approve, args.replace)
        for key in args.env:
            if os.environ.get(key):
                print(f"{key}: ortam değişkeninden alınacak (dosyaya yazılmaz)")
            elif interactive:
                value = getpass.getpass(
                    f"{key} değeri (ekranda görünmez; boş bırakırsan sonra verirsin): "
                )
                if value.strip():
                    mcpconfig.set_secret(home, args.name, key, value.strip())
                    print(f"{key}: kaydedildi (yalnız sana okunur dosyada)")
            else:
                print(f"{key}: tanımlı değil. Sunucuyu başlatmadan önce `export {key}=...` yap.")
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f"Eklendi: {args.name}. Denemek için: usta mcp test {args.name}")
    return 0


def _mcp_list(home: Path) -> int:
    servers = _mcp_servers(home)
    if servers is None:
        return 2
    if not servers:
        print("Ekli MCP sunucusu yok. Eklemek için: usta mcp add AD -- KOMUT")
        return 0
    for s in servers:
        env = mcpconfig.resolve_env(home, s, os.environ)
        keys = ", ".join(f"{k}({'tanımlı' if k in env else 'EKSİK'})" for k in s.env)
        print(
            f"{s.name}  [{'açık' if s.enabled else 'kapalı'}]  onay: {s.approve}  "
            f"{' '.join(s.command)}" + (f"  env: {keys}" if keys else "")
        )
    return 0


def _mcp_test(name: str, home: Path) -> int:
    servers = _mcp_servers(home)
    if servers is None:
        return 2
    server = next((s for s in servers if s.name == name), None)
    if server is None:
        print(f"hata: '{name}' yok. Ekli olanlar için: usta mcp list", file=sys.stderr)
        return 2
    env = mcpconfig.resolve_env(home, server, os.environ)
    print(f"'{name}' başlatılıyor (ilk seferde paket indirilebilir, bir dakika sürebilir)...")
    try:
        with McpClient(list(server.command), env, timeout=90) as client:
            tools = client.list_tools()
    except McpError as e:
        hint = (
            "\nKomutun kurulu olduğundan emin ol (ör. npx için Node.js)."
            if "bulunamadı" in str(e)
            else ""
        )
        print(f"hata: '{name}' başlatılamadı: {e}{hint}", file=sys.stderr)
        return 1
    print(f"{name}: {len(tools)} araç bulundu")
    for t in tools:
        print(f"- {t.name}: {t.description[:100]}")
    return 0


def _bench_compare(args: argparse.Namespace) -> int:
    tiers: dict[str, list[Path]] = {}
    for pair in args.pairs:
        tier, sep, path = pair.partition("=")
        if not sep or not tier.strip() or not path.strip():
            print(f"hata: KATMAN=RAPOR.json biçimi bekleniyor: {pair!r}", file=sys.stderr)
            return 2
        tiers.setdefault(tier.strip(), []).append(Path(path.strip()))
    try:
        md = bench.compare_markdown(tiers)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"hata: rapor okunamadı: {e}", file=sys.stderr)
        return 2
    print(md, end="")
    if args.out:
        Path(args.out).write_text(md)
    return 0


def _bench_cmd(args: argparse.Namespace) -> int:
    if args.bench_cmd == "compare":
        return _bench_compare(args)
    tasks = bench.load_tasks()
    if args.bench_cmd == "list":
        for t in tasks:
            print(f"{t.id}: {t.prompt[:90]}")
        return 0
    if args.task:
        unknown = sorted(set(args.task) - {t.id for t in tasks})
        if unknown:
            print(
                f"hata: bilinmeyen görev: {', '.join(unknown)} (liste: usta bench list)",
                file=sys.stderr,
            )
            return 2
        tasks = [t for t in tasks if t.id in args.task]
    model = _make_model(args)
    if model is None:
        return 2
    name = args.model or os.environ.get("USTA_MODEL") or "?"
    protocol = args.protocol or os.environ.get("USTA_PROTOCOL") or "native"
    print(
        f"Model: {name} ({protocol}); kol {args.arm}: {bench.ARMS[args.arm].description}; "
        f"{len(tasks)} görev x {args.repeat}",
        flush=True,
    )

    def show(r: bench.TaskResult) -> None:
        mark = {"pass": "GEÇTİ ", "fail": "KALDI ", "infra": "ALTYAPI"}[r.outcome]
        extra = f"  [{r.error}]" if r.error else "  [adım sınırı]" if r.truncated else ""
        flags = ("  !kanıtsız" if r.unverified_claim else "") + (
            "  !test-değişti" if r.tests_modified else ""
        )
        print(
            f"{mark} {r.task}: {r.steps} adım, {r.tool_calls} çağrı ({r.tool_errors} hata), "
            f"{r.prompt_tokens + r.completion_tokens} token, {r.seconds:g} sn{extra}{flags}",
            flush=True,
        )

    results = bench.run_bench(
        lambda: model,
        tasks,
        repeat=args.repeat,
        max_steps=args.max_steps,
        time_limit=args.time_limit,
        infra_retries=args.infra_retries,
        arm=bench.ARMS[args.arm],
        agent_factory=functools.partial(Agent, shrink_writes=args.shrink_writes),
        on_result=show,
        should_stop=(lambda: Path(args.stop_file).exists()) if args.stop_file else None,
    )
    if args.stop_file and Path(args.stop_file).exists():
        print(f"\nÖlçüm durduruldu ({args.stop_file} bulundu); {len(results)} koşu tamamlandı.")
    s = bench.summarize(results)
    solved = s["tokens_per_solved"]
    print(
        f"\nSonuç: {s['passed']}/{s['valid_runs']} geçti (%{s['pass_rate'] * 100:.0f}); "
        f"altyapı hatası (sayılmadı): {s['infra_errors']}\n"
        f"ort. {s['mean_steps']} adım, {s['mean_seconds']} sn, {s['mean_tokens']:g} token/görev, "
        f"çözülen başına {solved if solved is not None else '-'} token\n"
        f"araç hata oranı %{s['tool_error_rate'] * 100:.0f}, kanıtsız bildirim {s['unverified_claims']}, "
        f"'bitti' deyip kalan {s['claimed_but_failed']}, test dosyası değiştiren {s['tests_modified']}"
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                bench.report(name, protocol, results, args.arm), ensure_ascii=False, indent=2
            )
        )
        print(f"Rapor: {args.out}")
    return 0


def _mcp_cmd(args: argparse.Namespace, command: list[str]) -> int:
    home = _home()
    try:
        if args.mcp_cmd == "add":
            return _mcp_add(args, command, home)
        if args.mcp_cmd == "list":
            return _mcp_list(home)
        if args.mcp_cmd == "test":
            return _mcp_test(args.name, home)
        if args.mcp_cmd == "remove":
            mcpconfig.remove_server(home, args.name)
            print(f"silindi: {args.name}")
        else:
            mcpconfig.set_enabled(home, args.name, args.mcp_cmd == "enable")
            print(f"{args.name}: {'açıldı' if args.mcp_cmd == 'enable' else 'kapatıldı'}")
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    return 0


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
        mcp_servers=lambda: (
            _mcp_servers(home) or []
        ),  # panelden eklenenler yeniden başlatmadan gelir
    )
    print(f"Usta API: http://{args.host}:{args.port}  jeton dosyası: {home / 'token'}", flush=True)
    _serve(create_app(manager, home, token), args.host, args.port)
    return 0


def _open_browser(url: str) -> None:
    """Tarayıcıyı terminalden bağımsız açar: çıktısı/girdisi terminale karışmaz (istem donmaz)."""
    saved = []
    try:
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            saved.append((fd, os.dup(fd)))
            os.dup2(null, fd)
        os.close(null)
    except OSError:
        pass
    try:
        webbrowser.open(url)
    finally:
        for fd, copy in saved:
            os.dup2(copy, fd)
            os.close(copy)


def _discover_models(endpoint: str, key: str | None = None) -> list[str]:
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = httpx.get(endpoint.rstrip("/") + "/models", headers=headers, timeout=4)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", []) if isinstance(m.get("id"), str)]
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return []


def _pick_model(endpoint: str, home: Path, cur: settings.Settings) -> str | None:
    """İlk çalıştırma: uç noktadaki modelleri listeler, seçileni ayarlara kaydeder."""
    if not sys.stdin.isatty():
        print(
            "hata: model belirtilmedi (--model, USTA_MODEL ya da ~/.usta/config.json)",
            file=sys.stderr,
        )
        return None
    models = _discover_models(endpoint)
    if not models:
        print(
            f"hata: model uç noktasına ulaşılamadı: {endpoint}\n"
            "Ollama çalışıyor mu? (ollama serve). Ya da elle ver: usta --endpoint URL --model AD",
            file=sys.stderr,
        )
        return None
    print("Kullanılabilir modeller:")
    for i, m in enumerate(models, 1):
        print(f"  {i}) {m}")
    choice = input("Hangisini kullanayım? [numara] ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(models):
        print("hata: geçersiz seçim", file=sys.stderr)
        return None
    name = models[int(choice) - 1]
    try:
        settings.save(home, dataclasses.replace(cur, endpoint=endpoint, model=name))
    except OSError:
        pass  # kaydedilemese de bu oturumda kullanılır
    print(f"Seçildi: {name} (bir daha sorulmaz; değiştirmek için ~/.usta/config.json)")
    return name


def _setup_readline(home: Path):
    try:
        import readline
    except ImportError:  # Windows
        return None
    path = home / "repl_history"
    try:
        readline.read_history_file(path)
    except OSError:
        pass
    readline.set_history_length(500)
    return lambda: _save_history(readline, path)


def _save_history(readline, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        readline.write_history_file(path)
        path.chmod(0o600)
    except OSError:
        pass


def _verify_cmd(args: argparse.Namespace, command: list[str]) -> int:
    home, root = _home(), Path(args.workspace)
    if not root.is_dir():
        print(f"hata: çalışma alanı yok: {root}", file=sys.stderr)
        return 2
    try:
        if args.verify_cmd == "set":
            if not command:
                print("hata: komut eksik. Örnek: usta verify set -- pytest -q", file=sys.stderr)
                return 2
            projectcfg.set_verify(home, root, command, args.image)
            print(
                f"Doğrulama komutu ayarlandı: {' '.join(command)}"
                + (f" (imaj: {args.image})" if args.image else "")
            )
        elif args.verify_cmd == "clear":
            projectcfg.clear(home, root)
            print("Doğrulama ayarı silindi; otomatik keşif kullanılacak.")
        else:
            cfg = projectcfg.load(home, root)
            if cfg.verify:
                print(
                    f"komut: {' '.join(cfg.verify)}" + (f"\nimaj: {cfg.image}" if cfg.image else "")
                )
            else:
                print(
                    "Ayarlı komut yok; otomatik keşif kullanılır (test_*.py → python -m unittest)."
                )
    except projectcfg.ProjectConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    return 0


def _probe_cmd(args: argparse.Namespace) -> int:
    home = _home()
    cur = settings.load(home)
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or DEFAULT_ENDPOINT
    name = args.model or os.environ.get("USTA_MODEL") or cur.model
    if not name:
        print("hata: model belirtilmedi (--model veya USTA_MODEL)", file=sys.stderr)
        return 2
    make = lambda: _build_model(endpoint, name, "native", args.model_timeout)
    try:
        if args.refresh:
            prof = profile.probe(make(), name)
            profile.save(home, endpoint, name, prof)
        else:
            prof = profile.resolve_protocol(home, endpoint, name, make)
    except profile.ProfileError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f"{name}: protokol {prof.protocol} — {prof.note}")
    return 0


def _chat_cmd(args: argparse.Namespace) -> int:
    home = _home()
    cur = settings.load(home)
    try:
        if args.theme:
            cur = dataclasses.replace(cur, theme=theme.resolve(args.theme))
    except ValueError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    if args.guard:
        cur = dataclasses.replace(cur, guard=True)
    if args.mode:
        mode = MODE_ALIASES.get(args.mode.casefold())
        if mode is None:
            print(f"hata: geçersiz mod: {args.mode!r} (manuel, oto, plan)", file=sys.stderr)
            return 2
        cur = dataclasses.replace(cur, mode=mode)
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or DEFAULT_ENDPOINT
    name = args.model or os.environ.get("USTA_MODEL") or cur.model
    api_name, api_key = "varsayılan", os.environ.get("USTA_API_KEY")
    if cur.api and not (args.endpoint or os.environ.get("USTA_ENDPOINT")):
        try:
            saved = apis.load(home).get(cur.api)
        except apis.ApiError:
            saved = None
        if saved is not None:  # son oturumda seçilen kayıtlı API
            endpoint, api_key, api_name = saved.endpoint, saved.key, saved.name
    explicit = args.protocol or os.environ.get("USTA_PROTOCOL") or cur.protocol
    if explicit and explicit not in PROTOCOLS:
        print(f"hata: protokol native|json|text olmalı: {explicit}", file=sys.stderr)
        return 2
    if not name:
        name = _pick_model(endpoint, home, cur)
        if name is None:
            return 2
    protocol = explicit or "native"
    if not explicit:  # yetenek sondası: önbellekte yoksa birkaç küçük istekle ölç
        print(f"{name} tanınıyor (ilk seferde birkaç küçük istek)…", flush=True)
        try:
            prof = profile.resolve_protocol(
                home,
                endpoint,
                name,
                lambda: _build_model(endpoint, name, "native", args.model_timeout, api_key=api_key),
            )
        except profile.ProfileError as e:
            print(f"hata: {e}", file=sys.stderr)
            return 2
        protocol = prof.protocol
        print(f"Protokol: {protocol} — {prof.note}")
    hosts = _allowed_hosts(args)
    servers = _mcp_servers(home)
    root = Path(args.workspace).resolve()
    if hosts is None or servers is None or not root.is_dir():
        if not root.is_dir():
            print(f"hata: çalışma alanı yok: {root}", file=sys.stderr)
        return 2
    try:
        projects.check_root(home, root)
    except ValueError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    extra = _extra_body(args)
    if extra is None:
        return 2
    default_ep = (
        args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or DEFAULT_ENDPOINT
    )
    control = ModelControl(
        home,
        default_ep,
        name,
        protocol,
        lambda ep, nm, pr, key: _build_model(ep, nm, pr, args.model_timeout, extra, api_key=key),
        _discover_models,
        explicit_protocol=explicit,
        default_key=os.environ.get("USTA_API_KEY"),
        api=api_name,
    )
    try:
        cleanup_orphans()
    except OSError:  # docker yok
        pass
    wid = projects.register(home, root)
    window = args.context_window or cur.context_window
    manager = TaskManager(
        control.current,
        home=home,
        allowed_hosts=hosts,
        context_window=window,
        model_control=control,
        mcp_servers=lambda: _mcp_servers(home) or [],
    )
    interactive = sys.stdin.isatty()
    portal, url = None, None
    if cur.portal and not args.no_portal:
        try:
            portal = Portal(
                manager,
                home,
                load_or_create_token(home),
                preferred_port=args.port or 8765,
                workspace=wid,
            )
            url = portal.start()
        except RuntimeError as e:
            print(f"uyarı: portal başlatılamadı: {e}", file=sys.stderr)
            portal = None
    if portal is not None and interactive and not args.no_browser:
        with contextlib.suppress(Exception):  # tarayıcı açılamazsa terminal yine çalışır
            _open_browser(portal.login_page())
    save_history = _setup_readline(home) if interactive else None
    repl = Repl(
        manager,
        root,
        wid,
        home,
        cur,
        model_name=name,
        protocol=protocol,
        portal_url=url,
        open_portal=(lambda: _open_browser(portal.login_page())) if portal else None,
        login_link=portal.login_url if portal else None,
        context_window=window,
    )
    try:
        return repl.run()
    finally:
        if save_history:
            save_history()
        if portal is not None:
            portal.stop()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if (
        argv[:2] in (["mcp", "add"], ["verify", "set"]) and "--" in argv
    ):  # `--` sonrası sunucu komutudur
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    args = _parser().parse_args(argv)
    if args.cmd is None:
        return _chat_cmd(args)
    if args.cmd == "mcp":
        return _mcp_cmd(args, command)
    if args.cmd == "bench":
        return _bench_cmd(args)
    if args.cmd == "probe":
        return _probe_cmd(args)
    if args.cmd == "verify":
        return _verify_cmd(args, command)
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
    with McpSession(servers, _home()) as mcp:
        for warning in mcp.warnings:
            print(f"uyarı: {warning}", file=sys.stderr)
        agent = Agent(
            model,
            build_registry(ToolContext(root=root, allowed_hosts=hosts), extra=mcp.tools),
            Policy(root, set(hosts), mcp_modes=mcp.modes),
            audit,
            approver=_approver,
            max_steps=args.max_steps,
            memory_context=memory.render_context(root),
        )
        try:
            result = agent.run(args.prompt)
        except ModelError as e:
            print(f"hata: {e}", file=sys.stderr)
            return 1
    print(result.answer)
    return 1 if result.truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())
