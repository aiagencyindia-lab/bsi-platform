import threading
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.recommend import _rival_pages, generate, refresh
from sqlalchemy import delete, func, select, update

from tests.integration.test_api_recommendations import _wait_until_blocked
from tests.integration.test_gaps import scene  # noqa: F401
from tests.integration.test_rival_crawl import _page


def _mention(org, oid, etype, eid):
    return m.Mention(
        org_id=org.id,
        observation_id=oid,
        entity_type=etype,
        entity_id=eid,
        position=1,
        rec_status="mentioned",
        sentiment="neutral",
    )


@pytest.fixture
def world(owner, make_org, make_brand, make_observation):
    """Five active prompts, each built so exactly one rule fires or not.

    dominated  brand 0/4, Adidas 4/4; forbes.com, adidas.co.in (a
               declared Adidas domain) and four.com cited in all four
               -> create_content; separated at n=4, so no sample_more
    present    brand 3/4, blog.com cited in all four -> nothing: absent
               only once; blog.com cited in one brand-absent answer;
               needs 16 samples, a shortfall of 12, just past the 10.
               Its one brand-absent answer also cites forbes.com and
               adidas.co.in, bringing each to five - the threshold:
               forbes.com -> pursue_citation_source; adidas.co.in -> nothing,
               since a rival's own domain must never be recommended;
               four.com stays at four, one short -> nothing
    mismatch   brand 0/2, reason category_mismatch, nike.com (owned) and
               rare.com (two answers) cited -> nothing
    close      brand 3/3, Adidas 0/3 -> sample_more (needs 4)
    far        brand 2/3, Adidas 1/3 -> nothing: needs 31
    Puma is suggested with evidence 2 -> add_competitor; Reebok with
    evidence 1 -> nothing.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        adidas = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name="Adidas",
            domains=["adidas.co.in"],
        )
        puma = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name="Puma",
            status="suggested",
            evidence=2,
        )
        reebok = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name="Reebok",
            status="suggested",
            evidence=1,
        )
        s.add_all([adidas, puma, reebok])
        s.flush()
        ids = SimpleNamespace(
            org=org, brand=bid, adidas=adidas.id, puma=puma.id
        )

    def prompt(text, rows):
        """rows: (brand present, Adidas present, absence reason, cites)
        where cites is a list of (domain, brand-owned)."""
        first = make_observation(org, bid, status="done", text=text)
        with owner() as s:
            pid = s.get(m.Observation, first).prompt_id
        obs = [first] + [
            make_observation(
                org, bid, status="done", prompt_id=pid, sample_index=i
            )
            for i in range(1, len(rows))
        ]
        with owner() as s, s.begin():
            for oid, (brand, rival, reason, cites) in zip(
                obs, rows, strict=True
            ):
                s.add(
                    m.Extraction(
                        org_id=org.id,
                        observation_id=oid,
                        pipeline_version="2",
                        model_used="test",
                        brand_mentioned=brand,
                        absence_reason=reason,
                    )
                )
                if brand:
                    s.add(_mention(org, oid, "brand", bid))
                if rival:
                    s.add(_mention(org, oid, "competitor", ids.adidas))
                for pos, (domain, owned) in enumerate(cites, 1):
                    s.add(
                        m.Citation(
                            org_id=org.id,
                            observation_id=oid,
                            url=f"https://{domain}/",
                            domain=domain,
                            position=pos,
                            is_brand_owned=owned,
                        )
                    )
        return pid

    lost = (
        False,
        True,
        "competitor_dominance",
        [
            ("forbes.com", False),
            ("adidas.co.in", False),
            ("four.com", False),
        ],
    )
    ids.dominated = prompt("dominated", [lost] * 4)
    blog = [("blog.com", False)]
    ids.present = prompt(
        "present",
        [(True, False, None, blog)] * 3
        + [
            (
                False,
                True,
                "competitor_dominance",
                [*blog, ("forbes.com", False), ("adidas.co.in", False)],
            )
        ],
    )
    ids.mismatch = prompt(
        "mismatch",
        [
            (
                False,
                False,
                "category_mismatch",
                [("nike.com", True), ("rare.com", False)],
            )
        ]
        * 2,
    )
    ids.close = prompt("close", [(True, False, None, [])] * 3)
    ids.far = prompt(
        "far",
        [
            (True, True, None, []),
            (True, False, None, []),
            (False, False, "competitor_dominance", []),
        ],
    )
    return ids


def found(w):
    with tenant_session(w.org.id) as s:
        return {(c.type, c.subject_key): c for c in generate(s, w.brand)}


def test_each_rule_fires_exactly_where_it_should(world):
    # One assertion covers every negative case in the fixture docstring.
    # No labelled clusters or rival pages here: respond_to_rival_content
    # stays silent.
    assert set(found(world)) == {
        ("pursue_citation_source", "forbes.com"),
        ("create_content", str(world.dominated)),
        ("add_competitor", str(world.puma)),
        ("sample_more", str(world.close)),
    }


def test_citation_evidence_and_weights(world):
    c = found(world)[("pursue_citation_source", "forbes.com")]
    assert len(c.evidence["observation_ids"]) == 5
    assert c.evidence["prompt_ids"] == sorted(
        [str(world.dominated), str(world.present)]
    )
    assert c.evidence["rivals"] == ["Adidas"]
    # 5 brand-absent answers of 16 done ones on active prompts; all five
    # name Adidas. 0.3125 x 1.0 x 0.3 = 0.09375 -> 0.0938.
    assert (c.reach, c.pressure, c.feasibility, c.priority) == (
        0.3125,
        1.0,
        0.3,
        0.0938,
    )


def test_citation_rule_skips_a_rivals_declared_domain(world):
    # adidas.co.in is cited exactly as often as forbes.com (five
    # brand-absent answers, at the threshold) but is declared on the active
    # Adidas competitor, so it must never be recommended - while
    # forbes.com, an unrelated domain with the same count, still is.
    all_ = found(world)
    assert ("pursue_citation_source", "adidas.co.in") not in all_
    assert ("pursue_citation_source", "forbes.com") in all_


def test_content_names_the_reason_and_the_rivals(world):
    c = found(world)[("create_content", str(world.dominated))]
    assert c.evidence["reason"] == "competitor_dominance"
    assert (c.evidence["absent"], c.evidence["n"]) == (4, 4)
    assert "Adidas" in c.body
    assert (c.reach, c.priority) == (0.25, 0.1)  # 4/16 x 1.0 x 0.4


def test_competitor_and_sampling_weights(world):
    all_ = found(world)
    puma = all_[("add_competitor", str(world.puma))]
    # 2 of the 3 suggestion answers named Puma; pressure is not measured.
    assert (round(puma.reach, 4), puma.pressure, puma.priority) == (
        0.6667,
        1.0,
        0.6,
    )
    sample = all_[("sample_more", str(world.close))]
    assert (sample.evidence["n"], sample.evidence["needs_samples"]) == (3, 4)
    # n=3 of 16 answers x |spread| 1.0 x 1.0
    assert (sample.reach, sample.pressure, sample.priority) == (
        0.1875,
        1.0,
        0.1875,
    )


def test_generate_ranks_by_priority(world):
    with tenant_session(world.org.id) as s:
        ranked = [c.type for c in generate(s, world.brand)]
    assert ranked == [
        "add_competitor",
        "sample_more",
        "create_content",
        "pursue_citation_source",
    ]


def test_refresh_updates_in_place_and_keeps_decisions(world):
    org = world.org
    with tenant_session(org.id) as s:
        assert refresh(s, org.id, world.brand) == 4
    with tenant_session(org.id) as s:
        before = {
            r.subject_key: r.id for r in s.scalars(select(m.Recommendation))
        }
        comp = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "add_competitor"
            )
        ).one()
        comp.status, comp.dismiss_reason = "dismissed", "not a rival"
    with tenant_session(org.id) as s:
        refresh(s, org.id, world.brand)
    with tenant_session(org.id) as s:
        rows = s.scalars(select(m.Recommendation)).all()
    assert {r.subject_key: r.id for r in rows} == before
    assert {r.type: r.status for r in rows}["add_competitor"] == "dismissed"


def test_refresh_drops_open_rows_the_evidence_no_longer_supports(owner, world):
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    with owner() as s, s.begin():
        s.get(m.Competitor, world.puma).status = "active"
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        types = {r.type for r in s.scalars(select(m.Recommendation))}
    assert "add_competitor" not in types


def test_refresh_with_no_evidence_drops_every_open_row(owner, world):
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.type == "sample_more")
            .values(status="dismissed", dismiss_reason="later")
        )
    with owner() as s, s.begin():
        s.get(m.Competitor, world.puma).status = "active"
        s.execute(update(m.Prompt).values(status="paused"))
    with tenant_session(world.org.id) as s:
        assert refresh(s, world.org.id, world.brand) == 0
        left = [(r.type, r.status) for r in s.scalars(select(m.Recommendation))]
    assert left == [("sample_more", "dismissed")]


def test_a_dismiss_racing_refresh_survives(owner, world):
    """refresh finds a stale open row while a dismiss holds its lock. Once
    the dismiss commits, the delete must re-check the status and leave the
    decision alone."""
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    with owner() as s, s.begin():
        s.get(m.Competitor, world.puma).status = "active"  # now stale
    holder = owner()
    holder.begin()
    rec = holder.execute(
        select(m.Recommendation)
        .where(m.Recommendation.type == "add_competitor")
        .with_for_update()
    ).scalar_one()
    rec.status, rec.dismiss_reason = "dismissed", "not a rival"
    holder.flush()

    def run() -> None:
        with tenant_session(world.org.id) as s:
            refresh(s, world.org.id, world.brand)

    t = threading.Thread(target=run)
    t.start()
    try:
        assert _wait_until_blocked(holder), "refresh never blocked"
        assert t.is_alive()
        holder.commit()
        t.join(timeout=5)
        assert not t.is_alive()
    finally:
        holder.close()
    with owner() as s:
        got = s.get(m.Recommendation, rec.id)
        assert got is not None, "the dismissed row was deleted"
        assert (got.status, got.dismiss_reason) == ("dismissed", "not a rival")


def _site_audit(owner, w, checks):
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=w.org.id, brand_id=w.brand, host="nike.com"))
        s.add(
            m.SiteAudit(
                org_id=w.org.id,
                brand_id=w.brand,
                domain="nike.com",
                checks=checks,
            )
        )


def _check(code, ok, severity):
    return {
        "code": code,
        "ok": ok,
        "severity": severity,
        "observed": "o",
        "expected": "e",
        "url": "https://nike.com/",
    }


def test_each_failing_check_is_one_crawl_recommendation(owner, world):
    _site_audit(
        owner,
        world,
        [
            _check("bot_blocked:GPTBot", False, "high"),
            _check("sitemap_missing", False, "medium"),
            _check("llms_missing", False, "low"),
            _check("title_missing", True, "low"),
        ],
    )
    recs = {k: c for k, c in found(world).items() if k[0] == "fix_crawlability"}
    assert set(recs) == {
        ("fix_crawlability", "nike.com:bot_blocked:GPTBot"),
        ("fix_crawlability", "nike.com:sitemap_missing"),
        ("fix_crawlability", "nike.com:llms_missing"),
    }
    gpt = recs[("fix_crawlability", "nike.com:bot_blocked:GPTBot")]
    # Nothing measures a site fix against answers: reach is 1.0 and
    # pressure is the severity weight. 1.0 x 1.0 x 0.8.
    assert (gpt.reach, gpt.pressure, gpt.feasibility, gpt.priority) == (
        1.0,
        1.0,
        0.8,
        0.8,
    )
    assert (
        recs[("fix_crawlability", "nike.com:sitemap_missing")].priority == 0.4
    )
    assert recs[("fix_crawlability", "nike.com:llms_missing")].priority == 0.16
    assert gpt.evidence["domain"] == "nike.com"
    assert gpt.evidence["code"] == "bot_blocked:GPTBot"
    assert "audit_id" in gpt.evidence


def test_only_the_latest_audit_per_domain_counts(owner, world):
    _site_audit(owner, world, [_check("sitemap_missing", False, "medium")])
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 1)
            )
        )
        s.add(
            m.SiteAudit(
                org_id=world.org.id,
                brand_id=world.brand,
                domain="nike.com",
                checks=[_check("sitemap_missing", True, "medium")],
            )
        )
    assert not [k for k in found(world) if k[0] == "fix_crawlability"]


def test_a_fixed_check_disappears_on_refresh(owner, world):
    _site_audit(owner, world, [_check("llms_missing", False, "low")])
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                checks=[_check("llms_missing", True, "low")]
            )
        )
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        left = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "fix_crawlability"
            )
        ).all()
    assert left == []


def test_a_domain_audit_with_no_declared_domain_yields_nothing(owner, world):
    """Controller ruling: _crawl only considers audits of domains still
    declared for the brand. A domain removed after its audit ran must not
    keep producing recommendations."""
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=world.org.id,
                brand_id=world.brand,
                domain="nike.com",
                checks=[_check("sitemap_missing", False, "medium")],
            )
        )
    assert not [k for k in found(world) if k[0] == "fix_crawlability"]


def test_an_unrecognized_check_is_skipped_not_fatal(owner, world):
    """An unknown code or severity (an older row surviving a future code
    rename, or edited data) must not raise out of generate(): it is
    skipped, and every other recommendation type still comes back."""
    _site_audit(
        owner,
        world,
        [
            _check("bogus_future_check", False, "high"),
            _check("llms_missing", False, "low"),
        ],
    )
    recs = found(world)
    assert ("fix_crawlability", "nike.com:bogus_future_check") not in recs
    assert ("fix_crawlability", "nike.com:llms_missing") in recs
    # generate() still returns the brand's other types.
    assert ("add_competitor", str(world.puma)) in recs


def test_each_failing_entity_check_is_one_entity_recommendation(owner, world):
    _site_audit(
        owner,
        world,
        [
            _check("org_name_mismatch", False, "high"),
            _check("social_links_conflict", False, "medium"),
            _check("wikidata_missing", False, "low"),
            _check("about_missing", True, "low"),
            _check("llms_missing", False, "low"),
        ],
    )
    recs = found(world)
    ent = {k: c for k, c in recs.items() if k[0] == "fix_entity"}
    keys = [
        ("fix_entity", "nike.com:org_name_mismatch"),
        ("fix_entity", "nike.com:social_links_conflict"),
        ("fix_entity", "wikidata:wikidata_missing"),
    ]
    assert set(ent) == set(keys)
    # Judged, not measured: reach 1.0 x severity weight x 0.7.
    assert [ent[k].priority for k in keys] == [
        0.7,
        0.35,
        0.14,
    ]
    name = ent[("fix_entity", "nike.com:org_name_mismatch")]
    assert (name.reach, name.pressure, name.feasibility) == (1.0, 1.0, 0.7)
    assert name.evidence["code"] == "org_name_mismatch"
    assert name.evidence["domain"] == "nike.com"
    # Crawl checks in the same row still route to fix_crawlability.
    assert ("fix_crawlability", "nike.com:llms_missing") in recs
    assert ("fix_entity", "nike.com:llms_missing") not in recs


def _audit(owner, w, host, checks):
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=w.org.id, brand_id=w.brand, host=host))
        s.add(
            m.SiteAudit(
                org_id=w.org.id, brand_id=w.brand, domain=host, checks=checks
            )
        )


def _wd(code, ok, severity="low", qid="Q42"):
    return {
        "code": code,
        "ok": ok,
        "severity": severity,
        "observed": qid,
        "expected": "e",
        "url": f"https://www.wikidata.org/wiki/{qid}",
    }


def _entity(w):
    return {k[1]: c for k, c in found(w).items() if k[0] == "fix_entity"}


def test_wikidata_missing_is_one_rec_per_brand(owner, world):
    _audit(owner, world, "nike.com", [_wd("wikidata_missing", False)])
    _audit(owner, world, "nike.in", [_wd("wikidata_missing", False)])
    ent = _entity(world)
    assert set(ent) == {"wikidata:wikidata_missing"}
    ev = ent["wikidata:wikidata_missing"].evidence
    assert ev["domains"] == ["nike.com", "nike.in"]
    assert ev["domain"] == "nike.com"
    assert "audit_id" in ev


def test_a_matched_item_on_any_domain_suppresses_wikidata_missing(owner, world):
    _audit(owner, world, "nike.com", [_wd("wikidata_missing", True)])
    _audit(owner, world, "nike.in", [_wd("wikidata_missing", False)])
    assert _entity(world) == {}


def test_a_domain_without_wikidata_rows_neither_fires_nor_suppresses(
    owner, world
):
    _audit(owner, world, "nike.com", [_wd("wikidata_missing", False)])
    _audit(owner, world, "nike.in", [_check("llms_missing", False, "low")])
    ent = _entity(world)
    assert set(ent) == {"wikidata:wikidata_missing"}
    assert ent["wikidata:wikidata_missing"].evidence["domains"] == ["nike.com"]


def test_item_checks_are_one_rec_per_item(owner, world):
    for host in ("nike.com", "nike.in"):
        _audit(
            owner,
            world,
            host,
            [
                _wd("wikidata_name_mismatch", False, "medium"),
                _wd("wikidata_logo_missing", False),
            ],
        )
    ent = _entity(world)
    assert set(ent) == {
        "wikidata:Q42:wikidata_name_mismatch",
        "wikidata:Q42:wikidata_logo_missing",
    }
    for rec in ent.values():
        assert rec.evidence["domains"] == ["nike.com", "nike.in"]
        assert rec.evidence["domain"] == "nike.com"


def test_different_items_are_separate_recs(owner, world):
    _audit(owner, world, "nike.com", [_wd("wikidata_name_mismatch", False)])
    _audit(
        owner,
        world,
        "nike.in",
        [_wd("wikidata_name_mismatch", False, qid="Q7")],
    )
    ent = _entity(world)
    assert set(ent) == {
        "wikidata:Q42:wikidata_name_mismatch",
        "wikidata:Q7:wikidata_name_mismatch",
    }
    assert ent["wikidata:Q7:wikidata_name_mismatch"].evidence["domains"] == [
        "nike.in"
    ]


def test_social_links_conflict_stays_per_domain(owner, world):
    for host in ("nike.com", "nike.in"):
        _audit(owner, world, host, [_wd("social_links_conflict", False)])
    assert set(_entity(world)) == {
        "nike.com:social_links_conflict",
        "nike.in:social_links_conflict",
    }


def test_an_item_check_without_a_wiki_url_keeps_the_domain_key(owner, world):
    _audit(
        owner,
        world,
        "nike.com",
        [_check("wikidata_name_mismatch", False, "medium")],
    )
    assert set(_entity(world)) == {"nike.com:wikidata_name_mismatch"}


def test_a_repeated_wikidata_row_lists_its_domain_once(owner, world):
    _audit(
        owner,
        world,
        "nike.com",
        [_wd("wikidata_missing", False), _wd("wikidata_missing", False)],
    )
    ev = _entity(world)["wikidata:wikidata_missing"].evidence
    assert ev["domains"] == ["nike.com"]


def _page_audit(
    owner,
    org,
    bid,
    url,
    score,
    key="cluster:comparison:running shoes",
    obs=3,
    prompts=2,
):
    """A stored page_audit row; score None is a failed fetch."""
    with owner() as s, s.begin():
        a = m.PageAudit(
            org_id=org.id,
            brand_id=bid,
            url=url,
            cluster_key=key,
            status=200 if score is not None else 0,
            error=None if score is not None else "ConnectError",
            weights_version="v1",
            score=score,
            components=[],
            suggestions={
                "add": [],
                "remove": [],
                "rewrite": [],
                "evidence_to_add": [],
            },
            evidence={
                "prompt_ids": [f"p{i}" for i in range(prompts)],
                "observation_ids": [f"o{i}" for i in range(obs)],
                "cluster": {"intent": "comparison", "topic": "running shoes"},
            },
            fetches=1,
        )
        s.add(a)
        s.flush()
        return a.id


def _pages_found(world):
    with tenant_session(world.org.id) as s:
        return {
            c.subject_key: c
            for c in generate(s, world.brand)
            if c.type == "optimize_page"
        }


RUN_KEY = "page:cluster:comparison:running shoes:https://nike.com/run"


def test_a_low_page_score_is_an_optimize_page_candidate(owner, world):
    aid = _page_audit(owner, world.org, world.brand, "https://nike.com/run", 62)
    found = _pages_found(world)
    assert set(found) == {RUN_KEY}
    c = found[RUN_KEY]
    # world: 4 + 4 + 2 + 3 + 3 = 16 done answers on active prompts.
    assert (c.reach, c.pressure, c.feasibility) == (
        pytest.approx(3 / 16),
        pytest.approx(0.38),
        0.6,
    )
    assert c.priority == round(3 / 16 * 0.38 * 0.6, 4)
    assert c.title == "Improve nike.com/run for running shoes"
    assert "Metric to watch:" in c.body
    assert c.evidence["page_audit_id"] == str(aid)
    assert c.evidence["prompt_ids"] == ["p0", "p1"]
    assert c.evidence["score"] == 62
    assert c.evidence["url"] == "https://nike.com/run"


def test_a_page_at_the_threshold_or_a_failed_fetch_is_not_raised(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/a", 70)
    _page_audit(owner, world.org, world.brand, "https://nike.com/b", None)
    assert _pages_found(world) == {}


def test_only_the_latest_audit_per_url_counts(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 40)
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 80)
    assert _pages_found(world) == {}
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 50)
    assert list(_pages_found(world)) == [RUN_KEY]


def test_rescoring_above_the_threshold_drops_the_open_rec(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 40)
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 90)
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        left = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "optimize_page"
            )
        ).all()
    assert left == []


def test_pages_rule_is_one_statement(owner, world):
    from bsi_core.recommend import _pages
    from sqlalchemy import event

    for i in range(3):
        _page_audit(owner, world.org, world.brand, f"https://nike.com/{i}", 30)
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(world.org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            assert len(_pages(s, world.brand, "Nike", 16)) == 3
        finally:
            event.remove(bind, "before_cursor_execute", count)
    assert len(seen) == 1


KEY = "rival:cluster:comparison:running shoes"


def _rival_found(scene):  # noqa: F811
    with tenant_session(scene.org.id) as s:
        return {
            c.subject_key: c
            for c in generate(s, scene.brand)
            if c.type == "respond_to_rival_content"
        }


def test_rival_rule_fires_on_new_matching_pages_where_brand_is_behind(
    owner,
    scene,  # noqa: F811
):
    org, bid, A, B = scene.org, scene.brand, scene.adidas, scene.bata
    ad = "https://adidas.co.in"
    # The gap cluster (comparison, running shoes) is behind Adidas.
    _page(owner, org, bid, A, f"{ad}/running-shoes/new", 2)
    _page(owner, org, bid, A, f"{ad}/running-shoes/old", 2, baseline=True)
    _page(owner, org, bid, A, f"{ad}/running-shoes/stale", 20)
    _page(owner, org, bid, A, f"{ad}/socks", 2)
    _page(
        owner,
        org,
        bid,
        B,
        "https://bata.com/running-shoes",
        2,
        domain="bata.com",
    )
    # The (recommendation, kids) cluster has the brand ahead: 3/4 vs 2/4.
    _page(owner, org, bid, A, f"{ad}/kids/shoes", 2)
    found = _rival_found(scene)
    assert set(found) == {KEY}
    c = found[KEY]
    ev = c.evidence
    assert [p["url"] for p in ev["pages"]] == [f"{ad}/running-shoes/new"]
    assert ev["pages"][0]["name"] == "Adidas"
    assert ev["pages"][0]["competitor_id"] == str(A)
    assert ev["pages_total"] == 1
    assert ev["cluster"] == {"intent": "comparison", "topic": "running shoes"}
    assert ev["cluster_key"] == "cluster:comparison:running shoes"
    assert ev["gap"] is True and ev["n"] == 8 and ev["spread"] < 0
    assert set(ev["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(ev["observation_ids"]) == 6
    assert (c.reach, c.pressure, c.feasibility) == (8 / 19, 0.2, 0.4)
    assert c.title == "Adidas published 1 new running shoes page"
    assert "This cluster is a content gap for Nike." in c.body


def test_rival_rule_behind_but_not_a_gap_uses_the_standing_wording(
    owner,
    scene,  # noqa: F811
):
    A = scene.adidas
    # Brand present 2/4 (no absence reasons -> not a gap), Adidas 3/4.
    scene.add(
        "trail running shoes",
        "commercial",
        "trail shoes",
        [
            (True, [A], None, []),
            (True, [A], None, []),
            (False, [A], None, []),
            (False, [], None, []),
        ],
    )
    _page(
        owner, scene.org, scene.brand, A, "https://adidas.co.in/trail-shoes", 1
    )
    found = _rival_found(scene)
    c = found["rival:cluster:commercial:trail shoes"]
    assert c.evidence["gap"] is False and c.evidence["spread"] == -0.25
    assert "Nike is named in 50% of 4 answers; Adidas in 75%." in c.body
    assert "Publish a category page on trail shoes" in c.body


def test_rival_rule_pressure_saturates_and_evidence_is_capped(owner, scene):  # noqa: F811
    A = scene.adidas
    url = "https://adidas.co.in/running-shoes/{}"
    for i in range(2):
        _page(owner, scene.org, scene.brand, A, url.format(i), 1)
    assert _rival_found(scene)[KEY].pressure == 0.4
    for i in range(2, 12):
        _page(owner, scene.org, scene.brand, A, url.format(i), 1)
    c = _rival_found(scene)[KEY]
    assert c.pressure == 1.0
    assert len(c.evidence["pages"]) == 10 and c.evidence["pages_total"] == 12


def test_rival_rule_refresh_upserts_deletes_and_keeps_decisions(owner, scene):  # noqa: F811
    org, bid, A = scene.org, scene.brand, scene.adidas
    _page(owner, org, bid, A, "https://adidas.co.in/running-shoes/new", 2)

    def rows():
        with owner() as s:
            return s.scalars(
                select(m.Recommendation).where(
                    m.Recommendation.type == "respond_to_rival_content"
                )
            ).all()

    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
        refresh(s, org.id, bid)
    assert [r.subject_key for r in rows()] == [KEY]
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.type == "respond_to_rival_content")
            .values(status="accepted")
        )
        s.execute(delete(m.RivalPage))
    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
    assert [r.status for r in rows()] == ["accepted"]  # decided rows stay
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.type == "respond_to_rival_content")
            .values(status="open")
        )
    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
    assert rows() == []  # open rows without evidence are removed


def test_rival_pages_is_one_statement(owner, scene):  # noqa: F811
    from sqlalchemy import event

    _page(
        owner, scene.org, scene.brand, scene.adidas, "https://adidas.co.in/a", 1
    )
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(scene.org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            assert len(_rival_pages(s, scene.brand)) == 1
        finally:
            event.remove(bind, "before_cursor_execute", count)
    assert len(seen) == 1
