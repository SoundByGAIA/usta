"""JSON-metin yedek protokolü: yerel araç çağrısı desteklemeyen küçük modeller için.

Yanıt ya düz metindir (son yanıt) ya da tek bir araç çağrısıdır:

    {"tool": "write_file", "arguments": {"path": "a.py"}}
    <<<İÇERİK
    ham kod, JSON kaçışı yok
    İÇERİK>>>

Bloklar `<<<İÇERİK ad` ile adlandırılır (varsayılan ad: content) ve argümanlara eklenir.
Kapanmamış blok, kesik JSON ve belirsiz biçimler reddedilir (ProtocolError).
"""

from __future__ import annotations

import json
import re

from usta.models import Message, ModelClient, ModelError, ModelResponse, ToolCall

OPEN = "<<<İÇERİK"
CLOSE = "İÇERİK>>>"
_NAME = re.compile(r"\s*(\w+)?\s*")

PROTOCOL_PROMPT = f"""Araç kullanmak için yanıtın TAMAMI tek bir çağrı olmalı:
{{"tool": "araç_adı", "arguments": {{"arg": "değer"}}}}
Çok satırlı metin/kod (dosya içeriği gibi) JSON içine yazılmaz; çağrıdan sonra ayrı blokta verilir:
{OPEN}
ham metin
{CLOSE}
Birden çok blok için `{OPEN} ad` kullan (ör. edit_file için `{OPEN} old` ve `{OPEN} new`);
adsız blok `content` olur. Blok kapanış satırı ({CLOSE}) satır başında olmalı.
Bir yanıtta yalnız bir çağrı yap, çağrıdan sonra başka metin yazma. İş bitince araç çağrısı
yapmadan düz metinle yanıtla. Araç sonuçları "araç sonucu" ile gelir.
Kullanılabilir araçlar (JSON şeması):
"""


class ProtocolError(ValueError):
    pass


def parse_reply(text: str, call_id: str = "t1") -> ModelResponse:
    stripped = text.strip()
    if not stripped.startswith("{"):
        if re.search(rf"^{re.escape(OPEN)}", text, re.MULTILINE):
            raise ProtocolError("içerik bloğu var ama araç çağrısı yok")
        return ModelResponse(text)
    try:
        obj, end = json.JSONDecoder().raw_decode(stripped)
    except ValueError as e:
        raise ProtocolError("JSON çözümlenemedi (kesik olabilir)") from e
    if not isinstance(obj, dict) or "tool" not in obj:
        return ModelResponse(text)
    tool, args = obj["tool"], obj.get("arguments", {})
    if not isinstance(tool, str) or not tool:
        raise ProtocolError('"tool" bir ad (metin) olmalı')
    if not isinstance(args, dict):
        raise ProtocolError('"arguments" bir nesne olmalı')
    rest, args = stripped[end:], dict(args)
    seen: set[str] = set()
    while rest.strip():
        rest = rest.lstrip()
        if not rest.startswith(OPEN):
            raise ProtocolError("çağrıdan sonra yalnız içerik blokları gelebilir")
        nl = rest.find("\n")
        if nl < 0:
            raise ProtocolError("içerik bloğu kapanmamış")
        name = _NAME.fullmatch(rest[len(OPEN) : nl])
        if name is None:
            raise ProtocolError("blok adı geçersiz")
        name = name.group(1) or "content"
        if name in seen or name in args:
            raise ProtocolError(f"'{name}' birden çok kez veriliyor")
        pos = nl
        while True:
            close = rest.find("\n" + CLOSE, pos)
            if close < 0:
                raise ProtocolError("içerik bloğu kapanmamış (kesilmiş olabilir)")
            after = rest[close + 1 + len(CLOSE) :]
            if after == "" or after[0] in " \t\r\n" and after.split("\n", 1)[0].strip() == "":
                break
            pos = close + 1
        args[name] = rest[nl + 1 : close]
        seen.add(name)
        rest = after
    return ModelResponse(None, [ToolCall(call_id, tool, args)])


def render_call(call: ToolCall) -> str:
    inline, blocks = {}, []
    for k, v in call.arguments.items():
        if isinstance(v, str) and "\n" in v and ("\n" + CLOSE) not in "\n" + v and k.isidentifier():
            blocks.append(f"{OPEN}{'' if k == 'content' else ' ' + k}\n{v}\n{CLOSE}")
        else:
            inline[k] = v
    head = json.dumps({"tool": call.name, "arguments": inline}, ensure_ascii=False)
    return "\n".join([head, *blocks])


class TextProtocolClient:
    """Bir ModelClient'ı sarar; araçları metin protokolüne çevirir, yanıtı ayrıştırır."""

    def __init__(self, inner: ModelClient, retries: int = 2):
        self.inner, self.retries, self._n = inner, retries, 0

    @property
    def usage(self):
        return getattr(self.inner, "usage", None)

    def _flatten(self, messages: list[Message], tools: list[dict] | None) -> list[Message]:
        schema = "\n".join(json.dumps(t, ensure_ascii=False) for t in tools or [])
        out: list[Message] = []
        names: dict[str, str] = {}
        for m in messages:
            if m.role == "system":
                out.append(Message("system", f"{m.content}\n\n{PROTOCOL_PROMPT}{schema}"))
            elif m.role == "assistant" and m.tool_calls:
                names.update({c.id: c.name for c in m.tool_calls})
                out.append(Message("assistant", render_call(m.tool_calls[0])))
            elif m.role == "tool":
                out.append(
                    Message("user", f"araç sonucu ({names.get(m.tool_call_id, '?')}):\n{m.content}")
                )
            else:
                out.append(Message(m.role, m.content or ""))
        if not any(m.role == "system" for m in out):
            out.insert(0, Message("system", PROTOCOL_PROMPT + schema))
        return out

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> ModelResponse:
        wire = self._flatten(messages, tools)
        for attempt in range(self.retries + 1):
            reply = self.inner.chat(wire, None)
            text = reply.content or ""
            self._n += 1
            try:
                parsed = parse_reply(text, f"t{self._n}")
            except ProtocolError as e:
                if attempt == self.retries:
                    raise ModelError(f"model protokolü bozdu: {e}") from e
                wire = [
                    *wire,
                    Message("assistant", text),
                    Message("user", f"protokol hatası: {e}. Biçime uyarak yeniden dene."),
                ]
                continue
            return parsed
        raise AssertionError("ulaşılamaz")
