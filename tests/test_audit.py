import json

from usta.audit import AuditLog, mask

FAKE_SK = "sk-" + "abcdefghijklmnopqrstuvwxyz1234"
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_mask_secrets():
    assert "sk-" not in mask("anahtar " + FAKE_SK)
    assert "AKIA" not in mask(FAKE_AWS)
    assert mask("normal metin") == "normal metin"


def test_records_are_jsonl_append_only_and_masked(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("tool_call", tool="write_file", args={"content": FAKE_SK})
    log.record("decision", decision="deny")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    first, second = (json.loads(x) for x in lines)
    assert first["event"] == "tool_call" and "ts" in first
    assert "sk-abc" not in lines[0] and "[GİZLİ]" in lines[0]
    assert second["decision"] == "deny"


def test_creates_parent_dirs_with_private_mode(tmp_path):
    p = tmp_path / "x" / "audit.jsonl"
    AuditLog(p).record("e")
    assert p.exists() and (p.stat().st_mode & 0o077) == 0


def test_mask_covers_modern_key_shapes_and_whole_pem_blocks():
    from usta.audit import mask

    pem = (
        "-----BEGIN RSA "
        + "PRIVATE KEY-----\nMIIEowIBAAKCAQEA1234\nabcd\n-----END RSA PRIVATE KEY-----"
    )
    for secret in (
        "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx_yz-0123",
        "AIzaSyA-1234567890abcdefghijklmnopqrstuv",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghij",
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
    ):
        assert secret not in mask(f"anahtar: {secret} son"), secret
    out = mask(f"önce {pem} sonra")
    assert (
        "MIIEowIBAAKCAQEA1234" not in out and "abcd" not in out and "önce" in out and "sonra" in out
    )


def test_session_records_are_masked_too(tmp_path):
    from usta.sessions import SessionStore

    s = SessionStore(tmp_path)
    s.begin("w", "a" * 12, 1.0, {"prompt": "p"})
    s.append(
        "w",
        "a" * 12,
        {
            "i": 0,
            "ts": 1.0,
            "type": "tool_result",
            "data": {"result": "token sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 bitti"},
        },
    )
    raw = next((tmp_path / "sessions" / "w").iterdir()).read_text()
    assert "sk-proj-AbCd" not in raw and "[GİZLİ]" in raw
