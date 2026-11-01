def add_tax(amount, rate):
    return round(amount * (1 + rate), 2)


def split_bill(total, people):
    share = round(total / people, 2)
    return [share] * people
