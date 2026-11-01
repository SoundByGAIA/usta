import unittest

from calc import evaluate


class T(unittest.TestCase):
    def test_precedence_and_parens(self):
        self.assertEqual(evaluate("2 + 3 * 4"), 14)
        self.assertEqual(evaluate("(2+3)*4"), 20)
        self.assertEqual(evaluate("10 - 4 - 3"), 3)
        self.assertEqual(evaluate("100 / 10 / 5"), 2)

    def test_unary_and_decimals(self):
        self.assertEqual(evaluate("-(1+2)"), -3)
        self.assertEqual(evaluate("3 * -2"), -6)
        self.assertEqual(evaluate("+4"), 4)
        self.assertAlmostEqual(evaluate("1.5 * 2"), 3.0)
        self.assertEqual(evaluate("10/4"), 2.5)

    def test_whitespace_and_nesting(self):
        self.assertEqual(evaluate("  ( ( 1 + 2 ) * ( 3 + 4 ) )  "), 21)

    def test_division_by_zero(self):
        with self.assertRaises(ZeroDivisionError):
            evaluate("1/0")
        with self.assertRaises(ZeroDivisionError):
            evaluate("5/(2-2)")

    def test_invalid_expressions(self):
        for bad in ("", "  ", "(1+2", "1+2)", "2 $ 3", "1 + * 2", "1 2", "()", "*3", "2 **3"):
            with self.assertRaises(ValueError, msg=bad):
                evaluate(bad)

    def test_no_code_execution(self):
        for bad in ("__import__('os')", "abs(-1)", "1if 1else 2"):
            with self.assertRaises(ValueError, msg=bad):
                evaluate(bad)
