import unittest

from app import checkout
from ledger import Ledger


class T(unittest.TestCase):
    def test_checkout(self):
        ledger = Ledger()
        self.assertEqual(checkout(ledger, "web", {"kalem": 1}), 1)
        self.assertEqual(ledger.count("web"), 1)
        self.assertEqual(ledger.channels(), ["web"])


if __name__ == "__main__":
    unittest.main()
