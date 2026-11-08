from delivery import send


def route(kind, user, msg):
    """sms ise phone, değilse kullanıcı kimliği üzerinden mesajı yönlendirir."""
    if kind == "sms":
        return send("sms", user["phone"], msg)
    return send("email", user["id"], msg)
