import unittest

from words import join_words


class T(unittest.TestCase):
    def test_default(self):
        self.assertEqual(join_words(["a", "b"]), "a b")
