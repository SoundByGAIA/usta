import unittest

from rank import ranking


class T(unittest.TestCase):
    def test_high_score_first(self):
        players = [
            {"name": "a", "score": 5, "time": 1},
            {"name": "b", "score": 9, "time": 2},
        ]
        self.assertEqual([r["name"] for r in ranking(players)], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
