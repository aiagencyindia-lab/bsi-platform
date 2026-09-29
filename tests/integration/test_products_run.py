"""The product_run and import_feed jobs (slice 18)."""

import itertools
import json
from datetime import UTC, datetime, timedelta

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core import products
from bsi_core.crawl import Response
from bsi_core.providers.base import EngineResult, ParsedAnswer
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from tests.integration.test_worker import _job, _load_job

ANSWER = (
    "Popular picks: **Kids Sandals for Boys Summer** on amazon.in, "
    "**Boys Summer Sandals Lightweight** at flipkart.com."
)


class FakeEngine:
    """query returns one ok answer per call; parse returns its text."""

    code = "gemini"

    def __init__(self, results=None):
        self.results = list(results or [])
        self.prompts = []

    def query(self, prompt, country, language):
        self.prompts.append((prompt, country, language))
        if self.results:
            return self.results.pop(0)
        return EngineResult(
            "ok", raw={"text": ANSWER}, model="fake-1", cost_micros=35_000
        )

    def parse(self, raw):
        return ParsedAnswer(raw.get("text", ""), [("u", "amazon.in")])

    def cost(self, raw):
        return 0

    def health(self):
        return True

    def rate_budget(self):
        return 60


def _generator(
    owner=None, fail_on=None, keywords=None, by_index=None, titles=None
):
    """Answers each schema with fixed JSON; records the call kinds and,
    when `owner` is given, how many products had a keyword at call time."""
    calls = []

    def generate(prompt, schema, temperature):
        kind = {
            products.KeywordSet: "keywords",
            products.TitleSet: "titles",
            products.RewriteSet: "rewrite",
        }[schema]
        if owner is not None:
            with owner() as s:
                n = s.scalar(
                    text(
                        "SELECT count(*) FROM product WHERE keyword IS NOT NULL"
                    )
                )
            calls.append((kind, temperature, n))
        else:
            calls.append((kind, temperature))
        if fail_on is not None and len(calls) == fail_on:
            raise RuntimeError("model down")
        indexes = (
            [p["index"] for p in json.loads(prompt.split("Products:\n", 1)[1])]
            if "Products:\n" in prompt
            else []
        )
        if kind == "keywords":
            body = {
                "products": [
                    {
                        "index": i,
                        "keywords": (by_index or {}).get(i)
                        or keywords
                        or ["kids sandals", "walkaroo kids"],
                    }
                    for i in indexes
                ]
            }
        elif kind == "titles":
            body = {
                "titles": titles
                if titles is not None
                else [
                    {
                        "title": "Kids Sandals for Boys Summer",
                        "domain": "amazon.in",
                    },
                    {"title": "Boys Summer Sandals Lightweight", "domain": ""},
                    {"title": "Invented Sandal", "domain": "x"},
                ]
            }
        else:
            body = {
                "products": [
                    {
                        "index": i,
                        "title": "Walkaroo Kids Summer Sandals Sandals",
                        "bullets": ["Light", "Washable", "Soft", "Extra"],
                    }
                    for i in indexes
                ]
            }
        return json.dumps(body), 700, "fake-model"

    generate.calls = calls
    return generate


def _seed(owner, org, bid, n):
    with owner() as s, s.begin():
        for i in range(n):
            s.add(
                m.Product(
                    org_id=org.id,
                    brand_id=bid,
                    external_id=f"W-{i}",
                    title=f"Walkaroo Boys Sandal {i}",
                    source="csv",
                )
            )


def _run(owner, org, bid, generator, engine=None, **params):
    jid = _job(
        owner,
        org,
        bid,
        "product_run",
        "queued",
        params={"locale": {"country": "IN", "language": "en"}, **params},
    )
    worker.process_job(engine or FakeEngine(), generator, None)
    with owner() as s:
        rows = s.scalars(
            select(m.Product).order_by(m.Product.external_id)
        ).all()
        searches = s.scalars(select(m.KeywordSearch)).all()
    return _load_job(owner, jid), rows, searches


def test_keywords_are_written_per_batch(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 21)
    gen = _generator(owner)
    job, rows, _searches = _run(owner, org, bid, gen)
    assert (job.status, job.error) == ("done", None)
    keyword_calls = [c for c in gen.calls if c[0] == "keywords"]
    assert len(keyword_calls) == 6  # 2 batches x 3 samples
    assert [c[1] for c in keyword_calls] == [0.4] * 6
    assert [c[2] for c in keyword_calls] == [0, 0, 0, 20, 20, 20]
    assert all(p.keyword == "kids sandals" for p in rows)
    assert rows[0].keywords == ["kids sandals"]  # brand keyword dropped


def test_one_search_per_distinct_keyword_and_the_rewrite_is_checked(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 3)
    engine = FakeEngine()
    gen = _generator()
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert job.status == "done"
    assert engine.prompts == [
        (products.search_query("kids sandals"), "IN", "en")
    ]
    assert len(searches) == 1
    assert searches[0].keyword == "kids sandals"
    assert searches[0].titles == [
        {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
        {"title": "Boys Summer Sandals Lightweight", "domain": ""},
    ]
    assert searches[0].cost_micros == 35_700 and searches[0].error is None
    p = rows[0]
    # Stems fold plurals: "sandals" matches the product's "sandal", so only
    # "summer" is in both ranking titles and absent from the product.
    assert p.missing_keywords == ["summer"]
    assert p.suggested_title == "Walkaroo Kids Summer Sandals"
    # "Walkaroo Boys Sandal 0" rewritten as "…Kids Summer Sandals" loses
    # "boys", so the suggestion is flagged for review.
    assert (p.rule_check, p.dropped_words) == ("review", ["boys"])
    assert p.suggested_bullets == ["Light", "Washable", "Soft"]
    assert p.job_id == job.id and p.result_at is not None
    assert [c[0] for c in gen.calls] == [
        "keywords",
        "keywords",
        "keywords",
        "titles",
        "rewrite",
    ]
    assert job.cost_micros == 35_000 + 5 * 700


def test_a_fresh_search_is_reused_and_a_stale_one_redone(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query=products.search_query("kids sandals"),
                titles=[{"title": "Cached Summer Sandals", "domain": "c"}],
                searched_at=datetime.now(UTC) - timedelta(days=6),
            )
        )
    engine = FakeEngine()
    _, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert engine.prompts == [] and rows[0].missing_keywords == []
    with owner() as s, s.begin():
        s.execute(
            update(m.KeywordSearch).values(
                searched_at=datetime.now(UTC) - timedelta(days=8)
            )
        )
    _, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert len(engine.prompts) == 1 and len(searches) == 1
    assert searches[0].titles[0]["title"] == "Kids Sandals for Boys Summer"


def test_budget_failure_after_keywords_keeps_them(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    # $0.04: PRODUCT_JOB_MICROS (20,000) fits at claim; one search
    # (45,000) does not.
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=0.04)
        )
    engine = FakeEngine()
    gen = _generator()
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert (job.status, job.error) == ("failed", "budget")
    assert rows[0].keyword == "kids sandals" and rows[0].suggested_title is None
    assert engine.prompts == [] and searches == []
    assert job.cost_micros == 3 * 700


def test_an_error_search_is_not_reused(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query=products.search_query("kids sandals"),
                titles=[],
                error="429 quota",
                searched_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    engine = FakeEngine()
    _, _rows, searches = _run(owner, org, bid, _generator(), engine)
    assert engine.prompts == [
        (products.search_query("kids sandals"), "IN", "en")
    ]
    assert len(searches) == 1 and searches[0].error is None
    assert searches[0].titles == [
        {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
        {"title": "Boys Summer Sandals Lightweight", "domain": ""},
    ]


def test_a_search_under_the_old_query_is_redone(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query="kids sandals buy online",
                titles=[{"title": "Cached Summer Sandals", "domain": "c"}],
                searched_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    engine = FakeEngine()
    _, _rows, searches = _run(owner, org, bid, _generator(), engine)
    query = products.search_query("kids sandals")
    assert engine.prompts == [(query, "IN", "en")]
    assert len(searches) == 1 and searches[0].query == query
    assert searches[0].titles == [
        {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
        {"title": "Boys Summer Sandals Lightweight", "domain": ""},
    ]


def test_store_names_are_not_stored_as_titles(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    answer = "Shop **Kids Classic Sandal** and more at Zappos.com."
    engine = FakeEngine(
        [
            EngineResult(
                "ok", raw={"text": answer}, model="fake-1", cost_micros=35_000
            )
        ]
    )
    gen = _generator(
        titles=[
            {"title": "Zappos.com", "domain": "zappos.com"},
            {"title": "Kids Classic Sandal", "domain": ""},
        ]
    )
    _, _rows, searches = _run(owner, org, bid, gen, engine)
    assert searches[0].titles == [
        {"title": "Kids Classic Sandal", "domain": ""}
    ]


def test_keyword_spend_counts_against_the_search_budget(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    monkeypatch.setattr(products, "SEARCH_MICROS", 30_000)
    # $0.032: PRODUCT_JOB_MICROS (20,000) fits at claim, so the job runs.
    # Keywords spend 3 x 700 = 2,100; 2,100 + 30,000 > 32,000. Without the
    # spend term the check would pass (30,000 <= 32,000).
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=0.032)
        )
    engine = FakeEngine()
    job, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert (job.status, job.error) == ("failed", "budget")
    assert job.cost_micros == 3 * 700
    assert rows[0].keyword == "kids sandals"
    assert engine.prompts == [] and searches == []


def test_a_failed_search_is_stored_and_the_run_goes_on(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    engine = FakeEngine([EngineResult("fatal", error="400 bad", model="f")])
    job, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert job.status == "done"
    assert searches[0].error == "400 bad" and searches[0].titles == []
    assert rows[0].missing_keywords == []
    assert rows[0].suggested_title == "Walkaroo Kids Summer Sandals"


def test_a_model_failure_in_batch_two_keeps_batch_one(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 21)
    # R12: batch 1 is finished (3 keyword calls, titles parse, rewrite)
    # before batch 2 starts, so call 6 is batch 2's first keyword call.
    gen = _generator(fail_on=6)
    job, rows, _searches = _run(owner, org, bid, gen)
    assert job.status == "failed" and "model down" in (job.error or "")
    # batch 1's keywords, one search, one titles parse, one rewrite
    assert job.cost_micros == 3 * 700 + 35_000 + 700 + 700
    done = [p for p in rows if p.keyword and p.suggested_title]
    assert len(done) == 20
    rest = [p for p in rows if p not in done]
    assert len(rest) == 1
    assert rest[0].keyword is None and rest[0].suggested_title is None


def _stops_after_one_batch():
    """0 on the first read, then past PRODUCT_JOB_SECONDS."""
    reads = itertools.chain([0.0], itertools.repeat(481.0))
    return lambda: next(reads)


def _direct(owner, org, bid, generator, clock=None):
    """run_products called directly, for its summary and a fake clock."""
    jid = _job(owner, org, bid, "product_run", "running")
    kw = {"clock": clock} if clock else {}
    summary = products.run_products(
        org.id,
        jid,
        bid,
        {"locale": {"country": "IN", "language": "en"}},
        generator,
        FakeEngine(),
        **kw,
    )
    with owner() as s:
        rows = s.scalars(select(m.Product)).all()
    return jid, summary, rows


def test_a_run_stops_at_the_time_budget(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 41)
    _jid, summary, rows = _direct(
        owner, org, bid, _generator(), _stops_after_one_batch()
    )
    assert "out of time after 20 of 41 products" in summary
    assert sum(1 for p in rows if p.suggested_title) == 20
    assert sum(1 for p in rows if p.suggested_title is None) == 21


def test_a_second_run_continues_with_the_oldest_results(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 25)
    _jid, _summary, rows = _direct(
        owner, org, bid, _generator(), _stops_after_one_batch()
    )
    unrun = sorted(p.title for p in rows if p.result_at is None)
    assert len(unrun) == 5
    inner = _generator()
    rewritten: list[str] = []

    def generator(prompt, schema, temperature):
        if schema is products.RewriteSet:
            body = json.loads(prompt.split("Products:\n", 1)[1])
            rewritten.extend(p["title"] for p in body)
        return inner(prompt, schema, temperature)

    jid2, _summary, rows = _direct(owner, org, bid, generator)
    assert rewritten[:5] == unrun
    assert all(p.suggested_title for p in rows)
    assert {p.job_id for p in rows if p.title in unrun} == {jid2}


def test_a_product_whose_keyword_drops_loses_its_old_suggestion(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        s.add(
            m.Product(
                org_id=org.id,
                brand_id=bid,
                external_id="W-0",
                title="Walkaroo Boys Sandal",
                source="csv",
                keyword="kids sandals",
                missing_keywords=["x"],
                suggested_title="Old",
                rule_check="pass",
                dropped_words=["x"],
            )
        )
    gen = _generator(keywords=["walkaroo sandals"])
    job, rows, _searches = _run(owner, org, bid, gen)
    assert job.status == "done"
    p = rows[0]
    assert (p.keyword, p.suggested_title, p.rule_check) == (None, None, None)
    assert p.missing_keywords is None and p.job_id == job.id
    assert p.dropped_words is None


def test_no_transaction_is_open_during_model_calls(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
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

    inner = _generator()

    def generator(prompt, schema, temperature):
        seen.append(idle())
        return inner(prompt, schema, temperature)

    class Engine(FakeEngine):
        def query(self, prompt, country, language):
            seen.append(idle())
            return super().query(prompt, country, language)

    _run(owner, org, bid, generator, Engine())
    assert len(seen) == 6 and set(seen) == {0}


RSS = b"""<rss xmlns:g="http://base.google.com/ns/1.0"><channel>
<item><g:id>F-1</g:id><title>Feed Sandal</title><link>https://x.in/1</link></item>
</channel></rss>"""


def _feed_job(owner, org, bid, fetch):
    jid = _job(
        owner,
        org,
        bid,
        "import_feed",
        "queued",
        params={"url": "https://x.in/f"},
    )
    worker.process_job(FakeEngine(), _generator(), None, fetch=fetch)
    return _load_job(owner, jid)


def test_import_feed_fetches_parses_and_upserts(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        return Response(200, RSS.decode("latin-1"))

    job = _feed_job(owner, org, bid, fetch)
    assert (job.status, job.error) == ("done", None)
    assert calls == [("https://x.in/f", worker.BROWSER_UA)]
    with owner() as s:
        p = s.scalars(select(m.Product)).one()
    assert (p.external_id, p.title, p.source) == ("F-1", "Feed Sandal", "feed")


def test_import_feed_failures(owner, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    job = _feed_job(owner, org, bid, lambda u, ua: Response(0, error="refused"))
    assert job.status == "failed" and "fetch 0: refused" in (job.error or "")
    monkeypatch.setattr(products, "MAX_PRODUCTS", 0)
    job = _feed_job(owner, org, bid, lambda u, ua: Response(200, RSS.decode()))
    assert (job.status, job.error) == ("failed", "cap")


def test_the_database_accepts_review_and_rejects_an_unknown_status(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.execute(
            update(m.Product).values(
                rule_check="review", dropped_words=["casual"]
            )
        )
    with owner() as s:
        p = s.scalars(select(m.Product)).one()
        assert (p.rule_check, p.dropped_words) == ("review", ["casual"])
    with pytest.raises(IntegrityError):
        with owner() as s, s.begin():
            s.execute(update(m.Product).values(rule_check="maybe"))


def test_plural_variants_share_one_search(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        for suffix in ("A", "B"):
            s.add(
                m.Product(
                    org_id=org.id,
                    brand_id=bid,
                    external_id=f"S-{suffix}",
                    title=f"Walkaroo Men Sandal {suffix}",
                    source="csv",
                )
            )
    engine = FakeEngine()
    gen = _generator(by_index={0: ["mens sandal"], 1: ["men sandals"]})
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert job.status == "done"
    assert engine.prompts == [
        (products.search_query("mens sandal"), "IN", "en")
    ]
    assert len(searches) == 1
    assert [p.keyword for p in rows] == ["mens sandal", "mens sandal"]
