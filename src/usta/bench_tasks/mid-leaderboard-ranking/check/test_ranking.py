import unittest

from rank import ranking, top_names

PLAYERS = [
    {"name": "b", "score": 10, "time": 5},
    {"name": "a", "score": 10, "time": 5},
    {"name": "c", "score": 10, "time": 3},
    {"name": "d", "score": 9, "time": 1},
]


class ScoreOrder(unittest.TestCase):
    def test_order_and_ranks(self):
        got = ranking(PLAYERS)
        self.assertEqual([r["name"] for r in got], ["c", "a", "b", "d"])
        self.assertEqual([r["rank"] for r in got], [1, 2, 2, 4])

    def test_entry_shape(self):
        first = ranking(PLAYERS)[0]
        self.assertEqual(first, {"rank": 1, "name": "c", "score": 10, "time": 3})


class TimeOrder(unittest.TestCase):
    def test_time_then_score(self):
        got = ranking(PLAYERS, key="time")
        self.assertEqual([r["name"] for r in got], ["d", "c", "a", "b"])
        self.assertEqual([r["rank"] for r in got], [1, 2, 3, 3])

    def test_time_tie_broken_by_score(self):
        players = [
            {"name": "x", "score": 1, "time": 4},
            {"name": "y", "score": 8, "time": 4},
        ]
        self.assertEqual([r["name"] for r in ranking(players, key="time")], ["y", "x"])


class Names(unittest.TestCase):
    def test_alphabetic_tiebreak(self):
        players = [
            {"name": "Zed", "score": 3, "time": 2},
            {"name": "ada", "score": 3, "time": 2},
            {"name": "Bob", "score": 3, "time": 2},
        ]
        self.assertEqual([r["name"] for r in ranking(players)], ["Bob", "Zed", "ada"])
        self.assertEqual([r["rank"] for r in ranking(players)], [1, 1, 1])


class Invariants(unittest.TestCase):
    def test_input_not_mutated(self):
        snapshot = [dict(p) for p in PLAYERS]
        result = ranking(PLAYERS)
        self.assertEqual(PLAYERS, snapshot)
        result[0]["name"] = "degisti"
        self.assertEqual(PLAYERS, snapshot)
        self.assertEqual(result[0]["time"], 3)

    def test_limit(self):
        self.assertEqual([r["name"] for r in ranking(PLAYERS, n=2)], ["c", "a"])
        self.assertEqual(ranking(PLAYERS, n=0), [])
        self.assertEqual([r["rank"] for r in ranking(PLAYERS, n=9)], [1, 2, 2, 4])

    def test_errors(self):
        with self.assertRaises(ValueError):
            ranking(PLAYERS, n=-1)
        with self.assertRaises(ValueError):
            ranking(PLAYERS, key="name")
        with self.assertRaises(ValueError):
            top_names(PLAYERS, -3)

    def test_empty(self):
        self.assertEqual(ranking([]), [])
        self.assertEqual(top_names([], 3), [])


class TopNames(unittest.TestCase):
    def test_top_names(self):
        self.assertEqual(top_names(PLAYERS, 2), ["c", "a"])
        self.assertEqual(top_names(PLAYERS, 10), ["c", "a", "b", "d"])


if __name__ == "__main__":
    unittest.main()
