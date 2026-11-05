import unittest

from names import read_names


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(read_names("ali\n veli \n"), ["ali", "veli"])

    def test_blank_lines(self):
        self.assertEqual(read_names("a\n\n  \nb"), ["a", "b"])

    def test_empty(self):
        self.assertEqual(read_names(""), [])

    def test_tabs(self):
        self.assertEqual(read_names("\tx\t"), ["x"])
