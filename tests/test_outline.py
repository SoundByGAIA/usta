import pytest

from usta import outline
from usta.policy import Decision, Policy
from usta.tools import ToolContext, ToolError, build_registry

PY = '''import os


def top(a, b=2, *args, **kw) -> int:
    """Üst düzey fonksiyon."""
    return a + b


class Foo(Base):
    """Bir sınıf."""

    def __init__(self, x):
        self.x = x

    @property
    def value(self):
        return self.x

    async def run(self, n: int = 3) -> None:
        await go(n)


@decorator
def decorated():
    pass
'''


def test_python_outline_lists_symbols_with_ranges_and_signatures():
    out = outline.outline_text("a.py", PY)
    assert "a.py" in out and "satır" in out
    assert "def top(a, b=2, *args, **kw) -> int" in out and "Üst düzey fonksiyon." in out
    assert "class Foo(Base)" in out and "def __init__(self, x)" in out
    assert "async def run(self, n: int=3) -> None" in out
    assert "L4-L6" in out  # top
    assert "L9-" in out and "decorated" in out
    foo_line = next(ln for ln in out.splitlines() if "class Foo" in ln)
    init_line = next(ln for ln in out.splitlines() if "__init__" in ln)
    assert len(init_line) - len(init_line.lstrip()) > len(foo_line) - len(
        foo_line.lstrip()
    )  # girinti


def test_outline_is_much_smaller_than_the_source():
    big = "\n".join(
        f"def f{i}(a, b):\n    '''Belge {i}.'''\n"
        + "\n".join(f"    x{j} = a + b + {j}" for j in range(30))
        for i in range(40)
    )
    out = outline.outline_text("big.py", big)
    assert len(out) < len(big) / 5 and "f39" in out


def test_decorated_symbol_range_includes_decorator_line():
    out = outline.outline_text("a.py", PY)
    assert "L23-L25" in next(ln for ln in out.splitlines() if "decorated" in ln)


def test_syntax_error_falls_back_to_generic_outline_with_note():
    out = outline.outline_text("a.py", "def ok(x):\n    return x\n\ndef broken(:\n")
    assert "sözdizimi hatası" in out and "def ok" in out


def test_generic_outline_for_other_languages():
    js = "export function render(a) {\n  return a;\n}\nclass App {}\nconst x = 5;\n"
    out = outline.outline_text("app.js", js)
    assert "function render" in out and "class App" in out and "L1" in out
    go = "package main\n\nfunc (s *S) Run(x int) error {\n\treturn nil\n}\n\ntype S struct{}\n"
    out = outline.outline_text("main.go", go)
    assert "func (s *S) Run" in out and "type S struct" in out


def test_outline_symbol_cap_and_binary_guard():
    many = "\n".join(f"def f{i}(): pass" for i in range(500))
    out = outline.outline_text("m.py", many)
    assert "daha" in out and out.count("def f") <= outline.MAX_SYMBOLS
    with pytest.raises(ValueError):
        outline.outline_text("x.py", "a" * (outline.MAX_BYTES + 1))


def test_read_symbol_function_method_and_class():
    fn = outline.read_symbol("a.py", PY, "top")
    assert "def top" in fn and "return a + b" in fn and "class Foo" not in fn
    m = outline.read_symbol("a.py", PY, "Foo.run")
    assert "async def run" in m and "await go(n)" in m and "def __init__" not in m
    cls = outline.read_symbol("a.py", PY, "Foo")
    assert "class Foo" in cls and "def __init__" in cls and "async def run" in cls
    dec = outline.read_symbol("a.py", PY, "decorated")
    assert "@decorator" in dec


def test_read_symbol_has_line_numbers_header():
    out = outline.read_symbol("a.py", PY, "top")
    assert out.startswith("a.py top: satır 4-6")


def test_read_symbol_unknown_suggests_close_names():
    with pytest.raises(LookupError) as e:
        outline.read_symbol("a.py", PY, "tpo")
    assert "top" in str(e.value)


def test_read_symbol_generic_languages():
    js = "function a() {\n  return 1;\n}\n\nfunction b() {\n  return 2;\n}\n"
    out = outline.read_symbol("x.js", js, "b")
    assert "function b" in out and "return 2" in out and "function a" not in out


def test_line_range_slicing():
    text = "\n".join(f"satir{i}" for i in range(1, 11)) + "\n"
    assert outline.slice_lines(text, 3, 5).splitlines() == [
        "[satır 3-5 / 10]",
        "satir3",
        "satir4",
        "satir5",
    ]
    assert outline.slice_lines(text, 9, 99).splitlines()[0] == "[satır 9-10 / 10]"
    for bad in ((0, 3), (5, 2), (11, 12), (-1, 2)):
        with pytest.raises(ValueError):
            outline.slice_lines(text, *bad)


# --- araçlar ------------------------------------------------------------------------------
@pytest.fixture
def reg(tmp_path):
    (tmp_path / "a.py").write_text(PY)
    return build_registry(ToolContext(root=tmp_path)), tmp_path


def test_tools_registered_and_policy_allows_them_inside_workspace(reg):
    r, root = reg
    names = {s["name"] for s in r.schemas()}
    assert {"outline", "read_symbol", "read_file"} <= names
    p = Policy(root)
    assert p.check("outline", {"path": "a.py"}) == Decision.ALLOW
    assert p.check("read_symbol", {"path": "a.py", "name": "top"}) == Decision.ALLOW
    assert p.check("outline", {"path": "../x.py"}) == Decision.DENY
    assert p.check("read_symbol", {"path": "/etc/passwd", "name": "x"}) == Decision.DENY


def test_outline_and_read_symbol_tools_work(reg):
    r, _ = reg
    assert "def top" in r.call("outline", {"path": "a.py"})
    assert "return a + b" in r.call("read_symbol", {"path": "a.py", "name": "top"})
    with pytest.raises(ToolError, match="top"):
        r.call("read_symbol", {"path": "a.py", "name": "tpo"})
    with pytest.raises(ToolError):
        r.call("outline", {"path": "../disari.py"})
    with pytest.raises(ToolError):
        r.call("outline", {"path": "yok.py"})


def test_read_file_accepts_line_range_and_hints_when_truncated(reg):
    r, root = reg
    out = r.call("read_file", {"path": "a.py", "start": 4, "end": 6})
    assert out.startswith("[satır 4-6") and "def top" in out and "class Foo" not in out
    (root / "büyük.py").write_text("x = 1\n" * 50_000)
    big = build_registry(ToolContext(root=root, max_read=1000)).call(
        "read_file", {"path": "büyük.py"}
    )
    assert "kırpıldı" in big and "outline" in big and "start" in big
    with pytest.raises(ToolError):
        r.call("read_file", {"path": "a.py", "start": 99, "end": 120})
    with pytest.raises(ToolError):
        r.call("read_file", {"path": "a.py", "start": "x", "end": 3})


def test_read_file_plain_behaviour_unchanged(reg):
    r, _ = reg
    assert r.call("read_file", {"path": "a.py"}) == PY
