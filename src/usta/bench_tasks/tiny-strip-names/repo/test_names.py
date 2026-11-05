import unittest

from names import read_names


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(read_names("ali\n veli \n"), ["ali", "veli"])
