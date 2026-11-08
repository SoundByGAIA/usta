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
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from usta import taxonomy
from usta.agent import SYSTEM_PROMPT, Agent
from usta.audit import AuditLog
from usta.breaker import CircuitBreaker
from usta.models import ModelClient, ModelError
from usta.phases import PhaseTracker
from usta.policy import Policy
from usta.sandbox import SandboxConfig, SandboxError, run_command
from usta.tools import ToolContext, build_registry
from usta.verify import CompletionGate, Verifier
from usta.verify import env_problem as verify_env_problem

TASKS_DIR = Path(__file__).with_name("bench_tasks")
SPLITS = (
    "train",
    "dev",
    "final",
)  # eğitim: harness/istem ayarı; geliştirme: ara kontrol; final: yalnız sürüm ölçümü
TRACE_VERSION = 1


@dataclass(frozen=True)
class Arm:
    """Deney kolu: hangi harness yapılandırmasıyla ölçüldü."""

    name: str
    description: str
    tools: frozenset[str] | None = None  # None: Usta'nın tüm varsayılan araçları
    system_prompt: str | None = None  # None: Usta'nın varsayılan sistem istemi
    verify: bool = False  # düzenleme geri bildirimi + bitirme kapısı (verify.py)
    breaker: bool = False  # devre kesici: döngüde geri sar, denenenleri bildir (breaker.py)
    context_window: int | None = None  # verilirse bağlam bütçesi/sıkıştırma etkin (token)
    symbol_tools: bool = False  # find_symbol / symbol_context / related_files (usta[symbols])
    taint: bool = False  # kaynak izi kapısı: okunan içerikten türeyen yazma/komut hedefleri onay ister (taint.py)
    cascade: bool = (
        False  # ucuz→güçlü model yükseltmesi (cascade.py; modeli çağıran taraf CascadeModel verir)
    )
    max_read: int | None = (
        None  # verilirse read_file çıktısı bu karakterle sınırlı (kod okuma bütçesi)
    )
    experimental: bool = (
        False  # A-D'nin anlamı değişmez; deneysel yapılandırmalar ayrı etiketle eklenir
    )


MINIMAL_PROMPT = (
    "Bir yazılım görevini çözen ajansın. Tek aracın var: run (çalışma dizininde kabuk komutu çalıştırır). "
    "Dosyaları komutlarla oku ve düzenle, testleri çalıştır. İş bitince kısa bir yanıt yaz."
)
SYMBOL_PROMPT = (
    f"{SYSTEM_PROMPT} Koda yaklaşırken önce related_files ile ilgili dosyaları sırala, find_symbol/symbol_context ile "
    "yalnız gereken fonksiyon ve çağıranlarına bak; tüm dosyayı yalnız bu yetmezse oku."
)
ARMS: dict[str, Arm] = {
    "A": Arm(
        "A", "minimal ajan: yalnız kabuk aracı, kısa istem", frozenset({"run"}), MINIMAL_PROMPT
    ),
    "B": Arm("B", "mevcut Usta: dosya araçları, varsayılan istem"),
    "C": Arm("C", "Usta + doğrulama: sözdizimi geri bildirimi, bitirme kapısı", verify=True),
    "D": Arm("D", "Usta + doğrulama + devre kesici", verify=True, breaker=True),
    # --- deneysel yapılandırmalar (varsayılan değil; A-D anlamları değişmedi) ---
    "X-BRK": Arm("X-BRK", "Usta + yalnız devre kesici (doğrulama kapısı yok)", breaker=True, experimental=True),
    "X-CTX": Arm(
        "X-CTX", "Usta + bağlam bütçesi (8K pencere, araç çıktısı kırpma, sıkıştırma)",
        context_window=8192, experimental=True,
    ),
    "X-ALL": Arm(
        "X-ALL", "Usta + doğrulama + devre kesici + bağlam bütçesi",
        verify=True, breaker=True, context_window=8192, experimental=True,
    ),
    "X-FULL": Arm(
        "X-FULL", "Usta, yalnız tam dosya okuma (outline/read_symbol yok): seçici bağlamın karşılaştırma tabanı",
        tools=frozenset({"read_file", "write_file", "edit_file", "list_dir", "run", "remember", "fetch_url"}),
        experimental=True,
    ),
    "X-SYM": Arm(
        "X-SYM", "Usta + Tree-sitter sembol araçları (find_symbol/symbol_context/related_files) + 12K okuma bütçesi",
        symbol_tools=True, max_read=12_000, system_prompt=SYMBOL_PROMPT, experimental=True,
    ),
}  # fmt: skip
ARMS["X-TAINT"] = replace(
    ARMS["C"],
    name="X-TAINT",
    description="C + kaynak izi kapısı (taint.py)",
    taint=True,
    experimental=True,
)
ARMS["X-CASCADE"] = replace(
    ARMS["C"],
    name="X-CASCADE",
    description="C + kademeli yönlendirme: ucuz model, takılırsa güçlü model (cascade.py; --strong-model gerekir)",
    cascade=True,
    experimental=True,
)


@dataclass(frozen=True)
class BenchTask:
    id: str
    prompt: str
    repo: Path
    check: Path
    check_cmd: tuple[str, ...]
    split: str = "dev"


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
    failure: str = ""  # başarısızlık sınıfı (taxonomy.py); başarılıda boş
    split: str = ""  # görev bölümü (train/dev/final)
    terminal: str = ""  # yürütme aşamaları terminal durumu (phases.TERMINALS)
    phase_steps: dict = field(default_factory=dict)  # aşama -> araç çağrısı sayısı
    phase_transitions: int = 0
    signals: tuple[str, ...] = ()  # tespit edilen tüm işaretler (birincil neden dışındakiler dahil)
    repair_attempts: int = 0  # ilk testten sonra yapılan düzenleme (onarım) sayısı
    context_peak: int = 0  # en büyük bağlam (girdi token, uç nokta bildirirse)
    compactions: int = 0  # bağlam sıkıştırma sayısı
    escalated: bool = False  # kademeli yönlendirme: görev güçlü modele devredildi
    strong_tokens: int = 0  # güçlü modelin harcadığı token (girdi+çıktı)
    trace: str = ""  # adım izi dosyası (--trace-dir verilirse)

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
        split = data.get("split", "dev")
        if split not in SPLITS:
            raise ValueError(f"{d.name}: bilinmeyen split {split!r}")
        tasks.append(
            BenchTask(
                d.name, data["prompt"], d / "repo", d / "check", tuple(data["check_cmd"]), split
            )
        )
    return tasks


def select_tasks(tasks: list[BenchTask], split: str) -> list[BenchTask]:
    """`dev-all`: eğitim + geliştirme (final hariç, varsayılan); `all`: hepsi; aksi halde tek bölüm."""
    if split == "all":
        return list(tasks)
    if split == "dev-all":
        return [t for t in tasks if t.split in ("train", "dev")]
    if split not in SPLITS:
        raise ValueError(f"bilinmeyen split: {split}")
    return [t for t in tasks if t.split == split]


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


class RecordingModel:
    """Modelin yanıtlarını sırayla kaydeder (tekrar oynatma için). `usage` ve diğer alanlar alttaki istemciden gelir."""

    def __init__(self, inner: ModelClient):
        self._inner = inner
        self.replies: list[dict] = []

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def chat(self, messages, tools=None):
        reply = self._inner.chat(messages, tools)
        self.replies.append(
            {
                "content": reply.content,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls
                ],
            }
        )
        return reply


class ReplayModel:
    """Kaydedilmiş yanıtları aynen verir: harness/araç tarafını modelsiz yeniden çalıştırmak için."""

    def __init__(self, replies: list[dict]):
        self._replies = list(replies)
        self._n = 0
        self.usage = None

    def chat(self, messages, tools=None):
        from usta.models import ModelResponse, ToolCall

        if self._n >= len(self._replies):
            raise ModelError(
                "tekrar oynatma: kayıtlı yanıtlar bitti (harness kayıttan farklı ilerliyor)"
            )
        r = self._replies[self._n]
        self._n += 1
        return ModelResponse(
            r["content"], [ToolCall(c["id"], c["name"], c["arguments"]) for c in r["tool_calls"]]
        )


def _attempt(
    task: BenchTask,
    model: ModelClient,
    *,
    max_steps: int,
    time_limit: float,
    agent_factory: Callable[..., Agent],
    arm: Arm,
    trace_dir: Path | None = None,
    replay: list[dict] | None = None,
) -> TaskResult:
    t0 = time.monotonic()
    counts = {"tool_calls": 0, "tool_errors": 0, "denied": 0}
    gate_events: list[str] = []
    trips: list[bool] = []
    order: list[str] = []  # araç çağrılarının sırası: doğrulama, son düzenlemeden sonra mı?
    calls: list[tuple[str, str]] = []
    errors: list[str] = []
    events: list[dict] = []  # adım bazında iz: zaman, araç, sonuç, kaynak tüketimi
    stats = {"syntax": 0, "compactions": 0, "context_peak": 0}
    recorder = RecordingModel(model) if trace_dir is not None and replay is None else None
    active: ModelClient = ReplayModel(replay) if replay is not None else (recorder or model)
    usage = getattr(model, "usage", None)
    before = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)
    cascade = model if arm.cascade and hasattr(model, "observe") else None
    if cascade is not None:
        cascade.reset()
    strong_use = getattr(getattr(cascade, "strong", None), "usage", None)
    strong_before = strong_use.prompt + strong_use.completion if strong_use else 0

    def stamp(kind: str, **data) -> None:
        events.append({"t_ms": round((time.monotonic() - t0) * 1000), "kind": kind, **data})

    def on_event(kind: str, data: dict) -> None:
        if cascade is not None:
            cascade.observe(kind, data)
        if kind == "tool_call":
            counts["tool_calls"] += 1
            order.append(str(data.get("tool")))
            calls.append((str(data.get("tool")), taxonomy.summarize_args(data.get("args"))))
            stamp("tool_call", tool=data.get("tool"), args=calls[-1][1])
        elif kind == "breaker":
            trips.append(bool(data.get("final")))
            stamp(
                "breaker", reason=str(data.get("reason", ""))[:120], final=bool(data.get("final"))
            )
        elif kind == "verification":
            gate_events.append(str(data.get("status")))
            stamp("verification", status=data.get("status"))
        elif kind == "denied":
            counts["denied"] += 1
            stamp("denied", tool=data.get("tool"))
        elif kind == "tool_result":
            result = str(data.get("result", ""))
            if result.startswith("hata:"):
                counts["tool_errors"] += 1
                errors.append(result[:200])
            if "\nuyarı:" in result:  # düzenleme sonrası sözdizimi geri bildirimi
                stats["syntax"] += 1
            stamp(
                "tool_result",
                tool=data.get("tool"),
                ok=not result.startswith("hata:"),
                head=result[:100],
            )
        elif kind == "usage":
            stats["context_peak"] = max(stats["context_peak"], int(data.get("context") or 0))
            stamp(
                "usage",
                prompt=data.get("prompt"),
                completion=data.get("completion"),
                requests=data.get("requests"),
                context=data.get("context"),
            )
        elif kind == "compacted":
            stats["compactions"] += 1
            stamp("compacted", saved_chars=data.get("saved_chars"))

    cancel = threading.Event()
    timer = threading.Timer(time_limit, cancel.set)
    timer.daemon = True
    tracker = PhaseTracker()
    with tempfile.TemporaryDirectory(prefix="usta-bench-") as tmp:
        ws = Path(tmp) / "ws"
        shutil.copytree(task.repo, ws)
        registry = build_registry(
            ToolContext(
                root=ws,
                cancel=cancel,
                symbol_tools=arm.symbol_tools,
                **({"max_read": arm.max_read} if arm.max_read else {}),
            )
        )
        if arm.tools is not None:
            registry = registry.subset(arm.tools)
        agent = agent_factory(
            active,
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
            context_window=arm.context_window,
            phases=tracker,
            taint=arm.taint,
        )
        error, steps, truncated, infra, answer, timed_out = "", 0, False, False, "", False
        timer.start()
        try:
            result = agent.run(task.prompt)
            steps, truncated, answer = result.steps, result.truncated, result.answer
            if result.cancelled:
                error, timed_out = "zaman sınırı aşıldı", True
        except ModelError as e:
            error, infra = f"model hatası: {e}", e.infra
        finally:
            timer.cancel()
        modified = _tests_modified(task.repo, ws)
        passed, out = verify(task, ws)
        if not passed and verify_env_problem(
            out, ws
        ):  # gizli doğrulama ortamı sorunu: modelin başarısızlığı değil
            infra, error = True, f"doğrulama ortamı: {verify_env_problem(out, ws)}"
    edit_idx = [i for i, n in enumerate(order) if n in ("write_file", "edit_file")]
    run_idx = [i for i, n in enumerate(order) if n == "run"]
    gate_passed = bool(gate_events) and gate_events[-1] == "passed"
    verified = gate_passed or (bool(edit_idx) and bool(run_idx) and run_idx[-1] > edit_idx[-1])
    answered = not error and not truncated
    after = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)
    ok = passed and not error
    unverified = answered and bool(edit_idx) and not verified
    repairs = sum(1 for i in edit_idx if run_idx and i > run_idx[0])
    verdict = taxonomy.classify(
        taxonomy.Facts(
            passed=ok,
            infra=infra,
            timed_out=timed_out,
            model_error=bool(error) and not infra and not timed_out,
            truncated=truncated,
            tool_calls=counts["tool_calls"],
            edits=len(edit_idx),
            steps=steps,
            max_steps=max_steps,
            answer=answer,
            tool_errors=errors,
            calls=calls,
            gate_rounds=gate_events.count("failed"),
            breaker_trips=len(trips),
            compactions=stats["compactions"],
            context_peak=stats["context_peak"],
            context_window=arm.context_window or 0,
            syntax_warnings=stats["syntax"],
            tests_modified=modified,
            unverified_claim=unverified,
        )
    )
    res = TaskResult(
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
        unverified_claim=unverified,
        tests_modified=modified,
        gate=next((g for g in reversed(gate_events) if g != "nudge"), ""),
        gate_rounds=gate_events.count("failed"),
        breaker_trips=len(trips),
        blocked=bool(trips) and trips[-1],
        failure=verdict.primary,
        split=task.split,
        terminal=tracker.terminal
        or tracker.finish(
            answered=answered and not infra,
            truncated=truncated,
            cancelled=timed_out,
            error=bool(error) and not timed_out,
        ),
        phase_steps=dict(tracker.steps_in),
        phase_transitions=len(tracker.transitions),
        signals=tuple(verdict.signals),
        repair_attempts=repairs,
        context_peak=stats["context_peak"],
        compactions=stats["compactions"],
        escalated=bool(cascade and cascade.escalated),
        strong_tokens=(strong_use.prompt + strong_use.completion - strong_before)
        if strong_use
        else 0,
        **counts,
    )
    if trace_dir is not None and replay is None:
        res = replace(
            res, trace=_write_trace(trace_dir, task, arm, max_steps, res, events, recorder)
        )
    return res


def _write_trace(
    trace_dir: Path,
    task: BenchTask,
    arm: Arm,
    max_steps: int,
    res: TaskResult,
    events: list[dict],
    recorder: RecordingModel | None,
) -> str:
    """Adım izi + model yanıtları (tekrar oynatma için). Sırlar maskelenir."""
    from usta.audit import mask_deep

    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(trace_dir.glob(f"{task.id}.*.json"))) + 1
    path = trace_dir / f"{task.id}.{n}.json"
    doc = mask_deep(
        {
            "version": TRACE_VERSION,
            "task": task.id,
            "split": task.split,
            "arm": arm.name,
            "max_steps": max_steps,
            "result": asdict(res),
            "events": events,
            "replies": recorder.replies if recorder else [],
        }
    )
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return path.name


def replay_trace(path: Path, *, tasks: list[BenchTask] | None = None) -> tuple[TaskResult, dict]:
    """Kaydı modelsiz yeniden oynatır; (yeni sonuç, özgün sonuç). Harness/araç tarafı kararlıysa aynı çıkar."""
    doc = json.loads(Path(path).read_text())
    if doc.get("version") != TRACE_VERSION or not doc.get("replies"):
        raise ValueError(f"{path}: yeniden oynatılabilir iz değil")
    pool = tasks or load_tasks()
    task = next((t for t in pool if t.id == doc["task"]), None)
    if task is None:
        raise ValueError(f"görev yok: {doc['task']}")
    arm = ARMS[doc["arm"]]
    r = _attempt(
        task,
        ReplayModel(doc["replies"]),
        max_steps=int(doc["max_steps"]),
        time_limit=600.0,
        agent_factory=Agent,
        arm=arm,
        replay=doc["replies"],
    )
    return r, doc["result"]


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
    trace_dir: Path | None = None,
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
            trace_dir=trace_dir,
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
        "infra_error_rate": round((len(results) - n) / len(results), 3) if results else 0.0,
        "failures": dict(Counter(r.failure for r in valid if not r.passed and r.failure)),
        "signals": dict(Counter(sig for r in valid for sig in r.signals)),
        "mean_tool_calls": round(statistics.fmean(r.tool_calls for r in valid), 2) if n else 0.0,
        "mean_repairs": round(statistics.fmean(r.repair_attempts for r in valid), 2) if n else 0.0,
        "mean_requests": round(statistics.fmean(r.requests for r in valid), 2) if n else 0.0,
        "context_peak_max": max((r.context_peak for r in valid), default=0),
        "compactions": sum(r.compactions for r in valid),
        "gate_rounds": sum(r.gate_rounds for r in valid),
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
    trace_dir: Path | None = None,
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
                trace_dir=trace_dir,
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


def _results(rep: dict) -> list[TaskResult]:
    return [
        TaskResult(**{k: v for k, v in r.items() if k in TaskResult.__dataclass_fields__})
        for r in rep["results"]
    ]


def paired(a: list[TaskResult], b: list[TaskResult]) -> dict:
    """Aynı görev + aynı tekrar sırası eşleştirilir; yalnız iki tarafı da geçerli (altyapı hatasız) çiftler sayılır."""

    def keyed(rs: list[TaskResult]) -> dict[tuple[str, int], TaskResult]:
        seen: Counter[str] = Counter()
        out = {}
        for r in rs:
            seen[r.task] += 1
            out[(r.task, seen[r.task])] = r
        return out

    ka, kb = keyed(a), keyed(b)
    both = a_only = b_only = neither = 0
    for key in sorted(ka.keys() & kb.keys()):
        x, y = ka[key], kb[key]
        if x.outcome == "infra" or y.outcome == "infra":
            continue
        if x.passed and y.passed:
            both += 1
        elif x.passed:
            a_only += 1
        elif y.passed:
            b_only += 1
        else:
            neither += 1
    return {
        "pairs": both + a_only + b_only + neither,
        "both": both,
        "a_only": a_only,
        "b_only": b_only,
        "neither": neither,
    }


def paired_verdict(p: dict, a: str, b: str) -> str:
    """Yön + belirsizlik. Küçük örneklemde anlamlılık İDDİA EDİLMEZ."""
    d = p["a_only"] + p["b_only"]
    if p["pairs"] == 0:
        return "eşleşen çift yok"
    if d == 0:
        return "tüm çiftlerde aynı sonuç (fark gözlenmedi)"
    lo, hi = wilson(p["b_only"], d)
    lean = b if p["b_only"] > p["a_only"] else a if p["a_only"] > p["b_only"] else None
    if lean is None:
        return f"yön yok ({d} uyuşmayan çift eşit bölündü)"
    note = (
        "örneklem çok küçük; yalnız yön"
        if d < 10
        else "aralık 0,5'i içeriyor: belirsiz"
        if lo <= 0.5 <= hi
        else "aralık 0,5'i dışlıyor"
    )
    return f"yön {lean} lehine ({d} uyuşmayan çift); {note}"


def compare_markdown(tiers: dict[str, list[Path]]) -> str:
    """Katman (zayıf/orta/büyük) başına kol karşılaştırma tablosu, güven aralığı, eşleştirilmiş analiz, hata nedenleri."""
    lines = ["# USTA Bench karşılaştırması", ""]
    for tier, paths in tiers.items():
        reports = [load_report(p) for p in paths]
        lines += [f"## {tier}", ""]
        header = (
            "| Model | Kol | Geçen | %95 aralık | Token/görev | Çözülen başına token | Süre (sn) "
            "| Araç çağrısı | Onarım | Kanıtsız | 'Bitti' deyip kalan | Altyapı hatası |"
        )
        lines += [header, "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        ci: dict[tuple[str, str], tuple[float, float, float]] = {}
        by_model: dict[str, dict[str, list[TaskResult]]] = {}
        fails: list[tuple[str, str, dict]] = []
        for rep in sorted(reports, key=lambda r: (r["model"], r["arm"])):
            rs = _results(rep)
            s = summarize(rs)
            lo, hi = wilson(s["passed"], s["valid_runs"])
            ci[(rep["model"], rep["arm"])] = (s["pass_rate"], lo, hi)
            by_model.setdefault(rep["model"], {})[rep["arm"]] = rs
            fails.append((rep["model"], rep["arm"], s))
            solved = s["tokens_per_solved"]
            lines.append(
                f"| {rep['model']} | {rep['arm']} | {s['passed']}/{s['valid_runs']} (%{s['pass_rate'] * 100:.0f}) "
                f"| %{lo * 100:.0f}-%{hi * 100:.0f} | {s['mean_tokens']:g} | {solved if solved is not None else '-'} "
                f"| {s['mean_seconds']:g} | {s['mean_tool_calls']:g} | {s['mean_repairs']:g} | {s['unverified_claims']} "
                f"| {s['claimed_but_failed']} | {s['infra_errors']}/{s['runs']} (%{s['infra_error_rate'] * 100:.0f}) |"
            )
        lines += ["", *_verdicts(ci), ""]
        lines += ["**Başarısızlık nedenleri** (geçerli, başarısız koşular):", ""]
        for model, arm, s in fails:
            dist = (
                ", ".join(
                    f"{k} {v}" for k, v in sorted(s["failures"].items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            lines.append(f"- {model} / {arm}: {dist}")
        lines.append("")
        for model, arms in by_model.items():
            base = arms.get("B")
            others = [a for a in arms if a != "B"]
            if base is None or not others:
                continue
            lines += [
                f"**Eşleştirilmiş karşılaştırma — {model}** (B ile; aynı görev + tekrar sırası):",
                "",
            ]
            lines += [
                "| Kol | Çift | İkisi geçti | Yalnız B | Yalnız kol | İkisi kaldı | Yorum |",
                "|---|---|---|---|---|---|---|",
            ]
            for arm in others:
                pr = paired(base, arms[arm])
                lines.append(
                    f"| {arm} | {pr['pairs']} | {pr['both']} | {pr['a_only']} | {pr['b_only']} | {pr['neither']} "
                    f"| {paired_verdict(pr, 'B', arm)} |"
                )
            lines.append("")
    lines += [
        (
            "> Küçük örneklemde istatistiksel anlamlılık iddia edilmez: aralıklar örtüşüyorsa ya da uyuşmayan çift azsa "
            "fark kanıtlanmış sayılmaz. Altyapı hataları başarısızlık sayılmadı; sayıları ve oranları tabloda ayrıca verilir."
        ),
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def regress_markdown(old_path: Path, new_path: Path) -> str:
    """Önceki sürümün raporuna göre regresyonlar: görev bazında geçme farkı, maliyet farkı, neden kayması."""
    old, new = load_report(old_path), load_report(new_path)
    ro, rn = _results(old), _results(new)
    so, sn = summarize(ro), summarize(rn)
    lines = [
        "# USTA Bench regresyon raporu",
        "",
        f"- Önceki: `{Path(old_path).name}` ({old['model']}, kol {old['arm']}, protokol {old.get('protocol', '?')})",
        f"- Yeni: `{Path(new_path).name}` ({new['model']}, kol {new['arm']}, protokol {new.get('protocol', '?')})",
    ]
    for key, label in (("model", "model"), ("arm", "kol"), ("protocol", "protokol")):
        if old.get(key) != new.get(key):
            lines.append(
                f"- UYARI: {label} farklı ({old.get(key)} → {new.get(key)}); fark harness değişikliğinden gelmeyebilir."
            )
    if {r.task for r in ro} != {r.task for r in rn}:
        lines.append("- UYARI: görev kümeleri farklı; yalnız ortak görevler karşılaştırıldı.")
    lines += ["", "| Metrik | Önceki | Yeni | Fark |", "|---|---|---|---|"]
    for label, key, fmt in (
        ("Geçen", "passed", "{:g}"),
        ("Geçerli koşu", "valid_runs", "{:g}"),
        ("Altyapı hatası", "infra_errors", "{:g}"),
        ("Token/görev", "mean_tokens", "{:g}"),
        ("Süre (sn)", "mean_seconds", "{:g}"),
        ("Araç çağrısı", "mean_tool_calls", "{:g}"),
        ("Onarım", "mean_repairs", "{:g}"),
    ):
        a, b_ = so[key], sn[key]
        lines.append(f"| {label} | {fmt.format(a)} | {fmt.format(b_)} | {b_ - a:+g} |")
    common = sorted({r.task for r in ro} & {r.task for r in rn})
    reg, imp = [], []
    for t in common:
        po = [r for r in ro if r.task == t and r.outcome != "infra"]
        pn = [r for r in rn if r.task == t and r.outcome != "infra"]
        if not po or not pn:
            continue
        ao, an = sum(r.passed for r in po) / len(po), sum(r.passed for r in pn) / len(pn)
        row = (
            f"- {t}: {sum(r.passed for r in po)}/{len(po)} → {sum(r.passed for r in pn)}/{len(pn)}"
        )
        if an < ao:
            reg.append(row)
        elif an > ao:
            imp.append(row)
    lines += [
        "",
        f"**Regresyonlar ({len(reg)})**",
        "",
        *(reg or ["- yok"]),
        "",
        f"**İyileşmeler ({len(imp)})**",
        "",
        *(imp or ["- yok"]),
    ]
    cats = sorted(set(so["failures"]) | set(sn["failures"]))
    if cats:
        lines += [
            "",
            "**Başarısızlık nedeni kayması**",
            "",
            "| Neden | Önceki | Yeni |",
            "|---|---|---|",
        ]
        lines += [
            f"| {c} | {so['failures'].get(c, 0)} | {sn['failures'].get(c, 0)} |" for c in cats
        ]
    lines += [
        "",
        "> Küçük örneklemde fark kanıtlanmış sayılmaz; gerçek bir regresyonu doğrulamak için aynı görevleri daha çok tekrarla.",
    ]
    return "\n".join(lines) + "\n"


def diagnose_markdown(paths: list[Path]) -> str:
    """Başarısızlık nedenleri dağılımı, görev başına maliyet ve harness yükü: `neden başarısız?` sorusunun tablosu."""
    lines = ["# USTA Bench teşhisi", ""]
    for path in paths:
        rep = load_report(path)
        rs = _results(rep)
        s = summarize(rs)
        lines += [
            f"## {rep['model']} — kol {rep['arm']} (`{Path(path).name}`)",
            "",
            (
                f"- Koşu {s['runs']} (geçerli {s['valid_runs']}, altyapı {s['infra_errors']} = "
                f"%{s['infra_error_rate'] * 100:.0f}); geçen {s['passed']}/{s['valid_runs']}"
            ),
            (
                f"- Ortalama: {s['mean_tool_calls']:g} araç çağrısı, {s['mean_requests']:g} istek, "
                f"{s['mean_repairs']:g} onarım denemesi, {s['mean_tokens']:g} token, {s['mean_seconds']:g} sn; "
                f"en büyük bağlam {s['context_peak_max']}; sıkıştırma {s['compactions']}; "
                f"kapı turu {s['gate_rounds']}; devre kesici {s['breaker_trips']}"
            ),
            "",
            "| Neden | Koşu | Pay |",
            "|---|---|---|",
        ]
        bad = sum(s["failures"].values())
        for k, v in sorted(s["failures"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v} | %{v / bad * 100:.0f} |")
        if not bad:
            lines.append("| (başarısız koşu yok) | 0 | — |")
        sig = (
            ", ".join(f"{k} {v}" for k, v in sorted(s["signals"].items(), key=lambda kv: -kv[1]))
            or "—"
        )
        lines += ["", f"İşaretler (tüm koşular, birincil neden dışındakiler dahil): {sig}", ""]
        lines += [
            "| Görev | Bölüm | Sonuç | Neden | Çağrı | Onarım | Token | Süre |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in rs:
            res = "GEÇTİ" if r.passed else "ALTYAPI" if r.outcome == "infra" else "KALDI"
            lines.append(
                f"| {r.task} | {r.split or '-'} | {res} | {r.failure or '-'} | {r.tool_calls} | {r.repair_attempts} "
                f"| {r.prompt_tokens + r.completion_tokens} | {r.seconds:g} |"
            )
        lines.append("")
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
