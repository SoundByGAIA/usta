"""Arayüz işaretlemesi: tarayıcının sessizce bozduğu kalıplar (ör. düğme içinde düğme) depoya girmesin."""

import re
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "usta" / "web"
INDEX = WEB / "index.html"
# Etkileşimli öğeler birbirinin içine konamaz (HTML kuralı): tarayıcı dıştakini kapatıp içtekini dışarı atar,
# ekran bozulur. 0.4.3'te seçim kartı <button> idi ve içindeki "?" düğmeleri yüzünden dağıldı.
INTERACTIVE = {"button", "a", "select", "textarea", "label"}
VOID = {"input", "img", "br", "hr", "meta", "link"}


class _Nesting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.problems, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.append(d["id"])
        if tag in VOID:
            return
        if tag in INTERACTIVE and tag != "label":
            for outer in self.stack:
                if outer in INTERACTIVE - {"label"}:
                    self.problems.append(f"<{tag}> <{outer}> içinde (satır {self.getpos()[0]})")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def _parse():
    p = _Nesting()
    p.feed(INDEX.read_text(encoding="utf-8"))
    return p


def test_no_interactive_element_sits_inside_another():
    assert _parse().problems == []


def test_html_ids_are_unique():
    ids = _parse().ids
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_wizard_has_a_step_rail_and_three_places_to_run_the_ai():
    html = INDEX.read_text(encoding="utf-8")
    rail = re.search(r'<ol id="wiz-rail".*?</ol>', html, re.DOTALL).group(0)
    assert rail.count("<li") == 3
    for needed in ("wiz-cloud", "wiz-local", "wiz-lan", "wiz-lan-step", "wiz-lan-form"):
        assert f'id="{needed}"' in html
    # dinamik oluşturulan küçük kartlar düğmedir ama içlerinde başka düğme olmaz
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'WIZ_STEPS = ["wiz-start", "wiz-lan-step"' in js


def test_jargon_is_hidden_in_the_simple_view():
    html = INDEX.read_text(encoding="utf-8")
    for jargon in ('id="tokens" class="tokens adv"', 'id="ws-title" class="adv"'):
        assert jargon in html


def test_glossary_balloon_and_back_button_markup():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="gloss-tip"' in html and 'role="tooltip"' in html  # "?" balonu
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"Sayfaya dön"' in js  # açık bölümün düğmesi geri dönüş düğmesi olur
    # "?" artık sözlük sayfasına atlamaz: balon açar, sayfa değişmez (sözlüğe ancak balondaki düğmeyle gidilir)
    click = js[js.index("const b = qBtn(ev);") :][:200]
    assert "showGlossTip" in click and 'togglePanel("glossary")' not in click


def test_skill_design_markup_and_the_card_never_saves_by_itself():
    html = INDEX.read_text(encoding="utf-8")
    for needed in ("skill-design", "my-skills", "design-note", "design-off"):
        assert f'id="{needed}"' in html
    js = (WEB / "app.js").read_text(encoding="utf-8")
    card = js[js.index("function skillProposalNode") : js.index("async function loadMySkills")]
    # kayıt yalnız Kaydet düğmesinin tıklamasında ve kullanıcının gördüğü (sunucunun doğruladığı) metinle yapılır
    assert card.count('method: "PUT"') == 1
    assert card.index('method: "PUT"') > card.index('save.addEventListener("click"')
    assert (
        "content: d.content" in card
        and "args.instructions" not in card[card.index('method: "PUT"') :]
    )
