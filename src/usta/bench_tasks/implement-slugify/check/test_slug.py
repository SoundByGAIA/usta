import unittest

from slug import slugify


class T(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(slugify("Merhaba Dünya!"), "merhaba-dunya")
        self.assertEqual(slugify("  ÇığÖşÜ  "), "cigosu")
        self.assertEqual(slugify("---"), "n-a")

    def test_runs_collapse(self):
        self.assertEqual(slugify("a   b__c"), "a-b-c")

    def test_digits_and_edges(self):
        self.assertEqual(slugify("2024 Yılı!!"), "2024-yili")
        self.assertEqual(slugify(""), "n-a")
        self.assertEqual(slugify("İstanbul"), "istanbul")
        self.assertEqual(slugify("-x-"), "x")
