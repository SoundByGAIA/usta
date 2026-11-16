"""Yazma becerisi sondası: model ne kadar büyük bir parçayı sağlıklı yapabiliyor (DENEYSEL).

Fikir: modeli önce kısa bir sınavdan geçir, sonra işi onun yapabileceği en küçük birime böl.
Aynı boyuttaki iki model çok farklı davranıyor (16 Kasım ölçümü: Qwen3 4B, Qwen2.5-Coder 7B'den düzgün Türkçe yazdı ve
daha az uydurdu), o yüzden yalnız parametre sayısına bakılmaz. Altı küçük deneme, her biri kuralla puanlanır:

- **tek:** bir cümleyi değiştirmeden yazmak (tek talimat)
- **iki:** üç ürünü "ad - fiyat" biçiminde alt alta, başka bir şey yazmadan (iki talimat + bilgiyi aynen koruma)
- **plan:** bir site için 2-5 satırlık bölüm planı
- **bolum:** tek bir <section> parçası, verilen e-postayla, uydurmasız
- **uydurma:** verilen bilgilerle iki cümlelik tanıtım, saat/telefon/fiyat/yer uydurmadan, yalnız Türkçe
- **sayfa:** küçük bir sayfanın tamamı tek seferde

Seviye: 3 = sayfayı tek seferde yazar (her şey geçti ve model 12B'den küçük değil ya da boyutu bilinmiyor: bulut),
2 = bölüm bölüm (plan, iki, bölüm ve uydurma geçti), 1 = en küçük parçalar (Usta iskeleti ve bilgileri kendisi koyar,
model yalnız kısa düz cümle yazar). Sonuç `~/.usta/skills.json`'da model adı, uç nokta ve revizyonla saklanır.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from usta import compat, sitebuild, sitecheck
from usta.models import Message, ModelClient, ModelError

SCHEMA = 1
BIG_B = 12.0  # bu boyutun altındaki yerel modele tek seferde sayfa yazdırılmaz
SYSTEM = "Answer briefly and exactly as asked, with no explanation."

_ONE = "Tatlı Köşe her gün sizi bekliyor."
_ITEMS = (("baklava", "120"), ("sütlaç", "80"), ("kazandibi", "90"))
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_SENT = re.compile(r"[.!?]+(?:\s|$)")


@dataclass
class SkillProfile:
    level: int
    passed: dict[str, bool] = field(default_factory=dict)
    size_b: float | None = None
    revision: str = ""
    seconds: float = 0.0
    t: float = 0.0
    schema: int = SCHEMA


def _ask(model: ModelClient, prompt: str) -> str:
    try:
        reply = model.chat([Message("system", SYSTEM), Message("user", prompt)], None)
    except ModelError:
        return ""
    return (getattr(reply, "content", None) or "").strip()


def _clean(s: str) -> str:
    return sitebuild._unfence(s).strip().strip("\"'“”").strip()


def check_one(reply: str) -> bool:
    return _clean(reply).rstrip(".") == _ONE.rstrip(".")


def check_two(reply: str) -> bool:
    lines = [ln.strip() for ln in _clean(reply).splitlines() if ln.strip()]
    if len(lines) != len(_ITEMS):
        return False
    for line, (item, price) in zip(lines, _ITEMS, strict=True):
        line = sitecheck._fold(sitebuild._BULLET.sub("", line))
        if not re.fullmatch(rf"\W*{item}\s*[-–]\s*{price}\s*tl\W*", line):
            return False
    return True


def check_plan(reply: str) -> bool:
    plan = sitebuild.parse_plan(reply)
    return plan != sitebuild.DEFAULT_PLAN and 2 <= len(plan) <= 5


_SECTION_TASK = "Benim adım Ayşe, resim yapıyorum, e-postam ayse@ornek.com."


def check_section(reply: str) -> bool:
    body = sitebuild._unfence(reply)
    if not sitebuild._SECTION.search(body) or re.search(r"<html|<head|<style", body, re.IGNORECASE):
        return False
    frag = sitebuild.parse_section(reply, 0)
    return "ayse@ornek.com" in frag and not sitebuild.problems(_SECTION_TASK, frag)


_INTRO_TASK = "Pastanemin adı Tatlı Köşe, yeri Nilüfer, Bursa."


def check_noinvent(reply: str) -> bool:
    text = _clean(reply)
    if not text or "<" in text or _CJK.search(text) or "tatlı köşe" not in sitecheck._fold(text):
        return False
    if len(_SENT.findall(text + " ")) > 3:
        return False
    return not sitebuild.problems(_INTRO_TASK, f"<section><p>{text}</p></section>")


def check_page(reply: str) -> bool:
    body = sitebuild._unfence(reply)
    if not re.search(r"<!doctype|<html", body, re.IGNORECASE) or not re.search(
        r"</html>", body, re.IGNORECASE
    ):
        return False
    return (
        "ayse@ornek.com" in body
        and "Ayşe" in body
        and not sitebuild.problems(_SECTION_TASK, body)
        and not _CJK.search(body)
    )


# Sorular Usta'nın gerçekte kullandığı talimat biçimindedir (İngilizce, olumlu; metin Türkçe). İlk sürüm Türkçe ve
# yasak listeli sorular kullanıyordu: 4B gerçek görevlerde en iyisiyken sınavda en düşük seviyeyi aldı (16 Kasım).
_FACTS = "The user's facts (copy them exactly as written): "
PROBES = {
    "tek": (f"Copy this Turkish sentence exactly, adding nothing: {_ONE}", check_one),
    "iki": (
        (
            "List these products one per line in the form 'name - price'. Output only the lines.\n"
            "baklava 120 TL, sütlaç 80 TL, kazandibi 90 TL"
        ),
        check_two,
    ),
    "plan": (
        (
            f"{sitebuild.USER}{_INTRO_TASK} Menüm: baklava 120 TL. Bir sayfa istiyorum.\n"
            "Plan this one-page website in 2 to 4 sections. One section per line: short Turkish name - what it "
            "contains. Base everything on the user's facts. Output only the lines."
        ),
        check_plan,
    ),
    "bolum": (
        (
            f"{sitebuild.USER}{_SECTION_TASK}\n{_FACTS}Ayşe, ayse@ornek.com.\nNow write only the contact section. "
            'Output exactly one <section id="b0"> ... </section> with an h2 and the e-mail. The page frame (html, '
            "head, style) is added by the system. Use only the user's facts; visible text in Turkish."
        ),
        check_section,
    ),
    "uydurma": (
        (
            f"{sitebuild.USER}{_INTRO_TASK}\n{_FACTS}Tatlı Köşe, Nilüfer, Bursa.\nWrite a short welcome text for "
            "this bakery's website: at most two short, plain sentences in Turkish, as plain text. Use only the "
            "user's facts."
        ),
        check_noinvent,
    ),
    "sayfa": (
        (
            f"{sitebuild.USER}{_SECTION_TASK} Beni tanıtan bir sayfa istiyorum.\nWrite one complete HTML page "
            "(start with <!doctype html>). Output only HTML. Use only the user's facts; visible text in Turkish."
        ),
        check_page,
    ),
}


def level_for(passed: dict[str, bool], size_b: float | None) -> int:
    two = all(passed.get(k) for k in ("plan", "iki", "bolum", "uydurma"))
    if two and all(passed.get(k) for k in PROBES) and (size_b is None or size_b >= BIG_B):
        return 3
    return 2 if two else 1


def probe(model: ModelClient, size_b: float | None = None, revision: str = "") -> SkillProfile:
    t0 = time.monotonic()
    passed = {name: bool(check(_ask(model, prompt))) for name, (prompt, check) in PROBES.items()}
    return SkillProfile(
        level=level_for(passed, size_b),
        passed=passed,
        size_b=size_b,
        revision=revision,
        seconds=round(time.monotonic() - t0, 1),
        t=time.time(),
    )


def _path(home: Path) -> Path:
    return home / "skills.json"


def _key(endpoint: str, model: str) -> str:
    return f"{endpoint.rstrip('/')}|{model}"


def load(home: Path, endpoint: str, model: str, revision: str = "") -> SkillProfile | None:
    try:
        data = json.loads(_path(home).read_text(encoding="utf-8"))
        raw = data[_key(endpoint, model)]
        p = SkillProfile(**raw)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if p.schema != SCHEMA or (revision and p.revision and p.revision != revision):
        return None  # model değişti: yeniden ölç
    return p


def save(home: Path, endpoint: str, model: str, p: SkillProfile) -> None:
    home = Path(home)
    path = _path(home)
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() and not path.is_symlink()
            else {}
        )
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[_key(endpoint, model)] = asdict(p)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("skills.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
