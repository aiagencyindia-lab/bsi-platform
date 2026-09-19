from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy import select
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
