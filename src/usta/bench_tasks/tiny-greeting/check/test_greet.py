import unittest

from greet import greeting


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(greeting("Ada"), "Hello, Ada!")

    def test_empty(self):
        self.assertEqual(greeting(""), "Hello, !")

    def test_unicode(self):
        self.assertEqual(greeting("Çağlar"), "Hello, Çağlar!")
