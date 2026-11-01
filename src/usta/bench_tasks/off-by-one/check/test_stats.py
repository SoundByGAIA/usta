import unittest

from stats import moving_average


class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])

    def test_window_equals_length(self):
        self.assertEqual(moving_average([2, 4, 6], 3), [4.0])

    def test_window_larger_than_data(self):
        self.assertEqual(moving_average([1, 2], 5), [])

    def test_window_one(self):
        self.assertEqual(moving_average([5, 7], 1), [5.0, 7.0])

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2], 0)
