import stat

import pytest

from usta import profile
from usta.models import ModelError, ModelResponse, ToolCall, Usage


class Fake:
    """native: tools verilince nasıl davranır; text: tools=None iken (metin protokolü) ne yazar."""

    def __init__(self, native="call", text="call"):
        self.native, self.text, self.usage = native, text, Usage()
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        last = next(m.content for m in reversed(messages) if m.role == "user")
        want = (
            ("write_file", {"path": "not.txt", "content": 'satır 1\n"tırnaklı" satır 2\n'})
            if "yaz" in last
            else ("run", {"command": "ls"})
            if "komut" in last
            else ("read_file", {"path": "a.txt"})
        )
        if tools:
            if self.native == "call":
                return ModelResponse(None, [ToolCall("c1", want[0], want[1])])
            if self.native == "rescue":
                self.usage.rescued += 1
                return ModelResponse(None, [ToolCall("r1", want[0], want[1])])
            if self.native == "wrong":
                return ModelResponse(None, [ToolCall("c1", "yok_arac", {})])
            if self.native == "error":
                raise ModelError("ReadTimeout", infra=True)
            return ModelResponse("Elbette, dosyayı okuyabilirim.")  # araç çağırmadan konuşur
        if self.text == "call":
            import json

            from usta.textproto import CLOSE, OPEN

            args = {k: v for k, v in want[1].items() if k != "content"}
            body = json.dumps({"tool": want[0], "arguments": args}, ensure_ascii=False)
            if "content" in want[1]:
                body += f"\n{OPEN}\n{want[1]['content']}{CLOSE}"
            return ModelResponse(body.replace("\n" + CLOSE, "\n" + CLOSE) if False else body)
        return ModelResponse("düz konuşma, çağrı yok")


def test_good_native_model_gets_native():
    p = profile.probe(Fake("call", "call"), "m")
    assert p.protocol == "native" and p.native_ok == p.total and p.rescued == 0


def test_rescued_native_still_counts_as_native_and_is_reported():
    p = profile.probe(Fake("rescue", "none"), "m")
    assert p.protocol == "native" and p.rescued == p.total and "kurtar" in p.note.lower()


def test_native_silent_but_text_protocol_works_picks_text():
    p = profile.probe(Fake("talk", "call"), "m")
    assert p.protocol == "text" and p.text_ok == p.total and p.native_ok == 0


def test_neither_works_falls_back_to_text_with_warning():
    p = profile.probe(Fake("talk", "none"), "m")
    assert p.protocol == "text" and p.native_ok == 0 and p.text_ok == 0 and "güvenilir" in p.note


def test_wrong_tool_names_do_not_count_as_ok():
    p = profile.probe(Fake("wrong", "call"), "m")
    assert p.native_ok == 0 and p.protocol == "text"


def test_infra_error_raises_clear_error():
    with pytest.raises(profile.ProfileError, match="ulaşılamadı"):
        profile.probe(Fake("error"), "m")


def test_multiline_content_with_quotes_is_part_of_the_probe():
    seen = []

    class Spy(Fake):
        def chat(self, messages, tools=None):
            seen.append(next(m.content for m in reversed(messages) if m.role == "user"))
            return super().chat(messages, tools)

    profile.probe(Spy(), "m")
    assert any("yaz" in s for s in seen) and any("komut" in s for s in seen)


def test_probe_is_small():
    f = Fake()
    profile.probe(f, "m")
    assert f.calls <= 8


# --- önbellek -------------------------------------------------------------------------------
def test_cache_roundtrip_private_and_keyed_by_endpoint_and_model(tmp_path):
    p = profile.probe(Fake("talk", "call"), "m")
    profile.save(tmp_path, "http://e/v1", "m", p)
    got = profile.load(tmp_path, "http://e/v1", "m")
    assert got is not None and got.protocol == "text"
    assert profile.load(tmp_path, "http://e/v1", "baska") is None
    assert profile.load(tmp_path, "http://baska/v1", "m") is None
    assert stat.S_IMODE((tmp_path / "profiles.json").stat().st_mode) == 0o600


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "profiles.json").write_text("{bozuk")
    assert profile.load(tmp_path, "http://e/v1", "m") is None
    for text in ("[]", '{"http://e/v1|m": {"protocol": "tehlikeli"}}', '{"http://e/v1|m": 5}'):
        (tmp_path / "profiles.json").write_text(text)
        assert profile.load(tmp_path, "http://e/v1", "m") is None


# --- json protokolü seçimi -----------------------------------------------------------------
class FakeJson(Fake):
    """Native sessiz, düz metin protokolü bozuk; yalnız şemalı JSON çalışır."""

    def chat(self, messages, tools=None, extra=None):
        if extra and "response_format" in extra:
            self.calls += 1
            import json

            last = next(m.content for m in reversed(messages) if m.role == "user")
            want = (
                ("write_file", {"path": "not.txt", "content": 'satır 1\n"tırnaklı" satır 2\n'})
                if "yaz" in last
                else ("run", {"command": "ls"})
                if "komut" in last
                else ("read_file", {"path": "a.txt"})
            )
            return ModelResponse(
                json.dumps({"action": "tool", "tool": want[0], "arguments": want[1]})
            )
        return ModelResponse("Elbette." if tools else "düz konuşma")


def test_json_protocol_chosen_when_native_and_text_fail_but_schema_works():
    p = profile.probe(FakeJson(), "m")
    assert p.protocol == "json" and p.json_ok == p.total and p.native_ok == 0 and p.text_ok == 0
    assert "json" in p.note


def test_native_still_wins_ties_and_clients_without_extra_skip_json():
    p = profile.probe(Fake("call", "call"), "m")
    assert p.protocol == "native" and p.json_ok == 0  # Fake.chat `extra` almaz → json denenmez


def test_old_cache_entries_without_json_field_still_load(tmp_path):
    import json

    (tmp_path / "profiles.json").write_text(
        json.dumps(
            {
                "http://e/v1|m": {
                    "model": "m",
                    "protocol": "text",
                    "native_ok": 0,
                    "text_ok": 3,
                    "rescued": 0,
                    "total": 3,
                    "note": "eski",
                    "ts": 1.0,
                }
            }
        )
    )
    got = profile.load(tmp_path, "http://e/v1", "m")
    assert got is not None and got.protocol == "text" and got.json_ok == 0
