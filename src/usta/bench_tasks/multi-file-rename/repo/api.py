from users import get_user_name


def serialize(user):
    return {"id": user["id"], "name": get_user_name(user)}
