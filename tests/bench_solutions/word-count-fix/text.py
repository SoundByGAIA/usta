import re

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")


def word_count(text):
    return len(_WORD.findall(text))
