from decimal import ROUND_HALF_UP, Decimal


def add_tax(amount, rate):
    value = Decimal(str(amount)) * (1 + Decimal(str(rate)))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def split_bill(total, people):
    if people <= 0:
        raise ValueError("people pozitif olmalı")
    cents = int((Decimal(str(total)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    base, extra = divmod(cents, people)
    return [(base + (1 if i < extra else 0)) / 100 for i in range(people)]
