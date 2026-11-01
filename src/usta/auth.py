"""Portal girişi için tek kullanımlık, kısa ömürlü kodlar.

Tarayıcıyı jetonla açmak jetonu URL'ye (süreç listesi, tarayıcı geçmişi) koyardı. Bunun yerine
terminal bir kod üretir; tarayıcı kodu jetonla bir kez takas eder. Kod 2 dakika geçerlidir, bir kez
kullanılır ve art arda hatalı denemelerde tüm kodlar kilitlenir.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable


class LoginCodes:
    def __init__(
        self,
        ttl: float = 120.0,
        max_failures: int = 5,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl, self.max_failures, self.clock = ttl, max_failures, clock
        self._code: str | None = None
        self._expires = 0.0
        self._failures = 0
        self._lock = threading.Lock()

    @property
    def locked(self) -> bool:
        return self._failures >= self.max_failures

    def issue(self) -> str:
        with self._lock:
            self._code = secrets.token_urlsafe(24)
            self._expires = self.clock() + self.ttl
            self._failures = 0
            return self._code

    def redeem(self, code: object) -> bool:
        with self._lock:
            if self.locked or self._code is None or not isinstance(code, str) or len(code) > 200:
                if not self.locked and self._code is not None:
                    self._failures += 1
                return False
            ok = (
                hmac.compare_digest(code.encode(), self._code.encode())
                and self.clock() <= self._expires
            )
            if ok:
                self._code = None  # tek kullanım
            else:
                self._failures += 1
            return ok
