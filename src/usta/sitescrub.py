"""Modelin yazdığı site bölümünde uydurma bilgi (ad, yer, saat, telefon, fiyat) ve betik hatası arar; uydurma satırları temizler."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from usta import sitecheck

_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


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
