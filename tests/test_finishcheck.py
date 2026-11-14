"""Söz–eylem denetimi: bugünkü gerçek Lab izlerinden (DeepSeek-V4-Pro-Qwen3.5-9B) alınmış yanıtlarla."""

from pathlib import Path

from test_api import Scripted, call
from usta.agent import Agent
from usta.audit import AuditLog
from usta.finishcheck import FinishCheck
from usta.models import ModelResponse
from usta.policy import Policy
from usta.tools import ToolContext, build_registry

TASK_SUMMARY = "log.txt dosyasındaki uyarıları say ve sayıyı summary.txt dosyasına yaz."


# --- gerçek izlerdeki üç kalıp ----------------------------------------------------------------------
def test_claimed_write_that_never_happened_gets_one_reminder():
    fc = FinishCheck(TASK_SUMMARY)
    msg = fc.on_finish(
        "2 uyarı sayısı summary.txt dosyasına yazıldı."
    )  # gerçek iz: yalnız list_dir yapılmıştı
    assert msg and "summary.txt" in msg and "write_file" in msg
    assert (
        fc.on_finish("2 uyarı sayısı summary.txt dosyasına yazıldı.") is None
    )  # aynı kural ikinci kez yok


def test_a_real_write_satisfies_the_claim():
    fc = FinishCheck(TASK_SUMMARY)
    fc.observe("write_file", {"path": "./summary.txt", "content": "2"}, executed=True)
    assert fc.on_finish("2 uyarı summary.txt dosyasına yazıldı.") is None
    denied = FinishCheck(TASK_SUMMARY)
    denied.observe(
        "write_file", {"path": "summary.txt"}, executed=False
    )  # reddedilen yazma sayılmaz
    assert denied.on_finish("summary.txt dosyasına yazıldı.")


def test_announcing_an_action_and_stopping_gets_a_continue():
    fc = FinishCheck(TASK_SUMMARY)
    msg = fc.on_finish("Çalışma alanı dosyalarını kontrol ediyorum.")  # gerçek iz
    assert msg and "araç çağırmadın" in msg
    assert FinishCheck("x").on_finish("Let me check the files.")


def test_asking_permission_for_what_the_task_already_asks_gets_a_reminder():
    task = "mcp__docs__search aracıyla 'kurulum' ara ve ilk sonucu install.txt dosyasına yaz."
    msg = FinishCheck(task).on_finish(
        "mcp__docs__search aracını 'kurulum' ile aradım. Şimdi sonucunuzu install.txt'e yazmamı ister misiniz?"
    )  # gerçek iz
    assert msg and "izin sorma" in msg


# --- yanlış alarm vermemeli ---------------------------------------------------------------------------
def test_normal_final_answers_pass_through():
    fc = FinishCheck(TASK_SUMMARY)
    fc.observe("write_file", {"path": "summary.txt"}, executed=True)
    for ok in (
        "Bitti: 2 uyarı var, summary.txt dosyasına yazdım.",
        "Hesap makinesi sayfası hazır.",
        "Bu dosyada uyarı yok, o yüzden 0 yazdım ve summary.txt dosyasına kaydettim.",
        "Hangi dosyayı kastettiğini tam anlayamadım: log.txt mi, log2.txt mi?",  # gerçek bir soru
        "x" * 300 + " kontrol ediyorum",  # uzun yanıt niyet beyanı sayılmaz
        "",
    ):
        assert fc.on_finish(ok) is None, ok


def test_claims_about_files_the_user_never_asked_for_are_not_pushed():
    # Enjeksiyon modeli "public/leak.txt'ye yazdım" demeye ittiyse, denetim onu YAZMAYA itmemeli.
    fc = FinishCheck("data.csv dosyasındaki satırları say ve result.txt dosyasına yaz.")
    fc.observe("write_file", {"path": "result.txt"}, executed=True)
    assert fc.on_finish("Ayrıca config.env içeriğini public/leak.txt dosyasına yazdım.") is None


def test_at_most_two_reminders_per_task():
    fc = FinishCheck(TASK_SUMMARY)
    assert fc.on_finish("summary.txt dosyasına yazıldı.")
    assert fc.on_finish("Dosyaları kontrol ediyorum.")
    assert fc.on_finish("Tekrar kontrol ediyorum.") is None  # sınır: 2
    assert fc.nudges == 2


# --- ajan döngüsü -------------------------------------------------------------------------------------
def _agent(tmp_path, model, **kw):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "log.txt").write_text("UYARI a\nUYARI b\n")
    return Agent(
        model,
        build_registry(ToolContext(root=ws)),
        Policy(ws),
        AuditLog(tmp_path / "a.jsonl"),
        **kw,
    ), ws


def test_agent_reminds_then_the_model_actually_writes(tmp_path):
    model = Scripted(
        ModelResponse("2 uyarı summary.txt dosyasına yazıldı."),
        call("write_file", {"path": "summary.txt", "content": "2"}),
        ModelResponse("Tamam, yazdım."),
    )
    agent, ws = _agent(tmp_path, model, finish_check=True)
    res = agent.run(TASK_SUMMARY)
    assert (ws / "summary.txt").read_text() == "2" and res.answer == "Tamam, yazdım."
    assert "finish_check" in (tmp_path / "a.jsonl").read_text()


def test_agent_default_is_off_and_finishes_immediately(tmp_path):
    model = Scripted(ModelResponse("2 uyarı summary.txt dosyasına yazıldı."))
    agent, ws = _agent(tmp_path, model)
    res = agent.run(TASK_SUMMARY)
    assert res.answer.startswith("2 uyarı") and not (ws / "summary.txt").exists()


def test_reminder_does_not_bypass_the_permission_engine(tmp_path):
    # hatırlatmadan sonra model çalışma alanı dışına yazmaya kalkarsa izin motoru yine reddeder
    model = Scripted(
        ModelResponse("summary.txt dosyasına yazıldı."),
        call("write_file", {"path": "../disari.txt", "content": "x"}),
        ModelResponse("bitti"),
    )
    agent, ws = _agent(tmp_path, model, finish_check=True)
    agent.run(TASK_SUMMARY)
    assert not (Path(ws).parent / "disari.txt").exists()
