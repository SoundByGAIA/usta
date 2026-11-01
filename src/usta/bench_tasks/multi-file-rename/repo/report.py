from users import get_user_name


def names(users):
    return sorted(get_user_name(u) for u in users)
