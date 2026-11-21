"""Bağlantıdan beceri: GitHub'daki bir `SKILL.md`'yi indirip Usta'nın beceri biçimine çevirir.

Yalnız GitHub (github.com, raw.githubusercontent.com). İndirilen metin doğrudan kaydedilmez; beceri öneri kartından
(`skills.check_proposal`: tehlikeli ifade uyarıları, kullanıcı onayı) geçer. `SKILL.md`'nin yanındaki ek dosyalar
(betikler, şablonlar) alınmaz; yalnız yönerge metni gelir.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request

from usta import skills

MAX_BYTES = 200_000
_GH = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)(?:/(blob|tree)/([^/]+)(?:/(.*))?)?/?$"
)
_RAW = re.compile(r"^https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/[^/]+/.+$")
_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


class SkillLinkError(Exception):
    pass


def raw_url(url: str) -> str:
    """GitHub bağlantısı → `SKILL.md`'nin ham adresi (klasör bağlantısında klasördeki SKILL.md)."""
    url = url.strip()
    if "/" not in url:
        raise SkillLinkError(
            f'"{url}" bir ad, bağlantı değil. Usta becerileri adla bulamaz: becerinin GitHub sayfasını '
            "aç, adres çubuğundaki bağlantıyı kopyala ve buraya yapıştır."
        )
    if _RAW.match(url):
        return url
    m = _GH.match(url)
    if not m or not m.group(3):
        raise SkillLinkError(
            "bir GitHub dosya ya da klasör bağlantısı ver (ör. github.com/hesap/depo/blob/main/SKILL.md)"
        )
    owner, repo, kind, ref, path = m.groups()
    path = (path or "").strip("/")
    if kind == "tree":
        path = f"{path}/SKILL.md" if path else "SKILL.md"
    if not path.lower().endswith(".md"):
        raise SkillLinkError("bağlantı bir .md dosyasını göstermiyor")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{urllib.parse.quote(path)}"


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "usta"})
    with urllib.request.urlopen(req, timeout=15) as r:  # yalnız sabit GitHub adresleri
        data = r.read(limit + 1)
    if len(data) > limit:
        raise SkillLinkError("dosya çok büyük")
    return data


def is_repo(url: str) -> bool:
    """Dosya ya da klasör değil, deponun kendisi mi (github.com/hesap/depo)?"""
    m = _GH.match(url.strip())
    return bool(m) and not m.group(3)


def repo_skills(url: str) -> list[str]:
    """Depo bağlantısı → içindeki SKILL.md dosyalarının bağlantıları (en çok 30)."""
    m = _GH.match(url.strip())
    if not m or m.group(3):
        raise SkillLinkError("bir GitHub depo bağlantısı ver")
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    api = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    tree = json.loads(_get(api, 5_000_000)).get("tree", [])
    paths = sorted(
        t["path"]
        for t in tree
        if t.get("type") == "blob" and t["path"].split("/")[-1] == "SKILL.md"
    )
    return [f"https://github.com/{owner}/{repo}/blob/HEAD/{p}" for p in paths[:30]]


def fetch(url: str) -> str:
    try:
        return _get(raw_url(url), MAX_BYTES).decode("utf-8")
    except UnicodeDecodeError:
        raise SkillLinkError("dosya metin değil") from None


def _slug(text: str) -> str:
    s = re.sub(
        r"[^a-z0-9_-]+", "-", unicodedata.normalize("NFC", text).translate(_TR).lower()
    ).strip("-_")
    return s[:30].strip("-_") or "beceri"


def from_markdown(text: str) -> tuple[str, str, str]:
    """SKILL.md (üstte ad/açıklama, altta yönerge) → (ad, açıklama, yönerge)."""
    meta: dict[str, str] = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if m:
        body, key = m.group(2), None
        for line in m.group(1).splitlines():
            km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
            if km:
                key, value = km.group(1).lower(), km.group(2).strip()
                meta[key] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
            elif key and line.startswith((" ", "\t")):
                meta[key] = f"{meta[key]} {line.strip()}".strip()
    body = body.strip()
    title = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.startswith("#")), "")
    desc = " ".join((meta.get("description") or title or "Bağlantıdan alınan beceri").split())
    if len(desc) > skills.MAX_DESCRIPTION:
        desc = desc[: skills.MAX_DESCRIPTION - 1].rstrip() + "…"
    return _slug(meta.get("name") or title), desc, body
