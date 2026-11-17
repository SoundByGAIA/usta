"""Kodsuz kullanıcının site isteğini parça parça kurma (deneysel, `USTA_SITE_STEPS=1`).

Küçük model bir sayfanın tamamını tek seferde yazınca bilgi uydurur, sayacı bozar, dosyayı hiç yazmaz. Burada iş
modelin sağlıklı yapabileceği parçalara bölünür:

- Seviye 2: model kısa bir plan, tasarım (CSS) ve her bölümü ayrı ayrı yazar. Her bölüm hemen denetlenir (metin var
  mı, kullanıcının vermediği fiyat, saat, telefon, yer adı var mı, betik sözdizimi doğru mu); sorunlu bölüm bir kez
  yeniden yazdırılır, yine olmazsa bir basamak aşağı inilir.
- Seviye 1: iskeleti, kullanıcının bilgilerini ve sayacı Usta koyar; model yalnız kısa düz metin yazar.

Her iki seviyede de sayfayı Usta sabit bir iskelette birleştirir, sayaç Usta'nın hazır parçasıdır ve modelin
ekleyemediği bilgiyi Usta kendisi ekler. Model araç çağırmaz; dosya yazma ajanın olağan yolundan geçer (izin, denetim
kaydı, geri alma). Yalnız yeni site isteklerinde çalışır: istekte dosya adı geçiyorsa ya da klasörde zaten bir .html
varsa olağan ajan döngüsü kullanılır. Ölçüm: docs/olcumler/site-istekleri.md.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path

from usta import sitecheck
from usta.finishcheck import _ARTIFACT, write_targets
from usta.models import Message, ModelClient

MAX_SECTIONS = 5
DEFAULT_PLAN = [
    "Giriş - sitenin adı ve kısa tanıtım",
    "İçerik - kullanıcının verdiği bilgiler",
    "İletişim",
]
_SCRIPT_WANTED = re.compile(r"animasyon|buton|düğme", re.IGNORECASE)
_COUNTDOWN = re.compile(r"sayaç|geri\s*sayım|countdown|kaç\s+gün", re.IGNORECASE)
# model CSS yazamazsa tarayıcının çıplak görünümü yerine
DEFAULT_CSS = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#f6f7fb;color:#222;line-height:1.6}"
    "header{background:#1d3d9c;color:#fff;border-radius:12px}header h1{margin:8px 0}"
    "section{background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}"
    "h2{color:#1d3d9c;margin-top:0}a{color:#08808c}"
)
LAYOUT_CSS = (
    "body{display:block;margin:0;padding:0}"
    "header,section,footer{display:block;box-sizing:border-box;max-width:760px;margin:16px auto;padding:16px}"
    "header{text-align:center}img{max-width:100%}"
)
_FENCE = re.compile(r"```[\w-]*\n?(.*?)```", re.DOTALL)
_SECTION = re.compile(r"<section\b.*</section>", re.DOTALL | re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_STRIP = re.compile(
    r"<!doctype[^>]*>|</?(?:html|head|body)\b[^>]*>|<meta\b[^>]*>|<title>.*?</title>",
    re.IGNORECASE | re.DOTALL,
)
_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
_NAME_SPLIT = re.compile(r"\s+[-–—]\s+|:\s")
_TIME = re.compile(
    r"(?<![\d:.])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])|(?<=saat)\s*:?\s*(?:[01]?\d|2[0-3])[.:][0-5]\d(?!\d)",
    re.IGNORECASE,
)
# uydurma yer adı: birden çok büyük harfli kelime ya da yer eki ("Asya Düğün Salonu", "İznik Havalimanı")
_PLACE_WORD = re.compile(
    r"salon|plaza|otel|hotel|mahalle|cadde|sokak|bulvar|havaliman|istasyon|park|meydan|apartman|sitesi$",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?90[\s-]?)?\(?0?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")
_H2 = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.DOTALL | re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# Talimatlar İngilizce ve olumlu, sitedeki metin Türkçe. Yasak listesi ("telefon, saat yazma") küçük modele tam o
# bilgileri uydurtuyor; talimatlarda bilgi türü sayılmaz (ölçüm: docs/olcumler/site-istekleri.md).
SYSTEM = (
    "You write one part of a small website for a Turkish user. Write only the requested part, with no explanation. "
    "Use only the information the user gave. Keep sentences short and simple. All visible text must be in Turkish."
)
USER = "User's request (Turkish): "


def applies(task: str, root: Path | None) -> bool:
    """Yeni bir site isteği mi: site/sayfa kelimesi var, dosya adı verilmemiş, klasörde .html yok."""
    if not _ARTIFACT.search(task or "") or write_targets(task):
        return False
    if root is None or not Path(root).is_dir():
        return False
    try:
        return not any(p.suffix.lower() in (".html", ".htm") for p in Path(root).iterdir())
    except OSError:
        return False


def _text(reply) -> str:
    return (getattr(reply, "content", None) or "").strip()


def _unfence(s: str) -> str:
    m = _FENCE.search(s)
    return m.group(1).strip() if m else s.strip()


def plan_name(item: str) -> str:
    """Plan satırının kısa adı: "Menü - tatlılar ve fiyatlar" → "Menü"."""
    return _NAME_SPLIT.split(item, maxsplit=1)[0].strip()


def parse_plan(s: str) -> list[str]:
    """Modelin planından bölüm satırları. Plan iç içe yazılmışsa ("*Hobilerim" altında "Resim yapma") yalnız vurgulu
    satırlar bölüm sayılır; "Bölüm Planı" gibi başlıklar atılır."""
    rows = []
    for line in _unfence(s).splitlines():
        line = _BULLET.sub("", line).strip()
        if not line or line.endswith(":") or re.search(r"\bplan|\badet\b", sitecheck._fold(line)):
            continue
        rows.append(
            (line.startswith(("*", "#", "_")), line.strip("*#_ ").replace("**", "").strip())
        )
    if any(e for e, _ in rows) and not all(e for e, _ in rows):
        rows = [r for r in rows if r[0]]
    out: list[str] = []
    for _, line in rows:
        key = sitecheck._fold(plan_name(line))
        if 2 <= len(line) <= 120 and all(sitecheck._fold(plan_name(o)) != key for o in out):
            out.append(line)
    return out[:MAX_SECTIONS] or list(DEFAULT_PLAN)


def parse_css(s: str) -> str:
    m = _STYLE.search(s)
    css = m.group(1) if m else _unfence(s)
    css = css.replace("</style", "")  # birleştirilen sayfada style etiketini kapatıp kaçmasın
    return css.strip() if "{" in css else ""


def set_heading(fragment: str, name: str) -> str:
    """Bölüm başlığını Usta koyar: planın kısa adı ("Menü - tatlılar ve fiyatlar" → "Menü")."""
    h = f"<h2>{html.escape(name, quote=False)}</h2>"
    out, n = _H2.subn(h, fragment, count=1)
    return out if n else re.sub(r"(<section\b[^>]*>)", rf"\1\n{h}", fragment, count=1)


def parse_section(s: str, idx: int) -> str:
    body = _unfence(s)
    m = _SECTION.search(body)
    if m:
        body = m.group(0)
    else:
        body = _STYLE.sub("", _STRIP.sub("", body)).strip()
        if "<" not in body:
            body = "<p>" + html.escape(body) + "</p>"
        body = f'<section id="b{idx}">\n{body}\n</section>'
    return _STYLE.sub("", _STRIP.sub("", body)).strip()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style") and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


class _Blocks(HTMLParser):
    """Paragraf ve liste maddelerinin metni, ayrı ayrı (başlıklar ve betikler hariç)."""

    def __init__(self):
        super().__init__()
        self.blocks: list[str] = []
        self._cur: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")
        if tag in ("p", "li", "td"):
            self._cur = []

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style") and self._skip > 0
        if tag in ("p", "li", "td") and self._cur is not None:
            self.blocks.append(" ".join("".join(self._cur).split()))
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None and not self._skip:
            self._cur.append(data)


def invented_names(task: str, fragment: str) -> list[str]:
    """Bölümdeki yer/kurum adları (çok kelimeli özel ad ya da yer eki taşıyan: "… Düğün Salonu", "… Havalimanı")
    kullanıcının isteğinde yoksa. Tek kelimelik büyük harfli sözcükler ("Klasik", "Taze") sayılmaz; yanlış alarm çok."""
    known = set(re.findall(r"\w+", sitecheck._fold(task)))

    def given(w: str) -> bool:  # "Bursa'daki" → "bursa"; ek almış kelimeler kökünden tanınır
        return any(w.startswith(k[: max(3, len(k) - 2)]) or k.startswith(w) for k in known)

    p = _Blocks()
    p.feed(fragment)
    out: list[str] = []
    for block in p.blocks:
        for name in sitecheck._names(block):
            words = re.findall(r"\w+", sitecheck._fold(name))
            if not words or all(given(w) for w in words):
                continue
            if len(words) >= 2 or any(_PLACE_WORD.search(w) for w in words):
                out.append(name)
    return list(dict.fromkeys(out))


_HEADING = re.compile(r"<h[1-6]\b.*?</h[1-6]>", re.DOTALL | re.IGNORECASE)


def body_text(fragment: str) -> str:
    """Başlıklar dışındaki görünen metin (uydurma satırları silinince yalnız başlık kalan bölüm boş sayılır)."""
    return visible_text(_HEADING.sub(" ", fragment))


def visible_text(fragment: str) -> str:
    p = _Text()
    p.feed(fragment)
    return " ".join(" ".join(p.parts).split())


def _prices(text: str) -> set[float]:
    return {
        float(m.group(2).replace(",", "."))
        for m in sitecheck._PRICE.finditer(sitecheck._fold(text))
    }


def invented_prices(task: str, fragment: str) -> list[str]:
    """Bölümde geçen ama kullanıcının isteğinde olmayan fiyatlar (uydurma ürün belirtisi)."""
    given = _prices(task)
    return [f"{p:g} TL" for p in sorted(_prices(visible_text(fragment)) - given)]


def script_error(fragment: str) -> str:
    """Bölümdeki betiklerin sözdizimi hatası (node yoksa denetlenmez, boş döner)."""
    scripts = [s for s in _SCRIPT.findall(fragment) if s.strip()]
    node = shutil.which("node")
    if not scripts or not node:
        return ""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "b.js"
        f.write_text("\n;\n".join(scripts), encoding="utf-8")
        try:
            r = subprocess.run(
                [node, "--check", str(f)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if r.returncode == 0:
            return ""
        lines = [x for x in (r.stderr or "").splitlines() if "Error" in x]
        return (lines[0] if lines else "sözdizimi hatası")[:200]


_ELEMENT = re.compile(r"<(li|p|td)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)


def _made_up(task: str, element: str) -> bool:
    shown = visible_text(element)
    return bool(
        invented_prices(task, element)
        or invented_names(task, element)
        or any(m not in task for rx in (_TIME, _PHONE) for m in rx.findall(shown))
    )


def scrub(task: str, fragment: str) -> tuple[str, int]:
    """Yeniden yazdırmaya rağmen kalan uydurmalar: uydurma bilgi taşıyan paragraf/madde Usta tarafından silinir."""
    removed = 0

    def drop(m: re.Match) -> str:
        nonlocal removed
        if _made_up(task, m.group(0)):
            removed += 1
            return ""
        return m.group(0)

    return _ELEMENT.sub(drop, fragment), removed


def problems(task: str, fragment: str) -> list[str]:
    out = []
    if len(body_text(fragment)) < 3:
        out.append("bölümde başlık dışında metin yok")
    extra = invented_prices(task, fragment)
    if extra:
        out.append(f"kullanıcının vermediği fiyatlar var ({', '.join(extra[:4])}); bunları çıkar")
    shown = visible_text(fragment)
    for rx, what in ((_TIME, "saat"), (_PHONE, "telefon numarası")):
        made = [m for m in dict.fromkeys(rx.findall(shown)) if m not in task]
        if made:
            out.append(f"kullanıcının vermediği {what} var ({', '.join(made[:3])}); bunu çıkar")
    names = invented_names(task, fragment)
    if names:
        out.append(f"kullanıcının vermediği yer/isim var ({', '.join(names[:3])}); bunları çıkar")
    err = script_error(fragment)
    if err:
        out.append(f"betikte hata var: {err}")
    return out


def fix_note(task: str, fragment: str) -> str:
    """Yeniden yazdırma talimatı (İngilizce, olumlu): yalnız modelin kendi yazdığı uydurma parçaları anar, bilgi
    türlerini ("telefon, saat") saymaz; tür saymak küçük modele tam onları yazdırır."""
    shown = visible_text(fragment)
    made = [
        *invented_prices(task, fragment),
        *(m for rx in (_TIME, _PHONE) for m in dict.fromkeys(rx.findall(shown)) if m not in task),
        *invented_names(task, fragment),
    ]
    notes = []
    if len(body_text(fragment)) < 3:
        notes.append("write some Turkish text under the heading")
    if made:
        notes.append(
            "leave out these parts, they are not in the user's facts: "
            + ", ".join(m.strip(" :") for m in made[:6])
        )
    err = script_error(fragment)
    if err:
        notes.append(f"the script has an error ({err})")
    return ("Rewrite it using only the user's facts; " + "; ".join(notes) + ".\n") if notes else ""


def countdown(task: str) -> str:
    """İstekte sayaç ve tarih varsa Usta'nın hazır sayaç bölümü. Tarih kullanıcının isteğinden gelir, "bugün"
    tarayıcının saatinden; model betik yazmaz."""
    m = sitecheck._DATE.search(task or "")
    if not _COUNTDOWN.search(task or "") or not m:
        return ""
    d, mon, y = (
        int(m.group(1)),
        sitecheck._MONTHS.index(sitecheck._fold(m.group(2))) % 12 + 1,
        int(m.group(3)),
    )
    label = html.escape(f"{m.group(1)} {m.group(2)} {m.group(3)}")
    return (
        '<section id="sayac">\n<h2>Kaç gün kaldı?</h2>\n'
        f'<p>{label} tarihine <strong id="sayac-gun">…</strong> gün kaldı.</p>\n'
        "<script>\n(function () {\n"
        f"  var hedef = new Date({y}, {mon - 1}, {d});\n"
        "  var bugun = new Date(); bugun.setHours(0, 0, 0, 0);\n"
        "  var gun = Math.round((hedef - bugun) / 86400000);\n"
        '  document.getElementById("sayac-gun").textContent = gun > 0 ? gun : 0;\n'
        "})();\n</script>\n</section>"
    )


def assemble(title: str, css: str, sections: list[str], tail: str = "") -> str:
    parts = [f"<header>\n<h1>{html.escape(title)}</h1>\n</header>", *sections]
    body = "\n\n".join([*parts, tail] if tail else parts)
    css = f"{css}\n{LAYOUT_CSS}"
    return (
        '<!doctype html>\n<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>\n{css}\n</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _title(task: str, proposed: str = "") -> str:
    t = " ".join(_unfence(proposed).strip().strip("\"'#*").split())
    english = re.search(
        r"\b(?:about|me|my|the|welcome|page|website|home|of|our|your)\b", t, re.IGNORECASE
    )
    if 2 <= len(t) <= 60 and "<" not in t and not english:  # İngilizce başlık önerisi kabul edilmez
        return t
    names = sitecheck._names(task)
    for a, b in pairwise(names):  # "Ali ve Zeynep" tek kişi adından iyidir
        if f"{a} ve {b}" in task:
            return f"{a} ve {b}"
    return names[0] if names else "Sitem"


def _words(fragment: str) -> set[str]:
    return set(re.findall(r"\w+", sitecheck._fold(visible_text(fragment))))


def duplicate(fragment: str, earlier: list[str]) -> bool:
    """Bölümün metni önceki bir bölümün neredeyse aynısı mı (küçük model aynı menüyü iki kez yazdı)."""
    w = _words(fragment)
    h = _H2.search(fragment)
    head = sitecheck._fold(visible_text(h.group(1))) if h else ""

    def same_head(e: str) -> bool:
        m = _H2.search(e)
        return bool(head) and m is not None and sitecheck._fold(visible_text(m.group(1))) == head

    return bool(w) and any(same_head(e) or len(w & _words(e)) >= 0.7 * len(w) for e in earlier)


_TAGS = re.compile(r"<[^>]+>")


def _clean_piece(s: str) -> str:
    text = _TAGS.sub(" ", _unfence(s))
    text = " ".join(text.replace("**", "").split()).strip("\"'“” ")
    return text[:400]


def piece_problems(task: str, text: str) -> list[str]:
    if len(text) < 3:
        return ["metin yok"]
    out = []
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text):
        out.append("Türkçe olmayan harfler var")
    if len(re.findall(r"[.!?]+(?:\s|$)", text + " ")) > 3:
        out.append("çok uzun, en çok iki cümle yaz")
    return out + problems(task, f"<section><p>{html.escape(text, quote=False)}</p></section>")


def _cap(word: str) -> str:
    return ("İ" if word[:1] == "i" else word[:1].upper()) + word[1:]


def fact_rows(task: str, only: list[str] | None = None) -> list[str]:
    """Kullanıcının bilgileri, Usta'nın yazdığı satırlar olarak ("Baklava - 120 TL", "Tarih: 14 Haziran 2027").
    `only` verilirse yalnız o etiketlerden birini taşıyan satırlar."""
    rows: list[tuple[str, set[str]]] = []
    for m in sitecheck._PRICE.finditer(task):
        item, num = m.group(1), m.group(2)
        word = item.split()[-1] if item else ""
        if word and sitecheck._fold(word) not in sitecheck._SKIP_ITEM:
            rows.append((f"{html.escape(_cap(word))} - {num} TL", {word, f"{num} TL"}))
        else:
            rows.append((f"{num} TL", {f"{num} TL"}))
    for d, mon, y in sitecheck._DATE.findall(task):
        rows.append((f"Tarih: {d} {mon} {y}", {f"{d} {mon} {y}"}))
    for e in sitecheck._EMAIL.findall(task):
        rows.append((f'E-posta: <a href="mailto:{html.escape(e)}">{html.escape(e)}</a>', {e}))
    used = {lab for _, labs in rows for lab in labs}
    names = [n for n in sitecheck._names(task) if n not in used]
    if names:
        rows.append((html.escape(", ".join(names)), set(names)))
    if only is None:
        return [r for r, _ in rows]
    return [r for r, labs in rows if labs & set(only)]


def fact_sections(task: str) -> list[str]:
    """Seviye 1 için bilgi bölümleri: fiyatlar → Menü, diğerleri → Bilgiler."""
    rows = fact_rows(task)
    menu = [r for r in rows if r.endswith(" TL") and not r.startswith(("Tarih", "E-posta"))]
    rest = [r for r in rows if r not in menu]
    out = []
    for title, items in (("Menü", menu), ("Bilgiler", rest)):
        if items:
            lis = "\n".join(f"<li>{r}</li>" for r in items)
            out.append(f"<section>\n<h2>{title}</h2>\n<ul>\n{lis}\n</ul>\n</section>")
    return out


class SiteBuilder:
    def __init__(
        self,
        model: ModelClient,
        task: str,
        write: Callable[[str, str], str],
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        level: int = 2,
    ):
        self.level = level  # 2: bölüm bölüm, 1: en küçük parçalar (skillprobe.py)
        self.model, self.task, self.write = model, task, write
        self.progress = progress or (lambda _m: None)
        self.cancelled = cancelled or (lambda: False)
        self.facts = [label for label, _ in sitecheck.facts(task)]
        self.log: list[str] = []  # kullanıcıya gösterilecek yapılacaklar listesi

    def _ask(self, prompt: str) -> str:
        return _text(self.model.chat([Message("system", SYSTEM), Message("user", prompt)], None))

    def _step(self, line: str) -> None:
        self.log.append(line)
        self.progress(line)

    def _facts_note(self) -> str:
        if not self.facts:
            return ""
        return "The user's facts (copy them exactly as written): " + ", ".join(self.facts) + ".\n"

    def _section(self, idx: int, item: str, plan: list[str], fix: str = "") -> str:
        script = (
            "If this section needs a button or animation, you may add a short <script> that only uses elements of "
            "this section by id.\n"
            if _SCRIPT_WANTED.search(item)
            else "Use HTML only.\n"
        )
        prompt = (
            f"{USER}{self.task}\n{self._facts_note()}"
            f"Site sections: {'; '.join(plan)}.\n"
            f"Now write only this section: {item}\n"
            f'Output exactly one <section id="b{idx}"> ... </section> using h2, p and ul inside. The page frame '
            "(html, head, style) is added by the system. Put only the facts that belong to this section.\n"
            f"{script}{fix}"
        )
        return set_heading(parse_section(self._ask(prompt), idx), plan_name(item))

    def _piece(self, what: str) -> str:
        """En küçük birim: kısa düz metin (HTML yok), denetlenir; olmazsa boş (modelin sağlıklı yapabildiği
        en küçük parça)."""
        fix = ""
        for _ in range(2):
            text = _clean_piece(
                self._ask(
                    f"{USER}{self.task}\n{self._facts_note()}"
                    f"{what} Write at most two short, plain sentences in Turkish, as plain text. Use only the "
                    f"user's facts.\n{fix}"
                )
            )
            issues = piece_problems(self.task, text)
            if not issues:
                return text
            fix = fix_note(self.task, f"<section><p>{html.escape(text)}</p></section>") or (
                "Rewrite it as at most two short plain Turkish sentences."
            )
        return ""

    def _small_section(self, name: str) -> str:
        """Bölümü en küçük parçalarla kurar: başlığı Usta koyar, model yalnız kısa metni yazar."""
        text = self._piece(f'Write a short text for the "{name}" section of the site.')
        if not text:
            return ""
        return f"<section>\n<h2>{html.escape(name)}</h2>\n<p>{html.escape(text, quote=False)}</p>\n</section>"

    def _plan(self) -> list[str]:
        return parse_plan(
            self._ask(
                f"{USER}{self.task}\n{self._facts_note()}"
                f"Plan this one-page website in 2 to {MAX_SECTIONS - 1} sections. One section per line: short Turkish "
                "name - what it contains. Each fact appears in exactly one section. Base everything on the user's "
                "facts. Output only the lines."
            )
        )

    def _title(self) -> str:
        return _title(
            self.task,
            self._ask(
                f"{USER}{self.task}\nWrite a Turkish title for this website, at most 6 words. Output only the title."
            ),
        )

    def _css(self, plan: list[str]) -> str:
        css = parse_css(
            self._ask(
                f"{USER}{self.task}\nSections: {'; '.join(plan)}.\n"
                "Write simple, readable CSS for this site that also works on small screens. Selectors: body, header, "
                "section, h1, h2, p, ul, li, a, footer, .kart. Output only CSS."
            )
        )
        self._step(
            "✓ Tasarım (renk ve yazı)"
            if css
            else "• Tasarım yazılamadı, Usta'nın hazır görünümü kullanıldı"
        )
        return css or DEFAULT_CSS

    def _sections_level2(
        self, plan: list[str], tail: str
    ) -> tuple[list[str], list[tuple[int, str]]]:
        sections: list[str] = []
        kept: list[
            tuple[int, str]
        ] = []  # yazılan bölümlerin plandaki sırası ve adı (tekrarlar çıkarılır)
        for i, item in enumerate(plan):
            if self.cancelled():
                break
            if tail and _COUNTDOWN.search(item):
                continue  # sayaç bölümünü Usta hazır parçayla koyar
            name = plan_name(item)
            smaller = False
            frag = self._section(i, item, plan)
            issues = problems(self.task, frag)
            if issues:
                frag2 = self._section(
                    i,
                    item,
                    plan,
                    fix=fix_note(self.task, frag),
                )
                if len(problems(self.task, frag2)) <= len(issues):
                    frag, issues = frag2, problems(self.task, frag2)
            if issues:
                cleaned, n = scrub(self.task, frag)
                if n and len(body_text(cleaned)) >= 3:
                    frag, issues = cleaned, problems(self.task, cleaned)
                    self._step(f"• {name}: uydurma bilgi taşıyan {n} satırı Usta sildi")
            if issues:
                # iki denemede olmadı: bir basamak aşağı, daha küçük parçalarla
                small = self._small_section(name)
                self._step(
                    f"↓ {name}: daha küçük parçalarla yeniden yapıldı"
                    if small
                    else f"• {name} çıkarıldı (sağlıklı yazılamadı)"
                )
                if not small:
                    continue
                frag, issues, smaller = small, [], True
            if duplicate(frag, sections):
                self._step(f"• {name} çıkarıldı (önceki bir bölümün tekrarı)")
                continue
            if not smaller:
                self._step(f"✓ {name}")
            sections.append(frag)
            kept.append((i, item))
        return sections, kept

    def _sections_level1(self) -> list[str]:
        """Seviye 1: iskelet ve bilgiler Usta'dan; model yalnız kısa bir tanıtım yazar."""
        sections = []
        intro = self._piece("Write a short welcome text for this site.")
        if intro:
            sections.append(
                f"<section>\n<h2>Hoş geldiniz</h2>\n<p>{html.escape(intro, quote=False)}</p>\n</section>"
            )
            self._step("✓ Tanıtım (kısa metin)")
        else:
            self._step("• Tanıtım yazılamadı, yalnız bilgiler kondu")
        sections.extend(fact_sections(self.task))
        self._step("✓ Bilgiler (Usta yerleştirdi)")
        return sections

    def _repair(self, plan, sections, kept, page_of) -> list[str]:
        """Eksik bilgiyi modele ekletir; olmazsa Usta kendisi bir bilgi bölümü ekler."""
        lack = sitecheck.missing(self.task, [page_of(sections)])
        if lack and kept and not self.cancelled():
            # eksik bilgi, kullanıcının bilgilerinden en çoğunu zaten taşıyan bölüme eklenir (menüde eksik kalan
            # tatlı menüye; planda adı geçiyorsa o bölüme)
            total = len(self.facts)
            target = next(
                (
                    k
                    for k, (_, p) in enumerate(kept)
                    if any(sitecheck._fold(f) in sitecheck._fold(p) for f in lack)
                ),
                max(
                    range(len(kept)),
                    key=lambda k: total - len(sitecheck.missing(self.task, [sections[k]])),
                ),
            )
            frag = self._section(
                kept[target][0],
                kept[target][1],
                plan,
                fix=f"These facts are missing from the page; add them to this section exactly as written: "
                f"{', '.join(lack)}.\n",
            )
            if not problems(self.task, frag):
                sections = [*sections[:target], frag, *sections[target + 1 :]]
                lack = sitecheck.missing(self.task, [page_of(sections)])
        if lack:
            rows = fact_rows(self.task, only=lack)
            if rows:
                items = "\n".join(f"<li>{r}</li>" for r in rows)
                sections = [
                    *sections,
                    f"<section>\n<h2>Bilgiler</h2>\n<ul>\n{items}\n</ul>\n</section>",
                ]
                self._step(f"✓ Eksik bilgileri Usta ekledi: {', '.join(lack)}")
                lack = sitecheck.missing(self.task, [page_of(sections)])
        self._step(
            "✓ Bilgilerin hepsi sayfada"
            if not lack
            else f"• Sayfada eksik bilgi: {', '.join(lack)}"
        )
        return sections

    def run(self) -> tuple[str, bool]:
        """(kullanıcıya yanıt, sayfa yazıldı mı)."""
        tail = countdown(self.task)
        if self.level <= 1:
            self._step("Plan: tanıtım → bilgiler" + (" → gün sayacı" if tail else ""))
            title, plan, kept = self._title(), [], []
            css = DEFAULT_CSS
            sections = self._sections_level1()
        else:
            plan = self._plan()
            self._step("Plan: " + " → ".join(plan_name(p) for p in plan))
            title = self._title()
            if self.cancelled():
                return "(görev durduruldu)", False
            css = self._css(plan)
            sections, kept = self._sections_level2(plan, tail)
        if self.cancelled():
            return "(görev durduruldu)", False
        if tail:
            self._step("✓ Gün sayacı (Usta'nın hazır parçası)")
        sections = self._repair(plan, sections, kept, lambda secs: assemble(title, css, secs, tail))
        page = assemble(title, css, sections, tail)
        result = self.write("index.html", page)
        ok = not result.startswith(("reddedildi", "hata"))
        self._step("✓ index.html yazıldı" if ok else f"• index.html yazılamadı: {result[:120]}")
        end = (
            "Sayfanız hazır: index.html dosyasını çift tıklayarak tarayıcıda açabilirsiniz."
            if ok
            else "Sayfayı yazamadım."
        )
        return "Yapılanlar:\n" + "\n".join(self.log) + "\n\n" + end, ok
