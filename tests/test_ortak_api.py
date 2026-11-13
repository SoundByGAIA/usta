"""Ortak hafıza portal uçları: iki gerçek portal (ev sahibi + bağlı) birbirine loopback üzerinden bağlanır."""

import pytest

from test_api import AUTH, Scripted, make_client
from usta import kisi, ortak


@pytest.fixture
def duo(tmp_path):
    host, _ = make_client(tmp_path / "ev", Scripted())
    peer, _ = make_client(tmp_path / "salon", Scripted())
    hh, ph = tmp_path / "ev" / "home", tmp_path / "salon" / "home"
    srv = host.app.state.ortak_host
    srv.start(bind="127.0.0.1", port=18780)  # gerçek dinleyici, loopback
    yield host, peer, hh, ph, srv
    srv.stop()
    peer.app.state.ortak_host.stop()


def _pair(host, peer, srv):
    assert (
        host.post("/ortak/ev-sahibi", json={"acik": True, "ad": "Ana-PC"}, headers=AUTH).status_code
        == 200
    )
    kod = host.post("/ortak/kod", headers=AUTH).json()
    r = peer.post(
        "/ortak/baglan",
        json={"adres": kod["adres"], "kod": kod["kod"], "ad": "Salon-PC"},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_every_endpoint_requires_the_portal_token(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    for method, path in (
        ("get", "/ortak"),
        ("post", "/ortak/ev-sahibi"),
        ("post", "/ortak/kod"),
        ("post", "/ortak/baglan"),
        ("post", "/ortak/ayril"),
        ("delete", "/ortak/eslesmeler/x"),
        ("post", "/ortak/notlar"),
        ("post", "/ortak/notlar/x/onayla"),
        ("delete", "/ortak/notlar/x"),
    ):
        assert getattr(c, method)(path).status_code == 401, path


def test_default_state_is_off_and_nothing_listens(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    d = c.get("/ortak", headers=AUTH).json()
    assert d["rol"] == "yok"
    assert not c.app.state.ortak_host.running
    assert c.post("/ortak/notlar", json={"text": "x"}, headers=AUTH).status_code == 409
    for path in ("/ortak/kod",):
        assert c.post(path, headers=AUTH).status_code == 409  # ev sahibi değil


def test_full_flow_pair_note_approval_model_context_and_unpair(duo):
    host, peer, hh, ph, srv = duo
    kisi.save(hh, kisi.check({"ad": "Ceren", "bilgiler": ["Kedim var"]}))
    assert _pair(host, peer, srv)["ad"] == "Ana-PC"
    st = peer.get("/ortak", headers=AUTH).json()
    assert st["rol"] == "bagli" and st["profil"]["ad"] == "Ceren" and not st["ulasilamiyor"]

    # bağlı bilgisayardan eklenen not ev sahibinde onay bekler
    r = peer.post("/ortak/notlar", json={"text": "Büyük yazı severim"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["durum"] == "bekliyor"
    hd = host.get("/ortak", headers=AUTH).json()
    assert (
        hd["rol"] == "ev-sahibi"
        and [n["kaynak"] for n in hd["bekleyen"]] == ["Salon-PC"]
        and hd["notlar"] == []
    )
    assert "Büyük yazı" not in ortak.context(ph) and "Büyük yazı" not in ortak.context(hh)
    note_id = hd["bekleyen"][0]["id"]
    # bağlı bilgisayar onaylayamaz/silemez: yalnız ev sahibi
    assert peer.post(f"/ortak/notlar/{note_id}/onayla", headers=AUTH).status_code == 409
    assert peer.delete(f"/ortak/notlar/{note_id}", headers=AUTH).status_code == 409
    assert host.post(f"/ortak/notlar/{note_id}/onayla", headers=AUTH).status_code == 200
    assert "Büyük yazı" in ortak.context(ph) and "Ceren" in ortak.context(ph)
    assert "Büyük yazı" in ortak.context(hh)

    # bağlıyken profil yerelde değişmez
    assert peer.put("/profile", json={"ad": "Başka"}, headers=AUTH).status_code == 409
    assert peer.delete("/profile", headers=AUTH).status_code == 409

    # ev sahibi eşleşmeyi kaldırınca bağlı bilgisayarın erişimi biter
    key_id = host.get("/ortak", headers=AUTH).json()["eslesmeler"][0]["id"]
    assert host.delete(f"/ortak/eslesmeler/{key_id}", headers=AUTH).status_code == 200
    st = peer.get("/ortak", headers=AUTH).json()
    assert st["ulasilamiyor"] is True and "tanımıyor" in st["hata"]
    assert peer.post("/ortak/ayril", headers=AUTH).json()["rol"] == "yok"
    assert peer.put("/profile", json={"ad": "Başka"}, headers=AUTH).status_code == 200

    host, _peer, _hh, _ph, _srv = duo
    host, peer, hh, ph, srv = duo
    host.post("/ortak/ev-sahibi", json={"acik": True}, headers=AUTH)
    assert (
        host.post("/ortak/notlar", json={"text": "Ev notu"}, headers=AUTH).json()["durum"]
        == "onayli"
    )
    nid = host.get("/ortak", headers=AUTH).json()["notlar"][0]["id"]
    assert host.delete(f"/ortak/notlar/{nid}", headers=AUTH).status_code == 200
    assert host.delete(f"/ortak/notlar/{nid}", headers=AUTH).status_code == 404
    bad = host.post("/ortak/notlar", json={"text": "API_KEY=" + "sk-" + "a" * 26}, headers=AUTH)
    assert (
        bad.status_code == 422
        and "gizli" in bad.json()["detail"].lower()
        or "şifre" in bad.json()["detail"]
    )


def test_roles_are_exclusive_and_errors_are_plain(duo):
    host, peer, _hh, _ph, srv = duo
    _pair(host, peer, srv)
    # bağlı bilgisayar aynı anda ev sahibi olamaz; ev sahibi de başka yere bağlanamaz
    r = peer.post("/ortak/ev-sahibi", json={"acik": True}, headers=AUTH)
    assert r.status_code == 409 and "bağlı" in r.json()["detail"]
    kod = host.post("/ortak/kod", headers=AUTH).json()
    r = host.post("/ortak/baglan", json={"adres": kod["adres"], "kod": kod["kod"]}, headers=AUTH)
    assert r.status_code == 409 and "kendisi tutuyor" in r.json()["detail"]
    # yanlış kod ve dış adres anlaşılır hata verir
    peer.post("/ortak/ayril", headers=AUTH)
    r = peer.post("/ortak/baglan", json={"adres": kod["adres"], "kod": "000000"}, headers=AUTH)
    assert r.status_code == 400 and "Kod yanlış" in r.json()["detail"]
    r = peer.post("/ortak/baglan", json={"adres": "8.8.8.8", "kod": "123456"}, headers=AUTH)
    assert r.status_code == 400 and "evdeki ağın dışında" in r.json()["detail"]


def test_turning_host_off_stops_the_listener_and_forgets_the_role(duo):
    host, _peer, _hh, _ph, srv = duo
    host.post("/ortak/ev-sahibi", json={"acik": True}, headers=AUTH)
    assert srv.running
    d = host.post("/ortak/ev-sahibi", json={"acik": False}, headers=AUTH).json()
    assert d["rol"] == "yok" and not srv.running


def test_enabling_without_a_home_network_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr("usta.localmodels.own_ip", lambda: None)
    c, _ = make_client(tmp_path, Scripted())
    r = c.post("/ortak/ev-sahibi", json={"acik": True}, headers=AUTH)
    assert r.status_code == 409 and "ağ adresini" in r.json()["detail"]
    assert c.get("/ortak", headers=AUTH).json()["rol"] == "yok"  # yarım kalmaz
