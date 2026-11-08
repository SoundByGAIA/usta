from roles import role_for
from session import expires_at


def token_ttl_seconds(username, created_at):
    """Kullanıcı için token ömrü (saniye)."""
    role_for(username)
    return 300


def is_expired(created_at, ttl, now):
    """Token'ın süresi dolmuş mu?"""
    return now >= expires_at(created_at, ttl)
