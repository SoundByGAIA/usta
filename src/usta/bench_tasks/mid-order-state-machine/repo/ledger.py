from orders import Order


class Ledger:
    """Siparişleri kanala göre toplar."""

    def __init__(self):
        self._orders = {}

    def add(self, channel, items):
        order = Order(items)
        self._orders.setdefault(channel, []).append(order)
        return len(self._orders[channel])

    def channels(self):
        return sorted(self._orders)

    def count(self, channel):
        return len(self._orders.get(channel, []))

    def orders(self, channel):
        return list(self._orders.get(channel, []))
