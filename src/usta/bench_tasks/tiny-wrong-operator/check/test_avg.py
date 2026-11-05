import unittest

from avg import average


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(average([2, 4]), 3.0)

    def test_single(self):
        self.assertEqual(average([7]), 7.0)

    def test_empty(self):
        self.assertEqual(average([]), 0.0)

    def test_float(self):
        self.assertAlmostEqual(average([1, 2]), 1.5)
