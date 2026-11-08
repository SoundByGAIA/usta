from delivery import send


def route(kind, user, msg):
    """sms ise phone, değilse kullanıcı kimliği üzerinden mesajı yönlendirir."""
    if kind == "sms":
        return send("sms", msg, to=user["phone"])
    return send("email", msg, to=user["id"])
