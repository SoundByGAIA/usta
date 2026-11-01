_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year, month):
    if not 1 <= month <= 12:
        raise ValueError("ay 1-12 olmalı")
    if month == 2 and is_leap(year):
        return 29
    return _DAYS[month - 1]


def day_of_year(year, month, day):
    if not 1 <= day <= days_in_month(year, month):
        raise ValueError("geçersiz gün")
    return sum(days_in_month(year, m) for m in range(1, month)) + day
