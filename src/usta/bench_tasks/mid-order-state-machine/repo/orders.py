class InvalidTransition(Exception):
    """İzin verilmeyen durum geçişi."""


class Order:
    """Sipariş durum makinesi: new/paid/shipped/delivered/cancelled."""

    def __init__(self, items):
        raise NotImplementedError

    def pay(self, amount):
        raise NotImplementedError

    def ship(self):
        raise NotImplementedError

    def deliver(self):
        raise NotImplementedError

    def cancel(self):
        raise NotImplementedError

    @property
    def paid_total(self):
        raise NotImplementedError

    def items(self):
        raise NotImplementedError

    def history(self):
        raise NotImplementedError
