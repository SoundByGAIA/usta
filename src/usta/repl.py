"""Etkileşimli terminal: `usta` yazınca açılır. İnce bir istemci: görevler `TaskManager`'dadır,
bu yüzden portal aynı görevi canlı izler; onay, diff, geri alma ve meşgul kilidi ortaktır.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
import sys
import time
from collections.abc import Callable
from pathlib import Path

from usta import mcpconfig, memory, projectcfg, skills, theme
from usta import settings as st
from usta.modelctl import ModelSwitchError
from usta.tasks import RevertRefused, Task, TaskManager, WorkspaceBusy

MODE_LABELS = {"manual": "manuel", "auto": "oto onay", "plan": "plan"}
MODE_ALIASES = {
    "manuel": "manual", "manual": "manual", "m": "manual",
    "oto": "auto", "otomatik": "auto", "auto": "auto", "yolo": "auto", "o": "auto",
    "plan": "plan", "p": "plan",
}  # fmt: skip
CYCLE = ("manual", "auto", "plan")
COMMAND = re.compile(r"^/([\w?çğıöşüÇĞİÖŞÜ-]+)(?:\s+(.*))?$")
ALIASES = {
    "yardım": "help", "yardim": "help", "help": "help", "?": "help",
    "mod": "mode", "mode": "mode", "tema": "theme", "theme": "theme",
    "doğrula": "verify", "dogrula": "verify", "verify": "verify", "koruma": "guard", "guard": "guard", "temizle": "clear", "clear": "clear", "diff": "diff", "geri": "undo", "undo": "undo",
    "token": "tokens", "tokens": "tokens", "hafıza": "memory", "hafiza": "memory",
    "memory": "memory", "not": "memory", "geçmiş": "history", "beceriler": "skills", "skills": "skills", "gecmis": "history", "history": "history", "mcp": "mcp", "portal": "portal", "model": "model",
    "çık": "exit", "cik": "exit", "exit": "exit", "quit": "exit", "q": "exit",
}  # fmt: skip
HELP = [
    ("/yardım", "bu listeyi göster"),
    (
        "/mod [manuel|oto|plan]",
        "çalışma modu: manuel (her onay sorulur), oto onay, plan (önce plan sun)",
    ),
    ("/tema [beyaz|gri|siyah]", "renk teması"),
    (
        "/koruma [aç|kapat]",
        "doğrulama kapısı + devre kesici: değişiklikten sonra test koşar, döngüde geri sarar",
    ),
    ("/diff", "son görevin değişikliklerini renkli göster"),
    ("/geri", "son görevin değişikliklerini geri al (onay ister)"),
    ("/token", "son görevin token kullanımı ve bağlam doluluğu"),
    ("/hafıza", "proje notları ve son görevler"),
    (
        "/doğrula [komut | temizle]",
        "proje doğrulama komutu (ör. /doğrula pytest -q); koruma açıkken kapı bunu çalıştırır",
    ),
    ("/geçmiş [n]", "önceki oturumlar; /geçmiş 2 ikinci en yeni oturumun özetini gösterir"),
    ("/beceriler", "~/.usta/skills altındaki beceriler; /ad ile çalıştırılır"),
    ("/mcp", "ekli MCP araçları"),
    ("/model [[api] ad]", "kullanılan model ve bağlı API'lerin modelleri; ad verirsen değiştirir"),
    (
        "/portal [link]",
        "portal adresi; tarayıcı açılmazsa `link` tek kullanımlık giriş bağlantısını yazar",
    ),
    ("/temizle", "ekranı temizle"),
    ("/çık", "çıkış (Ctrl+D de olur)"),
]


def fmt_tokens(n: float) -> str:
    n = float(n or 0)
    if n >= 1e6:
        return f"{n / 1e6:.1f}".replace(".", ",").removesuffix(",0") + "M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}".replace(".", ",").removesuffix(",0") + "K"
    return str(int(n))


def brief(args: dict) -> str:
    for key in ("path", "command", "query", "url"):
        if isinstance(args.get(key), str):
            return args[key].splitlines()[0][:80] if args[key] else ""
    return ""


class Repl:
    def __init__(
        self,
        manager: TaskManager,
        root: Path,
        workspace_id: str,
        home: Path,
        settings: st.Settings,
        *,
        inp: Callable[[str], str] = input,
        out=None,
        color: bool | None = None,
        model_name: str = "?",
        protocol: str = "native",
        portal_url: str | None = None,
        open_portal: Callable[[], None] | None = None,
        login_link: Callable[[], str] | None = None,
        context_window: int | None = None,
        persist: bool = True,
    ):
        self.manager, self.root, self.ws, self.home = manager, Path(root), workspace_id, Path(home)
        self.settings, self.inp = settings, inp
        self.out = out if out is not None else sys.stdout
        self.color = (
            color if color is not None else bool(getattr(self.out, "isatty", lambda: False)())
        )
        self.paint = theme.Painter(settings.theme, color=self.color)
        self.model_name, self.protocol = model_name, protocol
        self.portal_url, self.open_portal, self.login_link = portal_url, open_portal, login_link
        self.context_window = context_window or settings.context_window
        self.persist = persist
        self.mode = settings.mode
        self.last: Task | None = None

    # --- çıktı yardımcıları ---------------------------------------------------------------
    def say(self, text: str = "", role: str | None = None) -> None:
        print(self.paint(role, text) if role else text, file=self.out, flush=True)

    def _prompt_str(self) -> str:
        s = self.paint("prompt", f"usta [{MODE_LABELS[self.mode]}] › ")
        if self.color:  # readline imleç hesabı için görünmez dizileri işaretle
            s = re.sub(r"(\x1b\[[0-9;]*m)", "\001\\1\002", s)
        return s

    def _save(self) -> None:
        if self.persist:
            try:
                st.save(self.home, self.settings)
            except OSError as e:
                self.say(f"ayar kaydedilemedi: {e.strerror or e}", "warn")

    # --- ana döngü ------------------------------------------------------------------------
    def run(self) -> int:
        self._banner()
        while True:
            try:
                line = self.inp(self._prompt_str())
            except EOFError:
                self.say()
                return 0
            except KeyboardInterrupt:
                self.say("\nÇıkmak için /çık yaz ya da Ctrl+D'ye bas.", "dim")
                continue
            if not self.execute(line):
                return 0

    def _banner(self) -> None:
        self.say(
            f"Usta · {self.model_name or 'model seçilmedi'} · {self.root.name} · mod: {MODE_LABELS[self.mode]} · tema: {self.settings.theme}",
            "title",
        )
        self.say(f"Çalışma klasörü: {self.root}  (dosyalar buraya yazılır)", "dim")
        if self.root == Path.home() or self.root == Path(self.root.anchor):
            self.say(
                "Uyarı: ev dizini/kök klasör çalışma alanı olarak açıldı; ajan altındaki her şeyi görebilir. "
                "Bir proje klasörüne girip öyle başlatmak daha güvenli.",
                "warn",
            )
        tail = f"Portal: {self.portal_url}  ·  " if self.portal_url else ""
        self.say(f"{tail}/yardım ile komutları gör", "dim")

    def execute(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        m = COMMAND.match(line)
        if m:
            cmd = ALIASES.get(m.group(1).casefold())
            if cmd is None:
                expanded = skills.expand(self.home, line)
                if expanded != line:  # ~/.usta/skills/<ad>.md becerisi
                    self.run_task(expanded)
                    return True
                self.say(
                    f"bilinmeyen komut: /{m.group(1)}  (/yardım; beceriler: /beceriler)", "warn"
                )
                return True
            return self._command(cmd, (m.group(2) or "").strip())
        self.run_task(line)
        return True

    # --- komutlar -------------------------------------------------------------------------
    def _command(self, cmd: str, arg: str) -> bool:
        if cmd == "exit":
            return False
        {
            "help": self._help, "mode": self._mode, "theme": self._theme, "clear": self._clear, "guard": self._guard, "verify": self._verify,
            "diff": self._diff, "undo": self._undo, "tokens": self._tokens,
            "memory": self._memory, "history": self._history, "skills": self._skills, "mcp": self._mcp, "portal": self._portal, "model": self._model,
        }[cmd](arg)  # fmt: skip
        return True

    def _help(self, _: str) -> None:
        for name, text in HELP:
            self.say(f"  {self.paint('tool', name.ljust(26))} {text}")

    def _clear(self, _: str) -> None:
        if self.color:
            print("\x1b[2J\x1b[H", end="", file=self.out, flush=True)

    def _mode(self, arg: str) -> None:
        if arg:
            new = MODE_ALIASES.get(arg.casefold())
            if new is None:
                self.say(f"geçersiz mod: {arg!r} (manuel, oto, plan)", "warn")
                return
        else:
            new = CYCLE[(CYCLE.index(self.mode) + 1) % len(CYCLE)]
        self.mode = new
        self.settings = dataclasses.replace(self.settings, mode=new)
        self._save()
        self.say(f"mod: {MODE_LABELS[new]}", "ok")
        if new == "auto":
            self.say("Dikkat: onay isteyen eylemler (ek araçlar, izin verilmemiş adresler) SORULMADAN çalışır. "
                     "Yasaklar ve sandbox sınırları yine geçerli.", "warn")  # fmt: skip
        if new == "plan":
            self.say("Plan modu: yalnız okur ve plan sunar; dosya değiştirmez.", "dim")

    def _verify(self, arg: str) -> None:
        arg = arg.strip()
        if arg.casefold() in {"temizle", "sil", "clear"}:
            projectcfg.clear(self.home, self.root)
            self.say("doğrulama ayarı silindi; otomatik keşif kullanılacak", "ok")
            return
        if not arg:
            cfg = projectcfg.load(self.home, self.root)
            self.say(
                f"doğrulama komutu: {' '.join(cfg.verify)}"
                if cfg.verify
                else "doğrulama komutu: otomatik keşif (test_*.py → unittest)"
            )
            return
        try:
            command = shlex.split(arg)
            projectcfg.set_verify(self.home, self.root, command)
        except (ValueError, projectcfg.ProjectConfigError) as e:
            self.say(f"geçersiz komut: {e}", "warn")
            return
        self.say(f"doğrulama komutu ayarlandı: {' '.join(command)}", "ok")

    def _guard(self, arg: str) -> None:
        word = arg.strip().casefold()
        if not word:
            self.say(
                f"koruma: {'açık' if self.settings.guard else 'kapalı'}  (/koruma aç | /koruma kapat)"
            )
            return
        if word not in {"aç", "ac", "açık", "on", "kapat", "kapalı", "off"}:
            self.say("kullanım: /koruma aç  veya  /koruma kapat", "warn")
            return
        on = word in {"aç", "ac", "açık", "on"}
        self.settings = dataclasses.replace(self.settings, guard=on)
        self._save()
        self.say(f"koruma: {'açık' if on else 'kapalı'}", "ok")
        if on:
            self.say(
                "Değişiklikten sonra testler sandbox'ta çalıştırılır; aynı hata tekrarlanırsa son güvenli duruma dönülür.",
                "dim",
            )

    def _theme(self, arg: str) -> None:
        if not arg:
            names = ", ".join(theme.THEMES)
            self.say(f"tema: {self.settings.theme}  (seçenekler: {names})")
            return
        try:
            name = theme.resolve(arg)
        except ValueError:
            self.say(f"bilinmeyen tema: {arg!r} (beyaz, gri, siyah)", "warn")
            return
        self.settings = dataclasses.replace(self.settings, theme=name)
        self.paint = theme.Painter(name, color=self.color)
        self._save()
        self.say(f"tema: {name}", "ok")

    def _diff(self, _: str) -> None:
        if self.last is None:
            self.say("henüz görev yok", "dim")
            return
        self._show_diff(self.last)

    def _undo(self, _: str) -> None:
        if self.last is None or self.last.snapshot is None:
            self.say("henüz görev yok", "dim")
            return
        if not self.last.diff:
            self.say("geri alınacak değişiklik yok", "dim")
            return
        if self.inp(
            "Son görevin değişiklikleri geri alınsın mı? [e/H] "
        ).strip().casefold() not in {"e", "evet", "y"}:
            self.say("vazgeçildi", "dim")
            return
        try:
            self.manager.revert(self.last.id)
        except WorkspaceBusy:
            self.say("çalışma alanında görev sürüyor", "warn")
            return
        except RevertRefused as e:
            self.say(str(e), "warn")
            return
        self.say("geri alındı", "ok")

    def _tokens(self, _: str) -> None:
        if self.last is None:
            self.say("henüz görev yok", "dim")
            return
        self.say(self._token_line(self.last) or "bu model kullanım bilgisi bildirmiyor", "dim")

    def _memory(self, _: str) -> None:
        try:
            notes = memory.list_notes(self.root)
            hist = memory.recent_history(self.root)
        except (OSError, ValueError):
            notes, hist = [], []
        self.say("Notlar:", "title")
        for n in notes or ["(yok)"]:
            self.say(f"  - {n}")
        self.say("Son görevler:", "title")
        for h in hist or []:
            self.say(f"  [{h['ts']}] {h['status']}: {h['prompt'][:80]}")
        if not hist:
            self.say("  (yok)")

    def _history(self, arg: str) -> None:
        rows = self.manager.sessions.list(self.ws, 20)
        if not rows:
            self.say("henüz kayıtlı oturum yok", "dim")
            return
        if arg.isdigit() and 1 <= int(arg) <= len(rows):
            row = rows[int(arg) - 1]
            full = self.manager.sessions.load(self.ws, row["id"]) or {"events": []}
            self.say(f"[{self._when(row['ts'])}] {row['status']}  {row['prompt']}", "title")
            tools = [e["data"].get("tool") for e in full["events"] if e["type"] == "tool_call"]
            if tools:
                self.say(f"  araç çağrıları: {', '.join(t for t in tools if t)}", "dim")
            done = next((e for e in reversed(full["events"]) if e["type"] == "done"), None)
            self.say(((done or {}).get("data", {}).get("answer") or "(yanıt yok)").strip())
            return
        for i, r in enumerate(rows, 1):
            self.say(f"  {i:>2}. [{self._when(r['ts'])}] {r['status']:<11} {r['prompt'][:70]}")
        self.say("ayrıntı için: /geçmiş <numara>", "dim")

    def _skills(self, _: str) -> None:
        rows = skills.list_skills(self.home)
        if not rows:
            self.say(
                f"beceri yok. {self.home}/skills/<ad>.md dosyası ekle (ilk satır açıklama).", "dim"
            )
        for r in rows:
            self.say(f"  /{r['name']:<16} {r['description']}")

    @staticmethod
    def _when(ts) -> str:
        return time.strftime("%d.%m %H:%M", time.localtime(ts)) if ts else "?"

    def _mcp(self, _: str) -> None:
        try:
            servers = list(mcpconfig.load(self.home).values())
        except mcpconfig.McpConfigError as e:
            self.say(f"MCP yapılandırması okunamadı: {e}", "warn")
            return
        self.say("MCP araçları:", "title")
        for s in servers or []:
            self.say(f"  {s.name}  [{'açık' if s.enabled else 'kapalı'}]  onay: {s.approve}")
        if not servers:
            self.say("  (yok)  — eklemek için: usta mcp add AD -- KOMUT")

    def _model(self, arg: str) -> None:
        ctl = self.manager.model_control
        if arg and ctl is not None:
            if self.manager.any_busy():
                self.say("görev sürerken model değiştirilemez", "warn")
                return
            parts = arg.split()
            api, model = (parts[0], parts[1]) if len(parts) == 2 else (None, arg)
            try:
                ctl.switch(model, api)
            except ModelSwitchError as e:
                self.say(f"model değişmedi: {e.message}", "warn")
                return
            self.model_name, self.protocol = ctl.name, ctl.protocol
        elif ctl is not None and not arg:
            for g in ctl.info()["apis"]:
                self.say(f"  {g['api']}: " + (", ".join(g["models"]) or f"({g['error']})"), "dim")
            self.say("değiştirmek için: /model <ad>  veya  /model <api> <ad>", "dim")
        self.say(f"model: {self.model_name}  protokol: {self.protocol}")

    def _portal(self, arg: str) -> None:
        if not self.portal_url:
            self.say("portal kapalı (usta --portal ile aç)", "dim")
            return
        if arg.strip().casefold() in ("link", "giriş", "giris"):
            if (
                self.login_link
            ):  # snap/flatpak tarayıcı yönlendirme sayfasını açamazsa: bağlantıyı elle yapıştır
                self.say(f"Tek kullanımlık giriş bağlantısı (2 dk): {self.login_link()}", "title")
            return
        self.say(f"Portal: {self.portal_url}  (tarayıcı açılmazsa: /portal link)")
        if self.open_portal:
            self.open_portal()

    # --- görev çalıştırma -----------------------------------------------------------------
    def run_task(
        self,
        prompt: str,
        mode: str | None = None,
        plan_task: str | None = None,
        phased: bool = False,
    ) -> Task | None:
        mode = mode or self.mode
        try:
            task = self.manager.start(
                self.ws,
                self.root,
                prompt,
                mode,
                self.settings.guard,
                plan_task=plan_task,
                phased=phased,
            )
        except WorkspaceBusy:
            self.say(
                "Bu çalışma alanında bir görev sürüyor (portaldan başlamış olabilir); bitmesini bekle.",
                "warn",
            )
            return None
        except (OSError, ValueError) as e:
            self.say(f"görev başlatılamadı: {e}", "error")
            return None
        self.last = task
        self._follow(task)
        self._finish(task)
        while (
            nxt := self._next_task(task)
        ) is not None:  # aşamalı uygulama: sunucu sıradakini başlattı
            task = nxt
            self.last = task
            self.say(f"→ {task.prompt}", "title")
            self._follow(task)
            self._finish(task)
        if mode == "plan" and task.status == "done" and task.answer.strip():
            self._offer_plan(task)
        return task

    def _wait_for(self, task: Task, i: int):
        return task.wait_events(i, 0.2)

    def _follow(self, task: Task) -> None:
        i, interrupted = 0, False
        while True:
            try:
                events, done = self._wait_for(task, i)
            except KeyboardInterrupt:
                if not interrupted:
                    interrupted = True
                    self.manager.cancel(task.id)
                    self.say("\ndurduruluyor…", "warn")
                continue
            for e in events:
                i = e["i"] + 1
                try:
                    self._render(task, e)
                except KeyboardInterrupt:
                    if not interrupted:
                        interrupted = True
                        self.manager.cancel(task.id)
                        self.say("\ndurduruluyor…", "warn")
            if done and not events:
                return

    def _render(self, task: Task, e: dict) -> None:
        kind, d = e["type"], e["data"] or {}
        if kind == "message":
            self.say(d.get("content", ""), "assistant")
        elif kind == "tool_call":
            self.say(f"● {d.get('tool')} {brief(d.get('args') or {})}".rstrip(), "tool")
        elif kind == "tool_result":
            lines = str(d.get("result", "")).splitlines() or [""]
            for ln in lines[:3]:
                self.say(f"  ⎿ {ln[:120]}", "result")
            if len(lines) > 3:
                self.say(f"    … {len(lines) - 3} satır daha", "dim")
        elif kind == "denied":
            self.say(f"reddedildi: {d.get('tool')}", "warn")
        elif kind == "auto_approved":
            self.say(f"oto-onay: {d.get('tool')} {brief(d.get('args') or {})}".rstrip(), "warn")
        elif kind == "warning":
            self.say(f"uyarı: {d.get('message')}", "warn")
        elif kind == "verification":
            self.say(f"doğrulama: {d.get('status')}", "dim")
        elif kind == "compacted":
            self.say(
                f"bağlam sıkıştırıldı (−{d.get('saved_chars')} karakter, eski araç çıktıları özetlendi)",
                "dim",
            )
        elif kind == "breaker":
            if d.get("final"):
                self.say(
                    f"■ Devre kesici: {d.get('reason')} — aynı yaklaşım tekrarlandı, konu sana bırakıldı; yönlendirme bekliyorum.",
                    "error",
                )
            else:
                self.say(
                    f"↺ Devre kesici: {d.get('reason')} — son güvenli duruma dönüldü, model farklı yaklaşım deneyecek.",
                    "warn",
                )
        elif kind == "approval_required":
            self._ask_approval(task, d)

    def _ask_approval(self, task: Task, d: dict) -> None:
        self.say(f"İzin gerekiyor: {d.get('tool')} {brief(d.get('args') or {})}".rstrip(), "warn")
        try:
            ans = self.inp("izin verilsin mi? [e/H] ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            ans = ""
            self.manager.cancel(task.id)
        try:
            self.manager.resolve_approval(d["approval_id"], ans in {"e", "evet", "y", "yes"})
        except KeyError:
            pass  # zaman aşımı/iptal: istek artık geçerli değil

    def _finish(self, task: Task) -> None:
        status = task.status
        if status == "done":
            self.say("✔ bitti", "ok")
        elif status == "cancelled":
            self.say("■ durduruldu", "warn")
        else:
            self.say("✘ başarısız", "error")
        if task.diff:
            self._show_diff(task)
        line = self._token_line(task)
        if line:
            self.say(line, "dim")

    def _show_diff(self, task: Task) -> None:
        if not task.diff:
            self.say("değişiklik yok", "dim")
            return
        s = theme.diff_summary(task.diff)
        self.say(f"Değişiklikler: {s['files']} dosya, +{s['added']} −{s['removed']}", "title")
        print(self.paint.diff(task.diff).rstrip("\n"), file=self.out, flush=True)

    def _token_line(self, task: Task) -> str:
        u = task.usage
        if not u:
            return ""
        total = u["prompt"] + u["completion"]
        cache = f", önbellek %{round(100 * u['cached'] / u['prompt'])}" if u.get("cached") else ""
        text = f"{total} token (girdi {u['prompt']}{cache}, çıktı {u['completion']}) · {u['requests']} istek"
        ctx = u.get("context") or 0
        if ctx and self.context_window:
            text += f" · bağlam {fmt_tokens(ctx)} / {fmt_tokens(self.context_window)} (%{round(100 * ctx / self.context_window)})"
        elif ctx:
            text += f" · bağlam {fmt_tokens(ctx)}"
        return text

    def _next_task(self, task: Task) -> Task | None:
        done = next((e for e in reversed(task.events) if e["type"] == "done"), None)
        nid = (done or {}).get("data", {}).get("next")
        try:
            return self.manager.get(nid) if nid else None
        except KeyError:
            return None

    def _offer_plan(self, plan_task: Task) -> None:
        try:
            ans = (
                self.inp(
                    "Planı uygulayayım mı? [a]şama aşama (oto onay, taze bağlam) / [m]anuel / [o]to onay / [h]ayır: "
                )
                .strip()
                .casefold()
            )
        except (EOFError, KeyboardInterrupt):
            return
        if ans in ("a", "aşama", "asama"):
            self.run_task("Planı aşama aşama uygula", "auto", plan_task=plan_task.id, phased=True)
            return
        mode = MODE_ALIASES.get(ans)
        if mode not in ("manual", "auto"):
            self.say("plan uygulanmadı", "dim")
            return
        self.run_task(
            "Planı uygula", mode, plan_task=plan_task.id
        )  # plan modele bir kez, kimlikle gider
