"""Yardım raporu: teşhise yarar, ama kullanıcının yazdıklarını, anahtarını ve adını taşımaz."""

import json
import time
from pathlib import Path

from test_api import AUTH, Scripted, make_client, new_ws
from usta import support
from usta.models import ModelError

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


def _seed(home: Path) -> None:
    (home / "audit").mkdir(parents=True)
    rows = [
        {"ts": time.time() - 30, "event": "user_message", "text": "annemin doğum günü sayfası"},
        {
            "ts": time.time() - 20,
            "event": "task_failed",
            "error": "model isteği başarısız: HTTP 402",
        },
        {
            "ts": time.time() - 15,
            "event": "task_failed",
            "error": "model protokolü bozdu: özel not",
        },
        {"ts": time.time() - 10, "event": "task_error", "error_type": "KeyError"},
        {
            "ts": time.time() - 5,
            "event": "tool_call",
            "tool": "write_file",
            "args": {"content": "sır"},
        },
    ]
    (home / "audit" / "abc.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\nbozuk satır\n", "utf-8"
    )
    (home / "usta.log").write_text(
        f"Usta arka planda çalışıyor: http://127.0.0.1:8765/?code=482913\n"
        f"anahtar {KEY}\n"
        f'File "{Path.home() / "proje" / "x.py"}", line 3\n',
        "utf-8",
    )


def test_report_has_diagnostics_but_no_personal_content(tmp_path):
    _seed(tmp_path)
    text = support.report(
        tmp_path,
        model="openrouter/free",
        api="openrouter",
        endpoint="https://kullanici:parola@openrouter.ai/api/v1?k=1",
        settings={"görünüm": "simple"},
        background=True,
    )
    for expected in (
        "Usta sürümü:",
        "Python:",
        "İşletim sistemi:",
        "openrouter/free",
        "adres: openrouter.ai",
        "arka planda",
        "model isteği başarısız: HTTP 402",
        "model protokolü bozdu",
        "KeyError",
        "http://127.0.0.1:8765/",
    ):
        assert expected in text, expected
    for forbidden in ("doğum günü", "özel not", "sır", KEY, "482913", "parola", str(Path.home())):
        assert forbidden not in text, forbidden
    assert "~" in text  # ev klasörü yolu kısaltıldı


def test_report_works_on_an_empty_home(tmp_path):
    text = support.report(tmp_path)
    assert "seçilmedi" in text and "(kayıtlı hata yok)" in text and "Günlüğün sonu" not in text


def test_tidy_leaves_plain_text_alone():
    assert support.tidy("Merhaba dünya: ğüşiöç") == "Merhaba dünya: ğüşiöç"


def test_support_endpoint_needs_auth_and_returns_a_file_name(tmp_path):
    c, _ = make_client(tmp_path, Scripted())
    assert c.get("/support/report").status_code == 401
    d = c.get("/support/report", headers=AUTH).json()
    assert d["filename"].startswith("usta-yardim-") and d["filename"].endswith(".txt")
    assert "Usta yardım raporu" in d["text"]


def test_a_failed_task_is_visible_in_the_report_without_its_prompt(tmp_path):
    class Failing:
        def chat(self, *a, **k):
            raise ModelError("model isteği başarısız: HTTP 429", infra=True)

    c, mgr = make_client(tmp_path, Failing())
    ws = new_ws(c)
    tid = c.post(
        f"/workspaces/{ws}/tasks", json={"prompt": "çok gizli istek", "mode": "auto"}, headers=AUTH
    ).json()["id"]
    assert mgr.get(tid).finished.wait(10)
    text = c.get("/support/report", headers=AUTH).json()["text"]
    assert "model isteği başarısız: HTTP 429" in text
    assert "çok gizli istek" not in text
