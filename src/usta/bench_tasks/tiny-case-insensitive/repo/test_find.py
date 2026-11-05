import unittest

from find import has_word


class T(unittest.TestCase):
    def test_case(self):
        self.assertTrue(has_word("Merhaba Dünya", "dünya"))
