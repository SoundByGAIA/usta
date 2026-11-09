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
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_kill_group_uses_killpg_when_available(monkeypatch):
    seen = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: seen.append((pid, sig)), raising=False)
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
