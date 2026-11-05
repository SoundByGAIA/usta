import unittest

from pct import percent


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(percent(1, 4), 25.0)
