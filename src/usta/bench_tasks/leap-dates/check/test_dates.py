import unittest

from dates import day_of_year, days_in_month, is_leap


class T(unittest.TestCase):
    def test_leap_rules(self):
        self.assertTrue(is_leap(2024))
        self.assertFalse(is_leap(2023))
        self.assertFalse(is_leap(1900))
        self.assertTrue(is_leap(2000))
        self.assertFalse(is_leap(2100))

    def test_days_in_month(self):
        self.assertEqual(days_in_month(1900, 2), 28)
        self.assertEqual(days_in_month(2000, 2), 29)
        self.assertEqual(days_in_month(2023, 12), 31)

    def test_invalid_month(self):
        for m in (0, 13, -1):
            with self.assertRaises(ValueError):
                days_in_month(2023, m)

    def test_day_of_year(self):
        self.assertEqual(day_of_year(2023, 3, 1), 60)
        self.assertEqual(day_of_year(2024, 3, 1), 61)
        self.assertEqual(day_of_year(1900, 12, 31), 365)
        self.assertEqual(day_of_year(2000, 12, 31), 366)

    def test_invalid_day(self):
        for args in ((2023, 2, 29), (2023, 4, 31), (2023, 1, 0), (2023, 13, 1)):
            with self.assertRaises(ValueError):
                day_of_year(*args)
        self.assertEqual(day_of_year(2024, 2, 29), 60)
