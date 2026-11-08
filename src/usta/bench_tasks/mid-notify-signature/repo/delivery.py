from transports import deliver


def send(channel, recipient, message):
    """Mesajı verilen kanaldan alıcıya gönderir ve (kanal, alıcı) döndürür."""
    deliver(channel, recipient, message)
    return (channel, recipient)
