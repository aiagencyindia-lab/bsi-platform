from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.impact import close_window, measure

NOW = datetime.now(UTC)
# A 14-day window around DONE: before is [-29d, -15d), after [-15d, -1d).
DONE = NOW - timedelta(days=15)
BEFORE, AFTER = NOW - timedelta(days=20), NOW - timedelta(days=5)


@pytest.fixture
def base(owner, make_org, make_brand, make_observation):
    org = make_org()
    bid = make_brand(org)
    # status 'fetched': a template for seed() that is never counted
    first = make_observation(org, bid)
    with owner() as s:
        pid = s.get(m.Observation, first).prompt_id
    return org, bid, pid, first


def seed(owner, org, first, when, present, count, start, version=None):
    """`count` done observations on first's prompt, requested at `when`;
    the brand is named in the first `present` of them."""
    with owner() as s, s.begin():
        t = s.get(m.Observation, first)
        for i in range(count):
            o = m.Observation(
                org_id=org.id,
                brand_id=t.brand_id,
                job_id=t.job_id,
                prompt_id=t.prompt_id,
                engine_id=t.engine_id,
                locale_id=t.locale_id,
                sample_index=start + i,
                scheduled_slot=t.scheduled_slot,
                status="done",
                requested_at=when,
            )
            s.add(o)
            s.flush()
            if i < present:
                s.add(
                    m.Mention(
                        org_id=org.id,
                        observation_id=o.id,
                        entity_type="brand",
                        entity_id=t.brand_id,
                        position=1,
                        rec_status="mentioned",
                        sentiment="neutral",
                    )
                )
            if version is not None:
                s.add(
                    m.Extraction(
                        org_id=org.id,
                        observation_id=o.id,
                        pipeline_version=version,
                        model_used="test",
                        brand_mentioned=i < present,
                    )
                )


def make_task(owner, org, bid, prompt_ids, done_at=DONE):
    with owner() as s, s.begin():
        t = m.Task(
            org_id=org.id,
            brand_id=bid,
            title="t",
            status="done",
            prompt_ids=prompt_ids,
            done_at=done_at,
            window_days=14,
        )
        s.add(t)
        s.flush()
        return t.id


def measured(org, tid):
    with tenant_session(org.id) as s:
        return measure(s, s.get_one(m.Task, tid))


@pytest.mark.parametrize(
    ("before", "after", "label"),
    [
        (0, 20, "improved"),
        (20, 0, "declined"),
        (10, 10, "no_change"),
        (None, 20, "insufficient_data"),
    ],
)
def test_measure_labels_the_change(owner, base, before, after, label):
    org, bid, pid, first = base
    if before is not None:
        seed(owner, org, first, BEFORE, before, 20, start=100)
    seed(owner, org, first, AFTER, after, 20, start=200)
    got, payload = measured(org, make_task(owner, org, bid, [pid]))
    assert got == label
    assert payload["metric"] == "mention_rate"
    assert payload["after"]["n"] == 20


def test_measure_refuses_mixed_pipeline_versions(owner, base):
    org, bid, pid, first = base
    seed(owner, org, first, BEFORE, 10, 20, start=100, version="1")
    seed(owner, org, first, AFTER, 10, 20, start=200, version="2")
    got, payload = measured(org, make_task(owner, org, bid, [pid]))
    assert got == "not_comparable"
    assert payload["delta"] is None and "pipeline" in payload["reason"]


def test_measure_counts_only_the_tasks_prompts(owner, base, make_observation):
    org, bid, pid, first = base
    seed(owner, org, first, BEFORE, 10, 20, start=100)
    seed(owner, org, first, AFTER, 10, 20, start=200)
    other = make_observation(org, bid, text="other prompt")
    seed(owner, org, other, AFTER, 20, 20, start=300)
    got, _ = measured(org, make_task(owner, org, bid, [pid]))
    assert got == "no_change"  # the other prompt's jump is not counted


def test_close_window_measures_a_due_task_once(owner, base):
    org, bid, pid, first = base
    seed(owner, org, first, BEFORE, 0, 20, start=100)
    seed(owner, org, first, AFTER, 20, 20, start=200)
    tid = make_task(owner, org, bid, [pid])
    assert close_window(org.id, tid) == "improved"
    with owner() as s:
        t = s.get(m.Task, tid)
        assert (t.status, t.impact_label) == ("impact_measured", "improved")
    assert close_window(org.id, tid) is None


def test_close_window_leaves_an_open_window_alone(owner, base):
    org, bid, pid, _ = base
    tid = make_task(owner, org, bid, [pid], done_at=NOW - timedelta(days=5))
    assert close_window(org.id, tid) is None
    with owner() as s:
        assert s.get(m.Task, tid).status == "done"
