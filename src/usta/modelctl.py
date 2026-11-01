"""Çalışırken model/API değiştirme. Kaynaklar: açılışta verilen varsayılan uç nokta + `apis.json`.

Her kaynağın modelleri kendi uç noktasından listelenir; yalnız o listedeki bir model seçilebilir.
Yeni model bir sonraki görevden itibaren geçerlidir. Seçim `~/.usta/config.json`'a yazılır (sır yok).
Protokol açıkça verilmediyse model için ölçülür.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from usta import apis, profile
from usta import settings as st
from usta.models import ModelClient, ModelError

DEFAULT_API = "varsayılan"


class ModelSwitchError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status, self.message = status, message


class ModelControl:
    def __init__(
        self,
        home: Path,
        endpoint: str,
        name: str,
        protocol: str,
        build: Callable[[str, str, str, str | None], ModelClient],
        discover: Callable[[str, str | None], list[str]],
        explicit_protocol: str | None = None,
        persist: bool = True,
        default_key: str | None = None,
        api: str = DEFAULT_API,
    ):
        self.home = Path(home)
        self.default = apis.Api(DEFAULT_API, endpoint, default_key)
        self.api, self.name, self.protocol = api, name, protocol
        self.build, self.discover = build, discover
        self.explicit_protocol, self.persist = explicit_protocol, persist
        self._lock = threading.Lock()
        src = self._source(api) or self.default
        self.endpoint = src.endpoint
        self._client = build(src.endpoint, name, protocol, src.key)

    def current(self) -> ModelClient:
        return self._client

    def sources(self) -> list[apis.Api]:
        try:
            stored = list(apis.load(self.home).values())
        except apis.ApiError:
            stored = []
        return [self.default, *stored]

    def _source(self, name: str) -> apis.Api | None:
        return next((s for s in self.sources() if s.name == name), None)

    def info(self) -> dict:
        srcs = self.sources()

        def one(s: apis.Api) -> dict:
            try:
                models = self.discover(s.endpoint, s.key)
                err = None if models else "model listesi boş ya da uç noktaya ulaşılamadı"
            except Exception:  # noqa: BLE001 - tek kaynak hata verirse diğerleri görünsün
                models, err = [], "uç noktaya ulaşılamadı"
            if s.name == self.api and self.name not in models:
                models = [self.name, *models]
            return {"api": s.name, "endpoint": s.endpoint, "models": models, "error": err}

        with ThreadPoolExecutor(max_workers=min(8, len(srcs))) as ex:
            groups = list(ex.map(one, srcs))
        return {
            "api": self.api,
            "model": self.name,
            "protocol": self.protocol,
            "apis": groups,
            "models": next((g["models"] for g in groups if g["api"] == self.api), []),
        }

    def switch(self, name: str, api: str | None = None) -> dict:
        with self._lock:
            api = api or self.api
            src = self._source(api)
            if src is None:
                raise ModelSwitchError("API yok", 404)
            if name == self.name and api == self.api:
                return self.info()
            if name not in self.discover(src.endpoint, src.key):
                raise ModelSwitchError("model uç noktanın listesinde yok")
            protocol = self.explicit_protocol
            if protocol is None:
                try:
                    protocol = profile.resolve_protocol(
                        self.home,
                        src.endpoint,
                        name,
                        lambda: self.build(src.endpoint, name, "native", src.key),
                    ).protocol
                except (profile.ProfileError, ModelError) as e:
                    raise ModelSwitchError(f"model denenemedi: {e}", 502) from None
            client = self.build(src.endpoint, name, protocol, src.key)
            self._client, self.name, self.protocol = client, name, protocol
            self.api, self.endpoint = api, src.endpoint
            if self.persist:
                try:
                    cur = st.load(self.home)
                    st.save(
                        self.home,
                        dataclasses.replace(
                            cur, model=name, api=None if api == DEFAULT_API else api
                        ),
                    )
                except (OSError, ValueError):
                    pass
            return self.info()
