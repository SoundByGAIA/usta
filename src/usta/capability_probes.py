"""Yetenek sondaları: modele küçük gerçek görevler verip araç çağrısını doğru yapıp yapmadığını ölçen denemeler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from usta.models import Message, ModelClient, ModelError, ToolCall

SYSTEM = "Araçları kullanarak görevi yap. Önce araç çağır."


TOOLS = [
    {"name": "read_file", "description": "Dosya okur.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_dir", "description": "Dizin listeler.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run", "description": "Komut çalıştırır.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "write_file", "description": "Dosya yazar.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]  # fmt: skip


SCHEMAS = {t["name"]: t["parameters"] for t in TOOLS}


@dataclass
class ProbeResult:
    name: str
    ok: bool
    calls: int = 0  # modelin ürettiği araç çağrısı sayısı (tüm tekrarlarda)
    arg_errors: int = 0  # şemaya uymayan çağrı sayısı (eksik/fazla/yanlış tip/bilinmeyen araç)
    note: str = ""
    ms: int = 0
    passes: int = 1  # tekrarlardan kaçı geçti (tek sonda tek örnektir ve gürültülüdür: yerel modeller örnekler arasında oynar)
    trials: int = 1


class CapabilityError(Exception):
    pass


# --- yardımcılar ---------------------------------------------------------------------------------
def validate_call(call: ToolCall, schemas: dict | None = None) -> str | None:
    """Çağrının şemaya uygunluğu: sorun varsa kısa neden, yoksa None."""
    schema = (schemas or SCHEMAS).get(call.name)
    if schema is None:
        return f"bilinmeyen araç: {call.name}"
    props, required = schema.get("properties", {}), schema.get("required", [])
    for key in required:
        if key not in call.arguments:
            return f"eksik argüman: {key}"
    for key, value in call.arguments.items():
        if key not in props:
            return f"fazla argüman: {key}"
        if props[key].get("type") == "string" and not isinstance(value, str):
            return f"yanlış tip: {key}"
        if props[key].get("type") == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return f"yanlış tip: {key}"
    return None


def _chat(client: ModelClient, ctx: dict, messages: list[Message]):
    try:
        return client.chat(messages, ctx["tools"])
    except ModelError as e:
        if e.infra:
            raise CapabilityError(f"model uç noktasına ulaşılamadı: {e}") from e
        return None  # protokol bozuldu: bu yetenek başarısız


def _tally(reply, ctx: dict) -> tuple[int, int]:
    calls = list(reply.tool_calls) if reply else []
    return len(calls), sum(1 for c in calls if validate_call(c, ctx["schemas"]))


def _has(reply, ctx: dict, tool: str, **expect: str) -> bool:
    return bool(reply) and any(
        c.name == tool and not validate_call(c, ctx["schemas"]) and all(str(c.arguments.get(k, "")).strip() == v for k, v in expect.items())
        for c in reply.tool_calls
    )  # fmt: skip


def _call_msg(call_id: str, name: str, args: dict) -> Message:
    return Message("assistant", None, [ToolCall(call_id, name, args)])


# --- sondalar ------------------------------------------------------------------------------------
def _probe(fn=None, *, single: bool = False):
    """Sonda bağlamını (sistem istemi, araçlar, şemalar) eksikse varsayılanlarla tamamlar.
    `single`: tekrar döngüsünde bir kez koşar (sonda kendi içinde birden çok örnek içerir)."""

    def deco(f):
        def wrapper(client: ModelClient, ctx: dict | None = None) -> ProbeResult:
            return f(client, normalize_ctx(ctx))

        wrapper.__name__ = f.__name__
        wrapper.single = single  # type: ignore[attr-defined]
        return wrapper

    return deco(fn) if fn is not None else deco


E2E_SCENARIOS = (
    "inj-tool-01",
    "readme-01",
    "fake-auth-03",
)  # yalnız dosya araçları; temiz (saldırısız) koşu


@_probe(single=True)
def probe_agent_tasks(client: ModelClient, ctx: dict) -> ProbeResult:
    """Uçtan uca: Lab'ın temiz senaryolarını GERÇEK ajan döngüsü, gerçek izin motoru ve gerçek dosya araçlarıyla çöz.
    Tek tek araç çağrısı sondaları (adı söylenen çağrı) çok adımlı görevlerde protokolün çökmesini yakalayamaz."""
    from usta.lab import runner as labrunner
    from usta.lab import scenario as labscenario

    wanted = ctx.get("e2e", E2E_SCENARIOS)
    if not wanted:  # devre dışı (birim testleri / --no-e2e)
        return ProbeResult("agent_tasks", True, 0, 0, "devre dışı", 0, 0, 0)
    by_id = {s.id: s for s in labscenario.load()}
    harness = labrunner.HarnessConfig()
    meta = {"experiment_id": "capability", "model": "?", "model_revision": ""}
    good = total_calls = 0
    notes = []
    for sid in wanted:
        sc = by_id[sid]
        try:
            rec = labrunner.run_one(
                sc, "clean", client, meta=meta, repeat=1, harness=harness, time_limit=240.0
            )
        except ModelError as e:
            if e.infra:
                raise CapabilityError(f"model uç noktasına ulaşılamadı: {e}") from e
            rec = {"task_success": False, "tool_calls": 0, "failure_category": "MODEL_ERROR"}
        good += bool(rec["task_success"])
        total_calls += rec["tool_calls"]
        if not rec["task_success"]:
            notes.append(f"{sid}: {rec.get('failure_category') or 'başarısız'}")
    n = len(wanted)
    return ProbeResult(
        "agent_tasks",
        good * 3 >= n * 2,
        total_calls,
        0,
        f"{good}/{n} görev çözüldü" + (f" ({'; '.join(notes)})" if notes else ""),
        0,
        good,
        n,
    )


@_probe
def probe_natural_task(client: ModelClient, ctx: dict) -> ProbeResult:
    """Araç ADI verilmeyen gerçek görev cümleleri: model kendiliğinden doğru aracı çağırmalı (çağrıyı metne yazmamalı).
    Gerçek görevler araç adı söylemez; araç adını söyleyen sondalar bu yüzden iyimser kalır."""
    cases = (
        ("notes.txt dosyasında ne yazdığını söyle.", lambda c: c.name in ("read_file", "outline") and c.arguments.get("path") == "notes.txt"),
        ("Bu klasörde hangi dosyalar var?", lambda c: c.name in ("list_dir", "run")),
    )  # fmt: skip
    total_calls = bad_calls = 0
    good = 0
    for prompt, accept in cases:
        reply = _chat(client, ctx, [Message("system", ctx["system"]), Message("user", prompt)])
        n, bad = _tally(reply, ctx)
        total_calls, bad_calls = total_calls + n, bad_calls + bad
        if reply and any(
            accept(c) and not validate_call(c, ctx["schemas"]) for c in reply.tool_calls
        ):
            good += 1
    note = f"{good}/{len(cases)} görev kendiliğinden araç çağrısına dönüştü"
    return ProbeResult("natural_task", good == len(cases), total_calls, bad_calls, note)


@_probe
def probe_single_call(client: ModelClient, ctx: dict) -> ProbeResult:
    reply = _chat(
        client,
        ctx,
        [
            Message("system", ctx["system"]),
            Message("user", "a.txt dosyasını read_file aracıyla oku."),
        ],
    )
    n, bad = _tally(reply, ctx)
    return ProbeResult("single_call", _has(reply, ctx, "read_file", path="a.txt"), n, bad)


@_probe
def probe_run_command(client: ModelClient, ctx: dict) -> ProbeResult:
    msg = "Çalışma dizinindeki dosyaları listelemek için `ls` komutunu run aracıyla çalıştır."
    reply = _chat(client, ctx, [Message("system", ctx["system"]), Message("user", msg)])
    n, bad = _tally(reply, ctx)
    ok = bool(reply) and any(c.name == "run" and not validate_call(c, ctx["schemas"]) and "ls" in c.arguments.get("command", "") for c in reply.tool_calls)  # fmt: skip
    return ProbeResult("run_command", ok, n, bad)


@_probe
def probe_args_exact(client: ModelClient, ctx: dict) -> ProbeResult:
    msg = 'not.txt dosyasına iki satır yaz: birinci satır `satır 1`, ikinci satır `"tırnaklı" satır 2`. write_file kullan.'
    reply = _chat(client, ctx, [Message("system", ctx["system"]), Message("user", msg)])
    n, bad = _tally(reply, ctx)
    ok = False
    if reply:
        for c in reply.tool_calls:
            content = c.arguments.get("content", "")
            if (
                c.name == "write_file"
                and not validate_call(c, ctx["schemas"])
                and c.arguments.get("path") == "not.txt"
            ):
                ok = (
                    isinstance(content, str)
                    and "satır 1" in content
                    and '"tırnaklı" satır 2' in content
                )
    return ProbeResult("args_exact", ok, n, bad, "" if ok else "içerik/tırnak bozuldu ya da eksik")


@_probe
def probe_multi_call(client: ModelClient, ctx: dict) -> ProbeResult:
    msgs = [
        Message("system", ctx["system"]),
        Message("user", "a.txt ve b.txt dosyalarının ikisini de read_file ile oku."),
    ]
    first = _chat(client, ctx, msgs)
    n, bad = _tally(first, ctx)
    if not first:
        return ProbeResult("multi_call", False, n, bad, "yanıt alınamadı")
    got = {
        c.arguments.get("path")
        for c in first.tool_calls
        if c.name == "read_file" and not validate_call(c, ctx["schemas"])
    }
    if {"a.txt", "b.txt"} <= got:
        return ProbeResult("multi_call", True, n, bad, "aynı yanıtta iki çağrı")
    if len(got) != 1 or not first.tool_calls:
        return ProbeResult("multi_call", False, n, bad, "çağrı yok ya da yanlış dosya")
    done = next(iter(got))
    msgs += [Message("assistant", first.content, first.tool_calls)]
    for c in first.tool_calls:
        msgs.append(Message("tool", f"{done} içeriği: merhaba", tool_call_id=c.id))
    second = _chat(client, ctx, msgs)
    n2, bad2 = _tally(second, ctx)
    other = "b.txt" if done == "a.txt" else "a.txt"
    return ProbeResult(
        "multi_call",
        _has(second, ctx, "read_file", path=other),
        n + n2,
        bad + bad2,
        "ardışık iki tur",
    )


@_probe
def probe_error_recovery(client: ModelClient, ctx: dict) -> ProbeResult:
    """Önceki çağrı argümansız hata verdi; model düzeltilmiş çağrıyı yapmalı."""
    msgs = [
        Message("system", ctx["system"]),
        Message("user", "a.txt dosyasını read_file ile oku."),
        _call_msg("e1", "read_file", {}),
        Message("tool", "hata: eksik argüman: path", tool_call_id="e1"),
    ]
    reply = _chat(client, ctx, msgs)
    n, bad = _tally(reply, ctx)
    return ProbeResult("error_recovery", _has(reply, ctx, "read_file", path="a.txt"), n, bad)


@_probe
def probe_bad_output_recovery(client: ModelClient, ctx: dict) -> ProbeResult:
    """Araç 'dosya yok' dedi; model pes etmeden dizine bakmalı (list_dir/run ls) ya da öteki dosyayı denemeli."""
    msgs = [
        Message("system", ctx["system"]),
        Message("user", "veri.txt dosyasını oku; bulunamazsa dizindeki dosyalara bak."),
        _call_msg("b1", "read_file", {"path": "veri.txt"}),
        Message("tool", "hata: FileNotFoundError: veri.txt", tool_call_id="b1"),
    ]
    reply = _chat(client, ctx, msgs)
    n, bad = _tally(reply, ctx)
    ok = bool(reply) and any(
        not validate_call(c, ctx["schemas"]) and (c.name == "list_dir" or (c.name == "run" and "ls" in c.arguments.get("command", "")))
        for c in reply.tool_calls
    )  # fmt: skip
    return ProbeResult("bad_output_recovery", ok, n, bad)


@_probe
def probe_long_context(client: ModelClient, ctx: dict) -> ProbeResult:
    """Uzun bir metnin ortasındaki dosya adını bulup araç çağırma (iğne-saman + araç çağrısı)."""
    chars = int(ctx.get("long_chars", 6000))
    filler = ("Bu satır dolgu metnidir ve görevle ilgisi yoktur. " * 40 + "\n") * max(
        1, chars // 2000
    )
    half = len(filler) // 2
    needle = "GİZLİ DOSYA ADI: rapor-7421.txt"
    text = (
        filler[:half]
        + needle
        + "\n"
        + filler[half:]
        + "\nYukarıdaki metinde geçen GİZLİ DOSYA ADI'nı read_file ile oku."
    )
    reply = _chat(client, ctx, [Message("system", ctx["system"]), Message("user", text)])
    n, bad = _tally(reply, ctx)
    return ProbeResult(
        "long_context",
        _has(reply, ctx, "read_file", path="rapor-7421.txt"),
        n,
        bad,
        f"{len(text)} karakter",
    )


PROBES: tuple[Callable[[ModelClient, dict], ProbeResult], ...] = (
    probe_agent_tasks,
    probe_natural_task,
    probe_single_call,
    probe_run_command,
    probe_args_exact,
    probe_multi_call,
    probe_error_recovery,
    probe_bad_output_recovery,
    probe_long_context,
)


def normalize_ctx(ctx: dict | None) -> dict:
    """Sonda bağlamı: sistem istemi + araç listesi + şemalar (verilmezse küçük varsayılan küme)."""
    ctx = dict(ctx or {})
    ctx.setdefault("system", SYSTEM)
    ctx.setdefault("tools", TOOLS)
    ctx.setdefault("schemas", {t["name"]: t["parameters"] for t in ctx["tools"]})
    return ctx
