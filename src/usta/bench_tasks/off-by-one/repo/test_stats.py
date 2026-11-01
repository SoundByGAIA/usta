import unittest

from stats import moving_average


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
