"""Cimri bağlam yönetimi: araç çıktısı bütçesi ve pencere dolarken eski içeriğin sıkıştırılması.

Yerel modellerde (4-16K) KV önbelleği ve bağlam hızla dolar. Burada model çağrısı yapılmaz; kurallar
deterministiktir: büyük çıktılar baş+son korunarak kırpılır, eski araç sonuçları ve eski dosya yazma
içerikleri kısa bir özetle değiştirilir. Mesaj sırası ve araç çağrısı eşleşmeleri korunur.
"""

from __future__ import annotations

import json
from dataclasses import replace

from usta.models import Message

CHARS_PER_TOKEN = 3
PER_MESSAGE_OVERHEAD = 8
RESULT_SHARE = 0.12  # pencerenin tek bir araç sonucuna ayrılabilecek payı
RESULT_FLOOR = 1500
STUB_MIN = 200  # bundan kısa içerikler özetlenmez
COMPACT_AT = 0.70


def estimate_tokens(messages: list[Message]) -> int:
    chars = 0
    for m in messages:
        chars += len(m.content or "") + PER_MESSAGE_OVERHEAD * CHARS_PER_TOKEN
        for c in m.tool_calls:
            chars += len(c.name) + len(json.dumps(c.arguments, ensure_ascii=False))
    return chars // CHARS_PER_TOKEN


def result_limit(window: int | None) -> int | None:
    if not window:
        return None
    return max(RESULT_FLOOR, int(window * CHARS_PER_TOKEN * RESULT_SHARE))


def truncate_result(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    head, tail = int(limit * 0.6), int(limit * 0.4)
    skipped = len(text) - head - tail
    return f"{text[:head]}\n[... {skipped} karakter atlandı: bağlam bütçesi]\n{text[-tail:]}"


def shrink_writes(messages: list[Message], keep: int = 2) -> int:
    """Dosyaya yazılmış içerikleri ERKEN kırpar: son `keep` yazma dokunulmaz, eskilerin gövdesi atılır.

    Dosya diskte durur; model gerekirse read_file/outline/read_symbol ile okur. Başarısız (hata dönen)
    yazmalara dokunulmaz: model aynı içerikle yeniden denemek isteyebilir. Yerinde çalışır; kazanılan
    karakter sayısı döner. Her yazma yalnız bir kez kırpılır (önek sağlayıcı önbelleğinde tekrar sabitlenir).
    """
    failed = {
        m.tool_call_id
        for m in messages
        if m.role == "tool" and (m.content or "").startswith(("hata:", "reddedildi:"))
    }
    writes = [
        (i, c.id)
        for i, m in enumerate(messages)
        if m.role == "assistant"
        for c in m.tool_calls
        if c.name == "write_file" and isinstance(c.arguments.get("content"), str)
    ]
    saved = 0
    for i, call_id in writes[: max(0, len(writes) - keep)]:
        if call_id in failed:
            continue
        m = messages[i]
        new_calls = []
        for c in m.tool_calls:
            v = c.arguments.get("content") if c.id == call_id else None
            if isinstance(v, str) and len(v) > STUB_MIN and not v.startswith("["):
                lines = v.count("\n") + 1
                stub = (
                    f"[{lines} satır, {len(v)} karakter yazıldı; içerik bağlamdan atıldı: "
                    "dosya diskte, gerekirse read_file/outline/read_symbol ile oku]"
                )
                saved += len(v) - len(stub)
                c = replace(c, arguments={**c.arguments, "content": stub})
            new_calls.append(c)
        messages[i] = replace(m, tool_calls=new_calls)
    return saved


def compact(messages: list[Message], keep_last: int = 4) -> int:
    """Eski araç sonuçlarını ve eski dosya yazma içeriklerini özetler (yerinde). Kazanılan karakter sayısı döner."""
    cutoff = max(
        2, len(messages) - keep_last
    )  # sistem + ilk kullanıcı mesajı ve son keep_last dokunulmaz
    names: dict[str, str] = {}
    saved = 0
    for i in range(cutoff):
        m = messages[i]
        if m.role == "assistant":
            for c in m.tool_calls:
                names[c.id] = c.name
            if any(
                isinstance(v, str) and len(v) > STUB_MIN and k in ("content", "new", "old")
                for c in m.tool_calls
                for k, v in c.arguments.items()
            ):
                new_calls = []
                for c in m.tool_calls:
                    args = dict(c.arguments)
                    for k in ("content", "new", "old"):
                        v = args.get(k)
                        if isinstance(v, str) and len(v) > STUB_MIN:
                            args[k] = f"[{len(v)} karakter yazıldı; eski içerik bağlamdan atıldı]"
                            saved += len(v) - len(args[k])
                    new_calls.append(replace(c, arguments=args))
                messages[i] = replace(m, tool_calls=new_calls)
        elif (
            m.role == "tool"
            and len(m.content or "") > STUB_MIN
            and "atıldı" not in (m.content or "")[:60]
        ):
            name = names.get(m.tool_call_id or "", "araç")
            stub = f"[eski {name} sonucu atıldı: {len(m.content or '')} karakter]"
            saved += len(m.content or "") - len(stub)
            messages[i] = replace(m, content=stub)
    return saved
