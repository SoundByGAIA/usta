import unittest

from execute import retry_delay


class T(unittest.TestCase):
    def test_delay(self):
        self.assertEqual(retry_delay(1), 1)
        self.assertEqual(retry_delay(3), 9)
