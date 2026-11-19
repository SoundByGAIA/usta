from usta.audit import AuditLog, verify
from usta.cli import main


def setup(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("USTA_HOME", str(home))
    log = AuditLog(home / "audit" / "ws1.jsonl")
    log.record("task", prompt="x")
    log.record("file_change", path="a.txt", before=None, after="ab" * 32, trigger="görev")
    return log


def test_verify_all_ok_prints_last_hash(tmp_path, monkeypatch, capsys):
    log = setup(tmp_path, monkeypatch)
    assert main(["audit", "verify"]) == 0
    out = capsys.readouterr().out
    assert "ws1" in out and "2 kayıt" in out and verify(log.path).last_hash in out


def test_verify_tampered_exits_nonzero(tmp_path, monkeypatch, capsys):
    log = setup(tmp_path, monkeypatch)
    log.record("e")
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert main(["audit", "verify", "ws1"]) == 1
    assert "satır 2" in capsys.readouterr().out


def test_show_prints_recent_records(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    assert main(["audit", "show", "ws1", "-n", "1"]) == 0
    out = capsys.readouterr().out
    assert "file_change" in out and "a.txt" in out and "task" not in out


def test_show_without_name_uses_the_latest_log(tmp_path, monkeypatch, capsys):
    import os

    log = setup(tmp_path, monkeypatch)
    newer = AuditLog(log.path.parent / "ws2.jsonl")
    newer.record("task", prompt="yeni")
    os.utime(log.path, (1, 1))
    assert main(["audit", "show"]) == 0
    out = capsys.readouterr().out
    assert "yeni" in out and "a.txt" not in out


def test_show_without_any_log_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("USTA_HOME", str(tmp_path / "bos"))
    assert main(["audit", "show"]) == 2
    assert "hata" in capsys.readouterr().err


def test_unknown_log_is_an_error(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch)
    assert main(["audit", "show", "yok"]) == 2
    assert "hata" in capsys.readouterr().err


def test_verify_with_anchor(tmp_path, monkeypatch, capsys):
    log = setup(tmp_path, monkeypatch)
    anchor = verify(log.path).last_hash
    assert main(["audit", "verify", "ws1", "--anchor", anchor]) == 0
    assert main(["audit", "verify", "ws1", "--anchor", "0" * 64]) == 1
    assert "saklanan hash" in capsys.readouterr().out
