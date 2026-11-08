import unittest

from auth import token_ttl_seconds


class T(unittest.TestCase):
    def test_member_ttl(self):
        self.assertEqual(token_ttl_seconds("ali", 0), 600)


if __name__ == "__main__":
    unittest.main()
