import re

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|(.))")


def _tokens(expr):
    out = []
    for num, other in _TOKEN.findall(expr):
        if num:
            out.append(("n", float(num) if "." in num else int(num)))
        elif other.strip():
            if other not in "+-*/()":
                raise ValueError(f"tanınmayan karakter: {other!r}")
            out.append((other, None))
    return out


def evaluate(expr):
    toks = _tokens(expr)
    if not toks:
        raise ValueError("boş ifade")
    pos = 0

    def peek():
        return toks[pos][0] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def expr_():
        v = term()
        while peek() in ("+", "-"):
            op = take()[0]
            r = term()
            v = v + r if op == "+" else v - r
        return v

    def term():
        v = unary()
        while peek() in ("*", "/"):
            op = take()[0]
            r = unary()
            v = v * r if op == "*" else v / r
        return v

    def unary():
        if peek() in ("+", "-"):
            op = take()[0]
            v = unary()
            return v if op == "+" else -v
        return atom()

    def atom():
        k = peek()
        if k == "n":
            return take()[1]
        if k == "(":
            take()
            v = expr_()
            if peek() != ")":
                raise ValueError("kapanmayan parantez")
            take()
            return v
        raise ValueError("beklenmeyen jeton")

    result = expr_()
    if pos != len(toks):
        raise ValueError("artık jeton")
    return result
