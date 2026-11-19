"""Komut satırı: argümansız `usta` (etkileşimli terminal + web portalı, arka plan kipi)."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import sys
import webbrowser
from pathlib import Path

import httpx

from usta import apis, cli, compat, profile, projects, services, settings, theme, thinking
from usta.api import load_or_create_token
from usta.modelctl import ModelControl
from usta.portal import Portal
from usta.repl import MODE_ALIASES, Repl
from usta.sandbox import cleanup_orphans
from usta.tasks import TaskManager


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
        found = services.usable_ids(r.json().get("data", []))
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        found = []
    return found or services.fallback_models(
        endpoint
    )  # bilinen servis: /models çalışmıyorsa sabit liste


def _pick_model(endpoint: str, home: Path, cur: settings.Settings) -> str | None:
    """İlk çalıştırma: uç noktadaki modelleri listeler, seçileni ayarlara kaydeder."""
    if not compat.is_tty():
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


def _running_file(home: Path) -> Path:
    return home / "running.json"


def _reuse_running(home: Path, no_browser: bool) -> bool:
    """Arka planda zaten çalışan bir Usta varsa yeni oturum kodu alıp tarayıcıyı açar; True döner."""
    try:
        info = json.loads(_running_file(home).read_text(encoding="utf-8"))
        port = int(info["port"])
        token = (home / "token").read_text(encoding="utf-8").strip()
        base = f"http://127.0.0.1:{port}"
        r = httpx.post(f"{base}/auth/code", headers={"Authorization": f"Bearer {token}"}, timeout=3)
        r.raise_for_status()
        code = r.json()["code"]
    except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError):
        return False  # çalışan örnek yok ya da yanıt vermiyor: yenisini başlat
    if not no_browser:
        with contextlib.suppress(Exception):
            _open_browser(f"{base}/?code={code}")
    return True


def chat_cmd(args: argparse.Namespace) -> int:
    home = cli._home()
    if args.background:
        if _reuse_running(home, args.no_browser):
            return 0  # zaten açıktı; tarayıcı yeniden açıldı
        # pencere yok: çıktıyı dosyaya yaz ki bir sorun olursa bakılabilsin
        with contextlib.suppress(OSError):
            log = open(home / "usta.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            sys.stdout = sys.stderr = log
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
    endpoint = (
        args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or cli.DEFAULT_ENDPOINT
    )
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
    if explicit == "auto":
        explicit = None
    if explicit and explicit not in cli.PROTOCOLS:
        print(f"hata: protokol native|json|text olmalı: {explicit}", file=sys.stderr)
        return 2
    setup = False
    if not name:
        # Terminalde seçilebilecek model varsa eski seçici; yoksa ve portal açıksa kurulum modu (sihirbaz).
        can_pick = compat.is_tty() and bool(_discover_models(endpoint))
        in_terminal = compat.is_tty() and not can_pick
        if cur.portal and not args.no_portal and (args.setup or args.background or in_terminal):
            setup = True
            name = ""
            print("Model seçilmedi: tarayıcıdaki kurulum sihirbazını tamamla.", flush=True)
        else:
            name = _pick_model(endpoint, home, cur)
            if name is None:
                return 2
    protocol = explicit or "native"
    if not explicit and not setup:  # yetenek sondası: önbellekte yoksa birkaç küçük istekle ölç
        print(f"{name} tanınıyor (ilk seferde birkaç küçük istek)…", flush=True)
        try:
            prof = profile.resolve_protocol(
                home,
                endpoint,
                name,
                lambda: cli._build_model(
                    endpoint, name, "native", args.model_timeout, api_key=api_key
                ),
            )
        except profile.ProfileError as e:
            print(f"hata: {e}", file=sys.stderr)
            return 2
        protocol = prof.protocol
        print(f"Protokol: {protocol} — {prof.note}")
    hosts = cli._allowed_hosts(args)
    servers = cli._mcp_servers(home)
    root = Path(args.workspace or ".").resolve()
    if hosts is None or servers is None or not root.is_dir():
        if not root.is_dir():
            print(f"hata: çalışma alanı yok: {root}", file=sys.stderr)
        return 2
    try:
        projects.check_root(home, root)
    except ValueError as e:
        if args.workspace is not None:  # klasörü kullanıcı açıkça verdi: sessizce değiştirme
            print(f"hata: {e}", file=sys.stderr)
            return 2
        # Klasör verilmedi ve bulunduğun yer uygun değil (ör. Windows'ta cmd'nin açıldığı ev klasörü):
        # hata vermek yerine kendi klasörünü kur. Kodsuz kullanıcı "proje klasörü"nü bilmez.
        fallback = Path.home() / "Usta"
        try:
            fallback.mkdir(exist_ok=True)
            projects.check_root(home, fallback)
        except (OSError, ValueError) as e2:
            print(f"hata: {e}\n(otomatik klasör de kurulamadı: {e2})", file=sys.stderr)
            return 2
        print(
            f"Bulunduğun yer ({root}) çalışma klasörü olamaz. Senin için bir klasör kurdum:\n"
            f"  {fallback.resolve()}\nUsta'ya yaptırdığın dosyalar buraya yazılacak.",
            flush=True,
        )
        root = fallback.resolve()
    extra = cli._extra_body(args)
    if extra is None:
        return 2
    default_ep = (
        args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or cli.DEFAULT_ENDPOINT
    )
    control = ModelControl(
        home,
        default_ep,
        name,
        protocol,
        lambda ep, nm, pr, key: cli._build_model(
            ep,
            nm,
            pr,
            args.model_timeout,
            {**thinking.extra_for(settings.load(home).think), **(extra or {})},
            api_key=key,
        ),
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
        symbol_tools=cli._symbol_tools(args),
        taint_gate=cli._taint_gate(args),
        finish_check=cli._finish_check(args),
        mcp_servers=lambda: cli._mcp_servers(home) or [],
    )
    interactive = compat.is_tty()
    portal, url = None, None
    if cur.portal and not args.no_portal:
        try:
            portal = Portal(
                manager,
                home,
                load_or_create_token(home),
                preferred_port=args.port or 8765,
                workspace=wid,
                lan=args.lan,
                background=args.background,
            )
            url = portal.start()
            pairing = portal.pairing()
            if pairing is not None:
                urls, pin = pairing
                print("Tablet/telefon için (aynı Wi-Fi'da):")
                print(f"  adres: {urls[0] if urls else 'yerel ağ adresi bulunamadı'}")
                print(
                    f'  giriş kodu: {pin}  (5 dakika geçerli; yeni kod için portalda "Tablet" düğmesi)'
                )
        except RuntimeError as e:
            print(f"uyarı: portal başlatılamadı: {e}", file=sys.stderr)
            portal = None
    if portal is not None and (interactive or args.background) and not args.no_browser:
        with contextlib.suppress(Exception):  # tarayıcı açılamazsa terminal yine çalışır
            _open_browser(portal.login_page())
    if args.background:
        return _background_loop(home, portal, url)
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


def _background_loop(home: Path, portal, url: str | None) -> int:
    """Arka plan kipi: REPL yok; portal `/quit` ile kapatılana kadar çalışır."""
    if portal is None:
        print("hata: portal başlatılamadı; arka planda çalışılamaz", file=sys.stderr)
        return 2
    port = int(url.rstrip("/").rsplit(":", 1)[1]) if url else 0
    with contextlib.suppress(OSError):
        _running_file(home).write_text(
            json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8"
        )
    print(f"Usta arka planda çalışıyor: {url}", flush=True)
    try:
        while not portal.quit.wait(timeout=1.0):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(OSError):
            _running_file(home).unlink()
        portal.stop()
    return 0
