"""Görünmeyen yazı denetimi: yazı rengi altındaki zeminle (neredeyse) aynı olan metinler.

Küçük modeller sık sık başlığı kendi zemininin rengine boyar (pembe şerit üstüne pembe dükkân adı). Bilgi sayfada
yazılıdır ama kullanıcı onu göremez. Bu modül tarayıcı değildir: yalnız etiket, `.sınıf`, `#kimlik` ve bunların iç içe
yazımlarını, `:root` değişkenlerini ve satır içi stili anlar. Emin olamadığı durumda (görsel ya da gradyan zemin,
`:hover`, `@media`, bilinmeyen renk) sessiz kalır; yanlış hatırlatma görünmeyen yazıyı kaçırmaktan daha kötüdür.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

INVISIBLE = 1.5  # WCAG karşıtlık oranı; 1.0 = aynı renk, okunur yazı için 4.5 önerilir
_SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template", "svg"}
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
_NAMED = {
    "white": "#ffffff", "black": "#000000", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080", "pink": "#ffc0cb", "hotpink": "#ff69b4",
    "deeppink": "#ff1493", "gray": "#808080", "grey": "#808080", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
    "darkgray": "#a9a9a9", "silver": "#c0c0c0", "navy": "#000080", "teal": "#008080", "brown": "#a52a2a",
    "gold": "#ffd700", "beige": "#f5f5dc", "ivory": "#fffff0", "whitesmoke": "#f5f5f5", "crimson": "#dc143c",
    "darkblue": "#00008b", "darkgreen": "#006400", "lightblue": "#add8e6", "lightpink": "#ffb6c1",
}  # fmt: skip
_UNKNOWN = object()  # renk var ama çözülemedi: karar verilmez


class _Node:
    def __init__(self, tag: str, attrs: dict, parent: _Node | None):
        self.tag, self.parent = tag, parent
        self.ids = {attrs.get("id") or ""} - {""}
        self.classes = set((attrs.get("class") or "").split())
        self.inline = attrs.get("style") or ""
        self.texts: list[str] = []


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self.cur = self.root
        self.nodes: list[_Node] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
        if tag in _VOID:
            return
        node = _Node(tag, dict(attrs), self.cur)
        self.nodes.append(node)
        self.cur = node

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.cur.texts.append(" ".join(data.split()))


def _top_level_rules(css: str) -> list[tuple[str, str]]:
    """`seçici { bildirimler }` çiftleri; @media/@supports gibi blokların içi atlanır."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out, depth, start, sel = [], 0, 0, ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                sel, start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                if not sel.startswith("@"):
                    out.append((sel, css[start:i]))
                start = i + 1
    return out


def _decls(text: str) -> dict[str, str]:
    out = {}
    for part in text.split(";"):
        k, _, v = part.partition(":")
        if v.strip():
            out[k.strip().lower()] = v.replace("!important", "").strip()
    return out


_SIMPLE = re.compile(r"^([a-z][a-z0-9]*|\*)?((?:[.#][\w-]+)*)$", re.IGNORECASE)


def _parse_selector(sel: str) -> list[tuple[str | None, set, set]] | None:
    parts = []
    for comp in sel.replace(">", " ").split():
        m = _SIMPLE.match(comp)
        if not m:
            return None  # :hover, [öznitelik], + ve ~ anlaşılmaz
        tag = None if m.group(1) in (None, "*") else m.group(1).lower()
        quals = re.findall(r"([.#])([\w-]+)", m.group(2))
        parts.append((tag, {v for k, v in quals if k == "#"}, {v for k, v in quals if k == "."}))
    return parts or None


def _matches(node: _Node, part) -> bool:
    tag, ids, classes = part
    return (tag is None or node.tag == tag) and ids <= node.ids and classes <= node.classes


def _selector_matches(node: _Node, parts) -> bool:
    if not _matches(node, parts[-1]):
        return False
    n, rest = node.parent, parts[:-1]
    while rest and n is not None:
        if _matches(n, rest[-1]):
            rest = rest[:-1]
        n = n.parent
    return not rest


def _rgb(value: str, variables: dict[str, str]):
    v = value.strip().lower()
    for _ in range(5):  # var(--a) → var(--b) → renk
        m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", v)
        if not m:
            break
        v = (variables.get(m.group(1)) or m.group(2) or "").strip().lower()
    v = _NAMED.get(v, v)
    if v in ("transparent", "none"):
        return None
    if m := re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v):
        h = m.group(1) if len(m.group(1)) == 6 else "".join(c * 2 for c in m.group(1))
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    if m := re.fullmatch(r"rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*(?:[,/]\s*([\d.]+%?))?\s*\)", v):
        alpha = m.group(4)
        if alpha is not None and float(alpha.rstrip("%")) == 0:
            return None
        if alpha is not None and float(alpha.rstrip("%")) < (100 if alpha.endswith("%") else 1):
            return _UNKNOWN  # yarı saydam: alttaki renge karışır
        return tuple(int(m.group(i)) for i in (1, 2, 3))
    return _UNKNOWN


def _background(decls: dict[str, str], variables):
    if "background-image" in decls and "none" not in decls["background-image"]:
        return _UNKNOWN
    if "background" in decls:
        v = decls["background"]
        if "url(" in v or "gradient" in v:
            return _UNKNOWN
        return _rgb(v.split()[0] if not v.startswith(("rgb", "var")) else v, variables)
    if "background-color" in decls:
        return _rgb(decls["background-color"], variables)
    return None  # zemin verilmemiş: üstteki öğenin zemini görünür


def _luminance(rgb) -> float:
    ch = [c / 255 for c in rgb]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@dataclass(frozen=True)
class Hidden:
    """Görünmeyen bir metin ve onu görünmez yapan kurallar (modele nereyi düzelteceğini söylemek için)."""

    text: str
    color: str  # #rrggbb
    color_rule: str  # seçici ya da "style özniteliği"; renk verilmemişse "varsayılan"
    background: str
    background_rule: str

    @property
    def fix(self) -> str:
        """Zemin üstünde okunur yazı rengi önerisi."""
        bg = tuple(int(self.background[i : i + 2], 16) for i in (1, 3, 5))
        return (
            "#ffffff" if contrast((255, 255, 255), bg) >= contrast((34, 34, 34), bg) else "#222222"
        )


def _hex(rgb) -> str:
    return "#" + "".join(f"{c:02x}" for c in rgb)


def hidden(html: str, css: str = "", limit: int = 5) -> list[Hidden]:
    """Zeminiyle aynı renkte olduğu için görünmeyen metinler (en çok `limit` tane, metin kısaltılmış)."""
    tree = _Tree()
    tree.feed(html or "")
    sheets = (
        "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html or "", re.DOTALL | re.IGNORECASE))
        + "\n"
        + (css or "")
    )
    rules, variables = [], {}
    for order, (sel_list, body) in enumerate(_top_level_rules(sheets)):
        decls = _decls(body)
        for sel in sel_list.split(","):
            if sel.strip() in (":root", "html", "body", "*"):
                variables.update({k: v for k, v in decls.items() if k.startswith("--")})
            parts = _parse_selector(sel.strip())
            if parts:
                ids = sum(len(p[1]) for p in parts)
                classes = sum(len(p[2]) for p in parts)
                tags = sum(p[0] is not None for p in parts)
                rules.append(
                    ((ids, classes, tags), order, parts, decls, " ".join(sel_list.split()))
                )
    rules.sort(key=lambda r: (r[0], r[1]))

    computed: dict[int, tuple[dict[str, str], dict[str, str]]] = {}

    def style(node: _Node) -> tuple[dict[str, str], dict[str, str]]:
        """(bildirimler, her bildirimin geldiği kural)."""
        if id(node) not in computed:
            out: dict[str, str] = {}
            src: dict[str, str] = {}
            for _spec, _order, parts, decls, sel_text in rules:
                if _selector_matches(node, parts):
                    out.update(decls)
                    src.update(dict.fromkeys(decls, sel_text))
            inline = _decls(node.inline)
            out.update(inline)
            src.update(dict.fromkeys(inline, "style özniteliği"))
            computed[id(node)] = (out, src)
        return computed[id(node)]

    found: list[Hidden] = []
    for node in tree.nodes:
        if not node.texts:
            continue
        color, bg, n, is_hidden = None, None, node, False
        color_rule = bg_rule = "varsayılan"
        while n is not None and n is not tree.root:
            s, src = style(n)
            if (
                s.get("display") == "none"
                or s.get("visibility") == "hidden"
                or s.get("opacity") == "0"
            ):
                is_hidden = True
            if color is None and "color" in s:
                color = _rgb(s["color"], variables)
                color = color if color is not None else _UNKNOWN
                color_rule = src["color"]
            if bg is None:
                bg = _background(s, variables)
                if bg is not None:
                    key = next(
                        k for k in ("background-color", "background", "background-image") if k in s
                    )
                    bg_rule = src[key]
            n = n.parent
        color = (0, 0, 0) if color is None else color
        bg = (255, 255, 255) if bg is None else bg
        if is_hidden or color is _UNKNOWN or bg is _UNKNOWN:
            continue
        if contrast(color, bg) < INVISIBLE:
            text = " ".join(node.texts)
            text = text if len(text) <= 60 else text[:57] + "…"
            found.append(Hidden(text, _hex(color), color_rule, _hex(bg), bg_rule))
            if len(found) >= limit:
                break
    return found


def hidden_texts(html: str, css: str = "", limit: int = 5) -> list[str]:
    return [h.text for h in hidden(html, css, limit)]
