import unittest

from inventory import parse, parse_and_report, report

TEXT = "# baslik\na,2,3\nbozuk\nb,x,1\n,5,1\nc,1,0\n"


class T(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            parse(TEXT),
            [{"sku": "a", "items": 2, "qty": 3}, {"sku": "c", "items": 1, "qty": 0}],
        )

    def test_report(self):
        self.assertEqual(report(parse(TEXT)), {"items": 3, "qty": 3, "sku": "a,c"})

    def test_parse_and_report(self):
        self.assertEqual(parse_and_report(TEXT), {"items": 3, "qty": 3, "sku": "a,c"})


if __name__ == "__main__":
    unittest.main()
