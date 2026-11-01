import unittest

from cart import total


class T(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(total([("a", 100.0, 1)], 10), 90.0)
