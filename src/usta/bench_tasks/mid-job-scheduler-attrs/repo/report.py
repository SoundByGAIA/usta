def failures(jobs, min_tries):
    """En az `min_tries` deneme yapmış işlerin kimlikleri."""
    return [j.id for j in jobs if j.tries >= min_tries]
