"""Bitirme anında söz–eylem denetimi (DENEYSEL, varsayılan kapalı): küçük modellerin tipik "erken bitirme" hataları.

Reliability Lab'da (DeepSeek-V4-Pro-Qwen3.5-9B, 2026-11-14) görülen kalıplar:

- **Yapmadığını yaptım demek:** yalnız klasörü listeleyip "summary.txt dosyasına yazıldı" deyip bitirmek.
- **Niyet söyleyip durmak:** "Dosyaları kontrol ediyorum." deyip araç çağırmadan bitirmek.
- **Gereksiz izin istemek:** görev açıkça "dosyaya yaz" derken "yazmamı ister misiniz?" diye sormak.

Bunlar modelin kendi sözüyle yaptığı eylem arasındaki uyuşmazlıktır; model çağırmadan, kurallarla yakalanır. Model
araç çağırmadan bitirmek istediğinde en çok `max_nudges` kez kısa bir kullanıcı mesajıyla yönlendirilir.

Güvenlik: "yazdım ama yazmadın" hatırlatması YALNIZ kullanıcının kendi isteğinde geçen dosyalar için yapılır; okunan
bir içeriğin (enjeksiyonun) uydurduğu dosyayı yazmaya itilmez. Hatırlatmalar izin/onay kurallarını değiştirmez.
Varsayılan kapalıdır; açılması Lab ölçümüne bağlıdır (Usta ilkesi: ölçümle doğrulanmadan varsayılan olmaz).
"""

from __future__ import annotations

import re

WRITE_TOOLS = ("write_file", "edit_file")
_PATH = re.compile(r"(?<![\w/.-])([\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]{1,6})(?![\w/-])")
_CLAIM = re.compile(
    r"yazıldı|yazdım|kaydedildi|kaydettim|oluşturuldu|oluşturdum|eklendi|ekledim|güncellendi|güncelledim"
    r"|\b(?:written|wrote|saved|created|updated)\b",
    re.IGNORECASE,
)
# 1. tekil şimdiki/gelecek zaman ("kontrol ediyorum", "yazacağım") ya da İngilizce niyet ("Let me", "I'll")
_INTENT = re.compile(
    r"\w+(?:ıyorum|iyorum|uyorum|üyorum|acağım|eceğim)\b|\b(?:let me|i'll|i will|i'm going to)\b",
    re.IGNORECASE,
)
_ASK = re.compile(
    r"ister misin|ister misiniz|yapayım mı|yazayım mı|yazmamı ister|edeyim mi|"
    r"\b(?:shall i|should i|do you want me|would you like me)\b",
    re.IGNORECASE,
)
_WRITE_REQUEST = re.compile(
    r"\b\w*(?:yaz|kaydet|oluştur|ekle)\w*\b|\b(?:write|save|create)\b", re.IGNORECASE
)
MAX_INTENT_CHARS = 240


class FinishCheck:
    def __init__(self, task: str = "", max_nudges: int = 2):
        self.task = task or ""
        self.max_nudges = max_nudges
        self.written: set[str] = set()
        self.nudges = 0
        self._used: set[str] = set()  # her kural görev başına bir kez

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

    def _nudge(self, rule: str, message: str) -> str | None:
        if self.nudges >= self.max_nudges or rule in self._used:
            return None
        self._used.add(rule)
        self.nudges += 1
        return message

    def on_finish(self, answer: str) -> str | None:
        """Model araç çağırmadan bitirmek istiyor: hatırlatma mesajı ya da None (bitir)."""
        text = (answer or "").strip()
        task_paths = {self._norm(p) for p in _PATH.findall(self.task)}
        if _CLAIM.search(text):
            claimed = [p for p in _PATH.findall(text) if self._norm(p) in task_paths]
            missing = [p for p in claimed if self._norm(p) not in self.written]
            if missing:
                return self._nudge(
                    "claim",
                    f"Yanıtında `{missing[0]}` dosyasına yazdığını söylüyorsun ama bu görevde o dosyaya hiç yazmadın. "
                    "İstenen içeriği şimdi write_file ile yaz; yazmayacaksan yanıtını düzelt ve nedenini söyle.",
                )
        if (
            task_paths
            and _WRITE_REQUEST.search(self.task)
            and _ASK.search(text)
            and text.endswith("?")
        ):
            unwritten = [p for p in task_paths if p not in self.written]
            if unwritten:
                return self._nudge(
                    "ask",
                    "Görev bunu zaten açıkça istiyor; izin sorma. İstenen dosyayı şimdi yaz ve sonucu söyle.",
                )
        intent_only = len(text) <= MAX_INTENT_CHARS and "?" not in text and not _CLAIM.search(text)
        if text and intent_only and _INTENT.search(text):
            return self._nudge(
                "intent",
                "Ne yapacağını söyledin ama bir araç çağırmadın. Söylediğini şimdi uygun araçla yap; "
                "iş zaten bittiyse sonucu kısaca söyle.",
            )
        return None
