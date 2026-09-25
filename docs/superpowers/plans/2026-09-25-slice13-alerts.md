# Slice 13: Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect three kinds of change over rolling windows of stored answers, store them as alerts, show them on an Alerts tab, and POST each one to an optional per-brand HTTPS webhook with bounded retries.

**Architecture:** A new core module `alerts.py` composes three detectors over existing metric and feed functions and inserts `alert` rows with a per-window dedupe. The worker's minute loop gains a daily per-brand scan (due-stamp pattern) and a delivery pass that POSTs through the existing SSRF-guarded fetcher, extended with a POST path. A small router lists alerts and triggers a scan; the brand PATCH gains a validated webhook URL; the web app gains an Alerts tab.

**Tech Stack:** Python 3.13, SQLAlchemy 2, psycopg 3, Alembic, FastAPI, pydantic 2, httpx (already a dependency), Postgres 16; Next.js 15 App Router, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-slice13-alerts-design.md`

## Changes made during execution

This plan is the record of what was planned. These changes were made while it ran; the spec is updated to match, and `docs/findings-slice13.md` §3 lists every ruling with its cost.
- Docs review fixes (commit 8194de4): no `s.begin()` on `tenant_session`; `http_fetch`'s response buffer renamed to `buf`; the 15-point floor rounds to 9 places and gets floor-only, label-only and exact-15-point tests; a delivery-marking test; the live check runs the detectors in a rolled-back session.
- Task 1: added the list index `ix_alert_list` (Ruling 1); ascending index columns (Ruling 4).
- Task 2: the scan test is named `test_scan_inserts_and_dedupes_within_the_window` (Ruling 3); alert copy is tested by a separate `ALERT_CASES` list (Ruling 10).
- Task 7: new-source alerts need a full window of history before the current window (Ruling 11, commits 4717c95 and 20b1387).
- Final review (commit 7e22c45): clearing the webhook stops pending deliveries; `scan` takes a per-brand advisory lock; webhook posts send `WEBHOOK_UA`.

## Global Constraints

- Every tenant table has `org_id`, RLS with `ENABLE` + `FORCE` via `_protect()` copied into the migration, a row in `TENANT_TABLES` and in the `org_b` fixture of `tests/integration/test_rls.py`.
- Every id-taking route gets a `CASES` row in `tests/integration/test_isolation.py`; the foreign fixture data is named "Secret".
- Cross-tenant reads only through SECURITY DEFINER `due_*()` functions called from `system_session()`; per-brand work in `tenant_session(org_id)`; stamps with `func.now()` (database clock).
- No transaction may be open during an HTTP call. Tests prove it with the `pg_stat_activity` "idle in transaction" probe.
- SQL: only fixed fragments are concatenated; every value is bound.
- Copy must never contain guarantee, will rank, will appear, will be recommended, ensure, boost, #1, top spot, dominat or certain (`tests/unit/test_recommend_copy.py`).
- Frontend: Server Components and server actions only; no `"use client"`; the API orders everything; links only for `http://`/`https://` URLs; `?queued=` + a `*Note()` helper built on `note()`.
- ruff line length 80; `mypy --strict` on `packages/core/bsi_core`.
- No model spend anywhere in this slice.
- Subagents: "Do NOT edit tests/conftest.py or create databases; never touch the dev DB, the network or the worker loop."
- Commit trailer: the `Co-Authored-By` line from the current session reminder.
- The shell cwd resets after every command: start each with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Gate: `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`, then `cd apps/web && npm run gate`.

---

### Task 1: Schema — `alert` table, brand columns, due functions

**Files:**
- Create: `migrations/versions/0016_alerts.py`
- Modify: `packages/core/bsi_core/models.py` (after `IMPACT_LABELS` ~line 51; `Brand` ~line 115; after `Task`)
- Test: `tests/integration/test_rls.py`, `tests/integration/test_constraints.py`, `tests/integration/test_alerts.py` (new)

**Interfaces:**
- Produces: `m.ALERT_TYPES`, `m.Alert` (columns below), `m.Brand.alerts_scanned_at`, `m.Brand.webhook_url`, SQL functions `due_alert_scans()` and `due_alert_deliveries()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_rls.py`: `"alert"` at the end of `TENANT_TABLES`, and in the `org_b` fixture's last `with owner() as s, s.begin():` block add
```python
        s.add(
            m.Alert(
                org_id=b.id,
                brand_id=bid,
                type="new_source",
                subject_key="b.com",
                title="t",
                window_from=datetime.now(UTC),
                window_to=datetime.now(UTC),
            )
        )
```
Add to the parametrize list of `test_slice6_checks_match_their_constants` in `tests/integration/test_constraints.py`:
```python
        ("ck_alert_type", m.ALERT_TYPES),
```
Create `tests/integration/test_alerts.py`:
```python
"""Alerts: detectors, dedupe, scan, and the due functions."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from sqlalchemy import func, select, text, update


def due_scans():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_alert_scans()"))
        ]


def due_deliveries():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(
                text("SELECT alert_id FROM due_alert_deliveries()")
            )
        ]


def _alert(owner, org, bid, **kw):
    """One stored alert; keyword arguments override the defaults."""
    now = datetime.now(UTC)
    row = {
        "type": "new_source",
        "subject_key": "x.com",
        "title": "t",
        "window_from": now - timedelta(days=7),
        "window_to": now,
        **kw,
    }
    with owner() as s, s.begin():
        a = m.Alert(org_id=org.id, brand_id=bid, **row)
        s.add(a)
        s.flush()
        return a.id


def test_a_never_scanned_active_brand_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    other = make_brand(org, "Archived")
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == other).values(status="archived")
        )
    assert due_scans() == [bid]


def test_a_brand_is_due_a_scan_again_after_a_day(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    for hours, due in ((20, []), (25, [bid])):
        with owner() as s, s.begin():
            s.execute(
                update(m.Brand)
                .where(m.Brand.id == bid)
                .values(
                    alerts_scanned_at=func.now()
                    - func.make_interval(0, 0, 0, 0, hours)
                )
            )
        assert due_scans() == due


def test_deliveries_are_due_only_with_a_webhook_and_a_past_attempt_time(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    past = func.now() - func.make_interval(0, 0, 0, 0, 0, 1)
    future = func.now() + func.make_interval(0, 0, 0, 0, 1)
    a_due = _alert(owner, org, bid, next_attempt_at=past)
    _alert(owner, org, bid, next_attempt_at=future)
    _alert(owner, org, bid, next_attempt_at=None)
    _alert(owner, org, bid, next_attempt_at=past, delivered_at=func.now())
    assert due_deliveries() == []  # no webhook yet
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == bid)
            .values(webhook_url="https://hooks.example.com/x")
        )
    assert due_deliveries() == [a_due]


def test_alert_rows_are_tenant_scoped(owner, make_org, make_brand):
    a, b = make_org("A"), make_org("B")
    aid = _alert(owner, a, make_brand(a))
    _alert(owner, b, make_brand(b))
    with tenant_session(a.id) as s:
        assert s.scalars(select(m.Alert.id)).all() == [aid]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_alerts.py tests/integration/test_rls.py tests/integration/test_constraints.py -x`
Expected: FAIL with `AttributeError: module 'bsi_core.models' has no attribute 'Alert'` (or `ALERT_TYPES`).

- [ ] **Step 3: Add the model**

In `packages/core/bsi_core/models.py`, after `IMPACT_LABELS`:
```python
ALERT_TYPES = ("mention_drop", "competitor_shift", "new_source")
```
In `Brand`, after `recs_refreshed_at`:
```python
    # Null = never scanned, which due_alert_scans() treats as due.
    alerts_scanned_at: Mapped[datetime | None] = mapped_column(TSZ)
    # One HTTPS URL each new alert is POSTed to; null = no delivery.
    webhook_url: Mapped[str | None]
```
After `class Task`:
```python
class Alert(Tenant, Base):
    """A change worth telling the operator about, found by the daily scan
    over rolling windows. Never raised from a single observation.

    Delivery state lives on the row: attempts, the next attempt time and
    the last error. next_attempt_at NULL = not for delivery (no webhook at
    scan time, delivered, or given up).
    """

    __tablename__ = "alert"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    # mention_rate | <competitor_id>:<up|down> | <domain>
    subject_key: Mapped[str]
    title: Mapped[str]
    detail: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    window_from: Mapped[datetime] = mapped_column(TSZ)
    window_to: Mapped[datetime] = mapped_column(TSZ)
    delivered_at: Mapped[datetime | None] = mapped_column(TSZ)
    delivery_attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(TSZ)
    last_error: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("type", ALERT_TYPES), name="ck_alert_type"),
        # Dedupe looks up (brand, type, subject) and reads window_to.
        Index(
            "ix_alert_subject", "brand_id", "type", "subject_key", "window_to"
        ),
        Index(
            "ix_alert_due",
            "next_attempt_at",
            postgresql_where=text(
                "delivered_at IS NULL AND next_attempt_at IS NOT NULL"
            ),
        ),
    )
```

- [ ] **Step 4: Write the migration**

Create `migrations/versions/0016_alerts.py`:
```python
"""alert table; brand.alerts_scanned_at, brand.webhook_url;
due_alert_scans(), due_alert_deliveries()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
SCAN_DAYS = 1
ALERT_TYPES = ("mention_drop", "competitor_shift", "new_source")


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def upgrade() -> None:
    op.add_column(
        "brand", sa.Column("alerts_scanned_at", sa.DateTime(timezone=True))
    )
    op.add_column("brand", sa.Column("webhook_url", sa.String()))
    op.create_table(
        "alert",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String()),
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in ALERT_TYPES) + ")",
            name="ck_alert_type",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_subject",
        "alert",
        ["brand_id", "type", "subject_key", "window_to"],
    )
    op.create_index(
        "ix_alert_due",
        "alert",
        ["next_attempt_at"],
        postgresql_where=sa.text(
            "delivered_at IS NULL AND next_attempt_at IS NOT NULL"
        ),
    )
    _protect("alert")
    op.execute(f"""
        CREATE FUNCTION due_alert_scans()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT b.id, b.org_id FROM brand b
          WHERE b.status = 'active'
            AND (b.alerts_scanned_at IS NULL
                 OR b.alerts_scanned_at
                    <= now() - make_interval(days => {SCAN_DAYS}))
          ORDER BY b.alerts_scanned_at NULLS FIRST, b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_alert_scans() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_alert_scans() TO bsi_app")
    op.execute("""
        CREATE FUNCTION due_alert_deliveries()
        RETURNS TABLE(alert_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT a.id, a.org_id FROM alert a
          JOIN brand b ON b.id = a.brand_id
          WHERE a.delivered_at IS NULL
            AND a.next_attempt_at IS NOT NULL
            AND a.next_attempt_at <= now()
            AND b.webhook_url IS NOT NULL
            AND b.status = 'active'
          ORDER BY a.next_attempt_at, a.id
          LIMIT 100
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_alert_deliveries() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_alert_deliveries() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_alert_deliveries()")
    op.execute("DROP FUNCTION due_alert_scans()")
    op.drop_table("alert")
    op.drop_column("brand", "webhook_url")
    op.drop_column("brand", "alerts_scanned_at")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_alerts.py tests/integration/test_rls.py tests/integration/test_constraints.py`
Expected: all PASS (conftest migrates the test DB to head at session start; the `alembic check` test in the RLS/constraints suite must not report a model/migration drift).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0016_alerts.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_constraints.py tests/integration/test_alerts.py && git commit -m "feat(alerts): alert table, brand scan stamp and webhook URL, due functions"
```

---

### Task 2: Detectors, dedupe, copy, scan and payload

**Files:**
- Create: `packages/core/bsi_core/alerts.py`, `tests/unit/test_alerts.py`
- Modify: `tests/unit/test_recommend_copy.py` (CASES), `tests/integration/test_alerts.py` (append)

**Interfaces:**
- Consumes: `metrics.brand_deltas(s, brand_id, Filters, days, to)`; `competitors.visibility_changes(s, brand_id, Filters, days, to)`; `recommend._rival_domains(s, brand_id)`; `matching.is_owned(domain, hosts)`; `citations.EVIDENCE_CAP`; `m.Alert`.
- Produces: `alerts.Candidate`; `alerts.detect_mention_drop / detect_competitor_shift / detect_new_source(s, brand_id, to) -> list[Candidate]`; `alerts.is_duplicate(s, brand_id, c) -> bool`; `alerts.scan(s, org_id, brand_id, to, *, deliver: bool) -> list[m.Alert]`; `alerts.payload(alert, brand_name) -> dict[str, Any]`; `alerts.drop_copy(pts, before, after)`, `shift_copy(name, direction, n_prompts)`, `source_copy(domain, answers)`; constants `DROP_DAYS=7`, `DROP_MIN_PTS=0.15`, `SHIFT_DAYS=14`, `SOURCE_DAYS=7`, `NEW_SOURCE_MIN_ANSWERS=5`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_alerts.py`:
```python
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from bsi_core.alerts import drop_copy, payload, shift_copy, source_copy


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
```
In `tests/unit/test_recommend_copy.py`, add the import `from bsi_core.alerts import drop_copy, shift_copy, source_copy` and, after the existing `CASES +=` blocks:
```python
CASES += [
    drop_copy(0.18, 0.52, 0.34),
    shift_copy("Adidas", "up", 11),
    shift_copy("Adidas", "down", 10),
    source_copy("forbes.com", 6),
]
```

- [ ] **Step 2: Write the failing integration tests**

Append to `tests/integration/test_alerts.py` (imports: add `from bsi_core.alerts import (NEW_SOURCE_MIN_ANSWERS, SOURCE_DAYS, is_duplicate, detect_competitor_shift, detect_mention_drop, detect_new_source, scan)`, `from bsi_core.metrics import Filters, brand_deltas`, `from bsi_core.alerts import DROP_DAYS`, `from tests.integration.test_competitors import NOW, _answers, _cite, _mention, _prompt, feed  # noqa: F401`):
```python
def _brand_mentions(owner, org, obs_ids):
    """The brand named in every one of these answers."""
    with owner() as s, s.begin():
        bid = s.scalar(
            select(m.Observation.brand_id).where(
                m.Observation.id == obs_ids[0]
            )
        )
        s.add_all([_mention(org, o, "brand", bid) for o in obs_ids])


def _drop_scene(owner, make_org, make_brand, before_k, after_k, n=50):
    """One prompt, n answers per 7-day window; the brand is named in
    before_k of the before answers and after_k of the after answers."""
    org = make_org()
    bid = make_brand(org, "Nike")
    p = _prompt(owner, org, bid, "best shoes")
    before = _answers(owner, org, bid, p, NOW - timedelta(days=10), n)
    after = _answers(owner, org, bid, p, NOW - timedelta(days=3), n)
    if before_k:
        _brand_mentions(owner, org, before[:before_k])
    if after_k:
        _brand_mentions(owner, org, after[:after_k])
    return org, bid


def test_mention_drop_fires_on_a_significant_drop_of_15_points(
    owner, make_org, make_brand
):
    org, bid = _drop_scene(owner, make_org, make_brand, 40, 20)  # 80% -> 40%
    with tenant_session(org.id) as s:
        found = detect_mention_drop(s, bid, NOW)
    assert len(found) == 1
    c = found[0]
    assert (c.type, c.subject_key) == ("mention_drop", "mention_rate")
    assert c.window_to == NOW and c.window_from == NOW - timedelta(days=7)
    assert c.detail["before"]["value"] == 0.8
    assert c.detail["after"]["value"] == 0.4
    assert c.title.startswith("Mention rate fell 40.0 points")


def test_mention_drop_needs_both_the_label_and_the_floor(
    owner, make_org, make_brand
):
    # The floor alone: 100/200 -> 75/200 is a significant "decrease" but
    # only 12.5 points. Assert the label, so the case really tests the floor.
    org, bid = _drop_scene(owner, make_org, make_brand, 100, 75, n=200)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] == "decrease"
        assert detect_mention_drop(s, bid, NOW) == []
    # The label alone: 5/10 -> 3/10 is 20 points but not significant.
    org, bid = _drop_scene(owner, make_org, make_brand, 5, 3, n=10)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] != "decrease"
        assert detect_mention_drop(s, bid, NOW) == []


def test_an_exact_15_point_drop_counts(owner, make_org, make_brand):
    # 60% -> 45% of 200: float subtraction gives -0.14999999999999997.
    org, bid = _drop_scene(owner, make_org, make_brand, 120, 90, n=200)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] == "decrease"
        assert len(detect_mention_drop(s, bid, NOW)) == 1


def test_mention_drop_is_silent_when_windows_are_not_comparable(
    owner, make_org, make_brand
):
    org, bid = _drop_scene(owner, make_org, make_brand, 40, 20)
    with owner() as s, s.begin():
        obs = s.scalars(
            select(m.Observation.id).where(m.Observation.brand_id == bid)
        ).all()
        s.add_all(
            m.Extraction(
                org_id=org.id,
                observation_id=o,
                pipeline_version="1" if i % 2 else "2",
                model_used="none",
                brand_mentioned=False,
            )
            for i, o in enumerate(obs)
        )
    with tenant_session(org.id) as s:
        assert detect_mention_drop(s, bid, NOW) == []


def test_competitor_shift_yields_one_candidate_per_feed_entry(feed):  # noqa: F811
    org, bid, ids = feed
    with tenant_session(org.id) as s:
        found = detect_competitor_shift(s, bid, NOW)
    assert [(c.type, c.subject_key) for c in found] == [
        ("competitor_shift", f"{ids['a']}:up")
    ]
    c = found[0]
    assert c.detail["competitor_id"] == ids["a"]
    assert len(c.detail["prompt_ids"]) == 11
    assert 0 < len(c.detail["observation_ids"]) <= 20
    assert c.title == "A was named more often on 11 prompts over the last 14 days"


def _source_scene(owner, make_org, make_brand):
    """Nike (nike.com), rival Adidas (adidas.com). One prompt; answers in
    the last 7 days cite: forbes.com x6 (new), nike.com x6, adidas.com x6,
    few.com x(min-1), old.com x6 (also cited 30 days ago)."""
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        s.add(
            m.Competitor(
                org_id=org.id, brand_id=bid, name="Adidas", domains=["adidas.com"]
            )
        )
    p = _prompt(owner, org, bid, "best shoes")
    old = _answers(owner, org, bid, p, NOW - timedelta(days=30), 1)
    recent = _answers(owner, org, bid, p, NOW - timedelta(days=2), 6)
    cites = [_cite(org, old[0], "old.com")]
    for d in ("forbes.com", "nike.com", "adidas.com", "old.com"):
        cites += [_cite(org, o, d) for o in recent]
    cites += [
        _cite(org, o, "few.com") for o in recent[: NEW_SOURCE_MIN_ANSWERS - 1]
    ]
    with owner() as s, s.begin():
        s.add_all(cites)
    return org, bid, recent


def test_new_source_needs_min_answers_first_seen_in_window_third_party(
    owner, make_org, make_brand
):
    org, bid, recent = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        found = detect_new_source(s, bid, NOW)
    assert [(c.type, c.subject_key) for c in found] == [
        ("new_source", "forbes.com")
    ]
    c = found[0]
    assert c.detail["domain"] == "forbes.com" and c.detail["answers"] == 6
    assert sorted(c.detail["observation_ids"]) == sorted(recent)
    assert c.window_from == NOW - timedelta(days=SOURCE_DAYS)
    assert c.title == (
        "forbes.com was cited in 6 answers, the first time in the last 7 days"
    )


def test_scan_inserts_and_dedupes_within_the_window(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        rows = scan(s, org.id, bid, NOW, deliver=False)
        assert [r.subject_key for r in rows] == ["forbes.com"]
        assert rows[0].next_attempt_at is None
    with tenant_session(org.id) as s:
        assert scan(s, org.id, bid, NOW, deliver=False) == []  # same window
        assert scan(s, org.id, bid, NOW + timedelta(days=3), deliver=True) == []
    # Later answers citing forbes.com again: it is not new any more.
    later = NOW + timedelta(days=8)
    p = _prompt(owner, org, bid, "another")
    again = _answers(owner, org, bid, p, later - timedelta(days=1), 6)
    with owner() as s, s.begin():
        s.add_all(_cite(org, o, "forbes.com") for o in again)
    with tenant_session(org.id) as s:
        assert scan(s, org.id, bid, later, deliver=False) == []  # not new any more
    with owner() as s:
        assert s.scalar(select(func.count(m.Alert.id))) == 1


def test_scan_marks_alerts_for_delivery_only_with_a_webhook(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        (row,) = scan(s, org.id, bid, NOW, deliver=True)
        aid = row.id
    with owner() as s:
        a = s.get(m.Alert, aid)
    assert a.next_attempt_at is not None and a.delivered_at is None


def test_is_duplicate_matches_only_a_younger_alert_of_the_same_subject(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        (c,) = detect_new_source(s, bid, NOW)
        assert not is_duplicate(s, bid, c)
        scan(s, org.id, bid, NOW, deliver=False)
        assert is_duplicate(s, bid, c)
    with owner() as s, s.begin():
        s.execute(
            update(m.Alert).values(window_to=NOW - timedelta(days=8))
        )
    with tenant_session(org.id) as s:
        assert not is_duplicate(s, bid, c)
```
Note for the implementer: the `feed` fixture is imported for pytest to find it; the `# noqa: F811` on the test parameter matches how `tests/integration/test_api_citations.py` reuses fixtures. Merge these imports into the top import block Task 1 created; do not add a second block. `tenant_session` already opens a transaction and commits on exit: never add `s.begin()` to it.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_alerts.py tests/integration/test_alerts.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsi_core.alerts'`.

- [ ] **Step 4: Write `alerts.py`**

Create `packages/core/bsi_core/alerts.py`:
```python
"""Alerts (PRD F15, alerts only): changes worth telling the operator about.

Each detector reads rolling windows of stored answers, so nothing here can
fire from a single observation. `to` is a parameter everywhere so tests
are deterministic. Copy states what was observed and never promises.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import models as m
from .citations import EVIDENCE_CAP
from .competitors import visibility_changes
from .matching import is_owned
from .metrics import Filters, brand_deltas
from .recommend import _rival_domains

DROP_DAYS = 7
DROP_MIN_PTS = 0.15
SHIFT_DAYS = 14
SOURCE_DAYS = 7
# ponytail: the PRD wants "authority above threshold"; there is no
# authority score, so a count of citing answers stands in for it.
NEW_SOURCE_MIN_ANSWERS = 5


@dataclass(frozen=True)
class Candidate:
    type: str
    subject_key: str
    title: str
    detail: dict[str, Any]
    window_from: datetime
    window_to: datetime


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def drop_copy(pts: float, before: float, after: float) -> str:
    return (
        f"Mention rate fell {pts * 100:.1f} points over the last "
        f"{DROP_DAYS} days ({_pct(before)} to {_pct(after)})"
    )


def shift_copy(name: str, direction: str, n_prompts: int) -> str:
    how = "more" if direction == "up" else "less"
    return (
        f"{name} was named {how} often on {n_prompts} prompts over the "
        f"last {SHIFT_DAYS} days"
    )


def source_copy(domain: str, answers: int) -> str:
    return (
        f"{domain} was cited in {answers} answers, the first time in the "
        f"last {SOURCE_DAYS} days"
    )


def detect_mention_drop(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    d = brand_deltas(s, brand_id, Filters(), DROP_DAYS, to)
    if not d["comparable"]:
        return []
    delta = d["deltas"]["mention_rate"]
    # Rounded: 0.45 - 0.6 is -0.14999999999999997 in floats.
    if delta["label"] != "decrease" or round(delta["value"], 9) > -DROP_MIN_PTS:
        return []
    before, after = d["before"]["mention_rate"], d["after"]["mention_rate"]
    return [
        Candidate(
            "mention_drop",
            "mention_rate",
            drop_copy(-delta["value"], before["value"], after["value"]),
            {
                "before": before,
                "after": after,
                "delta": delta,
                "prompt_ids": [],
                "observation_ids": [],
            },
            d["after"]["from"],
            d["after"]["to"],
        )
    ]


def detect_competitor_shift(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    out = visibility_changes(s, brand_id, Filters(), SHIFT_DAYS, to)
    return [
        Candidate(
            "competitor_shift",
            f"{e['competitor_id']}:{e['direction']}",
            shift_copy(e["name"], e["direction"], len(e["prompts"])),
            {
                "competitor_id": e["competitor_id"],
                "name": e["name"],
                "direction": e["direction"],
                "before": e["before"],
                "after": e["after"],
                "delta": e["delta"],
                "prompt_ids": [p["prompt_id"] for p in e["prompts"]],
                "observation_ids": e["observation_ids"],
            },
            out["window"]["split"],
            out["window"]["to"],
        )
        for e in out["changes"]
    ]


# first_seen is over all answers before :to, so a domain cited a year ago
# is never "new"; the answer count is inside the window only.
_NEW_SOURCES = f"""
WITH first AS (
  SELECT c.domain, min(o.requested_at) AS first_seen
  FROM citation c JOIN observation o ON o.id = c.observation_id
  WHERE o.brand_id = :brand AND o.status = 'done' AND o.requested_at < :to
  GROUP BY c.domain)
SELECT f.domain, count(DISTINCT o.id) AS answers,
       (array_agg(DISTINCT o.id))[1:{EVIDENCE_CAP}] AS obs,
       (array_agg(DISTINCT o.prompt_id))[1:{EVIDENCE_CAP}] AS prompts
FROM first f
JOIN citation c ON c.domain = f.domain
JOIN observation o ON o.id = c.observation_id
WHERE f.first_seen >= :from AND o.brand_id = :brand AND o.status = 'done'
  AND o.requested_at >= :from AND o.requested_at < :to
GROUP BY f.domain
HAVING count(DISTINCT o.id) >= :min
ORDER BY 2 DESC, 1"""


def detect_new_source(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    start = to - timedelta(days=SOURCE_DAYS)
    hosts = list(
        s.scalars(select(m.Domain.host).where(m.Domain.brand_id == brand_id))
    )
    rivals = _rival_domains(s, brand_id)
    rows = s.execute(
        text(_NEW_SOURCES),
        {"brand": brand_id, "from": start, "to": to, "min": NEW_SOURCE_MIN_ANSWERS},
    ).all()
    return [
        Candidate(
            "new_source",
            r.domain,
            source_copy(r.domain, r.answers),
            {
                "domain": r.domain,
                "answers": r.answers,
                "prompt_ids": list(r.prompts),
                "observation_ids": list(r.obs),
            },
            start,
            to,
        )
        for r in rows
        if not is_owned(r.domain, hosts) and not is_owned(r.domain, rivals)
    ]


DETECTORS = (detect_mention_drop, detect_competitor_shift, detect_new_source)


def is_duplicate(s: Session, brand_id: uuid.UUID, c: Candidate) -> bool:
    """An alert for the same subject whose window ends after this one
    starts. Windows of a type have one length, so that is "younger than
    the window"."""
    return (
        s.execute(
            text(
                "SELECT 1 FROM alert WHERE brand_id = :b AND type = :t "
                "AND subject_key = :k AND window_to > :wf LIMIT 1"
            ),
            {"b": brand_id, "t": c.type, "k": c.subject_key, "wf": c.window_from},
        ).first()
        is not None
    )


def scan(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    to: datetime,
    *,
    deliver: bool,
) -> list[m.Alert]:
    """Run every detector and store what is not a duplicate. `deliver`
    is whether the brand has a webhook now: an alert stored without one
    is never delivered later."""
    rows = []
    for detect in DETECTORS:
        for c in detect(s, brand_id, to):
            if is_duplicate(s, brand_id, c):
                continue
            rows.append(
                m.Alert(
                    org_id=org_id,
                    brand_id=brand_id,
                    type=c.type,
                    subject_key=c.subject_key,
                    title=c.title,
                    # UUIDs and rate dicts -> plain JSON for JSONB.
                    detail=json.loads(json.dumps(c.detail, default=str)),
                    window_from=c.window_from,
                    window_to=c.window_to,
                    next_attempt_at=func.now() if deliver else None,
                )
            )
    s.add_all(rows)
    s.flush()
    return rows


def payload(alert: Any, brand_name: str) -> dict[str, Any]:
    """The webhook body. `text` is what a Slack incoming webhook renders;
    the rest is for other consumers. Serialise with default=str."""
    return {
        "id": alert.id,
        "type": alert.type,
        "brand_id": alert.brand_id,
        "brand": brand_name,
        "title": alert.title,
        "text": alert.title,
        "subject_key": alert.subject_key,
        "window_from": alert.window_from,
        "window_to": alert.window_to,
        "created_at": alert.created_at,
        "detail": alert.detail,
    }
```
Notes for the implementer: `scan` stores `detail` through a json round trip (UUIDs become strings); `Candidate.detail` stays raw for the detector tests. If `array_agg(...)[1:N]` on uuid returns a list of `uuid.UUID` already, `list(r.obs)` is fine; the tests compare against `recent` (UUIDs), so cast with `uuid.UUID(str(x))` only if psycopg returns strings. `metrics.delta` does not round, so the comparison rounds to 9 places; an exact 15-point drop counts (test_an_exact_15_point_drop_counts).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_alerts.py tests/unit/test_recommend_copy.py tests/integration/test_alerts.py && uv run mypy`
Expected: all PASS; mypy "no issues".

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/alerts.py tests/unit/test_alerts.py tests/unit/test_recommend_copy.py tests/integration/test_alerts.py && git commit -m "feat(alerts): three window detectors, per-window dedupe, scan and webhook payload"
```

---

### Task 3: `http_fetch` POST path

**Files:**
- Modify: `packages/core/bsi_core/crawl.py:231-310` (`http_fetch`)
- Test: `tests/unit/test_http_fetch.py`

**Interfaces:**
- Produces: `http_fetch(url, user_agent, *, resolve=..., transport=None, method="GET", body: bytes | None = None, content_type: str | None = None) -> Response`. Behaviour for GET is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_http_fetch.py`:
```python
def test_post_sends_the_body_and_content_type_to_the_pinned_address():
    t = server(ok)
    r = http_fetch(
        "https://hook.example.com/in",
        "UA",
        resolve=dns({"hook.example.com": [PUBLIC]}),
        transport=t,
        method="POST",
        body=b'{"text":"hi"}',
        content_type="application/json",
    )
    assert r.ok
    (req,) = t.seen
    assert req.method == "POST" and req.content == b'{"text":"hi"}'
    assert req.headers["content-type"] == "application/json"
    assert req.headers["host"] == "hook.example.com"
    assert req.url.host == PUBLIC


def test_post_does_not_follow_a_redirect():
    def moved(request):
        return httpx.Response(302, headers={"location": "https://x.example.com/"})

    t = server(moved)
    r = http_fetch(
        "https://hook.example.com/in",
        "UA",
        resolve=dns({"hook.example.com": [PUBLIC], "x.example.com": [PUBLIC]}),
        transport=t,
        method="POST",
        body=b"{}",
    )
    assert (r.status, r.ok, len(t.seen)) == (302, False, 1)


def test_post_to_a_private_address_is_refused():
    t = server(ok)
    r = http_fetch(
        "https://hook.example.com/in",
        "UA",
        resolve=dns({"hook.example.com": ["10.0.0.1"]}),
        transport=t,
        method="POST",
        body=b"{}",
    )
    assert r.status == 0 and r.error.startswith("refused:") and t.seen == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_http_fetch.py -k post -x`
Expected: FAIL with `TypeError: http_fetch() got an unexpected keyword argument 'method'`.

- [ ] **Step 3: Extend `http_fetch`**

In `crawl.py`, change the signature to
```python
def http_fetch(
    url: str,
    user_agent: str,
    *,
    resolve: Callable[[str, int], list[str]] = _resolve,
    transport: httpx.BaseTransport | None = None,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> Response:
```
Add to the docstring: "POST sends `body` (and `content_type` as Content-Type) and never follows a redirect: a 3xx comes back as a non-ok Response. Every guard applies to both methods." Inside the loop replace the `client.stream("GET", target, headers={...}, ...)` call with:
```python
                headers = {
                    "Host": host,
                    "User-Agent": user_agent,
                    "Accept-Encoding": "gzip, deflate",
                }
                if content_type:
                    headers["Content-Type"] = content_type
                with client.stream(
                    method,
                    target,
                    content=body,
                    headers=headers,
                    extensions=ext,
                    timeout=httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left)),
                ) as r:
                    location = r.headers.get("location")
                    if (
                        method == "GET"
                        and r.status_code in _REDIRECTS
                        and location
                    ):
                        url = urljoin(url, location)
                        continue
```
Rename the response buffer `body = bytearray()` and its uses (`len(body)`, `body += ...`, `bytes(body)`) to `buf`, because `body` is now the request-body parameter (mypy --strict rejects the reuse). Nothing else changes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_http_fetch.py tests/unit/test_crawl.py && uv run mypy`
Expected: all PASS (every existing GET test too); mypy clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py && git commit -m "feat(crawl): http_fetch can POST a body; redirects are followed for GET only"
```

---

### Task 4: Worker scan and delivery passes

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (imports; constants after `CITED_URLS_CAP`; new functions after `refresh_due_recommendations` ~line 170; `main()` ~line 830-851)
- Test: `tests/integration/test_worker.py` (append)

**Interfaces:**
- Consumes: `alerts.scan`, `alerts.payload`, `http_fetch(..., method="POST", body=..., content_type=...)`, `due_alert_scans()`, `due_alert_deliveries()`.
- Produces: `worker.scan_due_alerts() -> int` (brands scanned), `worker.deliver_due_alerts(fetch=http_fetch) -> int` (alerts delivered), `worker.BACKOFF_DELIVERY = (60, 300, 1800, 7200)`, `worker.MAX_DELIVERY_ATTEMPTS = 5`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_worker.py` (add imports `import json`, `from bsi_core.crawl import Response`, `from bsi_workers.worker import BACKOFF_DELIVERY, deliver_due_alerts, scan_due_alerts`, and `from tests.integration.test_alerts import _alert`):
```python
def _hooked_brand(owner, make_org, make_brand, name="A"):
    org = make_org(name)
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == bid)
            .values(webhook_url="https://hooks.example.com/in")
        )
    return org, bid


def _due_alert(owner, org, bid):
    return _alert(
        owner, org, bid, next_attempt_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 1)
    )


class _Hook:
    """A fake fetch that records what was posted and answers as told."""

    def __init__(self, status=200, error=None):
        self.calls = []
        self.status, self.error = status, error

    def __call__(self, url, ua, *, method, body, content_type):
        self.calls.append((url, method, content_type, json.loads(body)))
        return Response(self.status, "", self.error)


def test_scan_due_alerts_serves_every_tenant_and_stamps(
    owner, make_org, make_brand
):
    ids = [make_brand(make_org(n)) for n in ("A", "B")]
    assert scan_due_alerts() == 2
    with owner() as s:
        stamps = s.scalars(
            select(m.Brand.alerts_scanned_at).where(m.Brand.id.in_(ids))
        ).all()
    assert all(t is not None for t in stamps)
    assert scan_due_alerts() == 0


def test_deliver_posts_the_payload_and_marks_delivered(
    owner, make_org, make_brand
):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    aid = _due_alert(owner, org, bid)
    hook = _Hook()
    assert deliver_due_alerts(fetch=hook) == 1
    (url, method, ctype, body) = hook.calls[0]
    assert (url, method, ctype) == (
        "https://hooks.example.com/in", "POST", "application/json"
    )
    assert body["id"] == str(aid) and body["brand"] == "Nike"
    assert body["text"] == body["title"] == "t"
    with owner() as s:
        a = s.get(m.Alert, aid)
    assert a.delivered_at is not None and a.next_attempt_at is None
    assert (a.delivery_attempts, a.last_error) == (1, None)
    assert deliver_due_alerts(fetch=hook) == 0


def test_delivery_walks_the_backoff_schedule_then_gives_up(
    owner, make_org, make_brand
):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    aid = _due_alert(owner, org, bid)
    hook = _Hook(500)
    for attempt, wait in enumerate(BACKOFF_DELIVERY, start=1):
        assert deliver_due_alerts(fetch=hook) == 0
        with owner() as s:
            a = s.get(m.Alert, aid)
            now = s.scalar(select(func.now()))
        assert (a.delivery_attempts, a.last_error) == (attempt, "HTTP 500")
        assert a.delivered_at is None
        assert abs((a.next_attempt_at - now).total_seconds() - wait) < 5
        with owner() as s, s.begin():  # bring the next attempt forward
            s.execute(
                update(m.Alert)
                .where(m.Alert.id == aid)
                .values(next_attempt_at=func.now())
            )
    assert deliver_due_alerts(fetch=hook) == 0
    with owner() as s:
        a = s.get(m.Alert, aid)
    assert (a.delivery_attempts, a.next_attempt_at) == (5, None)
    assert a.last_error == "HTTP 500" and len(hook.calls) == 5


def test_a_refused_url_is_recorded_as_the_error(owner, make_org, make_brand):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    aid = _due_alert(owner, org, bid)
    deliver_due_alerts(fetch=_Hook(0, "refused: 10.0.0.1 is not public"))
    with owner() as s:
        a = s.get(m.Alert, aid)
    assert a.last_error == "refused: 10.0.0.1 is not public"
    assert a.delivery_attempts == 1 and a.next_attempt_at is not None


def test_no_transaction_is_open_during_the_webhook_post(
    owner, make_org, make_brand
):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    _due_alert(owner, org, bid)
    seen = []

    def fetch(url, ua, *, method, body, content_type):
        with owner() as s:
            seen.append(
                s.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE state = 'idle in transaction' "
                        "AND pid <> pg_backend_pid()"
                    )
                )
            )
        return Response(200, "")

    deliver_due_alerts(fetch=fetch)
    assert seen == [0]


def test_one_failing_delivery_does_not_block_the_rest(
    owner, make_org, make_brand
):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    bad = _due_alert(owner, org, bid)
    good = _due_alert(owner, org, bid)
    with owner() as s, s.begin():  # bad is first in next_attempt_at order
        s.execute(
            update(m.Alert)
            .where(m.Alert.id == bad)
            .values(next_attempt_at=func.now() - func.make_interval(0, 0, 0, 1))
        )

    def fetch(url, ua, *, method, body, content_type):
        if json.loads(body)["id"] == str(bad):
            raise RuntimeError("boom")
        return Response(200, "")

    assert deliver_due_alerts(fetch=fetch) == 1
    with owner() as s:
        assert s.get(m.Alert, good).delivered_at is not None
        assert s.get(m.Alert, bad).delivered_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_worker.py -k "alert or deliver" -x`
Expected: FAIL with `ImportError: cannot import name 'deliver_due_alerts'`.

- [ ] **Step 3: Implement the two passes**

In `worker.py`: add `import json` (already present), `from datetime import UTC, datetime, timedelta` (extend the existing `timedelta` import), `from bsi_core.alerts import payload, scan as scan_alerts`. After `CITED_URLS_CAP`:
```python
# Waits before delivery attempts 2..5; after the fifth failure the alert
# is given up and keeps its last error.
BACKOFF_DELIVERY = (60, 300, 1800, 7200)
MAX_DELIVERY_ATTEMPTS = 5


class Poster(Protocol):
    def __call__(
        self,
        url: str,
        user_agent: str,
        *,
        method: str,
        body: bytes,
        content_type: str,
    ) -> Response: ...
```
(`Response` is imported from `bsi_core.crawl` alongside the others.) After `refresh_due_recommendations`:
```python
def scan_due_alerts() -> int:
    """Scan brands due a daily alert pass; returns how many were scanned.

    SQL only, no spend, so it runs inline like the recommendation refresh.
    One brand's failure never stops the others.
    """
    with system_session() as s:
        due = s.execute(text("SELECT brand_id, org_id FROM due_alert_scans()")).all()
    done = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                brand = s.get_one(m.Brand, brand_id)
                rows = scan_alerts(
                    s,
                    org_id,
                    brand_id,
                    datetime.now(UTC),
                    deliver=brand.webhook_url is not None,
                )
                brand.alerts_scanned_at = func.now()
            log.info("brand %s: %d alerts", brand_id, len(rows))
            done += 1
        except Exception:
            log.exception("brand %s alert scan failed", brand_id)
    return done


def deliver_due_alerts(fetch: Poster = http_fetch) -> int:
    """POST each due alert to its brand's webhook; returns how many were
    delivered. The POST runs with no session open. Never raises.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT alert_id, org_id FROM due_alert_deliveries()")
        ).all()
    delivered = 0
    for alert_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                alert = s.get_one(m.Alert, alert_id)
                brand = s.get_one(m.Brand, alert.brand_id)
                url, body = brand.webhook_url, json.dumps(
                    payload(alert, brand.name), default=str
                ).encode()
            assert url is not None  # due_alert_deliveries() filtered on it
            resp = fetch(
                url,
                BROWSER_UA,
                method="POST",
                body=body,
                content_type="application/json",
            )
            with tenant_session(org_id) as s:
                alert = s.get_one(m.Alert, alert_id)
                alert.delivery_attempts += 1
                if resp.ok:
                    alert.delivered_at = func.now()
                    alert.next_attempt_at = None
                    alert.last_error = None
                    delivered += 1
                else:
                    alert.last_error = (resp.error or f"HTTP {resp.status}")[:2000]
                    n = alert.delivery_attempts
                    alert.next_attempt_at = (
                        func.now() + timedelta(seconds=BACKOFF_DELIVERY[n - 1])
                        if n < MAX_DELIVERY_ATTEMPTS
                        else None
                    )
        except Exception:
            log.exception("alert %s delivery failed", alert_id)
    return delivered
```
In `main()`, after the `queue_due_rival_crawls` block:
```python
            try:
                log.info("scanned %d brands for alerts", scan_due_alerts())
            except Exception:
                log.exception("scan_due_alerts failed")
            try:
                log.info("delivered %d alerts", deliver_due_alerts())
            except Exception:
                log.exception("deliver_due_alerts failed")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_worker.py tests/integration/test_alerts.py && uv run ruff check . && uv run mypy`
Expected: all PASS; ruff and mypy clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_worker.py && git commit -m "feat(worker): daily alert scan and webhook delivery with bounded backoff"
```

---

### Task 5: API — alerts router, brand webhook URL, isolation

**Files:**
- Create: `apps/api/bsi_api/routers/alerts.py`, `tests/integration/test_api_alerts.py`
- Modify: `apps/api/bsi_api/schemas.py` (append), `apps/api/bsi_api/routers/brands.py:45-56` (`BrandPatch`, `BrandOut`, validator), `apps/api/bsi_api/main.py` (router tuple), `tests/integration/test_isolation.py` (`other` fixture + `CASES`)
- Generated: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` via `cd apps/web && npm run gen`

**Interfaces:**
- Consumes: `alerts.scan`, `m.Alert`, `matching.is_public_hostname`.
- Produces: `GET /v1/brands/{id}/alerts?limit=` → `list[AlertOut]`; `POST /v1/brands/{id}/alerts/scan` → `ScanOut{created}`; `PATCH /v1/brands/{id}` accepts `webhook_url: str | null`; `BrandOut.webhook_url`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_api_alerts.py`:
```python
import pytest
from bsi_core import models as m
from sqlalchemy import select

from tests.integration.test_alerts import _alert, _source_scene


def test_list_is_newest_first_and_limited(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    ids = [_alert(owner, org, bid, subject_key=f"d{i}.com") for i in range(3)]
    r = client.get(f"/v1/brands/{bid}/alerts", headers=org.headers)
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == [str(i) for i in reversed(ids)]
    assert r.json()[0]["delivery_attempts"] == 0
    two = client.get(f"/v1/brands/{bid}/alerts?limit=2", headers=org.headers)
    assert len(two.json()) == 2
    assert client.get(
        f"/v1/brands/{bid}/alerts?limit=0", headers=org.headers
    ).status_code == 422


def test_scan_creates_alerts_and_reports_the_count(
    client, owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    r = client.post(f"/v1/brands/{bid}/alerts/scan", headers=org.headers)
    assert r.status_code == 200 and r.json() == {"created": 1}
    again = client.post(f"/v1/brands/{bid}/alerts/scan", headers=org.headers)
    assert again.json() == {"created": 0}
    with owner() as s:
        brand = s.get(m.Brand, bid)
        alerts = s.scalars(select(m.Alert)).all()
    assert brand.alerts_scanned_at is None  # the daily pass still runs
    assert len(alerts) == 1 and alerts[0].next_attempt_at is None


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://hooks.slack.com/services/T0/B0/x", 200),
        ("https://hooks.example.com:443/in", 200),
        ("http://hooks.example.com/in", 422),
        ("https://localhost/x", 422),
        ("https://10.0.0.1/", 422),
        ("https://user:pw@hooks.example.com/in", 422),
        ("https://hooks.example.com:8443/in", 422),
        ("ftp://hooks.example.com/in", 422),
    ],
)
def test_webhook_url_validation(client, make_org, make_brand, url, code):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": url}
    )
    assert r.status_code == code, r.text
    if code == 200:
        assert r.json()["webhook_url"] == url


def test_null_clears_the_webhook(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_url": "https://hooks.example.com/in"},
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": None}
    )
    assert r.status_code == 200 and r.json()["webhook_url"] is None
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_url is None
```
In `tests/integration/test_isolation.py`: in the `other` fixture's last `with owner() as s, s.begin():` block add
```python
        alert = m.Alert(
            org_id=b.id,
            brand_id=bid,
            type="new_source",
            subject_key="secret.com",
            title="Secret",
            window_from=datetime.now(UTC),
            window_to=datetime.now(UTC),
        )
        s.add(alert)
```
and to `CASES`:
```python
    ("GET", "/v1/brands/{b}/alerts", None),
    ("POST", "/v1/brands/{b}/alerts/scan", None),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_alerts.py -x`
Expected: FAIL with 404 on `/alerts` (route missing) or 422 on the PATCH.

- [ ] **Step 3: Implement**

Append to `apps/api/bsi_api/schemas.py`:
```python
class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    type: str
    subject_key: str
    title: str
    detail: dict[str, Any]
    window_from: datetime
    window_to: datetime
    created_at: datetime
    delivered_at: datetime | None
    delivery_attempts: int
    next_attempt_at: datetime | None
    last_error: str | None


class ScanOut(BaseModel):
    created: int
```
Create `apps/api/bsi_api/routers/alerts.py`:
```python
"""Alerts: what the daily scan found, and a manual scan."""

import uuid
from datetime import UTC, datetime

from bsi_core import models as m
from bsi_core.alerts import scan
from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import AlertOut, ScanOut

router = APIRouter(prefix="/brands/{brand_id}/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    brand_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    c: Ctx = TENANT,
) -> list[m.Alert]:
    brand_or_404(c, brand_id)
    q = (
        select(m.Alert)
        .where(m.Alert.brand_id == brand_id)
        .order_by(m.Alert.created_at.desc(), m.Alert.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.post("/scan", response_model=ScanOut)
def scan_now(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, int]:
    """Run the detectors now. SQL only, so it runs inline. It does not
    stamp alerts_scanned_at: an operator's click must not defer the daily
    pass."""
    brand = brand_or_404(c, brand_id)
    rows = scan(
        c.s,
        c.org_id,
        brand_id,
        datetime.now(UTC),
        deliver=brand.webhook_url is not None,
    )
    return {"created": len(rows)}
```
In `main.py`: import `alerts` in the routers import and add `alerts.router,` to the tuple. In `brands.py`: add `from urllib.parse import urlsplit`, then after `Host = ...`:
```python
def _webhook_url(value: str) -> str:
    """An HTTPS URL on a public host, default port, no userinfo."""
    parts = urlsplit(value)
    ok = (
        parts.scheme == "https"
        and bool(parts.hostname)
        and is_public_hostname(parts.hostname or "")
        and parts.port in (None, 443)
        and parts.username is None
    )
    if not ok:
        raise ValueError("webhook_url must be https on a public host")
    return value


WebhookUrl = Annotated[
    str, Field(max_length=2000), AfterValidator(_webhook_url)
]
```
Add `webhook_url: WebhookUrl | None = None` to `BrandPatch` and `webhook_url: str | None` to `BrandOut`.

- [ ] **Step 4: Run the tests, then regenerate the web types**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_alerts.py tests/integration/test_isolation.py tests/integration/test_api_crud.py tests/integration/test_api_typed.py && uv run mypy && cd apps/web && npm run gen && git -C /Users/vineet/Downloads/ADK/bsi-platform status --short`
Expected: all PASS; `openapi.json` and `src/lib/schema.d.ts` show as modified.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/routers/alerts.py apps/api/bsi_api/schemas.py apps/api/bsi_api/routers/brands.py apps/api/bsi_api/main.py tests/integration/test_api_alerts.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(api): list and scan alerts; validated brand webhook URL"
```

---

### Task 6: Web — Alerts tab

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`, `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx` (tab link after Competitors), `apps/web/src/lib/format.ts` (append), `apps/web/src/lib/types.ts` (append), `apps/web/src/lib/format.test.ts` (append)

**Interfaces:**
- Consumes: `Alert = S["AlertOut"]`, `Brand.webhook_url`, `GET /brands/{id}/alerts`, `POST /brands/{id}/alerts/scan`, `PATCH /brands/{id}`.
- Produces: `ALERT_KIND: Record<string, string>`, `alertNote(status)`.

- [ ] **Step 1: Write the failing vitest cases**

Append to `format.test.ts` (add `ALERT_KIND, alertNote` to the import):
```ts
test("alertNote says what the alerts forms did", () => {
  expect(alertNote("saved")).toBe("Webhook saved; new alerts are posted to it.");
  expect(alertNote("cleared")).toBe("Webhook cleared.");
  expect(alertNote("new")).toBe("Scan done; new alerts are listed below.");
  expect(alertNote("none")).toBe("Scan done; nothing new.");
  expect(alertNote(undefined)).toBeNull();
  expect(alertNote("constructor")).toBeNull();
});

test("ALERT_KIND labels every alert type", () =>
  expect(ALERT_KIND).toEqual({
    mention_drop: "Mention drop",
    competitor_shift: "Competitor shift",
    new_source: "New source",
  }));
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm test`
Expected: FAIL, `alertNote` is not exported.

- [ ] **Step 3: Implement**

Append to `format.ts`:
```ts
// Display names for alert types.
export const ALERT_KIND: Record<string, string> = {
  mention_drop: "Mention drop",
  competitor_shift: "Competitor shift",
  new_source: "New source",
};

const ALERT_NOTES: Record<string, string> = {
  saved: "Webhook saved; new alerts are posted to it.",
  cleared: "Webhook cleared.",
  new: "Scan done; new alerts are listed below.",
  none: "Scan done; nothing new.",
};

/** What the webhook or scan form did. */
export const alertNote = (status: Params[string]) => note(ALERT_NOTES, status);
```
Append to `types.ts`: `export type Alert = S["AlertOut"];`. In `layout.tsx` add `<Link href={`/b/${id}/alerts`}>Alerts</Link>` after the Competitors link.

Create `alerts/actions.ts`:
```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function setWebhook(form: FormData) {
  const id = String(form.get("brand_id"));
  const value = String(form.get("webhook_url") ?? "").trim();
  const clear = form.get("clear") === "1" || value === "";
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ webhook_url: clear ? null : value }),
  });
  redirect(`/b/${id}/alerts?queued=${clear ? "cleared" : "saved"}`);
}

export async function scanNow(form: FormData) {
  const id = String(form.get("brand_id"));
  const r = await api<{ created: number }>(`/brands/${id}/alerts/scan`, {
    method: "POST",
  });
  redirect(`/b/${id}/alerts?queued=${r.created > 0 ? "new" : "none"}`);
}
```
Create `alerts/page.tsx`:
```tsx
import Link from "next/link";
import { api } from "@/lib/api";
import { ALERT_KIND, alertNote, lastDay, type Params } from "@/lib/format";
import type { Alert, Brand } from "@/lib/types";
import { scanNow, setWebhook } from "./actions";

function delivery(a: Alert) {
  if (a.delivered_at) return "delivered";
  if (a.next_attempt_at) return `pending (${a.delivery_attempts}/5)`;
  if (a.last_error) return `failed: ${a.last_error}`;
  return "—";
}

export default async function Alerts({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [brand, alerts] = await Promise.all([
    api<Brand>(`/brands/${id}`),
    api<Alert[]>(`/brands/${id}/alerts`),
  ]);
  const ids = (d: unknown, key: string): string[] => {
    const v = (d as Record<string, unknown>)[key];
    return Array.isArray(v) ? v.map(String) : [];
  };
  return (
    <>
      <form action={setWebhook} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="webhook_url"
          pattern="https://.*"
          placeholder="https://hooks.slack.com/services/…"
          defaultValue={brand.webhook_url ?? ""}
          style={{ minWidth: 360 }}
        />
        <button className="primary">Save webhook</button>
        <button name="clear" value="1" formNoValidate>
          Clear
        </button>
      </form>
      <form action={scanNow} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <button>Scan now</button>
        {alertNote(sp.queued) && (
          <span className="muted">{alertNote(sp.queued)}</span>
        )}
      </form>
      <p className="muted">
        The worker scans every active brand daily over rolling windows; no
        alert comes from a single answer. Each new alert is posted to the
        webhook as JSON with a <code>text</code> field.
      </p>
      {alerts.length === 0 && <p className="muted">No alerts yet.</p>}
      {alerts.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Alert</th>
              <th>Window</th>
              <th>Evidence</th>
              <th>Delivery</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id}>
                <td>
                  <span className="tag">{ALERT_KIND[a.type] ?? a.type}</span>
                </td>
                <td>{a.title}</td>
                <td className="muted">
                  {a.window_from.slice(0, 10)} – {lastDay(a.window_to)}
                </td>
                <td>
                  {ids(a.detail, "prompt_ids").slice(0, 5).map((p) => (
                    <Link key={p} href={`/b/${id}/prompts/${p}`}>
                      prompt{" "}
                    </Link>
                  ))}
                  {ids(a.detail, "observation_ids").slice(0, 5).map((o) => (
                    <Link key={o} href={`/o/${o}`}>
                      answer{" "}
                    </Link>
                  ))}
                  {typeof (a.detail as Record<string, unknown>).domain ===
                    "string" && (
                    <code>{String((a.detail as Record<string, unknown>).domain)}</code>
                  )}
                </td>
                <td className="muted">{delivery(a)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
```
Check that `/b/[id]/prompts/[pid]` exists (`ls apps/web/src/app/\(app\)/b/\[id\]/prompts`); if the prompt detail route is `prompts/[pid]` use it, otherwise link to `/b/${id}/prompts` with the prompt id as `?highlight=` only if that param exists; never invent a route.

- [ ] **Step 4: Run the web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`
Expected: typecheck, lint, 17 vitest tests, build and `gen:check` all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src && git commit -m "feat(web): Alerts tab with webhook form, manual scan and evidence links"
```

---

### Task 7: Findings doc, docs index, read-only live check

**Files:**
- Create: `docs/findings-slice13.md`
- Modify: `docs/README.md` (new "Slice 13: alerts" section before "Run data and evaluation sets…")

- [ ] **Step 1: Live check (controller, read-only for dev)**

The detectors read only existing tables, so they run on dev without migration 0016 and without writing. Run them in a tenant session that is rolled back, never committed:
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && set -a && source .env && set +a && uv run python - <<'PY'
import uuid
from datetime import UTC, datetime
from bsi_core.alerts import DETECTORS
from bsi_core.db import tenant_session
ORG = uuid.UUID("de2e7f7b-3aab-45f9-843b-48bb54c1710e")
BRAND = uuid.UUID("34db213a-f484-4991-a969-c52cfa5e1c10")
class Rollback(Exception):
    """Leaving the session by exception rolls it back."""
try:
    with tenant_session(ORG) as s:
        for detect in DETECTORS:
            found = detect(s, BRAND, datetime.now(UTC))
            print(detect.__name__, len(found), [c.title for c in found])
        raise Rollback
except Rollback:
    pass
PY
```
Record what fired, as observed. Do not migrate dev, set a webhook, call the scan route, or start the worker.

- [ ] **Step 2: Write `docs/findings-slice13.md`**

Sections: 1. What was built (one paragraph per layer); 2. Live check (the scan result on Run 1, per type, with the counts); 3. Deferred / decisions (the eight rulings from the spec plus anything from the reviews); 4. Not covered by tests.

- [ ] **Step 3: Docs index**

Add to `docs/README.md`:
```markdown
## Slice 13: alerts

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice13-alerts-design.md](superpowers/specs/2026-09-25-slice13-alerts-design.md) | Design spec: three rolling-window alert types, an Alerts tab, and one webhook per brand with bounded retries. |
| [superpowers/plans/2026-09-25-slice13-alerts.md](superpowers/plans/2026-09-25-slice13-alerts.md) | Implementation plan, Tasks 1–7. |
| [findings-slice13.md](findings-slice13.md) | Results: what was built, the read-only scan on Run 1, and what is deferred. |
```

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice13.md docs/README.md && git commit -m "docs: slice 13 findings and index"
```
