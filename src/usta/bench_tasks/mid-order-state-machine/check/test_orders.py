import unittest

from app import checkout
from ledger import Ledger
from orders import InvalidTransition, Order


class HappyPath(unittest.TestCase):
    def test_full_flow(self):
        o = Order({"kalem": 2, "kutu": 1})
        self.assertEqual(o.history(), ["new"])
        self.assertEqual(o.pay(10), "paid")
        self.assertEqual(o.paid_total, 10)
        self.assertEqual(o.ship(), "shipped")
        self.assertEqual(o.deliver(), "delivered")
        self.assertEqual(o.history(), ["new", "paid", "shipped", "delivered"])

    def test_cancel_from_new_and_paid(self):
        o = Order({})
        self.assertEqual(o.cancel(), "cancelled")
        p = Order({"x": 1})
        p.pay(5)
        self.assertEqual(p.cancel(), "cancelled")
        self.assertEqual(p.history(), ["new", "paid", "cancelled"])


class Rejections(unittest.TestCase):
    def test_ship_before_pay(self):
        with self.assertRaises(InvalidTransition):
            Order({}).ship()

    def test_double_pay(self):
        o = Order({})
        o.pay(1)
        with self.assertRaises(InvalidTransition):
            o.pay(2)
        self.assertEqual(o.paid_total, 1)

    def test_cancel_after_shipped_and_terminal_states(self):
        o = Order({})
        o.pay(1)
        o.ship()
        with self.assertRaises(InvalidTransition):
            o.cancel()
        self.assertEqual(o.history(), ["new", "paid", "shipped"])
        o.deliver()
        for call in (o.cancel, o.ship, o.deliver):
            with self.assertRaises(InvalidTransition):
                call()
        c = Order({})
        c.cancel()
        with self.assertRaises(InvalidTransition):
            c.pay(1)
        self.assertEqual(c.history(), ["new", "cancelled"])

    def test_invalid_amount(self):
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                Order({}).pay(bad)


class Copies(unittest.TestCase):
    def test_items_copied_both_ways(self):
        source = {"kalem": 2}
        o = Order(source)
        source["kalem"] = 99
        source["yeni"] = 1
        self.assertEqual(o.items(), {"kalem": 2})
        got = o.items()
        got["kalem"] = 0
        self.assertEqual(o.items(), {"kalem": 2})

    def test_items_is_method(self):
        o = Order({"a": 1})
        self.assertTrue(callable(o.items))
        self.assertEqual(o.items(), {"a": 1})


class Integration(unittest.TestCase):
    def test_ledger_and_app_still_work(self):
        led = Ledger()
        self.assertEqual(checkout(led, "web", {"kalem": 1}), 1)
        self.assertEqual(checkout(led, "web", {"kalem": 2}), 2)
        self.assertEqual(led.channels(), ["web"])
        self.assertEqual(led.count("web"), 2)
        orders = led.orders("web")
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].history(), ["new"])
        self.assertEqual(orders[0].pay(3), "paid")
        self.assertEqual(orders[1].history(), ["new"])


if __name__ == "__main__":
    unittest.main()
