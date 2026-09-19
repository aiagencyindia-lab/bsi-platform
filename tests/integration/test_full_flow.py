import json
from functools import partial
from pathlib import Path

import pytest
from bsi_core.extraction import ExtractionOut, extract
from bsi_core.providers.base import EngineResult
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from bsi_workers.worker import process_one

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


class CannedGemini(GeminiGroundingAdapter):
    def __init__(self):
        super().__init__(client=object())

    def query(self, prompt, country, language):
        return EngineResult(
            "ok", raw=RAW, model="canned", cost_micros=self.cost(RAW)
        )


def test_prompt_to_metric(client, make_org):
    h = make_org().headers
    bid = client.post("/v1/brands", headers=h, json={"name": "Nike"}).json()[
        "id"
    ]
    base = f"/v1/brands/{bid}"
    client.post(f"{base}/domains", headers=h, json={"host": "nike.com"})
    client.post(f"{base}/competitors", headers=h, json={"name": "Adidas"})
    client.post(
        f"{base}/prompts", headers=h, json=[{"text": "a"}, {"text": "b"}]
    )
    run = client.post(f"{base}/runs", headers=h).json()
    assert run["enqueued"] == 6

    adapter, store = CannedGemini(), LocalRawStore()
    extract_fn = partial(
        extract,
        adapter=adapter,
        store=store,
        judge=lambda text, names: ExtractionOut(),
    )
    while process_one(adapter, store, extract_fn):
        pass

    job = client.get(run["status_url"], headers=h).json()
    assert (job["status"], job["done"], job["failed"]) == ("done", 6, 0)
    assert client.post(f"{base}/runs", headers=h).json()["enqueued"] == 0

    got = client.get(f"{base}/metrics", headers=h).json()
    assert got["mention_rate"]["value"] == 1.0
    assert got["mention_rate"]["n"] == 6
    assert got["mention_rate"]["ci_low"] == pytest.approx(0.61, abs=0.01)
    assert got["citation_rate"]["value"] == 1.0
    assert got["recommendation_rate"]["value"] == 0.0
    assert got["sov"]["value"] == 0.5
    sov_resp = client.get(f"{base}/sov", headers=h).json()
    assert [e["mentions"] for e in sov_resp["entities"]] == [6, 6]
    assert sov_resp["n_failed"] == 0
    assert sov_resp["pipeline_version"] == "1"
    assert "computed_at" in sov_resp

    listed = client.get(
        f"/v1/observations?brand_id={bid}&status=done", headers=h
    ).json()
    assert len(listed) == 6
    oid = listed[0]["id"]
    detail = client.get(f"/v1/observations/{oid}", headers=h).json()
    assert detail["cost_micros"] == 14_915
    assert [x["entity_type"] for x in detail["mentions"]] == [
        "brand",
        "competitor",
    ]
    assert detail["citations"][0]["is_brand_owned"] is True
    assert client.get(f"/v1/observations/{oid}/raw", headers=h).json() == RAW

    filtered = client.get(
        f"{base}/metrics?engine=gemini&prompt_ids={listed[0]['prompt_id']}",
        headers=h,
    ).json()
    assert filtered["mention_rate"]["n"] == 3
