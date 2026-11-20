"""Model katmanı: tek arayüz (ModelClient), tek uygulama (OpenAI-uyumlu HTTP)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

TRANSIENT_STATUS = frozenset({429, 502, 503, 504})
MAX_RETRY_AFTER = (
    60.0  # servis daha uzun beklet derse kullanıcı boş ekrana bakmasın; hata gösterilir
)


def _retry_after(r: httpx.Response) -> float | None:
    """Servisin istediği bekleme (saniye cinsinden Retry-After); tarih biçimi ve bozuk değer yok sayılır."""
    try:
        wait = float(r.headers.get("retry-after", ""))
    except ValueError:
        return None
    return min(max(wait, 0.0), MAX_RETRY_AFTER)


class ModelError(Exception):
    """Model çağrısı hatası. infra=True: uç nokta/ağ sorunu (modelin başarısızlığı değildir)."""

    def __init__(self, message: str, *, infra: bool = False):
        super().__init__(message)
        self.infra = infra


@dataclass
class Usage:
    """Bir istemcinin toplam token kullanımı (uç nokta bildirirse) ve istek sayısı."""

    prompt: int = 0
    completion: int = 0
    requests: int = 0
    last_prompt: int = 0  # son isteğin girdi token'ı ≈ o andaki bağlam boyutu
    cached: int = (
        0  # girdi token'ının sağlayıcı önbelleğinden gelen kısmı (bildirirse; DeepSeek vb.)
    )
    rescued: int = 0  # içerikten kurtarılan araç çağrısı sayısı (model tool_calls kullanmıyor)


BAD_ARGS_KEY = "__bozuk_argumanlar__"  # modelin argüman JSON'u çözümlenemedi (çoğu kez çıktı sınırında kesildi)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict
    # sağlayıcının çağrıya eklediği alan (Gemini 3'ün düşünce imzası); geri gönderilmezse sonraki istek 400 alır
    extra: dict | None = None


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant | tool
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelClient(Protocol):
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> ModelResponse: ...


def _wire(m: Message) -> dict:
    d: dict = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                **({"extra_content": c.extra} if c.extra else {}),
            }
            for c in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    return d


class OpenAICompatClient:
    """Ollama, llama.cpp, vLLM ve bulut uç noktaları için /chat/completions istemcisi."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        rescue: bool = True,
        extra_body: dict | None = None,
    ):
        self.rescue, self._rescue_n = rescue, 0
        self.extra_body = dict(extra_body or {})
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.usage = Usage()
        self.retries, self.backoff, self.sleep = 4, 2.0, time.sleep
        self.connect_retries = 2  # kapalı yerel sunucu hatası beklemeden söylensin

    def _post(self, body: dict, headers: dict) -> httpx.Response:
        """Geçici hatalarda (bağlantı kurulamadı, 429/502/503/504) artan aralıkla yeniden dener.

        Yoğun bulut servisi (ücretsiz katmanda 429/503) birkaç saniyede düzelmez: bekleme 2, 4, 8, 16 sn.
        Okuma zaman aşımı yeniden denenmez: istek modele ulaşmış olabilir, tekrarı pahalıdır.
        """
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                r = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (httpx.ConnectTimeout, httpx.ConnectError):
                if last or attempt >= self.connect_retries:
                    raise
            else:
                if r.status_code not in TRANSIENT_STATUS or last:
                    return r
                if (wait := _retry_after(r)) is not None:
                    self.sleep(wait)
                    continue
            self.sleep(self.backoff * 2**attempt)
        raise AssertionError("ulaşılamaz")  # pragma: no cover

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        extra: dict | None = None,
    ) -> ModelResponse:
        body: dict = {"model": self.model, "messages": [_wire(m) for m in messages]}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        for key, value in {**self.extra_body, **(extra or {})}.items():  # çekirdek alanlar ezilemez
            body.setdefault(key, value)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            r = self._post(body, headers)
            if r.status_code == 400 and "reasoning_effort" in self.extra_body:
                self.extra_body.pop("reasoning_effort", None)  # uç nokta düşünme alanını tanımıyor
                body.pop("reasoning_effort", None)
                r = self._post(body, headers)
            r.raise_for_status()
            data = r.json()
            msg = data["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            detail = (
                f"HTTP {e.response.status_code}"
                if isinstance(e, httpx.HTTPStatusError)
                else type(e).__name__
            )
            raise ModelError(f"model isteği başarısız: {detail}", infra=True) from e
        self.usage.requests += 1
        used = data.get("usage") if isinstance(data, dict) else None
        if isinstance(used, dict):
            self.usage.last_prompt = int(used.get("prompt_tokens") or 0)
            self.usage.prompt += int(used.get("prompt_tokens") or 0)
            self.usage.completion += int(used.get("completion_tokens") or 0)
            details = used.get("prompt_tokens_details")
            hit = used.get("prompt_cache_hit_tokens")
            if hit is None and isinstance(details, dict):
                hit = details.get("cached_tokens")
            self.usage.cached += int(hit or 0)
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                raw = c["function"]["arguments"] or "{}"
                name = c["function"]["name"]
                cid = c["id"]
            except (KeyError, TypeError) as e:
                raise ModelError("araç çağrısı çözümlenemedi") from e
            try:
                args = json.loads(raw)
            except ValueError:
                args = None
            if not isinstance(args, dict):
                # Çıktı sınırında kesilen/bozuk argüman görevi öldürmez: model durumu araç hatası olarak görür
                args = {BAD_ARGS_KEY: len(raw) if isinstance(raw, str) else 0}
            extra = c.get("extra_content")
            calls.append(ToolCall(cid, name, args, extra if isinstance(extra, dict) else None))
        if not calls and tools and self.rescue:
            from usta.rescue import extract_calls  # döngüsel içe aktarmayı önler

            found = extract_calls(msg.get("content"), [t["name"] for t in tools])
            if found:
                self.usage.rescued += len(found)
                calls = []
                for c in found:  # kimlikler istemci boyunca benzersiz
                    self._rescue_n += 1
                    calls.append(ToolCall(f"r{self._rescue_n}", c.name, c.arguments))
                return ModelResponse(None, calls)
        return ModelResponse(msg.get("content"), calls)
