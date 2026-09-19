import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bsi_core.providers.gemini import GeminiGroundingAdapter
from google.genai import errors

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


def adapter_with(behaviour):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=behaviour))
    return GeminiGroundingAdapter(client=client, model="gemini-2.5-flash")


def test_parse_joins_text_and_reads_real_hosts():
    answer = GeminiGroundingAdapter(client=object()).parse(RAW)
    assert answer.text == (
        "For kids, Nike and Adidas are popular. Puma is also listed."
    )
    assert [d for _, d in answer.citations] == ["nike.com", "runrepeat.com"]
    assert answer.citations[0][0].endswith("/AAA")


def test_parse_survives_empty_payload():
    answer = GeminiGroundingAdapter(client=object()).parse({})
    assert (answer.text, answer.citations) == ("", [])


def test_cost_counts_tokens_and_the_grounded_query():
    # 10 * 0.30 + (100 + 20) * 2.50 = 303, plus 14_000 for grounding.
    assert GeminiGroundingAdapter(client=object()).cost(RAW) == 14_303
    ungrounded = {"usage_metadata": RAW["usage_metadata"]}
    assert GeminiGroundingAdapter(client=object()).cost(ungrounded) == 303


def test_query_ok():
    response = SimpleNamespace(model_dump=lambda **_: RAW)
    result = adapter_with(lambda **_: response).query("q", "IN", "en")
    assert result.kind == "ok"
    assert result.raw == RAW
    assert result.cost_micros == 14_303
    assert result.model_version == "gemini-2.5-flash"
    assert result.params["country"] == "IN"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (errors.ClientError(429, {"error": {"message": "quota"}}), "retryable"),
        (errors.ServerError(503, {"error": {"message": "down"}}), "retryable"),
        (errors.ClientError(400, {"error": {"message": "bad"}}), "fatal"),
        (TimeoutError("slow"), "retryable"),
    ],
)
def test_query_never_raises(exc, kind):
    def boom(**_):
        raise exc

    result = adapter_with(boom).query("q", "IN", "en")
    assert result.kind == kind
    assert result.error


@pytest.mark.parametrize("name", ["kids_shoes", "crm"])
def test_parse_recorded_payloads(name):
    raw = json.loads(Path(f"tests/fixtures/gemini_{name}.json").read_text())
    adapter = GeminiGroundingAdapter(client=object())
    answer = adapter.parse(raw)
    assert len(answer.text) > 100
    assert answer.citations
    assert all("." in d and "/" not in d for _, d in answer.citations)
    assert "vertexaisearch" not in {d for _, d in answer.citations}
    assert adapter.cost(raw) > 14_000
