def _render(template, data):
    out = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch == "{":
            if template.startswith("{{", i):
                out.append("{")
                i += 2
                continue
            end = template.find("}", i + 1)
            if end == -1:
                raise ValueError("kapanmayan '{'")
            name = template[i + 1 : end]
            if not name or not all(c.isalnum() or c == "_" for c in name):
                raise ValueError(f"geçersiz yer tutucu: {name!r}")
            out.append(f"{data.get(name, '')}")
            i = end + 1
        elif ch == "}":
            if template.startswith("}}", i):
                out.append("}")
                i += 2
                continue
            raise ValueError("beklenmeyen '}'")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def render(template, data):
    """{name} yer tutucularını data ile doldurur; {{ ve }} tek süslü parantez üretir."""
    return _render(template, data)


def render_all(templates, data):
    """Her şablonu render eder."""
    return [render(t, data) for t in templates]
