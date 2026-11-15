"""Bitirme anında söz–eylem denetimi (portalda ve komut satırında varsayılan AÇIK): küçük modellerin "erken bitirme" hataları.

Reliability Lab'da (DeepSeek-V4-Pro-Qwen3.5-9B, 2026-11-14) görülen kalıplar:

- **Yapmadığını yaptım demek:** yalnız klasörü listeleyip "summary.txt dosyasına yazıldı" deyip bitirmek.
- **Gereksiz izin istemek:** görev açıkça "dosyaya yaz" derken "yazmamı ister misiniz?" diye sormak.
- **Sonucu dosya yerine yanıta yazmak** ya da boş yanıtla bitirmek.
- **Niyet söyleyip durmak:** "Dosyaları kontrol ediyorum." / "Önce dosyaya bakalım." deyip araç çağırmadan bitirmek.

İlk üçü tek kuralla yakalanır: kullanıcının isteğinde yazılması istenen **hedef dosya** ("X dosyasına yaz", "X'e
kaydet", "write to X") bitirme anında hâlâ yazılmamışsa kısa bir hatırlatma yapılır. Hedef yalnız kullanıcının
kendi isteğinden çıkarılır; yalnız okunan kaynak dosyalar ("X dosyasındaki") ve modelin yanıtında geçen başka dosyalar
hedef sayılmaz. (İlk sürüm modelin yanıtındaki her görev dosyasını hedef sanıyordu; "todo.md'yi okudum, count.txt'e
yazdım" yanıtında okunan todo.md için yanlış hatırlatma yapıp modeli şaşırttı. Lab izinde görüldü, düzeltildi.)

Güvenlik: okunan bir içeriğin (enjeksiyonun) uydurduğu dosyayı yazmaya itilmez; hatırlatmalar izin/onay kurallarını
değiştirmez.

Ölçüm (Reliability Lab, DeepSeek-V4-Pro-Qwen3.5-9B Q4_K_M, düşünme kapalı, 29 senaryo x temiz/saldırılı, 15 Kasım 2026):
meşru görev başarısı 13/25 → 19/25, saldırı altında görev başarısı 16/25 → 21/25, saldırı başarısı 1/25 → 1/25 (iki
koşuda farklı senaryo; ikisinde de hatırlatma tetiklenmedi), yanlış ret 0 → 0, hiç araç çağırmayan koşu 2 → 0.
Eşleştirilmiş koşularda 18 kazanç, 3 kayıp (ikisi hatırlatmadan önce yanlış dosya adına yazma, biri `run` ile yazılmış
dosyanın yeniden yazdırılması; sonuncusu düzeltildi). Bedeli: ortalama gecikme ~%20 arttı. Kapatmak:
`--no-finish-check` ya da `USTA_FINISH_CHECK=0`.
"""

from __future__ import annotations

import re

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


def write_targets(task: str) -> list[str]:
    """Kullanıcının isteğinde yazılması istenen dosyalar (sıralı, tekrarsız)."""
    found: list[str] = []
    for rx in (_TARGET_TR, _TARGET_EN):
        for m in rx.finditer(task or ""):
            if m.group(1) not in found:
                found.append(m.group(1))
    return found


class FinishCheck:
    def __init__(self, task: str = "", max_nudges: int = 2):
        self.task = task or ""
        self.max_nudges = max_nudges
        self.targets = write_targets(self.task)
        self.written: set[str] = set()
        self.nudges = 0
        self.fired: list[str] = []  # tetiklenen kurallar (Lab izi için)

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
        # komutla yazma ("echo 3 > count.txt"): hedef adı geçen bir komut çalıştıysa yeniden yazmaya itilmez
        # (Lab izi: hatırlatma komutla yazılmış dosyayı model uzun bir cümleyle yeniden yazdırdı)
        if executed and tool == "run" and isinstance(args.get("command"), str):
            cmd = args["command"].replace("\\", "/").lower()
            self.written.update(self._norm(t) for t in self.targets if self._norm(t) in cmd)

    def _nudge(self, rule: str, message: str) -> str | None:
        if self.nudges >= self.max_nudges or rule in self.fired:
            return None
        self.fired.append(rule)
        self.nudges += 1
        return message

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
        intent_only = len(text) <= MAX_INTENT_CHARS and "?" not in text and not _CLAIM.search(text)
        if text and intent_only and _INTENT.search(text):
            return self._nudge(
                "intent",
                "Ne yapacağını söyledin ama bir araç çağırmadın. Söylediğini şimdi uygun araçla yap; "
                "iş zaten bittiyse sonucu kısaca söyle.",
            )
        return None
