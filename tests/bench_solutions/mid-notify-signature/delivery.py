from transports import URGENT_PREFIX, deliver


def send(channel, text, *, to, urgent=False, retries=1):
    """Mesajı verilen kanaldan `to` alıcısına gönderir; (kanal, alıcı, deneme_sayisi) döndürür."""
    if retries < 1:
        raise ValueError("retries en az 1 olmalı")
    body = f"{URGENT_PREFIX} {text}" if urgent else text
    attempt = 0
    while True:
        attempt += 1
        try:
            deliver(channel, to, body)
        except ConnectionError:
            if attempt >= retries:
                raise
            continue
        return (channel, to, attempt)
