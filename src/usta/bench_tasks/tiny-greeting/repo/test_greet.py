import unittest

from greet import greeting


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(greeting("Ada"), "Hello, Ada!")
