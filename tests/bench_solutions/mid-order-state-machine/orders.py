class InvalidTransition(Exception):
    """İzin verilmeyen durum geçişi."""


_TRANSITIONS = {
    "new": {"pay": "paid", "cancel": "cancelled"},
    "paid": {"ship": "shipped", "cancel": "cancelled"},
    "shipped": {"deliver": "delivered"},
    "delivered": {},
    "cancelled": {},
}


class Order:
    """Sipariş durum makinesi: new/paid/shipped/delivered/cancelled."""

    def __init__(self, items):
        self._items = dict(items)
        self._state = "new"
        self._history = ["new"]
        self._paid_total = 0

    def _move(self, action):
        target = _TRANSITIONS.get(self._state, {}).get(action)
        if target is None:
            raise InvalidTransition(f"{self._state} durumunda {action} yok")
        self._state = target
        self._history.append(target)
        return target

    def pay(self, amount):
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("amount > 0 olmalı")
        new_state = self._move("pay")
        self._paid_total += amount
        return new_state

    def ship(self):
        return self._move("ship")

    def deliver(self):
        return self._move("deliver")

    def cancel(self):
        return self._move("cancel")

    @property
    def paid_total(self):
        return self._paid_total

    def items(self):
        return dict(self._items)

    def history(self):
        return list(self._history)
