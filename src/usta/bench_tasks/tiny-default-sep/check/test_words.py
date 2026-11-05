import unittest

from words import join_words


class T(unittest.TestCase):
    def test_default(self):
        self.assertEqual(join_words(["a", "b"]), "a b")

    def test_explicit(self):
        self.assertEqual(join_words(["a", "b", "c"], "-"), "a-b-c")

    def test_empty(self):
        self.assertEqual(join_words([]), "")

    def test_keyword(self):
        self.assertEqual(join_words(["x", "y"], sep=","), "x,y")
