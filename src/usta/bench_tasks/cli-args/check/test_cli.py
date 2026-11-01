import unittest

from cli import parse_args


class T(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(parse_args([]), {"verbose": False, "name": None, "count": 1, "files": []})

    def test_flags_and_values(self):
        r = parse_args(["-v", "--name", "ali", "--count=3", "a.txt", "b.txt"])
        self.assertEqual(
            r, {"verbose": True, "name": "ali", "count": 3, "files": ["a.txt", "b.txt"]}
        )
        self.assertEqual(parse_args(["-n", "veli"])["name"], "veli")
        self.assertEqual(parse_args(["--name=x=y"])["name"], "x=y")

    def test_double_dash_and_mixed_order(self):
        r = parse_args(["a", "-v", "b", "--", "-v", "--count", "c"])
        self.assertEqual(r["files"], ["a", "b", "-v", "--count", "c"])
        self.assertTrue(r["verbose"])

    def test_last_value_wins(self):
        self.assertEqual(parse_args(["--count", "2", "--count=5"])["count"], 5)

    def test_negative_count_is_int(self):
        self.assertEqual(parse_args(["--count", "-2"])["count"], -2)

    def test_errors(self):
        for bad in (
            ["--bilinmeyen"],
            ["-x"],
            ["--name"],
            ["-n"],
            ["--count"],
            ["--count", "abc"],
            ["--count=1.5"],
            ["--verbose=1"],
        ):
            with self.assertRaises(ValueError, msg=str(bad)):
                parse_args(bad)

    def test_single_dash_is_a_file(self):
        self.assertEqual(parse_args(["-"])["files"], ["-"])
