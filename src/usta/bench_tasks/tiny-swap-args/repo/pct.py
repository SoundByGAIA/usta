def percent(part, total):
    """part, total'in yüzde kaçı; total 0 ise 0.0."""
    if total == 0:
        return 0.0
    return total / part * 100
