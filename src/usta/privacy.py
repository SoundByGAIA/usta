"""Gizlilik özeti: verinin nereye gittiğini ve nerede durduğunu gerçek duruma göre hesaplar.

Sabit metin değil: seçili modelin ve kayıtlı API'lerin uç noktası yerel mi uzak mı, hangi dosyalar ev dizininde,
dışarı çıkabilecek yollar hangi izne bağlı. "Telemetri yok" iddiası `tests/test_privacy.py` ile korunur: kaynakta ağa
çıkabilen modüller bilinen bir listeden fazlaysa test kırılır.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

LOCAL, LAN, INTERNET = "bu-bilgisayar", "yerel-ağ", "internet"

FILES = {
    "config.json": "ayarların (tema, mod, model, düşünme, bağlam); sır içermez",
    "apis.json": "bağladığın API'ler ve anahtarları; yalnız sen okuyabilirsin",
    "token": "portal giriş jetonun",
    "mcp.json": "bağladığın MCP araç sunucuları",
    "profiles.json": "modellerin ölçülmüş yetenek profilleri",
    "audit": "yapılan işlemlerin kaydı (neyi okudu, neyi yazdı)",
    "workspaces": "çalışma alanların ve oturum geçmişin",
    "login": "tek kullanımlık giriş kodları",
}


def where(endpoint: str) -> str:
    """Uç nokta bu bilgisayarda mı, yerel ağda mı, internette mi."""
    host = (urlsplit(endpoint).hostname or "").lower()
    if host == "localhost":
        return LOCAL
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return LAN if host.endswith((".local", ".lan", ".internal")) else INTERNET
    if ip.is_loopback:
        return LOCAL
    return LAN if ip.is_private or ip.is_link_local else INTERNET


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def report(
    home: Path, sources: list[dict], current_api: str | None, allowed_hosts, lan_urls=None
) -> dict:
    """`sources`: [{name, endpoint}]; `current_api`: kullanılan API adı (yoksa None)."""
    rows = [
        {"name": s["name"], "endpoint": s["endpoint"], "where": where(s["endpoint"])}
        for s in sources
    ]
    cur = next((r for r in rows if r["name"] == current_api), None)
    sends = []
    if cur is None:
        sends.append("Aktif model bilinmiyor.")
    elif cur["where"] == LOCAL:
        sends.append(
            "İstemlerin ve açtığın dosyalar yalnız bu bilgisayardaki modele gider; dışarı çıkmaz."
        )
    elif cur["where"] == LAN:
        sends.append(
            f"İstemlerin ve açtığın dosyaların içeriği yerel ağındaki {cur['endpoint']} adresine gider."
        )
    else:
        sends.append(
            f"İstemlerin ve açtığın dosyaların içeriği internetteki {cur['endpoint']} adresine gider "
            "(o sağlayıcının gizlilik koşulları geçerli)."
        )
    hosts = sorted(allowed_hosts or [])
    lan = (
        []
        if lan_urls is None
        else [
            (
                "Yerel ağ modu AÇIK: aynı ağdaki cihazlar bu sayfaya erişebilir ama eşleştirme PIN'i "
                "olmadan giremez. Trafik şifrelenmez; yalnız güvendiğin ağda (ev Wi-Fi'ı) kullan."
            )
        ]
    )
    return {
        "model": cur,
        "apis": rows,
        "sends": sends,
        "other": [
            *lan,
            "Komutlar Docker içinde çalışır; Docker yoksa çalışmaz, bilgisayarında doğrudan çalışmaz. "
            + (
                f"Ağ yalnız şu adreslere açıktır: {', '.join(hosts)}."
                if hosts
                else "Ağ kapalıdır; internete çıkamaz."
            ),
            "Web sayfası getirme (fetch_url) her seferinde onay ister"
            + (f"; yalnız şu adresler onaysız açıktır: {', '.join(hosts)}." if hosts else "."),
            "MCP sunucuları yalıtılmış konteynerde çalışır (ağ kapalı ya da yalnız izinli adresler).",
            "Arayüz dışarıdan yazı tipi, betik ya da görsel yüklemez; her şey bilgisayarından gelir.",
            "Kullanım istatistiği, çökme raporu ya da izleme göndermeyiz; bu kodda yok.",
        ],
        "home": str(home),
        "stored": [
            {"name": n, "what": w, "bytes": _size(home / n)}
            for n, w in FILES.items()
            if (home / n).exists()
        ],
    }
