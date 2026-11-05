import unittest

from nums import double_all


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(double_all([1, 2, 3]), [2, 4, 6])
