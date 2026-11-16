"""Site/sayfa isteğinde kullanıcının verdiği bilgiler sayfaya girdi mi (kural; model çağrısı yok).

Kodsuz kullanıcı isteğine somut bilgiler yazar: adı, e-postası, ürün ve fiyatları, tarih, şehir. 16 Kasım ölçümünde
(DeepSeek-V4-Pro-Qwen3.5-9B, kodsuz kullanıcı gibi üç site isteği) küçük model sayfayı yazdı ama bilgileri eksik ya da
değiştirerek koydu ("Sütlaç" yerine "Süt Laç"), bitti dedi. Bu modül istekten bilgileri çıkarır ve yazılan sayfada
arar; eksik olanlar söz–eylem denetimi (finishcheck.py) üzerinden modele bir kez söylenir.

Sezgiseldir: özel isimleri büyük harfle başlayan (cümle başında olmayan) kelimelerden çıkarır. Eşleşme büyük/küçük harf
ve Türkçe İ/ı farkını yok sayar; sayfanın kaynağında (metin ya da betik) geçmesi yeter. Fiyat yalnız para
birimiyle, tarih yazıyla ya da sayıyla (2027-06-14, 14.06.2027) sayılır.
"""

from __future__ import annotations

import html
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CUR = r"(?:tl|₺|lira|\$|€|usd|eur)"
# "baklava 120 TL": ürün adı (fiyattan önceki en çok iki küçük harfli kelime) ve fiyat
_PRICE = re.compile(
    rf"(?:([a-zçğıöşü]+(?:\s+[a-zçğıöşü]+)?)\s+)?(\d+(?:[.,]\d+)?)\s*{_CUR}(?!\w)", re.IGNORECASE
)
_MONTHS = [
    "ocak",
    "şubat",
    "mart",
    "nisan",
    "mayıs",
    "haziran",
    "temmuz",
    "ağustos",
    "eylül",
    "ekim",
    "kasım",
    "aralık",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_DATE = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(_MONTHS)})\s+(\d{{4}})\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû'’]+|[.!?:;,()]")
_UPPER = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZQWX"
# fiyattan önce gelen ama ürün adı olmayan kelimeler ("toplam 120 TL", "fiyatı 80 TL")
_SKIP_ITEM = {
    "fiyat",
    "fiyatı",
    "toplam",
    "ücret",
    "ücreti",
    "tane",
    "adet",
    "ise",
    "ve",
    "de",
    "da",
    "için",
}
# büyük harfle başlasa da bilgi sayılmayanlar (hitap, kısaltma)
_SKIP = {"tl", "usd", "eur", "html", "css", "js", "web", "merhaba", "selam"}


def _fold(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower().replace("’", "'")


def _names(task: str) -> list[str]:
    """Cümle başında olmayan, büyük harfle başlayan ardışık kelimeler: "Tatlı Köşe", "Nilüfer", "Ayşe"."""
    out: list[str] = []
    run: list[str] = []
    start = True  # cümle başı
    for tok in _WORD.findall(task):
        if tok in ".!?:;,()":
            # iki nokta ve virgülden sonra gelen ad cümle başı değildir ("istiyorum: Ali")
            start = tok in ".!?"
            if run:
                out.append(" ".join(run))
                run = []
            continue
        word = re.split(r"['’]", tok)[0]  # "Ayşe'nin" → "Ayşe"
        cap = word[:1] in _UPPER and not word.isupper()
        if cap and not start and _fold(word) not in _SKIP and _fold(word) not in _MONTHS:
            run.append(word)
        elif run:
            out.append(" ".join(run))
            run = []
        start = False
    if run:
        out.append(" ".join(run))
    return out


def facts(task: str) -> list[tuple[str, tuple[str, ...]]]:
    """İstekteki bilgiler: (gösterilecek ad, sayfada aranacak düzenli ifadeler). Biri geçerse bilgi var sayılır."""
    found: list[tuple[str, tuple[str, ...]]] = []

    def add(label: str, *alts: str) -> None:
        if label and all(label != f[0] for f in found):
            found.append((label, alts))

    def lit(s: str) -> str:
        return re.escape(_fold(s)).replace(r"\ ", r"\s+")

    for e in _EMAIL.findall(task):
        add(e, lit(e))
    for m in _PRICE.finditer(task):
        item, num = m.group(1), m.group(2)
        if item and _fold(item.split()[-1]) not in _SKIP_ITEM:
            add(item.split()[-1], lit(item.split()[-1]))
        n = re.escape(num)
        # "120 TL", "120,00 ₺", "₺120": sayı yalnız para birimiyle sayılır (CSS'teki 120px eşleşmesin)
        add(f"{num} TL", rf"(?<![\d.,]){n}(?:[.,]0+)?\s*{_CUR}", rf"[₺$€]\s*{n}(?![\d])")
    for d, mon, y in _DATE.findall(task):
        num = _MONTHS.index(_fold(mon)) % 12 + 1
        add(
            f"{d} {mon} {y}",
            lit(f"{d} {mon}"),
            rf"{y}\s*[-/.,]\s*0?{num}\s*[-/.,]\s*0?{int(d)}(?!\d)",
            rf"(?<!\d)0?{int(d)}\s*[./-]\s*0?{num}\s*[./-]\s*{y}",
        )
    for n in _names(task):
        add(n, lit(n))
    return found


def missing(task: str, pages: list[str]) -> list[str]:
    """Sayfalarda hiçbir seçeneği geçmeyen bilgiler."""
    text = _fold(html.unescape("\n".join(pages)))
    return [label for label, alts in facts(task) if not any(re.search(a, text) for a in alts)]
