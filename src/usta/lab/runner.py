"""Deney çalıştırıcı: eşleştirilmiş (temiz/saldırılı) koşular, iz kaydı, kalıcı deney kaydı.

Ajan döngüsü DEĞİŞTİRİLMEZ: gerçek `Agent`, gerçek izin motoru ve gerçek dosya araçları kullanılır; Lab yalnız
olayları gözler ve sonucu değerlendirir. Aynı senaryonun iki koşulunda model, istem, izinler ve bütçe aynıdır.
"""

from __future__ import annotations

import json
import platform
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from usta.agent import Agent
from usta.audit import AuditLog, mask_deep
from usta.breaker import CircuitBreaker
from usta.lab import env as labenv
from usta.lab import evaluator, scenario
from usta.models import ModelClient, ModelError

SCHEMA = 1


def _usta_version() -> str:
    try:
        return version("usta")
    except PackageNotFoundError:
        return "dev"


@dataclass(frozen=True)
class HarnessConfig:
    """Deneyde sabitlenen harness ayarları (karşılaştırma adil kalsın diye kayda geçer)."""

    id: str = "base"
    breaker: bool = False
    protocol: str = "native"
    approver: str = "deny"  # ölçümde insan yok: onay isteyen eylemler reddedilir

    def label(self) -> str:
        return self.id


def _git_sha() -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(Path(__file__).parent), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def experiment_meta(
    scenarios: list[scenario.Scenario],
    *,
    model: str,
    model_revision: str,
    endpoint: str,
    harness: HarnessConfig,
    repeat: int,
    note: str = "",
) -> dict:
    return {
        "schema": SCHEMA,
        "experiment_id": time.strftime("exp-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "usta_version": _usta_version(),
        "usta_git": _git_sha(),
        "python": platform.python_version(),
        "model": model,
        "model_revision": model_revision,
        "endpoint": endpoint,  # anahtar yok; yalnız adres
        "harness_config": asdict(harness),
        "scenario_set": scenario.set_hash(scenarios),
        "scenarios": len(scenarios),
        "repeat": repeat,
        "note": note,
    }


def run_one(
    sc: scenario.Scenario,
    condition: str,
    model: ModelClient,
    *,
    meta: dict,
    repeat: int,
    harness: HarnessConfig,
    out_dir: Path | None = None,
    time_limit: float = 300.0,
) -> dict:
    run_id = f"{sc.id}.{condition}.{repeat}"
    usage = getattr(model, "usage", None)
    before = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)
    cancel = threading.Event()
    timer = threading.Timer(time_limit, cancel.set)
    timer.daemon = True
    status, error, infra, answer, steps = "COMPLETED", "", False, "", 0
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="usta-lab-") as tmp:
        env = labenv.build(sc, condition, Path(tmp) / "ws")
        agent = Agent(
            model,
            env.registry,
            env.policy,
            AuditLog(Path(tmp) / "audit.jsonl"),
            approver=lambda *_: False,
            max_steps=sc.max_steps,
            on_event=env.on_event,
            cancel=cancel,
            breaker=CircuitBreaker(env.root) if harness.breaker else None,
        )
        timer.start()
        try:
            result = agent.run(sc.task)
            answer, steps = result.answer, result.steps
            if result.cancelled:
                status, error = "ERROR", "zaman sınırı aşıldı"
            elif result.truncated:
                status = "TRUNCATED"
        except ModelError as e:
            status, error, infra = "INFRA" if e.infra else "ERROR", f"model hatası: {e}", e.infra
        finally:
            timer.cancel()
        outcome = evaluator.evaluate(env, answer)
        calls = [asdict(c) for c in env.calls]
        fault_hit = env.fault_hits > 0
    after = (usage.prompt, usage.completion, usage.requests) if usage else (0, 0, 0)
    if status == "COMPLETED" and not outcome.task_success:
        status = "FAILED"
    category = None
    if status != "COMPLETED":
        category = (
            "INFRA_ERROR"
            if infra
            else "MODEL_ERROR"
            if status == "ERROR"
            else "STEP_LIMIT"
            if status == "TRUNCATED"
            else "FALSE_REFUSAL"
            if outcome.false_refusal
            else "NO_TOOL_CALLS"
            if not calls
            else "TASK_INCOMPLETE"
        )
    rec = {
        "run_id": run_id,
        "experiment_id": meta["experiment_id"],
        "scenario_id": sc.id,
        "scenario_version": sc.version,
        "category": sc.category,
        "surface": sc.surface,
        "condition": condition,
        "repeat": repeat,
        "model": meta["model"],
        "model_revision": meta["model_revision"],
        "harness_config": harness.label(),
        "task_status": status,
        "failure_category": category,
        "task_success": outcome.task_success,
        "attack_attempted": condition == "attack" and outcome.unauthorized_attempted,
        "attack_succeeded": condition == "attack" and outcome.goal_achieved,
        "unauthorized_action_attempted": outcome.unauthorized_attempted,
        "unauthorized_action_executed": outcome.unauthorized_executed,
        "blocked_attempts": len(outcome.blocked),
        "false_refusal": outcome.false_refusal,
        "fault_triggered": fault_hit,
        "tool_calls": len(calls),
        "steps": steps,
        "input_tokens": after[0] - before[0],
        "output_tokens": after[1] - before[1],
        "requests": after[2] - before[2],
        "duration_ms": round((time.monotonic() - t0) * 1000),
        "infra": infra,
        "error": error,
        "detail": outcome.detail,
        "artifact_refs": [f"traces/{run_id}.json"],
    }
    trace = mask_deep(
        {"run_id": run_id, "answer": answer[:2000], "calls": calls, "detail": outcome.detail}
    )
    if out_dir is not None:
        d = Path(out_dir) / "traces"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{run_id}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1))
    rec["_trace"] = trace
    return rec


def run_experiment(
    scenarios: list[scenario.Scenario],
    model_factory: Callable[[scenario.Scenario, str], ModelClient],
    *,
    meta: dict,
    harness: HarnessConfig,
    repeat: int = 1,
    out_dir: Path | None = None,
    time_limit: float = 300.0,
    on_record: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Her senaryo × koşul × tekrar için bir kayıt. Kayıtlar `runs.jsonl`'a anında eklenir (kesilirse kaybolmaz)."""
    records: list[dict] = []
    runs_file = None
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "experiment.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        runs_file = Path(out_dir) / "runs.jsonl"
    for rep in range(1, repeat + 1):
        for sc in scenarios:
            for cond in sc.conditions:
                rec = run_one(
                    sc,
                    cond,
                    model_factory(sc, cond),
                    meta=meta,
                    repeat=rep,
                    harness=harness,
                    out_dir=out_dir,
                    time_limit=time_limit,
                )
                rec.pop("_trace", None)
                records.append(rec)
                if runs_file is not None:
                    with runs_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if on_record:
                    on_record(rec)
    return records
