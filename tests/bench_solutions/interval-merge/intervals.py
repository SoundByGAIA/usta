def merge_intervals(intervals):
    items = []
    for a, b in intervals:
        if a > b:
            raise ValueError("başlangıç > bitiş")
        items.append((a, b))
    items.sort()
    out = []
    for a, b in items:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out
