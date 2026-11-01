import unittest

from lru import LRUCache


class T(unittest.TestCase):
    def test_eviction_order(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        self.assertEqual(c.keys(), ["b", "c"])
        self.assertEqual(c.get("a"), None)

    def test_get_refreshes(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertEqual(c.get("a"), 1)
        c.put("c", 3)
        self.assertEqual(c.keys(), ["a", "c"])

    def test_update_refreshes_and_does_not_grow(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("a", 10)
        self.assertEqual(len(c), 2)
        c.put("c", 3)
        self.assertEqual(c.keys(), ["a", "c"])
        self.assertEqual(c.get("a"), 10)

    def test_contains_does_not_refresh(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertIn("a", c)
        c.put("c", 3)
        self.assertEqual(c.keys(), ["b", "c"])

    def test_default_and_falsy_values(self):
        c = LRUCache(1)
        c.put("a", 0)
        self.assertEqual(c.get("a", "yok"), 0)
        self.assertEqual(c.get("z", "yok"), "yok")

    def test_invalid_capacity(self):
        for bad in (0, -1, 1.5, "2", None):
            with self.assertRaises(ValueError):
                LRUCache(bad)
