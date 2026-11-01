import unittest

from users import get_user_name


class T(unittest.TestCase):
    def test_name(self):
        self.assertEqual(get_user_name({"name": "Ayşe"}), "Ayşe")
