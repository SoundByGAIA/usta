import unittest

from parity import is_even


class T(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(5))
