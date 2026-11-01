import re


def word_count(text):
    return len(re.findall(r"[A-Za-z]+", text))
