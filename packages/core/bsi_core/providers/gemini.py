"""Gemini with Google Search grounding, through Vertex AI."""

from typing import Any, Literal, NamedTuple

from google import genai
from google.auth.exceptions import DefaultCredentialsError
from google.genai import errors, types

from ..config import get_settings
from ..matching import normalize_domain
from .base import EngineResult, ParsedAnswer


class Price(NamedTuple):
    """Micros (1e-6 USD). Grounding is billed per grounded prompt on
    Gemini 2.5 and per search query on Gemini 3."""

    input_per_token: float
    output_per_token: float  # thinking tokens are billed as output
    per_grounded_prompt: int
    per_search_query: int


# List prices read 2026-09-19. Sources: docs/findings-slice1.md (2.5) and
# the slice-2 spec §2 (3.8). 3.8 is recorded at its standard rate from
# 2027-01-01; it is cheaper until then, but planning should not rely on it.
# ponytail: marginal price at scale; the free grounding allowance (1,500
# prompts/day on 2.5, 5,000 queries/month on 3) is not modelled.
# A model missing here fails its observations rather than being mispriced.
PRICES = {
    "gemini-2.5-flash": Price(0.30, 2.50, 35_000, 0),
    "gemini-3.8-flash": Price(1.50, 7.50, 0, 14_000),
}


class GeminiGroundingAdapter:
    code = "gemini"

    def __init__(self, client: Any = None, model: str | None = None) -> None:
        self._client = client
        self._model = model or get_settings().engine_model

    def query(self, prompt: str, country: str, language: str) -> EngineResult:
        # Locale is recorded, not enforced: the prompt is sent as written.
        # Temperature is left at the provider default on purpose (PRD 10.3).
        params: dict[str, Any] = {
            "country": country,
            "language": language,
            "tools": ["google_search"],
            "temperature": "provider_default",
        }
        try:
            if self._client is None:
                self._client = genai.Client(
                    http_options=types.HttpOptions(timeout=120_000)
                )
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            raw = response.model_dump(mode="json", exclude_none=True)
        except errors.APIError as e:
            retry = e.code == 429 or (e.code or 0) >= 500
            kind: Literal["retryable", "fatal"] = (
                "retryable" if retry else "fatal"
            )
            return EngineResult(
                kind,
                error=f"{e.code} {e.message}",
                model=self._model,
                params=params,
            )
        except DefaultCredentialsError as e:
            return EngineResult(
                "fatal", error=repr(e), model=self._model, params=params
            )
        except Exception as e:  # timeouts, connection resets
            return EngineResult(
                "retryable", error=repr(e), model=self._model, params=params
            )
        try:
            # Malformed/unparseable payload shapes (e.g. a numeric field
            # that isn't a number) won't fix themselves on retry, so any
            # failure deriving fields from `raw` is fatal, not retryable.
            model_version = raw.get("model_version")
            cost_micros = self.cost(raw)
        except Exception as e:
            return EngineResult(
                "fatal",
                raw=raw,
                error=repr(e),
                model=self._model,
                params=params,
            )
        return EngineResult(
            "ok",
            raw=raw,
            model=self._model,
            model_version=model_version,
            params=params,
            cost_micros=cost_micros,
        )

    @staticmethod
    def _candidate(raw: dict[str, Any]) -> dict[str, Any]:
        candidates = raw.get("candidates") or [{}]
        first: dict[str, Any] = candidates[0]
        return first

    def parse(self, raw: dict[str, Any]) -> ParsedAnswer:
        candidate = self._candidate(raw)
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            p.get("text") or "" for p in parts if not p.get("thought")
        )
        meta = candidate.get("grounding_metadata") or {}
        citations: list[tuple[str, str]] = []
        for chunk in meta.get("grounding_chunks") or []:
            web = chunk.get("web") or {}
            # uri is a redirect; the real host is only in domain/title.
            host = normalize_domain(web.get("domain") or web.get("title") or "")
            if host:
                citations.append((web.get("uri") or "", host))
        return ParsedAnswer(text=text, citations=citations)

    def cost(self, raw: dict[str, Any]) -> int:
        price = PRICES.get(self._model)
        if price is None:
            raise KeyError(f"no price for model {self._model!r} in PRICES")
        usage = raw.get("usage_metadata") or {}
        tokens_in = usage.get("prompt_token_count") or 0
        tokens_out = (usage.get("candidates_token_count") or 0) + (
            usage.get("thoughts_token_count") or 0
        )
        meta = self._candidate(raw).get("grounding_metadata") or {}
        queries = len(meta.get("web_search_queries") or [])
        grounded = bool(meta.get("grounding_chunks") or queries)
        return round(
            tokens_in * price.input_per_token
            + tokens_out * price.output_per_token
        ) + (
            price.per_grounded_prompt * grounded
            + price.per_search_query * queries
        )

    def health(self) -> bool:
        return True

    def rate_budget(self) -> int:
        return 60
