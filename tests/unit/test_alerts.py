import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from bsi_core.alerts import drop_copy, payload, shift_copy, sign, source_copy


def test_copy_reads_as_observed_facts():
    assert (
        drop_copy(0.18, 0.52, 0.34)
        == "Mention rate fell 18.0 points over the last 7 days "
        "(52.0% to 34.0%)"
    )
    assert (
        shift_copy("Adidas", "up", 11)
        == "Adidas was named more often on 11 prompts over the last 14 days"
    )
    assert (
        shift_copy("Adidas", "down", 10)
        == "Adidas was named less often on 10 prompts over the last 14 days"
    )
    assert (
        source_copy("forbes.com", 6)
        == "forbes.com was cited in 6 answers, the first time in the last "
        "7 days"
    )


def test_payload_is_json_with_slack_text():
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    a = SimpleNamespace(
        id=uuid.uuid4(),
        brand_id=uuid.uuid4(),
        type="new_source",
        subject_key="forbes.com",
        title="forbes.com was cited in 6 answers, the first time in the "
        "last 7 days",
        detail={"domain": "forbes.com", "answers": 6},
        window_from=now - timedelta(days=7),
        window_to=now,
        created_at=now,
    )
    p = payload(a, "Nike")
    body = json.loads(json.dumps(p, default=str))
    assert body["text"] == a.title and body["brand"] == "Nike"
    assert body["type"] == "new_source" and body["detail"]["answers"] == 6
    assert body["window_to"] == "2026-09-25 12:00:00+00:00"
    assert set(body) == {
        "id",
        "type",
        "brand_id",
        "brand",
        "title",
        "text",
        "subject_key",
        "window_from",
        "window_to",
        "created_at",
        "detail",
    }


def test_sign_is_an_hmac_over_t_dot_body():
    body = b'{"text":"hi"}'
    want = hmac.new(
        b"s" * 32, b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    assert sign("s" * 32, body, 1700000000) == f"t=1700000000,v1={want}"
    assert sign("s" * 32, body + b" ", 1700000000) != sign(
        "s" * 32, body, 1700000000
    )
