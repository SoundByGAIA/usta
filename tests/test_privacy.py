"""Gizlilik özeti doğru sınıflar ve 'telemetri yok' iddiası kaynakta ağ modülü listesiyle korunur."""

import re
from pathlib import Path

from test_api import AUTH, Scripted, make_client
from usta import privacy

NET_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(httpx|urllib\.request|requests|socket|http\.client|aiohttp|websockets?)\b",
    re.MULTILINE,
)
# Ağa çıkabilen modüllerin tamamı ve nedenleri. Yeni bir modül eklenirse burada gerekçelendirilmeli
# (ve arayüzdeki gizlilik özeti güncel kalmalı); aksi halde test kırılır.
KNOWN_NETWORK_MODULES = {
    "cli.py": "model uç noktasından model listesi",
    "models.py": "seçilen model API'sine istek",
    "modelinfo.py": "model uç noktasından özet (Ollama)",
    "localmodels.py": "127.0.0.1 ve evdeki (özel ağ) adresler: yalnız model listesi sorgusu",
    "ortak.py": "evdeki ortak hafıza: yalnız özel ağdaki ev sahibi bilgisayar, imzalı istekler",
    "fetch_inner.py": "sandbox içinde, allowlist proxy üzerinden sayfa getirme",
    "proxy.py": "allowlist proxy",
    "portal.py": "yerel portal sunucusu",
}


def test_where_classifies_local_lan_and_internet():
    assert privacy.where("http://127.0.0.1:11434/v1") == privacy.LOCAL
    assert privacy.where("http://localhost:8000/v1") == privacy.LOCAL
    assert privacy.where("http://192.168.1.20:1234/v1") == privacy.LAN
    assert privacy.where("http://nas.local/v1") == privacy.LAN
    assert privacy.where("https://api.deepseek.com/v1") == privacy.INTERNET
    assert privacy.where("http://8.8.8.8/v1") == privacy.INTERNET


def test_report_says_where_prompts_go(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    src = [
        {"name": "ollama", "endpoint": "http://127.0.0.1:11434/v1"},
        {"name": "deepseek", "endpoint": "https://api.deepseek.com/v1"},
    ]
    local = privacy.report(tmp_path, src, "ollama", ())
    assert "dışarı çıkmaz" in local["sends"][0]
    remote = privacy.report(tmp_path, src, "deepseek", ("docs.python.org",))
    assert "internetteki https://api.deepseek.com/v1" in remote["sends"][0]
    assert any("docs.python.org" in line for line in remote["other"])
    assert any("Ağ kapalıdır" in line for line in local["other"])
    assert [s["name"] for s in remote["stored"]] == ["config.json"]


def test_privacy_endpoint_requires_auth_and_returns_report(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.get("/privacy").status_code == 401
    d = c.get("/privacy", headers=AUTH).json()
    assert d["home"] and d["other"] and "sends" in d


def test_only_known_modules_import_network_libraries():
    root = Path(__file__).resolve().parent.parent / "src" / "usta"
    found = {
        p.name
        for p in root.rglob("*.py")
        if "web" not in p.parts and NET_IMPORT.search(p.read_text())
    }
    assert found <= set(KNOWN_NETWORK_MODULES), (
        f"gerekçelendirilmemiş ağ modülü: {sorted(found - set(KNOWN_NETWORK_MODULES))}"
    )


def test_web_ui_loads_nothing_from_outside():
    web = Path(__file__).resolve().parent.parent / "src" / "usta" / "web"
    ext = re.compile(
        r"""(?:src|href)\s*=\s*["']https?://|@import\s+url\(\s*["']?https?://|url\(\s*["']?https?://"""
    )
    for f in [*web.glob("*.html"), *web.glob("*.css")]:
        assert not ext.search(f.read_text()), f"dış kaynak: {f.name}"
