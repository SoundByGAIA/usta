"""Rapor üretici: JSON + Markdown; iki deney arasında regresyon karşılaştırması."""

from __future__ import annotations

import json
from pathlib import Path

from usta.lab.metrics import summarize

PAIRS = (
    ("task_success_rate", "Meşru görev başarısı (TSR)", True),
    ("task_success_under_attack", "Saldırı altında görev başarısı", True),
    ("asr", "Saldırı başarı oranı (ASR)", False),
    ("unauthorized_attempt_rate", "Yetkisiz eylem denemesi", False),
    ("unauthorized_execution_rate", "Yetkisiz eylem gerçekleşmesi", False),
    ("false_refusal_rate", "Yanlış ret", False),
    ("recovery_rate", "Hata sonrası toparlanma", True),
)


def load(out_dir: Path) -> tuple[dict, list[dict]]:
    out_dir = Path(out_dir)
    meta = json.loads((out_dir / "experiment.json").read_text())
    recs = [
        json.loads(line)
        for line in (out_dir / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return meta, recs


def _fmt(m: dict) -> str:
    if not m["n"]:
        return "—"
    lo, hi = m["ci95"]
    return f"{m['k']}/{m['n']} (%{m['rate'] * 100:.0f}; %95 aralık %{lo * 100:.0f}–%{hi * 100:.0f})"


def markdown(meta: dict, records: list[dict], summary: dict | None = None) -> str:
    s = summary or summarize(records)
    h = meta["harness_config"]
    lines = [
        f"# USTA Reliability Lab raporu — {meta['experiment_id']}",
        "",
        f"- Model: `{meta['model']}` (revizyon: `{meta['model_revision'] or 'bilinmiyor'}`), uç nokta: `{meta['endpoint']}`",
        f"- Harness: `{h['id']}` (devre kesici: {'açık' if h['breaker'] else 'kapalı'}, protokol: {h['protocol']}, onaycı: {h['approver']})",
        f"- Usta {meta['usta_version']} (`{meta['usta_git'] or '-'}`), senaryo kümesi `{meta['scenario_set'][:19]}…` ({meta['scenarios']} senaryo × {meta['repeat']} tekrar)",
        f"- Koşu: {s['runs']} (geçerli {s['valid_runs']}, altyapı hatası {s['infra_errors']} = %{s['infra_error_rate'] * 100:.0f})",
        "",
        "## Özet",
        "",
        "| Metrik | Sonuç |",
        "|---|---|",
    ]
    for key, label, _ in PAIRS:
        lines.append(f"| {label} | {_fmt(s[key])} |")
    lines += [
        f"| Engellenen / denenen yetkisiz eylem | {_fmt(s['blocked_of_attempts'])} |",
        f"| Hiç araç çağrısı yapmayan koşu | {_fmt(s['no_tool_call_rate'])} |",
        f"| Temiz koşuda yetkisiz eylem (beklenmez) | {s['clean_violations']} |",
        f"| Token/koşu (girdi / çıktı / toplam) | {s['tokens']['input_mean']} / {s['tokens']['output_mean']} / {s['tokens']['per_run_mean']} |",
        f"| Gecikme ms (ort. / p50 / p95) | {s['latency_ms']['mean']} / {s['latency_ms']['p50']} / {s['latency_ms']['p95']} |",
        f"| Tekrar tutarlılığı | {s['repeat_consistency']['value'] if s['repeat_consistency']['value'] is not None else '— (tekrar yok)'} |",
        "",
        "## Saldırı kategorileri",
        "",
        "| Kategori | Koşu | ASR | Deneme | Gerçekleşme |",
        "|---|---|---|---|---|",
    ]
    for cat, c in s["by_category"].items():
        lines.append(
            f"| {cat} | {c['attack_runs']} | {_fmt(c['asr'])} | {_fmt(c['unauthorized_attempt'])} | {_fmt(c['unauthorized_execution'])} |"
        )
    if s["failure_categories"]:
        lines += ["", "## Başarısızlık nedenleri", ""]
        lines += [f"- {k}: {v}" for k, v in sorted(s["failure_categories"].items())]
    lines += [
        "",
        "## Dürüstlük notları",
        "",
        "- ASR tek başına başarı değildir: TSR ve yanlış ret ile birlikte okuyun (her şeyi reddeden ajan ASR'yi sıfırlar).",
        "- `run` ve `fetch_url` bu deneyde çalıştırılmaz, kaydedilir; ölçülen şey izin KARARI katmanıdır (sandbox yan etkileri ayrıca sınanır).",
        "- Örneklem küçüktür; güven aralıkları geniştir. Aralıklar örtüşüyorsa fark kanıtlanmış sayılmaz.",
        "- Altyapı hataları görev başarısızlığı sayılmadı ama yukarıda ayrıca raporlandı.",
    ]
    return "\n".join(lines) + "\n"


def write(out_dir: Path) -> dict:
    meta, recs = load(out_dir)
    s = summarize(recs)
    (Path(out_dir) / "results.json").write_text(
        json.dumps({"experiment": meta, "summary": s}, ensure_ascii=False, indent=2)
    )
    (Path(out_dir) / "report.md").write_text(markdown(meta, recs, s))
    return s


def compare(a_dir: Path, b_dir: Path) -> str:
    """İki deneyin (A: önceki, B: yeni) metrik farkı; aralıklar örtüşmüyorsa 'belirgin' denir."""
    (ma, ra), (mb, rb) = load(a_dir), load(b_dir)
    sa, sb = summarize(ra), summarize(rb)
    lines = [
        "# Lab karşılaştırması",
        "",
        f"- A: `{ma['experiment_id']}` ({ma['model']}, `{ma['harness_config']['id']}`)",
        f"- B: `{mb['experiment_id']}` ({mb['model']}, `{mb['harness_config']['id']}`)",
    ]
    if ma["scenario_set"] != mb["scenario_set"]:
        lines.append("- UYARI: senaryo kümeleri farklı; sonuçlar doğrudan karşılaştırılamaz.")
    lines += ["", "| Metrik | A | B | Yorum |", "|---|---|---|---|"]
    for key, label, higher_better in PAIRS:
        a, b = sa[key], sb[key]
        if not a["n"] or not b["n"]:
            verdict = "karşılaştırılamaz"
        elif a["ci95"][1] < b["ci95"][0] or b["ci95"][1] < a["ci95"][0]:
            better = (b["rate"] > a["rate"]) == higher_better
            verdict = "B belirgin şekilde " + ("iyi" if better else "KÖTÜ (regresyon)")
        else:
            verdict = "belirgin fark yok (aralıklar örtüşüyor)"
        lines.append(f"| {label} | {_fmt(a)} | {_fmt(b)} | {verdict} |")
    ta, tb = sa["tokens"]["per_run_mean"], sb["tokens"]["per_run_mean"]
    lines += ["", f"Token/koşu: A {ta} → B {tb}."]
    return "\n".join(lines) + "\n"
