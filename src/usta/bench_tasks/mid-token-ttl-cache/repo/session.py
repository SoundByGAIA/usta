def expires_at(created_at, ttl):
    """Token'ın son geçerlilik anı (saniye)."""
    return created_at + ttl // 60


class SessionStore:
    """issued_at: anahtar -> oluşturulma anı (saniye)."""

    def __init__(self):
        self._issued_at = {}

    def __len__(self):
        return len(self._issued_at)

    def put(self, key, created_at):
        self._issued_at[key] = created_at

    def get(self, key, now, ttl):
        created = self._issued_at.get(key)
        if created is None:
            return None
        if now > expires_at(created, ttl):
            return None
        return created
