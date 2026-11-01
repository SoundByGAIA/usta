import re


def wrap(text, width):
    if width < 1:
        raise ValueError("width >= 1 olmalı")
    out = []
    for para in re.split(r"\n\s*\n", text):
        words = para.split()
        if not words:
            continue
        if out:
            out.append("")
        line = ""
        for word in words:
            while len(word) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:width])
                word = word[width:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out
