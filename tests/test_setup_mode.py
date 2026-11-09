"""Kurulum modu: model seçilmeden başlayan sunucu görev almaz, sihirbaz model seçince çalışır."""

import pytest

from test_api import AUTH, Scripted, make_client, new_ws
from usta.modelctl import ModelControl, ModelSwitchError
from usta.models import ModelResponse


def blank_control(tmp_path):
    def discover(ep, key=None):
        return ["m1", "m2"] if ep == "http://local/v1" else []

    return ModelControl(
        tmp_path / "home",
        "http://local/v1",
        "",
        "native",
        lambda ep, nm, pr, key: object(),
        discover,
        explicit_protocol="native",
        persist=False,
    )


def test_blank_control_is_not_ready_and_lists_only_real_models(tmp_path):
    ctl = blank_control(tmp_path)
    assert not ctl.ready
    assert ctl.info()["models"] == ["m1", "m2"]  # boş ad listeye karışmaz


def test_switch_makes_control_ready(tmp_path):
    ctl = blank_control(tmp_path)
    ctl.switch("m1")
    assert ctl.ready and ctl.name == "m1"


def test_tasks_refused_until_a_model_is_chosen(tmp_path):
    ctl = blank_control(tmp_path)
    c, _ = make_client(tmp_path, Scripted(ModelResponse("tamam")), model_control=ctl)
    ws = new_ws(c)
    r = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "merhaba"}, headers=AUTH)
    assert r.status_code == 400 and "model seçilmedi" in r.json()["detail"]
    ctl.switch("m2")
    r = c.post(f"/workspaces/{ws}/tasks", json={"prompt": "merhaba"}, headers=AUTH)
    assert r.status_code == 202


def test_switch_to_unknown_model_keeps_setup_mode(tmp_path):
    ctl = blank_control(tmp_path)
    with pytest.raises(ModelSwitchError):
        ctl.switch("yok")
    ctl.switch("")  # değişiklik yok sayılır
    assert not ctl.ready


def test_ping_reports_friendly_result_and_needs_a_model(tmp_path):
    from usta.models import ModelError

    ctl = blank_control(tmp_path)
    c, _ = make_client(tmp_path, Scripted(ModelResponse("Merhaba")), model_control=ctl)
    assert c.post("/setup/ping", headers=AUTH).status_code == 409  # model seçilmedi
    ctl.switch("m1")
    ctl._client = Scripted(ModelResponse("Merhaba"))
    r = c.post("/setup/ping", headers=AUTH).json()
    assert r["ok"] and r["reply"] == "Merhaba"

    class Failing:
        def chat(self, messages, tools=None):
            raise ModelError("model isteği başarısız: HTTP 401", infra=True)

    ctl._client = Failing()
    bad = c.post("/setup/ping", headers=AUTH).json()
    assert not bad["ok"] and "Anahtar kabul edilmedi" in bad["error"]


def test_friendly_errors_cover_common_cases():
    from usta.api import friendly_model_error as f

    assert "bakiye" in f("model isteği başarısız: HTTP 402")
    assert "bulunamadı" in f("model isteği başarısız: HTTP 404")
    assert "ulaşılamıyor" in f("model isteği başarısız: ConnectError")
    assert "Ayrıntı" in f("garip bir şey")
