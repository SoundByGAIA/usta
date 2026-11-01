"""Araç çağrısı kurtarma: bazı yerel modeller (ör. qwen2.5-coder) çağrıyı `tool_calls` yerine
içeriğe JSON metni olarak yazar. İçerik TAMAMEN bir çağrıdan ibaretse (isteğe bağlı kod çiti ya da
`<tool_call>` sarmalıyla) çağrı sayılır. Açıklama içinde gömülü JSON örnekleri çağrı SAYILMAZ.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from usta.models import ToolCall

MAX_CONTENT = 1_000_000
MAX_CALLS = 3
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```$", re.DOTALL)
_TAG = re.compile(r"^<tool_call>\s*(.*?)\s*</tool_call>$", re.DOTALL)
_NAME_KEYS = ("name", "tool", "function")
_ARG_KEYS = ("arguments", "parameters", "args", "input")


def _unwrap(content: str) -> str:
    text = content.strip()
    for rx in (_FENCE, _TAG):
        m = rx.match(text)
        if m:
            return m.group(1).strip()
    return text


def _one(obj: object, tools: set[str]) -> tuple[str, dict] | None:
    if not isinstance(obj, dict):
        return None
    name = next((obj[k] for k in _NAME_KEYS if k in obj), None)
    if not isinstance(name, str) or name not in tools:
        return None
    key = next((k for k in _ARG_KEYS if k in obj), None)
    if key is None:
        return None
    args = obj[key]
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    return (name, args) if isinstance(args, dict) else None


def extract_calls(content: str | None, tools: Iterable[str]) -> list[ToolCall]:
    known = set(tools)
    if not content or not known or len(content) > MAX_CONTENT:
        return []
    text = _unwrap(content)
    if not text or text[0] not in "{[":
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    items = data if isinstance(data, list) else [data]
    if not items or len(items) > MAX_CALLS:
        return []
    parsed = [_one(item, known) for item in items]
    if any(p is None for p in parsed):
        return []
    return [ToolCall(f"r{i}", name, args) for i, (name, args) in enumerate(parsed, 1)]  # type: ignore[misc]
