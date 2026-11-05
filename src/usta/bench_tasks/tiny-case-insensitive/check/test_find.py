import unittest

from find import has_word


class T(unittest.TestCase):
    def test_case(self):
        self.assertTrue(has_word("Merhaba Dünya", "merhaba"))

    def test_exact(self):
        self.assertTrue(has_word("abc", "abc"))

    def test_missing(self):
        self.assertFalse(has_word("abc", "xyz"))

    def test_upper_query(self):
        self.assertTrue(has_word("hello world", "WORLD"))
