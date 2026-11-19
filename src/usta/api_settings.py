"""Ayarların ve kullanıcının kendi yazdığı tanışma bilgilerinin (profil) HTTP uçları."""

from __future__ import annotations

import dataclasses
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import kisi, ortak
from usta import settings as usta_settings
from usta.api_models import ProfileIn, SettingsIn
from usta.tasks import TaskManager


def register(
    api: APIRouter, home: Path, manager: TaskManager, *, workspace: str | None, background: bool
) -> None:
    """Profil ve ayar uçlarını `api` yönlendiricisine ekler."""

    @api.get("/profile")
    def get_profile() -> dict:
        """Kullanıcının kendi yazdığı tanışma bilgileri (modelin yazabildiği bir yol yoktur)."""
        return asdict(kisi.load(home))

    @api.put("/profile")
    def put_profile(body: ProfileIn) -> dict:
        if ortak.load_link(home) is not None:
            raise HTTPException(
                409,
                "Bu bilgisayar evdeki ortak hafızaya bağlı. Bilgiler ev sahibi bilgisayardan değiştirilir.",
            )
        try:
            k = kisi.check(body.model_dump())
            kisi.save(home, k)
        except kisi.KisiError as e:
            raise HTTPException(422, str(e)) from None
        except OSError:
            raise HTTPException(500, "profil kaydedilemedi") from None
        return asdict(k)

    @api.delete("/profile")
    def delete_profile() -> dict:
        if ortak.load_link(home) is not None:
            raise HTTPException(
                409,
                "Bu bilgisayar evdeki ortak hafızaya bağlı. Bilgiler ev sahibi bilgisayardan değiştirilir.",
            )
        try:
            kisi.delete(home)
        except OSError:
            raise HTTPException(500, "profil silinemedi") from None
        return asdict(kisi.Kisi())

    @api.get("/settings")
    def get_settings() -> dict:
        cur = usta_settings.load(home)
        return {
            "theme": cur.theme,
            "mode": cur.mode,
            "guard": cur.guard,
            "zoom": cur.zoom,
            "accent": cur.accent,
            "think": cur.think,
            "view": cur.view,
            "context_window": cur.context_window or 0,
            "background": background,
            "workspace": workspace,
        }

    @api.put("/settings")
    def put_settings(body: SettingsIn) -> dict:
        cur = usta_settings.load(home)
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if "context_window" in changes:
            cw = changes["context_window"]
            if cw == 0:
                changes["context_window"] = None
            elif cw < 256:
                raise HTTPException(422, "bağlam en az 256 token olmalı")
        try:
            new = dataclasses.replace(cur, **changes)
            usta_settings.save(home, new)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except OSError:
            raise HTTPException(500, "ayar kaydedilemedi") from None
        if "context_window" in changes:
            manager.context_window = new.context_window  # bir sonraki görevden itibaren
        if "think" in changes and manager.model_control is not None:
            manager.model_control.rebuild()
        return {
            "theme": new.theme,
            "mode": new.mode,
            "guard": new.guard,
            "zoom": new.zoom,
            "accent": new.accent,
            "think": new.think,
            "view": new.view,
            "context_window": new.context_window or 0,
        }
