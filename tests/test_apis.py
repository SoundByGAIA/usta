import json
import os

import pytest

from test_api import AUTH, make_client
from usta import apis
from usta.modelctl import ModelControl
from usta.settings import load as load_settings


def test_add_list_remove_and_key_mode(tmp_path):
    apis.add(tmp_path, "deepseek", "https://api.deepseek.com/v1/", "sk-gizli")
    a = apis.load(tmp_path)["deepseek"]
    assert a.endpoint == "https://api.deepseek.com/v1" and a.key == "sk-gizli"
    assert oct(os.stat(tmp_path / "apis.json").st_mode & 0o777) == "0o600"
    with pytest.raises(apis.ApiError):
        apis.add(tmp_path, "deepseek", "https://x.example/v1")
    apis.set_key(tmp_path, "deepseek", None)
    assert apis.load(tmp_path)["deepseek"].key is None
    apis.remove(tmp_path, "deepseek")
    assert not apis.load(tmp_path)


@pytest.mark.parametrize(
    "ep",
    ["ftp://x/v1", "http://u:p@x/v1", "javascript:alert(1)", "https://x/v1?k=1", "", "http:///v1"],
)
def test_bad_endpoints(tmp_path, ep):
    with pytest.raises(apis.ApiError):
        apis.add(tmp_path, "x", ep)


@pytest.mark.parametrize("name", ["Büyük", "../x", "varsayılan", "", "a" * 31])
def test_bad_names(tmp_path, name):
    with pytest.raises(apis.ApiError):
        apis.add(tmp_path, name, "https://x.example/v1")


def seeded(tmp_path):
    seen = []

    def build(ep, nm, pr, key=None):
        seen.append((ep, nm, key))
        return object()

    def discover(ep, key=None):
        return {"http://local/v1": ["l1", "l2"], "https://cloud.example/v1": ["c1"]}.get(ep, [])

    ctl = ModelControl(
        tmp_path,
        "http://local/v1",
        "l1",
        "native",
        build,
        discover,
        explicit_protocol="native",
        default_key=None,
    )
    return ctl, seen


def test_models_of_all_apis_listed_and_switch_across_apis(tmp_path):
    ctl, seen = seeded(tmp_path)
    apis.add(tmp_path, "bulut", "https://cloud.example/v1", "anahtar-1")
    groups = {g["api"]: g["models"] for g in ctl.info()["apis"]}
    assert groups == {"varsayılan": ["l1", "l2"], "bulut": ["c1"]}
    ctl.switch("c1", "bulut")
    assert ctl.api == "bulut" and seen[-1] == ("https://cloud.example/v1", "c1", "anahtar-1")
    assert load_settings(tmp_path).api == "bulut" and load_settings(tmp_path).model == "c1"
    ctl.switch("l2", "varsayılan")
    assert seen[-1][2] is None and load_settings(tmp_path).api is None


def test_unreachable_api_does_not_break_listing(tmp_path):
    ctl, _ = seeded(tmp_path)
    apis.add(tmp_path, "olu", "https://dead.example/v1")
    g = {x["api"]: x for x in ctl.info()["apis"]}
    assert g["olu"]["models"] == [] and g["olu"]["error"] and g["varsayılan"]["models"]


def test_api_endpoints_never_return_keys(tmp_path):
    c, mgr = make_client(tmp_path, object())
    ctl, _ = seeded(tmp_path / "home")
    mgr.model_control = ctl
    assert (
        c.post(
            "/apis",
            json={"name": "bulut", "endpoint": "https://cloud.example/v1", "key": "SIR-DEGER"},
            headers=AUTH,
        ).status_code
        == 201
    )
    rows = c.get("/apis", headers=AUTH)
    assert "SIR-DEGER" not in rows.text and any(r["has_key"] for r in rows.json())
    assert "SIR-DEGER" not in c.get("/model", headers=AUTH).text
    assert (
        c.post(
            "/apis", json={"name": "bulut", "endpoint": "https://x.example/v1"}, headers=AUTH
        ).status_code
        == 409
    )
    assert (
        c.post("/apis", json={"name": "k", "endpoint": "ftp://x"}, headers=AUTH).status_code == 400
    )
    assert c.get("/apis").status_code == 401 and c.delete("/apis/bulut").status_code == 401
    assert (
        c.put("/model", json={"model": "c1", "api": "bulut"}, headers=AUTH).json()["api"] == "bulut"
    )
    assert c.delete("/apis/bulut", headers=AUTH).status_code == 409  # kullanımda
    assert (
        c.put("/model", json={"model": "l1", "api": "varsayılan"}, headers=AUTH).status_code == 200
    )
    assert c.delete("/apis/bulut", headers=AUTH).status_code == 200
    assert "SIR-DEGER" not in json.dumps(c.get("/apis", headers=AUTH).json())
