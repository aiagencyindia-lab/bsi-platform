import json
import subprocess
import sys
from pathlib import Path

import pytest
from bsi_core import models as m

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


@pytest.fixture
def labelled_scene(owner, make_org, make_brand, make_observation):
    org = make_org()
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    with owner() as s, s.begin():
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="recommended",
                sentiment="positive",
                evidence_sentence="Nike is best.",
            )
        )
    return org, bid, oid


def test_queue_hides_the_verdict_then_put_reveals_it(client, labelled_scene):
    org, bid, oid = labelled_scene
    queue = client.get(
        f"/v1/brands/{bid}/labels/next", headers=org.headers
    ).json()
    item = queue["item"]
    assert (item["observation_id"], item["entity_name"]) == (str(oid), "Nike")
    assert item["evidence_sentence"] == "Nike is best." and item["text"]
    assert "rec_status" not in item and "judge" not in item
    assert (queue["labelled"], queue["remaining"]) == (0, 1)

    url = f"/v1/observations/{oid}/labels/{bid}"
    put = client.put(url, json={"label": "listed"}, headers=org.headers)
    assert put.json() == {
        "label": "listed",
        "judge": "recommended",
        "agrees": False,
    }
    again = client.put(url, json={"label": "recommended"}, headers=org.headers)
    assert again.json()["agrees"] is True  # relabelling overwrites

    queue = client.get(
        f"/v1/brands/{bid}/labels/next", headers=org.headers
    ).json()
    assert queue["item"] is None
    assert (queue["labelled"], queue["remaining"]) == (1, 0)
    assert (queue["agreement"]["value"], queue["agreement"]["n"]) == (1.0, 1)


def test_labels_reject_bad_input_and_other_tenants(
    client, make_org, labelled_scene
):
    org, bid, oid = labelled_scene
    url = f"/v1/observations/{oid}/labels/{bid}"
    bad = client.put(url, json={"label": "brilliant"}, headers=org.headers)
    assert bad.status_code == 422
    missing = client.put(
        f"/v1/observations/{oid}/labels/{oid}",
        json={"label": "listed"},
        headers=org.headers,
    )
    assert missing.status_code == 404  # no such mention
    other = make_org("B")
    assert (
        client.put(url, json={"label": "listed"}, headers=other.headers)
    ).status_code == 404
    assert (
        client.get(f"/v1/brands/{bid}/labels/next", headers=other.headers)
    ).status_code == 404


def test_label_vocabulary_matches_the_model():
    from typing import get_args

    from bsi_api.routers.labels import RecStatus

    assert get_args(RecStatus) == m.REC_STATUSES


def test_db_check_constraint_matches_rec_statuses(owner):
    """The migration hardcodes this CHECK (a migration must be static);
    models.py generates the identical one from REC_STATUSES. alembic
    check doesn't diff CHECK constraints, so query the live constraint
    from the test database rather than trusting the two stay in step."""
    import re

    from sqlalchemy import text

    with owner() as s:
        defn = s.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_rec_label_label'"
            )
        ).scalar_one()
    accepted = set(re.findall(r"'([^']*)'", defn))
    assert accepted == set(m.REC_STATUSES)


def test_orphaned_competitor_mention_is_skipped(
    client, owner, make_org, make_brand, make_observation
):
    """A mentioned competitor can be hard-deleted later; Mention.entity_id
    has no FK to it. The queue must skip that mention, not 404."""
    org = make_org()
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=org.id, brand_id=bid, name="Ghost")
        s.add(comp)
        s.flush()
        comp_id = comp.id
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="competitor",
                entity_id=comp_id,
                position=1,
                rec_status="listed",
                sentiment="neutral",
                evidence_sentence="Ghost is fine.",
            )
        )
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=2,
                rec_status="recommended",
                sentiment="positive",
                evidence_sentence="Nike is best.",
            )
        )
    with owner() as s, s.begin():
        s.delete(s.get_one(m.Competitor, comp_id))

    queue = client.get(
        f"/v1/brands/{bid}/labels/next", headers=org.headers
    ).json()
    item = queue["item"]
    assert (item["entity_type"], item["entity_name"]) == ("brand", "Nike")
    # The orphaned mention is unlabellable: it must not be counted as
    # remaining work the operator can never actually do.
    assert queue["remaining"] == 1


def test_export_from_db_skips_orphaned_entity(
    owner, make_org, make_brand, make_observation
):
    """from_db must not abort the whole export over one deleted entity."""
    org_name = "Export Org"
    org = make_org(org_name)
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=org.id, brand_id=bid, name="Ghost")
        s.add(comp)
        s.flush()
        comp_id = comp.id
        s.add(
            m.RecLabel(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                label="recommended",
            )
        )
        s.add(
            m.RecLabel(
                org_id=org.id,
                observation_id=oid,
                entity_type="competitor",
                entity_id=comp_id,
                label="listed",
            )
        )
    with owner() as s, s.begin():
        s.delete(s.get_one(m.Competitor, comp_id))

    result = subprocess.run(
        [sys.executable, "scripts/export_rec_labels.py", "--from-db", org_name],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = [json.loads(line) for line in result.stdout.splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["observation_id"] == str(oid)
    assert rows[0]["expected"] == {"Nike": "recommended"}
    assert rows[0]["entities"] == [
        {"id": "Nike", "type": "brand", "aliases": ["Nike"]}
    ]
