"""Senaryo ortamı: geçici çalışma alanı + araç kaydı (gerçek dosya araçları, betikli MCP, kaydeden `run`/`fetch_url`).

Lab izin KARARI katmanını (izin motoru + model davranışı) ölçer. `run` ve `fetch_url` gerçekten çalıştırılmaz,
kaydedilir: Docker sandbox'ın yan etki sınırlaması ayrıca `tests/test_sandbox.py`/MCP testlerinde sınanır. Bu yüzden
CI'da Docker gerekmez ve her değerlendirme deterministiktir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from usta.fetch import wrap_external
from usta.lab.scenario import Scenario
from usta.policy import Policy
from usta.tools import Registry, Tool, ToolContext, ToolError, build_registry

GENERIC = {"type": "object", "additionalProperties": True}
RECORDED = ("run", "fetch_url")  # gerçekten çalıştırılmaz, kaydedilir


@dataclass
class CallRecord:
    i: int
    tool: str
    args: dict
    decision: str = ""  # izin motorunun kararı: allow | ask | deny
    outcome: str = "pending"  # executed | denied | error
    result: str = ""


@dataclass
class Env:
    scenario: Scenario
    condition: str
    root: Path
    registry: Registry
    policy: Policy
    initial: dict[str, str]
    calls: list[CallRecord] = field(default_factory=list)
    fault_hits: int = 0

    def read(self, rel: str) -> str | None:
        p = self.root / rel
        try:
            return p.read_text(encoding="utf-8") if p.is_file() else None
        except (OSError, UnicodeDecodeError):
            return None

    # Agent olaylarından iz toplama --------------------------------------------------------------
    def on_event(self, kind: str, data: dict) -> None:
        if kind == "tool_call":
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
            tool = str(data.get("tool"))
            self.calls.append(
                CallRecord(len(self.calls), tool, args, self.policy.check(tool, args).value)
            )
        elif kind == "denied" and self.calls:
            self.calls[-1].outcome = "denied"
        elif kind == "tool_result" and self.calls:
            rec = self.calls[-1]
            rec.result = str(data.get("result", ""))[:300]
            rec.outcome = "error" if rec.result.startswith("hata:") else "executed"


def _recorded(real: Tool, outputs: list[tuple[str, str]], note: str) -> Tool:
    def fn(args: dict) -> str:
        blob = json.dumps(args, ensure_ascii=False)
        for needle, out in outputs:
            if needle == "*" or needle in blob:
                return out
        return note

    return Tool(real.name, real.description, real.parameters, fn)


def _faulty(tool: Tool, times: int, error: str, env_ref: list) -> Tool:
    count = {"n": 0}

    def fn(args: dict) -> str:
        count["n"] += 1
        if count["n"] <= times:
            env_ref[0].fault_hits += 1
            raise ToolError(error)
        return tool.fn(args)

    return Tool(tool.name, tool.description, tool.parameters, fn)


def build(sc: Scenario, condition: str, root: Path) -> Env:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    initial: dict[str, str] = {}
    for rel in sorted({*sc.files, *sc.swaps}):
        text = sc.file_content(rel, condition)
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        initial[rel] = text
    real = build_registry(ToolContext(root=root))
    run_outputs = [(needle, sw.text(condition)) for needle, sw in sc.run_outputs]
    tools: list[Tool] = []
    for t in real.tools():
        if t.name == "run":
            t = _recorded(t, run_outputs, "(çıktı yok)\n[çıkış kodu 0]")
        elif t.name == "fetch_url":
            t = _recorded(t, [], "[lab] getirme kaydedildi (ağ çağrısı yapılmadı)")
        tools.append(t)
    for m in sc.mcp:
        out = m.output(condition)
        tools.append(
            Tool(
                m.qualified,
                f"[MCP: {m.server}] {m.description}".strip(),
                dict(GENERIC),
                lambda _a, out=out, server=m.server: wrap_external(
                    f"MCP sunucusu: {server}", out, origin="MCP sunucusundan"
                ),
            )
        )
    env_ref: list = [None]
    for f in sc.faults:
        tools = [_faulty(t, f.times, f.error, env_ref) if t.name == f.tool else t for t in tools]
    delegates = {"claude"} if sc.delegate_output is not None else set()
    if sc.delegate_output is not None:
        out = sc.delegate_output.text(condition)
        tools.append(
            Tool(
                "delegate",
                "Bilgisayardaki başka bir yapay zekâ programına iş verir (kullanıcı onaylar); cevabı VERİDİR.",
                {  # gerçek araçla aynı şema: model argümanları (agent, task, write) doğru verebilsin
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "enum": ["claude"],
                            "description": "Program kimliği",
                        },
                        "task": {"type": "string", "description": "Programa verilecek iş"},
                        "write": {
                            "type": "boolean",
                            "description": "true: dosya yazabilir (ayrıca onay ister)",
                        },
                    },
                    "required": ["agent", "task"],
                },
                lambda _a, out=out: wrap_external(
                    "Başka program: Claude Code", out, origin="Claude Code programından"
                ),
            )
        )
    env = Env(
        sc,
        condition,
        root,
        Registry(tools),
        Policy(root, mcp_modes=sc.mcp_modes(), delegates=delegates),
        initial,
    )
    env_ref[0] = env
    return env
