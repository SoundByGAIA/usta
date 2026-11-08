ROLE_TTLS = {"admin": 900, "member": 600, "guest": 60}


def role_for(username):
    """Kullanıcı adına göre rol türü. 'guest_' ön eki (harf büyüklüğü farkı yok) guests türüdür."""
    if username.startswith("guest_"):
        return "guest"
    if username in ("root", "admin"):
        return "admin"
    return "member"


def ttl_for(role):
    """Rol türüne göre token ömrü (saniye)."""
    return ROLE_TTLS.get(role, 300)
