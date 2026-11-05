import unittest

from parity import is_even, is_odd


class T(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(5))

    def test_zero_and_negative(self):
        self.assertTrue(is_even(0))
        self.assertTrue(is_even(-2))
        self.assertFalse(is_even(-3))

    def test_is_odd_untouched(self):
        self.assertTrue(is_odd(3))
        self.assertFalse(is_odd(4))
