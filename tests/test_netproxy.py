import shutil
import subprocess
import uuid

import pytest

from usta.sandbox import (
    ProxyNetwork,
    SandboxConfig,
    SandboxError,
    build_docker_args,
    cleanup_orphans,
    run_command,
)

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


def docker_names(kind: str) -> list[str]:
    cmd, fmt = {"c": (["ps", "-a"], "{{.Names}}"), "n": (["network", "ls"], "{{.Name}}")}[kind]
    out = subprocess.run(
        ["docker", *cmd, "--filter", "name=usta-", "--format", fmt],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [n for n in out.split() if n.startswith(("usta-proxy-", "usta-net-"))]


def test_args_with_network_use_it_and_set_proxy_env(tmp_path):
    cfg = SandboxConfig(workdir=tmp_path)
    args = build_docker_args(
        cfg, ["true"], network="usta-net-x", env={"HTTP_PROXY": "http://p:3128"}
    )
    assert args[args.index("--network") + 1] == "usta-net-x" and "none" not in args
    assert args[args.index("-e") + 1] == "HTTP_PROXY=http://p:3128"


def test_default_args_unchanged_without_network(tmp_path):
    args = build_docker_args(SandboxConfig(workdir=tmp_path), ["true"])
    assert args[args.index("--network") + 1] == "none" and "-e" not in args


def test_config_defaults_to_no_hosts(tmp_path):
    assert SandboxConfig(workdir=tmp_path).allowed_hosts == ()


@needs_docker
@pytest.mark.docker
def test_direct_egress_is_impossible_even_with_allowlist(tmp_path):
    cfg = SandboxConfig(workdir=tmp_path, allowed_hosts=("example.com",), timeout=60)
    code = "import socket;socket.create_connection(('1.1.1.1',53),timeout=3)"
    r = run_command(cfg, ["python", "-c", code])
    assert r.exit_code != 0


@needs_docker
@pytest.mark.docker
def test_denied_host_gets_403_and_is_logged(tmp_path):
    cfg = SandboxConfig(workdir=tmp_path, allowed_hosts=("example.com",), timeout=60)
    code = (
        "import urllib.request,urllib.error\n"
        "try:\n urllib.request.urlopen('http://evil.example/gizli/yol?x=1', timeout=10)\n"
        "except urllib.error.HTTPError as e:\n print('HTTP', e.code)\n"
    )
    r = run_command(cfg, ["python", "-c", code])
    assert "HTTP 403" in r.stdout
    assert any(d["host"] == "evil.example" and d["allowed"] is False for d in r.network_log)
    assert "gizli" not in str(r.network_log)


@needs_docker
@pytest.mark.docker
def test_allowed_host_goes_through_proxy(tmp_path):
    cfg = SandboxConfig(
        workdir=tmp_path,
        allowed_hosts=("upstream-test",),
        allowed_ports=(8080,),
        proxy_allow_private=True,  # yalnız test: yukarı akış özel bir konteyner adresinde
        timeout=60,
    )
    up = f"usta-up-{uuid.uuid4().hex[:8]}"
    with ProxyNetwork(cfg) as net:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                up,
                "--network",
                net.network,
                "--network-alias",
                "upstream-test",
                "--label",
                "usta.managed=1",
                "python:3.12-slim",
                "python",
                "-m",
                "http.server",
                "8080",
            ],
            check=True,
            capture_output=True,
        )
        try:
            code = (
                "import urllib.request,time\n"
                "for _ in range(20):\n"
                " try:\n  print('HTTP', urllib.request.urlopen('http://upstream-test:8080/', timeout=5).status);break\n"
                " except Exception as e:\n  time.sleep(0.5)\n"
            )
            r = run_command(cfg, ["python", "-c", code], session=net)
        finally:
            subprocess.run(["docker", "rm", "-f", up], check=False, capture_output=True)
        assert "HTTP 200" in r.stdout, r.stderr
        assert any(d["host"] == "upstream-test" and d["allowed"] is True for d in net.decisions())


@needs_docker
@pytest.mark.docker
def test_resources_are_cleaned_up_after_run_and_after_errors(tmp_path):
    cfg = SandboxConfig(workdir=tmp_path, allowed_hosts=("example.com",), timeout=60)
    run_command(cfg, ["true"])
    assert docker_names("c") == [] and docker_names("n") == []
    with pytest.raises(SandboxError):
        run_command(
            SandboxConfig(workdir=tmp_path, allowed_hosts=("a",), proxy_image="usta-yok:0"),
            ["true"],
        )
    assert docker_names("c") == [] and docker_names("n") == []


@needs_docker
@pytest.mark.docker
def test_cleanup_orphans_removes_only_dead_owners(tmp_path):
    def mk(pid):
        name = f"usta-net-{uuid.uuid4().hex[:8]}"
        subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--internal",
                "--label",
                "usta.managed=1",
                "--label",
                f"usta.pid={pid}",
                name,
            ],
            check=True,
            capture_output=True,
        )
        return name

    dead, alive = mk(2**22 + 12345), mk(__import__("os").getpid())
    try:
        assert cleanup_orphans() >= 1
        names = docker_names("n")
        assert dead not in names and alive in names
    finally:
        subprocess.run(["docker", "network", "rm", alive, dead], check=False, capture_output=True)
