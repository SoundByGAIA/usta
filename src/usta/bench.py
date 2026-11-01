"""Ölçüm düzeneği: küçük gerçek yazılım görevlerini bir modelle çalıştırıp gizli testle doğrular.

Amaç harness değişikliklerinin (araç seti, istem, doğrulama döngüsü, bağlam yönetimi) küçük modellerde
gerçekten fark yaratıp yaratmadığını sayıyla görmek. Her görev: başlangıç deposu (`repo/`), ajanın
GÖRMEDİĞİ doğrulama dosyaları (`check/`, bitince çalışma alanına yazılır ve ajanın testleri ezilir) ve
sandbox'ta çalışan doğrulama komutu. Görevler stdlib `unittest` kullanır (imajda ek paket gerekmez).
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from usta.agent import Agent
from usta.audit import AuditLog
from usta.breaker import CircuitBreaker
from usta.models import ModelClient, ModelError
from usta.policy import Policy
from usta.sandbox import SandboxConfig, SandboxError, run_command
from usta.tools import ToolContext, build_registry
from usta.verify import CompletionGate, Verifier

TASKS_DIR = Path(__file__).with_name("bench_tasks")


@dataclass(frozen=True)
class Arm:
    """Deney kolu: hangi harness yapılandırmasıyla ölçüldü."""

    name: str
    description: str
    tools: frozenset[str] | None = None  # None: Usta'nın tüm varsayılan araçları
    system_prompt: str | None = None  # None: Usta'nın varsayılan sistem istemi
    verify: bool = False  # düzenleme geri bildirimi + bitirme kapısı (verify.py)
    breaker: bool = False  # devre kesici: döngüde geri sar, denenenleri bildir (breaker.py)


MINIMAL_PROMPT = (
    "Bir yazılım görevini çözen ajansın. Tek aracın var: run (çalışma dizininde kabuk komutu çalıştırır). "
    "Dosyaları komutlarla oku ve düzenle, testleri çalıştır. İş bitince kısa bir yanıt yaz."
)
ARMS: dict[str, Arm] = {
    "A": Arm(
        "A", "minimal ajan: yalnız kabuk aracı, kısa istem", frozenset({"run"}), MINIMAL_PROMPT
    ),
    "B": Arm("B", "mevcut Usta: dosya araçları, varsayılan istem"),
    "C": Arm("C", "Usta + doğrulama: sözdizimi geri bildirimi, bitirme kapısı", verify=True),
    "D": Arm("D", "Usta + doğrulama + devre kesici", verify=True, breaker=True),
}


@dataclass(frozen=True)
class BenchTask:
    id: str
    prompt: str
    repo: Path
    check: Path
    check_cmd: tuple[str, ...]


@dataclass(frozen=True)
class TaskResult:
    task: str
    passed: bool
    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    denied: int = 0
    seconds: float = 0.0
    truncated: bool = False
    error: str = ""
    check_output: str = ""
    outcome: str = ""  # pass | fail | infra (altyapı: görev başarısızlığı sayılmaz)
    attempts: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    edits: int = 0
    verified: bool = False  # son düzenlemeden sonra en az bir `run` çalıştırıldı
    unverified_claim: bool = False  # düzenledi, bitti dedi, ama doğrulamadı
    gate: str = ""  # bitirme kapısının son durumu: passed | failed | unavailable | ""
    gate_rounds: int = 0  # kapının başarısız saydığı tur sayısı
    breaker_trips: int = 0  # devre kesicinin açıldığı sayı
    blocked: bool = False  # devre kesici akışı kesip kullanıcıya bıraktı
    tests_modified: bool = False  # depodaki mevcut test dosyalarını değiştirdi/sildi

    def __post_init__(self) -> None:
        if not self.outcome:
            object.__setattr__(self, "outcome", "pass" if self.passed else "fail")


def load_tasks(root: Path = TASKS_DIR) -> list[BenchTask]:
    tasks = []
    for d in sorted(Path(root).iterdir()):
        spec = d / "task.json"
        if not spec.is_file():
            continue
        data = json.loads(spec.read_text())
        tasks.append(
            BenchTask(d.name, data["prompt"], d / "repo", d / "check", tuple(data["check_cmd"]))
        )
    return tasks


def verify(task: BenchTask, workspace: Path, timeout: float = 60.0) -> tuple[bool, str]:
    """Gizli doğrulama dosyalarını çalışma alanına yazar (ajanın testlerini ezer) ve komutu koşar."""
    shutil.copytree(task.check, workspace, dirs_exist_ok=True)
    cfg = SandboxConfig(workdir=workspace, timeout=timeout, memory="256m")
    try:
        r = run_command(cfg, list(task.check_cmd))
    except SandboxError as e:
        return False, f"sandbox hatası: {e}"
    out = (r.stdout + r.stderr).strip()
    return r.exit_code == 0 and not r.timed_out, out[-1500:]


def _tests_modified(repo: Path, ws: Path) -> bool:
    for f in repo.rglob("test_*.py"):
        mine = ws / f.relative_to(repo)
        if not mine.is_file() or mine.read_bytes() != f.read_bytes():
            return True
    return False


def _attempt(
    task: BenchTask,
    model: ModelClient,
    *,
    max_steps: int,
    time_limit: float,
    agent_factory: Callable[..., Agent],
    arm: Arm,
) -> TaskResult:
    t0 = time.monotonic()
    counts = {"tool_calls": 0, "tool_errors": 0, "denied": 0}
    gate_events: list[str] = []
    trips: list[bool] = []
    order: list[str] = []  # araç çağrılarının sırası: doğrulama, son düzenlemeden sonra mı?
    usage = getattr(model, "usage", None)
    before = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)

    def on_event(kind: str, data: dict) -> None:
        if kind == "tool_call":
            counts["tool_calls"] += 1
            order.append(str(data.get("tool")))
        elif kind == "breaker":
            trips.append(bool(data.get("final")))
        elif kind == "verification":
            gate_events.append(str(data.get("status")))
        elif kind == "denied":
            counts["denied"] += 1
        elif kind == "tool_result" and str(data.get("result", "")).startswith("hata:"):
            counts["tool_errors"] += 1

    cancel = threading.Event()
    timer = threading.Timer(time_limit, cancel.set)
    timer.daemon = True
    with tempfile.TemporaryDirectory(prefix="usta-bench-") as tmp:
        ws = Path(tmp) / "ws"
        shutil.copytree(task.repo, ws)
        registry = build_registry(ToolContext(root=ws, cancel=cancel))
        if arm.tools is not None:
            registry = registry.subset(arm.tools)
        agent = agent_factory(
            model,
            registry,
            Policy(ws),
            AuditLog(Path(tmp) / "audit.jsonl"),
            approver=lambda *_: False,  # ölçümde insan yok: onay gerektiren eylem reddedilir
            max_steps=max_steps,
            on_event=on_event,
            cancel=cancel,
            system_prompt=arm.system_prompt,
            verifier=Verifier(CompletionGate(ws, cancel=cancel)) if arm.verify else None,
            breaker=CircuitBreaker(ws) if arm.breaker else None,
        )
        error, steps, truncated, infra = "", 0, False, False
        timer.start()
        try:
            result = agent.run(task.prompt)
            steps, truncated = result.steps, result.truncated
            if result.cancelled:
                error = "zaman sınırı aşıldı"
        except ModelError as e:
            error, infra = f"model hatası: {e}", e.infra
        finally:
            timer.cancel()
        modified = _tests_modified(task.repo, ws)
        passed, out = verify(task, ws)
    edit_idx = [i for i, n in enumerate(order) if n in ("write_file", "edit_file")]
    run_idx = [i for i, n in enumerate(order) if n == "run"]
    gate_passed = bool(gate_events) and gate_events[-1] == "passed"
    verified = gate_passed or (bool(edit_idx) and bool(run_idx) and run_idx[-1] > edit_idx[-1])
    answered = not error and not truncated
    after = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)
    ok = passed and not error
    return TaskResult(
        task.id,
        ok,
        steps=steps,
        seconds=round(time.monotonic() - t0, 2),
        truncated=truncated,
        error=error,
        check_output="" if passed else out,
        outcome="infra" if infra else "pass" if ok else "fail",
        prompt_tokens=after[0] - before[0],
        completion_tokens=after[1] - before[1],
        requests=after[2] - before[2],
        edits=len(edit_idx),
        verified=verified,
        unverified_claim=answered and bool(edit_idx) and not verified,
        tests_modified=modified,
        gate=next((g for g in reversed(gate_events) if g != "nudge"), ""),
        gate_rounds=gate_events.count("failed"),
        breaker_trips=len(trips),
        blocked=bool(trips) and trips[-1],
        **counts,
    )


def run_task(
    task: BenchTask,
    model: ModelClient,
    *,
    max_steps: int = 30,
    time_limit: float = 600.0,
    agent_factory: Callable[..., Agent] = Agent,
    infra_retries: int = 2,
    retry_delay: float = 3.0,
    arm: Arm = ARMS["B"],
) -> TaskResult:
    """Altyapı hatasında (uç nokta/ağ) yeniden dener; hâlâ başarısızsa `infra` olarak döner."""
    for attempt in range(1, infra_retries + 2):
        r = _attempt(
            task,
            model,
            max_steps=max_steps,
            time_limit=time_limit,
            agent_factory=agent_factory,
            arm=arm,
        )
        if r.outcome != "infra" or attempt == infra_retries + 1:
            return replace(r, attempts=attempt)
        time.sleep(retry_delay)
    raise AssertionError("ulaşılamaz")


def summarize(results: list[TaskResult]) -> dict:
    valid = [r for r in results if r.outcome != "infra"]
    n = len(valid)
    passed = sum(r.passed for r in valid)
    tokens = sum(r.prompt_tokens + r.completion_tokens for r in valid)
    calls = sum(r.tool_calls for r in valid)
    per_task: dict[str, dict[str, int]] = {}
    for r in results:
        d = per_task.setdefault(r.task, {"passed": 0, "runs": 0, "infra": 0})
        if r.outcome == "infra":
            d["infra"] += 1
        else:
            d["runs"] += 1
            d["passed"] += r.passed
    return {
        "runs": len(results),
        "valid_runs": n,
        "infra_errors": len(results) - n,
        "passed": passed,
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "mean_steps": round(statistics.fmean(r.steps for r in valid), 2) if n else 0.0,
        "mean_seconds": round(statistics.fmean(r.seconds for r in valid), 1) if n else 0.0,
        "mean_tokens": round(tokens / n, 1) if n else 0.0,
        "tokens_per_solved": round(tokens / passed) if passed else None,
        "tool_error_rate": round(sum(r.tool_errors for r in valid) / calls, 3) if calls else 0.0,
        "unverified_claims": sum(r.unverified_claim for r in valid),
        "claimed_but_failed": sum(
            r.outcome == "fail" and not r.error and not r.truncated for r in valid
        ),
        "tests_modified": sum(r.tests_modified for r in valid),
        "breaker_trips": sum(r.breaker_trips for r in valid),
        "blocked": sum(r.blocked for r in valid),
        "per_task": per_task,
    }


def run_bench(
    model_factory: Callable[[], ModelClient],
    tasks: list[BenchTask],
    *,
    repeat: int = 1,
    max_steps: int = 30,
    time_limit: float = 600.0,
    infra_retries: int = 2,
    arm: Arm = ARMS["B"],
    agent_factory: Callable[..., Agent] = Agent,
    on_result: Callable[[TaskResult], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[TaskResult]:
    results = []
    for _ in range(repeat):
        for task in tasks:
            if should_stop is not None and should_stop():  # her koşudan önce: dış taraf kesebilir
                return results
            r = run_task(
                task,
                model_factory(),
                max_steps=max_steps,
                time_limit=time_limit,
                infra_retries=infra_retries,
                arm=arm,
                agent_factory=agent_factory,
            )
            results.append(r)
            if on_result:
                on_result(r)
    return results


def report(model: str, protocol: str, results: list[TaskResult], arm: str = "B") -> dict:
    return {
        "arm": arm,
        "model": model,
        "protocol": protocol,
        "summary": summarize(results),
        "results": [asdict(r) for r in results],
    }


def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Başarı oranı için Wilson %95 güven aralığı (küçük örneklemde normal yaklaşımdan güvenilir)."""
    if n <= 0:
        return 0.0, 0.0
    p = passed / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, round(centre - half, 4)), min(1.0, round(centre + half, 4))


def load_report(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or "results" not in data or "model" not in data:
        raise ValueError(f"{path}: bench raporu değil")
    data.setdefault("arm", "B")  # kol alanından önce üretilen raporlar B koluydu
    return data


def compare_markdown(tiers: dict[str, list[Path]]) -> str:
    """Katman (zayıf/orta/büyük) başına kol karşılaştırma tablosu, güven aralığı ve dürüst özet."""
    lines = ["# USTA Bench karşılaştırması", ""]
    for tier, paths in tiers.items():
        reports = [load_report(p) for p in paths]
        lines += [f"## {tier}", ""]
        header = (
            "| Model | Kol | Geçen | %95 aralık | Token/görev | Çözülen başına token | Süre (sn) "
            "| Kanıtsız | 'Bitti' deyip kalan | Altyapı hatası |"
        )
        lines += [header, "|---|---|---|---|---|---|---|---|---|---|"]
        ci: dict[tuple[str, str], tuple[float, float, float]] = {}
        for rep in sorted(reports, key=lambda r: (r["model"], r["arm"])):
            rs = [
                TaskResult(**{k: v for k, v in r.items() if k in TaskResult.__dataclass_fields__})
                for r in rep["results"]
            ]
            s = summarize(rs)
            lo, hi = wilson(s["passed"], s["valid_runs"])
            ci[(rep["model"], rep["arm"])] = (s["pass_rate"], lo, hi)
            solved = s["tokens_per_solved"]
            lines.append(
                f"| {rep['model']} | {rep['arm']} | {s['passed']}/{s['valid_runs']} (%{s['pass_rate'] * 100:.0f}) "
                f"| %{lo * 100:.0f}-%{hi * 100:.0f} | {s['mean_tokens']:g} | {solved if solved is not None else '-'} "
                f"| {s['mean_seconds']:g} | {s['unverified_claims']} | {s['claimed_but_failed']} | {s['infra_errors']} |"
            )
        lines += ["", *_verdicts(ci), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _verdicts(ci: dict[tuple[str, str], tuple[float, float, float]]) -> list[str]:
    out = []
    models = sorted({m for m, _ in ci})
    for m in models:
        arms = {a: v for (mm, a), v in ci.items() if mm == m}
        for a, b in (("B", "A"), ("C", "B")):
            if a in arms and b in arms:
                _, lo_a, hi_a = arms[a]
                _, lo_b, hi_b = arms[b]
                if lo_a > hi_b:
                    out.append(f"- {m}: {a}, {b}'den belirgin şekilde yüksek.")
                elif lo_b > hi_a:
                    out.append(f"- {m}: {b}, {a}'den belirgin şekilde yüksek.")
                else:
                    out.append(
                        f"- {m}: {a} ve {b} arasında belirgin fark yok (aralıklar örtüşüyor)."
                    )
    return out or ["- Karşılaştırılacak kol çifti yok."]
