_KEYS = ("score", "time")


def _orders(key):
    if key == "score":
        return (lambda p: -p["score"], lambda p: p["time"], lambda p: p["name"])
    if key == "time":
        return (lambda p: p["time"], lambda p: -p["score"], lambda p: p["name"])
    raise ValueError(f"bilinmeyen sıralama anahtarı: {key!r}")


def ranking(players, key="score", n=None):
    """Oyuncuları sıralayıp {\"rank\", \"name\", \"score\", \"time\"} listesi döndürür."""
    if n is not None and n < 0:
        raise ValueError("n negatif olamaz")
    first, second, third = _orders(key)
    ordered = sorted(players, key=lambda p: (first(p), second(p), third(p)))
    out = []
    for i, p in enumerate(ordered):
        if i and (p["score"], p["time"]) == (ordered[i - 1]["score"], ordered[i - 1]["time"]):
            rank = out[-1]["rank"]
        else:
            rank = i + 1
        out.append({"rank": rank, "name": p["name"], "score": p["score"], "time": p["time"]})
    if n is not None:
        out = out[:n]
    return out


def top_names(players, n):
    """Sıralamadaki ilk n oyuncunun adlarını döndürür."""
    return [r["name"] for r in ranking(players, n=n)]
