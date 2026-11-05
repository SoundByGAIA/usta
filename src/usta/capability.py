"""Model Capability Profiler: bir modelin araç çağrısı yeteneğini protokol başına ölçen yeniden kullanılabilir profil.

`profile.py` üç küçük sondayla en iyi protokolü seçer (hızlı, ilk açılışta). Burası daha derin ölçer:
tek/çoklu araç çağrısı, argüman doğruluğu ve disiplini, hata sonrası toparlanma, bozuk araç çıktısından sonra
toparlanma ve uzun bağlamda araç çağırma; her biri native / json / text protokolünde ayrı ayrı.

Profil model adının yanında UÇ NOKTA, model REVİZYONU (ör. Ollama özeti) ve sunucu YAPILANDIRMASI (bağlam penceresi,
ek gövde alanları) ile ilişkilendirilir: bunlardan biri değişince eski profil geçerli sayılmaz (`~/.usta/capabilities.json`).
Ajan, yeterli kanıt olduğunda görev başında en güvenilir protokolü buradan seçer. Benchmark/lab koşularında protokol
koşu başında bir kez çözülüp SABİTLENİR (rapora yazılır); koşu sırasında değişmez.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from usta.jsonproto import JsonProtocolClient
from usta.modelinfo import detect_revision  # noqa: F401 - dışa açık ad (geriye dönük)
from usta.models import Message, ModelClient, ModelError, ToolCall
from usta.textproto import TextProtocolClient

SCHEMA = 1
PROTOCOLS = ("native", "json", "text")  # eşitlikte en basit/güvenilir olan önce
SYSTEM = "Araçları kullanarak görevi yap. Önce araç çağır."
MIN_SCORE = 0.5  # bunun altında hiçbir protokol güvenilir sayılmaz

TOOLS = [
    {"name": "read_file", "description": "Dosya okur.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_dir", "description": "Dizin listeler.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "run", "description": "Komut çalıştırır.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "write_file", "description": "Dosya yazar.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]  # fmt: skip
SCHEMAS = {t["name"]: t["parameters"] for t in TOOLS}

# probe adı -> ağırlık (çekirdek yetenekler 2, diğerleri 1)
WEIGHTS = {
    "agent_tasks": 4,  # uçtan uca: gerçek ajan döngüsü + gerçek araçlarla küçük görevler (en öngörücü sonda)
    "natural_task": 2,
    "single_call": 2,
    "run_command": 2,
    "args_exact": 2,
    "multi_call": 1,
    "error_recovery": 1,
    "bad_output_recovery": 1,
    "long_context": 1,
}


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


@dataclass
class ProtocolScore:
    protocol: str
    results: list[ProbeResult] = field(default_factory=list)
    score: float = 0.0  # ağırlıklı geçme oranı
    arg_error_rate: float = 0.0
    infra_error: str = ""

    def finish(self) -> ProtocolScore:
        rs = [
            r for r in self.results if r.trials > 0
        ]  # hiç örneği olmayan (devre dışı) sonda skora girmez
        total = sum(WEIGHTS.get(r.name, 1) for r in rs)
        good = sum(WEIGHTS.get(r.name, 1) * r.passes / r.trials for r in rs)
        self.score = round(good / total, 3) if total else 0.0
        calls = sum(r.calls for r in self.results)
        self.arg_error_rate = (
            round(sum(r.arg_errors for r in self.results) / calls, 3) if calls else 0.0
        )
        return self


@dataclass
class CapabilityProfile:
    schema: int
    model: str
    endpoint: str
    revision: str
    config: dict
    key: str
    ts: float
    recommended: str
    rationale: str
    protocols: dict[str, dict]
    long_context_chars: int = 0
    probe_tools: int = 0  # sondada modele sunulan araç sayısı
    repeats: int = 1  # her sonda kaç kez tekrarlandı
    realistic: bool = False  # sondalar ajanın gerçek sistem istemi + araç şemalarıyla mı koştu


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


def realistic_ctx(long_chars: int = 6000) -> dict:
    """Sondaları AJANIN gerçek sistem istemi ve gerçek araç şemalarıyla koştur: küçük bir araç kümesiyle ölçülen yetenek,
    büyük araç kümesi altında çökebilir (7B yerel modellerde gözlendi); sonda bu yüzden gerçek yapılandırmayı kullanır."""
    import tempfile

    from usta.agent import SYSTEM_PROMPT
    from usta.tools import ToolContext, build_registry

    with tempfile.TemporaryDirectory(prefix="usta-probe-") as d:
        tools = build_registry(ToolContext(root=Path(d))).schemas()
    return normalize_ctx(
        {"system": SYSTEM_PROMPT, "tools": tools, "long_chars": long_chars, "realistic": True}
    )


def run_protocol(client: ModelClient, protocol: str, ctx: dict) -> ProtocolScore:
    """Her sonda `repeats` kez koşar; sonda geçmiş sayılması için örneklerin en az 2/3'ü geçmeli (skor ise kesirlidir)."""
    ctx = normalize_ctx(ctx)
    repeats = max(1, int(ctx.get("repeats", 1)))
    score = ProtocolScore(protocol)
    for fn in PROBES:
        t0 = time.monotonic()
        runs: list[ProbeResult] = []
        try:
            if getattr(fn, "single", False):
                res = fn(client, ctx)
                res.ms = round((time.monotonic() - t0) * 1000)
                if res.trials > 0:  # devre dışı bırakılmış sonda sonuca hiç girmez
                    score.results.append(res)
                continue
            for _ in range(repeats):
                runs.append(fn(client, ctx))
        except CapabilityError as e:
            score.infra_error = str(e)
            raise
        passes = sum(r.ok for r in runs)
        note = (
            runs[-1].note
            if repeats == 1
            else f"{passes}/{repeats} örnek geçti" + (f"; {runs[-1].note}" if runs[-1].note else "")
        )
        score.results.append(
            ProbeResult(
                runs[0].name,
                passes * 3 >= repeats * 2,
                sum(r.calls for r in runs),
                sum(r.arg_errors for r in runs),
                note,
                round((time.monotonic() - t0) * 1000),
                passes,
                repeats,
            )
        )
    return score.finish()


def wrap(base: ModelClient, protocol: str) -> ModelClient:
    if protocol == "json":
        return JsonProtocolClient(base, retries=0)
    if protocol == "text":
        return TextProtocolClient(base, retries=0)
    return base


def config_hash(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def profile_key(endpoint: str, model: str, revision: str, config: dict) -> str:
    return f"{endpoint.rstrip('/')}|{model}|{revision or '-'}|{config_hash(config)}"


def recommend(scores: dict[str, ProtocolScore]) -> tuple[str, str]:
    """Protokol önerisi: en yüksek skor, eşitlikte en basit. Kanıt yetersizse `text` ve açıklama."""
    best = max(
        PROTOCOLS, key=lambda p: (scores[p].score if p in scores else -1, -PROTOCOLS.index(p))
    )
    s = scores.get(best)
    if s is None or s.score < MIN_SCORE:
        return (
            "text",
            f"hiçbir protokol yeterince güvenilir değil (skor < %{MIN_SCORE * 100:.0f}); metin protokolü denenecek",
        )
    others = ", ".join(f"{p} {scores[p].score:.2f}" for p in PROTOCOLS if p in scores)

    # Skorlar yakınsa en öngörücü kanıt (uçtan uca ajan görevleri) karar verir: tek çağrı sondalarını geçip çok adımlı
    # görevi bitiremeyen protokol (7B native örneği) yakın skorla öne geçmemeli.
    def agent(p: str) -> float:
        r = next((r for r in scores[p].results if r.name == "agent_tasks"), None)
        return r.passes / r.trials if r and r.trials else -1.0

    for p in PROTOCOLS:
        if (
            p in scores
            and p != best
            and scores[p].score >= s.score - 0.1
            and agent(p) - agent(best) >= 0.3
        ):
            return p, (
                f"{p} (skorlar yakın: {others}; ama uçtan uca ajan görevlerinde {p} "
                f"{agent(p):.0%} vs {best} {agent(best):.0%}); argüman hata oranı {scores[p].arg_error_rate:.0%}"
            )
    return best, f"{best} en yüksek skor ({others}); argüman hata oranı {s.arg_error_rate:.0%}"


def profile_model(
    make_client: Callable[[], ModelClient],
    model: str,
    *,
    endpoint: str,
    revision: str = "",
    config: dict | None = None,
    long_chars: int = 6000,
    protocols: tuple[str, ...] = PROTOCOLS,
    realistic: bool = True,
    repeats: int = 3,
    e2e: tuple[str, ...] | None = None,
) -> CapabilityProfile:
    config = dict(config or {})
    ctx = realistic_ctx(long_chars) if realistic else normalize_ctx({"long_chars": long_chars})
    ctx["repeats"] = repeats
    if e2e is not None:
        ctx["e2e"] = list(e2e)
    scores: dict[str, ProtocolScore] = {}
    for proto in protocols:
        if proto == "json" and not _supports_extra(make_client()):
            continue  # sunucu şema kısıtlı yanıtı desteklemiyor
        scores[proto] = run_protocol(wrap(make_client(), proto), proto, ctx)
    rec, why = recommend(scores)
    return CapabilityProfile(
        schema=SCHEMA,
        model=model,
        endpoint=endpoint.rstrip("/"),
        revision=revision,
        config=config,
        key=profile_key(endpoint, model, revision, config),
        ts=time.time(),
        recommended=rec,
        rationale=why,
        protocols={p: asdict(s) for p, s in scores.items()},
        long_context_chars=long_chars,
        probe_tools=len(ctx["tools"]),
        realistic=bool(ctx.get("realistic")),
        repeats=repeats,
    )


def _supports_extra(client: object) -> bool:
    import inspect

    try:
        return "extra" in inspect.signature(client.chat).parameters  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return False


# --- kalıcılık -----------------------------------------------------------------------------------
def _path(home: Path) -> Path:
    return Path(home) / "capabilities.json"


def load(
    home: Path, endpoint: str, model: str, revision: str, config: dict
) -> CapabilityProfile | None:
    """Anahtar (uç nokta + model + revizyon + yapılandırma) tam eşleşmezse None: eski profil geçersizdir."""
    path = _path(home)
    try:
        data = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
        raw = (
            data.get(profile_key(endpoint, model, revision, config))
            if isinstance(data, dict)
            else None
        )
        if (
            not isinstance(raw, dict)
            or raw.get("schema") != SCHEMA
            or raw.get("recommended") not in PROTOCOLS
        ):
            return None
        return CapabilityProfile(
            **{k: raw[k] for k in CapabilityProfile.__dataclass_fields__ if k in raw}
        )
    except (OSError, ValueError, TypeError):
        return None


def save(home: Path, p: CapabilityProfile) -> None:
    home = Path(home)
    path = _path(home)
    try:
        data = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[p.key] = asdict(p)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("capabilities.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def table(p: CapabilityProfile) -> str:
    """İnsan okunur özet tablo (CLI)."""
    names = [fn.__name__.removeprefix("probe_") for fn in PROBES]
    lines = [
        (
            f"{p.model} @ {p.endpoint} (revizyon: {p.revision or 'bilinmiyor'}, "
            f"yapılandırma: {config_hash(p.config)}; "
            f"sonda: {'ajanın gerçek istemi ve ' + str(p.probe_tools) + ' aracı' if p.realistic else str(p.probe_tools) + ' araçlı küçük küme'}; "
            f"tekrar: {p.repeats})"
        ),
        f"{'sonda':22}" + "".join(f"{proto:>9}" for proto in p.protocols),
    ]
    for name in names:
        row = f"{name:22}"
        for proto in p.protocols:
            res = next((r for r in p.protocols[proto]["results"] if r["name"] == name), None)
            cell = (
                "-"
                if not res
                else f"{res['passes']}/{res['trials']}"
                if res.get("trials", 1) > 1
                else ("ok" if res["ok"] else "YOK")
            )
            row += f"{cell:>9}"
        lines.append(row)
    lines.append(f"{'skor':22}" + "".join(f"{p.protocols[x]['score']:>9.2f}" for x in p.protocols))
    lines.append(
        f"{'argüman hata oranı':22}"
        + "".join(f"{p.protocols[x]['arg_error_rate']:>9.0%}" for x in p.protocols)
    )
    lines.append(f"Öneri: {p.recommended} — {p.rationale}")
    return "\n".join(lines)
