"""Ölçüm raporları: güven aralığı, eşleştirilmiş karşılaştırma, katman tablosu, regresyon ve başarısızlık dökümü."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from usta.bench import TaskResult, summarize


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
    data = json.loads(Path(path).read_text(encoding="utf-8"))
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
