"""Bölüm bölüm site kurma (sitebuild.py, deneysel)."""

from test_api import Scripted
from usta import sitebuild
from usta.agent import Agent
from usta.audit import AuditLog
from usta.models import ModelResponse
from usta.policy import Policy
from usta.tools import ToolContext, build_registry

PASTANE = (
    "Yeni bir pastane açtım, adı Tatlı Köşe. Menümü gösteren bir sayfa istiyorum: baklava 120 TL, sütlaç 80 TL, "
    "kazandibi 90 TL. Adresimiz Nilüfer, Bursa."
)


def _agent(tmp_path, model, **kw):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return Agent(
        model,
        build_registry(ToolContext(root=ws)),
        Policy(ws),
        AuditLog(tmp_path / "a.jsonl"),
        **kw,
    ), ws


def test_applies_only_to_new_site_requests(tmp_path):
    assert sitebuild.applies(PASTANE, tmp_path)
    assert not sitebuild.applies("Bu klasördeki dosyaları say.", tmp_path)
    assert not sitebuild.applies(
        "index.html dosyasına bir site yaz.", tmp_path
    )  # dosya adı verildi
    assert not sitebuild.applies(PASTANE, None)
    (tmp_path / "index.html").write_text("<h1>x</h1>")
    assert not sitebuild.applies(PASTANE, tmp_path)  # var olan site: olağan döngü


def test_plan_parsing_drops_headers_nested_items_and_repeats():
    nested = "***Adım**\nAyşe\n***Hobilerim**\nResim yapma\n***Bana Ulaşmak için E-posta**"
    assert sitebuild.parse_plan(nested) == ["Adım", "Hobilerim", "Bana Ulaşmak için E-posta"]
    header = "**Davetiye Sayfası – Bölüm Planı (2-4 adet)**\n1. Bilgi – tarih\n2. Konum – Bursa"
    assert sitebuild.parse_plan(header) == ["Bilgi – tarih", "Konum – Bursa"]
    assert sitebuild.parse_plan("Menü - a\nMenü - b\nAdres: Bursa") == ["Menü - a", "Adres: Bursa"]
    assert sitebuild.parse_plan("") == sitebuild.DEFAULT_PLAN


def test_section_checks_catch_invented_prices_times_phones_and_broken_scripts():
    ok = "<section><h2>Menü</h2><ul><li>Baklava 120 TL</li><li>Sütlaç 80,00 TL</li></ul></section>"
    assert sitebuild.problems(PASTANE, ok) == []
    made = sitebuild.problems(PASTANE, "<section><p>Künefe 150 TL</p></section>")
    assert any("150 TL" in p for p in made)
    hours = sitebuild.problems(
        PASTANE, "<section><p>8:00 ile 18:00 arası açık, tel 0532 123 45 67</p></section>"
    )
    assert any("saat" in p for p in hours) and any("telefon" in p for p in hours)
    assert sitebuild.problems(PASTANE, "<section><h2></h2></section>") == [
        "bölümde görünen metin yok"
    ]
    if sitebuild.shutil.which("node"):
        assert any(
            "betik" in p
            for p in sitebuild.problems(
                PASTANE, "<section><p>Sayaç</p><script>let a = ;</script></section>"
            )
        )
        assert (
            sitebuild.problems(PASTANE, "<section><p>Sayaç</p><script>let a = 1;</script></section>")
            == []
        )


def test_duplicate_sections_by_heading_or_text():
    menu = "<section><h2>Menü</h2><p>Baklava 120 TL</p></section>"
    assert sitebuild.duplicate("<section><h2>menü</h2><p>başka</p></section>", [menu])
    assert sitebuild.duplicate("<section><h2>İkinci</h2><p>Baklava 120 TL</p></section>", [menu])
    assert not sitebuild.duplicate("<section><h2>Adres</h2><p>Nilüfer, Bursa</p></section>", [menu])


def test_section_parsing_keeps_only_the_fragment():
    frag = sitebuild.parse_section(
        "```html\n<html><head><style>x{}</style></head><h2>Menü</h2><p>a</p>\n```", 1
    )
    assert frag.startswith('<section id="b1">') and "<html" not in frag and "<style" not in frag
    assert (
        sitebuild.parse_css("<style>body{color:red}</style></style><script>") == "body{color:red}"
    )


def test_agent_builds_site_section_by_section_and_writes_one_page(tmp_path):
    model = Scripted(
        ModelResponse("1. Menü - tatlılar\n2. Adres - konum\n3. Menü - tekrar"),
        ModelResponse("Tatlı Köşe"),
        ModelResponse("```css\nbody { font-family: sans-serif }\n```"),
        ModelResponse(
            '<section id="b0"><h2>Menü</h2><p>Baklava 120 TL, kazandibi 90 TL, künefe 150 TL</p></section>'
        ),
        ModelResponse(
            '<section id="b0"><h2>Menü</h2><p>Baklava 120 TL, kazandibi 90 TL</p></section>'
        ),
        ModelResponse('<section id="b1"><h2>Adres</h2><p>Nilüfer, Bursa</p></section>'),
        # tamamlama: eksik sütlaç ilk bölüme eklenir
        ModelResponse(
            '<section id="b0"><h2>Menü</h2><p>Baklava 120 TL, sütlaç 80 TL, kazandibi 90 TL</p></section>'
        ),
    )
    agent, ws = _agent(tmp_path, model, site_steps=True)
    result = agent.run(PASTANE)
    page = (ws / "index.html").read_text()
    assert "<h1>Tatlı Köşe</h1>" in page and "künefe" not in page.lower() and "sütlaç 80 TL" in page
    assert page.count("<h2>Menü</h2>") == 1
    assert "Plan: Menü → Adres" in result.answer and "✓ Bilgilerin hepsi sayfada" in result.answer
    assert "✓ index.html yazıldı" in result.answer and not model.responses


def test_site_steps_off_or_existing_site_uses_the_normal_loop(tmp_path):
    model = Scripted(ModelResponse("tamam"))
    agent, ws = _agent(tmp_path, model)
    assert agent.run(PASTANE).answer == "tamam" and not (ws / "index.html").exists()
    model = Scripted(ModelResponse("tamam"))
    agent, ws = _agent(tmp_path, model, site_steps=True)
    (ws / "index.html").write_text("<h1>eski</h1>")
    assert agent.run("Sitemin rengini maviye çevir.").answer == "tamam"
