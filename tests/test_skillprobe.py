"""Yazma becerisi sondası (skillprobe.py) ve seviyeye göre site kurma."""

import re

from test_api import Scripted
from usta import sitebuild, skillprobe
from usta.models import ModelResponse

SECTION = '<section id="b0"><h2>İletişim</h2><p>E-posta: ayse@ornek.com</p></section>'
PAGE = (
    "<!doctype html><html><head><title>Ayşe</title></head><body><h1>Ayşe</h1><p>Resim yapıyorum.</p>"
    "<p>ayse@ornek.com</p></body></html>"
)
GOOD = {
    "tek": "Tatlı Köşe her gün sizi bekliyor.",
    "iki": "baklava - 120 TL\nsütlaç - 80 TL\nkazandibi - 90 TL",
    "plan": "1. Tanıtım - pastane\n2. Menü - baklava",
    "bolum": SECTION,
    "uydurma": "Tatlı Köşe, Nilüfer'de sizi bekliyor. Tatlılarımızı deneyin.",
    "sayfa": PAGE,
}


def test_each_check_accepts_a_good_answer_and_rejects_typical_failures():
    for name, (_prompt, check) in skillprobe.PROBES.items():
        assert check(GOOD[name]), name
    assert not skillprobe.check_one("Tatlı Köşe her gün sizi bekliyor. Afiyet olsun!")
    assert not skillprobe.check_two("Menü:\nbaklava - 120 TL\nsütlaç - 80 TL\nkazandibi - 90 TL")
    assert not skillprobe.check_two("baklava - 120 TL\nsütlaç - 85 TL\nkazandibi - 90 TL")
    assert not skillprobe.check_plan("Plan yapamıyorum")
    assert not skillprobe.check_section("<h2>İletişim</h2><p>ayse@ornek.com</p>")  # section yok
    assert not skillprobe.check_section(SECTION.replace("</p>", " Tel: 0532 123 45 67</p>"))
    assert not skillprobe.check_noinvent("Tatlı Köşe her gün 09:00'da açılır.")
    assert not skillprobe.check_noinvent("Tatlı Köşe 甜点 sunar.")
    assert not skillprobe.check_noinvent("<p>Tatlı Köşe</p>")
    assert not skillprobe.check_page(SECTION)


def test_level_needs_all_checks_and_a_big_or_unknown_model_for_whole_pages():
    every = dict.fromkeys(skillprobe.PROBES, True)
    assert skillprobe.level_for(every, None) == 3  # bulut: boyut bilinmiyor
    assert skillprobe.level_for(every, 32.0) == 3
    assert skillprobe.level_for(every, 9.2) == 2  # 12B altı yerel: bölüm bölüm
    assert skillprobe.level_for({**every, "sayfa": False}, 70.0) == 2
    assert skillprobe.level_for({**every, "uydurma": False}, 70.0) == 1
    assert skillprobe.level_for({}, None) == 1


def test_probe_runs_every_check_and_profile_is_cached_per_model_and_revision(tmp_path):
    model = Scripted(*(ModelResponse(GOOD[k]) for k in skillprobe.PROBES))
    p = skillprobe.probe(model, size_b=4.0, revision="abc")
    assert p.level == 2 and all(p.passed.values()) and not model.responses
    skillprobe.save(tmp_path, "http://x/v1/", "m", p)
    assert skillprobe.load(tmp_path, "http://x/v1", "m", "abc").level == 2
    assert skillprobe.load(tmp_path, "http://x/v1", "m", "yeni") is None  # model değişti
    assert skillprobe.load(tmp_path, "http://x/v1", "baska", "abc") is None


def test_failing_model_gets_the_smallest_pieces(tmp_path):
    model = Scripted(*(ModelResponse("bilmiyorum") for _ in skillprobe.PROBES))
    assert skillprobe.probe(model).level == 1


# --- seviyeye göre site kurma ---------------------------------------------------------------------------
from test_sitebuild import DAVETIYE, PASTANE, _agent


def test_level1_page_is_built_by_usta_and_the_model_only_writes_a_short_intro(tmp_path):
    model = Scripted(
        ModelResponse("Tatlı Köşe"),
        ModelResponse("Tatlı Köşe her gün 09:00'da açılır."),  # uydurma saat: yeniden
        ModelResponse("Tatlı Köşe, Nilüfer'de sizi bekliyor."),
    )
    agent, ws = _agent(tmp_path, model, site_steps=True, site_level=1)
    result = agent.run(PASTANE)
    page = (ws / "index.html").read_text()
    assert "<li>Baklava - 120 TL</li>" in page and "<li>Sütlaç - 80 TL</li>" in page
    assert "Nilüfer'de sizi bekliyor" in page and "09:00" not in page
    assert "✓ Bilgilerin hepsi sayfada" in result.answer and not model.responses


def test_failing_section_is_redone_in_smaller_pieces_and_usta_adds_missing_facts(tmp_path):
    bad = "<section><h2>Yer</h2><p>Konuklar Oteli, telefon 0532 123 45 67</p></section>"
    model = Scripted(
        ModelResponse("1. Davet - Ali ve Zeynep\n2. Yer - Bursa"),
        ModelResponse("Ali ve Zeynep Evleniyor"),
        ModelResponse("body { color: #333 }"),
        ModelResponse("<section><h2>Davet</h2><p>Ali ve Zeynep evleniyor.</p></section>"),
        ModelResponse(bad),
        ModelResponse(bad),  # ısrar; satır silinince bölüm boş kalır → küçük parça
        ModelResponse("Düğün Bursa'da olacak."),
    )
    agent, ws = _agent(tmp_path, model, site_steps=True, site_level=2)
    result = agent.run(DAVETIYE)
    page = (ws / "index.html").read_text()
    assert "Oteli" not in page and "<p>Düğün Bursa'da olacak.</p>" in page
    assert "↓ Yer: daha küçük parçalarla yeniden yapıldı" in result.answer
    assert "14 Haziran 2027 tarihine" in page and not model.responses


def test_usta_adds_facts_the_model_could_not(tmp_path):
    menu = (
        "<section><h2>Menü</h2><ul><li>Baklava 120 TL</li><li>Kazandibi 90 TL</li></ul></section>"
    )
    model = Scripted(
        ModelResponse("1. Menü - tatlılar"),
        ModelResponse("Tatlı Köşe"),
        ModelResponse("body { color: #333 }"),
        ModelResponse(menu.replace("</ul>", "</ul><p>Tatlı Köşe, Nilüfer, Bursa</p>")),
        ModelResponse(menu),  # tamamlama da sütlaçsız
    )
    agent, ws = _agent(tmp_path, model, site_steps=True, site_level=2)
    result = agent.run(PASTANE)
    page = (ws / "index.html").read_text()
    assert "<li>Sütlaç - 80 TL</li>" in page and "Eksik bilgileri Usta ekledi" in result.answer
    assert "✓ Bilgilerin hepsi sayfada" in result.answer and not model.responses


def test_level3_uses_the_normal_agent_loop(tmp_path):
    model = Scripted(ModelResponse("tamam"))
    agent, ws = _agent(tmp_path, model, site_steps=True, site_level=3)
    assert agent.run(PASTANE).answer == "tamam" and not (ws / "index.html").exists()


def test_fact_rows_keep_the_users_words():
    rows = sitebuild.fact_rows(PASTANE)
    assert rows[:3] == ["Baklava - 120 TL", "Sütlaç - 80 TL", "Kazandibi - 90 TL"]
    assert sitebuild.fact_rows(DAVETIYE, only=["14 Haziran 2027"]) == ["Tarih: 14 Haziran 2027"]
    assert "mailto:ayse@ornek.com" in sitebuild.fact_rows("e-postam ayse@ornek.com")[0]


def test_heading_only_section_counts_as_empty():
    assert sitebuild.problems(PASTANE, "<section><h2>Menü</h2></section>") == [
        "bölümde başlık dışında metin yok"
    ]


class Recording(Scripted):
    def __init__(self, *responses):
        super().__init__(*responses)
        self.prompts: list[str] = []

    def chat(self, messages, tools=None):
        self.prompts.append("\n".join(m.content for m in messages))
        return super().chat(messages, tools)


def test_prompts_name_no_forbidden_items(tmp_path):
    """Yasak listesi ("telefon, saat, adres ekleme") 4B'ye tam onları yazdırdı (0/5); talimatlar olumlu kalmalı."""
    model = Recording(
        ModelResponse("1. Menü - tatlılar"),
        ModelResponse("Tatlı Köşe"),
        ModelResponse("body { color: #333 }"),
        ModelResponse(
            "<section><h2>Menü</h2><p>Baklava 120 TL, sütlaç 80 TL, kazandibi 90 TL</p>"
            "<p>Tatlı Köşe, Nilüfer, Bursa</p></section>"
        ),
    )
    agent, _ = _agent(tmp_path, model, site_steps=True, site_level=2)
    agent.run(PASTANE)
    forbidden = re.compile(
        r"telefon|phone|\bsaat|hours|\badres|address|uydurma|invent|do not|don't", re.IGNORECASE
    )
    for prompt in model.prompts + [p for p, _ in skillprobe.PROBES.values()]:
        own = prompt.replace(PASTANE, "")  # kullanıcının kendi sözleri sayılmaz
        assert not forbidden.search(own), (forbidden.search(own).group(0), own[:300])


def test_fix_note_names_the_models_own_inventions_not_categories():
    note = sitebuild.fix_note(
        DAVETIYE,
        "<section><h2>Yer</h2><p>Bursa, Konuklar Oteli, saat 19:00, tel 0532 123 45 67</p></section>",
    )
    assert "facts: 19:00, 0532 123 45 67, Konuklar Oteli" in note and not re.search(
        r"telefon|phone|saat|hours", note
    )
    assert (
        sitebuild.fix_note(
            DAVETIYE, "<section><h2>Davet</h2><p>Ali ve Zeynep evleniyor.</p></section>"
        )
        == ""
    )


def test_usta_sets_section_headings_and_rejects_english_titles():
    frag = sitebuild.set_heading(
        '<section id="b0"><h2>Adım - Adım: Ayşe</h2><p>Ayşe</p></section>', "Adım"
    )
    assert frag == '<section id="b0"><h2>Adım</h2><p>Ayşe</p></section>'
    assert "<h2>Menü</h2>" in sitebuild.set_heading('<section id="b1">\n<p>x</p></section>', "Menü")
    assert sitebuild._title("Merhaba, ben Ayşe. Bir site yap.", "Ayşe about me") == "Ayşe"
    assert sitebuild._title("Bir site yap.", "Ayşe'nin Resim Köşesi") == "Ayşe'nin Resim Köşesi"
