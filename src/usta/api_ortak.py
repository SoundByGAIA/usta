"""Evdeki ortak hafızanın HTTP uçları (tasarım: docs/ortak-hafiza.md)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from usta import kisi, ortak
from usta.api_models import OrtakConnectIn, OrtakHostIn, OrtakNoteIn


def register(api: APIRouter, home: Path) -> ortak.HostServer:
    """Ortak hafıza uçlarını `api` yönlendiricisine ekler; ev sahibi dinleyicisini döndürür."""
    ohost = ortak.HostServer(home)

    def ortak_role() -> str:
        if ortak.load_link(home) is not None:
            return "bagli"
        return "ev-sahibi" if ortak.Store(home).enabled else "yok"

    def ortak_host_only() -> ortak.Store:
        store = ortak.Store(home)
        if ortak_role() != "ev-sahibi":
            raise HTTPException(409, "Bunu yalnız ev sahibi bilgisayar yapabilir.")
        return store

    @api.get("/ortak")
    def ortak_status() -> dict:
        role = ortak_role()
        store = ortak.Store(home)
        out: dict = {"rol": role, "bilgisayar": ortak.pc_name()}
        if role == "ev-sahibi":
            out.update(
                ad=store.name,
                adres=ohost.address,
                calisiyor=ohost.running,
                eslesmeler=store.peers_public(),
                notlar=store.approved(),
                bekleyen=store.pending(),
            )
        elif role == "bagli":
            link = ortak.load_link(home) or {}
            out["baglanti"] = {"ad": link.get("ad"), "adres": link.get("adres")}
            try:
                data = ortak.fetch(home)
                out.update(ulasilamiyor=False, profil=data["profil"], notlar=data["notlar"])
            except ortak.OrtakError as e:
                data = ortak.cached(home) or {"profil": asdict(kisi.Kisi()), "notlar": []}
                out.update(
                    ulasilamiyor=True, hata=str(e), profil=data["profil"], notlar=data["notlar"]
                )
        return out

    @api.post("/ortak/ev-sahibi")
    def ortak_set_host(body: OrtakHostIn) -> dict:
        store = ortak.Store(home)
        if body.acik:
            if ortak.load_link(home) is not None:
                raise HTTPException(
                    409, "Bu bilgisayar başka bir ortak hafızaya bağlı. Önce bağlantıyı kes."
                )
            store.configure(True, body.ad)
            try:
                ohost.start()
            except ortak.OrtakError as e:
                store.configure(False)
                raise HTTPException(409, str(e)) from None
        else:
            store.configure(False)
            ohost.stop()
        return ortak_status()

    @api.post("/ortak/kod")
    def ortak_code() -> dict:
        ortak_host_only()
        if not ohost.running:
            try:
                ohost.start()
            except ortak.OrtakError as e:
                raise HTTPException(409, str(e)) from None
        return {"kod": ohost.codes.issue(), "adres": ohost.address, "sure": 300}

    @api.post("/ortak/baglan")
    def ortak_join(body: OrtakConnectIn) -> dict:
        if ortak.Store(home).enabled:
            raise HTTPException(
                409, "Bu bilgisayar ortak hafızayı kendisi tutuyor. Önce onu kapat."
            )
        try:
            res = ortak.connect(home, body.adres, body.kod, body.ad or ortak.pc_name())
        except ortak.OrtakError as e:
            raise HTTPException(400, str(e)) from None
        return {"ad": res["ad"], "adres": res["adres"]}

    @api.post("/ortak/ayril")
    def ortak_leave() -> dict:
        ortak.disconnect(home)
        return {"rol": ortak_role()}

    @api.delete("/ortak/eslesmeler/{key_id}")
    def ortak_unpair(key_id: str) -> dict:
        store = ortak_host_only()
        try:
            store.remove_peer(key_id)
        except KeyError:
            raise HTTPException(404, "böyle bir bilgisayar yok") from None
        return {"eslesmeler": store.peers_public()}

    @api.post("/ortak/notlar")
    def ortak_add_note(body: OrtakNoteIn) -> dict:
        role = ortak_role()
        try:
            if role == "bagli":
                res = ortak.post_note(home, body.text)
                return {"durum": res.get("durum", "bekliyor")}
            if role == "ev-sahibi":
                note = ortak.Store(home).add(body.text, ortak.Store(home).name, approved=True)
                return {"durum": note["durum"]}
        except ortak.OrtakError as e:
            raise HTTPException(422, str(e)) from None
        raise HTTPException(
            409, "Ortak hafıza kapalı. Önce ev sahibi ol ya da bir ev sahibine bağlan."
        )

    @api.post("/ortak/notlar/{note_id}/onayla")
    def ortak_approve(note_id: str) -> dict:
        try:
            ortak_host_only().approve(note_id)
        except KeyError:
            raise HTTPException(404, "böyle bir not yok") from None
        return {"tamam": True}

    @api.delete("/ortak/notlar/{note_id}")
    def ortak_delete(note_id: str) -> dict:
        try:
            ortak_host_only().delete(note_id)
        except KeyError:
            raise HTTPException(404, "böyle bir not yok") from None
        return {"tamam": True}

    return ohost
