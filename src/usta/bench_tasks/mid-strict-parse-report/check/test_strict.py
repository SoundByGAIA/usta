import unittest

import inventory
from inventory import parse, parse_and_report, report

TEXT = "# baslik\na,2,3\nbozuk\nb,x,1\n,5,1\nc,1,0\n"
ROWS = [{"sku": "a", "items": 2, "qty": 3}, {"sku": "c", "items": 1, "qty": 0}]
BASE = {"items": 3, "qty": 3, "sku": "a,c"}


class OldCallSites(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse(TEXT), ROWS)
        self.assertIsInstance(parse(TEXT), list)

    def test_report(self):
        self.assertEqual(report(ROWS), BASE)

    def test_parse_and_report(self):
        self.assertEqual(parse_and_report(TEXT), BASE)
        self.assertEqual(inventory.parse_and_report(""), {"items": 0, "qty": 0, "sku": ""})

    def test_explicit_false_same_as_old(self):
        self.assertEqual(parse(TEXT, strict=False), ROWS)
        self.assertEqual(report(ROWS, strict=False), BASE)
        self.assertEqual(parse_and_report(TEXT, strict=False), BASE)


class StrictParse(unittest.TestCase):
    def test_returns_tuple_with_line_numbers(self):
        rows, errors = parse(TEXT, strict=True)
        self.assertEqual(rows, ROWS)
        self.assertEqual(errors, [3, 4, 5])

    def test_blank_and_comments_are_not_errors(self):
        rows, errors = parse("a,1,1\n\n# yorum\n   \nb,2\n", strict=True)
        self.assertEqual(rows, [{"sku": "a", "items": 1, "qty": 1}])
        self.assertEqual(errors, [5])

    def test_bad_qty_and_empty_sku(self):
        _, errors = parse("a,1,x\n,2,3\nc,2,4\n", strict=True)
        self.assertEqual(errors, [1, 2])


class StrictReport(unittest.TestCase):
    def test_warnings_order(self):
        rows = [
            {"sku": "z", "items": 1, "qty": -2},
            {"sku": "", "items": 7, "qty": 4},
            {"sku": "y", "items": 2, "qty": 0},
            {"sku": "", "items": 3, "qty": 1},
        ]
        rep, warnings = report(rows, strict=True)
        self.assertEqual(rep, {"items": 13, "qty": 3, "sku": "z,,y,"})
        self.assertEqual(warnings, ["negatif adet: z", "negatif adet: y", "sku yok: 7", "sku yok: 3"])

    def test_no_warnings_for_clean_rows(self):
        clean = [{"sku": "a", "items": 2, "qty": 3}, {"sku": "b", "items": 1, "qty": 1}]
        rep, warnings = report(clean, strict=True)
        self.assertEqual(rep, {"items": 3, "qty": 4, "sku": "a,b"})
        self.assertEqual(warnings, [])


class StrictParseAndReport(unittest.TestCase):
    def test_combined(self):
        rep, errors = parse_and_report(TEXT, strict=True)
        self.assertEqual(rep, BASE)
        self.assertEqual(errors, ["satir 3", "satir 4", "satir 5", "negatif adet: c"])

    def test_clean_input(self):
        rep, errors = parse_and_report("a,1,2\nb,3,4\n", strict=True)
        self.assertEqual(rep, {"items": 4, "qty": 6, "sku": "a,b"})
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
