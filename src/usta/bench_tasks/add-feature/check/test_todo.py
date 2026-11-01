import unittest

from todo import TodoList


class T(unittest.TestCase):
    def test_add(self):
        t = TodoList()
        self.assertEqual(t.add("a"), 0)
        self.assertEqual(t.titles(), ["a"])

    def test_complete_and_pending(self):
        t = TodoList()
        t.add("a")
        t.add("b")
        t.add("c")
        t.complete(1)
        self.assertEqual(t.pending(), ["a", "c"])

    def test_complete_errors(self):
        t = TodoList()
        t.add("a")
        with self.assertRaises(IndexError):
            t.complete(5)
        t.complete(0)
        with self.assertRaises(ValueError):
            t.complete(0)

    def test_json_roundtrip(self):
        t = TodoList()
        t.add("a")
        t.add("b")
        t.complete(0)
        u = TodoList.from_json(t.to_json())
        self.assertEqual(u.titles(), ["a", "b"])
        self.assertEqual(u.pending(), ["b"])
        self.assertIsInstance(t.to_json(), str)
