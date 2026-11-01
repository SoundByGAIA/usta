def apply_discount(price, rate):
    """rate 0 ile 1 arasında bir orandır (0.1 = %10)."""
    if not 0 <= rate <= 1:
        raise ValueError("rate 0..1 olmalı")
    return round(price * (1 - rate), 2)
