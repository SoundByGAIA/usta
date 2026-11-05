"""Doğrulama: düzenleme geri bildirimi (sözdizimi) ve bitirme kapısı (testi harness çalıştırır).

Amaç küçük modellerin erken ve kanıtsız "bitti" demesini azaltmak: model düzenleyip bitirmek
isterse harness testi kendisi koşar, başarısızsa kısa hata özetini modele geri verir. Döngü
sınırsız değildir: tekrar bütçesi ve aynı-hata tespiti vardır. Test komutları yalnız sandbox
imajında bulunan çalışma zamanlarını kullanır (şimdilik Python `unittest`).
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from usta.sandbox import RunResult, SandboxConfig, SandboxError, run_command

MAX_SYNTAX_BYTES = 1_000_000
SKIP_DIRS = {".git", ".usta", "__pycache__", "node_modules", ".venv", "venv", "site-packages"}
TEST_COMMAND = ["python", "-m", "unittest", "discover", "-q"]


def syntax_check(path: str, content: str) -> str | None:
    """Python dosyası için sözdizimi hatası mesajı (yoksa None). Kodu ÇALIŞTIRMAZ, yalnız ayrıştırır."""
    if not path.endswith(".py") or len(content) > MAX_SYNTAX_BYTES:
        return None
    try:
        ast.parse(content, filename=path)
    except SyntaxError as e:
        where = f"satır {e.lineno}" if e.lineno else "bilinmeyen satır"
        return f"{path}: sözdizimi hatası ({where}): {e.msg}"
    except ValueError as e:  # ör. null bayt
        return f"{path}: geçersiz içerik: {e}"
    return None


def _is_test_file(name: str) -> bool:
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def detect_test_command(root: Path) -> list[str] | None:
    for dirpath, dirs, files in os.walk(Path(root)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if any(_is_test_file(f) for f in files):
            return list(TEST_COMMAND)
    return None


def summarize_failure(output: str, limit: int = 1500) -> str:
    """Hatanın ucu en bilgilidir (traceback sonu, assert mesajı): sondan `limit` karakter."""
    text = output.strip()
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return "[... başı kırpıldı]\n" + cut[cut.find("\n") + 1 :]


_NOISE = [
    (re.compile(r"\bin \d+(\.\d+)?s\b"), "in Ns"),
    (re.compile(r"0x[0-9a-fA-F]+"), "0xADDR"),
    (re.compile(r"/tmp/[^\s:]+"), "/tmp/X"),
]


def failure_signature(output: str) -> str:
    """Süre/adres gibi değişken parçalar atılmış hata parmak izi: aynı hatayı yeniden tanımak için."""
    text = output
    for rx, repl in _NOISE:
        text = rx.sub(repl, text)
    return hashlib.sha1(text.strip().encode(), usedforsecurity=False).hexdigest()


_ENV_PATTERNS = (
    re.compile(r"(?:ModuleNotFoundError|ImportError): No module named '?([A-Za-z0-9_.\-]+)'?"),
    re.compile(r"(?:sh|bash): (?:\d+: )?([A-Za-z0-9_.\-]+): (?:command )?not found"),
)


def env_problem(output: str, root: Path | None = None) -> str | None:
    """Doğrulama çıktısı KOD hatası mı yoksa ORTAM sorunu mu: sandbox'ta olmayan bir paket/komut aranıyorsa ortamdır.

    Proje kendi modülünü bulamıyorsa (ör. `No module named 'shop.cart'`) bu kod hatasıdır; kökte karşılığı olmayan
    bir üçüncü taraf paket ya da komut (pytest, numpy, ...) bulunamıyorsa ortam sorunudur: sandbox'ta ağ kapalı olduğundan
    ajan bunu kodla düzeltemez ve yeniden denemek onarım bütçesini boşa harcar."""
    for rx in _ENV_PATTERNS:
        for m in rx.finditer(output):
            name = m.group(1)
            top = name.split(".")[0]
            if root is not None and (
                (Path(root) / f"{top}.py").exists() or (Path(root) / top).is_dir()
            ):
                continue  # projenin kendi modülü: kod hatası
            return f"eksik {'komut' if rx is not _ENV_PATTERNS[0] else 'bağımlılık'}: {name}"
    return None


@dataclass(frozen=True)
class GateResult:
    status: str  # passed | failed | unavailable | env_error
    command: str = ""
    output: str = ""
    reason: str = ""
    give_up: bool = False


class CompletionGate:
    def __init__(
        self,
        root: Path,
        *,
        max_rounds: int = 3,
        timeout: float = 90.0,
        run: Callable[..., RunResult] = run_command,
        cancel: threading.Event | None = None,
        command: list[str] | None = None,
        image: str | None = None,
    ):
        self.command = list(command) if command else None  # kullanıcının verdiği doğrulama komutu
        self.image = image
        self.root, self.max_rounds, self.timeout = Path(root), max_rounds, timeout
        self.run, self.cancel = run, cancel
        self.failures = 0
        self._last_sig: str | None = None

    def check(self) -> GateResult:
        command = self.command or detect_test_command(self.root)
        if command is None:
            return GateResult("unavailable", reason="çalıştırılabilir test bulunamadı")
        extra = {"image": self.image} if self.image else {}
        cfg = SandboxConfig(workdir=self.root, timeout=self.timeout, memory="256m", **extra)
        try:
            r = self.run(cfg, command, cancel=self.cancel)
        except SandboxError as e:
            return GateResult("unavailable", " ".join(command), reason=f"sandbox: {e}")
        out = (r.stdout + "\n" + r.stderr).strip()
        text = " ".join(command)
        if r.cancelled:
            return GateResult("unavailable", text, reason="iptal edildi")
        if r.exit_code == 0 and not r.timed_out:
            if re.search(r"\bRan 0 tests\b", out):
                return GateResult("unavailable", text, out, "keşif hiç test bulamadı")
            self.failures, self._last_sig = 0, None
            return GateResult("passed", text, summarize_failure(out, 400))
        env = env_problem(out, self.root)
        if env:  # kod hatası değil: onarım turu/devre kesici sayılmaz, ajan kodla düzeltemez
            return GateResult("env_error", text, summarize_failure(out, 600), env)
        self.failures += 1
        sig = failure_signature(out)
        repeated = sig == self._last_sig
        self._last_sig = sig
        reason = ""
        if repeated:
            reason = "aynı hata tekrarladı"
        elif self.failures >= self.max_rounds:
            reason = f"doğrulama bütçesi doldu ({self.max_rounds} tur)"
        body = "[zaman aşımı]\n" + out if r.timed_out else out
        return GateResult("failed", text, summarize_failure(body), reason, give_up=bool(reason))


@dataclass(frozen=True)
class Intervention:
    """Ajanın bitirme anında harness kararı: devam ettir (done=False) ya da kanıtla kabul et."""

    done: bool
    message: str = ""  # done=False: modele gidecek kullanıcı mesajı
    note: str = ""  # done=True: nihai yanıta eklenen kanıt satırı
    status: str = ""
    command: str = ""


class Verifier:
    def __init__(self, gate: CompletionGate, *, nudge_no_tests: bool = True):
        self.gate, self.nudge_no_tests, self._nudged = gate, nudge_no_tests, False
        self._code_nudged = False

    def on_unapplied_code(self, answer: str) -> Intervention | None:
        """Model kod içeren yanıt verip hiçbir dosyayı değiştirmeden bitirmek isterse bir kez yönlendirir."""
        if self._code_nudged or "```" not in answer:
            return None
        self._code_nudged = True
        msg = (
            "Yanıtında kod var ama çalışma alanında hiçbir dosyayı değiştirmedin. Görev dosya değişikliği "
            "gerektiriyorsa kodu write_file veya edit_file ile ilgili dosyaya uygula; gerektirmiyorsa "
            "yanıtını aynen tekrarla."
        )
        return Intervention(False, message=msg, status="unapplied")

    def after_edit(self, tool: str, args: dict, root: Path) -> str | None:
        """Düzenlemeden hemen sonra sözdizimi uyarısı (yoksa None)."""
        path = args.get("path")
        if tool not in ("write_file", "edit_file") or not isinstance(path, str):
            return None
        if tool == "write_file" and isinstance(args.get("content"), str):
            return syntax_check(path, args["content"])
        try:
            return syntax_check(path, (Path(root) / path).read_text(errors="replace"))
        except OSError:
            return None

    def on_finish(self) -> Intervention:
        r = self.gate.check()
        if r.status == "passed":
            return Intervention(
                True, note=f"Doğrulama: geçti ({r.command})", status="passed", command=r.command
            )
        if r.status == "failed":
            if r.give_up:
                note = f"Doğrulama başarısız, bırakıldı ({r.reason}); son çıktı:\n{r.output}"
                return Intervention(True, note=note, status="failed", command=r.command)
            msg = (
                f"Doğrulama başarısız ({r.command}). Çıktının sonu:\n{r.output}\n"
                "Hatayı düzelt; bitirmeden önce testin geçtiğinden emin ol."
            )
            return Intervention(False, message=msg, status="failed", command=r.command)
        if r.status == "env_error":
            note = (
                f"Doğrulama YAPILAMADI: doğrulama ortamı sorunu, kod hatası değil ({r.reason}). "
                "Sandbox'ta ağ kapalı olduğundan paket kurulamaz; ortamı (imaj/doğrulama komutu) düzeltmek kullanıcıya kalır. "
                f"Çıktının sonu:\n{r.output}"
            )
            return Intervention(True, note=note, status="env_error", command=r.command)
        if self.nudge_no_tests and not self._nudged and "test bulunamadı" in r.reason:
            self._nudged = True
            msg = (
                "Çalıştırılabilir test yok. Değişikliğini doğrulamak için küçük bir unittest dosyası "
                "yaz (test_*.py) ve python -m unittest ile çalıştır, sonra bitir."
            )
            return Intervention(False, message=msg, status="nudge")
        return Intervention(True, note=f"Doğrulama: yapılamadı ({r.reason})", status="unavailable")
