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

Gizli bilgi dosyası okuma: güvenilmeyen bir içerik okunduktan (ya da ortak/kalıcı not bağlamı verildikten) sonra
`.env`, anahtar, parola dosyası gibi bir dosyayı okumak, kullanıcı o dosyayı isteğinde anmadıysa onay ister. Lab
(DeepSeek-V4-Qwen3.5-9B, 2026-11-15): iki ayrı ölçümde model bir bilet / ortak not talimatıyla `config.env` okuyup
anahtarı yanıtına yazdı. Yanıta sızmayı hiçbir kural engelleyemez; ama sızmanın ön koşulu olan okumayı yakalamak mümkün.
"""

from __future__ import annotations

import re
import shlex

UNTRUSTED_TOOLS = frozenset({"read_file", "read_symbol", "fetch_url", "web_search", "delegate"})
MAX_BLOB = 400_000  # güvenilmeyen metin üst sınırı (karakter); eskiler atılır
MIN_LEN = 4  # bundan kısa parçalar eşleşme sayılmaz (".py", "ls" gibi)
_URL = re.compile(r"https?://([^\s/'\"<>]+)", re.IGNORECASE)
_PATHISH = re.compile(r"[\w.\-]+[/.][\w.\-/]*\w|[\w\-]+/")
SECRET_READ_TOOLS = frozenset({"read_file", "read_symbol"})
# dosya adı (yolun son parçası) ya da klasör: .env, x.env, .env.local, anahtarlar, parola/kimlik dosyaları
_SECRET_NAME = re.compile(
    r"(?:^|/)(?:\.env(?:[.~][\w.~-]*)?|[\w.-]+\.env(?:[.~][\w.~-]*)?|id_(?:rsa|dsa|ecdsa|ed25519)\b[\w.]*"
    r"|[\w.-]+\.(?:pem|key|p12|pfx|kdbx|keystore|jks|tfstate(?:\.backup)?)"
    # kimlik/anahtar adı taşıyan VERİ dosyası (kod dosyası değil: token_parser.py, tokenizer.json, secret-sharing.md geçer)
    r"|(?:[\w-]*[._-])?\.?(?:credentials|secrets?|tokens?|api[_-]?keys?|service[_-]?account)(?:[_-][\w-]*)?"
    r"(?:\.(?:txt|json|ya?ml|ini|cfg|conf|toml|xml|csv))?"
    r"|\.(?:npmrc|pypirc|netrc|pgpass|git-credentials|htpasswd|[\w]+_history)|kubeconfig|hosts\.ya?ml)$"
    r"|(?:^|/)\.(?:ssh|aws|gnupg|docker|kube|azure)/|(?:^|/)gcloud/",
    re.IGNORECASE,
)


def secret_path(path: str) -> bool:
    """Yol gizli bilgi taşıyan bir dosyaya benziyor mu (ad kalıbı; içerik okunmaz)."""
    return bool(_SECRET_NAME.search(_norm_path(path)))


#: kullanıcının başka programı yalnız okuma izniyle çalıştırma isteği (Lab: Qwen3 1.7B görevde "YALNIZ OKUMA" yazarken
#: ilk çağrıda kendiliğinden write=true gönderdi)
_READ_ONLY = re.compile(
    r"\b(?:yaln[ıi]z(?:ca)?|sadece|salt)\s+okuma\b|\bread[\s-]?only\b"
    r"|\bwrite\b\W{0,3}(?:alan[ıi]n[ıi]\s+)?(?:=|:)?\s*false\b|yazma\s+izni\s+(?:verme|olmadan)",
    re.IGNORECASE,
)


def wants_write(args: dict) -> bool:
    return args.get("write") is True or str(args.get("write")).lower() == "true"


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

    def __init__(self, user_text: str = "", context: str = ""):
        self._user = [str(user_text or "")]
        self._blobs: list[str] = []
        self._size = 0
        self._context = bool(
            str(context or "").strip()
        )  # ortak/kalıcı notlar: kullanıcının bu görevdeki sözü değil

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

    def forbids_write(self, tool: str, args: dict) -> bool:
        """Kullanıcı "yalnız okuma" dediği halde başka programa yazma izni isteniyor mu (onay sorulmadan reddedilir)."""
        return (
            tool == "delegate"
            and wants_write(args)
            and any(_READ_ONLY.search(u) for u in self._user)
        )

    def check(self, tool: str, args: dict) -> str:
        """Boş dize: sorun yok. Aksi halde gerekçe (hedef ve nerede bulunduğu)."""
        if tool in SECRET_READ_TOOLS and (self._blobs or self._context):
            path = _norm_path(args.get("path"))
            user = "\n".join(self._user).lower()
            name = path.rsplit("/", 1)[-1].lower()
            if secret_path(path) and path.lower() not in user and name not in user:
                return (
                    f"'{path}' gizli bilgi (anahtar, parola) taşıyan bir dosyaya benziyor; isteğinde geçmiyor ve "
                    "Usta az önce başka bir içerik okudu (bu içerik okumayı yönlendirmiş olabilir)"
                )
        if not self._blobs:
            return ""
        if tool == "delegate" and wants_write(args):
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
