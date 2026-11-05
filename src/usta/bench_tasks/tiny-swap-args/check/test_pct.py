import unittest

from pct import percent


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(percent(1, 4), 25.0)

    def test_zero_total(self):
        self.assertEqual(percent(5, 0), 0.0)

    def test_zero_part(self):
        self.assertEqual(percent(0, 8), 0.0)

    def test_over_100(self):
        self.assertEqual(percent(3, 2), 150.0)
