from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCapability:
    text: bool = False
    vision: bool = False
    structured_output: bool = False
    strong_reasoning: bool = False


@dataclass
class ProviderResult:
    provider: str
    model: str
    data: Any
    usage: dict[str, Any]
    latency_ms: int


class AIProvider(Protocol):
    name: str
    capability: ProviderCapability

    def run(self, task: dict[str, Any]) -> ProviderResult:
        ...
