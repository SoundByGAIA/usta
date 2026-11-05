def read_names(text):
    """Satır satır adları döndürür."""
    return [ln.strip() for ln in text.split("\n") if ln.strip()]
