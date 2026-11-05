"""Tedarik zinciri: hash'li kilit dosyaları, sandbox imaj sabitleme, CI'nın kilitle kurması."""

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from usta import sandbox
from usta.cli import main

ROOT = Path(__file__).parent.parent
needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"], check=False, capture_output=True
    ).returncode
    != 0,
    reason="Docker veya python:3.12-slim imajı yok",
)


def req_names(path: Path) -> set[str]:
    return {
        m.group(1).lower().replace("_", "-")
        for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", path.read_text(), re.MULTILINE)
    }


@pytest.mark.parametrize("name", ["requirements.lock", "requirements-dev.lock"])
def test_lock_files_pin_every_package_with_hashes(name):
    text = (ROOT / name).read_text()
    blocks = re.split(r"\n(?=[A-Za-z0-9_.\-]+==)", text)
    pkgs = [b for b in blocks if re.match(r"[A-Za-z0-9_.\-]+==", b)]
    assert len(pkgs) >= 15
    for b in pkgs:
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", b), f"hash yok: {b.splitlines()[0]}"
        assert "git+" not in b and "http://" not in b  # yalnız kayıttan, doğrulanmış paketler


def test_lock_files_cover_declared_dependencies():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = lambda reqs: {
        re.split(r"[<>=!~\[ ;]", r, 1)[0].lower().replace("_", "-") for r in reqs
    }
    runtime = declared(meta["dependencies"]) | declared(meta["optional-dependencies"]["symbols"])
    assert runtime <= req_names(ROOT / "requirements.lock")
    dev = runtime | declared(meta["optional-dependencies"]["dev"])
    assert dev <= req_names(ROOT / "requirements-dev.lock")
    assert "tree-sitter" in req_names(ROOT / "requirements.lock")


def test_ci_installs_from_hashed_locks_and_audits_the_lock():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert (
        "--require-hashes -r requirements-dev.lock" in ci
        and "--require-hashes -r requirements.lock" in ci
    )
    assert "pip-audit" in ci and "requirements.lock" in ci
    assert "docker pull" in ci  # sandbox imajı CI'da önceden çekilir (Usta kendiliğinden çekmez)


def test_makefile_documents_how_to_regenerate_locks():
    assert "--generate-hashes" in (ROOT / "Makefile").read_text()


# --- sandbox imaj sabitleme --------------------------------------------------------------------
@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "ustahome"
    monkeypatch.setenv("USTA_HOME", str(h))
    sandbox._PIN_OK.clear()
    return h


def test_no_pin_means_no_restriction(home):
    sandbox.verify_pin("python:3.12-slim")  # sabitleme yoksa hata vermez


def test_pin_mismatch_blocks_sandbox_and_mentions_how_to_repin(home, monkeypatch):
    home.mkdir()
    (home / sandbox.PIN_FILE).write_text(json.dumps({"python:3.12-slim": "sha256:" + "0" * 64}))
    monkeypatch.setattr(sandbox, "local_image_id", lambda image: "sha256:" + "1" * 64)
    with pytest.raises(sandbox.SandboxError, match="usta sandbox pin"):
        sandbox.verify_pin("python:3.12-slim")
    monkeypatch.setattr(sandbox, "local_image_id", lambda image: None)
    with pytest.raises(sandbox.SandboxError, match="yok"):
        sandbox.verify_pin("python:3.12-slim")


def test_run_command_refuses_a_changed_image_before_starting_anything(home, monkeypatch, tmp_path):
    home.mkdir()
    (home / sandbox.PIN_FILE).write_text(json.dumps({"python:3.12-slim": "sha256:" + "0" * 64}))
    monkeypatch.setattr(sandbox, "local_image_id", lambda image: "sha256:" + "1" * 64)
    started = []
    monkeypatch.setattr(
        sandbox.subprocess,
        "Popen",
        lambda *a, **k: started.append(a) or (_ for _ in ()).throw(AssertionError("başlamamalı")),
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(sandbox.SandboxError):
        sandbox.run_command(sandbox.SandboxConfig(workdir=ws), ["true"])
    assert not started


@needs_docker
@pytest.mark.docker
def test_pin_status_and_a_pinned_image_still_runs(home, capsys, tmp_path):
    assert main(["sandbox", "status"]) == 0 and "Sabitlenmiş imaj yok" in capsys.readouterr().out
    assert main(["sandbox", "pin"]) == 0
    assert "sha256:" in capsys.readouterr().out
    assert oct((home / sandbox.PIN_FILE).stat().st_mode & 0o777) == "0o600"
    assert main(["sandbox", "status"]) == 0 and "TUTUYOR" in capsys.readouterr().out
    r = sandbox.run_command(sandbox.SandboxConfig(workdir=tmp_path), ["echo", "tamam"])
    assert r.exit_code == 0 and r.stdout.strip() == "tamam"


def test_pin_refuses_a_missing_image(home, monkeypatch, capsys):
    monkeypatch.setattr(sandbox, "local_image_id", lambda image: None)
    assert main(["sandbox", "pin", "--image", "yok:1"]) == 1
    assert "imaj yerelde yok" in capsys.readouterr().err
