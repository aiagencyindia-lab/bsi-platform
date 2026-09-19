"""The interface every engine adapter implements. Adapters never raise."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class EngineResult:
    kind: Literal["ok", "retryable", "fatal"]
    raw: dict[str, Any] | None = None
    error: str | None = None
    model: str = ""
    model_version: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    cost_micros: int = 0


@dataclass
class ParsedAnswer:
    text: str
    citations: list[tuple[str, str]]  # (url, domain), in answer order


class EngineAdapter(Protocol):
    code: str

    def query(
        self,
        prompt: str,
        country: str,
        language: str,
        *,
        grounded: bool = True,
        context: str | None = None,
    ) -> EngineResult: ...

    def parse(self, raw: dict[str, Any]) -> ParsedAnswer: ...

    def cost(self, raw: dict[str, Any]) -> int: ...

    def health(self) -> bool: ...

    def rate_budget(self) -> int: ...
