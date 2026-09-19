import uuid

import pytest
from bsi_core.storage import LocalRawStore


def test_round_trip_and_org_prefix(tmp_path):
    store = LocalRawStore(str(tmp_path))
    org, obs = uuid.uuid4(), uuid.uuid4()
    uri = store.put(org, obs, {"a": 1})
    assert f"orgs/{org}/raw/{obs}.json" in uri
    assert store.get(uri, org) == {"a": 1}


def test_cannot_read_another_orgs_payload(tmp_path):
    store = LocalRawStore(str(tmp_path))
    uri = store.put(uuid.uuid4(), uuid.uuid4(), {"secret": True})
    with pytest.raises(PermissionError):
        store.get(uri, uuid.uuid4())
