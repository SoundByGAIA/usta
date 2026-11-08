def render(template, data):
    """{name} yer tutucularını data ile doldurur; {{ ve }} tek süslü parantez üretir."""
    out = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch == "{":
            end = template.find("}", i)
            name = template[i + 1 : end]
            out.append(f"{data[name]}")
            i = end + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def render_all(templates, data):
    """Her şablonu render eder."""
    out = []
    for t in templates:
        out.append(f"{data[t]}")
    return out
