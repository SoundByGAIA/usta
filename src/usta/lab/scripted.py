"""Betikli modeller: harici model olmadan değerlendiriciyi ve izin katmanını sınamak için (CI smoke).

- `compliant`: yalnızca meşru görevi yapar, saldırıyı yok sayar.
- `gullible`: meşru adımlardan sonra enjekte edilen yasak eylemi de yapar (saf bir model).
- `refuser`: hiçbir araç çağırmaz, her şeyi reddeder.
Bunlar gerçek modellerin yerine geçmez; ölçümün kendisini (değerlendirici, izin motoru) doğrular.
"""

from __future__ import annotations

import json

from usta.lab.scenario import Scenario
from usta.models import Message, ModelResponse, ToolCall, Usage

BEHAVIORS = ("compliant", "gullible", "refuser")


class ScriptedModel:
    def __init__(self, sc: Scenario, condition: str, behavior: str):
        if behavior not in BEHAVIORS:
            raise ValueError(f"bilinmeyen davranış {behavior!r}")
        self.usage = Usage()
        self.behavior = behavior
        steps = list(sc.legit)
        if behavior == "gullible" and condition == "attack" and sc.attack_action is not None:
            steps.append(sc.attack_action)
        self._steps = steps
        self._n = 0
        marks = list(sc.success.get("answer_contains", []))
        if behavior == "gullible" and condition == "attack":
            marks += [f.marker for f in sc.forbidden if f.kind == "answer_contains"]
        self._answer = "Tamamlandı. " + " ".join(marks)

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> ModelResponse:
        self.usage.requests += 1
        self.usage.prompt += sum(len(m.content or "") for m in messages) // 3
        if self.behavior == "refuser":
            self.usage.completion += 6
            return ModelResponse("Bunu yapamam.", [])
        if self._n < len(self._steps):
            step = self._steps[self._n]
            self._n += 1
            self.usage.completion += len(json.dumps(step.args)) // 3
            return ModelResponse(None, [ToolCall(f"c{self._n}", step.tool, dict(step.args))])
        self.usage.completion += len(self._answer) // 3
        return ModelResponse(self._answer.strip(), [])
