from delivery import send


def notify(user, msg):
    """Bir kullanıcıya push bildirimi gönderir."""
    return send("push", user["id"], msg)
