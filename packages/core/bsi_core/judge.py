"""Judge model calls: retries, prices, and the three judge modes."""

import random
import time
from collections.abc import Callable

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from .config import get_settings
from .extraction import ExtractionOut, build_prompt
from .labels import (
    JudgeOut,
    JudgeReply,
    Selected,
    SentenceJudge,
    build_batched_prompt,
    build_isolated_prompt,
)
from .providers.gemini import Price


class JudgeFailed(RuntimeError):
    """A judge call failed after spending; carries what was spent."""

    def __init__(self, cause: Exception, cost_micros: int) -> None:
        super().__init__(repr(cause))
        self.cost_micros = cost_micros


# Micros per token, read 2026-09-19 (slice-2 spec §2 and slice-1 findings).
# A judge model missing here fails before any call is made.
JUDGE_PRICES = {
    "gemini-3.5-flash-lite": Price(0.30, 2.50, 0, 0),
    "gemini-2.5-flash-lite": Price(0.10, 0.40, 0, 0),
}
ATTEMPTS = 3
WAITS = (2.0, 8.0)  # before attempts 2 and 3
JITTER = 0.2


def _retryable(e: Exception) -> bool:
    if isinstance(e, errors.APIError):
        return e.code == 429 or (e.code or 0) >= 500
    return isinstance(e, TimeoutError | ConnectionError | httpx.TransportError)


def with_retries[T](
    fn: Callable[[], T], sleep: Callable[[float], None] = time.sleep
) -> T:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == ATTEMPTS or not _retryable(e):
                raise
            sleep(WAITS[attempt - 1] * random.uniform(1 - JITTER, 1 + JITTER))
    raise AssertionError("unreachable")


def judge_cost(
    model: str, usage: types.GenerateContentResponseUsageMetadata | None
) -> int:
    price = JUDGE_PRICES.get(model)
    if price is None:
        raise KeyError(f"no price for judge model {model!r} in JUDGE_PRICES")
    if usage is None:
        return 0
    tokens_in = usage.prompt_token_count or 0
    tokens_out = (usage.candidates_token_count or 0) + (
        usage.thoughts_token_count or 0
    )
    return round(
        tokens_in * price.input_per_token + tokens_out * price.output_per_token
    )


def _generate(prompt: str, schema: type[BaseModel]) -> tuple[str, int, str]:
    """One judge call with retries. Returns (json text, cost micros, model)."""
    model = get_settings().extract_model
    judge_cost(model, None)  # raise before spending if the model is unpriced
    client = genai.Client(http_options=types.HttpOptions(timeout=120_000))
    response = with_retries(
        lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    )
    return (
        response.text or "",
        judge_cost(model, response.usage_metadata),
        model,
    )


def batched_judge(selected: list[Selected], names: list[str]) -> JudgeReply:
    text, cost, model = _generate(
        build_batched_prompt(selected, names), JudgeOut
    )
    try:
        return JudgeReply(JudgeOut.model_validate_json(text), model, cost)
    except ValidationError as e:
        raise JudgeFailed(e, cost) from e


def isolated_judge(selected: list[Selected], names: list[str]) -> JudgeReply:
    # One call per sentence, with no surrounding context (spec §4.2).
    labels = []
    context, cost, model = "", 0, get_settings().extract_model
    for sel in selected:
        try:
            text, call_cost, model = _generate(
                build_isolated_prompt(sel), JudgeOut
            )
            cost += call_cost
            out = JudgeOut.model_validate_json(text)
            labels += [
                label.model_copy(update={"sentence": sel.index})
                for label in out.labels
            ]
            context = context or out.context
        except Exception as e:
            raise JudgeFailed(e, cost) from e
    return JudgeReply(JudgeOut(labels=labels, context=context), model, cost)


def legacy_judge(text: str, names: list[str]) -> tuple[ExtractionOut, int]:
    """The slice-1 whole-answer judge, kept only as an evaluation baseline."""
    raw, cost, _ = _generate(build_prompt(text, names), ExtractionOut)
    try:
        return ExtractionOut.model_validate_json(raw), cost
    except ValidationError as e:
        raise JudgeFailed(e, cost) from e


JUDGES: dict[str, SentenceJudge] = {
    "batched": batched_judge,
    "isolated": isolated_judge,
}
