"""Bölüm bölüm site kurma (DENEYSEL, varsayılan kapalı: `USTA_SITE_STEPS=1`).

Kodsuz kullanıcının "bana bir site yap" isteğinde küçük model tüm sayfayı tek seferde yazınca her şey birden bozuluyor
(16 Kasım ölçümü, 9B: uydurma ürün ve düğün salonu, bozuk sayaç, eksik bilgi). Burada iş parçalanır:

1. Model kısa bir plan yazar (her satır bir bölüm). Kullanıcıya yapılacaklar listesi olarak gösterilir.
2. Model tasarımı (CSS) ayrı yazar.
3. Her bölüm ayrı, küçük bir istekle yazılır ve hemen denetlenir: içinde metin var mı, kullanıcının vermediği fiyat
   var mı, betik varsa sözdizimi doğru mu (node varsa). Sorunlu bölüm bir kez yeniden yazdırılır.
4. Usta parçaları tek index.html'de birleştirir (modelin yazdığı değil, sabit iskelet) ve kullanıcının verdiği
   bilgilerin sayfada olup olmadığına bakar; eksik varsa ilgili bölüm bir kez daha yazdırılır.

Her istek kısa olduğu için küçük bağlam yeter; model hiçbir aracı çağırmaz. Dosya yazma ajanın olağan yolundan geçer
(izin, denetim kaydı, geri alma). Yalnız yeni site isteklerinde çalışır: istekte dosya adı geçiyorsa ya da klasörde
zaten bir .html varsa olağan ajan döngüsü kullanılır.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from html.parser import HTMLParser
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
# Sayfa düzeni Usta'nındır: modelin CSS'i renk ve yazıyı seçer, düzeni bozamaz (16 Kasım, 4B: body'yi flex yapıp
# bölümleri yan yana dizdi)
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
_TIME = re.compile(r"(?<![\d:])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])")
_PHONE = re.compile(r"(?<!\d)(?:\+?90[\s-]?)?\(?0?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")
_H2 = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.DOTALL | re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

SYSTEM = (
    "Sen bir web sitesinin tek bir parçasını yazan yardımcısın. Yalnız istenen parçayı yaz, açıklama yapma. "
    "Kullanıcının vermediği bilgi (ürün, fiyat, isim, adres, tarih) uydurma. Metinler Türkçe olsun."
)


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
    """Modelin planından bölüm satırları. 4B planı başlıklı ve iç içe yazdı ("*Hobilerim" altında "Resim yapma"):
    vurgulu satırlarla vurgusuzlar karışıksa yalnız vurgulular bölüm sayılır; "Bölüm Planı" gibi başlıklar atılır."""
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


def problems(task: str, fragment: str) -> list[str]:
    out = []
    if len(visible_text(fragment)) < 3:
        out.append("bölümde görünen metin yok")
    extra = invented_prices(task, fragment)
    if extra:
        out.append(f"kullanıcının vermediği fiyatlar var ({', '.join(extra[:4])}); bunları çıkar")
    shown = visible_text(fragment)
    for rx, what in ((_TIME, "saat"), (_PHONE, "telefon numarası")):
        made = [m for m in dict.fromkeys(rx.findall(shown)) if m not in task]
        if made:
            out.append(f"kullanıcının vermediği {what} var ({', '.join(made[:3])}); bunu çıkar")
    err = script_error(fragment)
    if err:
        out.append(f"betikte hata var: {err}")
    return out


def countdown(task: str) -> str:
    """İstekte sayaç ve tarih varsa Usta'nın hazır sayaç bölümü (16 Kasım: 9B'nin sayacı üç turda da bozuktu, 4B
    "bugünü" 2024 diye sabit yazdı). Tarih kullanıcının isteğinden gelir; model betik yazmaz."""
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
    if 2 <= len(t) <= 60 and "<" not in t:
        return t
    names = sitecheck._names(task)
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


class SiteBuilder:
    def __init__(
        self,
        model: ModelClient,
        task: str,
        write: Callable[[str, str], str],
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
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
        return (
            "Kullanıcının verdiği bilgiler (aynen yaz, değiştirme): "
            + ", ".join(self.facts)
            + ".\n"
        )

    def _section(self, idx: int, item: str, plan: list[str], fix: str = "") -> str:
        script = (
            "Bu bölüm bir sayaç ya da etkileşim gerektiriyorsa kısa bir <script> ekleyebilirsin; betik yalnız bu "
            "bölümdeki öğelere id ile erişsin.\n"
            if _SCRIPT_WANTED.search(item)
            else "Betik (script) yazma.\n"
        )
        prompt = (
            f"Kullanıcının isteği: {self.task}\n{self._facts_note()}"
            f"Sitenin bölümleri: {'; '.join(plan)}.\n"
            f"Şimdi yalnız şu bölümü yaz: {item}\n"
            f'Çıktın tek bir <section id="b{idx}"> ... </section> olsun (içinde h2, p, ul gibi etiketler). '
            "Diğer bölümleri, <html>, <head>, <style> yazma. Bu bölüme ait olmayan bilgiyi koyma.\n"
            f"{script}{fix}"
        )
        return parse_section(self._ask(prompt), idx)

    def run(self) -> tuple[str, bool]:
        """(kullanıcıya yanıt, sayfa yazıldı mı)."""
        plan = parse_plan(
            self._ask(
                f"Kullanıcının isteği: {self.task}\n{self._facts_note()}"
                f"Bu tek sayfalık site için 2 ile {MAX_SECTIONS - 1} arası bölüm planla. Her satıra bir bölüm yaz: kısa ad - "
                "içinde ne olacağı. Her bilgi yalnız bir bölümde olsun, aynı içerikte iki bölüm olmasın. Yalnız "
                "kullanıcının verdiği bilgilere dayan. Başka bir şey yazma."
            )
        )
        self._step("Plan: " + " → ".join(plan_name(p) for p in plan))
        title = _title(
            self.task,
            self._ask(
                f"Kullanıcının isteği: {self.task}\nBu site için en çok 6 kelimelik bir başlık yaz. Yalnız başlığı yaz."
            ),
        )
        if self.cancelled():
            return "(görev durduruldu)", False
        css = parse_css(
            self._ask(
                f"Kullanıcının isteği: {self.task}\nBölümler: {'; '.join(plan)}.\n"
                "Bu site için sade, okunaklı, telefonda da düzgün görünen bir CSS yaz. Seçiciler: body, header, "
                "section, h1, h2, p, ul, li, a, footer, .kart. Yalnız CSS yaz."
            )
        )
        self._step(
            "✓ Tasarım (renk ve yazı)" if css else "• Tasarım yazılamadı, sade görünüm kullanıldı"
        )
        sections: list[str] = []
        kept: list[
            tuple[int, str]
        ] = []  # yazılan bölümlerin plandaki sırası ve adı (tekrarlar çıkarılır)
        tail = countdown(self.task)
        for i, item in enumerate(plan):
            if self.cancelled():
                return "(görev durduruldu)", False
            if tail and _COUNTDOWN.search(item):
                continue  # sayaç bölümünü Usta hazır parçayla koyar
            frag = self._section(i, item, plan)
            issues = problems(self.task, frag)
            if issues:
                frag2 = self._section(
                    i, item, plan, fix="Önceki denemede sorun vardı: " + "; ".join(issues) + ".\n"
                )
                if len(problems(self.task, frag2)) <= len(issues):
                    frag, issues = frag2, problems(self.task, frag2)
            name = plan_name(item)
            if duplicate(frag, sections):
                self._step(f"• {name} çıkarıldı (önceki bir bölümün tekrarı)")
                continue
            self._step(
                f"✓ {name}" if not issues else f"• {name} (sorun kaldı: {'; '.join(issues)})"
            )
            sections.append(frag)
            kept.append((i, item))
        if tail:
            self._step("✓ Gün sayacı (Usta'nın hazır parçası)")
        page = assemble(title, css, sections, tail)
        lack = sitecheck.missing(self.task, [page])
        if lack and sections and not self.cancelled():
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
                fix=f"Şu bilgiler sayfada eksik, bu bölüme aynen ekle: {', '.join(lack)}.\n",
            )
            if not problems(self.task, frag):
                sections[target] = frag
                page = assemble(title, css, sections, tail)
                lack = sitecheck.missing(self.task, [page])
        self._step(
            "✓ Bilgilerin hepsi sayfada"
            if not lack
            else f"• Sayfada eksik bilgi: {', '.join(lack)}"
        )
        result = self.write("index.html", page)
        ok = not result.startswith(("reddedildi", "hata"))
        self._step("✓ index.html yazıldı" if ok else f"• index.html yazılamadı: {result[:120]}")
        tail = (
            "Sayfanız hazır: index.html dosyasını çift tıklayarak tarayıcıda açabilirsiniz."
            if ok
            else "Sayfayı yazamadım."
        )
        return "Yapılanlar:\n" + "\n".join(self.log) + "\n\n" + tail, ok
