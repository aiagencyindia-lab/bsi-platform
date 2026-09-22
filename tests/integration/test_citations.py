"""Per-domain citation intelligence over the slice-6 fixture world."""

import pytest
from bsi_core import models as m
from bsi_core.citations import sources
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters
from sqlalchemy import select, update

from tests.integration.test_recommend import _mention, world  # noqa: F401


@pytest.fixture
def cited(owner, world):  # noqa: F811
    """The world, plus what the audit needs that the rules did not.

    nike.com becomes a declared brand domain, and Bata, a second active
    rival, is named in one forbes.com-citing answer. forbes.com is then
    the one gap: two rivals named, the brand never.
    """
    with owner() as s, s.begin():
        s.add(
            m.Domain(org_id=world.org.id, brand_id=world.brand, host="nike.com")
        )
        bata = m.Competitor(
            org_id=world.org.id, brand_id=world.brand, name="Bata"
        )
        s.add(bata)
        s.flush()
        # Observation ids are random UUIDs, so ordering by them alone
        # picks arbitrarily among the 5 observations citing forbes.com -
        # 4 belong to `dominated` (which also cite four.com) and only 1
        # to `present` (the brand-absent answer the docstring above
        # means). Pin it to the `present` prompt so the mention lands on
        # that one, deterministically.
        forbes_obs = s.scalars(
            select(m.Citation.observation_id)
            .join(m.Observation, m.Observation.id == m.Citation.observation_id)
            .where(
                m.Citation.domain == "forbes.com",
                m.Observation.prompt_id == world.present,
            )
        ).first()
        s.add(_mention(world.org, forbes_obs, "competitor", bata.id))
    return world


def by_domain(w, f=None):
    with tenant_session(w.org.id) as s:
        return {r["domain"]: r for r in sources(s, w.brand, f or Filters())}


def test_every_cited_domain_is_listed_most_cited_first(cited):
    with tenant_session(cited.org.id) as s:
        rows = sources(s, cited.brand, Filters())
    assert [r["domain"] for r in rows] == [
        "adidas.co.in",  # 5 answers
        "forbes.com",  # 5
        "blog.com",  # 4
        "four.com",  # 4
        "nike.com",  # 2
        "rare.com",  # 2
    ]
    assert [r["answers"] for r in rows] == [5, 5, 4, 4, 2, 2]


def test_gap_needs_two_rivals_and_no_brand(cited):
    rows = by_domain(cited)
    forbes = rows["forbes.com"]
    assert (forbes["brand_named"], forbes["prompts"]) == (0, 2)
    assert forbes["rivals"] == [
        {"name": "Adidas", "answers": 5},
        {"name": "Bata", "answers": 1},
    ]
    assert forbes["gap"] is True
    # blog.com: the brand is named in 3 of its 4 answers. Its 4th
    # (brand-absent) answer is the same one Bata's mention landed on
    # above, so blog.com picks up Bata too - but brand_named != 0
    # keeps it out of gap.
    assert rows["blog.com"]["brand_named"] == 3
    assert rows["blog.com"]["rivals"] == [
        {"name": "Adidas", "answers": 1},
        {"name": "Bata", "answers": 1},
    ]
    assert rows["blog.com"]["gap"] is False
    # four.com: brand never named, but only one rival -> not a gap.
    assert rows["four.com"]["brand_named"] == 0
    assert rows["four.com"]["gap"] is False
    # adidas.co.in: rival-owned, 2 rivals named, brand never named, but
    # it isn't a gap - a rival's own domain is not an outreach opportunity.
    adidas = rows["adidas.co.in"]
    assert len(adidas["rivals"]) == 2
    assert adidas["brand_named"] == 0
    assert adidas["gap"] is False
    assert {r["gap"] for d, r in rows.items() if d != "forbes.com"} == {False}


def test_owner_is_read_live_from_declared_domains(cited):
    rows = by_domain(cited)
    assert (rows["nike.com"]["owner"], rows["nike.com"]["source_type"]) == (
        "brand",
        "vendor",
    )
    assert rows["adidas.co.in"]["owner"] == "rival"
    assert rows["forbes.com"]["owner"] == "third_party"
    assert rows["forbes.com"]["source_type"] == "other"


def test_seen_range_and_evidence_links(cited):
    forbes = by_domain(cited)["forbes.com"]
    assert forbes["first_seen"] <= forbes["last_seen"]
    assert len(forbes["observation_ids"]) == 5
    # Every linked answer really cites the domain.
    with tenant_session(cited.org.id) as s:
        citing = set(
            s.scalars(
                select(m.Citation.observation_id).where(
                    m.Citation.domain == "forbes.com"
                )
            )
        )
    assert set(forbes["observation_ids"]) <= citing


def test_filters_apply(cited):
    only_present = by_domain(cited, Filters(prompt_ids=[cited.present]))
    assert only_present["forbes.com"]["answers"] == 1
    assert only_present["forbes.com"]["prompts"] == 1
    assert "four.com" not in only_present  # cited on `dominated` only


def test_locale_filter_drops_answers_in_another_locale(owner, cited):
    with owner() as s, s.begin():
        oid, first = s.execute(
            select(m.Observation.id, m.Observation.locale_id)
            .join(m.Citation, m.Citation.observation_id == m.Observation.id)
            .where(m.Citation.domain == "forbes.com")
        ).first()
        other = m.Locale(
            org_id=cited.org.id,
            brand_id=cited.brand,
            country="GB",
            language="en",
        )
        s.add(other)
        s.flush()
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == oid)
            .values(locale_id=other.id)
        )
    assert by_domain(cited)["forbes.com"]["answers"] == 5
    first_only = by_domain(cited, Filters(locale_id=first))
    assert first_only["forbes.com"]["answers"] == 4
    assert oid not in first_only["forbes.com"]["observation_ids"]


def test_empty_brand_gives_empty_list(make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        assert sources(s, bid, Filters()) == []
