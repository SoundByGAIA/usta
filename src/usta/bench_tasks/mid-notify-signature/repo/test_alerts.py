import unittest

import transports
from alerts import notify


class T(unittest.TestCase):
    def setUp(self):
        transports.reset()

    def test_notify(self):
        self.assertEqual(notify({"id": "u1"}, "selam"), ("push", "u1", 1))
        self.assertEqual(transports.sent(), [("push", "u1", "selam")])


if __name__ == "__main__":
    unittest.main()
