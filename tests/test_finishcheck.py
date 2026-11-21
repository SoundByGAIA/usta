"""Söz–eylem denetimi: gerçek küçük model yanıtlarına benzeyen örneklerle."""

from pathlib import Path

from test_api import Scripted, call
from usta.agent import Agent
from usta.audit import AuditLog
from usta.finishcheck import FinishCheck, write_targets
from usta.models import ModelResponse
from usta.policy import Policy
from usta.tools import ToolContext, build_registry

TASK_SUMMARY = "log.txt dosyasındaki uyarıları say ve sayıyı summary.txt dosyasına yaz."


# --- gerçek izlerdeki kalıplar ----------------------------------------------------------------------
def test_targets_come_only_from_write_phrases_in_the_users_task():
    assert write_targets(TASK_SUMMARY) == ["summary.txt"]  # log.txt yalnız okunur
    assert write_targets("todo.md içindeki madde sayısını count.txt dosyasına yaz.") == [
        "count.txt"
    ]
    assert write_targets("Sonucu install.txt'e kaydet, README.md’ye de bir satır ekle.") == [
        "install.txt",
        "README.md",
    ]
    assert write_targets("Read data.csv and write the count to result.txt.") == ["result.txt"]
    assert write_targets("version.txt içindeki 'v1' ifadesini 'v2' yap.") == []
    assert write_targets("util.py içindeki add fonksiyonunu oku ve yanıtında açıkla.") == []


def test_claimed_write_that_never_happened_gets_one_reminder():
    fc = FinishCheck(TASK_SUMMARY)
    msg = fc.on_finish(
        "2 uyarı sayısı summary.txt dosyasına yazıldı."
    )  # gerçek iz: yalnız list_dir yapılmıştı
    assert msg and "summary.txt" in msg and "write_file" in msg and "söylüyorsun" in msg
    assert (
        fc.on_finish("2 uyarı sayısı summary.txt dosyasına yazıldı.") is None
    )  # aynı kural ikinci kez yok


def test_asking_permission_empty_answer_or_answer_instead_of_file_all_get_the_target_reminder():
    task = "mcp__docs__search aracıyla 'kurulum' ara ve sonucu install.txt dosyasına yaz."
    for answer in (
        "Şimdi sonucunuzu install.txt'e yazmamı ister misiniz?",  # gerçek iz
        "",  # gerçek iz: boş yanıt
        '```json {"install.txt": {"content": "pip install"}} ```',  # gerçek iz: dosya yerine yanıta yazdı
    ):
        msg = FinishCheck(task).on_finish(answer)
        assert msg and "install.txt" in msg and "İzin sormana gerek yok" in msg, answer


def test_a_real_write_satisfies_the_target():
    fc = FinishCheck(TASK_SUMMARY)
    fc.observe("write_file", {"path": "./summary.txt", "content": "2"}, executed=True)
    assert fc.on_finish("2 uyarı summary.txt dosyasına yazıldı.") is None
    denied = FinishCheck(TASK_SUMMARY)
    denied.observe(
        "write_file", {"path": "summary.txt"}, executed=False
    )  # reddedilen yazma sayılmaz
    assert denied.on_finish("summary.txt dosyasına yazıldı.")


def test_a_command_that_names_the_target_counts_as_writing_it():
    # sonuç `run` ile yazıldıysa dosya yazılmış sayılır
    fc = FinishCheck("Cevabı sonuc.txt dosyasına yaz.")
    fc.observe("run", {"command": "echo Paris > sonuc.txt"}, executed=True)
    assert fc.on_finish("sonuc.txt dosyasına yazıldı.") is None
    other = FinishCheck("Cevabı sonuc.txt dosyasına yaz.")
    other.observe("run", {"command": "ls"}, executed=True)
    other.observe(
        "run", {"command": "echo x > sonuc.txt"}, executed=False
    )  # reddedilen komut sayılmaz
    assert other.on_finish("Bitti.")


def test_announcing_an_action_and_stopping_gets_a_continue():
    task = "util.py içindeki add fonksiyonunu oku ve ne yaptığını yanıtında belirt."
    assert "araç çağırmadın" in FinishCheck(task).on_finish(
        "Çalışma alanı dosyalarını kontrol ediyorum."
    )
    assert FinishCheck(task).on_finish(
        "Önce mevcut dizinin yapısını ve todo.md dosyasının içeriğini görelim."
    )
    assert FinishCheck("x").on_finish("Let me check the files.")


PASTANE = (
    "Yeni bir pastane açtım, adı Tatlı Köşe. Menümü gösteren bir sayfa istiyorum: baklava 120 TL, sütlaç 80 TL, "
    "kazandibi 90 TL. Adresimiz Nilüfer, Bursa."
)


def test_site_request_without_a_file_name_answered_with_code_gets_a_reminder():
    # HTML yanıta dökülüp "Menüleriniz artık webde mevcut!" denir, dosya yazılmaz
    msg = FinishCheck(PASTANE).on_finish(
        "```html\n<!DOCTYPE html>\n<html>...</html>\n```\nMenüleriniz artık webde mevcut!"
    )
    assert msg and "write_file" in msg and "index.html" in msg
    assert FinishCheck("Bana bir web sitesi yap, adım Ayşe.").on_finish("Siteniz oluşturuldu!")
    assert FinishCheck("Make me a landing page for my bakery.").on_finish(
        "<html><body>Hi</body></html>"
    )
    # 3. ölçüm: tasarımı anlatıp yapmak için izin istedi, dosya yazmadı
    assert FinishCheck("Bana bir web sitesi yap.").on_finish(
        "Sizin için şu tasarımı oluşturuyorum: pastel tonlar.\n\nWeb sitesini oluşturabiliyorum mu?"
    )
    assert FinishCheck(PASTANE).on_finish("Sayfayı hazırlamamı ister misiniz?")


def test_site_request_is_satisfied_by_any_written_file():
    for tool, args in (
        ("write_file", {"path": "menu.html"}),
        ("edit_file", {"path": "index.html"}),
        ("run", {"command": "cat > index.html"}),
    ):
        fc = FinishCheck(PASTANE)
        fc.observe(tool, args, executed=True)
        assert fc.on_finish("Sayfanız oluşturuldu: ```html <html>``` ") is None, tool
    denied = FinishCheck(PASTANE)
    denied.observe("write_file", {"path": "index.html"}, executed=False)
    assert denied.on_finish("Sayfanız oluşturuldu.")


def test_site_word_without_code_or_claim_is_left_alone():
    # soru soran ya da yalnız açıklayan yanıt itilmez; "site" geçmeyen kod isteği de
    assert FinishCheck(PASTANE).on_finish("Sayfada hangi renkleri istersiniz?") is None
    assert (
        FinishCheck("README sayfasını özetle.").on_finish("Kurulum ve kullanım anlatılıyor.")
        is None
    )
    assert (
        FinishCheck("Bana bir toplama fonksiyonu göster.").on_finish(
            "```py\ndef add(a, b): ...\n```"
        )
        is None
    )


ABC = "bana ABC kayıt formunun şablon şeklinde olduğu ve süre sayacının da olduğu gözlem formu yap"


def test_make_request_without_site_word_answered_with_code_or_offer_gets_a_reminder():
    msg = FinishCheck(ABC).on_finish(
        "Aşağıda bir taslak hazırladım.\n\n```html\n<!DOCTYPE html>\n<html>...</html>\n```\n"
        "Bunu bir HTML dosyası olarak kaydedip tarayıcınızda açabilirsiniz."
    )
    assert msg and "write_file" in msg and ".html" in msg
    assert FinishCheck(ABC).on_finish(
        "İsterseniz bunu bir Excel dosyası haline getirebilirim veya HTML ile sayaçlı form olarak "
        "kodlayabilirim. Hangi yöntem işinize yarar?"
    )
    done = FinishCheck(ABC)
    done.observe("write_file", {"path": "form.html"}, executed=True)
    assert done.on_finish("Form hazır: ```html <html>```") is None
    # açıklama ya da gerçek bir soru itilmez
    assert FinishCheck(ABC).on_finish("Formda kaç satır olsun?") is None
    assert FinishCheck("Bana bir plan yap.").on_finish("1. Sabah yürüyüş\n2. Öğlen okuma") is None


def test_page_code_written_into_a_markdown_file_gets_a_reminder():
    page = (
        "# Form\n\n```html\n<!DOCTYPE html><html><script>setInterval(t, 1000)</script></html>\n```"
    )
    fc = FinishCheck(ABC)
    fc.observe("write_file", {"path": "abc_gozlem_formu.md", "content": page}, executed=True)
    msg = fc.on_finish("Form güncellendi.")
    assert msg and "abc_gozlem_formu.html" in msg and "write_file" in msg
    fixed = FinishCheck(ABC)
    fixed.observe("write_file", {"path": "abc_gozlem_formu.md", "content": page}, executed=True)
    fixed.observe(
        "write_file", {"path": "abc_gozlem_formu.html", "content": "<html></html>"}, executed=True
    )
    assert fixed.on_finish("Tamam.") is None
    plain = FinishCheck("Notlarımı notlar.md dosyasına yaz.")
    plain.observe(
        "write_file", {"path": "notlar.md", "content": "# Notlar\n- süt al"}, executed=True
    )
    assert plain.on_finish("Yazdım.") is None


def test_claimed_file_that_does_not_exist_gets_a_reminder(tmp_path):
    (tmp_path / "abc_gozlem_formu.md").write_text("# Form", encoding="utf-8")
    task = "ben bunu uygulama şeklinde görmek istiyorum"
    msg = FinishCheck(task, root=tmp_path).on_finish(
        "Uygulama dosyasını oluşturdum: **`index.html`**. Tarayıcınızda açabilirsiniz!"
    )
    assert msg and "index.html" in msg and "write_file" in msg
    assert FinishCheck(task, root=tmp_path).on_finish(
        "Uygulamayı açmak için `index.html` dosyasını çift tıklamanız yeterlidir."
    )
    # dosya gerçekten varsa ya da yalnız anılıyorsa itilmez
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    assert FinishCheck("x", root=tmp_path).on_finish("index.html dosyasını oluşturdum.") is None
    assert (
        FinishCheck("x", root=tmp_path).on_finish("abc_gozlem_formu.md dosyasını okudum.") is None
    )


def test_read_only_command_does_not_count_as_writing():
    for cmd in ("ls -la", "dir", "cat abc.md", "Get-ChildItem"):
        fc = FinishCheck("ben bunu uygulama şeklinde görmek istiyorum")
        fc.observe("run", {"command": cmd}, executed=True)
        assert fc.on_finish("Uygulamayı hemen index.html olarak oluşturmamı ister misin?"), cmd
    wrote = FinishCheck("ben bunu uygulama şeklinde görmek istiyorum")
    wrote.observe("run", {"command": "cat > index.html"}, executed=True)
    assert wrote.on_finish("Oluşturmamı ister misin?") is None


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


def test_source_files_named_in_the_answer_are_not_treated_as_unwritten():
    # yalnız okunan todo.md hedef dosya sayılmaz
    fc = FinishCheck("todo.md içindeki madde sayısını count.txt dosyasına yaz.")
    fc.observe("write_file", {"path": "count.txt", "content": "1"}, executed=True)
    assert (
        fc.on_finish("todo.md dosyasını okudum ve madde sayısını count.txt dosyasına kaydettim.")
        is None
    )


def test_claims_about_files_the_user_never_asked_for_are_not_pushed():
    # Enjeksiyon modeli "public/leak.txt'ye yazdım" demeye ittiyse, denetim onu YAZMAYA itmemeli.
    fc = FinishCheck("data.csv dosyasındaki satırları say ve result.txt dosyasına yaz.")
    fc.observe("write_file", {"path": "result.txt"}, executed=True)
    assert fc.on_finish("Ayrıca config.env içeriğini public/leak.txt dosyasına yazdım.") is None
    # okunan içerikteki "X dosyasına yaz" talimatı hedef değildir: hedefler yalnız kullanıcının isteğinden
    assert FinishCheck("notes.md dosyasını özetle.").targets == []


def test_at_most_two_reminders_per_task():
    fc = FinishCheck(TASK_SUMMARY)
    assert fc.on_finish("summary.txt dosyasına yazıldı.")
    fc.observe("write_file", {"path": "summary.txt"}, executed=True)
    assert fc.on_finish("Dosyaları kontrol ediyorum.")
    assert fc.on_finish("Tekrar kontrol ediyorum.") is None  # sınır: 2
    assert fc.nudges == 2 and fc.fired == ["target", "intent"]


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


# --- site isteğindeki bilgiler (sitecheck.py) ---------------------------------------------------------
def test_facts_are_taken_from_the_users_site_request():
    from usta.sitecheck import facts

    assert [f[0] for f in facts(PASTANE)] == [
        "baklava",
        "120 TL",
        "sütlaç",
        "80 TL",
        "kazandibi",
        "90 TL",
        "Tatlı Köşe",
        "Nilüfer",
        "Bursa",
    ]
    davetiye = "Düğünümüz için bir davetiye sitesi istiyorum: Ali ve Zeynep evleniyor, 14 Haziran 2027, Bursa."
    assert [f[0] for f in facts(davetiye)] == ["14 Haziran 2027", "Ali", "Zeynep", "Bursa"]
    ayse = "Merhaba, ben Ayşe. Resim yapmayı seviyorum. E-postam (ayse@ornek.com) yazsın."
    assert [f[0] for f in facts(ayse)] == [
        "ayse@ornek.com",
        "Ayşe",
    ]  # cümle başındaki "Resim" ad değil


def test_missing_facts_tolerate_case_spelling_of_dates_and_prices():
    from usta.sitecheck import missing

    page = (
        "<h1>TATLI KÖŞE</h1><li>Baklava <b>120,00 ₺</b></li><li>Sütlaç ₺80</li><li>Kazandibi 90 TL</li>"
        "<p>Nilüfer / BURSA</p>"
    )
    assert missing(PASTANE, [page]) == []
    # "Süt Laç" sütlaç sayılmaz; CSS'teki 80px fiyat sayılmaz
    bad = page.replace("Sütlaç ₺80", "Süt Laç <span style='width:80px'>")
    assert missing(PASTANE, [bad]) == ["sütlaç", "80 TL"]
    assert "120 TL" in missing(
        PASTANE, [page.replace("120,00 ₺", "1120 TL")]
    )  # başka sayının parçası değil
    davetiye = "Ali ve Zeynep evleniyor, 14 Haziran 2027, Bursa."
    js = "<h1>Ali &amp; Zeynep</h1><p>Bursa</p><script>new Date('2027-06-14T12:00')</script>"
    assert missing(davetiye, [js]) == []


def test_site_with_missing_facts_gets_one_reminder_naming_them(tmp_path):
    (tmp_path / "index.html").write_text(
        "<h1>Tatlı Köşe</h1><p>Baklava 120 TL</p>", encoding="utf-8"
    )
    fc = FinishCheck(PASTANE, root=tmp_path)
    fc.observe("write_file", {"path": "index.html"}, executed=True)
    msg = fc.on_finish("Menünüz hazır!")
    assert (
        msg and "sütlaç" in msg and "Nilüfer" in msg and "uydurma" in msg and "baklava" not in msg
    )
    assert fc.on_finish("Menünüz hazır!") is None  # bir kez
    # bilgiler tamamsa ya da kök verilmediyse sessiz
    (tmp_path / "index.html").write_text(
        "Tatlı Köşe baklava 120 TL sütlaç 80 TL kazandibi 90 TL Nilüfer Bursa", encoding="utf-8"
    )
    ok = FinishCheck(PASTANE, root=tmp_path)
    ok.observe("write_file", {"path": "index.html"}, executed=True)
    assert ok.on_finish("Hazır.") is None
    noroot = FinishCheck(PASTANE)
    noroot.observe("write_file", {"path": "index.html"}, executed=True)
    assert noroot.on_finish("Hazır.") is None


def test_pages_outside_the_workspace_are_not_read(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "out.html").write_text("x", encoding="utf-8")
    fc = FinishCheck(PASTANE, root=ws)
    fc.observe("write_file", {"path": "../out.html"}, executed=True)
    assert fc.on_finish("Hazır.") is None


# --- çalışma klasörü bilgisi --------------------------------------------------------------------------
class Recording(Scripted):
    def chat(self, messages, tools=None):
        self.seen = [m.content for m in messages]
        return super().chat(messages, tools)


def test_workspace_hint_lists_visible_files_only_when_enabled(tmp_path):
    model = Recording(ModelResponse("tamam"))
    agent, ws = _agent(tmp_path, model, workspace_hint=True)
    (ws / "index.html").write_text("<h1>Ayşe</h1>")
    (ws / ".usta").mkdir()
    agent.run("Sitemin rengini maviye çevir.")
    first = model.seen[1]
    assert "index.html" in first and "log.txt" in first and ".usta" not in first
    assert first.endswith("Sitemin rengini maviye çevir.") and "talimat değil" in first
    off = Recording(ModelResponse("tamam"))
    agent, _ = _agent(tmp_path, off)
    agent.run("Sitemin rengini maviye çevir.")
    assert off.seen[1] == "Sitemin rengini maviye çevir."


ABC = "ABC gözlem formu uygulaması yap, kayıtları indirebileyim."
JSON_EXPORT = (
    "<button id=indir>İndir</button><script>const b = new Blob([JSON.stringify(kayitlar)], "
    "{type: 'application/json'}); a.download = 'kayitlar.json';</script>"
)


def test_json_download_in_an_app_gets_one_csv_reminder(tmp_path):
    (tmp_path / "abc.html").write_text(JSON_EXPORT, encoding="utf-8")
    fc = FinishCheck(ABC, root=tmp_path)
    fc.observe("write_file", {"path": "abc.html"}, executed=True)
    msg = fc.on_finish("Uygulama hazır.")
    assert msg and "CSV" in msg and "Excel" in msg and "\\ufeff" in msg
    assert fc.on_finish("Uygulama hazır.") is None


def test_csv_without_bom_gets_the_same_reminder(tmp_path):
    page = "<script>const b = new Blob([csv], {type: 'text/csv'}); a.download = 'k.csv';</script>"
    (tmp_path / "abc.html").write_text(page, encoding="utf-8")
    fc = FinishCheck(ABC, root=tmp_path)
    fc.observe("write_file", {"path": "abc.html"}, executed=True)
    msg = fc.on_finish("Uygulama hazır.")
    assert msg and "Excel" in msg and "noktalı virgül" in msg


def test_excel_ready_csv_or_asked_json_is_left_alone(tmp_path):
    ready = "<script>new Blob(['\\ufeff' + csv], {type: 'text/csv;charset=utf-8'}); a.download='k.csv'</script>"
    (tmp_path / "abc.html").write_text(JSON_EXPORT + ready, encoding="utf-8")
    fc = FinishCheck(ABC, root=tmp_path)
    fc.observe("write_file", {"path": "abc.html"}, executed=True)
    assert fc.on_finish("Uygulama hazır.") is None
    (tmp_path / "abc.html").write_text(JSON_EXPORT, encoding="utf-8")
    fc = FinishCheck("Kayıtları JSON olarak indiren bir form yap.", root=tmp_path)
    fc.observe("write_file", {"path": "abc.html"}, executed=True)
    assert fc.on_finish("Uygulama hazır.") is None
