"""Arka plan görevleri: iş parçacığında ajan, olay günlüğü, onaylar, durdurma, diff/geri alma."""

from __future__ import annotations

import contextlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from usta import attachments, mcpconfig, memory, projectcfg, projects
from usta.agent import SYSTEM_PROMPT, Agent
from usta.audit import AuditLog
from usta.breaker import CircuitBreaker
from usta.fetch import validate_url
from usta.mcp_tools import McpSession
from usta.modelctl import ModelControl
from usta.models import ModelClient, ModelError
from usta.policy import Policy
from usta.proxy import host_allowed
from usta.sandbox import run_command
from usta.sessions import SessionStore
from usta.tools import ToolContext, build_registry
from usta.verify import CompletionGate, Verifier
from usta.workspace import Snapshot, diff, remove_new_protected, revert, snapshot

MODES = ("manual", "auto", "plan")
PLAN_TOOLS = frozenset({"read_file", "list_dir", "fetch_url"})
PLAN_PROMPT = (
    "PLAN MODU: Dosyaları değiştiremez ve komut çalıştıramazsın (bu araçlar yok). Gerekirse dosyaları oku, "
    "sonra numaralı, uygulanabilir bir plan sun: değişecek dosyalar, adımlar, nasıl doğrulanacağı ve riskler. "
    "Kod yazma; yalnız planı yaz. Planın en başına 'Gereksinimler ve kısıtlar' bölümü koy ve kullanıcının "
    "verdiği TÜM istek/kısıtları eksiksiz taşı: onaylanınca plan, orijinal istem OLMADAN tek başına uygulanacak."
)
APPLY_PLAN_PROMPT = (
    "Aşağıdaki plan kullanıcı tarafından ONAYLANDI. Planı olduğu gibi uygula; planı tekrar yazma, özetleme "
    "ya da yeniden tartışma. Çalışma klasöründe PLAN.md yoksa oluştur ve ilerledikçe işaretle."
)


PHASE_SETUP_PROMPT = (
    "Aşağıdaki ONAYLI planı AŞAMALARA böl ve çalışma klasöründe PLAN.md olarak yaz. KOD YAZMA. "
    "PLAN.md şunları içermeli: (1) 'Gereksinimler ve kısıtlar', mimari ve dosya yapısı (sonraki aşamalar "
    "YALNIZ PLAN.md'yi görecek; teknik kararlar burada eksiksiz olsun); (2) 'Aşamalar': her biri tek satırlık, "
    "işaretlenebilir madde: `- [ ] A1 — başlık: kabul kriteri (hangi test/komut geçmeli)`. Aşamalar sıralı, "
    "her biri tek başına yaklaşık 15 araç adımında bitecek kadar küçük ve doğrulanabilir olsun; en az 4, en çok 25. "
    "Bitince dur."
)
PHASE_PROMPT = (
    "Çalışma klasöründeki PLAN.md'yi oku (gereksinimler, mimari, aşamalar). İşaretlenmemiş İLK aşamayı "
    "(`- [ ]`) uygula: gerekli dosyaları oku, kodu yaz/düzenle, testleri çalıştır, kırılırsa düzelt. Başarıyla "
    "bitince PLAN.md'de yalnız o maddeyi `- [x]` yap (yanına kısa not ekleyebilirsin). SONRAKİ AŞAMAYA GEÇME: "
    "işin bitince dur ve iki cümleyle ne yaptığını söyle."
)
CHECKBOX = re.compile(r"^[ \t]*[-*][ \t]*\[( |x|X)\][ \t]*(.*)$", re.MULTILINE)  # \s değil: ReDoS
MAX_PHASES = 40


@dataclass
class Series:
    """Aşamalı uygulama: her aşama taze bağlamlı ayrı görev; sıra PLAN.md'deki `- [ ]` satırlarıyla izlenir."""

    max_phases: int = MAX_PHASES
    phase: int = 0  # biten görev sayısı (kurulum dahil)
    last_unchecked: int | None = None
    stalls: int = 0
    active: bool = True


def plan_checklist(root: Path) -> tuple[int, list[str]] | None:
    """PLAN.md'deki (işaretli sayısı, işaretsiz madde başlıkları); dosya yoksa None."""
    p = Path(root) / "PLAN.md"
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 400_000:
            return None
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    done, todo = 0, []
    for m in CHECKBOX.finditer(text):
        if m.group(1) == " ":
            todo.append(m.group(2).strip())
        else:
            done += 1
    return done, todo


class RevertRefused(Exception):
    """Geri alma yapılamaz (daha yeni bir görev var ya da anlık görüntü artık tutulmuyor)."""


KEEP_SNAPSHOTS = 5


class PlanNotFound(Exception):
    """Uygulanacak plan yok: görev yok, plan modunda değil ya da başarıyla bitmemiş."""


class TaskFinished(Exception):
    """Biten göreve mesaj gönderilemez."""


class WorkspaceBusy(Exception):
    """Çalışma alanında zaten çalışan bir görev var."""


class _Approval:
    def __init__(self, tool: str, args: dict):
        self.tool, self.args = tool, args
        self.event = threading.Event()
        self.allow = False


class Task:
    def __init__(
        self,
        workspace_id: str,
        root: Path,
        prompt: str,
        context_window: int | None = None,
        mode: str = "manual",
        guard: bool = False,
        files: tuple[tuple[str, str], ...] = (),
    ):
        self.files = files
        self.model_prompt: str | None = (
            None  # modele giden metin; yoksa prompt (plan uygulamada farklıdır)
        )
        self.plan_of: str | None = None
        self.series: Series | None = None
        self.blocked = False
        self.diff_failed = False
        self.store: SessionStore | None = None
        self.mode = mode
        self.guard = guard
        self.id = uuid.uuid4().hex[:12]
        self.created = time.monotonic()
        self.usage: dict | None = None
        self.context_window = context_window
        self.workspace_id, self.root, self.prompt = workspace_id, root, prompt
        self.status = "running"
        self.answer = ""
        self.diff = ""
        self.events: list[dict] = []
        self.finished = threading.Event()
        self.cancel = threading.Event()
        self.snapshot: Snapshot | None = None
        self.approvals: dict[str, _Approval] = {}
        self._inbox: list[str] = []
        self._cond = threading.Condition()

    def emit(self, type_: str, data: dict | None = None) -> None:
        if type_ == "usage" and data:
            self.usage = dict(data)
        with self._cond:
            ev = {"i": len(self.events), "ts": time.time(), "type": type_, "data": data or {}}
            self.events.append(ev)
            self._cond.notify_all()
        if self.store is not None:
            self.store.append(self.workspace_id, self.id, ev)

    def post(self, text: str) -> None:
        with self._cond:
            if self.finished.is_set():
                raise TaskFinished(self.id)
            self._inbox.append(text)
        self.emit("user_message", {"text": text})

    def drain(self) -> list[str]:
        with self._cond:
            out, self._inbox = self._inbox, []
            return out

    def set_status(self, status: str) -> None:
        with self._cond:
            self.status = status

    def wait_events(self, start: int, timeout: float) -> tuple[list[dict], bool]:
        with self._cond:
            self._cond.wait_for(lambda: len(self.events) > start or self.finished.is_set(), timeout)
            return self.events[start:], self.finished.is_set()

    def public(self) -> dict:
        return {
            "id": self.id,
            "workspace": self.workspace_id,
            "prompt": self.prompt,
            "status": self.status,
            "answer": self.answer,
            "mode": self.mode,
            "guard": self.guard,
            "usage": self.usage,
            "context_window": self.context_window,
            "files": [n for n, _ in self.files],
            "plan_of": self.plan_of,
            "series": self.series is not None,
        }


class TaskManager:
    def __init__(
        self,
        model_factory: Callable[[], ModelClient],
        home: Path,
        max_steps: int = 20,
        approval_timeout: float = 300.0,
        allowed_hosts: tuple[str, ...] = (),
        mcp_servers: Sequence[mcpconfig.Server] | Callable[[], Sequence[mcpconfig.Server]] = (),
        context_window: int | None = None,
        guard: bool = False,
        model_control: ModelControl | None = None,
        shrink_writes: int | None = None,
    ):
        self.shrink_writes = shrink_writes
        self.model_control = model_control
        self.context_window = context_window
        self.guard = guard
        self.gate_run = run_command  # testlerde sandbox'sız doğrulama için değiştirilebilir
        self.allowed_hosts = tuple(allowed_hosts)
        self.mcp_servers = mcp_servers if callable(mcp_servers) else tuple(mcp_servers)
        self.model_factory, self.home = model_factory, Path(home)
        self.max_steps, self.approval_timeout = max_steps, approval_timeout
        self.sessions = SessionStore(self.home)
        self.tasks: dict[str, Task] = {}
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    def start(
        self,
        workspace_id: str,
        root: Path,
        prompt: str,
        mode: str = "manual",
        guard: bool | None = None,
        files: Sequence[tuple[str, str]] = (),
        plan_task: str | None = None,
        phased: bool = False,
        series: Series | None = None,
        model_prompt: str | None = None,
    ) -> Task:
        if mode not in MODES:
            raise ValueError(f"geçersiz mod: {mode!r} ({', '.join(MODES)})")
        use_guard = (self.guard if guard is None else guard) and mode != "plan"
        if phased and plan_task is None:
            raise ValueError("aşamalı uygulama için onaylı bir plan gerekir")
        if plan_task is not None:
            if mode == "plan":
                raise ValueError("plan modunda plan uygulanamaz")
            model_prompt = self._apply_prompt(
                workspace_id, plan_task, prompt, PHASE_SETUP_PROMPT if phased else APPLY_PLAN_PROMPT
            )
            if phased:
                series = Series()
        checked = tuple(attachments.validate(list(files)))  # AttachmentError çağırana gider
        task = Task(
            workspace_id,
            Path(root).resolve(),
            prompt,
            self.context_window,
            mode,
            use_guard,
            checked,
        )
        task.store = self.sessions
        task.model_prompt, task.plan_of, task.series = model_prompt, plan_task, series
        if not task.root.is_dir():
            raise NotADirectoryError(str(task.root))
        projects.check_root(
            self.home, task.root
        )  # eski kayıtlar/API yolu dahil: ev dizini çalışma alanı olamaz
        with self._lock:
            if workspace_id in self._busy:
                raise WorkspaceBusy(workspace_id)
            self._busy.add(workspace_id)
            self.tasks[task.id] = task
            self._prune_snapshots()
        try:
            task.snapshot = snapshot(task.root)
        except OSError:
            with self._lock:
                self._busy.discard(workspace_id)
                self.tasks.pop(task.id, None)
            raise
        self.sessions.begin(
            workspace_id,
            task.id,
            time.time(),
            {
                "prompt": prompt,
                "mode": mode,
                "guard": use_guard,
                "files": [n for n, _ in checked],
                "plan_of": plan_task,
            },
        )
        task.emit("started", {"task": task.id, "mode": mode, "guard": use_guard})
        if task.snapshot is not None and task.snapshot.truncated:
            task.emit(
                "warning",
                {
                    "message": "Klasör çok büyük: bazı dosyalar geri alma kapsamı dışında "
                    "(diff'e girmez, geri alınca silinmez). Daha küçük bir proje klasöründen başlatmak daha güvenli."
                },
            )
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        return task

    def _continue_series(self, task: Task, status: str) -> Task | None:
        """Aşamalı uygulamada sıradaki aşamayı başlatır; durma nedeni olayla bildirilir."""
        s = task.series
        if s is None or not s.active:
            return None

        def stop(msg: str) -> None:
            s.active = False
            task.emit("warning", {"message": msg})

        if status != "done" or task.cancel.is_set() or task.blocked:
            s.active = False
            return None
        s.phase += 1
        lst = plan_checklist(task.root)
        if lst is None:
            stop("PLAN.md bulunamadı ya da okunamadı; aşamalı uygulama durdu.")
            return None
        checked, todo = lst
        if not todo:
            stop(f"Tüm aşamalar tamam ({checked} aşama).")
            return None
        if s.phase > 1:  # kurulumdan sonra her görev bir madde işaretlemeli
            s.stalls = (
                s.stalls + 1
                if s.last_unchecked is not None and len(todo) >= s.last_unchecked
                else 0
            )
            if s.stalls >= 2:
                stop(
                    f"İlerleme yok: '{todo[0][:60]}' iki denemede de işaretlenemedi; aşamalı uygulama durdu."
                )
                return None
        if s.phase > s.max_phases:
            stop(f"Aşama sınırına ({s.max_phases}) ulaşıldı; aşamalı uygulama durdu.")
            return None
        s.last_unchecked = len(todo)
        try:
            return self.start(
                task.workspace_id,
                task.root,
                f"Aşama {checked + 1}/{checked + len(todo)}: {todo[0][:80]}",
                task.mode,
                task.guard,
                series=s,
                model_prompt=PHASE_PROMPT,
            )
        except (WorkspaceBusy, OSError, ValueError) as e:
            stop(f"Sonraki aşama başlatılamadı: {type(e).__name__}")
            return None

    def plan_answer(self, workspace_id: str, task_id: str) -> str:
        """Bitmiş bir plan görevinin planı (bellekte ya da kalıcı oturum kaydında)."""
        t = self.tasks.get(task_id)
        if t is not None:
            ok = t.workspace_id == workspace_id and t.mode == "plan" and t.status == "done"
            if ok and t.answer.strip():
                return t.answer
            raise PlanNotFound(task_id)
        found = self.sessions.load(workspace_id, task_id)
        if found and found["meta"].get("mode") == "plan" and found["status"] == "done":
            done = next((e for e in reversed(found["events"]) if e["type"] == "done"), None)
            answer = (done or {}).get("data", {}).get("answer", "")
            if answer.strip():
                return answer
        raise PlanNotFound(task_id)

    def _apply_prompt(self, workspace_id: str, plan_task: str, note: str, head: str = "") -> str:
        plan = self.plan_answer(workspace_id, plan_task)
        nonce = uuid.uuid4().hex[:8]
        extra = note.strip()
        extra = (
            ""
            if extra.casefold().startswith("planı uygula")
            else f"\nKullanıcının ek notu: {extra}"
        )
        return f"{head or APPLY_PLAN_PROMPT}{extra}\n<<<ONAYLI-PLAN id={nonce}>>>\n{plan}\n<<<ONAYLI-PLAN-SONU id={nonce}>>>"

    def post_message(self, task_id: str, text: str) -> None:
        self.tasks[task_id].post(text)

    def any_busy(self) -> bool:
        with self._lock:
            return bool(self._busy)

    def _prune_snapshots(self) -> None:
        """Bellek: yalnız son birkaç görevin anlık görüntüsü tutulur (kilit altında çağrılır)."""
        by_ws: dict[str, list[Task]] = {}
        for t in self.tasks.values():
            if t.snapshot is not None:
                by_ws.setdefault(t.workspace_id, []).append(t)
        for tasks in by_ws.values():  # çalışma alanı başına son KEEP_SNAPSHOTS görev
            tasks.sort(key=lambda t: t.created)
            for t in tasks[: max(0, len(tasks) - KEEP_SNAPSHOTS)]:
                if t.finished.is_set():
                    t.snapshot = None

    def is_busy(self, workspace_id: str) -> bool:
        with self._lock:
            return workspace_id in self._busy

    def get(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def cancel(self, task_id: str) -> None:
        task = self.tasks[task_id]
        if task.finished.is_set():
            return
        task.cancel.set()
        if task.series is not None:
            task.series.active = False  # iptal: sonraki aşamalar başlamaz
        task.set_status("cancelling")

    def resolve_approval(self, approval_id: str, allow: bool) -> None:
        for task in list(self.tasks.values()):
            ap = task.approvals.pop(approval_id, None)
            if ap is not None:
                ap.allow = allow
                ap.event.set()
                return
        raise KeyError(approval_id)

    def revert(self, task_id: str) -> None:
        task = self.tasks[task_id]
        with self._lock:
            if task.workspace_id in self._busy:
                raise WorkspaceBusy(task.workspace_id)
            if task.snapshot is None:
                raise RevertRefused("bu görevin geri alma verisi artık tutulmuyor")
            newer = any(
                t is not task
                and t.workspace_id == task.workspace_id
                and t.created > task.created
                and t.mode != "plan"
                and (
                    t.diff or t.diff_failed or not t.finished.is_set()
                )  # değişiklik yapmamışı saymaz
                for t in self.tasks.values()
            )
            if newer:  # eski görevin geri alınması sonraki görevlerin işini de silerdi
                raise RevertRefused("daha yeni bir görev var; yalnız son görev geri alınabilir")
            self._busy.add(
                task.workspace_id
            )  # dosya G/Ç'si kilit dışında; bu arada yeni görev başlamaz
        try:
            revert(task.snapshot, task.root)
        finally:
            with self._lock:
                self._busy.discard(task.workspace_id)
        task.diff = ""
        task.emit("reverted")

    def _approver(self, task: Task, tool: str, args: dict) -> bool:
        if task.mode == "auto" and tool == "fetch_url" and not self._fetch_allowed(args):
            # sorgu dizesiyle veri sızdırma yolu: oto onay bunu kendiliğinden açmaz (--allow-host gerekir)
            task.emit("denied", {"tool": tool, "reason": "oto onay: izinli olmayan alan adı"})
            return False
        if task.mode == "auto":  # kullanıcı seçti: sorma, ama kaydet (DENY kararları buraya gelmez)
            task.emit("auto_approved", {"tool": tool, "args": args})
            return not task.cancel.is_set()
        ap, aid = _Approval(tool, args), uuid.uuid4().hex[:12]
        task.approvals[aid] = ap
        previous = task.status
        task.set_status("awaiting_approval")
        task.emit("approval_required", {"approval_id": aid, "tool": tool, "args": args})
        deadline = time.monotonic() + self.approval_timeout
        while not ap.event.wait(0.1):
            if task.cancel.is_set() or time.monotonic() >= deadline:
                break
        task.approvals.pop(aid, None)
        if not task.cancel.is_set():
            task.set_status(previous)
        return ap.allow and ap.event.is_set() and not task.cancel.is_set()

    def _fetch_allowed(self, args: dict) -> bool:
        try:
            _, host = validate_url(args.get("url"))
        except ValueError:
            return False
        return host_allowed(host, self.allowed_hosts)

    def _verifier(self, task: Task) -> Verifier | None:
        if not task.guard:
            return None
        proj = projectcfg.load(
            self.home, task.root
        )  # kullanıcının verdiği komut/imaj (çalışma alanı dışında)
        gate = CompletionGate(
            task.root,
            run=self.gate_run,
            cancel=task.cancel,
            command=list(proj.verify) if proj.verify else None,
            image=proj.image,
        )
        return Verifier(gate, nudge_no_tests=proj.verify is None)

    def _run(self, task: Task) -> None:
        audit = AuditLog(self.home / "audit" / f"{task.workspace_id}.jsonl")
        status, error = "done", None
        mcp: McpSession | None = None
        try:
            memory_context = ""
            with contextlib.suppress(OSError, ValueError):  # hafıza yoksa/bozuksa görev sürer
                memory_context = memory.render_context(task.root)
            servers = self.mcp_servers() if callable(self.mcp_servers) else self.mcp_servers
            if servers:
                mcp = McpSession(servers, self.home, cancel=task.cancel)
                mcp.start()  # bozuk sunucu görevi düşürmez, uyarı olarak bildirilir
                for w in mcp.warnings:
                    task.emit("warning", {"message": w})
            plan = task.mode == "plan"
            registry = build_registry(
                ToolContext(root=task.root, cancel=task.cancel, allowed_hosts=self.allowed_hosts),
                extra=mcp.tools if mcp else (),
            )
            if plan:  # plan modu: yalnız okuma; yazma, komut, not ve MCP araçları hiç verilmez
                registry = registry.subset(PLAN_TOOLS)
            agent = Agent(
                self.model_factory(),
                registry,
                Policy(task.root, set(self.allowed_hosts), mcp_modes=mcp.modes if mcp else None),
                audit,
                approver=lambda t, a: self._approver(task, t, a),
                max_steps=self.max_steps,
                on_event=task.emit,
                cancel=task.cancel,
                memory_context=memory_context,
                verifier=self._verifier(task),
                breaker=CircuitBreaker(task.root) if task.guard else None,
                context_window=self.context_window,
                inbox=task.drain,
                shrink_writes=self.shrink_writes,
                system_prompt=f"{SYSTEM_PROMPT}\n\n{PLAN_PROMPT}" if plan else None,
            )
            result = agent.run(
                attachments.compose(task.model_prompt or task.prompt, list(task.files))
            )
            task.answer = result.answer
            task.blocked = result.blocked
            if result.cancelled:
                status = "cancelled"
        except ModelError as e:
            status, error = "failed", str(e)
        except Exception as e:  # noqa: BLE001 - ayrıntı sızdırma, yalnız tür kaydedilir
            audit.record("task_error", error_type=type(e).__name__)
            status, error = "failed", "beklenmeyen hata"
        finally:
            if task.snapshot is not None:
                with contextlib.suppress(Exception):  # çalışma alanı asla bu yüzden meşgul kalmasın
                    quarantine = self.home / "quarantine" / task.id
                    gone = remove_new_protected(task.root, task.snapshot.protected, quarantine)
                    if (
                        gone
                    ):  # ajan .git/.usta/çıplak depo oluşturdu: hook/config ile kod çalıştırma yolu
                        audit.record("protected_quarantined", paths=gone)
                        task.emit(
                            "warning",
                            {
                                "message": "Görev sırasında oluşturulan .git/.usta girdileri çalışma "
                                f"alanından çıkarıldı ve karantinaya alındı ({quarantine}): "
                                + ", ".join(gone[:5])
                            },
                        )
            try:
                task.diff = diff(task.snapshot, task.root) if task.snapshot else ""
            except OSError:
                task.diff = ""
                task.diff_failed = True  # değişiklik var sayılır (geri alma kuralı)
            if (
                task.mode != "plan"
            ):  # plan hiçbir şeyi değiştirmedi; hafızaya girip istemi şişirmesin
                with contextlib.suppress(OSError, ValueError):
                    memory.append_history(
                        task.root,
                        task_id=task.id,
                        prompt=task.prompt,
                        status=status,
                        answer=task.answer,
                    )
            task.status = status
            with (
                self._lock
            ):  # önce çalışma alanını bırak: aşamalı uygulamada sonraki görev buraya girer
                self._busy.discard(task.workspace_id)
            data = {"status": status, "answer": task.answer}
            if error:
                data["error"] = error
            nxt = self._continue_series(task, status)
            if nxt is not None:
                data["next"] = nxt.id  # arayüz/terminal akışı bu göreve geçirir
            task.emit("done", data)
            task.finished.set()
