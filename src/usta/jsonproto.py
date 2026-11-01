"""Şemayla kısıtlı JSON protokolü: sunucu çıktıyı JSON şemasına kilitler (`response_format`).

Yerel araç çağrısı güvenilmez ama sunucu yapılandırılmış çıktıyı (llama.cpp grammar / Ollama / vLLM)
zorlayabiliyorsa, çok satırlı kod ve tırnak kaçışları artık modelin elinde değildir: kod normal bir
JSON metin alanıdır ve sunucu kaçışı garanti eder. Yanıt ya `{"action":"tool",...}` ya da
`{"action":"final","message":...}` olur. Şemaya rağmen gelen geçersiz yanıtlar (eksik argüman vb.)
geri bildirimle yeniden denenir.
"""

from __future__ import annotations

import json

from usta.models import Message, ModelError, ModelResponse, ToolCall

PROMPT = (
    "Her yanıtın TEK bir JSON nesnesi olmalı. Araç çağırmak için: "
    '{"action": "tool", "tool": "araç_adı", "arguments": {"arg": "değer"}}. '
    'İş bitince: {"action": "final", "message": "kısa yanıt"}. Çok satırlı metin/kod JSON metin alanında verilir. '
    'Bir yanıtta yalnız bir araç çağır. Araç sonuçları "araç sonucu" ile gelir.\nKullanılabilir araçlar:\n'
)


def build_schema(tools: list[dict]) -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["tool", "final"]},
            "tool": {"type": "string", "enum": [t["name"] for t in tools]},
            "arguments": {"type": "object"},
            "message": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }


class _Bad(ValueError):
    pass


def _check_args(tool: dict, args: object) -> dict:
    if not isinstance(args, dict):
        raise _Bad('"arguments" bir nesne olmalı')
    params = tool.get("parameters", {})
    for key in params.get("required", []):
        if key not in args:
            raise _Bad(f"{tool['name']}: '{key}' argümanı eksik")
    for key, spec in params.get("properties", {}).items():
        if key in args and spec.get("type") == "string" and not isinstance(args[key], str):
            raise _Bad(f"{tool['name']}: '{key}' metin olmalı")
        if (
            key in args
            and spec.get("type") == "integer"
            and (not isinstance(args[key], int) or isinstance(args[key], bool))
        ):
            raise _Bad(f"{tool['name']}: '{key}' tamsayı olmalı")
    return args


class JsonProtocolClient:
    """Bir istemciyi sarar; araçları şemayla kısıtlı JSON protokolüne çevirir."""

    def __init__(self, inner, retries: int = 2):
        self.inner, self.retries, self._n = inner, retries, 0

    @property
    def usage(self):
        return getattr(self.inner, "usage", None)

    def _flatten(self, messages: list[Message], tools: list[dict]) -> list[Message]:
        listing = "\n".join(json.dumps(t, ensure_ascii=False) for t in tools)
        out: list[Message] = []
        names: dict[str, str] = {}
        for m in messages:
            if m.role == "system":
                out.append(Message("system", f"{m.content}\n\n{PROMPT}{listing}"))
            elif m.role == "assistant" and m.tool_calls:
                names.update({c.id: c.name for c in m.tool_calls})
                c = m.tool_calls[0]
                out.append(
                    Message(
                        "assistant",
                        json.dumps(
                            {"action": "tool", "tool": c.name, "arguments": c.arguments},
                            ensure_ascii=False,
                        ),
                    )
                )
            elif m.role == "assistant":
                out.append(
                    Message(
                        "assistant",
                        json.dumps(
                            {"action": "final", "message": m.content or ""}, ensure_ascii=False
                        ),
                    )
                )
            elif m.role == "tool":
                out.append(
                    Message(
                        "user",
                        f"araç sonucu ({names.get(m.tool_call_id or '', '?')}):\n{m.content}",
                    )
                )
            else:
                out.append(Message(m.role, m.content or ""))
        if not any(m.role == "system" for m in out):
            out.insert(0, Message("system", PROMPT + listing))
        return out

    def _parse(self, text: str, by_name: dict[str, dict]) -> ModelResponse:
        try:
            obj = json.loads(text)
        except ValueError:
            raise _Bad("geçerli JSON değil") from None
        if not isinstance(obj, dict) or obj.get("action") not in ("tool", "final"):
            raise _Bad('"action" tool veya final olmalı')
        if obj["action"] == "final":
            if not isinstance(obj.get("message"), str):
                raise _Bad('final için "message" metin olmalı')
            return ModelResponse(obj["message"])
        name = obj.get("tool")
        if name not in by_name:
            raise _Bad(f"bilinmeyen araç: {name!r}")
        args = _check_args(by_name[name], obj.get("arguments"))
        self._n += 1
        return ModelResponse(None, [ToolCall(f"j{self._n}", name, args)])

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> ModelResponse:
        tools = tools or []
        wire = self._flatten(messages, tools)
        schema = build_schema(tools or [{"name": "none"}])
        extra = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "usta_reply", "strict": True, "schema": schema},
            }
        }
        by_name = {t["name"]: t for t in tools}
        for attempt in range(self.retries + 1):
            text = self.inner.chat(wire, None, extra=extra).content or ""
            try:
                reply = self._parse(text, by_name)
            except _Bad as e:
                if attempt == self.retries:
                    raise ModelError(f"model protokolü bozdu: {e}") from e
                wire = [
                    *wire,
                    Message("assistant", text),
                    Message("user", f"protokol hatası: {e}. Biçime uyarak yeniden dene."),
                ]
                continue
            return reply
        raise AssertionError("ulaşılamaz")
