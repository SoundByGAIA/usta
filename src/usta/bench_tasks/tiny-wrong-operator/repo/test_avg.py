import unittest

from avg import average


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(average([2, 4]), 3.0)
