def moving_average(values, window):
    """Her pencere için ortalamayı döndürür."""
    if window <= 0:
        raise ValueError("window pozitif olmalı")
    result = []
    for i in range(len(values) - window + 1):
        result.append(sum(values[i : i + window]) / window)
    return result
