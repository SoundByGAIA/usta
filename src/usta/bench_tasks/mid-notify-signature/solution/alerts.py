from delivery import send


def notify(user, msg):
    """Bir kullanıcıya push bildirimi gönderir."""
    return send("push", msg, to=user["id"], urgent=user.get("urgent", False))
