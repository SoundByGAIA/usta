import unittest

from cart import total


class T(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(total([("a", 100.0, 1)], 10), 90.0)

    def test_quantity_and_discount(self):
        self.assertEqual(total([("a", 50.0, 2), ("b", 20.0, 5)], 25), 150.0)

    def test_no_discount(self):
        self.assertEqual(total([("a", 10.0, 3)]), 30.0)

    def test_full_and_invalid(self):
        self.assertEqual(total([("a", 10.0, 1)], 100), 0.0)
        with self.assertRaises(ValueError):
            total([("a", 10.0, 1)], 150)
