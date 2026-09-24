"""The optimize_url job: what it reads, fetches, embeds and stores."""

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.crawl import Response
from bsi_core.db import tenant_session
from bsi_core.pages import COS_COVERED, WEIGHTS_VERSION, cosine, parse
from sqlalchemy import select, text, update

from tests.integration.test_gaps import scene  # noqa: F401
from tests.integration.test_worker import FakeAdapter, _job, _load_job
from tests.unit.test_pages import bow

KEY = "cluster:comparison:running shoes"
URL = "https://nike.com/run"
PAGE = """<html><head><title>Nike vs Adidas running shoes</title></head>
<body><h1>Nike vs Adidas: running shoes compared</h1>
<h2>Which is the best running shoe brand?</h2><p>Nike, for most runners.</p>
<h2>Nike vs Adidas</h2><p>Nike is lighter; Adidas is softer.</p>
<table><tr><th>Shoe</th></tr><tr><td>Pegasus</td></tr></table>
<a href="https://forbes.com/x">Forbes</a></body></html>"""


def _embedder(texts):
    return [bow(t) for t in texts], 55


def _fetch(pages=None):
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        return (pages or {}).get(url, Response(200, PAGE))

    fetch.calls = calls
    return fetch


def _embed_prompts(owner, ids):
    with owner() as s, s.begin():
        for pid, txt in [
            (ids.vs, "nike vs adidas"),
            (ids.best, "best running shoe brand"),
        ]:
            s.execute(
                update(m.Prompt)
                .where(m.Prompt.id == pid)
                .values(embedding=bow(txt))
            )


def _run(owner, scene, params, fetch=None, embedder=_embedder):  # noqa: F811
    jid = _job(
        owner, scene.org, scene.brand, "optimize_url", "queued", params=params
    )
    worker.process_job(FakeAdapter(), None, embedder, fetch=fetch or _fetch())
    with owner() as s:
        rows = s.scalars(
            select(m.PageAudit).order_by(m.PageAudit.created_at)
        ).all()
        return _load_job(owner, jid), rows


def test_job_stores_a_scored_row_and_refreshes_recs(owner, scene):  # noqa: F811
    _embed_prompts(owner, scene)
    fetch = _fetch()
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": KEY}, fetch)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 55)
    assert fetch.calls == [(URL, worker.BROWSER_UA)]
    [a] = rows
    assert (a.url, a.cluster_key, a.status, a.error, a.fetches) == (
        URL,
        KEY,
        200,
        None,
        1,
    )
    assert a.weights_version == WEIGHTS_VERSION and 0 <= a.score <= 100
    assert [c["code"] for c in a.components][:2] == [
        "topic_coverage",
        "evidence",
    ]
    topic = next(c for c in a.components if c["code"] == "topic_coverage")
    sections = [bow(x.embed_text()) for x in parse(PAGE).sections]
    covered = sum(
        max(cosine(bow(q), sv) for sv in sections) >= COS_COVERED
        for q in ("nike vs adidas", "best running shoe brand")
    )
    assert topic["value"] > 0
    assert topic["observed"] == f"{covered} of 2 prompts covered"
    assert set(a.evidence["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(a.evidence["observation_ids"]) == 6
    assert a.evidence["cluster"] == {
        "intent": "comparison",
        "topic": "running shoes",
    }
    # forbes.com is linked; shop.adidas.co.in (rival) is cited but not linked
    ev = a.suggestions["evidence_to_add"]
    assert [s["urls"] for s in ev] == [["https://shop.adidas.co.in/y"]]
    with owner() as s:
        recs = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "optimize_page"
            )
        ).all()
    # The fixture page scores 47: under 70, so the rule fires.
    assert a.score < 70
    assert [r.subject_key for r in recs] == [f"page:{KEY}:{URL}"]


def test_accepting_an_optimize_page_rec_tasks_the_cluster(
    client,
    owner,
    scene,  # noqa: F811
):
    _embed_prompts(owner, scene)
    _, [a] = _run(owner, scene, {"url": URL, "cluster_key": KEY})
    assert a.score < 70  # the rule fires
    with owner() as s:
        rid = s.scalars(
            select(m.Recommendation.id).where(
                m.Recommendation.type == "optimize_page"
            )
        ).one()
    t = client.post(
        f"/v1/brands/{scene.brand}/recommendations/{rid}/accept",
        headers=scene.org.headers,
    )
    assert t.is_success, t.text
    task = t.json()
    assert set(task["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert task["measures_impact"] is True


def test_unknown_cluster_fails_the_job_and_stores_nothing(owner, scene):  # noqa: F811
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": "cluster:x:y"})
    assert job.status == "failed" and "unknown cluster" in job.error
    assert rows == []


def test_bad_url_fails_the_job(owner, scene):  # noqa: F811
    job, rows = _run(owner, scene, {"url": "ftp://x", "cluster_key": KEY})
    assert job.status == "failed" and rows == []


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (Response(0, "", "ConnectError('down')"), "ConnectError"),
        (Response(404, "<h1>x</h1>"), "HTTP 404"),
        (
            Response(200, "<html><body><p>no headings</p></body></html>"),
            "no headings",
        ),
    ],
)
def test_a_failed_fetch_is_a_stored_finding(owner, scene, response, error):  # noqa: F811
    _embed_prompts(owner, scene)
    calls = []
    job, rows = _run(
        owner,
        scene,
        {"url": URL, "cluster_key": KEY},
        _fetch({URL: response}),
        lambda texts: (calls.append(texts), ([], 0))[1],
    )
    assert job.status == "done"
    [a] = rows
    assert a.score is None and error in a.error
    assert a.status == response.status
    assert calls == []  # nothing embedded


def test_budget_gate_refuses_when_the_estimate_does_not_fit(owner, scene):  # noqa: F811
    assert worker.JOB_ESTIMATES["optimize_url"] == worker.PAGE_JOB_MICROS
    assert worker.PAGE_JOB_MICROS == 5_000
    # A $0 cap: the 5,000-micro estimate cannot fit.
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == scene.org.id)
            .values(daily_budget_usd=0)
        )
    fetch = _fetch()
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": KEY}, fetch)
    assert (job.status, job.error) == ("failed", "budget") and rows == []
    assert fetch.calls == []


def test_no_transaction_is_open_while_fetching_or_embedding(owner, scene):  # noqa: F811
    _embed_prompts(owner, scene)
    seen = []

    def idle():
        with owner() as s:
            return s.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'idle in transaction' "
                    "AND pid <> pg_backend_pid()"
                )
            )

    def fetch(url, ua):
        seen.append(idle())
        return Response(200, PAGE)

    def embedder(texts):
        seen.append(idle())
        return [bow(t) for t in texts], 1

    _run(owner, scene, {"url": URL, "cluster_key": KEY}, fetch, embedder)
    assert len(seen) == 2 and set(seen) == {0}


def test_cited_urls_are_top_non_owned_by_answers(owner, scene):  # noqa: F811
    with tenant_session(scene.org.id) as s:
        rows = worker.cited_urls(
            s,
            scene.brand,
            [scene.vs, scene.best],
            ["nike.com"],
            ["adidas.co.in"],
        )
    # scene: forbes.com/x in 4 absent answers, shop.adidas.co.in/y in 2,
    # nike.com/run is owned -> excluded.
    assert [(r["url"], r["owner"], r["answers"]) for r in rows] == [
        ("https://forbes.com/x", "third_party", 4),
        ("https://shop.adidas.co.in/y", "rival", 2),
    ]
    assert len(rows[0]["observation_ids"]) == 4
