"""Becerilerin ve yardıma çağrılabilen diğer programların (harness) HTTP uçları."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import harnesses, skilllink, skills
from usta import settings as usta_settings
from usta.api_models import HarnessToggleIn, SkillIn, SkillLinkIn, SkillProposalIn


def register(api: APIRouter, home: Path) -> None:
    """Beceri ve program uçlarını `api` yönlendiricisine ekler."""

    @api.get("/skills")
    def list_skills() -> list[dict]:
        return skills.list_skills(home)

    @api.get("/harnesses")
    def list_harnesses() -> dict:
        """Usta'nın yardıma çağırabileceği diğer yapay zekâ programları: kurulu mu, sürüm, açık mı."""
        cur = usta_settings.load(home)
        return {"programlar": harnesses.detect(set(cur.delegates))}

    @api.put("/harnesses/{harness_id}")
    def set_harness(harness_id: str, body: HarnessToggleIn) -> dict:
        h = harnesses.CATALOG.get(harness_id)
        if h is None:
            raise HTTPException(404, "böyle bir program yok")
        if body.enabled:
            if harnesses._which(h) is None:
                raise HTTPException(409, f"{h.label} bu bilgisayarda kurulu değil.")
            reason = harnesses.usable_here(h)
            if reason:
                raise HTTPException(409, f"{h.label}: {reason}")
        cur = usta_settings.load(home)
        opened = set(cur.delegates)
        (opened.add if body.enabled else opened.discard)(harness_id)
        try:
            usta_settings.save(home, dataclasses.replace(cur, delegates=tuple(sorted(opened))))
        except (ValueError, OSError):
            raise HTTPException(500, "ayar kaydedilemedi") from None
        return {"programlar": harnesses.detect(opened)}

    @api.post("/skills/check")
    def check_skill_proposal(body: SkillProposalIn) -> dict:
        """Usta'nın önerdiği becerinin temizlenmiş hâli ve uyarıları (öneri kartı bunu gösterir). Hiçbir şey yazmaz."""
        try:
            return skills.check_proposal(home, body.name, body.description, body.instructions)
        except skills.SkillError as e:
            raise HTTPException(422, str(e)) from None

    @api.post("/skills/baglanti")
    def skill_from_link(body: SkillLinkIn) -> dict:
        """GitHub bağlantısındaki beceri, öneri kartı için (yazmaz). Depo bağlantısında içindeki beceriler listelenir."""
        try:
            if skilllink.is_repo(body.url):
                return {"secenekler": skilllink.repo_skills(body.url)}
            name, desc, text = skilllink.from_markdown(skilllink.fetch(body.url))
            card = skills.check_proposal(home, name, desc, text, limit=skills.MAX_SIZE)
        except (skilllink.SkillLinkError, skills.SkillError) as e:
            raise HTTPException(422, str(e)) from None
        except (OSError, ValueError):
            raise HTTPException(
                502, "bağlantıyı açamadım; adresi ve internet bağlantını kontrol et"
            ) from None
        return {**card, "kaynak": body.url}

    @api.put("/skills/{name}")
    def put_skill(name: str, body: SkillIn) -> dict:
        try:
            skills.put(home, name, body.content)
        except skills.SkillError as e:
            raise HTTPException(400, str(e)) from None
        return {"name": name}

    @api.delete("/skills/{name}")
    def delete_skill(name: str) -> dict:
        try:
            skills.delete(home, name)
        except skills.SkillError as e:
            raise HTTPException(404, str(e)) from None
        return {"removed": name}
