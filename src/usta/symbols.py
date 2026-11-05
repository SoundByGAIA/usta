"""Çok dilli sembol çıkarma (Tree-sitter) ve proje sembol indeksi.

Amaç: modele gereksiz kod göndermemek. "Ödeme hesaplama hatasını düzelt" denince ajanın tüm depoyu okuması yerine
ilgili dosyaları, fonksiyonları, sınıfları ve bağımlılıkları (çağırdığı/çağıranlar) seçmesi.

- İsteğe bağlı bağımlılık: `pip install usta[symbols]` (tree-sitter + dil dilbilgileri). Yoksa ya da dosya ayrıştırılamıyorsa
  mevcut regex/AST özetine (outline.py) DÜŞÜLÜR; hiçbir araç çökmez.
- İndeks dosya durumuyla (mtime_ns, boyut) geçersizleşir: ajanın yazdığı ya da `run` ile değişen dosyalar bir sonraki
  sorguda yeniden ayrıştırılır; silinen dosyalar indeksten düşer. Sembol özeti kod değişikliği için tek başına güvenli
  değildir; araçlar bu yüzden her zaman daha geniş okumaya (`expand`, satır aralığı, tam dosya) kontrollü geçiş yolu verir.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 3000
SKIP_DIRS = frozenset({".git", ".usta", "node_modules", ".venv", "venv", "__pycache__", "site-packages", "dist", "build", "target", ".mypy_cache", ".pytest_cache"})  # fmt: skip
SIG_MAX = 160

# uzantı -> dil adı
EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".go": "go", ".rs": "rust",
}  # fmt: skip

_PARSERS: dict[str, object] = {}
_LOAD_ERROR: str | None = None


@dataclass(frozen=True)
class Symbol:
    name: str  # çıplak ad
    qualname: str  # Sınıf.yöntem
    kind: str  # function | method | class | struct | interface | enum | trait | type | module
    start: int  # 1 tabanlı
    end: int
    signature: str
    parent: str | None = None


@dataclass
class FileSymbols:
    path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    calls: dict[str, set[str]] = field(
        default_factory=dict
    )  # qualname (ya da "<modül>") -> çağrılan adlar
    imports: list[str] = field(default_factory=list)
    broken: bool = False  # ayrıştırma hatası içeriyor (kısmi sonuç olabilir)


def language_for(path: str) -> str | None:
    return EXT.get(os.path.splitext(path)[1].lower())


def _load(lang: str):
    """Dil dilbilgisini tembel yükler; paket yoksa None (çağıran düşer)."""
    global _LOAD_ERROR
    if lang in _PARSERS:
        return _PARSERS[lang]
    try:
        from tree_sitter import Language, Parser

        if lang == "python":
            import tree_sitter_python as m

            lang_obj = m.language()
        elif lang == "javascript":
            import tree_sitter_javascript as m

            lang_obj = m.language()
        elif lang == "typescript":
            import tree_sitter_typescript as m

            lang_obj = m.language_typescript()
        elif lang == "tsx":
            import tree_sitter_typescript as m

            lang_obj = m.language_tsx()
        elif lang == "go":
            import tree_sitter_go as m

            lang_obj = m.language()
        elif lang == "rust":
            import tree_sitter_rust as m

            lang_obj = m.language()
        else:
            return None
        _PARSERS[lang] = Parser(Language(lang_obj))
    except Exception as e:  # noqa: BLE001 - eksik paket/uyumsuz sürüm: sessizce düş
        _LOAD_ERROR = f"{type(e).__name__}: {e}"
        _PARSERS[lang] = None
    return _PARSERS[lang]


def available(lang: str | None = None) -> bool:
    """tree-sitter ve (verilirse) o dilin dilbilgisi kurulu mu."""
    if lang is not None:
        return _load(lang) is not None
    return _load("python") is not None


def _text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _sig(node, src: bytes) -> str:
    first = _text(node, src).splitlines()[0].strip() if node.end_byte > node.start_byte else ""
    return first[:SIG_MAX]


def _name(node, src: bytes, field_name: str = "name") -> str | None:
    n = node.child_by_field_name(field_name)
    return _text(n, src) if n is not None else None


# --- dil kuralları -------------------------------------------------------------------------------
def _py(node, src, out: FileSymbols, parent: str | None, calls_ctx: list[str]) -> bool:
    t = node.type
    if t == "decorated_definition":
        inner = node.child_by_field_name("definition")
        if inner is not None:
            _py_def(inner, src, out, parent, calls_ctx, start_node=node)
        return True
    if t in ("function_definition", "class_definition"):
        _py_def(node, src, out, parent, calls_ctx, start_node=node)
        return True
    return False


def _py_def(node, src, out, parent, calls_ctx, start_node) -> None:
    name = _name(node, src)
    if not name:
        return
    is_class = node.type == "class_definition"
    qual = f"{parent}.{name}" if parent else name
    kind = "class" if is_class else "method" if parent and parent in _classes(out) else "function"
    out.symbols.append(
        Symbol(
            name,
            qual,
            kind,
            start_node.start_point[0] + 1,
            node.end_point[0] + 1,
            _sig(node, src),
            parent,
        )
    )
    body = node.child_by_field_name("body")
    if body is None:
        return
    if is_class:
        for ch in body.named_children:
            if not _py(ch, src, out, qual, calls_ctx):
                _walk(ch, src, out, qual, calls_ctx, _py)
    else:
        calls_ctx.append(qual)
        _walk(body, src, out, parent, calls_ctx, _py)
        calls_ctx.pop()


def _classes(out: FileSymbols) -> set[str]:
    return {s.qualname for s in out.symbols if s.kind in ("class", "struct", "interface", "trait")}


def _js(node, src, out, parent, calls_ctx) -> bool:
    t = node.type
    if t == "export_statement":
        for ch in node.named_children:
            _js(ch, src, out, parent, calls_ctx) or _walk(ch, src, out, parent, calls_ctx, _js)
        return True
    if t in ("function_declaration", "generator_function_declaration"):
        _js_add(node, src, out, parent, calls_ctx, "function", _name(node, src), node)
        return True
    if t in ("class_declaration", "abstract_class_declaration"):
        name = _name(node, src)
        if name:
            qual = f"{parent}.{name}" if parent else name
            out.symbols.append(
                Symbol(
                    name,
                    qual,
                    "class",
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                    parent,
                )
            )
            body = node.child_by_field_name("body")
            for ch in body.named_children if body is not None else []:
                if ch.type == "method_definition":
                    _js_add(ch, src, out, qual, calls_ctx, "method", _name(ch, src), ch)
                else:
                    _walk(ch, src, out, qual, calls_ctx, _js)
        return True
    if t in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
        kind = {
            "interface_declaration": "interface",
            "type_alias_declaration": "type",
            "enum_declaration": "enum",
        }[t]
        name = _name(node, src)
        if name:
            out.symbols.append(
                Symbol(
                    name,
                    name,
                    kind,
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                    parent,
                )
            )
        return True
    if t in ("lexical_declaration", "variable_declaration"):
        handled = False
        for d in node.named_children:
            val = d.child_by_field_name("value") if d.type == "variable_declarator" else None
            if val is not None and val.type in (
                "arrow_function",
                "function_expression",
                "function",
                "generator_function",
            ):
                _js_add(val, src, out, parent, calls_ctx, "function", _name(d, src), node)
                handled = True
        return handled
    return False


def _js_add(node, src, out, parent, calls_ctx, kind, name, span_node) -> None:
    if not name:
        return
    qual = f"{parent}.{name}" if parent else name
    out.symbols.append(
        Symbol(
            name,
            qual,
            kind,
            span_node.start_point[0] + 1,
            span_node.end_point[0] + 1,
            _sig(span_node, src),
            parent,
        )
    )
    calls_ctx.append(qual)
    _walk(
        node, src, out, parent, calls_ctx, _js
    )  # gövde ifade olabilir (ok işlevi): düğümün kendisinden yürü
    calls_ctx.pop()


def _go(node, src, out, parent, calls_ctx) -> bool:
    t = node.type
    if t == "function_declaration":
        name = _name(node, src)
        if name:
            out.symbols.append(
                Symbol(
                    name,
                    name,
                    "function",
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                )
            )
            body = node.child_by_field_name("body")
            if body is not None:
                calls_ctx.append(name)
                _walk(body, src, out, None, calls_ctx, _go)
                calls_ctx.pop()
        return True
    if t == "method_declaration":
        name = _name(node, src)
        recv = node.child_by_field_name("receiver")
        rtype = None
        if recv is not None:
            m = re.search(
                r"\*?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*$", _text(recv, src).rstrip(") \t")
            )
            rtype = m.group(1) if m else None
        if name:
            qual = f"{rtype}.{name}" if rtype else name
            out.symbols.append(
                Symbol(
                    name,
                    qual,
                    "method",
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                    rtype,
                )
            )
            body = node.child_by_field_name("body")
            if body is not None:
                calls_ctx.append(qual)
                _walk(body, src, out, None, calls_ctx, _go)
                calls_ctx.pop()
        return True
    if t == "type_declaration":
        for spec in node.named_children:
            if spec.type == "type_spec":
                name = _name(spec, src)
                typ = spec.child_by_field_name("type")
                kind = (
                    "struct"
                    if typ is not None and typ.type == "struct_type"
                    else "interface"
                    if typ is not None and typ.type == "interface_type"
                    else "type"
                )
                if name:
                    out.symbols.append(
                        Symbol(
                            name,
                            name,
                            kind,
                            node.start_point[0] + 1,
                            node.end_point[0] + 1,
                            _sig(node, src),
                        )
                    )
        return True
    return False


def _rust(node, src, out, parent, calls_ctx) -> bool:
    t = node.type
    simple = {
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "type_item": "type",
        "mod_item": "module",
    }
    if t == "function_item":
        name = _name(node, src)
        if name:
            qual = f"{parent}.{name}" if parent else name
            kind = "method" if parent and parent in _classes(out) else "function"
            out.symbols.append(
                Symbol(
                    name,
                    qual,
                    kind,
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                    parent,
                )
            )
            body = node.child_by_field_name("body")
            if body is not None:
                calls_ctx.append(qual)
                _walk(body, src, out, parent, calls_ctx, _rust)
                calls_ctx.pop()
        return True
    if t in simple:
        name = _name(node, src)
        if name:
            qual = f"{parent}.{name}" if parent and t == "mod_item" else name
            out.symbols.append(
                Symbol(
                    name,
                    qual,
                    simple[t],
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                    _sig(node, src),
                    parent,
                )
            )
            if t in ("mod_item", "trait_item"):
                body = node.child_by_field_name("body")
                for ch in body.named_children if body is not None else []:
                    _rust(ch, src, out, qual, calls_ctx) or _walk(
                        ch, src, out, qual, calls_ctx, _rust
                    )
        return True
    if t == "impl_item":
        typ = node.child_by_field_name("type")
        tname = _text(typ, src).split("<")[0].strip() if typ is not None else None
        body = node.child_by_field_name("body")
        for ch in body.named_children if body is not None else []:
            _rust(ch, src, out, tname, calls_ctx) or _walk(ch, src, out, tname, calls_ctx, _rust)
        return True
    return False


_RULES = {"python": _py, "javascript": _js, "typescript": _js, "tsx": _js, "go": _go, "rust": _rust}
_CALL = {
    "python": ("call", "function"), "javascript": ("call_expression", "function"), "typescript": ("call_expression", "function"),
    "tsx": ("call_expression", "function"), "go": ("call_expression", "function"), "rust": ("call_expression", "function"),
}  # fmt: skip
_IMPORT = {
    "python": ("import_statement", "import_from_statement"), "javascript": ("import_statement",), "typescript": ("import_statement",),
    "tsx": ("import_statement",), "go": ("import_spec",), "rust": ("use_declaration",),
}  # fmt: skip


def _callee(fn, src: bytes) -> str | None:
    """Çağrının hedef adı: `a.b.c(...)` -> c, `f(...)` -> f, `pkg::f` -> f."""
    if fn is None:
        return None
    if fn.type in ("identifier", "property_identifier", "field_identifier", "type_identifier"):
        return _text(fn, src)
    for key in ("attribute", "property", "field", "name"):
        n = fn.child_by_field_name(key)
        if n is not None:
            return _text(n, src)
    txt = _text(fn, src)
    m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", txt)
    return m.group(1) if m else None


def _walk(node, src, out: FileSymbols, parent, calls_ctx: list[str], rule) -> None:
    lang = out.language
    call_t, call_f = _CALL[lang]
    for ch in node.named_children:
        if ch.type == call_t:
            callee = _callee(ch.child_by_field_name(call_f), src)
            if callee:
                out.calls.setdefault(calls_ctx[-1] if calls_ctx else "<modül>", set()).add(callee)
        if ch.type in _IMPORT[lang]:
            out.imports.append(_sig(ch, src))
            continue
        if rule(ch, src, out, parent, calls_ctx):
            continue
        _walk(ch, src, out, parent, calls_ctx, rule)


def extract(path: str, text: str) -> FileSymbols | None:
    """Dosyadan semboller/çağrılar/içe aktarmalar. Desteklenmeyen dil, eksik paket ya da dev dosya: None (çağıran düşer)."""
    lang = language_for(path)
    if lang is None or len(text) > MAX_FILE_BYTES:
        return None
    parser = _load(lang)
    if parser is None:
        return None
    src = text.encode("utf-8", "replace")
    try:
        tree = parser.parse(src)
    except Exception:  # noqa: BLE001
        return None
    out = FileSymbols(path, lang, broken=tree.root_node.has_error)
    _walk(tree.root_node, src, out, None, [], _RULES[lang])
    out.symbols.sort(key=lambda s: (s.start, s.end))
    return out


# --- proje indeksi -------------------------------------------------------------------------------
_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+")
STOP = frozenset({"the", "a", "an", "of", "to", "in", "for", "and", "or", "bir", "ve", "ile", "için", "bu", "şu", "hata", "hatası", "düzelt", "fix", "bug"})  # fmt: skip


def tokens(text: str) -> list[str]:
    """camelCase/snake_case/kebab ayrıştırır, küçük harfe çevirir, kısa/dolgu sözcükleri atar."""
    out = []
    for w in _WORD.findall(text.replace("_", " ")):
        for part in re.sub(r"(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", " ", w).split():
            p = part.lower()
            if len(p) >= 3 and p not in STOP:
                out.append(p)
    return out


@dataclass
class _Entry:
    stamp: tuple[int, int]
    data: FileSymbols | None  # None: desteklenmeyen/ayrıştırılamayan dosya (yalnız yol eşleşmesi)


class SymbolIndex:
    """Çalışma alanının sembol indeksi; her sorguda dosya durumuna göre kendini tazeler."""

    def __init__(self, root: Path, *, max_files: int = MAX_FILES):
        self.root = Path(root).resolve()
        self.max_files = max_files
        self._files: dict[str, _Entry] = {}
        self.parse_count = 0  # test/ölçüm: kaç dosya ayrıştırıldı

    # -- tazeleme --
    def _scan(self) -> dict[str, tuple[int, int]]:
        seen: dict[str, tuple[int, int]] = {}
        stack = [self.root]
        while stack and len(seen) < self.max_files:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in SKIP_DIRS:
                                stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            if st.st_size <= MAX_FILE_BYTES:
                                seen[os.path.relpath(e.path, self.root)] = (
                                    st.st_mtime_ns,
                                    st.st_size,
                                )
            except OSError:
                continue
        return seen

    def refresh(self) -> int:
        """Değişen/yeni dosyaları yeniden ayrıştırır, silinenleri düşürür; yeniden ayrıştırılan dosya sayısını döner."""
        seen = self._scan()
        for gone in set(self._files) - set(seen):
            del self._files[gone]
        changed = 0
        for rel, stamp in seen.items():
            cur = self._files.get(rel)
            if cur is not None and cur.stamp == stamp:
                continue
            data = None
            if language_for(rel):
                try:
                    data = extract(
                        rel, (self.root / rel).read_text(encoding="utf-8", errors="replace")
                    )
                except OSError:
                    data = None
                self.parse_count += 1
            self._files[rel] = _Entry(stamp, data)
            changed += 1
        return changed

    # -- sorgular --
    def symbols_of(self, rel: str) -> FileSymbols | None:
        self.refresh()
        e = self._files.get(rel)
        return e.data if e else None

    def definitions(self, name: str) -> list[tuple[str, Symbol]]:
        """Ada göre tanımlar: tam eşleşme (çıplak ya da nitelikli) önce, sonra büyük/küçük harf duyarsız, sonra içerir."""
        self.refresh()
        exact, loose, sub = [], [], []
        low = name.lower()
        for rel, e in sorted(self._files.items()):
            for s in e.data.symbols if e.data else ():
                if name in (s.name, s.qualname):
                    exact.append((rel, s))
                elif low in (s.name.lower(), s.qualname.lower()):
                    loose.append((rel, s))
                elif low in s.qualname.lower():
                    sub.append((rel, s))
        return exact or loose or sub

    def callers(self, name: str) -> list[tuple[str, str]]:
        self.refresh()
        out = []
        for rel, e in sorted(self._files.items()):
            for who, callees in e.data.calls.items() if e.data else ():
                if name in callees:
                    out.append((rel, who))
        return out

    def callees(self, rel: str, qualname: str) -> list[tuple[str, Symbol]]:
        """Bu sembolün çağırdığı, PROJEDE tanımlı sembollerin tanımları."""
        fs = self.symbols_of(rel)
        if fs is None:
            return []
        out, seen = [], set()
        for callee in sorted(fs.calls.get(qualname, ())):
            for drel, sym in self.definitions(callee)[:2]:
                if (drel, sym.qualname) not in seen and not (
                    drel == rel and sym.qualname == qualname
                ):
                    seen.add((drel, sym.qualname))
                    out.append((drel, sym))
        return out

    def rank_files(self, query: str, limit: int = 8) -> list[tuple[str, float, str]]:
        """Görev metnine göre dosya önceliği: sembol adı eşleşmesi > yol eşleşmesi > çağrı/içe aktarma eşleşmesi."""
        self.refresh()
        q = set(tokens(query))
        if not q:
            return []
        scored = []
        for rel, e in self._files.items():
            path_hits = q & set(tokens(rel))
            sym_hits: set[str] = set()
            ref_hits: set[str] = set()
            if e.data:
                for s in e.data.symbols:
                    sym_hits |= q & set(tokens(s.qualname))
                for callees in e.data.calls.values():
                    for c in callees:
                        ref_hits |= q & set(tokens(c))
                for imp in e.data.imports:
                    ref_hits |= q & set(tokens(imp))
            score = 3.0 * len(sym_hits) + 2.0 * len(path_hits) + 1.0 * len(ref_hits)
            if score:
                why = ", ".join(
                    p for p in (
                        f"sembol: {', '.join(sorted(sym_hits))}" if sym_hits else "",
                        f"yol: {', '.join(sorted(path_hits))}" if path_hits else "",
                        f"referans: {', '.join(sorted(ref_hits))}" if ref_hits else "",
                    ) if p
                )  # fmt: skip
                scored.append((rel, score, why))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:limit]

    def file_count(self) -> int:
        self.refresh()
        return len(self._files)
