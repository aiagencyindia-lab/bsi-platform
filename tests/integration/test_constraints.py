import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bsi_core import models as m
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError


def test_observation_status_check_rejects_bad_value(
    owner, make_org, make_brand
):
    org = make_org()
    brand_id = make_brand(org)
    now = datetime.now(UTC)

    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == brand_id)
        ).one()
        engine = s.scalars(
            select(m.Engine).where(m.Engine.code == "gemini")
        ).one()
        prompt = m.Prompt(
            org_id=org.id,
            brand_id=brand_id,
            locale_id=locale.id,
            text="who is the best?",
        )
        s.add(prompt)
        s.flush()
        job = m.Job(org_id=org.id, brand_id=brand_id, scheduled_slot=now)
        s.add(job)
        s.flush()
        prompt_id, engine_id, job_id = prompt.id, engine.id, job.id

    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.Observation(
                org_id=org.id,
                brand_id=brand_id,
                job_id=job_id,
                prompt_id=prompt_id,
                engine_id=engine_id,
                locale_id=locale.id,
                sample_index=0,
                scheduled_slot=now,
                status="runing",
            )
        )
        s.flush()


def test_extraction_cost_defaults_to_zero_and_mention_has_evidence(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    oid = make_observation(org, bid, status="done")
    with owner() as s, s.begin():
        s.add(
            m.Extraction(
                org_id=org.id,
                observation_id=oid,
                pipeline_version="2",
                model_used="x",
                brand_mentioned=True,
            )
        )
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="recommended",
                sentiment="positive",
                evidence_sentence="Nike is the best choice.",
            )
        )
    with owner() as s:
        ex = s.scalars(select(m.Extraction)).one()
        mention = s.scalars(select(m.Mention)).one()
    assert ex.cost_micros == 0
    assert mention.evidence_sentence == "Nike is the best choice."


@pytest.mark.parametrize(
    ("bad", "check"),
    [
        ({"intent": "shopping"}, "ck_prompt_intent"),
        ({"status": "draft"}, "ck_prompt_status"),
        ({"source": "imported"}, "ck_prompt_source"),
    ],
)
def test_prompt_label_checks(owner, make_org, make_brand, bad, check):
    org = make_org()
    brand_id = make_brand(org)
    with owner() as s:
        locale_id = (
            s.scalars(select(m.Locale).where(m.Locale.brand_id == brand_id))
            .one()
            .id
        )
    with pytest.raises(IntegrityError, match=check), owner() as s, s.begin():
        s.add(
            m.Prompt(
                org_id=org.id,
                brand_id=brand_id,
                locale_id=locale_id,
                text="who is the best?",
                **bad,
            )
        )


def test_prompt_embedding_round_trips(owner, make_org, make_brand):
    org = make_org()
    brand_id = make_brand(org)
    vec = [0.5] * 768
    with owner() as s, s.begin():
        locale_id = (
            s.scalars(select(m.Locale).where(m.Locale.brand_id == brand_id))
            .one()
            .id
        )
        prompt = m.Prompt(
            org_id=org.id,
            brand_id=brand_id,
            locale_id=locale_id,
            text="best running shoes",
            intent="commercial",
            topic="running shoes",
            embedding=vec,
        )
        s.add(prompt)
        s.flush()
        prompt_id = prompt.id
    with owner() as s:
        distance = s.execute(
            text("SELECT embedding <=> (:v)::vector FROM prompt WHERE id = :i"),
            {"v": str(vec), "i": prompt_id},
        ).scalar_one()
    assert distance == pytest.approx(0.0, abs=1e-6)


def test_competitor_status_check(owner, make_org, make_brand):
    org = make_org()
    brand_id = make_brand(org)
    with (
        pytest.raises(IntegrityError, match="ck_competitor_status"),
        owner() as s,
        s.begin(),
    ):
        s.add(
            m.Competitor(
                org_id=org.id, brand_id=brand_id, name="X", status="maybe"
            )
        )


def test_organization_budget_check(owner, make_org):
    make_org()
    with (
        pytest.raises(IntegrityError, match="ck_organization_budget"),
        owner() as s,
        s.begin(),
    ):
        s.add(m.Organization(name="Broke", daily_budget_usd=Decimal("-1")))


def test_job_status_check(owner, make_org, make_brand):
    org = make_org()
    brand_id = make_brand(org)
    with (
        pytest.raises(IntegrityError, match="ck_job_status"),
        owner() as s,
        s.begin(),
    ):
        s.add(
            m.Job(
                org_id=org.id,
                brand_id=brand_id,
                kind="suggest_prompts",
                scheduled_slot=datetime.now(UTC),
                status="pending",
            )
        )


def test_job_bookkeeping_defaults(owner, make_org, make_brand):
    org = make_org()
    brand_id = make_brand(org)
    with owner() as s, s.begin():
        s.add(
            m.Job(
                org_id=org.id,
                brand_id=brand_id,
                scheduled_slot=datetime.now(UTC),
            )
        )
    with owner() as s:
        job = s.scalars(select(m.Job)).one()
    assert (job.status, job.params, job.cost_micros) == (None, {}, 0)
    assert job.error is None and job.started_at is None


def test_rec_label_rejects_an_unknown_label(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    oid = make_observation(org, bid, status="done")
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.RecLabel(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                label="brilliant",
            )
        )


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("ck_recommendation_type", m.REC_TYPES),
        ("ck_recommendation_status", m.REC_STATES),
        ("ck_task_status", m.TASK_STATUSES),
        ("ck_task_impact_label", m.IMPACT_LABELS),
        ("ck_alert_type", m.ALERT_TYPES),
    ],
)
def test_slice6_checks_match_their_constants(owner, db, name, values):
    # alembic check does not diff CHECK constraints; the migration spells
    # the lists out, so compare the live database with the constants.
    with owner() as s:
        sql = s.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = :n"
            ),
            {"n": name},
        ).scalar_one()
    assert set(re.findall(r"'([a-z_]+)'", sql)) == set(values)


def test_a_done_task_must_carry_its_window(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(m.Task(org_id=org.id, brand_id=bid, title="t", status="done"))


def test_one_recommendation_becomes_at_most_one_task(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type="sample_more",
            subject_key="k",
            title="t",
            body="b",
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        rid = rec.id
        s.add(
            m.Task(
                org_id=org.id, brand_id=bid, recommendation_id=rid, title="a"
            )
        )
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.Task(
                org_id=org.id, brand_id=bid, recommendation_id=rid, title="b"
            )
        )
