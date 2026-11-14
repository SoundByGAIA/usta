"""Kaynak izi (taint) kapısı: güvenilmeyen içerikten türeyen yazma/komut hedefleri onay ister.

Saldırı biçimi: ajan bir dosyayı/sayfayı/araç çıktısını okur, içindeki gizli talimata uyar ve kullanıcının hiç
bahsetmediği bir dosyaya yazar ya da bir komut çalıştırır. Ortak nokta: eylemin HEDEFİ (dosya yolu, komut
parçası, adres) okunan içerikte geçer ama kullanıcının isteğinde geçmez.

Kapı bunu yakalar: write_file/edit_file yolu ve `run` komutundaki yol/adres benzeri parçalar, güvenilmeyen kaynaklardan
gelen metinde geçiyor ve kullanıcı metninde (istem, ekler, görev sırasında gönderilen mesajlar) geçmiyorsa, eylem
`ASK` olur (manuel modda kullanıcıya sorulur, oto modda reddedilir). Sezgiseldir; kesin koruma değildir.

Güvenilmeyen kaynaklar: read_file/read_symbol (depo içeriği), fetch_url, web_search, delegate (başka programın çıktısı) ve MCP araçları. Komut çıktıları
(`run`) ve dizin listeleri kapsam dışıdır: ajanın kendi çalıştırdığı kod/izler ve dosya adları meşru hedefleri
sürekli işaretlerdi (ör. test çıktısındaki izden hatalı dosyayı düzeltmek).
"""

from __future__ import annotations

import re
import shlex

UNTRUSTED_TOOLS = frozenset({"read_file", "read_symbol", "fetch_url", "web_search", "delegate"})
MAX_BLOB = 400_000  # güvenilmeyen metin üst sınırı (karakter); eskiler atılır
MIN_LEN = 4  # bundan kısa parçalar eşleşme sayılmaz (".py", "ls" gibi)
_URL = re.compile(r"https?://([^\s/'\"<>]+)", re.IGNORECASE)
_PATHISH = re.compile(r"[\w.\-]+[/.][\w.\-/]*\w|[\w\-]+/")


def _norm_path(p: str) -> str:
    p = str(p or "").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def _is_untrusted(tool: str) -> bool:
    return tool in UNTRUSTED_TOOLS or tool.startswith("mcp__")


def _candidates(tool: str, args: dict) -> list[str]:
    """Eylemin hedef parçaları: yazma yolu; komutta URL sunucuları ve yol/dosya benzeri jetonlar."""
    if tool in ("write_file", "edit_file"):
        path = _norm_path(args.get("path"))
        return [path] if len(path) >= MIN_LEN else []
    if tool == "run":
        cmd = str(args.get("command") or "")
        out = [h.lower() for h in _URL.findall(cmd)]
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()
        for t in tokens:
            if t.startswith("-") or len(t) < MIN_LEN:
                continue
            if "://" in t:
                continue  # URL sunucu olarak zaten eklendi
            if _PATHISH.search(t):
                out.append(_norm_path(t))
        return [c for c in out if len(c) >= MIN_LEN]
    return []


class Taint:
    """Bir görev boyunca güvenilmeyen metni ve kullanıcı metnini tutar; eylemleri denetler."""

    def __init__(self, user_text: str = ""):
        self._user = [str(user_text or "")]
        self._blobs: list[str] = []
        self._size = 0

    def add_user(self, text: str) -> None:
        self._user.append(str(text or ""))

    def observe(self, tool: str, result: str) -> None:
        if not _is_untrusted(tool):
            return
        text = str(result or "")
        self._blobs.append(text)
        self._size += len(text)
        while self._size > MAX_BLOB and len(self._blobs) > 1:
            self._size -= len(self._blobs.pop(0))

    def check(self, tool: str, args: dict) -> str:
        """Boş dize: sorun yok. Aksi halde gerekçe (hedef ve nerede bulunduğu)."""
        if not self._blobs:
            return ""
        if tool == "delegate" and (
            args.get("write") is True or str(args.get("write")).lower() == "true"
        ):
            # Yetki yükseltme: başka programın cevabı "yazma izni verildi" diyerek yazma kipini ister (Lab: küçük model 4/4 uydu).
            # Onay zaten sorulur; kullanıcı bu isteğin az önce okunan içerikten sonra geldiğini bilsin.
            return "yazma izni, Usta az önce başka bir içerik okuduktan sonra isteniyor (bu içerik isteği yönlendirmiş olabilir)"
        user = "\n".join(self._user)
        blob = "\n".join(self._blobs)
        low_user, low_blob = user.lower(), blob.lower()
        for cand in _candidates(tool, args):
            key = cand.lower()
            if key in low_user:
                continue
            if key in low_blob:
                return f"hedef '{cand}' okunan içerikte geçiyor ama isteğinde geçmiyor"
        return ""
