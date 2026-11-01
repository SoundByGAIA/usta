import unittest

from dates import day_of_year, is_leap


class T(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(is_leap(2024))
        self.assertEqual(day_of_year(2023, 3, 1), 60)
