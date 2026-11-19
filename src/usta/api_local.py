"""Yerel model sihirbazının HTTP uçları: bu bilgisayarda ve evdeki ağda model sunucusu arama, Ollama kurma, model indirme."""

from __future__ import annotations

import sys

from fastapi import APIRouter, HTTPException

from usta import compat, localmodels
from usta.api_models import LocalCtxIn, LocalHostIn, LocalPullIn, LocalScanIn, SystemInstallIn


def register(api: APIRouter) -> None:
    """Yerel model uçlarını `api` yönlendiricisine ekler."""

    @api.post("/local/scan")
    def local_scan(body: LocalScanIn) -> list[dict]:
        try:
            return localmodels.scan(body.port)
        except localmodels.LocalError as e:
            raise HTTPException(400, str(e)) from None

    @api.post("/local/scan-lan")
    def local_scan_lan() -> list[dict]:
        """Evdeki ağda (bu bilgisayarın /24'ü) yaygın portlarda model sunucusu arar."""
        return localmodels.lan_scan()

    @api.post("/local/probe-host")
    def local_probe_host(body: LocalHostIn) -> dict:
        """Kullanıcının yazdığı evdeki adreste model sunucusu var mı (yalnız özel ağ adresleri)."""
        try:
            found = localmodels.probe_host(body.host)
        except localmodels.LocalError as e:
            raise HTTPException(400, str(e)) from None
        if not found:
            raise HTTPException(
                404,
                "Bu adreste yapay zekâ bulamadım. Öbür bilgisayar açık mı ve Ollama (ya da LM Studio) "
                "ağa açık mı? Adresi de kontrol et.",
            )
        return found

    @api.get("/system/info")
    def system_info() -> dict:
        """Yerel model sihirbazı için: bellek, Ollama durumu, kurulu modeller ve öneri."""
        ram = localmodels.memory_gb()
        ollama = localmodels.probe(11434, timeout=1.0)
        return {
            "os": sys.platform,
            "ram_gb": None if ram is None else round(ram, 1),
            "ollama_running": ollama is not None,
            "ollama_installed": ollama is not None or compat.safe_which("ollama") is not None,
            "docker_installed": compat.safe_which("docker") is not None,
            "can_install": {k: localmodels.can_install(k) for k in localmodels.INSTALLABLE},
            "installed": ollama["models"] if ollama else [],
            "recommend": localmodels.recommend(ram),
        }

    @api.post("/system/install", status_code=202)
    def system_install(body: SystemInstallIn) -> dict:
        """Eksik programı (şimdilik yalnız Ollama, yalnız Windows) kullanıcının düğmesiyle kurar."""
        try:
            localmodels.INSTALL.start(body.what)
        except localmodels.LocalError as e:
            raise HTTPException(409 if "sürüyor" in str(e) else 400, str(e)) from None
        return {"started": True}

    @api.get("/system/install")
    def system_install_progress() -> dict:
        return localmodels.INSTALL.snapshot()

    @api.post("/local/pull", status_code=202)
    def local_pull(body: LocalPullIn) -> dict:
        try:
            localmodels.PULL.start(body.port, body.model)
        except localmodels.LocalError as e:
            raise HTTPException(409 if "sürüyor" in str(e) else 400, str(e)) from None
        return {"started": True}

    @api.get("/local/pull")
    def local_pull_progress() -> dict:
        return localmodels.PULL.snapshot()

    @api.post("/local/context")
    def local_context(body: LocalCtxIn) -> dict:
        try:
            return {"model": localmodels.context_variant(body.port, body.model, body.num_ctx)}
        except localmodels.LocalError as e:
            raise HTTPException(502 if "oluşturulamadı" in str(e) else 400, str(e)) from None
