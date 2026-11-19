"""Model seçimi ve bağlı API'lerin HTTP uçları (anahtarlar geri verilmez)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import apis
from usta.api_models import ApiIn, KeyIn, ModelIn, ServerName, friendly_model_error
from usta.modelctl import ModelSwitchError
from usta.models import Message, ModelError
from usta.tasks import TaskManager


def register(api: APIRouter, home: Path, manager: TaskManager) -> Callable[[], list[dict]]:
    """Model ve API uçlarını ekler; gizlilik özeti için bağlı API listesini veren işlevi döndürür."""

    @api.get("/model")
    def get_model() -> dict:
        ctl = manager.model_control
        if ctl is None:
            raise HTTPException(404, "model değiştirme bu sunucuda yok")
        return ctl.info()

    @api.put("/model")
    def put_model(body: ModelIn) -> dict:
        ctl = manager.model_control
        if ctl is None:
            raise HTTPException(404, "model değiştirme bu sunucuda yok")
        if manager.any_busy():
            raise HTTPException(409, "görev sürerken model değiştirilemez")
        try:
            return ctl.switch(body.model, body.api)
        except ModelSwitchError as e:
            raise HTTPException(e.status, e.message) from None

    # --- bağlı API'ler (anahtarlar geri verilmez) --------------------------------------------
    def api_rows() -> list[dict]:
        ctl = manager.model_control
        rows = (
            [
                {
                    "name": "varsayılan",
                    "endpoint": ctl.default.endpoint if ctl else "",
                    "has_key": bool(ctl and ctl.default.key),
                    "builtin": True,
                }
            ]
            if ctl
            else []
        )
        try:
            stored = apis.load(home)
        except apis.ApiError as e:
            raise HTTPException(500, str(e)) from None
        rows += [
            {"name": a.name, "endpoint": a.endpoint, "has_key": bool(a.key), "builtin": False}
            for a in stored.values()
        ]
        return rows

    @api.get("/apis")
    def list_apis() -> list[dict]:
        return api_rows()

    @api.post("/apis", status_code=201)
    def add_api(body: ApiIn) -> dict:
        try:
            a = apis.add(home, body.name, body.endpoint, body.key)
        except apis.ApiError as e:
            raise HTTPException(409 if "zaten" in str(e) else 400, str(e)) from None
        return {"name": a.name}

    @api.post("/setup/ping")
    def setup_ping() -> dict:
        """Sihirbazın son denemesi: seçili modele tek kısa istek atar, anlaşılır bir sonuç döner."""
        ctl = manager.model_control
        if ctl is None or not ctl.ready:
            raise HTTPException(409, "önce bir model seç")
        t0 = time.monotonic()
        try:
            r = ctl.current().chat([Message(role="user", content="Merhaba de, tek kelime yaz.")])
        except ModelError as e:
            return {"ok": False, "error": friendly_model_error(str(e))}
        return {
            "ok": True,
            "seconds": round(time.monotonic() - t0, 1),
            "reply": (r.content or "")[:200],
        }

    @api.put("/apis/{name}/key")
    def set_api_key(name: ServerName, body: KeyIn) -> dict:
        try:
            apis.set_key(home, name, body.key)
        except apis.ApiError as e:
            raise HTTPException(404 if "yok" in str(e) else 400, str(e)) from None
        return {"has_key": bool(body.key)}

    @api.delete("/apis/{name}")
    def delete_api(name: ServerName) -> dict:
        ctl = manager.model_control
        if ctl is not None and ctl.api == name:
            raise HTTPException(409, "kullanılan API silinemez; önce başka bir model seç")
        try:
            apis.remove(home, name)
        except apis.ApiError as e:
            raise HTTPException(404, str(e)) from None
        return {"removed": name}

    return api_rows
