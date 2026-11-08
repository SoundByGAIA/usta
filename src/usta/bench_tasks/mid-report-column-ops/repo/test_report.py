import unittest

from report import Report


class T(unittest.TestCase):
    def test_add_and_dict(self):
        r = Report("T")
        self.assertEqual(r.add_row({"a": 1, "b": 2}), 0)
        self.assertEqual(r.to_dict(), {"title": "T", "columns": ["a", "b"], "rows": [[1, 2]]})

    def test_total_and_clear(self):
        r = Report("T")
        r.add_row({"a": 1.5, "b": 2})
        r.add_row({"a": 10, "b": "x"})
        self.assertEqual(r.total(), 13.5)
        self.assertEqual(r.row_count(), 2)
        r.clear()
        self.assertEqual(r.row_count(), 0)
        self.assertEqual(r.total(), 0)


if __name__ == "__main__":
    unittest.main()
