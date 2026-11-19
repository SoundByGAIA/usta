"""Komut satırı: ölçüm komutları (usta lab, usta bench, usta probe, usta verify)."""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from pathlib import Path

from usta import bench, bench_report, capability, cli, profile, projectcfg, settings
from usta.agent import Agent
from usta.cascade import CascadeModel


def bench_compare(args: argparse.Namespace) -> int:
    tiers: dict[str, list[Path]] = {}
    for pair in args.pairs:
        tier, sep, path = pair.partition("=")
        if not sep or not tier.strip() or not path.strip():
            print(f"hata: KATMAN=RAPOR.json biçimi bekleniyor: {pair!r}", file=sys.stderr)
            return 2
        tiers.setdefault(tier.strip(), []).append(Path(path.strip()))
    try:
        md = bench_report.compare_markdown(tiers)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"hata: rapor okunamadı: {e}", file=sys.stderr)
        return 2
    print(md, end="")
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    return 0


def lab_cmd(args: argparse.Namespace) -> int:
    from usta.lab import report as labreport
    from usta.lab import runner as labrunner
    from usta.lab import scenario as labscenario
    from usta.lab.metrics import summarize as lab_summarize
    from usta.lab.scripted import BEHAVIORS, ScriptedModel

    try:
        if args.lab_cmd == "report":
            labreport.write(Path(args.dir))
            print(f"Rapor: {Path(args.dir) / 'report.md'}")
            return 0
        if args.lab_cmd == "compare":
            print(labreport.compare(Path(args.a), Path(args.b)))
            return 0
        path = Path(args.file) if getattr(args, "file", None) else None
        scenarios = labscenario.load(path)
    except (labscenario.ScenarioError, OSError, ValueError, KeyError) as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    if args.lab_cmd == "validate":
        print(
            f"{len(scenarios)} senaryo geçerli; küme özeti {labscenario.set_hash(scenarios)[:19]}…"
        )
        return 0
    if args.lab_cmd == "list":
        for s in scenarios:
            print(f"{s.id:14} {s.category:22} {s.surface}")
        return 0
    harness = labrunner.HarnessConfig(
        id=getattr(args, "harness_id", "base"), breaker=getattr(args, "breaker", False)
    )
    if args.lab_cmd == "smoke":
        bad = 0
        for beh in BEHAVIORS:
            meta = labrunner.experiment_meta(
                scenarios,
                model=f"scripted-{beh}",
                model_revision="",
                endpoint="-",
                harness=harness,
                repeat=1,
            )
            out = Path(args.out) / beh if args.out else None
            recs = labrunner.run_experiment(
                scenarios,
                lambda s, c, b=beh: ScriptedModel(s, c, b),
                meta=meta,
                harness=harness,
                out_dir=out,
            )
            sm = lab_summarize(recs)
            if out:
                labreport.write(out)
            print(
                f"{beh:10} TSR {sm['task_success_rate']['rate']}  ASR {sm['asr']['rate']}  "
                f"deneme {sm['unauthorized_attempt_rate']['rate']}  gerçekleşme {sm['unauthorized_execution_rate']['rate']}  "
                f"yanlış ret {sm['false_refusal_rate']['rate']}  toparlanma {sm['recovery_rate']['rate']}"
            )
            if beh == "gullible":  # izin katmanı beklentileri (senaryodaki `expect`)
                exp = {s.id: s.expect for s in scenarios}
                for r in recs:
                    e = exp[r["scenario_id"]]
                    if (
                        r["condition"] == "attack"
                        and e
                        and (
                            r["attack_attempted"],
                            r["unauthorized_action_executed"],
                            r["blocked_attempts"] > 0,
                        )
                        != (e["attempt"], e["executed"], e["blocked"])
                    ):
                        print(f"  BEKLENTİ TUTMADI: {r['scenario_id']}", file=sys.stderr)
                        bad += 1
        return 1 if bad else 0
    # run
    if args.scenario:
        unknown = sorted(set(args.scenario) - {s.id for s in scenarios})
        if unknown:
            print(f"hata: bilinmeyen senaryo: {', '.join(unknown)}", file=sys.stderr)
            return 2
        scenarios = [s for s in scenarios if s.id in args.scenario]
    if args.category:
        scenarios = [s for s in scenarios if s.category in args.category]
    if not scenarios:
        print("hata: çalıştırılacak senaryo yok", file=sys.stderr)
        return 2
    model = cli._make_model(args)
    if model is None:
        return 2
    if args.strong_model:
        # Lab'da takılma işareti söz–eylem hatırlatmasıdır (bitirme kapısı yok). Boş el işareti kapalı: yanıtı
        # okuyarak veren görevlerde ucuz modelin doğru yanıtını atar
        model = CascadeModel(model, cli._strong_model(args), on_nudge=True, empty_handed=False)
    base_name = name = args.model or os.environ.get("USTA_MODEL") or "?"
    if args.strong_model:
        name = f"{name}→{args.strong_model}"
    endpoint = args.endpoint or os.environ.get("USTA_ENDPOINT") or cli.DEFAULT_ENDPOINT
    harness = labrunner.HarnessConfig(
        id=args.harness_id,
        breaker=args.breaker,
        finish_check=cli._finish_check(args),
        taint=cli._taint_gate(args),
        protocol=args.protocol or os.environ.get("USTA_PROTOCOL") or "native",
    )
    rev = args.model_revision or capability.detect_revision(endpoint, base_name)
    meta = labrunner.experiment_meta(
        scenarios,
        model=name,
        model_revision=rev,
        endpoint=endpoint,
        harness=harness,
        repeat=args.repeat,
        note=args.note,
    )
    print(
        f"Lab: {name} ({harness.protocol}); {len(scenarios)} senaryo x {args.repeat}; deney {meta['experiment_id']}",
        flush=True,
    )

    def show(r: dict) -> None:
        mark = "GEÇTİ " if r["task_success"] else "KALDI "
        extra = f"  [{'; '.join(r['detail'])}]" if r["detail"] else ""
        print(
            f"{mark} {r['scenario_id']}/{r['condition']}: {r['tool_calls']} çağrı, {r['duration_ms']} ms{extra}",
            flush=True,
        )

    recs = labrunner.run_experiment(
        scenarios,
        lambda s, c: model,
        meta=meta,
        harness=harness,
        repeat=args.repeat,
        out_dir=Path(args.out),
        time_limit=args.time_limit,
        on_record=show,
    )
    labreport.write(Path(args.out))
    sm = lab_summarize(recs)
    print(
        f"TSR {sm['task_success_rate']['rate']}  ASR {sm['asr']['rate']}  deneme {sm['unauthorized_attempt_rate']['rate']}  "
        f"gerçekleşme {sm['unauthorized_execution_rate']['rate']}  yanlış ret {sm['false_refusal_rate']['rate']}  "
        f"altyapı hatası {sm['infra_errors']}\nRapor: {Path(args.out) / 'report.md'}"
    )
    return 0


def bench_cmd(args: argparse.Namespace) -> int:
    if args.bench_cmd == "compare":
        return bench_compare(args)
    tasks = bench.load_tasks()
    if args.bench_cmd == "list":
        for t in tasks:
            print(f"{t.id} [{t.split}]: {t.prompt[:90]}")
        return 0
    if args.bench_cmd == "splits":
        for sp in bench.SPLITS:
            print(f"{sp}: {', '.join(t.id for t in tasks if t.split == sp)}")
        return 0
    if args.bench_cmd == "replay":
        try:
            new, old = bench.replay_trace(Path(args.trace), tasks=tasks)
        except (OSError, ValueError, KeyError) as e:
            print(f"hata: {e}", file=sys.stderr)
            return 2
        same = new.passed == old["passed"]
        print(
            f"{new.task}: yeniden oynatma {'GEÇTİ' if new.passed else 'KALDI'} (kayıtta: {'GEÇTİ' if old['passed'] else 'KALDI'}); "
            f"{new.tool_calls} araç çağrısı; nedeni: {new.failure or '-'}\n"
            f"{'Sonuç kayıtla AYNI.' if same else 'UYARI: sonuç kayıttan FARKLI (harness/araç davranışı değişmiş).'}"
        )
        return 0 if same else 1
    if args.bench_cmd == "regress":
        try:
            print(bench_report.regress_markdown(Path(args.old), Path(args.new)))
        except (OSError, ValueError, KeyError) as e:
            print(f"hata: {e}", file=sys.stderr)
            return 2
        return 0
    if args.bench_cmd == "diagnose":
        try:
            print(bench_report.diagnose_markdown([Path(p) for p in args.reports]))
        except (OSError, ValueError, KeyError) as e:
            print(f"hata: {e}", file=sys.stderr)
            return 2
        return 0
    tasks = bench.select_tasks(tasks, args.split)
    if args.split in ("final", "all"):
        print(
            "uyarı: final bölümü yalnız sürüm ölçümü içindir; harness'ı bu görevlere bakarak AYARLAMA.",
            file=sys.stderr,
        )
    if args.task:
        unknown = sorted(set(args.task) - {t.id for t in tasks})
        if unknown:
            print(
                f"hata: bilinmeyen görev: {', '.join(unknown)} (liste: usta bench list)",
                file=sys.stderr,
            )
            return 2
        tasks = [t for t in tasks if t.id in args.task]
    model = cli._make_model(args)
    if model is None:
        return 2
    if bench.ARMS[args.arm].cascade:
        if not args.strong_model:
            print("hata: X-CASCADE kolu için --strong-model gerekir", file=sys.stderr)
            return 2
        model = CascadeModel(model, cli._strong_model(args))
    name = args.model or os.environ.get("USTA_MODEL") or "?"
    protocol = args.protocol or os.environ.get("USTA_PROTOCOL") or "native"
    print(
        f"Model: {name} ({protocol}); kol {args.arm}: {bench.ARMS[args.arm].description}; "
        f"{len(tasks)} görev x {args.repeat}",
        flush=True,
    )

    def show(r: bench.TaskResult) -> None:
        mark = {"pass": "GEÇTİ ", "fail": "KALDI ", "infra": "ALTYAPI"}[r.outcome]
        extra = f"  [{r.error}]" if r.error else "  [adım sınırı]" if r.truncated else ""
        flags = ("  !kanıtsız" if r.unverified_claim else "") + (
            "  !test-değişti" if r.tests_modified else ""
        )
        print(
            f"{mark} {r.task}: {r.steps} adım, {r.tool_calls} çağrı ({r.tool_errors} hata), "
            f"{r.prompt_tokens + r.completion_tokens} token, {r.seconds:g} sn{extra}{flags}"
            + (f"  ↑güçlü({r.strong_tokens} token)" if r.escalated else ""),
            flush=True,
        )

    results = bench.run_bench(
        lambda: model,
        tasks,
        repeat=args.repeat,
        max_steps=args.max_steps,
        time_limit=args.time_limit,
        infra_retries=args.infra_retries,
        arm=bench.ARMS[args.arm],
        agent_factory=functools.partial(Agent, shrink_writes=args.shrink_writes),
        on_result=show,
        should_stop=(lambda: Path(args.stop_file).exists()) if args.stop_file else None,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
    )
    if args.stop_file and Path(args.stop_file).exists():
        print(f"\nÖlçüm durduruldu ({args.stop_file} bulundu); {len(results)} koşu tamamlandı.")
    s = bench.summarize(results)
    solved = s["tokens_per_solved"]
    print(
        f"\nSonuç: {s['passed']}/{s['valid_runs']} geçti (%{s['pass_rate'] * 100:.0f}); "
        f"altyapı hatası (sayılmadı): {s['infra_errors']}\n"
        f"ort. {s['mean_steps']} adım, {s['mean_seconds']} sn, {s['mean_tokens']:g} token/görev, "
        f"çözülen başına {solved if solved is not None else '-'} token\n"
        f"araç hata oranı %{s['tool_error_rate'] * 100:.0f}, kanıtsız bildirim {s['unverified_claims']}, "
        f"'bitti' deyip kalan {s['claimed_but_failed']}, test dosyası değiştiren {s['tests_modified']}"
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                bench.report(name, protocol, results, args.arm), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        print(f"Rapor: {args.out}")
    return 0


def verify_cmd(args: argparse.Namespace, command: list[str]) -> int:
    home, root = cli._home(), Path(args.workspace)
    if not root.is_dir():
        print(f"hata: çalışma alanı yok: {root}", file=sys.stderr)
        return 2
    try:
        if args.verify_cmd == "set":
            if not command:
                print("hata: komut eksik. Örnek: usta verify set -- pytest -q", file=sys.stderr)
                return 2
            projectcfg.set_verify(home, root, command, args.image)
            print(
                f"Doğrulama komutu ayarlandı: {' '.join(command)}"
                + (f" (imaj: {args.image})" if args.image else "")
            )
        elif args.verify_cmd == "clear":
            projectcfg.clear(home, root)
            print("Doğrulama ayarı silindi; otomatik keşif kullanılacak.")
        else:
            cfg = projectcfg.load(home, root)
            if cfg.verify:
                print(
                    f"komut: {' '.join(cfg.verify)}" + (f"\nimaj: {cfg.image}" if cfg.image else "")
                )
            else:
                print(
                    "Ayarlı komut yok; otomatik keşif kullanılır (test_*.py → python -m unittest)."
                )
    except projectcfg.ProjectConfigError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    return 0


def _probe_deep(args: argparse.Namespace, home: Path, endpoint: str, name: str) -> int:
    extra = cli._extra_body(args)
    if extra is None:
        return 2
    config = cli._capability_config(args, extra)
    revision = capability.detect_revision(endpoint, name)
    cached = None if args.refresh else capability.load(home, endpoint, name, revision, config)
    if cached is not None:
        print(capability.table(cached))
        return 0
    long_chars = args.long_chars
    if config["context_window"]:  # pencereyi aşmayacak bir uzunluk (≈3 karakter/token, yarısı)
        long_chars = min(long_chars, int(config["context_window"] * 3 * 0.5))
    print(
        f"{name}: derin yetenek profili çıkarılıyor (protokol başına 8 sonda × {args.probe_repeats} tekrar)…",
        flush=True,
    )
    try:
        prof = capability.profile_model(
            lambda: cli._build_model(endpoint, name, "native", args.model_timeout, extra),
            name,
            endpoint=endpoint,
            revision=revision,
            config=config,
            long_chars=long_chars,
            repeats=max(1, args.probe_repeats),
        )
    except capability.CapabilityError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    capability.save(home, prof)
    print(capability.table(prof))
    return 0


def probe_cmd(args: argparse.Namespace) -> int:
    home = cli._home()
    cur = settings.load(home)
    endpoint = (
        args.endpoint or os.environ.get("USTA_ENDPOINT") or cur.endpoint or cli.DEFAULT_ENDPOINT
    )
    name = args.model or os.environ.get("USTA_MODEL") or cur.model
    if not name:
        print("hata: model belirtilmedi (--model veya USTA_MODEL)", file=sys.stderr)
        return 2
    make = lambda: cli._build_model(endpoint, name, "native", args.model_timeout)
    if args.deep:
        return _probe_deep(args, home, endpoint, name)
    try:
        if args.refresh:
            prof = profile.probe(make(), name)
            profile.save(home, endpoint, name, prof)
        else:
            prof = profile.resolve_protocol(home, endpoint, name, make)
    except profile.ProfileError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 2
    print(f"{name}: protokol {prof.protocol} — {prof.note}")
    return 0
