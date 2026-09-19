import json
from pathlib import Path
from types import SimpleNamespace

from bsi_core.extraction import Extractor
from bsi_core.labels import JudgeOut, JudgeReply, SentenceLabel
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


def judge(selected, names):
    return JudgeReply(
        JudgeOut(
            labels=[
                SentenceLabel(
                    sentence=1,
                    entity="Nike",
                    label="recommends",
                    sentiment="positive",
                    sentiment_conf=0.9,
                )
            ]
        ),
        "fake",
        777,
    )


def test_observation_detail_has_evidence_and_judge_cost(
    client, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    Extractor(
        GeminiGroundingAdapter(client=object()), LocalRawStore(), judge
    ).run(org.id, oid)
    got = client.get(f"/v1/observations/{oid}", headers=org.headers).json()
    assert got["extraction"]["cost_micros"] == 777
    assert got["mentions"][0]["evidence_sentence"] == (
        "For kids, Nike and Adidas are popular."
    )


def test_recommendation_rate_is_flagged_experimental_by_default(
    client, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    got = client.get(f"/v1/brands/{bid}/metrics", headers=org.headers).json()
    assert got["recommendation_rate"]["experimental"] is True
    assert "experimental" not in got["mention_rate"]


def test_flag_can_be_turned_off(client, make_org, make_brand, monkeypatch):
    import bsi_api.routers.metrics as metrics_router

    monkeypatch.setattr(
        metrics_router,
        "get_settings",
        lambda: SimpleNamespace(rec_rate_experimental=False),
    )
    org = make_org()
    bid = make_brand(org)
    got = client.get(f"/v1/brands/{bid}/metrics", headers=org.headers).json()
    assert got["recommendation_rate"]["experimental"] is False
