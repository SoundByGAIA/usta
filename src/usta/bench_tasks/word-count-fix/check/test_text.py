import unittest

from text import word_count


class T(unittest.TestCase):
    def test_old_behaviour(self):
        self.assertEqual(word_count("a,b"), 2)
        self.assertEqual(word_count("hello...world"), 2)
        self.assertEqual(word_count("3 cats"), 1)
        self.assertEqual(word_count(""), 0)
        self.assertEqual(word_count("   "), 0)

    def test_apostrophe_and_hyphen(self):
        self.assertEqual(word_count("don't stop"), 2)
        self.assertEqual(word_count("a well-known fact"), 3)
        self.assertEqual(word_count("rock'n'roll"), 1)

    def test_turkish_letters(self):
        self.assertEqual(word_count("çok güzel bir gün"), 4)
        self.assertEqual(word_count("ığdır şehri"), 2)

    def test_dangling_marks_do_not_join(self):
        self.assertEqual(word_count("-- dash - alone"), 2)
        self.assertEqual(word_count("'quoted' word"), 2)
