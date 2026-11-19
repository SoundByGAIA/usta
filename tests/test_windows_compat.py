"""Windows taklidi: os.getuid, os.O_NOFOLLOW, os.killpg gibi POSIX'e özgü çağrılar yokken çekirdek yollar çalışmalı."""

import os
import signal
import subprocess

import pytest

from usta import compat, memory, settings
from usta.sandbox import SandboxConfig, build_docker_args


@pytest.fixture
def windows(tmp_path, monkeypatch):  # tmp_path önce kurulsun (pytest os.getuid kullanır)
    for name in ("getuid", "getgid", "killpg", "O_NOFOLLOW", "O_NONBLOCK"):
        monkeypatch.delattr(os, name, raising=False)
    monkeypatch.delattr(signal, "SIGKILL", raising=False)


def test_compat_helpers_degrade_gracefully(windows, tmp_path):
    assert compat.nofollow() == 0 and compat.nonblock() == 0
    assert compat.user_args() == []
    assert compat.owns(tmp_path) is True


def test_settings_roundtrip_without_posix_flags(windows, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    settings.save(home, settings.Settings(theme="gri", think="off"))
    got = settings.load(home)
    assert (got.theme, got.think) == ("gri", "off")


def test_memory_note_roundtrip_without_posix_flags(windows, tmp_path):
    memory.add_note(tmp_path, "proje notu")
    assert any("proje notu" in n for n in memory.list_notes(tmp_path))


def test_docker_args_omit_user_without_uid(windows, tmp_path):
    args = build_docker_args(SandboxConfig(workdir=tmp_path), ["echo", "x"])
    assert "--user" not in args


def test_kill_group_uses_taskkill_without_killpg(windows, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    compat.kill_group(4242)
    assert calls == [[compat.taskkill(), "/PID", "4242", "/T", "/F"]]


def test_kill_group_uses_killpg_when_available(monkeypatch):
    seen = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: seen.append((pid, sig)), raising=False)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)  # Windows'ta yok
    compat.kill_group(7)
    assert seen and seen[0][0] == 7


def test_workspace_revert_works_without_fchmod(windows, tmp_path, monkeypatch):
    from usta import workspace

    monkeypatch.delattr(os, "fchmod", raising=False)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("ilk")
    snap = workspace.snapshot(root)
    (root / "a.txt").write_text("değişti")
    workspace.revert(snap, root)
    assert (root / "a.txt").read_text() == "ilk"


def test_all_text_io_declares_utf8_encoding():
    """Windows'ta varsayılan kodlama ANSI (ör. cp1254) olabilir: kodlamasız metin I/O Türkçe karakterleri bozar.

    Gerçek Windows denemesinde ajanın yazdığı index.html bu yüzden UTF-8 değildi. Bu test kaynakta kodlamasız
    `read_text/write_text`, metin kipinde `open/os.fdopen/Path.open` ve `subprocess(text=True)` bulunmasını engeller.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "usta"
    bad = []

    def kw(call, name):
        return any(k.arg == name for k in call.keywords)

    def mode_of(call, pos):
        m = call.args[pos] if len(call.args) > pos else None
        for k in call.keywords:
            if k.arg == "mode":
                m = k.value
        return m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else "r"

    for f in root.rglob("*.py"):
        if "bench_tasks" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            owner = ast.unparse(fn.value) if isinstance(fn, ast.Attribute) else ""
            where = f"{f.relative_to(root)}:{n.lineno}"
            if name in ("read_text", "write_text") and not kw(n, "encoding"):
                bad.append(f"{where} {name}")
            elif (
                name == "open"
                and owner in ("", "io", "codecs")
                or (
                    name == "open"
                    and owner != "os"
                    and not owner.endswith(("opener", "webbrowser"))
                )
            ):
                pos = 1 if owner in ("", "io", "codecs") else 0
                if (
                    "b" not in mode_of(n, pos)
                    and not kw(n, "encoding")
                    and owner not in ("opener",)
                ):
                    bad.append(f"{where} open")
            elif name == "fdopen" and "b" not in mode_of(n, 1) and not kw(n, "encoding"):
                bad.append(f"{where} fdopen")
            elif (
                name in ("run", "Popen", "check_output") and kw(n, "text") and not kw(n, "encoding")
            ):
                bad.append(f"{where} subprocess text=True")
    assert not bad, "kodlamasız metin I/O: " + ", ".join(bad)


def test_mount_path_check_allows_only_drive_colon_on_windows():
    from usta.sandbox import unsafe_mount_path as bad

    assert not bad("C:\\Users\\Ayşe\\proje", windows=True)
    assert not bad("D:/proje", windows=True)
    assert bad("C:\\a:b", windows=True) and bad("C:\\a,b", windows=True)
    assert bad("C:\\Users\\Ayşe", windows=False)  # Linux'ta ':' hâlâ reddedilir
    assert bad("/ev/a:b", windows=False) and not bad("/ev/proje", windows=False)


def test_run_without_docker_gives_plain_explanation(monkeypatch, tmp_path):
    from usta.sandbox import SandboxError, run_command

    monkeypatch.setenv("PATH", "")  # docker hiçbir mutlak klasörde yok
    with pytest.raises(SandboxError, match="Docker bu bilgisayarda kurulu değil"):
        run_command(SandboxConfig(workdir=tmp_path), ["sh", "-c", "echo x"])


class _Kernel32:
    """GetConsoleMode/SetConsoleMode taklidi; `console=False` yönlendirilmiş (konsol olmayan) çıktıyı, `can_set=False` VT açılamamasını taklit eder."""

    def __init__(self, console=True, can_set=True, mode=3):
        self.console, self.can_set, self.mode, self.sets = console, can_set, mode, []

    def GetStdHandle(self, std):
        return std

    def GetConsoleMode(self, handle, ref):
        if not self.console:
            return 0
        ref._obj.value = self.mode
        return 1

    def SetConsoleMode(self, handle, mode):
        self.sets.append(mode)
        return 1 if self.can_set else 0


def test_enable_ansi_is_noop_off_windows_and_sets_vt_flag_on_windows():
    assert compat.enable_ansi(windows=False) is True
    k = _Kernel32()
    assert compat.enable_ansi(k, windows=True) is True
    assert k.sets and all(m & 0x0004 for m in k.sets)
    assert (
        compat.enable_ansi(_Kernel32(console=False), windows=True) is True
    )  # konsol değil: renk zaten kapalı
    assert (
        compat.enable_ansi(_Kernel32(can_set=False), windows=True) is False
    )  # çöp karakter yerine düz yazı
    assert compat.enable_ansi(_Kernel32(mode=0x0007), windows=True) is True  # zaten açık


def test_repl_color_respects_no_color(monkeypatch, tmp_path):
    import io

    from usta.repl import Repl
    from usta.settings import Settings
    from usta.tasks import TaskManager

    class Tty(io.StringIO):
        def isatty(self):
            return True

    def make():
        mgr = TaskManager(lambda: None, home=tmp_path / "home")
        return Repl(mgr, tmp_path, "w", tmp_path / "home", Settings(), out=Tty())

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert make().color is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert make().color is False  # renk kodları çözülemeyen konsol için cli bu değişkeni kurar


def test_prompt_has_no_readline_markers_without_readline(monkeypatch, tmp_path):
    import io

    from usta.repl import Repl
    from usta.settings import Settings
    from usta.tasks import TaskManager

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    mgr = TaskManager(lambda: None, home=tmp_path / "home")
    repl = Repl(mgr, tmp_path, "w", tmp_path / "home", Settings(), out=Tty())
    monkeypatch.setattr(compat, "has_readline", lambda: True)
    assert "\001" in repl._prompt_str()
    monkeypatch.setattr(compat, "has_readline", lambda: False)
    p = repl._prompt_str()
    assert "\001" not in p and "\002" not in p and "usta [" in p  # Windows: ☺☻ çöpü yok


def test_make_dir_link_falls_back_to_junction_when_symlink_needs_privilege(monkeypatch, tmp_path):
    """Gerçek Windows denemesi: normal kullanıcıda os.symlink WinError 1314 verip Usta'yı çökertiyordu."""
    import sys
    import types

    real_symlink = os.symlink
    made = []

    def no_privilege(*a, **k):
        raise OSError(1314, "Gereken ayrıcalık istemci tarafından sağlanmıyor")

    def fake_junction(src, dst):  # Windows'ta _winapi.CreateJunction; testte gerçek bağla taklit
        made.append((src, dst))
        real_symlink(src, dst, target_is_directory=True)

    monkeypatch.setattr(os, "symlink", no_privilege)
    monkeypatch.setitem(sys.modules, "_winapi", types.SimpleNamespace(CreateJunction=fake_junction))
    target = tmp_path / "proje"
    target.mkdir()
    compat.make_dir_link(target, tmp_path / "bag", windows=True)
    assert made == [(str(target), str(tmp_path / "bag"))]
    assert (tmp_path / "bag").resolve() == target.resolve()


def test_make_dir_link_reraises_off_windows_and_when_link_exists(monkeypatch, tmp_path):
    target = tmp_path / "proje"
    target.mkdir()

    monkeypatch.setattr(
        os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError(1, "izin yok"))
    )
    with pytest.raises(OSError):
        compat.make_dir_link(target, tmp_path / "bag", windows=False)  # Linux: hata saklanmaz
    monkeypatch.undo()
    compat.make_dir_link(target, tmp_path / "bag2", windows=False)
    with pytest.raises(FileExistsError):
        compat.make_dir_link(
            target, tmp_path / "bag2", windows=True
        )  # var olan bağ: birleşime düşme


def test_register_creates_workspace_link_without_symlink_privilege(monkeypatch, tmp_path):
    import sys
    import types

    from usta import projects

    real_symlink = os.symlink
    monkeypatch.setattr(
        os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError(1314, "yetki yok"))
    )
    monkeypatch.setitem(
        sys.modules,
        "_winapi",
        types.SimpleNamespace(
            CreateJunction=lambda s, d: real_symlink(s, d, target_is_directory=True)
        ),
    )
    monkeypatch.setattr(sys, "platform", "win32")
    home, proj = tmp_path / "home", tmp_path / "proje"
    proj.mkdir()
    wid = projects.register(home, proj)
    assert (home / "workspaces" / wid).resolve() == proj.resolve()
    assert projects.register(home, proj) == wid  # ikinci kayıt aynı kimliği döndürür


def test_docker_and_taskkill_never_resolve_from_the_current_folder(tmp_path, monkeypatch):
    # 0.8.3 kutu kaçışının ikinci katmanı: kutudan çalışma alanına bırakılan sahte `docker` seçilmez
    from usta import compat
    from usta.sandbox import SandboxError, run_command

    fake = tmp_path / ("docker.exe" if os.name == "nt" else "docker")
    fake.write_text("#!/bin/sh\necho SAHTE\n")
    fake.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f".{os.pathsep}{os.pathsep}rel")
    assert compat.safe_which("docker") is None and compat.program("docker") == "docker"
    with pytest.raises(SandboxError, match="kurulu değil"):
        run_command(SandboxConfig(workdir=tmp_path), ["sh", "-c", "echo x"])
    monkeypatch.setenv("PATH", str(tmp_path))
    assert compat.program("docker") == str(fake)  # mutlak klasördeki gerçek yol
    monkeypatch.setenv("SystemRoot", "rel")
    assert compat.taskkill() == "taskkill"
    sysdir = tmp_path / "Windows" / "System32"
    sysdir.mkdir(parents=True)
    (sysdir / "taskkill.exe").write_text("")
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    assert compat.taskkill() == str(sysdir / "taskkill.exe")
