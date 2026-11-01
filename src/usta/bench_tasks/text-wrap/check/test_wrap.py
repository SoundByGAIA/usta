import unittest

from wrap import wrap


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(wrap("aa bb cc", 5), ["aa bb", "cc"])
        self.assertEqual(wrap("aa bb cc", 8), ["aa bb cc"])
        self.assertEqual(wrap("aa bb cc", 2), ["aa", "bb", "cc"])

    def test_whitespace_collapses(self):
        self.assertEqual(wrap("  aa    bb  \n cc ", 5), ["aa bb", "cc"])

    def test_long_word_is_split(self):
        self.assertEqual(wrap("abcdefgh", 3), ["abc", "def", "gh"])
        self.assertEqual(wrap("x abcdefg y", 3), ["x", "abc", "def", "g y"])

    def test_paragraphs(self):
        self.assertEqual(wrap("aa bb\n\ncc dd", 5), ["aa bb", "", "cc dd"])
        self.assertEqual(wrap("aa\n\n\n\nbb", 5), ["aa", "", "bb"])

    def test_empty_and_invalid(self):
        self.assertEqual(wrap("", 5), [])
        self.assertEqual(wrap(" \n \n\n ", 5), [])
        for w in (0, -3):
            with self.assertRaises(ValueError):
                wrap("a", w)
