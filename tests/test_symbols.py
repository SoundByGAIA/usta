"""Tree-sitter sembol çıkarma, proje indeksi, seçici bağlam araçları, geri düşme ve güncellik."""

import os
import time

import pytest

from usta import bench, outline, symbols
from usta.models import ModelResponse
from usta.policy import Decision, Policy
from usta.tools import ToolContext, ToolError, build_registry

pytestmark = pytest.mark.skipif(not symbols.available(), reason="tree-sitter kurulu değil")

PY = '''import os
from x import y


@deco
def pay(a, b):
    """doc"""
    return helper(a) + b.calc()


class Cart:
    def total(self):
        return pay(1, 2)

    class Inner:
        def z(self):
            pass
'''
JS = """import { f } from './f.js';
export function calcTotal(items) { return sum(items) }
const tax = (x) => x * 0.2;
class Cart { add(i) { this.items.push(i); return calcTotal(this.items) } }
"""
TS = """interface Item { id: number }
type Id = number;
enum Color { Red }
export const f = (x: number): number => g(x);
export class C { m(): void { f(1) } }
"""
GO = """package main

import "fmt"

type Server struct{ a int }

type Doer interface{ Do() }

func (s *Server) Handle(x int) int { return helper(x) }

func helper(x int) int { fmt.Println(x); return x }
"""
RS = """use std::io;
struct Cart { n: i32 }
enum E { A }
trait T { fn t(&self); }
impl Cart { fn total(&self) -> i32 { helper(self.n) } }
fn helper(x: i32) -> i32 { x }
mod m { pub fn inner() {} }
"""


def syms(path, text):
    fs = symbols.extract(path, text)
    assert fs is not None and not fs.broken
    return {s.qualname: (s.kind, s.start, s.end) for s in fs.symbols}, fs


# --- çıkarma (Python dışında en az iki dil) ---------------------------------------------------
def test_python_symbols_include_decorators_and_nesting():
    got, fs = syms("a.py", PY)
    assert got["pay"] == ("function", 5, 8)  # dekoratör satırı dahil
    assert (
        got["Cart"][0] == "class"
        and got["Cart.total"][0] == "method"
        and got["Cart.Inner.z"][0] == "method"
    )
    assert fs.calls["pay"] == {"helper", "calc"} and fs.calls["Cart.total"] == {"pay"}
    assert fs.imports == ["import os", "from x import y"]


def test_javascript_symbols_cover_functions_arrows_classes_and_methods():
    got, fs = syms("a.js", JS)
    assert got["calcTotal"][0] == "function" and got["tax"][0] == "function"
    assert got["Cart"][0] == "class" and got["Cart.add"][0] == "method"
    assert fs.calls["calcTotal"] == {"sum"} and "calcTotal" in fs.calls["Cart.add"]


def test_typescript_symbols_cover_types_and_arrow_call_edges():
    got, fs = syms("a.ts", TS)
    assert got["Item"][0] == "interface" and got["Id"][0] == "type" and got["Color"][0] == "enum"
    assert got["f"][0] == "function" and got["C.m"][0] == "method"
    assert fs.calls["f"] == {"g"}  # ifade gövdeli ok işlevinin çağrısı


def test_go_symbols_attach_methods_to_receiver_types():
    got, fs = syms("a.go", GO)
    assert got["Server"][0] == "struct" and got["Doer"][0] == "interface"
    assert got["Server.Handle"][0] == "method" and got["helper"][0] == "function"
    assert fs.calls["Server.Handle"] == {"helper"} and fs.imports == ['"fmt"']


def test_rust_symbols_cover_impl_trait_enum_and_modules():
    got, fs = syms("a.rs", RS)
    assert got["Cart"][0] == "struct" and got["E"][0] == "enum" and got["T"][0] == "trait"
    assert got["Cart.total"][0] == "method" and got["helper"][0] == "function"
    assert got["m"][0] == "module" and got["m.inner"][0] == "function"
    assert fs.calls["Cart.total"] == {"helper"}


def test_extract_returns_none_for_unsupported_huge_or_unparsable_input():
    assert symbols.extract("notes.md", "# başlık") is None
    assert symbols.extract("big.py", "x = 1\n" * (symbols.MAX_FILE_BYTES // 3)) is None
    broken = symbols.extract("b.py", "def f(:\n  pass\nclass C:\n  def m(self): pass\n")
    assert broken is not None and broken.broken  # hata var ama kısmi semboller dönebilir


# --- indeks: çok dosyalı depo ---------------------------------------------------------------
@pytest.fixture
def repo(tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "payment.py").write_text(
        "from shop.tax import vat\n\n\ndef calculate_payment(items):\n    total = sum(i.price for i in items)\n    return total + vat(total)\n"
    )
    (tmp_path / "shop" / "tax.py").write_text("def vat(amount):\n    return amount * 0.2\n")
    (tmp_path / "shop" / "cart.py").write_text(
        "from shop.payment import calculate_payment\n\n\nclass Cart:\n    def checkout(self):\n        return calculate_payment(self.items)\n"
    )
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "api.ts").write_text(
        "export function charge(order: Order) { return calculatePayment(order) }\n"
    )
    (tmp_path / "docs.md").write_text("# kullanım\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function ignored() {}\n")
    return tmp_path


def test_index_finds_definitions_callers_and_callees_across_files(repo):
    idx = symbols.SymbolIndex(repo)
    defs = idx.definitions("calculate_payment")
    assert [(r, s.kind) for r, s in defs] == [("shop/payment.py", "function")]
    assert ("shop/cart.py", "Cart.checkout") in idx.callers("calculate_payment")
    assert [(r, s.qualname) for r, s in idx.callees("shop/payment.py", "calculate_payment")] == [
        ("shop/tax.py", "vat")
    ]
    assert idx.definitions("Cart.checkout") and idx.definitions("checkout")
    assert idx.definitions("ignored") == []  # node_modules atlanır
    assert idx.file_count() == 5  # node_modules içi sayılmaz


def test_related_files_ranks_by_symbols_paths_and_references(repo):
    idx = symbols.SymbolIndex(repo)
    ranked = idx.rank_files("calculate payment total")
    names = [r for r, _, _ in ranked]
    assert names[0] == "shop/payment.py" and "shop/cart.py" in names
    assert "node_modules/x.js" not in names
    assert idx.rank_files("alakasız xyzzy") == [] and idx.rank_files("") == []


def test_index_refreshes_only_changed_files_and_drops_deleted(repo):
    idx = symbols.SymbolIndex(repo)
    idx.refresh()
    first = idx.parse_count
    idx.refresh()
    assert idx.parse_count == first  # değişiklik yok: yeniden ayrıştırma yok
    p = repo / "shop" / "tax.py"
    p.write_text("def vat(amount):\n    return amount * 0.2\n\n\ndef new_fn():\n    return 1\n")
    os.utime(p, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert (
        idx.definitions("new_fn") and idx.parse_count == first + 1
    )  # yalnız o dosya yeniden okundu
    (repo / "shop" / "cart.py").unlink()
    assert idx.callers("calculate_payment") == []  # silinen dosya indeksten düştü
    (repo / "shop" / "fresh.py").write_text("def brand_new():\n    pass\n")
    assert idx.definitions("brand_new")


def test_edits_made_through_tools_are_visible_immediately(repo):
    reg = build_registry(ToolContext(root=repo, symbol_tools=True))
    assert "bulunamadı" in reg.call("find_symbol", {"name": "added_later"})
    reg.call(
        "write_file", {"path": "shop/extra.py", "content": "def added_later():\n    return 2\n"}
    )
    assert "shop/extra.py:L1-L2 function added_later" in reg.call(
        "find_symbol", {"name": "added_later"}
    )
    reg.call("edit_file", {"path": "shop/extra.py", "old": "added_later", "new": "renamed_fn"})
    assert "bulunamadı" in reg.call("find_symbol", {"name": "added_later"})
    assert "renamed_fn" in reg.call("find_symbol", {"name": "renamed_fn"})


# --- araçlar ----------------------------------------------------------------------------------
def test_symbol_context_returns_source_callees_and_callers(repo):
    reg = build_registry(ToolContext(root=repo, symbol_tools=True))
    out = reg.call("symbol_context", {"name": "calculate_payment"})
    assert "shop/payment.py:L4-L6 function calculate_payment" in out
    assert "return total + vat(total)" in out  # gövde
    assert "Çağırdığı proje sembolleri" in out and "shop/tax.py" in out and "vat" in out
    assert "Çağıranlar" in out and "shop/cart.py" in out and "Cart.checkout" in out


def test_symbol_context_lists_candidates_when_ambiguous_and_path_disambiguates(repo):
    (repo / "shop" / "other.py").write_text("def vat(x):\n    return 0\n")
    reg = build_registry(ToolContext(root=repo, symbol_tools=True))
    out = reg.call("symbol_context", {"name": "vat"})
    assert "birden fazla tanım" in out and "shop/other.py" in out and "shop/tax.py" in out
    assert "return amount * 0.2" in reg.call(
        "symbol_context", {"name": "vat", "path": "shop/tax.py"}
    )


def test_symbol_context_budget_truncates_and_expand_widens(tmp_path):
    body = "\n".join(f"    x{i} = helper_{i % 5}({i})" for i in range(150))
    (tmp_path / "big.py").write_text(
        f"def helper_0(a): return a\ndef helper_1(a): return a\ndef big():\n{body}\n"
    )
    reg = build_registry(ToolContext(root=tmp_path, symbol_tools=True, context_budget=1500))
    small = reg.call("symbol_context", {"name": "big"})
    assert len(small) < 1700 and "bağlam bütçesi doldu" in small and "expand=true" in small
    wide = reg.call("symbol_context", {"name": "big", "expand": True})
    assert len(wide) > len(small) and len(wide) < 1500 * 3 + 300


def test_symbol_context_is_much_cheaper_than_reading_the_whole_file(tmp_path):
    funcs = "\n\n".join(
        f"def fn_{i}(a):\n    '''doc {i}'''\n    return a + {i}\n" for i in range(120)
    )
    (tmp_path / "mod.py").write_text(funcs)
    reg = build_registry(ToolContext(root=tmp_path, symbol_tools=True))
    whole = len(reg.call("read_file", {"path": "mod.py"}))
    ctx = reg.call("symbol_context", {"name": "fn_77"})
    assert len(ctx) < whole * 0.1 and "return a + 77" in ctx  # hedef sembol eksiksiz geldi


def test_every_symbol_source_is_complete_in_symbol_context(repo):
    """Seçici bağlam hedef kaynağı kesmemeli (bütçe içinde): her sembolün tüm gövdesi çıktıda olmalı."""
    reg = build_registry(ToolContext(root=repo, symbol_tools=True))
    idx = symbols.SymbolIndex(repo)
    for rel in ("shop/payment.py", "shop/tax.py", "shop/cart.py", "web/api.ts"):
        for s in idx.symbols_of(rel).symbols:
            lines = (repo / rel).read_text().splitlines()[s.start - 1 : s.end]
            out = reg.call("symbol_context", {"name": s.qualname, "path": rel})
            assert all(line in out for line in lines), (rel, s.qualname)


def test_related_files_and_find_symbol_tools_output_and_errors(repo):
    reg = build_registry(ToolContext(root=repo, symbol_tools=True))
    out = reg.call("related_files", {"query": "payment calculation"})
    assert out.splitlines()[0].startswith("shop/payment.py") and "puan" in out
    assert "eşleşen dosya yok" in reg.call("related_files", {"query": "qqqzzz"})
    assert "sembol bulunamadı" in reg.call("symbol_context", {"name": "yok_boyle"})
    with pytest.raises(ToolError):
        reg.call("find_symbol", {"name": ""})
    with pytest.raises(ToolError):
        reg.call("related_files", {"query": 5})


def test_symbol_tools_are_off_by_default(repo):
    reg = build_registry(ToolContext(root=repo))
    names = {s["name"] for s in reg.schemas()}
    assert not names & {"find_symbol", "symbol_context", "related_files"}
    on = {s["name"] for s in build_registry(ToolContext(root=repo, symbol_tools=True)).schemas()}
    assert {"find_symbol", "symbol_context", "related_files"} <= on


def test_policy_treats_symbol_tools_as_read_only_workspace_tools(tmp_path):
    pol = Policy(tmp_path)
    assert pol.check("find_symbol", {"name": "x"}) is Decision.ALLOW
    assert pol.check("symbol_context", {"name": "x", "path": "a/b.py"}) is Decision.ALLOW
    assert pol.check("symbol_context", {"name": "x", "path": "../../etc/passwd"}) is Decision.DENY
    assert pol.check("symbol_context", {"name": "x", "path": "/etc/passwd"}) is Decision.DENY


# --- geri düşme -------------------------------------------------------------------------------
def test_outline_uses_tree_sitter_for_other_languages_and_read_symbol_finds_methods():
    out = outline.outline_text("a.go", GO)
    assert "struct type Server struct" in out and "method func (s *Server) Handle" in out
    assert "L9-L9" in out
    assert "Handle" in outline.read_symbol("a.go", GO, "Server.Handle")
    assert "func helper(x int)" in outline.read_symbol("a.go", GO, "helper")
    js = outline.outline_text("a.js", JS)
    assert "  L4-L4 method" in js.replace("Cart.add", "")  # iç içe yöntem girintili


def test_everything_falls_back_when_tree_sitter_is_unavailable(monkeypatch, repo):
    monkeypatch.setattr(symbols, "_PARSERS", {lang: None for lang in set(symbols.EXT.values())})
    assert not symbols.available() and symbols.extract("a.go", GO) is None
    out = outline.outline_text("a.go", GO)  # regex özetine düştü, çökmedi
    assert "Handle" in out and "struct" not in out.split("\n")[1] or "Handle" in out
    assert "helper" in outline.read_symbol("a.go", GO, "helper")
    with pytest.raises(ValueError, match="usta\\[symbols\\]"):
        build_registry(ToolContext(root=repo, symbol_tools=True))
    assert symbols.SymbolIndex(repo).definitions("calculate_payment") == []


def test_unparsable_and_unsupported_files_do_not_break_the_index(tmp_path):
    (tmp_path / "ok.py").write_text("def good():\n    pass\n")
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe\x00 def (:::\n")
    (tmp_path / "notes.md").write_text("# not\n")
    (tmp_path / "huge.py").write_text("x = 1\n" * 400_000)
    idx = symbols.SymbolIndex(tmp_path)
    assert idx.definitions("good") and idx.file_count() >= 3
    reg = build_registry(ToolContext(root=tmp_path, symbol_tools=True))
    assert "good" in reg.call("find_symbol", {"name": "good"})


def test_syntax_error_in_target_file_is_flagged_in_context(tmp_path):
    (tmp_path / "m.py").write_text("def ok():\n    return 1\n\ndef broken(:\n    pass\n")
    reg = build_registry(ToolContext(root=tmp_path, symbol_tools=True))
    out = reg.call("symbol_context", {"name": "ok"})
    assert "return 1" in out and "sözdizimi hatası" in out


# --- bench kolları ---------------------------------------------------------------------------
class Spy:
    def __init__(self):
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append((messages[0].content, [t["name"] for t in tools or []]))
        return ModelResponse("bitti")


def test_x_full_and_x_sym_arms_define_the_ab_pair():
    full, sym, base = bench.ARMS["X-FULL"], bench.ARMS["X-SYM"], bench.ARMS["B"]
    assert base.tools is None and not base.symbol_tools
    assert full.tools and not {"outline", "read_symbol"} & full.tools
    assert sym.symbol_tools and sym.max_read and "related_files" in (sym.system_prompt or "")
    assert full.experimental and sym.experimental


# --- deneysel bayrak: CLI/TaskManager ---------------------------------------------------------
def test_symbol_tools_flag_reaches_the_registry_and_defaults_off(tmp_path, monkeypatch):
    import argparse

    from usta import cli
    from usta.tasks import TaskManager

    monkeypatch.delenv("USTA_SYMBOL_TOOLS", raising=False)
    assert cli._symbol_tools(argparse.Namespace(symbol_tools=False)) is False
    assert cli._symbol_tools(argparse.Namespace(symbol_tools=True)) is True
    monkeypatch.setenv("USTA_SYMBOL_TOOLS", "1")
    assert cli._symbol_tools(argparse.Namespace(symbol_tools=False)) is True
    assert TaskManager(lambda: None, home=tmp_path / "h").symbol_tools is False
    assert TaskManager(lambda: None, home=tmp_path / "h", symbol_tools=True).symbol_tools is True


def test_symbol_tools_flag_without_package_warns_and_stays_off(monkeypatch, capsys):
    import argparse

    from usta import cli

    monkeypatch.setattr(symbols, "_PARSERS", {lang: None for lang in set(symbols.EXT.values())})
    assert cli._symbol_tools(argparse.Namespace(symbol_tools=True)) is False
    assert "usta[symbols]" in capsys.readouterr().err
