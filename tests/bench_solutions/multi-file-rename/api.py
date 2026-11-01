from users import display_name


def serialize(user):
    return {"id": user["id"], "name": display_name(user)}
