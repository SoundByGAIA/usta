"""Komut satırı: MCP sunucuları ve sandbox imajı (usta mcp …, usta sandbox …)."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from usta import cli, compat, mcp_http, mcp_runtime, mcpconfig
from usta.mcp import McpClient, McpError


def _mcp_add_remote(args: argparse.Namespace, command: list[str], home: Path) -> int:
    if command:
        print("hata: --url ile komut verilmez", file=sys.stderr)
        return 2
    try:
        mcpconfig.validate_remote(
            args.name,
            args.url,
            [mcpconfig.token_env(args.name)] if args.token else [],
            args.approve,
        )
        if args.name in mcpconfig.load(home) and not args.replace:
            raise mcpconfig.McpConfigError(f"'{args.name}' zaten var (değiştirmek için --replace)")
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(
        f"Usta bu adresteki sunucuyla konuşacak: {args.url}\n"
        f"Araçlara giden bilgiler{' ve jeton' if args.token else ''} bu adrese gider. "
        + (
            "Araçları her çağrıda onayına sunulur (onay: ask)."
            if args.approve == "ask"
            else "Araçları SORMADAN çalışır (onay: allow)."
        )
    )
    if not args.yes:
        if not compat.is_tty():
            print("hata: etkileşimli değil; onaylamak için --yes ekle", file=sys.stderr)
            return 1
        if input("Eklensin mi? [e/H] ").strip().lower() not in {"e", "y"}:
            print("iptal edildi")
            return 1
    try:
        mcpconfig.add_remote(home, args.name, args.url, args.token, args.approve, args.replace)
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f"Eklendi: {args.name}.")
    if args.token:
        print(f"Jetonu gir: usta mcp secret {args.name}")
    print(f"Sonra dene: usta mcp test {args.name}")
    return 0


def _mcp_secret(name: str, key: str | None, home: Path) -> int:
    server = mcpconfig.load(home).get(name)
    if server is None:
        print(f"hata: '{name}' yok. Ekli olanlar için: usta mcp list", file=sys.stderr)
        return 2
    if key is None:
        if len(server.env) != 1:
            names = ", ".join(server.env) or "yok"
            print(f"hata: hangi anahtar? ({names})", file=sys.stderr)
            return 2
        key = server.env[0]
    if compat.is_tty():
        value = getpass.getpass(f"{key} değeri (ekranda görünmez): ")
    else:
        value = sys.stdin.readline()
    try:
        mcpconfig.set_secret(home, name, key, value.strip())
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f"{key}: kaydedildi (yalnız sana okunur dosyada)")
    return 0


def _mcp_add(args: argparse.Namespace, command: list[str], home: Path) -> int:
    if args.url:
        return _mcp_add_remote(args, command, home)
    if not command:
        print("hata: komut eksik. Örnek: usta mcp add arama -- npx -y paket-adi", file=sys.stderr)
        return 2
    host = args.isolation == "host"
    if host and not args.host_risk:
        print(
            "hata: --isolation host sunucuyu ana makinede, tüm yetkilerinle çalıştırır "
            "(ev dizinin, jetonların, ssh anahtarların dahil). Bunu bilerek istiyorsan "
            "--i-understand-host-risk ekle; aksi halde --image ile konteyner izolasyonu kullan.",
            file=sys.stderr,
        )
        return 2
    try:
        mcpconfig.validate(args.name, command, args.env, args.approve)
        mcpconfig.validate_runtime(
            args.isolation,
            args.image,
            [h.lower() for h in args.allow_hosts],
            args.workspace_access,
            args.memory,
            args.cpus,
            args.pids,
        )
        if args.name in mcpconfig.load(home) and not args.replace:
            raise mcpconfig.McpConfigError(f"'{args.name}' zaten var (değiştirmek için --replace)")
    except mcpconfig.McpConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    interactive = compat.is_tty()
    where = (
        "bilgisayarında SENİN yetkilerinle çalışacak (UYUMLULUK MODU, yalıtım yok)"
        if host
        else f"konteynerde ({args.image}) çalışacak: ağ "
        + (", ".join(args.allow_hosts) if args.allow_hosts else "kapalı")
        + f", çalışma alanı {args.workspace_access}, {args.memory}/{args.cpus} CPU/{args.pids} süreç"
    )
    print(
        f"Bu komut {where}:\n  {' '.join(command)}\n"
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
        mcpconfig.add_server(
            home,
            args.name,
            command,
            args.env,
            args.approve,
            args.replace,
            isolation=args.isolation,
            image=args.image,
            allow_hosts=[h.lower() for h in args.allow_hosts],
            workspace=args.workspace_access,
            memory=args.memory,
            cpus=args.cpus,
            pids=args.pids,
        )
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
    nxt = (
        f"usta mcp test {args.name}"
        if host
        else f"usta mcp prepare {args.name}  (paketleri indirip sabitler), sonra usta mcp test {args.name}"
    )
    print(f"Eklendi: {args.name}. Sonraki adım: {nxt}")
    return 0


def _mcp_list(home: Path) -> int:
    servers = cli._mcp_servers(home)
    if servers is None:
        return 2
    if not servers:
        print("Ekli MCP sunucusu yok. Eklemek için: usta mcp add AD -- KOMUT")
        return 0
    for s in servers:
        env = mcpconfig.resolve_env(home, s, os.environ)
        keys = ", ".join(f"{k}({'tanımlı' if k in env else 'EKSİK'})" for k in s.env)
        iso = (
            f"uzak:{s.url}"
            if s.isolation == mcpconfig.REMOTE
            else "HOST(yalıtımsız)"
            if s.isolation == "host"
            else f"konteyner:{s.image or 'İMAJ YOK'}"
            + (f" ağ:{','.join(s.allow_hosts)}" if s.allow_hosts else " ağ:kapalı")
            + (" sabit" if s.pin_image and s.pin_cache else " sabitlenmemiş")
        )
        print(
            f"{s.name}  [{'açık' if s.enabled else 'kapalı'}]  onay: {s.approve}  {iso}  "
            f"{' '.join(s.command)}" + (f"  env: {keys}" if keys else "")
        )
    return 0


def _mcp_test(name: str, home: Path) -> int:
    servers = cli._mcp_servers(home)
    if servers is None:
        return 2
    server = next((s for s in servers if s.name == name), None)
    if server is None:
        print(f"hata: '{name}' yok. Ekli olanlar için: usta mcp list", file=sys.stderr)
        return 2
    env = mcpconfig.resolve_env(home, server, os.environ)
    print(f"'{name}' başlatılıyor...")
    try:
        if server.isolation == mcpconfig.REMOTE:
            client = mcp_http.connect(server, env, 90)
            try:
                tools = client.list_tools()
            finally:
                client.close()
        elif server.isolation == "host":
            print("uyarı: ana makinede, yetkilerinle çalışıyor (uyumluluk modu)", file=sys.stderr)
            with McpClient(list(server.command), env, timeout=90) as client:
                tools = client.list_tools()
        else:
            handle = mcp_runtime.start(server, home=home, env=env, workspace=None, timeout=90)
            try:
                tools = handle.client.list_tools()
            finally:
                handle.close()
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


def _mcp_prepare(name: str, home: Path) -> int:
    servers = cli._mcp_servers(home)
    if servers is None:
        return 2
    server = next((s for s in servers if s.name == name), None)
    if server is None:
        print(f"hata: '{name}' yok. Ekli olanlar için: usta mcp list", file=sys.stderr)
        return 2
    if server.isolation != "container":
        print("hata: yalnız konteyner izolasyonlu sunucular hazırlanır", file=sys.stderr)
        return 2
    print(
        f"'{name}' hazırlanıyor: paketler yalnız paket kayıtlarına ({', '.join(mcp_runtime.PREPARE_HOSTS)}) "
        "açık bir ağda indirilir; kurulum betikleri çalışmaz. Sonra ağ kapalı çalışır."
    )
    try:
        iid, digest = mcp_runtime.prepare(
            server, home=home, env=mcpconfig.resolve_env(home, server, os.environ)
        )
        mcpconfig.set_pin(home, name, iid, digest)
    except (McpError, mcpconfig.McpConfigError) as e:
        print(f"hata: {e}", file=sys.stderr)
        return 1
    print(f"Hazır. Sabitlendi: imaj {iid[:19]}…, önbellek {digest[:19]}…")
    return 0


def mcp_cmd(args: argparse.Namespace, command: list[str]) -> int:
    home = cli._home()
    try:
        if args.mcp_cmd == "prepare":
            return _mcp_prepare(args.name, home)
        if args.mcp_cmd == "add":
            return _mcp_add(args, command, home)
        if args.mcp_cmd == "list":
            return _mcp_list(home)
        if args.mcp_cmd == "secret":
            return _mcp_secret(args.name, args.key, home)
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


def sandbox_cmd(args: argparse.Namespace) -> int:
    from usta import sandbox as sbx

    if args.sandbox_cmd == "pin":
        try:
            iid = sbx.pin_image(args.image, cli._home())
        except sbx.SandboxError as e:
            print(f"hata: {e}", file=sys.stderr)
            return 1
        print(f"Sabitlendi: {args.image} → {iid}")
        return 0
    pins = sbx.load_pins(cli._home())
    if not pins:
        print(
            "Sabitlenmiş imaj yok (usta sandbox pin ile sabitle). İmajlar etiketle seçilir; etiket başka içeriğe işaret edebilir."
        )
    for image, want in pins.items():
        have = sbx.local_image_id(image)
        state = "TUTUYOR" if have == want else f"DEĞİŞMİŞ (yerel {(have or 'yok')[:19]}…)"
        print(f"{image}: {want[:19]}… — {state}")
    return 0
