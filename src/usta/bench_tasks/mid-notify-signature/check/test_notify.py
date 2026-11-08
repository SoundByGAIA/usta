import unittest

import alerts
import router
import delivery
import transports
from delivery import send


class Base(unittest.TestCase):
    def setUp(self):
        transports.reset()


class SendSignature(Base):
    def test_keyword_only_to(self):
        self.assertEqual(send("sms", "Merhaba", to="+90"), ("sms", "+90", 1))
        self.assertEqual(transports.sent(), [("sms", "+90", "Merhaba")])

    def test_to_is_required_and_keyword(self):
        with self.assertRaises(TypeError):
            send("sms", "Merhaba")
        with self.assertRaises(TypeError):
            send("sms", "Merhaba", "+90")
        with self.assertRaises(TypeError):
            send("sms", "Merhaba", "+90", True)

    def test_urgent_prefix(self):
        send("sms", "x", to="y", urgent=True)
        send("sms", "z", to="y")
        self.assertEqual(
            transports.sent(), [("sms", "y", "ACIL: x"), ("sms", "y", "z")]
        )

    def test_invalid_retries(self):
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                send("sms", "x", to="y", retries=bad)


class Retries(Base):
    def test_retries_until_success(self):
        calls = {"n": 0}
        real = delivery.deliver

        def flaky(channel, recipient, text):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("gecici")
            return real(channel, recipient, text)

        real = delivery.deliver
        delivery.deliver = flaky
        try:
            result = send("sms", "x", to="y", retries=5)
        finally:
            delivery.deliver = real
        self.assertEqual(result, ("sms", "y", 3))
        self.assertEqual(transports.sent(), [("sms", "y", "x")])

    def test_gives_up_after_retries(self):
        calls = {"n": 0}

        def always_fail(channel, recipient, text):
            calls["n"] += 1
            raise ConnectionError("yok")

        real = delivery.deliver
        delivery.deliver = always_fail
        try:
            with self.assertRaises(ConnectionError):
                send("sms", "x", to="y", retries=3)
        finally:
            delivery.deliver = real
        self.assertEqual(calls["n"], 3)

    def test_default_single_attempt(self):
        calls = {"n": 0}

        def always_fail(channel, recipient, text):
            calls["n"] += 1
            raise ConnectionError("yok")

        real = delivery.deliver
        delivery.deliver = always_fail
        try:
            with self.assertRaises(ConnectionError):
                send("sms", "x", to="y")
        finally:
            delivery.deliver = real
        self.assertEqual(calls["n"], 1)

    def test_other_errors_not_retried(self):
        calls = {"n": 0}

        def boom(channel, recipient, text):
            calls["n"] += 1
            raise KeyError("kanal")

        real = delivery.deliver
        delivery.deliver = boom
        try:
            with self.assertRaises(KeyError):
                send("sms", "x", to="y", retries=4)
        finally:
            delivery.deliver = real
        self.assertEqual(calls["n"], 1)


class Callers(Base):
    def test_alerts(self):
        self.assertEqual(alerts.notify({"id": "u1"}, "selam"), ("push", "u1", 1))
        self.assertEqual(alerts.notify({"id": "u2", "urgent": True}, "yangin"), ("push", "u2", 1))
        self.assertEqual(
            transports.sent(), [("push", "u1", "selam"), ("push", "u2", "ACIL: yangin")]
        )

    def test_router(self):
        user = {"id": "u3", "phone": "+9055"}
        self.assertEqual(router.route("sms", user, "a"), ("sms", "+9055", 1))
        self.assertEqual(router.route("email", user, "b"), ("email", "u3", 1))
        self.assertEqual(
            transports.sent(),
            [("sms", "+9055", "a"), ("email", "u3", "b")],
        )


if __name__ == "__main__":
    unittest.main()
