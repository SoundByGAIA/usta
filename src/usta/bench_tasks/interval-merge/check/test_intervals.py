import unittest

from intervals import merge_intervals


class T(unittest.TestCase):
    def test_basic_and_touching(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 6], [8, 10]]), [[1, 6], [8, 10]])
        self.assertEqual(merge_intervals([[1, 3], [3, 5]]), [[1, 5]])

    def test_unsorted_nested(self):
        self.assertEqual(merge_intervals([[8, 10], [1, 10], [2, 3]]), [[1, 10]])

    def test_empty_and_single(self):
        self.assertEqual(merge_intervals([]), [])
        self.assertEqual(merge_intervals([[4, 4]]), [[4, 4]])

    def test_negative_and_float(self):
        self.assertEqual(merge_intervals([[-5, -1], [-2, 2.5]]), [[-5, 2.5]])

    def test_input_not_mutated_and_output_independent(self):
        data = [[5, 7], [1, 2]]
        out = merge_intervals(data)
        self.assertEqual(data, [[5, 7], [1, 2]])
        out[0][0] = 99
        self.assertEqual(data[1], [1, 2])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            merge_intervals([[3, 1]])
