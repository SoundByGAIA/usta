from users import display_name


def names(users):
    return sorted(display_name(u) for u in users)
