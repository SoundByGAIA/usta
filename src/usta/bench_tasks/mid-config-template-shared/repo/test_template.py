import unittest

from template import render


class T(unittest.TestCase):
    def test_named(self):
        self.assertEqual(render("Merhaba {name}!", {"name": "Ali"}), "Merhaba Ali!")


if __name__ == "__main__":
    unittest.main()
