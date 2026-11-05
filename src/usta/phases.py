"""Yürütme aşamaları: görev yaşam döngüsünü GÖZLEMLENEBİLİR kılan durum makinesi.

    DISCOVER → PLAN → EDIT → VERIFY ─┬─ geçti → COMPLETE_*
                                      └─ kaldı → DIAGNOSE → REPAIR → VERIFY …

İzleyici ajan döngüsünü DEĞİŞTİRMEZ: yalnız ajanın olaylarını (araç çağrısı/sonucu, doğrulama, devre kesici, mesaj)
dinler, aşama geçişlerini ve nedenlerini kaydeder, aşama başına adım/süre/onarım sayar ve görev sonunda bir TERMİNAL
durum üretir. İsteğe bağlı olarak (`enforce=True`) onarım bütçesi aşıldığında görevi açıklanabilir biçimde durdurur;
varsayılan kapalıdır ve ölçümle doğrulanmadan açılmaz.

Aşama girişi/çıkışı (gözlenebilir koşullar):
- DISCOVER: başlangıç. Okuma/arama araçları (read_file, list_dir, outline, read_symbol, find_symbol, symbol_context,
  related_files, fetch_url). Çıkış: ilk düzenleme (→ EDIT) ya da ilk düzenlemeden önce model metin planı yazarsa (→ PLAN).
- PLAN: DISCOVER'dan sonra, ilk düzenlemeden önce modelin düz metin mesajı. Atlanabilir (DISCOVER → EDIT).
- EDIT: write_file/edit_file (henüz başarısız doğrulama yokken). Çıkış: test komutu (→ VERIFY).
- VERIFY: test benzeri `run` komutu ya da bitirme kapısı (`verification` olayı). Çıkış: geçti → (düzenleme yoksa) COMPLETE
  ya da yeni düzenleme (→ EDIT); kaldı → DIAGNOSE.
- DIAGNOSE: başarısız doğrulamadan sonra okuma/komut. Çıkış: düzenleme (→ REPAIR).
- REPAIR: başarısız doğrulamadan sonraki düzenleme. Her REPAIR girişi bir onarım denemesidir (ayrı bütçe).

Terminal durumlar: COMPLETE_VERIFIED, COMPLETE_UNVERIFIED, COMPLETE_NO_CHANGE, FAILED_VERIFICATION (doğrulama
başarısızken bırakıldı: başarı olarak GÖSTERİLMEZ), BLOCKED (devre kesici), EXHAUSTED (adım sınırı / onarım bütçesi),
CANCELLED, ERROR.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from usta.verify import failure_signature

PHASES = ("DISCOVER", "PLAN", "EDIT", "VERIFY", "DIAGNOSE", "REPAIR")
TERMINALS = (
    "COMPLETE_VERIFIED", "COMPLETE_UNVERIFIED", "COMPLETE_NO_CHANGE", "FAILED_VERIFICATION",
    "BLOCKED", "EXHAUSTED", "CANCELLED", "ERROR",
)  # fmt: skip
READ_TOOLS = frozenset({"read_file", "list_dir", "outline", "read_symbol", "find_symbol", "symbol_context", "related_files", "fetch_url"})  # fmt: skip
EDIT_TOOLS = frozenset({"write_file", "edit_file"})
TEST_CMD = re.compile(
    r"\b(unittest|pytest|py\.test|tox|nose2?|go test|cargo test|npm (run )?test|yarn test|pnpm test|make (test|check)|jest|mocha|vitest|rspec|ctest|node --test)\b",
    re.IGNORECASE,
)


@dataclass
class Transition:
    step: int  # o ana kadar yapılan araç çağrısı sayısı
    t_ms: int
    frm: str
    to: str
    reason: str


@dataclass
class PhaseTracker:
    repair_budget: int = 3
    enforce: bool = False  # True: onarım bütçesi aşılınca stop_reason verir (ajan durur)
    clock: Callable[[], float] = time.monotonic
    on_transition: Callable[[Transition], None] | None = None

    phase: str = "DISCOVER"
    terminal: str = ""
    transitions: list[Transition] = field(default_factory=list)
    steps_in: Counter = field(default_factory=Counter)  # aşama -> araç çağrısı
    ms_in: Counter = field(default_factory=Counter)  # aşama -> süre (ms)
    repairs: int = 0
    edits: int = 0
    verify_passes: int = 0
    verify_fails: int = 0
    same_failure_repeats: int = 0
    rewinds: int = 0
    denied: int = 0
    signals: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._t0 = self.clock()
        self._phase_since = self._t0
        self._calls = 0
        self._last_call: tuple[str, dict] | None = None
        self._pending_test = False  # son araç çağrısı bir test koşusuydu
        self._last_verify: str = ""  # "" | passed | failed
        self._edits_since_verify = 0
        self._last_fail_sig = ""
        self._read_seen = False
        self._planned = False
        self._blocked = False
        self._stop = ""

    # --- olay girişi -------------------------------------------------------------------------
    def observe(self, kind: str, data: dict) -> None:
        if self.terminal:
            return
        if kind == "tool_call":
            self._on_call(
                str(data.get("tool")),
                data.get("args") if isinstance(data.get("args"), dict) else {},
            )
        elif kind == "tool_result":
            self._on_result(str(data.get("tool")), str(data.get("result", "")))
        elif kind == "verification":
            self._on_gate(str(data.get("status")))
        elif kind == "breaker":
            self._on_breaker(bool(data.get("final")), str(data.get("reason", "")))
        elif kind == "denied":
            self.denied += 1
        elif (
            kind == "message"
            and self.phase == "DISCOVER"
            and self._read_seen
            and not self._planned
            and not self.edits
            and data.get("content")
        ):
            self._planned = True
            self._go("PLAN", "ilk düzenlemeden önce metin planı")

    def _on_call(self, tool: str, args: dict) -> None:
        self._calls += 1
        self._last_call = (tool, args)
        self._pending_test = False
        if tool in EDIT_TOOLS:
            self.edits += 1
            self._edits_since_verify += 1
            if self._last_verify == "failed" or self.phase == "DIAGNOSE":
                if self.phase != "REPAIR":
                    self.repairs += 1
                    self._go("REPAIR", "başarısız doğrulamadan sonra düzenleme")
                    if self.repairs > self.repair_budget:
                        self.signals.append("repair_budget_exceeded")
                        if self.enforce:
                            self._stop = f"onarım bütçesi doldu ({self.repair_budget} deneme)"
            elif self.phase in ("DISCOVER", "PLAN", "VERIFY"):
                self._go("EDIT", "ilk düzenleme" if self.edits == 1 else "yeni düzenleme")
        elif tool == "run" and TEST_CMD.search(str(args.get("command", ""))):
            self._pending_test = True
            if self.phase != "VERIFY":
                self._go("VERIFY", f"test komutu: {str(args.get('command', ''))[:60]}")
        elif tool in READ_TOOLS:
            self._read_seen = True
        self.steps_in[self.phase] += 1

    def _on_result(self, tool: str, result: str) -> None:
        if tool == "run" and self._pending_test:
            self._pending_test = False
            head = result.split("\n", 1)[0]
            if head.startswith("exit_code: 0"):
                self._verify_ok("test komutu geçti")
            else:
                self._verify_fail(
                    result.split("\n", 1)[1] if "\n" in result else result, "test komutu başarısız"
                )

    def _on_gate(self, status: str) -> None:
        if status == "passed":
            if self.phase != "VERIFY":
                self._go("VERIFY", "bitirme kapısı")
            self._verify_ok("bitirme kapısı geçti")
        elif status == "failed":
            if self.phase != "VERIFY":
                self._go("VERIFY", "bitirme kapısı")
            self._verify_fail(status, "bitirme kapısı başarısız")
        elif status == "env_error":
            self.signals.append("verification_env_error")

    def _verify_ok(self, why: str) -> None:
        self.verify_passes += 1
        self._last_verify = "passed"
        self._edits_since_verify = 0
        self._last_fail_sig = ""

    def _verify_fail(self, output: str, why: str) -> None:
        self.verify_fails += 1
        self._last_verify = "failed"
        sig = failure_signature(output)
        if sig == self._last_fail_sig:
            self.same_failure_repeats += 1
            if "repeated_failure" not in self.signals:
                self.signals.append("repeated_failure")
        self._last_fail_sig = sig
        self._go("DIAGNOSE", why)

    def _on_breaker(self, final: bool, reason: str) -> None:
        self.rewinds += 1
        if final:
            self._blocked = True
            return
        self._go("DIAGNOSE", f"devre kesici geri sardı: {reason[:60]}")
        self._last_verify = "failed"
        self._edits_since_verify = 0

    # --- geçiş ve sonuç ----------------------------------------------------------------------
    def _go(self, to: str, reason: str) -> None:
        if to == self.phase:
            return
        now = self.clock()
        self.ms_in[self.phase] += round((now - self._phase_since) * 1000)
        self._phase_since = now
        tr = Transition(self._calls, round((now - self._t0) * 1000), self.phase, to, reason)
        self.transitions.append(tr)
        self.phase = to
        if self.on_transition:
            self.on_transition(tr)

    @property
    def stop_reason(self) -> str:
        """enforce açıkken onarım bütçesi aşıldıysa nedeni (ajan bunu görünce durur); aksi halde boş."""
        return self._stop if self.enforce else ""

    def finish(
        self,
        *,
        answered: bool,
        truncated: bool = False,
        cancelled: bool = False,
        blocked: bool = False,
        error: bool = False,
    ) -> str:
        """Görev sonu: terminal durum. Başarısız doğrulama başarı olarak gösterilmez."""
        if self.terminal:
            return self.terminal
        now = self.clock()
        self.ms_in[self.phase] += round((now - self._phase_since) * 1000)
        if cancelled:
            term = "CANCELLED"
        elif error:
            term = "ERROR"
        elif self._blocked:  # devre kesici akışı kesti
            term = "BLOCKED"
        elif self.enforce and self._stop:  # onarım bütçesi (enforce)
            term = "EXHAUSTED"
        elif blocked:
            term = "BLOCKED"
        elif truncated:
            term = "EXHAUSTED"
        elif not answered:
            term = "ERROR"
        elif not self.edits:
            term = "COMPLETE_NO_CHANGE"
        elif self._last_verify == "passed" and not self._edits_since_verify:
            term = "COMPLETE_VERIFIED"
        elif self._last_verify == "failed":
            term = "FAILED_VERIFICATION"
        else:
            term = "COMPLETE_UNVERIFIED"
        self.terminal = term
        return term

    def summary(self) -> dict:
        """Deney/iz kaydı için özet (JSON'a serileştirilebilir)."""
        return {
            "terminal": self.terminal,
            "phase": self.phase,
            "transitions": [asdict(t) for t in self.transitions],
            "steps_in": dict(self.steps_in),
            "ms_in": dict(self.ms_in),
            "repairs": self.repairs,
            "repair_budget": self.repair_budget,
            "verify_passes": self.verify_passes,
            "verify_fails": self.verify_fails,
            "same_failure_repeats": self.same_failure_repeats,
            "rewinds": self.rewinds,
            "signals": list(dict.fromkeys(self.signals)),
        }
