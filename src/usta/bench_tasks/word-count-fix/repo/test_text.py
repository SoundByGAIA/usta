import unittest

from text import word_count


class T(unittest.TestCase):
    def test_old_behaviour(self):
        self.assertEqual(word_count("a,b"), 2)
        self.assertEqual(word_count("hello...world"), 2)
        self.assertEqual(word_count("3 cats"), 1)
