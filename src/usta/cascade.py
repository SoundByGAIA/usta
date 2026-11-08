"""Kademeli yönlendirme (DENEYSEL): ucuz modelle başla, takılırsa aynı konuşmayı güçlü modelle sürdür.

Takılma işareti ajanın kendi gözleminden gelir (gizli test ya da çözüm bilgisi kullanılmaz): bitirme kapısı
başarısız saydıysa ya da devre kesici açıldıysa konuşmanın geri kalanı güçlü modele verilir. Konuşma geçmişi
olduğu gibi taşınır; yükseltme geri alınmaz (görev başına en fazla bir geçiş). Ek işaret: ucuz model hiç düzenleme yapmadan araç
çağırmayı bırakıp "bitti" derse (zayıf modellerde sık) o yanıt atılır ve aynı istek güçlü modele sorulur.
Sınır: kapı yalnız deponun kendi testlerini görür; test yoksa ya da ucuz model yanlış çözümü doğrulatamıyorsa
yükseltme tetiklenmez. Bu yüzden fayda ölçümle gösterilmeden varsayılan olmaz (bkz. docs/bench-orta-olcum.md).
"""

from __future__ import annotations

from usta.models import Message, ModelClient, ModelResponse


class _SumUsage:
    """İki istemcinin toplam kullanımı; `last_prompt` etkin istemciden okunur (bağlam boyutu)."""

    def __init__(self, owner: CascadeModel):
        self._o = owner

    def _sum(self, field: str) -> int:
        return sum(
            getattr(getattr(m, "usage", None), field, 0) for m in (self._o.cheap, self._o.strong)
        )

    prompt = property(lambda s: s._sum("prompt"))
    completion = property(lambda s: s._sum("completion"))
    requests = property(lambda s: s._sum("requests"))
    cached = property(lambda s: s._sum("cached"))
    rescued = property(lambda s: s._sum("rescued"))
    last_prompt = property(lambda s: getattr(getattr(s._o.active, "usage", None), "last_prompt", 0))


class CascadeModel:
    def __init__(
        self,
        cheap: ModelClient,
        strong: ModelClient,
        *,
        after_failures: int = 1,
        empty_handed: bool = True,
    ):
        self.empty_handed = empty_handed
        self.cheap, self.strong = cheap, strong
        self.after_failures = max(1, after_failures)
        self.usage = _SumUsage(self)
        self.escalated = False
        self._failures = 0
        self._edited = False

    @property
    def active(self) -> ModelClient:
        return self.strong if self.escalated else self.cheap

    def reset(self) -> None:
        """Yeni görev: ucuz modele dön (istemci kullanım sayaçları birikir; fark alınarak okunur)."""
        self.escalated = False
        self._failures = 0
        self._edited = False

    def observe(self, kind: str, data: dict) -> None:
        if kind == "tool_call" and data.get("tool") in ("write_file", "edit_file"):
            self._edited = True
        if self.escalated:
            return
        if kind == "verification" and data.get("status") == "failed":
            self._failures += 1
        elif kind == "breaker":
            self._failures += self.after_failures  # devre kesici açıldı: tek başına yeter
        if self._failures >= self.after_failures:
            self.escalated = True

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> ModelResponse:
        resp = self.active.chat(messages, tools)
        if not self.escalated and self.empty_handed and not resp.tool_calls and not self._edited:
            self.escalated = True  # ucuz model hiçbir şey yapmadan bitirdi: yanıtı at, güçlüye sor
            return self.strong.chat(messages, tools)
        return resp
