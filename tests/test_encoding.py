"""Ürün kodundaki her metin dosyası kodlamasını açıkça söyler.

Windows'un varsayılanı UTF-8 değil (cp1254, cp1252); kodlama verilmezse Türkçe karakterler bozulur ya da okuma çöker.
Windows testleri UTF-8 kipinde (PYTHONUTF8=1) koştuğu için bu hatayı orada göremeyiz; bu tarama yakalar.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "usta"


def _text_opens_without_encoding(tree: ast.AST):
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or "encoding" in {k.arg for k in n.keywords}:
            continue
        mode_kw = next((k.value for k in n.keywords if k.arg == "mode"), None)
        if isinstance(n.func, ast.Attribute) and n.func.attr in ("read_text", "write_text"):
            yield n
        elif isinstance(n.func, ast.Name) and n.func.id == "open":  # open(yol, kip)
            mode = mode_kw or (n.args[1] if len(n.args) > 1 else None)
            if mode is None or (isinstance(mode, ast.Constant) and "b" not in mode.value):
                yield n
        elif isinstance(n.func, ast.Attribute) and n.func.attr in ("open", "fdopen"):
            # Path.open(kip) / os.fdopen(fd, kip); webbrowser.open(url) ve os.open(...) dosya metni açmaz
            owner = n.func.value
            if (
                isinstance(owner, ast.Name)
                and owner.id in ("os", "webbrowser")
                and n.func.attr == "open"
            ):
                continue
            args = n.args[1:] if n.func.attr == "fdopen" else n.args
            mode = mode_kw or (args[0] if args else None)
            if (
                mode is None
                and not n.args
                or isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and "b" not in mode.value
            ):
                yield n


def test_text_files_always_name_their_encoding():
    found = [
        f"{f.relative_to(SRC.parent)}:{n.lineno}"
        for f in sorted(SRC.rglob("*.py"))
        for n in _text_opens_without_encoding(ast.parse(f.read_text(encoding="utf-8")))
    ]
    assert found == []


def test_the_scan_catches_the_common_forms():
    code = """
p.read_text()
p.write_text("x")
open("a")
open("a", "w")
p.open()
p.open("w")
os.fdopen(fd, "w")
p.read_text(encoding="utf-8")
p.open("rb")
open("a", "rb")
os.open("a", 0)
webbrowser.open(url)
os.fdopen(fd, "wb")
"""
    lines = sorted(n.lineno for n in _text_opens_without_encoding(ast.parse(code)))
    assert lines == [2, 3, 4, 5, 6, 7, 8]
