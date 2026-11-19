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

from usta import compat
from usta.capability_probes import PROBES, CapabilityError, ProbeResult, normalize_ctx
from usta.jsonproto import JsonProtocolClient
from usta.modelinfo import detect_revision  # noqa: F401 - dışa açık ad (geriye dönük)
from usta.models import ModelClient
from usta.textproto import TextProtocolClient

SCHEMA = 1
PROTOCOLS = ("native", "json", "text")  # eşitlikte en basit/güvenilir olan önce
MIN_SCORE = 0.5  # bunun altında hiçbir protokol güvenilir sayılmaz


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


def realistic_ctx(long_chars: int = 6000) -> dict:
    """Sondaları AJANIN gerçek sistem istemi ve gerçek araç şemalarıyla koştur: küçük bir araç kümesiyle ölçülen yetenek,
    büyük araç kümesi altında çökebilir; sonda bu yüzden gerçek yapılandırmayı kullanır."""
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
    # görevi bitiremeyen protokol yakın skorla öne geçmemeli.
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
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() and not path.is_symlink()
            else {}
        )
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
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() and not path.is_symlink()
            else {}
        )
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[p.key] = asdict(p)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("capabilities.json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | compat.nofollow(), 0o600)
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
