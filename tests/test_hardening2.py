"""İkinci bağımsız incelemenin bulguları için regresyon testleri."""

import os
import signal

import pytest

from test_api import AUTH, make_client
from test_tasks import Scripted, manager
from usta.audit import mask
from usta.models import ModelResponse
from usta.workspace import find_protected, remove_new_protected, revert, snapshot


def _fork_guard(seconds=5):
    """Bloklanan çağrı testi sonsuza dek kilitlemesin."""
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("bloklandı")))
    signal.alarm(seconds)


# --- YÜKSEK-1: ajanın oluşturduğu .git silinir
def test_new_protected_entries_removed_at_any_depth_and_existing_ones_kept(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / ".git" / "config").write_text("[core]\n")
    before = find_protected(ws)
    (ws / "alt" / ".git" / "hooks").mkdir(parents=True)
    (ws / "derin" / ".GIT").mkdir(parents=True)
    (ws / "alt" / ".usta").write_text(
        "n"
    )  # iç içe .usta (kök .usta ana makine tarafından yazılır, serbest)
    removed = remove_new_protected(ws, before)
    assert set(removed) >= {"alt/.git", "derin/.GIT", "alt/.usta"}
    assert (ws / ".git" / "config").exists()  # önceden var olan dokunulmadı
    assert find_protected(ws) == {".git"}


def test_task_emits_warning_when_new_protected_entries_were_created(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    class Make:
        def chat(self, messages, tools=None):
            if not any(m.role == "tool" for m in messages):
                # dosya aracı değil: görev bittikten sonra silinecek girdiyi doğrudan oluşturur
                (ws / "x").mkdir()
                (ws / "x" / ".git").mkdir()
                return ModelResponse("bitti")
            return ModelResponse("bitti")

    m = manager(tmp_path, Make())
    t = m.start("w", ws, "y", "auto")
    assert t.finished.wait(10)
    assert not (ws / "x" / ".git").exists()
    assert any(e["type"] == "warning" and ".git" in e["data"]["message"] for e in t.events)


def test_policy_blocks_dotgit_case_variants_and_raw_path(tmp_path):
    from usta.policy import Decision, Policy

    (tmp_path / "gitdata").mkdir()
    (tmp_path / ".git").symlink_to(tmp_path / "gitdata")  # projenin kendi .git bağı
    p = Policy(tmp_path)
    for path in (".GIT/config", ".Git/hooks/x", ".git/config", "a/.USTA/x"):
        assert p.check("write_file", {"path": path}) == Decision.DENY, path


# --- ORTA-2: yaprak FIFO ve sabit bağ
def test_revert_over_a_fifo_leaf_does_not_block(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("orijinal")
    snap = snapshot(root)
    (root / "app.py").unlink()
    os.mkfifo(root / "app.py")
    _fork_guard()
    try:
        revert(snap, root)  # önceden: O_WRONLY açılışı okuyucu bekleyerek sonsuza dek bloklanıyordu
    finally:
        signal.alarm(0)
    assert (root / "app.py").is_file() and (root / "app.py").read_text() == "orijinal"


def test_revert_does_not_clobber_hard_linked_sibling(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a").write_text("A")
    (root / "b").write_text("B")
    snap = snapshot(root)
    (root / "b").unlink()
    os.link(root / "a", root / "b")  # b artık a ile aynı inode
    revert(snap, root)
    assert (root / "a").read_text() == "A" and (root / "b").read_text() == "B"


# --- ORTA-3: çalışma alanı denetimi görev başlatmada
def test_start_refuses_workspace_that_contains_usta_home_or_is_home(tmp_path, monkeypatch):
    home = tmp_path / "kullanici" / ".usta"
    home.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path / "kullanici"))
    from usta.tasks import TaskManager

    m = TaskManager(lambda: Scripted(), home=home)
    for bad in (tmp_path / "kullanici", tmp_path):
        with pytest.raises(ValueError):
            m.start("w", bad, "x", "auto")


def test_api_cannot_start_task_in_legacy_workspace_symlinked_to_home(tmp_path, monkeypatch):
    c, _ = make_client(tmp_path, Scripted())
    fake_home = tmp_path / "kullanici"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    (tmp_path / "home" / "workspaces").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "workspaces" / "eski").symlink_to(
        fake_home
    )  # eski sürümde ~ içinde başlatılmış kayıt
    r = c.post("/workspaces/eski/tasks", json={"prompt": "x"}, headers=AUTH)
    assert r.status_code == 400


# --- DÜŞÜK-5: FIFO diğer yollarda
def test_outline_and_write_file_refuse_fifo(tmp_path):
    from usta.tools import ToolContext, ToolError, build_registry

    os.mkfifo(tmp_path / "boru")
    reg = build_registry(ToolContext(root=tmp_path))
    _fork_guard()
    try:
        for tool, args in (
            ("outline", {"path": "boru"}),
            ("write_file", {"path": "boru", "content": "x"}),
        ):
            with pytest.raises(ToolError):
                reg.call(tool, args)
    finally:
        signal.alarm(0)


def test_memory_read_and_write_do_not_block_on_fifo(tmp_path):
    from usta import memory

    d = tmp_path / ".usta" / "memory"
    d.mkdir(parents=True)
    os.mkfifo(d / "NOTES.md")
    os.mkfifo(d / "NOTES.md.tmp")
    _fork_guard()
    try:
        memory.add_note(tmp_path, "not")  # FIFO'lar engel olmadan geçilir
        assert "not" in memory.list_notes(tmp_path)
    finally:
        signal.alarm(0)


# --- DÜŞÜK-6: maske yanlış pozitifleri
@pytest.mark.parametrize(
    "benign",
    [
        "task-queue-worker-implementation",
        "mask-secret-values-in-logs",
        "disk-usage-report-generator-v2",
    ],
)
def test_mask_does_not_mangle_kebab_case_words(benign):
    assert mask(f"dosya: {benign} tamam") == f"dosya: {benign} tamam"


def test_pem_header_without_end_only_masks_the_header_line_not_the_rest():
    head = "-----BEGIN RSA " + "PRIVATE KEY-----"
    out = mask(f"PEM ayrıştıran kod: {head} burada biter ve devam eden belge metni uzun uzun sürer")
    assert "devam eden belge metni" in out and head not in out


# --- DÜŞÜK-7: geri alma kısıtları
def test_plan_and_no_change_tasks_do_not_block_revert_and_snapshots_are_per_workspace(tmp_path):
    from usta.tasks import KEEP_SNAPSHOTS

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "f.txt").write_text("0")
    m = manager(tmp_path, Scripted(*[ModelResponse("tamam") for _ in range(KEEP_SNAPSHOTS + 6)]))
    ta = m.start("A", a, "x", "auto")
    assert ta.finished.wait(10)
    (a / "f.txt").write_text(
        "değişti"
    )  # a'daki görevin sonrası değil; ta.diff boş → ta geri alınacak bir şey yok
    tp = m.start("A", a, "planla", "plan")
    assert tp.finished.wait(10)
    for _ in range(KEEP_SNAPSHOTS + 2):  # başka çalışma alanında çok görev
        t = m.start("B", b, "y", "auto")
        assert t.finished.wait(10)
    assert ta.snapshot is not None  # A'nın anlık görüntüsü B'deki görevlerle düşmedi


def test_auth_exchange_body_limit_really_applies_with_login_enabled(tmp_path):
    from fastapi.testclient import TestClient

    from usta.api import create_app
    from usta.auth import LoginCodes
    from usta.tasks import TaskManager

    home = tmp_path / "home"
    app = create_app(TaskManager(lambda: Scripted(), home=home), home, "tok", login=LoginCodes())
    r = TestClient(app).post(
        "/auth/exchange", content=b"x" * 10_000, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


def test_import_limit_applies_only_to_the_real_import_route():
    from usta.api import MAX_BODY, MAX_BODY_IMPORT, _body_limit

    assert _body_limit("/workspaces/p/import") == MAX_BODY_IMPORT
    assert _body_limit("/workspaces/p/tasks/import") == MAX_BODY
    assert _body_limit("/x/import") == MAX_BODY


# ===== 3. tur (üçüncü inceleme) =====
def test_audit_log_masks_pem_bodies_written_via_json_and_encrypted_headers(tmp_path):
    from usta.audit import AuditLog

    head = "-----BEGIN RSA " + "PRIVATE KEY-----"
    body = "MIIEowIBAAKCAQEAverysecretbase64body+/=="
    plain = f"{head}\n{body}\n-----END RSA PRIVATE KEY-----"
    encrypted = f"{head}\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,ABCDEF0123\n\n{body}\n-----END RSA PRIVATE KEY-----"
    no_end = f"{head}\n{body}\n{body}"  # END'siz (kırpılmış çıktı)
    log = AuditLog(tmp_path / "a.jsonl")
    log.record("tool_call", args={"content": plain}, x=[encrypted], y=no_end)
    raw = (tmp_path / "a.jsonl").read_text()
    assert "verysecretbase64body" not in raw and "AES-128-CBC" not in raw and "[GİZLİ]" in raw


def test_mask_still_keeps_prose_after_an_endless_pem_header():
    head = "-----BEGIN RSA " + "PRIVATE KEY-----"
    assert "devam eden belge" in mask(f"kod: {head} burada biter ve devam eden belge metni")


def test_find_protected_sees_nested_shallow_ignored_and_bare_repos(tmp_path):
    (tmp_path / "sub" / ".git").mkdir(parents=True)
    (tmp_path / ".venv" / ".git").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / ".git").mkdir(parents=True)
    (tmp_path / "node_modules" / "a" / "b" / "c" / "d" / ".git").mkdir(
        parents=True
    )  # çok derin: taranmaz
    bare = tmp_path / "bare"
    (bare / "objects").mkdir(parents=True)
    (bare / "refs").mkdir()
    (bare / "HEAD").write_text("ref: refs/heads/main\n")
    found = find_protected(tmp_path)
    assert {"sub/.git", ".venv/.git", "node_modules/x/.git", "bare"} <= found
    assert "node_modules/a/b/c/d/.git" not in found


def test_sandbox_mounts_every_preexisting_nested_git_read_only(tmp_path):
    from usta.sandbox import SandboxConfig, build_docker_args

    (tmp_path / "vendor" / "lib" / ".git").mkdir(parents=True)
    (tmp_path / "ordinary").mkdir()
    args = " ".join(build_docker_args(SandboxConfig(workdir=tmp_path), ["true"]))
    assert (
        f"{(tmp_path / 'vendor' / 'lib' / '.git').resolve()}:/workspace/vendor/lib/.git:ro" in args
    )
    assert "ordinary" not in args


def test_new_protected_entries_are_quarantined_not_destroyed(tmp_path):
    ws, q = tmp_path / "ws", tmp_path / "q"
    ws.mkdir()
    before = find_protected(ws)
    (ws / "vendor" / "lib2" / ".git").mkdir(parents=True)
    (ws / "vendor" / "lib2" / ".git" / "HEAD").write_text("ref: x")
    gone = remove_new_protected(ws, before, q)
    assert gone == ["vendor/lib2/.git"] and not (ws / "vendor" / "lib2" / ".git").exists()
    assert (q / "vendor__lib2__.git" / "HEAD").read_text() == "ref: x"  # geçmiş kaybolmadı


def test_quarantine_skips_paths_whose_parent_became_a_symlink_outside(tmp_path):
    ws, outside = tmp_path / "ws", tmp_path / "onemli"
    ws.mkdir()
    (outside / "x" / ".git").mkdir(parents=True)
    before = find_protected(ws)
    (ws / "link").symlink_to(outside)  # ara bileşen dışarıya işaret ediyor
    # find_protected sembolik bağın içine inmez; yine de savunma: elle verilmiş "yeni" yol dışarıyı etkilemez
    import usta.workspace as w

    orig = w.find_protected
    w.find_protected = lambda root: {"link/x/.git"}
    try:
        assert remove_new_protected(ws, before, tmp_path / "q") == []
    finally:
        w.find_protected = orig
    assert (outside / "x" / ".git").exists()


def test_revert_preserves_file_modes_and_survives_very_long_names(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    secret = root / ".env"
    secret.write_text("S=1")
    secret.chmod(0o600)
    script = root / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    long = root / ("u" * 240)
    long.write_text("uzun")
    snap = snapshot(root)
    for p in (secret, script, long):
        p.write_text("bozuk")
        p.chmod(0o644)
        p.unlink()
        p.write_text("bozuk")
    revert(snap, root)
    assert oct(secret.stat().st_mode & 0o777) == "0o600" and secret.read_text() == "S=1"
    assert oct(script.stat().st_mode & 0o777) == "0o755"
    assert long.read_text() == "uzun"


def test_failed_diff_counts_as_change_for_revert_rule(tmp_path, monkeypatch):
    import usta.tasks as tasks_mod
    from usta.tasks import RevertRefused

    ws = tmp_path / "ws"
    ws.mkdir()
    m = manager(tmp_path, Scripted(ModelResponse("a"), ModelResponse("b")))
    t1 = m.start("w", ws, "x", "auto")
    assert t1.finished.wait(10)
    monkeypatch.setattr(tasks_mod, "diff", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    t2 = m.start("w", ws, "y", "auto")
    assert t2.finished.wait(10) and t2.diff_failed
    with pytest.raises(RevertRefused):
        m.revert(t1.id)  # t2'nin ne değiştirdiği bilinmiyor: t1'i geri almak t2'yi ezebilir


def test_protected_cleanup_errors_never_leave_workspace_busy(tmp_path, monkeypatch):
    import usta.tasks as tasks_mod

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(
        tasks_mod, "remove_new_protected", lambda *a, **k: (_ for _ in ()).throw(OSError("dolu"))
    )
    m = manager(tmp_path, Scripted(ModelResponse("a")))
    t = m.start("w", ws, "x", "auto")
    assert t.finished.wait(10) and not m.is_busy("w")
