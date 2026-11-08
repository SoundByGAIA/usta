import unittest

from pager import page_links, paginate


class Paginate(unittest.TestCase):
    def test_first_and_middle(self):
        self.assertEqual(paginate(10, 3), {"page": 1, "pages": 4, "offset": 0, "size": 3})
        self.assertEqual(paginate(10, 3, 2), {"page": 2, "pages": 4, "offset": 3, "size": 3})

    def test_last_page_remainder(self):
        self.assertEqual(paginate(10, 3, 4), {"page": 4, "pages": 4, "offset": 9, "size": 1})
        self.assertEqual(paginate(9, 3, 3), {"page": 3, "pages": 3, "offset": 6, "size": 3})

    def test_no_empty_last_page(self):
        self.assertEqual(paginate(10, 5)["pages"], 2)
        self.assertEqual(paginate(5, 5, 1), {"page": 1, "pages": 1, "offset": 0, "size": 5})
        self.assertEqual(paginate(11, 5)["pages"], 3)
        self.assertEqual(paginate(11, 5, 3)["size"], 1)

    def test_empty(self):
        self.assertEqual(paginate(0, 5), {"page": 1, "pages": 0, "offset": 0, "size": 0})
        self.assertEqual(paginate(0, 5, 1)["pages"], 0)

    def test_errors(self):
        for args in ((10, 3, 5), (0, 5, 2), (-1, 3), (10, 0), (10, 3, 0), (10, -2, 1)):
            with self.assertRaises(ValueError, msg=str(args)):
                paginate(*args)


class Links(unittest.TestCase):
    def test_window_default(self):
        self.assertEqual(page_links(10, 1, 5), [1, "...", 3, 4, 5, 6, 7, "...", 10])

    def test_edges(self):
        self.assertEqual(page_links(10, 1, 1), [1, 2, 3, "...", 10])
        self.assertEqual(page_links(10, 1, 2), [1, 2, 3, 4, "...", 10])
        self.assertEqual(page_links(10, 1, 10), [1, "...", 8, 9, 10])
        self.assertEqual(page_links(10, 1, 9), [1, "...", 7, 8, 9, 10])

    def test_no_adjacent_ellipsis(self):
        self.assertEqual(page_links(10, 1, 3), [1, 2, 3, 4, 5, "...", 10])
        self.assertEqual(page_links(10, 1, 10, window=1), [1, "...", 9, 10])
        self.assertEqual(page_links(10, 1, 4, window=2), [1, 2, 3, 4, 5, 6, "...", 10])

    def test_small_and_empty(self):
        self.assertEqual(page_links(3, 1, 2), [1, 2, 3])
        self.assertEqual(page_links(1, 10, 1), [1])
        self.assertEqual(page_links(0, 5, 1), [])

    def test_errors(self):
        for args in ((10, 1, 11), (0, 5, 2), (10, 0, 1), (10, 1, 0)):
            with self.assertRaises(ValueError, msg=str(args)):
                page_links(*args)


if __name__ == "__main__":
    unittest.main()
