URGENT_PREFIX = "ACIL:"

_sent = []


def deliver(channel, recipient, text):
    """Teslimi yapar ve kaydeder. Testler bu kaydı okur."""
    _sent.append((channel, recipient, text))


def sent():
    """Teslim edilen mesajların kopyası."""
    return list(_sent)


def reset():
    _sent.clear()
