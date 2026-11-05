"""Başarısızlık sınıflandırması (Failure Taxonomy): bir koşunun NEDEN başarısız olduğunu olay izinden çıkarır.

Amaç: "7B modelde başarı 0/30" gibi bir sonucu, modelin işi yapamamasından mı (araç şemasını anlamama, yanlış dosya,
yanlış çözüm), harness'ın şişirmesinden mi (bağlam dolması, tekrar döngüsü) yoksa altyapıdan mı kaynaklandığını
ayırmak. Sınıflandırma deterministiktir: aynı iz her zaman aynı kategoriyi verir. Kurallar öncelik sırasıyla işlenir;
ilk eşleşen BİRİNCİL kategoridir, tespit edilen diğer işaretler `signals` içinde ayrıca listelenir.

Başarılı bir koşu kategori almaz (`""`); işaretleri yine de çıkarılır (ör. başarılı ama çok onarım denemesi).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# birincil kategoriler (öncelik sırası burada)
INFRA = "INFRA_ERROR"  # uç nokta/ağ: modelin başarısızlığı sayılmaz
TIMEOUT = "TIMEOUT"
MODEL_ERROR = "MODEL_ERROR"  # model çağrısı hata verdi (altyapı değil)
TOOL_CALL_AS_TEXT = "TOOL_CALL_AS_TEXT"  # araç çağrısını yanıt metnine yazdı, gerçek çağrı yok
NO_TOOL_CALLS = "NO_TOOL_CALLS"  # hiç araç çağırmadı
TOOL_ARGUMENT_ERROR = "TOOL_ARGUMENT_ERROR"  # eksik/geçersiz argüman, bilinmeyen araç
WRONG_FILE_OR_SYMBOL = "WRONG_FILE_OR_SYMBOL"  # olmayan dosya/sembol (yanlış yere baktı)
EDIT_FAILURE = "EDIT_FAILURE"  # düzenleme uygulanamadı (eşleşme yok/birden fazla)
SYNTAX_ERROR_INTRODUCED = "SYNTAX_ERROR_INTRODUCED"  # yazdığı kod ayrıştırılamıyor
CONTEXT_EXHAUSTED = "CONTEXT_EXHAUSTED"  # bağlam penceresi doldu/sıkıştırma gerekti
REPEATED_APPROACH = "REPEATED_APPROACH"  # aynı çağrı/hata tekrarı (devre kesici ya da yineleme)
HARNESS_LOOP = "HARNESS_LOOP"  # kapı/devre kesici turları adım bütçesini tüketti
STEP_LIMIT = "STEP_LIMIT"  # adım sınırı, belirgin başka neden yok
TESTS_TAMPERED = "TESTS_TAMPERED"  # testi değiştirerek geçmeye çalıştı
NO_CHANGE = "NO_CHANGE"  # hiç düzenleme yapmadı
UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"  # düzenledi, doğrulamadan "bitti" dedi, sonuç yanlış
WRONG_SOLUTION = "WRONG_SOLUTION"  # düzenledi/doğruladı ama gizli test geçmiyor
UNKNOWN = "UNKNOWN"

CATEGORIES = (
    INFRA, TIMEOUT, MODEL_ERROR, TOOL_CALL_AS_TEXT, NO_TOOL_CALLS, TOOL_ARGUMENT_ERROR,
    WRONG_FILE_OR_SYMBOL, EDIT_FAILURE, SYNTAX_ERROR_INTRODUCED, CONTEXT_EXHAUSTED, REPEATED_APPROACH,
    HARNESS_LOOP, STEP_LIMIT, TESTS_TAMPERED, NO_CHANGE, UNVERIFIED_CLAIM, WRONG_SOLUTION, UNKNOWN,
)  # fmt: skip

# araç hata metinlerinden nedenler (tools.py/Registry hata iletileri)
ARG_ERROR = re.compile(
    r"eksik argüman|geçersiz argüman|bilinmeyen araç|geçersiz yol|geçersiz", re.IGNORECASE
)
MISSING_PATH = re.compile(
    r"FileNotFoundError|No such file|bulunamadı|sembol bulunamadı|bilinmeyen sembol|IsADirectory",
    re.IGNORECASE,
)
EDIT_ERR = re.compile(
    r"eşleşme|tam bir kez|birden fazla|bulunamadı.*eski|old.*bulun", re.IGNORECASE
)
TEXT_CALL = re.compile(
    r'"(?:name|tool)"\s*:\s*"(?:read_file|write_file|edit_file|run|list_dir|outline|read_symbol)"'
)


@dataclass
class Facts:
    """Sınıflandırıcının girdisi: bir koşunun özet olguları (bench TaskResult + olay izi)."""

    passed: bool
    infra: bool = False
    timed_out: bool = False
    model_error: bool = False
    truncated: bool = False
    tool_calls: int = 0
    edits: int = 0
    steps: int = 0
    max_steps: int = 0
    answer: str = ""
    tool_errors: list[str] = field(default_factory=list)  # `hata:` ile başlayan araç sonuçları
    calls: list[tuple[str, str]] = field(default_factory=list)  # (araç, argüman özeti)
    gate_rounds: int = 0
    breaker_trips: int = 0
    compactions: int = 0
    context_peak: int = 0
    context_window: int = 0
    syntax_warnings: int = 0
    tests_modified: bool = False
    unverified_claim: bool = False


@dataclass
class Verdict:
    primary: str
    signals: list[str]


def _repeats(calls: list[tuple[str, str]]) -> int:
    """Art arda aynı çağrı sayısının en büyüğü (aynı araç + aynı argüman)."""
    best = run = 0
    prev = None
    for c in calls:
        run = run + 1 if c == prev else 1
        prev = c
        best = max(best, run)
    return best


def _signals(f: Facts) -> list[str]:
    out: list[str] = []
    errs = f.tool_errors
    if any(ARG_ERROR.search(e) for e in errs):
        out.append(TOOL_ARGUMENT_ERROR)
    if any(MISSING_PATH.search(e) for e in errs):
        out.append(WRONG_FILE_OR_SYMBOL)
    if any(EDIT_ERR.search(e) for e in errs):
        out.append(EDIT_FAILURE)
    if f.syntax_warnings:
        out.append(SYNTAX_ERROR_INTRODUCED)
    if f.compactions or (f.context_window and f.context_peak > 0.85 * f.context_window):
        out.append(CONTEXT_EXHAUSTED)
    if f.breaker_trips or _repeats(f.calls) >= 3:
        out.append(REPEATED_APPROACH)
    if f.gate_rounds + f.breaker_trips >= max(3, f.max_steps // 3 if f.max_steps else 3):
        out.append(HARNESS_LOOP)
    if f.tests_modified:
        out.append(TESTS_TAMPERED)
    if f.tool_calls == 0:
        out.append(TOOL_CALL_AS_TEXT if TEXT_CALL.search(f.answer) else NO_TOOL_CALLS)
    return out


def classify(f: Facts) -> Verdict:
    """Başarısız koşunun birincil kategorisi ve tüm işaretleri. Başarılı koşu: primary == ''."""
    sig = _signals(f)
    if f.passed:
        return Verdict("", sig)
    if f.infra:
        return Verdict(INFRA, sig)
    if f.timed_out:
        return Verdict(TIMEOUT, sig)
    if f.model_error:
        return Verdict(MODEL_ERROR, sig)
    for cat in (TOOL_CALL_AS_TEXT, NO_TOOL_CALLS):
        if cat in sig:
            return Verdict(cat, sig)
    if TESTS_TAMPERED in sig:
        return Verdict(TESTS_TAMPERED, sig)
    if HARNESS_LOOP in sig and f.truncated:
        return Verdict(HARNESS_LOOP, sig)
    if CONTEXT_EXHAUSTED in sig and (f.truncated or f.tool_calls and f.edits == 0):
        return Verdict(CONTEXT_EXHAUSTED, sig)
    errors_dominate = f.tool_calls and len(f.tool_errors) * 2 >= f.tool_calls
    if errors_dominate:
        for cat in (TOOL_ARGUMENT_ERROR, EDIT_FAILURE, WRONG_FILE_OR_SYMBOL):
            if cat in sig:
                return Verdict(cat, sig)
    if REPEATED_APPROACH in sig:
        return Verdict(REPEATED_APPROACH, sig)
    if f.truncated:
        return Verdict(STEP_LIMIT, sig)
    if SYNTAX_ERROR_INTRODUCED in sig:
        return Verdict(SYNTAX_ERROR_INTRODUCED, sig)
    if f.edits == 0:
        return Verdict(NO_CHANGE, sig)
    if f.unverified_claim:
        return Verdict(UNVERIFIED_CLAIM, sig)
    return Verdict(WRONG_SOLUTION, sig)


def summarize_args(args: object) -> str:
    """Tekrar tespiti için argümanların kararlı, kısa özeti."""
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)[:160]
    except (TypeError, ValueError):
        return str(args)[:160]
