def average(numbers):
    """Sayıların aritmetik ortalaması; boş listede 0.0."""
    if not numbers:
        return 0.0
    return sum(numbers) * len(numbers)
