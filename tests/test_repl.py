import re
import threading
from pathlib import Path

from usta import settings as st
from usta.models import ModelResponse, ToolCall
from usta.repl import Repl
from usta.tasks import TaskManager

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Out:
    def __init__(self):
        self.parts = []

    def write(self, s):
        self.parts.append(s)
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False

    @property
    def text(self):
        return "".join(self.parts)


class Scripted:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def chat(self, messages, tools=None):
        self.seen.append((messages, [t["name"] for t in tools or []]))
        return self.responses.pop(0) if self.responses else ModelResponse("tamam")


def call(name, args, i=1):
    return ModelResponse(None, [ToolCall(f"c{i}", name, args)])


def feed(*lines):
    it = iter(lines)

    def inp(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return inp


def make(tmp_path, model, *lines, **kw):
    ws = tmp_path / "proje"
    ws.mkdir(exist_ok=True)
    home = tmp_path / "home"
    mgr = TaskManager(lambda: model, home=home)
    out = Out()
    raw = feed(*lines)

    def inp(prompt=""):  # gerçek terminalde input() istemi ekrana basar
        out.write(ANSI.sub("", prompt.replace("\001", "").replace("\002", "")))
        return raw(prompt)

    repl = Repl(
        mgr,
        ws,
        "proje-ab12",
        home,
        kw.pop("settings", st.Settings()),
        inp=inp,
        out=out,
        **kw,
    )
    return repl, out, ws, mgr


def test_banner_shows_model_workspace_mode_and_help_hint(tmp_path):
    repl, out, _, _ = make(
        tmp_path, Scripted(), "/çık", model_name="qwen", portal_url="http://127.0.0.1:8765/"
    )
    assert repl.run() == 0
    t = out.text
    assert "qwen" in t and "proje" in t and "manuel" in t and "/yardım" in t and "8765" in t


def test_eof_exits_cleanly(tmp_path):
    repl, _, _, _ = make(tmp_path, Scripted())
    assert repl.run() == 0


def test_plain_prompt_runs_task_and_prints_answer_and_tool_activity(tmp_path):
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "selam\n"}),
        ModelResponse("Dosyayı yazdım."),
    )
    repl, out, ws, _ = make(tmp_path, model, "a.txt yaz")
    repl.run()
    t = out.text
    assert (ws / "a.txt").read_text() == "selam\n"
    assert "write_file" in t and "Dosyayı yazdım." in t
    assert "+selam" in t and "a.txt" in t  # değişen kod diff olarak gösterilir


def test_diff_is_colored_with_theme_when_color_on(tmp_path):
    model = Scripted(call("write_file", {"path": "a.txt", "content": "x\n"}), ModelResponse("ok"))
    repl, out, _, _ = make(tmp_path, model, "yaz", color=True)
    repl.run()
    assert "\x1b[" in out.text
    added = [ln for ln in out.text.splitlines() if ANSI.sub("", ln) == "+x"]
    assert added and added[0].startswith("\x1b[")


def test_no_color_when_disabled(tmp_path):
    model = Scripted(call("write_file", {"path": "a.txt", "content": "x\n"}), ModelResponse("ok"))
    repl, out, _, _ = make(tmp_path, model, "yaz", color=False)
    repl.run()
    assert "\x1b[" not in out.text


def test_help_lists_commands(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/yardım")
    repl.run()
    for cmd in ("/mod", "/tema", "/diff", "/geri", "/token", "/çık"):
        assert cmd in out.text


def test_unknown_command_gives_hint_and_does_not_call_model(tmp_path):
    model = Scripted()
    repl, out, _, _ = make(tmp_path, model, "/bilinmeyen")
    repl.run()
    assert "bilinmeyen komut" in out.text and "/yardım" in out.text and model.seen == []


def test_theme_command_switches_and_persists(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/tema gri", "/tema")
    repl.run()
    assert st.load(tmp_path / "home").theme == "gri"
    assert "gri" in out.text
    repl2, out2, _, _ = make(tmp_path, Scripted(), "/tema pembe")
    repl2.run()
    assert "bilinmeyen tema" in out2.text and st.load(tmp_path / "home").theme == "gri"


def test_mode_command_cycles_and_sets_and_persists(tmp_path):
    repl, _out, _, _ = make(tmp_path, Scripted(), "/mod auto", "/mod plan", "/mod")
    repl.run()
    assert repl.mode == "manual"  # plan'dan sonra döngü: manuel'e döner
    assert st.load(tmp_path / "home").mode == "manual"
    repl2, out2, _, _ = make(tmp_path, Scripted(), "/mod tehlikeli")
    repl2.run()
    assert "geçersiz mod" in out2.text and repl2.mode == "manual"


def test_auto_mode_banner_warns(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/mod auto")
    repl.run()
    assert "oto" in out.text.lower() and "onay" in out.text.lower()


def test_plan_mode_shows_plan_then_asks_and_applies_on_yes(tmp_path):
    model = Scripted(
        ModelResponse("1) a.txt oluştur"),  # plan
        call("write_file", {"path": "a.txt", "content": "plan uygulandı\n"}),
        ModelResponse("uyguladım"),
    )
    repl, out, ws, _ = make(tmp_path, model, "/mod plan", "dosya oluştur", "m")
    repl.run()
    assert "1) a.txt oluştur" in out.text and "Planı uygula" in out.text
    assert (ws / "a.txt").read_text() == "plan uygulandı\n"
    applied_prompt = model.seen[1][0][1].content
    assert "ONAYLI-PLAN" in applied_prompt and "1) a.txt oluştur" in applied_prompt
    assert "dosya oluştur" not in applied_prompt  # orijinal istem yeniden yazılmaz
    assert (
        repl.mode == "plan" or repl.mode == "manual"
    )  # uygulama sonrası kullanıcının modu korunur


def test_plan_mode_decline_changes_nothing(tmp_path):
    model = Scripted(ModelResponse("plan metni"))
    repl, _out, ws, _ = make(tmp_path, model, "/mod plan", "bir şey yap", "h")
    repl.run()
    assert [p.name for p in ws.iterdir() if p.name != ".usta"] == [] and len(model.seen) == 1


def test_plan_mode_tools_are_read_only(tmp_path):
    model = Scripted(ModelResponse("plan"))
    repl, _, _, _ = make(tmp_path, model, "/mod plan", "x", "h")
    repl.run()
    assert set(model.seen[0][1]) == {"read_file", "list_dir", "fetch_url"}


def test_manual_approval_prompt_allow_and_deny(tmp_path):
    import sys

    from usta import mcpconfig

    fake = str(Path(__file__).parent / "fake_mcp.py")
    srv = mcpconfig.Server("fake", (sys.executable, "-I", fake), (), "ask", True, isolation="host")
    for answer, expect in (("e", "selam mcp"), ("h", "reddedildi")):
        model = Scripted(call("mcp__fake__echo", {"text": "selam mcp"}), ModelResponse("bitti"))
        ws = tmp_path / f"w{answer}"
        ws.mkdir()
        mgr = TaskManager(lambda m=model: m, home=tmp_path / f"h{answer}", mcp_servers=[srv])
        out = Out()
        Repl(
            mgr,
            ws,
            "p-1234",
            tmp_path / f"h{answer}",
            st.Settings(),
            inp=feed("dene", answer),
            out=out,
        ).run()
        assert "zin gerekiyor" in out.text
        tool_msg = next(m for m in model.seen[1][0] if m.role == "tool").content
        assert expect in tool_msg


def test_auto_mode_does_not_prompt(tmp_path):
    import sys

    from usta import mcpconfig

    fake = str(Path(__file__).parent / "fake_mcp.py")
    srv = mcpconfig.Server("fake", (sys.executable, "-I", fake), (), "ask", True, isolation="host")
    model = Scripted(call("mcp__fake__echo", {"text": "otomatik"}), ModelResponse("bitti"))
    mgr = TaskManager(lambda: model, home=tmp_path / "h", mcp_servers=[srv])
    ws = tmp_path / "w"
    ws.mkdir()
    out = Out()
    Repl(
        mgr, ws, "p-1234", tmp_path / "h", st.Settings(mode="auto"), inp=feed("dene"), out=out
    ).run()
    assert "otomatik" in next(m for m in model.seen[1][0] if m.role == "tool").content
    assert "oto-onay" in out.text.lower() or "otomatik onay" in out.text.lower()


def test_diff_command_shows_last_changes_and_revert_undoes_after_confirm(tmp_path):
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "yeni\n"}), ModelResponse("ok")
    )
    repl, out, ws, _ = make(tmp_path, model, "yaz", "/diff", "/geri", "e")
    repl.run()
    assert out.text.count("+yeni") >= 2  # görev sonunda bir, /diff ile bir daha
    assert not (ws / "a.txt").exists()
    assert "geri alındı" in out.text


def test_revert_declined_keeps_changes(tmp_path):
    model = Scripted(
        call("write_file", {"path": "a.txt", "content": "yeni\n"}), ModelResponse("ok")
    )
    repl, _out, ws, _ = make(tmp_path, model, "yaz", "/geri", "h")
    repl.run()
    assert (ws / "a.txt").exists()


def test_revert_without_task_is_graceful(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/geri", "/diff", "/token")
    repl.run()
    assert "henüz görev yok" in out.text


def test_token_line_after_task_and_token_command(tmp_path):
    from usta.models import Usage

    class Counting(Scripted):
        usage = Usage()

        def chat(self, messages, tools=None):
            self.usage.prompt += 120
            self.usage.completion += 8
            self.usage.requests += 1
            self.usage.last_prompt = 120
            return super().chat(messages, tools)

    repl, out, _, _ = make(
        tmp_path, Counting(ModelResponse("ok")), "merhaba", "/token", context_window=8192
    )
    repl.run()
    assert out.text.count("128 token") >= 2 and "%1" in out.text


def test_ctrl_c_during_task_cancels_it(tmp_path):
    gate = threading.Event()

    class Slow(Scripted):
        def chat(self, messages, tools=None):
            gate.wait(5)
            return call("list_dir", {"path": "."})

    model = Slow()
    repl, out, _, mgr = make(tmp_path, model, "uzun görev")
    original = repl._wait_for
    fired = []

    def interrupting(task, i):
        if not fired:
            fired.append(1)
            threading.Timer(0.3, gate.set).start()
            raise KeyboardInterrupt
        return original(task, i)

    repl._wait_for = interrupting
    repl.run()
    assert "durdur" in out.text.lower()
    assert all(t.status in ("cancelled", "done", "failed") for t in mgr.tasks.values())


def test_busy_workspace_message(tmp_path):
    gate = threading.Event()

    class Slow(Scripted):
        def chat(self, messages, tools=None):
            gate.wait(5)
            return ModelResponse("ok")

    repl, out, ws, mgr = make(tmp_path, Slow(), "ikinci")
    first = mgr.start("proje-ab12", ws, "birinci")
    repl.run()
    gate.set()
    first.finished.wait(5)
    assert "meşgul" in out.text.lower() or "sürüyor" in out.text.lower()


def test_memory_and_mcp_commands_are_read_only_views(tmp_path):
    from usta import memory

    repl, out, ws, _ = make(tmp_path, Scripted(), "/hafıza", "/mcp")
    memory.add_note(ws, "test: make ci")
    repl.run()
    assert "make ci" in out.text and "MCP" in out.text


def test_model_command_shows_model_and_protocol(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/model", model_name="qwen3:4b", protocol="text")
    repl.run()
    assert "qwen3:4b" in out.text and "text" in out.text


def test_slash_in_normal_text_is_a_prompt_when_path_like(tmp_path):
    model = Scripted(ModelResponse("tamam"))
    repl, _out, _, _ = make(tmp_path, model, "/home/x/proje dosyasını oku")
    repl.run()
    assert len(model.seen) == 1  # bilinmeyen komut sanılmaz: istem olarak gider


def test_koruma_command_toggles_persists_and_applies_to_next_task(tmp_path):
    model = Scripted(ModelResponse("tamam"))
    repl, out, _, mgr = make(tmp_path, model, "/koruma", "/koruma aç", "merhaba", "/koruma kapat")
    repl.run()
    assert "koruma: kapalı" in out.text and "koruma: açık" in out.text
    task = next(iter(mgr.tasks.values()))
    assert task.guard is True
    assert st.load(tmp_path / "home").guard is False  # son komut kapattı


def test_koruma_invalid_argument(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/koruma belki")
    repl.run()
    assert "aç" in out.text and "kapat" in out.text and repl.settings.guard is False


def test_breaker_event_is_rendered_to_user(tmp_path):
    repl, out, _, mgr = make(tmp_path, Scripted(ModelResponse("x")))
    task = mgr.start("proje-ab12", repl.root, "x")
    task.finished.wait(5)
    repl._render(
        task,
        {
            "i": 99,
            "type": "breaker",
            "data": {"reason": "aynı hata", "final": False, "tried": ["a", "b"]},
        },
    )
    assert "devre kesici" in out.text.lower() and "aynı hata" in out.text
    repl._render(
        task, {"i": 100, "type": "breaker", "data": {"reason": "döngü", "final": True, "tried": []}}
    )
    assert "sana bırak" in out.text.lower() or "yönlendirme" in out.text.lower()


def test_help_lists_koruma(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), "/yardım")
    repl.run()
    assert "/koruma" in out.text


def test_dogrula_command_sets_shows_and_clears_project_verify(tmp_path):
    from usta import projectcfg

    repl, out, ws, _ = make(
        tmp_path,
        Scripted(),
        "/doğrula",
        "/doğrula pytest -q tests",
        "/doğrula",
        "/doğrula temizle",
        "/doğrula",
    )
    repl.run()
    assert out.text.count("otomatik") >= 2 and "pytest -q tests" in out.text
    assert projectcfg.load(tmp_path / "home", ws).verify is None  # son komut temizledi


def test_dogrula_bad_quoting_is_a_message_not_a_crash(tmp_path):
    repl, out, _, _ = make(tmp_path, Scripted(), '/doğrula pytest "kapanmamis')
    assert repl.run() == 0 and "geçersiz" in out.text


def test_history_command_lists_and_shows_sessions(tmp_path):
    repl, out, _, _ = make(
        tmp_path, Scripted(ModelResponse("Selam dünya", [])), "ilk görev", "/geçmiş", "/geçmiş 1"
    )
    repl.run()
    assert "ilk görev" in out.text and "Selam dünya" in out.text


def test_banner_shows_workspace_folder_and_warns_for_home(tmp_path, monkeypatch):
    repl, out, _, _ = make(tmp_path, Scripted())
    repl.run()
    assert "Çalışma klasörü:" in out.text and str(repl.root) in out.text
    assert "Uyarı: ev dizini" not in out.text
    repl2, out2, _, _ = make(tmp_path, Scripted())
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: repl2.root))
    repl2.run()
    assert "Uyarı: ev dizini" in out2.text


def test_phased_plan_apply_runs_all_phases_in_terminal(tmp_path):
    from test_phased import Phased
    from usta.tasks import plan_checklist

    repl, out, ws, _ = make(tmp_path, Phased(), "/mod plan", "pet shop yap", "a")
    repl.run()
    assert plan_checklist(ws) == (3, [])
    for i in (1, 2, 3):
        assert f"Aşama {i}/3" in out.text
    assert "Tüm aşamalar tamam" in out.text
