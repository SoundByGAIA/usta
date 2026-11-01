import re

_MAP = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "İ": "i",
        "Ç": "c",
        "Ğ": "g",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)


def slugify(text):
    text = text.translate(_MAP).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "n-a"
