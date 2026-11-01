import unittest

from money import add_tax


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(add_tax(100, 0.075), 107.5)
