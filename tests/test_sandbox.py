import shutil
import subprocess

import pytest

from usta.sandbox import SandboxConfig, build_docker_args, run_command


def test_args_are_locked_down_by_default(tmp_path):
    args = build_docker_args(SandboxConfig(workdir=tmp_path), ["echo", "hi"])
    assert args[:2] == ["docker", "run"]
    assert "--rm" in args
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges" in args
    assert "--pids-limit" in args and "--memory" in args and "--cpus" in args
    assert args[args.index("--user") + 1] != "0:0"
    assert args[-2:] == ["echo", "hi"]


def test_only_workdir_is_mounted_and_no_env_leaks(tmp_path):
    args = build_docker_args(SandboxConfig(workdir=tmp_path), ["true"])
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert mounts == [f"{tmp_path.resolve()}:/workspace:rw"]
    assert "-e" not in args and "--env" not in args
    assert "docker.sock" not in " ".join(args)


def test_read_only_mounts_are_added_ro_and_validated(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    cfg = SandboxConfig(workdir=tmp_path, ro_mounts=((lib, "/opt/lib"),))
    args = build_docker_args(cfg, ["true"])
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert f"{lib.resolve()}:/opt/lib:ro" in mounts
    assert len(mounts) == 2
    with pytest.raises(ValueError):
        build_docker_args(
            SandboxConfig(workdir=tmp_path, ro_mounts=((tmp_path / "yok", "/x"),)), ["true"]
        )
    with pytest.raises(ValueError):  # mutlak olmayan / ':' içeren hedef
        build_docker_args(SandboxConfig(workdir=tmp_path, ro_mounts=((lib, "x:rw"),)), ["true"])


def test_workdir_must_exist(tmp_path):
    with pytest.raises(ValueError):
        build_docker_args(SandboxConfig(workdir=tmp_path / "yok"), ["true"])


def test_empty_command_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_docker_args(SandboxConfig(workdir=tmp_path), [])


needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


@needs_docker
@pytest.mark.docker
def test_runs_command_and_captures_output(tmp_path):
    r = run_command(SandboxConfig(workdir=tmp_path), ["sh", "-c", "echo merhaba; echo hata >&2"])
    assert r.exit_code == 0
    assert r.stdout.strip() == "merhaba"
    assert r.stderr.strip() == "hata"
    assert not r.timed_out


@needs_docker
@pytest.mark.docker
def test_network_is_off(tmp_path):
    code = "import socket;socket.create_connection(('1.1.1.1',53),timeout=3)"
    r = run_command(SandboxConfig(workdir=tmp_path), ["python", "-c", code])
    assert r.exit_code != 0


@needs_docker
@pytest.mark.docker
def test_writes_only_in_workspace(tmp_path):
    r = run_command(SandboxConfig(workdir=tmp_path), ["sh", "-c", "echo x > /workspace/a.txt"])
    assert r.exit_code == 0
    assert (tmp_path / "a.txt").read_text().strip() == "x"
    r = run_command(SandboxConfig(workdir=tmp_path), ["sh", "-c", "echo x > /etc/a"])
    assert r.exit_code != 0


@needs_docker
@pytest.mark.docker
def test_timeout_kills_container(tmp_path):
    r = run_command(SandboxConfig(workdir=tmp_path, timeout=2), ["sleep", "30"])
    assert r.timed_out
    assert r.exit_code != 0


@needs_docker
@pytest.mark.docker
def test_cancel_kills_running_container(tmp_path):
    import threading
    import time

    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    t0 = time.monotonic()
    r = run_command(SandboxConfig(workdir=tmp_path, timeout=30), ["sleep", "30"], cancel=cancel)
    assert r.cancelled and not r.timed_out and r.exit_code != 0
    assert time.monotonic() - t0 < 10
    out = subprocess.run(
        ["docker", "ps", "-q", "--filter", "name=usta-"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert out.strip() == ""


def test_precancelled_does_not_start(tmp_path):
    import threading

    cancel = threading.Event()
    cancel.set()
    r = run_command(SandboxConfig(workdir=tmp_path), ["sleep", "30"], cancel=cancel)
    assert r.cancelled and r.exit_code != 0


@needs_docker
@pytest.mark.docker
def test_cancel_during_container_startup_still_returns(tmp_path):
    import threading
    import time

    cancel = threading.Event()
    threading.Timer(0.05, cancel.set).start()  # konteyner yaratılmadan önce
    t0 = time.monotonic()
    r = run_command(SandboxConfig(workdir=tmp_path, timeout=30), ["sleep", "30"], cancel=cancel)
    assert r.cancelled and time.monotonic() - t0 < 15


def test_git_and_usta_are_mounted_read_only(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".usta").mkdir()
    args = " ".join(build_docker_args(SandboxConfig(workdir=tmp_path), ["true"]))
    assert f"{tmp_path.resolve() / '.git'}:/workspace/.git:ro" in args
    assert f"{tmp_path.resolve() / '.usta'}:/workspace/.usta:ro" in args
    plain = tmp_path / "temiz"
    plain.mkdir()
    assert ":ro" not in " ".join(build_docker_args(SandboxConfig(workdir=plain), ["true"]))


@needs_docker
def test_git_dir_cannot_be_modified_from_inside_a_real_sandbox(tmp_path):
    (tmp_path / ".git").mkdir()
    r = run_command(
        SandboxConfig(workdir=tmp_path),
        ["sh", "-c", "touch .git/evil 2>/dev/null; echo $?; touch normal; echo $?"],
    )
    assert r.stdout.split() == ["1", "0"], r
    assert not (tmp_path / ".git" / "evil").exists() and (tmp_path / "normal").exists()


@pytest.mark.parametrize("name", ["a:b", "x,y", "p:rw,z"])
def test_workdir_with_mount_syntax_chars_is_refused(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    with pytest.raises(ValueError):
        build_docker_args(SandboxConfig(workdir=d), ["true"])


@needs_docker
def test_nested_preexisting_git_is_read_only_in_a_real_sandbox(tmp_path):
    (tmp_path / "vendor" / "lib" / ".git").mkdir(parents=True)
    r = run_command(
        SandboxConfig(workdir=tmp_path),
        ["sh", "-c", "touch vendor/lib/.git/evil 2>/dev/null; echo $?; touch vendor/ok; echo $?"],
    )
    assert r.stdout.split() == ["1", "0"], r
