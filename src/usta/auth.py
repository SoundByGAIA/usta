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
        digits: int | None = None,
    ):
        self.ttl, self.max_failures, self.clock, self.digits = ttl, max_failures, clock, digits
        self._code: str | None = None
        self._expires = 0.0
        self._failures = 0
        self._lock = threading.Lock()

    @property
    def locked(self) -> bool:
        return self._failures >= self.max_failures

    def issue(self) -> str:
        with self._lock:
            self._code = (
                f"{secrets.randbelow(10**self.digits):0{self.digits}d}"
                if self.digits
                else secrets.token_urlsafe(24)
            )
            self._expires = self.clock() + self.ttl
            self._failures = 0
            return self._code

    def peek(self) -> str | None:
        """Geçerli kod (süresi dolmamış, kilitsiz); kodu kendisi kullanan taraf için (ör. SPAKE2 eşleşmesi)."""
        with self._lock:
            if self.locked or self._code is None or self.clock() > self._expires:
                return None
            return self._code

    def fail(self) -> None:
        with self._lock:
            if self._code is not None:
                self._failures += 1

    def consume(self, code: str) -> bool:
        """`peek` ile alınan kod hâlâ geçerliyse tek kullanımlık olarak tüketir."""
        with self._lock:
            ok = (
                not self.locked
                and self._code is not None
                and hmac.compare_digest(code.encode(), self._code.encode())
                and self.clock() <= self._expires
            )
            if ok:
                self._code = None
            return ok

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
