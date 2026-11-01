import unittest

from pricing import apply_discount


class T(unittest.TestCase):
    def test_rate(self):
        self.assertEqual(apply_discount(200.0, 0.25), 150.0)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            apply_discount(10, 10)
