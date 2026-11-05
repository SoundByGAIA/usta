import unittest

from nums import double_all


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(double_all([1, 2, 3]), [2, 4, 6])

    def test_empty(self):
        self.assertEqual(double_all([]), [])

    def test_negative(self):
        self.assertEqual(double_all([-1, 0]), [-2, 0])

    def test_input_untouched(self):
        src = [1, 2]
        double_all(src)
        self.assertEqual(src, [1, 2])
