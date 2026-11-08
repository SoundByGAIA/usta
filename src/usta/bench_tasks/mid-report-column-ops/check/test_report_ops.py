import unittest

from report import Report


def sample():
    r = Report("S")
    r.add_row({"a": 3, "b": "z"})
    r.add_row({"a": 1, "b": "y"})
    r.add_row({"a": 2, "b": "x"})
    return r


class OldBehaviour(unittest.TestCase):
    def test_add_and_dict(self):
        r = Report("T")
        self.assertEqual(r.add_row({"a": 1, "b": 2}), 0)
        self.assertEqual(r.to_dict(), {"title": "T", "columns": ["a", "b"], "rows": [[1, 2]]})

    def test_total_clear_rows(self):
        r = Report("T")
        r.add_row({"a": 1.5, "b": 2})
        r.add_row({"a": 10, "b": "x"})
        self.assertEqual(r.total(), 13.5)
        self.assertEqual(r.rows(), [{"a": 1.5, "b": 2}, {"a": 10, "b": "x"}])
        r.clear()
        self.assertEqual(r.row_count(), 0)
        self.assertEqual(r.total(), 0)


class RenameColumn(unittest.TestCase):
    def test_rename_keeps_position_and_values(self):
        r = sample()
        r.rename_column("a", "n")
        self.assertEqual(r.to_dict()["columns"], ["n", "b"])
        self.assertEqual(r.to_dict()["rows"], [[3, "z"], [1, "y"], [2, "x"]])

    def test_errors(self):
        r = sample()
        with self.assertRaises(KeyError):
            r.rename_column("q", "n")
        with self.assertRaises(ValueError):
            r.rename_column("a", "b")
        self.assertEqual(r.to_dict()["columns"], ["a", "b"])


class Select(unittest.TestCase):
    def test_select_order_and_copy(self):
        r = sample()
        s = r.select("only-b", ["b"])
        self.assertIsInstance(s, Report)
        self.assertEqual(s.title, "only-b")
        self.assertEqual(s.to_dict(), {"title": "only-b", "columns": ["b"], "rows": [["z"], ["y"], ["x"]]})
        s.add_row({"b": "w"})
        self.assertEqual(r.row_count(), 3)
        self.assertEqual(r.to_dict()["columns"], ["a", "b"])

    def test_missing_column(self):
        with self.assertRaises(KeyError):
            sample().select("x", ["a", "yok"])


class ColumnAndAggregate(unittest.TestCase):
    def test_column(self):
        self.assertEqual(sample().column("a"), [3, 1, 2])
        with self.assertRaises(KeyError):
            sample().column("yok")

    def test_aggregate(self):
        r = sample()
        self.assertEqual(r.aggregate("a"), 6)
        self.assertIsInstance(r.aggregate("a"), int)
        self.assertEqual(r.aggregate("b"), "z y x")
        with self.assertRaises(KeyError):
            r.aggregate("yok")

    def test_aggregate_empty_column(self):
        empty = Report("E")
        empty.add_row({"n": 1, "t": "x"})
        empty.clear()
        self.assertEqual(empty.aggregate("n"), 0)

    def test_aggregate_float(self):
        r = Report("F")
        r.add_row({"n": 0.5})
        r.add_row({"n": 1})
        self.assertEqual(r.aggregate("n"), 1.5)

    def test_aggregate_mixed(self):
        r = Report("M")
        r.add_row({"v": 1})
        r.add_row({"v": "x"})
        with self.assertRaises(ValueError):
            r.aggregate("v")


class SortBy(unittest.TestCase):
    def test_ascending_and_stable(self):
        r = Report("S")
        r.add_row({"a": 2, "b": "ilk"})
        r.add_row({"a": 1, "b": "ikinci"})
        r.add_row({"a": 2, "b": "ucuncu"})
        s = r.sort_by("a")
        self.assertEqual(s.to_dict()["rows"], [[1, "ikinci"], [2, "ilk"], [2, "ucuncu"]])
        self.assertEqual(r.to_dict()["rows"], [[2, "ilk"], [1, "ikinci"], [2, "ucuncu"]])

    def test_reverse(self):
        self.assertEqual(sample().sort_by("a", reverse=True).column("a"), [3, 2, 1])

    def test_missing(self):
        with self.assertRaises(KeyError):
            sample().sort_by("yok")


class Csv(unittest.TestCase):
    def test_plain(self):
        r = Report("T")
        r.add_row({"a": "1", "b": "2"})
        r.add_row({"a": "3", "b": "4"})
        self.assertEqual(r.to_csv(), "a,b\n1,2\n3,4\n")
        self.assertIsInstance(r.to_csv(), str)

    def test_quoting(self):
        r = Report("T")
        r.add_row({"a": "x,y"})
        self.assertEqual(r.to_csv(), 'a\n"x,y"\n')
        r2 = Report("T")
        r2.add_row({"a": 'he said "hi"', "b": "ok"})
        self.assertEqual(r2.to_csv(), 'a,b\n"he said ""hi""",ok\n')

    def test_empty(self):
        self.assertEqual(Report("T").to_csv(), "")


if __name__ == "__main__":
    unittest.main()
