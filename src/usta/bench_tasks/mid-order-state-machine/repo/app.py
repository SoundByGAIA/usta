from ledger import Ledger


def checkout(ledger, channel, items):
    """Yeni sipariş açar ve kanala kaydeder."""
    return ledger.add(channel, items)
