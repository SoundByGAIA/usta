"""Cimri bağlam: dosyayı ham metin olarak vermek yerine sembol özeti (imza + satır aralığı) ve
tek bir sembolün kaynağı. Python için `ast`; diğer diller için satır tabanlı genel özet.
Bağlam penceresi küçük yerel modellerde (4-8K) tüm dosyayı okumak yerine bu araçlar kullanılır.
"""

from __future__ import annotations

import ast
import difflib
import re

MAX_BYTES = 1_000_000
MAX_SYMBOLS = 300
MAX_SYMBOL_LINES = 200

_GENERIC = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:pub(?:\([^)]*\))?\s+)?"
    r"(?:function|class|interface|struct|enum|trait|impl|type|func|fn|def|module|namespace)\b.*"
    r"|^\s*(?:export\s+)?const\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>.*"
)


def _check_size(text: str) -> None:
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise ValueError(f"dosya çok büyük (>{MAX_BYTES} bayt)")


def _py_signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"


def _py_symbols(tree: ast.Module) -> list[tuple[int, str, str, int, int, str]]:
    """(derinlik, nitelikli ad, imza, başlangıç, bitiş, belge) — yalnız sınıf gövdelerine iner."""
    out: list[tuple[int, str, str, int, int, str]] = []

    def walk(body: list[ast.stmt], depth: int, prefix: str) -> None:
        for node in body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            qual = f"{prefix}{node.name}"
            out.append(
                (
                    depth,
                    qual,
                    _py_signature(node),
                    start,
                    node.end_lineno or node.lineno,
                    doc[0][:80] if doc else "",
                )
            )
            if isinstance(node, ast.ClassDef):
                walk(node.body, depth + 1, qual + ".")

    walk(tree.body, 0, "")
    return out


def _generic_symbols(text: str) -> list[tuple[int, str]]:
    return [
        (i, ln.strip().rstrip("{").strip()[:100])
        for i, ln in enumerate(text.splitlines(), 1)
        if _GENERIC.match(ln)
    ]


def outline_text(path: str, text: str) -> str:
    _check_size(text)
    total = len(text.splitlines())
    head = f"{path} ({total} satır)"
    note = ""
    if path.endswith(".py"):
        try:
            syms = _py_symbols(ast.parse(text))
        except SyntaxError as e:
            note = f"(sözdizimi hatası, satır {e.lineno}: genel özet)"
        else:
            lines = [
                f"{'  ' * d}L{s}-L{e} {sig}" + (f"  # {doc}" if doc else "")
                for d, _q, sig, s, e, doc in syms[:MAX_SYMBOLS]
            ]
            if len(syms) > MAX_SYMBOLS:
                lines.append(f"… {len(syms) - MAX_SYMBOLS} sembol daha")
            return "\n".join([head, *lines])
    ts = _ts_outline(path, text)
    if ts is not None:
        return "\n".join(
            [
                head,
                *ts[:MAX_SYMBOLS],
                *([f"… {len(ts) - MAX_SYMBOLS} sembol daha"] if len(ts) > MAX_SYMBOLS else []),
            ]
        )
    gen = _generic_symbols(text)
    lines = [f"L{n} {t}" for n, t in gen[:MAX_SYMBOLS]]
    if len(gen) > MAX_SYMBOLS:
        lines.append(f"… {len(gen) - MAX_SYMBOLS} sembol daha")
    return "\n".join([head, *([note] if note else []), *(lines or ["(sembol bulunamadı)"])])


def read_symbol(path: str, text: str, name: str) -> str:
    _check_size(text)
    src = text.splitlines()
    if path.endswith(".py"):
        try:
            syms = _py_symbols(ast.parse(text))
        except SyntaxError:
            syms = None
        if syms is not None:
            for _d, qual, _sig, s, e, _doc in syms:
                if qual == name:
                    return _render(path, name, s, e, src)
            names = [q for _d, q, *_ in syms]
            bare = {q.rsplit(".", 1)[-1]: q for q in names}
            if name in bare and list(bare).count(name) == 1:
                q = bare[name]
                _d, _q, _sig, s, e, _doc = next(x for x in syms if x[1] == q)
                return _render(path, q, s, e, src)
            raise LookupError(_not_found(name, names))
    fs = _ts_symbols(path, text)
    if fs is not None:
        hit = [s for s in fs.symbols if name in (s.qualname, s.name)]
        if len(hit) == 1:
            return _render(
                path,
                hit[0].qualname,
                hit[0].start,
                min(hit[0].end, hit[0].start + MAX_SYMBOL_LINES - 1),
                src,
            )
        if len(hit) > 1:
            raise LookupError(
                f"'{name}' birden fazla tanımlı: {', '.join(s.qualname for s in hit)}. Nitelikli ad kullan."
            )
    gen = _generic_symbols(text)
    pat = re.compile(rf"\b{re.escape(name)}\b")
    for idx, (line, label) in enumerate(gen):
        if pat.search(label):
            end = (gen[idx + 1][0] - 1) if idx + 1 < len(gen) else len(src)
            while end > line and not src[end - 1].strip():
                end -= 1
            return _render(path, name, line, min(end, line + MAX_SYMBOL_LINES - 1), src)
    raise LookupError(_not_found(name, [lbl for _n, lbl in gen]))


def _ts_symbols(path: str, text: str):
    """Tree-sitter ile semboller (Python dışı diller); paket/dilbilgisi yoksa ya da dosya ayrıştırılamıyorsa None."""
    if path.endswith(".py"):
        return None
    from usta import symbols

    if symbols.language_for(path) is None or not symbols.available(symbols.language_for(path)):
        return None
    fs = symbols.extract(path, text)
    return fs if fs is not None and fs.symbols else None


def _ts_outline(path: str, text: str) -> list[str] | None:
    fs = _ts_symbols(path, text)
    if fs is None:
        return None
    return [
        f"{'  ' * s.qualname.count('.')}L{s.start}-L{s.end} {s.kind} {s.signature}"
        for s in fs.symbols
    ]


def _render(path: str, name: str, start: int, end: int, src: list[str]) -> str:
    return f"{path} {name}: satır {start}-{end}\n" + "\n".join(src[start - 1 : end])


def _not_found(name: str, candidates: list[str]) -> str:
    close = difflib.get_close_matches(name, candidates, n=3, cutoff=0.5)
    hint = f" Benzer: {', '.join(close)}." if close else ""
    return f"sembol bulunamadı: {name}.{hint} Tüm semboller için outline kullan."


def slice_lines(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    n = len(lines)
    if start < 1 or end < start or start > n:
        raise ValueError(f"geçersiz satır aralığı {start}-{end} (dosya {n} satır)")
    end = min(end, n)
    return "\n".join([f"[satır {start}-{end} / {n}]", *lines[start - 1 : end]])
