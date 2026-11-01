import unittest

from money import add_tax, split_bill


class T(unittest.TestCase):
    def test_add_tax_basic(self):
        self.assertEqual(add_tax(100, 0.075), 107.5)
        self.assertEqual(add_tax(0, 0.2), 0.0)

    def test_add_tax_half_up(self):
        self.assertEqual(add_tax(1.15, 0.1), 1.27)
        self.assertEqual(add_tax(0.5, 0.01), 0.51)
        self.assertEqual(add_tax(2.5, 0.1), 2.75)
        self.assertEqual(add_tax(10.05, 0.05), 10.55)

    def test_split_sums_exactly(self):
        self.assertEqual(split_bill(100, 3), [33.34, 33.33, 33.33])
        self.assertEqual(split_bill(10, 4), [2.5, 2.5, 2.5, 2.5])
        shares = split_bill(0.05, 3)
        self.assertEqual(shares, [0.02, 0.02, 0.01])
        self.assertEqual(round(sum(split_bill(99.99, 7)) * 100), 9999)

    def test_split_invalid(self):
        for p in (0, -2):
            with self.assertRaises(ValueError):
                split_bill(10, p)
