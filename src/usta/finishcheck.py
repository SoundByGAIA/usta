"""Bitirme anında söz–eylem denetimi: küçük modellerin "erken bitirme" hataları.

Küçük modeller sık sık şunları yapar:

- yalnız klasörü listeleyip "summary.txt dosyasına yazıldı" deyip bitirmek,
- görev açıkça "dosyaya yaz" derken "yazmamı ister misiniz?" diye sormak,
- sonucu dosya yerine yanıta yazmak ya da boş yanıtla bitirmek,
- "dosyaları kontrol ediyorum" deyip araç çağırmadan bitirmek.

İlk üçü tek kuralla yakalanır: kullanıcının isteğinde yazılması istenen hedef dosya ("X dosyasına yaz", "X'e kaydet",
"write to X") bitirme anında hâlâ yazılmamışsa kısa bir hatırlatma yapılır. Hedef yalnız kullanıcının kendi isteğinden
çıkarılır; yalnız okunan kaynak dosyalar ("X dosyasındaki") ve modelin yanıtında geçen başka dosyalar hedef sayılmaz.

Dosya adı vermeyen site/sayfa isteklerinde ("web sitesi yap") hiç dosya yazılmadan kod yanıta dökülür, "oluşturdum"
denir ya da izin sorulursa; sayfa yazılmışsa da kullanıcının verdiği bilgiler sayfada yoksa ya da bir yazı zeminiyle
aynı renkte olduğu için görünmüyorsa (`sitecontrast.py`) bir kez hatırlatılır.

Okunan bir içeriğin uydurduğu dosyayı yazmaya itilmez; hatırlatmalar izin ve onay kurallarını değiştirmez. Görev başına
en çok iki hatırlatma. Ölçüm: docs/olcumler/soz-eylem.md. Kapatmak: `--no-finish-check` ya da `USTA_FINISH_CHECK=0`.
"""

from __future__ import annotations

import re
from pathlib import Path

from usta import sitecheck, sitecontrast

WRITE_TOOLS = ("write_file", "edit_file")
_P = r"[\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]{1,6}"
_WRITE_VERB = r"(?:yaz|kaydet|ekle|oluştur|aktar)\w*"
# Türkçe yönelme hâli: "X dosyasına yaz", "X'e kaydet", "X’ye yaz" (fiil en çok 3 kelime sonra)
_TARGET_TR = re.compile(
    rf"(?<![\w/.-])({_P})(?:\s+dosyas[ıi]na|['’](?:y)?[ae])\s+(?:\S+\s+){{0,3}}?{_WRITE_VERB}",
    re.IGNORECASE,
)
_TARGET_EN = re.compile(
    rf"\b(?:write|save|append|output)\b[^.\n]{{0,60}}?\b(?:to|into|in)\s+(?:the\s+file\s+)?`?({_P})",
    re.IGNORECASE,
)
_CLAIM = re.compile(
    r"yazıldı|yazdım|kaydedildi|kaydettim|oluşturuldu|oluşturdum|eklendi|ekledim|güncellendi|güncelledim"
    r"|\b(?:written|wrote|saved|created|updated)\b",
    re.IGNORECASE,
)
# 1. tekil şimdiki/gelecek zaman ("kontrol ediyorum", "yazacağım"), 1. çoğul istek ("bakalım", "görelim")
# ya da İngilizce niyet ("Let me", "I'll")
_INTENT = re.compile(
    r"\w+(?:ıyorum|iyorum|uyorum|üyorum|acağım|eceğim|alım|elim)\b|\b(?:let me|let's|i'll|i will|i'm going to)\b",
    re.IGNORECASE,
)
MAX_INTENT_CHARS = 240
# kodsuz kullanıcı dosya adı vermez: "web sitesi yap", "menümü gösteren bir sayfa istiyorum"
_ARTIFACT = re.compile(
    r"\b(?:web\s*)?site\w*|\bsayfa\w*|\bweb\s*page|\bwebsite|\blanding\s*page|\bhomepage",
    re.IGNORECASE,
)
_CODE_IN_ANSWER = re.compile(r"```|<html|<!doctype", re.IGNORECASE)
# yapmak için izin sormak ("oluşturayım mı?", "shall I")
_ASK_TO_BUILD = re.compile(
    r"(?:yap|oluştur|hazırla|başla|yaz)\w*\s+m[ıiuü]\w*\s*\?|ister\s+misiniz|ister\s+misin|shall\s+i|should\s+i|want\s+me\s+to",
    re.IGNORECASE,
)


def write_targets(task: str) -> list[str]:
    """Kullanıcının isteğinde yazılması istenen dosyalar (sıralı, tekrarsız)."""
    found: list[str] = []
    for rx in (_TARGET_TR, _TARGET_EN):
        for m in rx.finditer(task or ""):
            if m.group(1) not in found:
                found.append(m.group(1))
    return found


class FinishCheck:
    def __init__(self, task: str = "", max_nudges: int = 2, root: Path | None = None):
        self.task = task or ""
        self.root = (
            root  # verilirse site isteğinde yazılan sayfalar kullanıcının bilgileri için okunur
        )
        self.max_nudges = max_nudges
        self.targets = write_targets(self.task)
        self.written: set[str] = set()
        self.artifact = bool(_ARTIFACT.search(self.task))
        self.pages: list[str] = []  # bu görevde yazılan .html dosyaları (özgün yazımıyla)
        self.wrote_any = False  # bu görevde herhangi bir dosya yazıldı mı (ya da komut çalıştı mı)
        self.nudges = 0
        self.fired: list[str] = []  # tetiklenen kurallar (Lab kaydı için)

    @staticmethod
    def _norm(path: str) -> str:
        p = str(path or "").replace("\\", "/").strip()
        while p.startswith("./"):
            p = p[2:]
        return p.lower()

    def observe(self, tool: str, args: dict, executed: bool) -> None:
        """Gerçekten yapılan yazmaları kaydeder (reddedilen/başarısız çağrılar sayılmaz)."""
        if executed and tool in WRITE_TOOLS and isinstance(args.get("path"), str):
            self.written.add(self._norm(args["path"]))
            if args["path"].lower().endswith((".html", ".htm")) and args["path"] not in self.pages:
                self.pages.append(args["path"])
        if executed and tool in (*WRITE_TOOLS, "run"):
            self.wrote_any = True
        # komutla yazma ("echo 3 > count.txt"): hedef adı geçen bir komut çalıştıysa dosya yazılmış sayılır
        if executed and tool == "run" and isinstance(args.get("command"), str):
            cmd = args["command"].replace("\\", "/").lower()
            self.written.update(self._norm(t) for t in self.targets if self._norm(t) in cmd)

    def _nudge(self, rule: str, message: str) -> str | None:
        if self.nudges >= self.max_nudges or rule in self.fired:
            return None
        self.fired.append(rule)
        self.nudges += 1
        return message

    def _read(self, rel: str) -> str | None:
        """Çalışma klasöründeki bir dosya (dışarısı ya da okunamayan dosya için None)."""
        root = Path(self.root).resolve()
        try:
            f = (root / rel).resolve()
            if f.is_relative_to(root) and f.is_file():
                return f.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            pass
        return None

    def _page_texts(self) -> list[str]:
        if self.root is None:
            return []
        return [t for t in (self._read(rel) for rel in self.pages[:5]) if t is not None]

    def _missing_facts(self) -> list[str]:
        """Site isteğindeki bilgilerden yazılan sayfalarda geçmeyenler (kök verilmediyse ya da sayfa yoksa boş)."""
        texts = self._page_texts()
        return sitecheck.missing(self.task, texts) if texts else []

    def _hidden_texts(self) -> list[str]:
        """Yazılan sayfalarda zemin rengiyle aynı renkte olduğu için görünmeyen metinler."""
        found: list[str] = []
        for rel in self.pages[:5] if self.root is not None else []:
            html = self._read(rel)
            if html is None:
                continue
            css = []
            for href in re.findall(
                r"<link[^>]+href=[\"']([^\"':?#]+\.css)[\"']", html, re.IGNORECASE
            )[:5]:
                css.append(self._read(str(Path(rel).parent / href)) or "")
            found += [t for t in sitecontrast.hidden_texts(html, "\n".join(css)) if t not in found]
        return found

    def on_finish(self, answer: str) -> str | None:
        """Model araç çağırmadan bitirmek istiyor: hatırlatma mesajı ya da None (bitir)."""
        text = (answer or "").strip()
        missing = [p for p in self.targets if self._norm(p) not in self.written]
        if missing:
            said = "yazdığını söylüyorsun ama " if _CLAIM.search(text) else ""
            return self._nudge(
                "target",
                f"Görev `{missing[0]}` dosyasına yazmanı istiyor; {said}bu görevde o dosyaya henüz yazmadın. "
                "İzin sormana gerek yok: istenen sonucu şimdi write_file ile yaz. Yazamıyorsan nedenini kısaca söyle.",
            )
        if (
            self.artifact
            and not self.wrote_any
            and (_CODE_IN_ANSWER.search(text) or _CLAIM.search(text) or _ASK_TO_BUILD.search(text))
        ):
            return self._nudge(
                "artifact",
                "Kullanıcı bir site/sayfa istedi ama bu görevde hiçbir dosya yazmadın; kodu yanıta yazmak yetmez, "
                "kullanıcı onu açamaz. Sayfayı şimdi write_file ile yaz (ör. index.html), sonra kısaca ne yaptığını söyle.",
            )
        lack = self._missing_facts() if self.artifact and self.wrote_any else []
        if lack:
            return self._nudge(
                "facts",
                f"Kullanıcının verdiği şu bilgiler yazdığın sayfada yok ya da değişmiş: {', '.join(lack[:8])}. "
                "Sayfayı oku, bunları kullanıcının yazdığı gibi ekle; kullanıcının vermediği bilgi (ürün, fiyat, isim) "
                "uydurma.",
            )
        hidden = self._hidden_texts() if self.artifact and self.wrote_any else []
        if hidden:
            quoted = ", ".join(f'"{t}"' for t in hidden[:3])
            return self._nudge(
                "contrast",
                f"Sayfada şu yazılar zeminle aynı renkte, kullanıcı onları göremiyor: {quoted}. "
                "Yazı rengini ya da zemin rengini değiştir ki okunsun.",
            )
        intent_only = len(text) <= MAX_INTENT_CHARS and "?" not in text and not _CLAIM.search(text)
        if text and intent_only and _INTENT.search(text):
            return self._nudge(
                "intent",
                "Ne yapacağını söyledin ama bir araç çağırmadın. Söylediğini şimdi uygun araçla yap; "
                "iş zaten bittiyse sonucu kısaca söyle.",
            )
        return None
