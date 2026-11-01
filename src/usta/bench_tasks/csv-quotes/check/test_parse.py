import unittest

from parse import parse_line


class T(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_line("a,b,c"), ["a", "b", "c"])
        self.assertEqual(parse_line("a,,b"), ["a", "", "b"])
        self.assertEqual(parse_line("a,b,"), ["a", "b", ""])

    def test_quoted_comma(self):
        self.assertEqual(parse_line('a,"b,c",d'), ["a", "b,c", "d"])

    def test_escaped_quote(self):
        self.assertEqual(parse_line('"he said ""hi"""'), ['he said "hi"'])

    def test_spaces_kept(self):
        self.assertEqual(parse_line(' a ,"b"'), [" a ", "b"])

    def test_empty_line(self):
        self.assertEqual(parse_line(""), [""])
