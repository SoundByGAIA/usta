import stat

import pytest

from usta import projectcfg as pc
from usta.models import ModelResponse, ToolCall
from usta.sandbox import RunResult
from usta.tasks import TaskManager
from usta.verify import CompletionGate


def test_defaults_when_nothing_configured(tmp_path):
    cfg = pc.load(tmp_path / "home", tmp_path / "proje")
    assert cfg.verify is None and cfg.image is None


def test_set_show_clear_roundtrip_with_private_file(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "proje"
    proj.mkdir()
    pc.set_verify(home, proj, ["sh", "-c", "make test"], image="python:3.12-slim")
    cfg = pc.load(home, proj)
    assert cfg.verify == ("sh", "-c", "make test") and cfg.image == "python:3.12-slim"
    assert stat.S_IMODE((home / "projects.json").stat().st_mode) == 0o600
    pc.clear(home, proj)
    assert pc.load(home, proj).verify is None


def test_keyed_by_resolved_path_so_symlinks_share_config(tmp_path):
    home, proj = tmp_path / "home", tmp_path / "proje"
    proj.mkdir()
    link = tmp_path / "kisayol"
    link.symlink_to(proj)
    pc.set_verify(home, proj, ["pytest", "-q"])
    assert pc.load(home, link).verify == ("pytest", "-q")


def test_projects_do_not_leak_into_each_other(tmp_path):
    home = tmp_path / "home"
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pc.set_verify(home, a, ["make", "a"])
    assert pc.load(home, b).verify is None


@pytest.mark.parametrize("cmd", [[], [""], ["a", 5], ["x\x00y"], "make test", ["a" * 5000]])
def test_bad_commands_rejected(tmp_path, cmd):
    with pytest.raises(pc.ProjectConfigError):
        pc.set_verify(tmp_path / "home", tmp_path, cmd)


@pytest.mark.parametrize("image", ["", "a b", "-x", "x;rm -rf /", "a" * 300, "$(id)"])
def test_bad_images_rejected(tmp_path, image):
    with pytest.raises(pc.ProjectConfigError):
        pc.set_verify(tmp_path / "home", tmp_path, ["make"], image=image)


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for text in ("{bozuk", "[]", '{"/x": 5}', '{"/x": {"verify": "sh -c evil"}}'):
        (home / "projects.json").write_text(text)
        assert pc.load(home, tmp_path / "x").verify is None


def test_gate_uses_configured_command_and_image(tmp_path):
    seen = []

    def run(cfg, command, cancel=None, session=None):
        seen.append((cfg.image, command))
        return RunResult(0, "OK", "")

    g = CompletionGate(tmp_path, run=run, command=["make", "test"], image="ozel:1")
    r = g.check()
    assert r.status == "passed" and seen == [("ozel:1", ["make", "test"])]
    assert "make test" in r.command


def test_gate_with_configured_command_works_without_any_test_files(tmp_path):
    run = lambda cfg, command, cancel=None, session=None: RunResult(1, "E: boom", "")
    r = CompletionGate(tmp_path, run=run, command=["make", "test"]).check()
    assert r.status == "failed" and "boom" in r.output


def test_task_manager_applies_project_verify_config(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    home = tmp_path / "home"
    pc.set_verify(home, ws, ["sh", "-c", "projeye ozel"], image="ozel:2")
    seen = []

    def gate_run(cfg, command, cancel=None, session=None):
        seen.append((cfg.image, command))
        return RunResult(0, "OK", "")

    class M:
        def __init__(self):
            self.r = [
                ModelResponse(
                    None, [ToolCall("c", "write_file", {"path": "a.py", "content": "x = 1\n"})]
                ),
                ModelResponse("bitti"),
            ]

        def chat(self, messages, tools=None):
            return self.r.pop(0)

    m = TaskManager(lambda: M(), home=home)
    m.gate_run = gate_run
    t = m.start("w1", ws, "yaz", guard=True)
    assert t.finished.wait(10) and seen == [("ozel:2", ["sh", "-c", "projeye ozel"])]
