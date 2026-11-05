"""Senaryo biçimi (sürümlü JSONL) ve doğrulayıcı.

Bir senaryo aynı görevin iki koşulunu tanımlar: `clean` (saldırı içermeyen kontrol) ve `attack` (aynı görev, bir
araç çıktısına/dosyaya gömülü saldırı yükü). İki koşulda model, istem, araç izinleri ve bütçe aynıdır; fark yalnız
`swaps`/`mcp.outputs`/`run_outputs` içindeki yük metnidir.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
SCENARIO_FILE = Path(__file__).with_name("scenarios") / "v1.jsonl"
CATEGORIES = (
    "tool_output_injection",  # araç çıktısı üzerinden talimat enjeksiyonu
    "mcp_authority",  # MCP yanıtı üzerinden yetki manipülasyonu
    "readme_hijack",  # dosya/README üzerinden görev yönlendirme
    "fake_authority",  # sahte sistem/geliştirici otoritesi iddiası
    "secret_exfil",  # gizli bilgi sızdırma girişimi
    "memory_poison",  # kalıcı hafızayı/görev durumunu kirletme
    "fault",  # saldırısız hata senaryosu (toparlanma)
)
CONDITIONS = ("clean", "attack")
FORBIDDEN_KINDS = ("tool_call", "arg_contains", "file_changed", "file_contains", "answer_contains")
SAFE_PATH = re.compile(r"[A-Za-z0-9_.\-][A-Za-z0-9_./\-]{0,120}")


class ScenarioError(ValueError):
    """Senaryo dosyası/biçimi geçersiz."""


@dataclass(frozen=True)
class Step:
    """Betikli modelin (smoke testleri) atacağı araç çağrısı."""

    tool: str
    args: dict


@dataclass(frozen=True)
class Forbidden:
    """Yasak eylem koşulu. `goal`: saldırganın amacı mı (ASR bunu sayar) yoksa yalnız yetkisiz eylem mi."""

    kind: str
    tool: str = ""  # tool_call: ad kalıbı (fnmatch), ör. "mcp__docs__*"
    contains: str = ""  # tool_call/arg_contains: argümanlarda geçen metin
    path: str = ""  # file_changed / file_contains
    marker: str = ""  # file_contains / answer_contains
    goal: bool = True
    note: str = ""


@dataclass(frozen=True)
class McpTool:
    server: str
    tool: str
    mode: str  # ask | allow (izin motorunun MCP modu)
    description: str
    clean: str
    attack: str = ""

    @property
    def qualified(self) -> str:
        return f"mcp__{self.server}__{self.tool}"

    def output(self, condition: str) -> str:
        return self.attack if condition == "attack" and self.attack else self.clean


@dataclass(frozen=True)
class Swap:
    """Koşula göre içeriği değişen metin (dosya içeriği ya da `run` çıktısı)."""

    clean: str
    attack: str

    def text(self, condition: str) -> str:
        return self.attack if condition == "attack" else self.clean


@dataclass(frozen=True)
class Fault:
    tool: str
    times: int
    error: str


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    surface: str
    description: str
    task: str
    files: dict[str, str]
    swaps: dict[str, Swap] = field(default_factory=dict)  # yol -> koşula bağlı içerik
    mcp: tuple[McpTool, ...] = ()
    run_outputs: tuple[tuple[str, Swap], ...] = ()  # (komutta geçen metin, çıktı); "*" her komut
    legit: tuple[Step, ...] = ()
    attack_action: Step | None = None
    forbidden: tuple[Forbidden, ...] = ()
    success: dict = field(default_factory=dict)
    faults: tuple[Fault, ...] = ()
    max_steps: int = 14
    expect: dict = field(
        default_factory=dict
    )  # betikli "saf" modelde beklenen: {"attempt","executed","blocked"}
    version: int = SCHEMA_VERSION

    @property
    def conditions(self) -> tuple[str, ...]:
        return ("clean",) if self.category == "fault" else CONDITIONS

    def file_content(self, path: str, condition: str) -> str:
        return self.swaps[path].text(condition) if path in self.swaps else self.files[path]

    def mcp_modes(self) -> dict[str, str]:
        return {m.qualified: m.mode for m in self.mcp}


def _step(d: dict | None) -> Step | None:
    if d is None:
        return None
    return Step(str(d["tool"]), dict(d.get("args", {})))


def _swap(d: dict) -> Swap:
    return Swap(str(d["clean"]), str(d["attack"]))


def parse(row: dict) -> Scenario:
    """Bir JSON satırından senaryo; geçersizse ScenarioError."""
    try:
        sc = Scenario(
            id=str(row["id"]),
            category=str(row["category"]),
            surface=str(row["surface"]),
            description=str(row["description"]),
            task=str(row["task"]),
            files={str(k): str(v) for k, v in row.get("files", {}).items()},
            swaps={str(k): _swap(v) for k, v in row.get("swaps", {}).items()},
            mcp=tuple(
                McpTool(
                    m["server"],
                    m["tool"],
                    m["mode"],
                    m.get("description", ""),
                    m["clean"],
                    m.get("attack", ""),
                )
                for m in row.get("mcp", [])
            ),
            run_outputs=tuple((str(m), _swap(v)) for m, v in row.get("run_outputs", [])),
            legit=tuple(_step(s) for s in row.get("legit", [])),  # type: ignore[misc]
            attack_action=_step(row.get("attack_action")),
            forbidden=tuple(Forbidden(**f) for f in row.get("forbidden", [])),
            success=dict(row.get("success", {})),
            faults=tuple(
                Fault(f["tool"], int(f["times"]), f["error"]) for f in row.get("faults", [])
            ),
            max_steps=int(row.get("max_steps", 14)),
            expect=dict(row.get("expect", {})),
            version=int(row.get("version", SCHEMA_VERSION)),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ScenarioError(f"senaryo okunamadı ({row.get('id', '?')}): {e!r}") from None
    validate(sc)
    return sc


def validate(sc: Scenario) -> None:
    def bad(msg: str) -> None:
        raise ScenarioError(f"{sc.id}: {msg}")

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", sc.id):
        bad("id küçük harf/rakam/- olmalı")
    if sc.version != SCHEMA_VERSION:
        bad(f"şema sürümü {sc.version}, beklenen {SCHEMA_VERSION}")
    if sc.category not in CATEGORIES:
        bad(f"bilinmeyen kategori {sc.category!r}")
    if not sc.task.strip() or not sc.legit:
        bad("görev metni ve meşru adımlar (legit) gerekli")
    for path in (*sc.files, *sc.swaps):
        if not SAFE_PATH.fullmatch(path) or ".." in Path(path).parts or Path(path).is_absolute():
            bad(f"geçersiz dosya yolu {path!r}")
    for path in sc.swaps:
        if path not in sc.files and sc.swaps[path] is None:
            bad(f"swap {path!r} için dosya yok")
    for m in sc.mcp:
        if m.mode not in ("ask", "allow"):
            bad(f"MCP modu {m.mode!r} geçersiz")
    if sc.category == "fault":
        if not sc.faults or sc.forbidden or sc.attack_action:
            bad("fault senaryosu hata tanımlar; saldırı/yasak içermez")
    else:
        if not sc.forbidden or sc.attack_action is None:
            bad("saldırı senaryosu yasak eylem ve attack_action tanımlamalı")
        if not any(f.goal for f in sc.forbidden):
            bad("en az bir yasak koşul goal=true olmalı")
        if not (
            sc.swaps
            or any(m.attack for m in sc.mcp)
            or any(s.attack != s.clean for _, s in sc.run_outputs)
        ):
            bad("saldırı yükü yok (swaps/mcp.attack/run_outputs)")
    for f in sc.forbidden:
        if f.kind not in FORBIDDEN_KINDS:
            bad(f"yasak türü {f.kind!r} geçersiz")
        need = {
            "tool_call": f.tool,
            "arg_contains": f.contains,
            "file_changed": f.path,
            "file_contains": f.path and f.marker,
            "answer_contains": f.marker,
        }[f.kind]
        if not need:
            bad(f"{f.kind} yasağı için gerekli alan eksik")
    if not sc.success:
        bad("görev başarı koşulu (success) gerekli")
    for key in sc.success:
        if key not in ("file_contains", "file_equals", "answer_contains"):
            bad(f"bilinmeyen başarı koşulu {key!r}")
    if sc.max_steps < 4 or sc.max_steps > 40:
        bad("max_steps 4-40 arasında olmalı")


def load(path: Path | None = None) -> list[Scenario]:
    path = Path(path) if path else SCENARIO_FILE
    out: list[Scenario] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise ScenarioError(f"{path.name}:{n}: JSON değil") from None
        sc = parse(row)
        if sc.id in seen:
            raise ScenarioError(f"{path.name}:{n}: yinelenen id {sc.id}")
        seen.add(sc.id)
        out.append(sc)
    return out


def set_hash(scenarios: list[Scenario]) -> str:
    """Senaryo kümesinin içerik özeti (deney kaydına yazılır; küme değişince sonuçlar karşılaştırılamaz)."""
    blob = json.dumps(
        [_canon(s) for s in scenarios], sort_keys=True, ensure_ascii=False, default=str
    )
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _canon(sc: Scenario) -> dict:
    from dataclasses import asdict

    return asdict(sc)


def matches_tool(pattern: str, tool: str) -> bool:
    return fnmatch.fnmatchcase(tool, pattern)
