import unittest

import auth
import roles
import session


class T(unittest.TestCase):
    def test_role_ttls(self):
        self.assertEqual(roles.ttl_for("admin"), 3600)
        self.assertEqual(roles.ttl_for("member"), 600)
        self.assertEqual(roles.ttl_for("guest"), 60)
        self.assertEqual(roles.ttl_for("bilinmeyen"), 300)

    def test_role_detection(self):
        self.assertEqual(roles.role_for("guest_7"), "guest")
        self.assertEqual(roles.role_for("ali"), "member")
        self.assertEqual(roles.role_for("root"), "admin")

    def test_ttl_uses_role(self):
        self.assertEqual(auth.token_ttl_seconds("root", 0), 3600)
        self.assertEqual(auth.token_ttl_seconds("ali", 0), 600)
        self.assertEqual(auth.token_ttl_seconds("guest_7", 0), 60)

    def test_expires_at_adds_seconds(self):
        self.assertEqual(session.expires_at(1000, 600), 1600)
        self.assertEqual(session.expires_at(0, 60), 60)

    def test_expired_boundary(self):
        self.assertFalse(auth.is_expired(0, 60, now=0))
        self.assertFalse(auth.is_expired(0, 60, now=59))
        self.assertFalse(auth.is_expired(0, 60, now=60))
        self.assertTrue(auth.is_expired(0, 60, now=61))

    def test_store_returns_live_entry(self):
        store = session.SessionStore()
        store.put("k", 100)
        self.assertEqual(store.get("k", now=150, ttl=60), 100)
        self.assertEqual(store.get("k", now=160, ttl=60), 100)
        self.assertIsNone(store.get("yok", now=100, ttl=60))

    def test_store_drops_expired_entry(self):
        store = session.SessionStore()
        store.put("k", 100)
        self.assertIsNone(store.get("k", now=161, ttl=60))
        self.assertEqual(len(store), 0)
        self.assertIsNone(store.get("k", now=161, ttl=60))


if __name__ == "__main__":
    unittest.main()
