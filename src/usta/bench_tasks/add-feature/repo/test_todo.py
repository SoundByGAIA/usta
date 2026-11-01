import unittest

from todo import TodoList


class T(unittest.TestCase):
    def test_add(self):
        t = TodoList()
        self.assertEqual(t.add("a"), 0)
        self.assertEqual(t.add("b"), 1)
        self.assertEqual(t.titles(), ["a", "b"])
