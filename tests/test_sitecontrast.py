from usta.finishcheck import FinishCheck
from usta.sitecontrast import hidden_texts

PINK = """<style>
header { background: #ff69b4; color: white; padding: 2rem; }
header h1 { color: #ff69b4; }
</style>
<header><h1>Ayşe Kuaför</h1><p>Buca'nın en şık adresi</p></header>"""


def test_pink_title_on_pink_header_is_hidden():
    assert hidden_texts(PINK) == ["Ayşe Kuaför"]


def test_readable_page_has_nothing_hidden():
    html = PINK.replace("header h1 { color: #ff69b4; }", "header h1 { color: #fff; }")
    assert hidden_texts(html) == []


def test_css_variables_from_root_are_resolved():
    html = """<style>:root { --ana: #2a9d8f; }
    .hero { background-color: var(--ana); } .hero .baslik { color: var(--ana); }</style>
    <div class="hero"><span class="baslik">Kafe Deniz</span></div>"""
    assert hidden_texts(html) == ["Kafe Deniz"]


def test_white_text_without_any_background_is_hidden():
    html = "<style>p { color: #fefefe }</style><body><p>Telefon: 0555</p></body>"
    assert hidden_texts(html) == ["Telefon: 0555"]


def test_inline_style_wins_over_stylesheet():
    html = '<style>h1 { color: white }</style><div style="background:#000"><h1 style="color:#111">Ad</h1></div>'
    assert hidden_texts(html) == ["Ad"]


def test_specificity_and_order():
    html = """<style>#ust h1 { color: black } h1 { color: white } div { background: white }</style>
    <div id="ust"><h1>Görünür</h1></div>"""
    assert hidden_texts(html) == []


def test_unknown_cases_stay_silent():
    # görsel/gradyan zemin, :hover, @media ve gizli öğeler hakkında karar verilmez
    html = """<style>
    .a { background: url(foto.jpg); color: white }
    .b { background: linear-gradient(#fff, #000); color: white }
    .c:hover { color: white }
    @media (prefers-color-scheme: dark) { body { background: #000 } }
    .d { display: none; color: white }
    p { color: #fff }
    </style><div class="a"><p>Bir</p></div><div class="b"><p>İki</p></div>
    <p class="c" style="color:#000">Üç</p><p class="d">Dört</p>"""
    assert hidden_texts(html) == []


def test_script_and_style_text_is_ignored():
    html = "<body style='background:#fff'><script>var x = 'gizli';</script><p style='color:#000'>Ok</p></body>"
    assert hidden_texts(html) == []


def test_finish_check_reminds_once_about_invisible_text(tmp_path):
    (tmp_path / "index.html").write_text(PINK, encoding="utf-8")
    fc = FinishCheck("Kuaför dükkanım için bir site yap. Adı Ayşe Kuaför.", root=tmp_path)
    fc.observe("write_file", {"path": "index.html", "content": PINK}, True)
    note = fc.on_finish("Siteyi yaptım.")
    assert note and "Ayşe Kuaför" in note and "göremiyor" in note
    assert fc.on_finish("Siteyi yaptım.") is None


def test_finish_check_reads_linked_stylesheet(tmp_path):
    (tmp_path / "stil.css").write_text(
        "header{background:#ff69b4} h1{color:#ff69b4}", encoding="utf-8"
    )
    page = '<link rel="stylesheet" href="stil.css"><header><h1>Ayşe Kuaför</h1></header>'
    (tmp_path / "index.html").write_text(page, encoding="utf-8")
    fc = FinishCheck("Bana bir site yap. Adı Ayşe Kuaför.", root=tmp_path)
    fc.observe("write_file", {"path": "index.html", "content": page}, True)
    assert "Ayşe Kuaför" in (fc.on_finish("Bitti.") or "")
