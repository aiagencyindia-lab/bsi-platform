# Slice 6: Recommendations and Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop from evidence to action to measured outcome: rule-generated recommendations, accept or dismiss, tasks, and an impact measurement when a task's window closes.

**Architecture:** `bsi_core/recommend.py` turns stored observations into ranked recommendations with four deterministic SQL rules and fixed templates — no model calls. Accepting one creates a task; marking the task done opens a window that the worker closes by calling the existing `metrics.brand_deltas` on the task's prompts. Two new tenant tables (migration 0009), two routers, three pages.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, pytest. Next.js 15 (App Router, Server Components), TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-21-slice6-recommendations-and-tasks-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`. **The shell's working directory resets between commands: start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.** Branch: `slice6-recommendations-and-tasks`.
- **TDD, with evidence:** write the failing test first and **paste the failing test output into your report** before implementing.
- Backend gate, after every task:
  `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- Frontend gate, after every task that touches the API or `apps/web`: `cd apps/web && npm run gate`. It ends with **zero** warnings. A changed response model means running `npm run gen` and committing the regenerated `openapi.json` and `schema.d.ts`.
- `bsi_core/metrics.py` stays at **100% line coverage**. `mypy --strict` covers `packages/core/bsi_core`. Ruff line length is 80.
- **No model calls anywhere in this slice.** Recommendations are rules + templates.
- **Recommendation copy never promises an outcome.** A unit test scans every template for forbidden words; do not weaken it to make copy pass.
- Every tenant table gets `org_id`, ENABLE **and** FORCE row-level security, the `tenant` policy and a grant to `bsi_app`, exactly as migration `0008` does. New tables go in `TENANT_TABLES` (`tests/integration/test_rls.py`); every new id-bearing route goes in `CASES` (`tests/integration/test_isolation.py`).
- Application code gets sessions only through `tenant_session(org_id)` (routes: `c: Ctx = TENANT`). Cross-tenant listing goes through a SECURITY DEFINER function called from `system_session()`.
- Timestamps written by the app use the **database clock** (`select(func.now())`), never Python's.
- The frontend computes no statistic, interval or priority. It formats and sorts server values. Server Components and server actions only — no `"use client"`, no new dependencies.
- API response models live in `apps/api/bsi_api/schemas.py`.
- Commits: conventional subject, blank line, then exactly `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

```
packages/core/bsi_core/models.py       modify  REC_TYPES, REC_STATES, TASK_STATUSES, IMPACT_LABELS, Recommendation, Task
packages/core/bsi_core/config.py       modify  impact_window_days
migrations/versions/0009_recommendations_and_tasks.py   create
packages/core/bsi_core/recommend.py    create  rules, templates, generate(), refresh()
packages/core/bsi_core/impact.py       create  measure(), close_window()
apps/workers/bsi_workers/worker.py     modify  close_due_impact_windows(), main() loop
apps/api/bsi_api/schemas.py            modify  RecommendationOut, TaskOut, DismissIn, TaskPatch
apps/api/bsi_api/routers/recommendations.py   create
apps/api/bsi_api/routers/tasks.py      create
apps/api/bsi_api/main.py               modify  register both routers
apps/web/src/app/(app)/b/[id]/recommendations/{page.tsx,actions.ts}   create
apps/web/src/app/(app)/b/[id]/tasks/{page.tsx,actions.ts}             create
apps/web/src/app/(app)/b/[id]/{layout.tsx,page.tsx}                  modify  tabs, top 3
apps/web/src/lib/types.ts              modify
docs/findings-slice6.md                create
```

---

### Task 1: Models, migration 0009, and the window setting

**Files:**
- Modify: `packages/core/bsi_core/models.py`, `packages/core/bsi_core/config.py`
- Create: `migrations/versions/0009_recommendations_and_tasks.py`
- Test: `tests/integration/test_rls.py`, `tests/integration/test_constraints.py` (append to each)

**Interfaces:**
- Produces: `m.REC_TYPES`, `m.REC_STATES`, `m.TASK_STATUSES`, `m.IMPACT_LABELS` (tuples of str); `m.Recommendation` (`brand_id, type, subject_key, status, dismiss_reason, title, body, evidence: dict, reach, pressure, feasibility, priority: float`); `m.Task` (`brand_id, recommendation_id, title, owner, due_date: date|None, status, notes, prompt_ids: list[UUID], done_at, window_days, impact_label, impact: dict|None`); SQL function `due_impact_windows() RETURNS TABLE(task_id uuid, org_id uuid)`; `get_settings().impact_window_days == 14`.

- [ ] **Step 1: Failing tests.**

In `tests/integration/test_rls.py`: add `"recommendation"` and `"task"` to `TENANT_TABLES`, and at the end of the `org_b` fixture, just before `return b`, add:

```python
    with owner() as s, s.begin():
        rec = m.Recommendation(
            org_id=b.id,
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
        s.add(
            m.Task(
                org_id=b.id, brand_id=bid, recommendation_id=rec.id, title="t"
            )
        )
```

Append to `tests/integration/test_constraints.py` (add `import re` to its imports):

```python
@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("ck_recommendation_type", m.REC_TYPES),
        ("ck_recommendation_status", m.REC_STATES),
        ("ck_task_status", m.TASK_STATUSES),
        ("ck_task_impact_label", m.IMPACT_LABELS),
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
        s.add(m.Task(org_id=org.id, brand_id=bid, recommendation_id=rid, title="a"))
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(m.Task(org_id=org.id, brand_id=bid, recommendation_id=rid, title="b"))
```

Run: `uv run pytest -q tests/integration/test_rls.py tests/integration/test_constraints.py`. Expected: `AttributeError: module 'bsi_core.models' has no attribute 'REC_TYPES'` (collection fails).

- [ ] **Step 2: Models.** In `models.py`: add `date` to the `datetime` import (`from datetime import date, datetime`) and `Uuid` to the `sqlalchemy` import list. Beside `REC_STATUSES`:

```python
REC_TYPES = (
    "pursue_citation_source",
    "create_content",
    "add_competitor",
    "sample_more",
)
REC_STATES = ("open", "accepted", "dismissed")
TASK_STATUSES = ("open", "in_progress", "done", "impact_measured")
IMPACT_LABELS = (
    "improved",
    "no_change",
    "declined",
    "insufficient_data",
    # brand_deltas refuses windows with mixed pipeline versions; that is
    # not a shortage of data and must not be reported as one.
    "not_comparable",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"
```

After `RecLabel`:

```python
class Recommendation(Tenant, Base):
    """A suggested action, generated by rules from a brand's evidence."""

    __tablename__ = "recommendation"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    # What it is about - a domain, a prompt id, a competitor id. With the
    # brand and type it is the identity that regeneration upserts on.
    subject_key: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="open")
    dismiss_reason: Mapped[str | None]
    title: Mapped[str]
    body: Mapped[str]
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    reach: Mapped[float]
    pressure: Mapped[float]
    feasibility: Mapped[float]
    priority: Mapped[float]
    __table_args__ = (
        UniqueConstraint("brand_id", "type", "subject_key"),
        CheckConstraint(_in("type", REC_TYPES), name="ck_recommendation_type"),
        CheckConstraint(
            _in("status", REC_STATES), name="ck_recommendation_status"
        ),
    )


class Task(Tenant, Base):
    """An accepted recommendation, followed through to a measured outcome."""

    __tablename__ = "task"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendation.id")
    )
    title: Mapped[str]
    owner: Mapped[str | None]  # free text: there are no user accounts yet
    due_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="open")
    notes: Mapped[str] = mapped_column(server_default="")
    # The prompts the task is meant to move; empty means the whole brand.
    prompt_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default="{}"
    )
    done_at: Mapped[datetime | None] = mapped_column(TSZ)
    window_days: Mapped[int | None]
    impact_label: Mapped[str | None]
    impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("recommendation_id"),
        CheckConstraint(_in("status", TASK_STATUSES), name="ck_task_status"),
        CheckConstraint(
            "impact_label IS NULL OR " + _in("impact_label", IMPACT_LABELS),
            name="ck_task_impact_label",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress') "
            "OR (done_at IS NOT NULL AND window_days IS NOT NULL)",
            name="ck_task_done_has_window",
        ),
    )
```

`config.py`, in `Settings` after `obs_cost_estimate_micros`:

```python
    # Slice 6: days either side of a task's done_at that impact compares.
    # Copied onto the task when it is marked done, so changing it never
    # moves a window that is already open.
    impact_window_days: int = 14
```

- [ ] **Step 3: Migration** — `migrations/versions/0009_recommendations_and_tasks.py`. Migrations are frozen history: spell the value lists out, never import the constants.

```python
"""recommendation and task tables, their RLS, and due_impact_windows()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def _row() -> list[sa.Column]:
    return [
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
    ]


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
    op.create_table(
        "recommendation",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), server_default="open", nullable=False
        ),
        sa.Column("dismiss_reason", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("reach", sa.Float(), nullable=False),
        sa.Column("pressure", sa.Float(), nullable=False),
        sa.Column("feasibility", sa.Float(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        *_row(),
        sa.CheckConstraint(
            "type IN ('pursue_citation_source', 'create_content', "
            "'add_competitor', 'sample_more')",
            name="ck_recommendation_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'dismissed')",
            name="ck_recommendation_status",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "type", "subject_key"),
    )
    _protect("recommendation")

    op.create_table(
        "task",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status", sa.String(), server_default="open", nullable=False
        ),
        sa.Column("notes", sa.String(), server_default="", nullable=False),
        sa.Column(
            "prompt_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("impact_label", sa.String(), nullable=True),
        sa.Column(
            "impact", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        *_row(),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'done', 'impact_measured')",
            name="ck_task_status",
        ),
        sa.CheckConstraint(
            "impact_label IS NULL OR impact_label IN ('improved', "
            "'no_change', 'declined', 'insufficient_data', 'not_comparable')",
            name="ck_task_impact_label",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress') "
            "OR (done_at IS NOT NULL AND window_days IS NOT NULL)",
            name="ck_task_done_has_window",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id"),
    )
    _protect("task")

    # Runs as its owner, like due_schedules() in 0006, so the worker can
    # find closed windows across tenants without a tenant setting.
    op.execute("""
        CREATE FUNCTION due_impact_windows()
        RETURNS TABLE(task_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT t.id, t.org_id FROM task t
          WHERE t.status = 'done'
            AND t.done_at + make_interval(days => t.window_days) <= now()
          ORDER BY t.done_at
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_impact_windows() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_impact_windows() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_impact_windows()")
    op.drop_table("task")
    op.drop_table("recommendation")
```

Run: `uv run alembic upgrade head && uv run alembic check`. Expected: `No new upgrade operations detected.` If `alembic check` reports a difference, fix the migration to match the model, not the other way round, unless the model contradicts the spec.

- [ ] **Step 4: Downgrade round trip on the test database.** Prove `downgrade()` works rather than trusting it:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && export DATABASE_URL="postgresql+psycopg://bsi_app:app@localhost:5433/bsi_test" OWNER_DATABASE_URL="postgresql+psycopg://bsi_owner:owner@localhost:5433/bsi_test" && uv run alembic upgrade head && uv run alembic downgrade 0008 && uv run alembic upgrade head && uv run alembic check
```

Expected: all four succeed and the last prints `No new upgrade operations detected.` Paste the output.

- [ ] **Step 5: Tests, backend gate, commit** — `feat(core): recommendation and task tables`

---

### Task 2: The rules — `bsi_core/recommend.py`

**Files:**
- Create: `packages/core/bsi_core/recommend.py`
- Test: `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py` (create both)

**Interfaces:**
- Consumes: `m.Recommendation` (Task 1); `metrics.prompt_metrics`, `metrics.Filters`; `suggest.ANSWERS` (= 3).
- Produces: `Candidate` (dataclass: `type, subject_key, title, body, evidence: dict[str, Any], reach: float, pressure: float`; properties `feasibility`, `priority`); `generate(s, brand_id) -> list[Candidate]` (priority descending); `refresh(s, org_id, brand_id) -> int` (upserts, returns the candidate count); `FEASIBILITY`; copy functions `citation_copy`, `content_copy`, `competitor_copy`, `sample_copy`, each returning `(title, body)`; `names(list[str]) -> str`.

The four rules, and exactly where each fires:

| Type | Fires when | subject_key | reach | pressure |
|---|---|---|---|---|
| `pursue_citation_source` | a non-owned domain is cited in ≥ 3 done answers on active prompts that do not mention the brand | the domain | prompts citing it / active prompts | share of those answers naming an active rival |
| `create_content` | the brand is absent from at least half a prompt's done answers and the most common absence reason among them is `competitor_dominance` or `not_retrieved` | prompt id | 1 / active prompts | share of the absent answers naming an active rival |
| `add_competitor` | a `suggested` competitor has `evidence >= 2` | competitor id | 1.0 | `min(evidence / ANSWERS, 1)` |
| `sample_more` | an active prompt is not separated and `needs_samples - n` is between 1 and 10 | prompt id | 1 / active prompts | `abs(spread)` |

`priority = round(reach * pressure * feasibility, 4)`.

- [ ] **Step 1: Failing tests.**

```python
# tests/unit/test_recommend_copy.py
import pytest
from bsi_core.recommend import (
    citation_copy,
    competitor_copy,
    content_copy,
    names,
    sample_copy,
)

# A template may describe evidence and name the metric to watch; it may
# never promise what will happen.
FORBIDDEN = (
    "guarantee",
    "will rank",
    "will appear",
    "will be recommended",
    "ensure",
    "boost",
    "#1",
    "top spot",
    "dominat",
    "certain",
)

CASES = [
    citation_copy("Nike", "forbes.com", 4, ["Adidas", "Puma", "Bata", "Crocs"]),
    citation_copy("Nike", "forbes.com", 3, []),
    content_copy("Nike", "best shoes", 4, 4, "competitor_dominance", ["Adidas"]),
    content_copy("Nike", "best shoes", 3, 5, "competitor_dominance", []),
    content_copy("Nike", "best shoes", 3, 4, "not_retrieved", []),
    competitor_copy("Puma", 2),
    sample_copy("Nike", "best shoes", 3, 4, "Adidas"),
    sample_copy("Nike", "best shoes", 3, 7, "Adidas"),
]


@pytest.mark.parametrize("copy", CASES)
def test_copy_never_promises_an_outcome(copy):
    text = " ".join(copy).lower()
    for word in FORBIDDEN:
        assert word not in text, word


@pytest.mark.parametrize("copy", CASES)
def test_copy_names_the_metric_to_watch(copy):
    assert "Metric to watch:" in copy[1]


def test_rival_lists_read_naturally():
    assert names([]) == ""
    assert names(["A"]) == "A"
    assert names(["A", "B"]) == "A and B"
    assert names(["A", "B", "C", "D"]) == "A, B and C"


def test_sample_copy_counts_the_shortfall():
    assert sample_copy("N", "p", 3, 4, "R")[0].startswith(
        "Take 1 more sample of"
    )
    assert sample_copy("N", "p", 3, 7, "R")[0].startswith(
        "Take 4 more samples of"
    )
```

```python
# tests/integration/test_recommend.py
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.recommend import generate, refresh
from sqlalchemy import select


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

    dominated  brand 0/4, Adidas 4/4, forbes.com cited in all four
               -> create_content, pursue_citation_source (forbes.com);
                  separated at n=4, so no sample_more
    present    brand 3/4, blog.com cited in all four -> nothing: absent
               only once; blog.com cited in one brand-absent answer;
               needs 16 samples, a shortfall of 12, just past the 10
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
        adidas = m.Competitor(org_id=org.id, brand_id=bid, name="Adidas")
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

    lost = (False, True, "competitor_dominance", [("forbes.com", False)])
    ids.dominated = prompt("dominated", [lost] * 4)
    blog = [("blog.com", False)]
    ids.present = prompt(
        "present",
        [(True, False, None, blog)] * 3
        + [(False, True, "competitor_dominance", blog)],
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
    assert set(found(world)) == {
        ("pursue_citation_source", "forbes.com"),
        ("create_content", str(world.dominated)),
        ("add_competitor", str(world.puma)),
        ("sample_more", str(world.close)),
    }


def test_citation_evidence_and_weights(world):
    c = found(world)[("pursue_citation_source", "forbes.com")]
    assert len(c.evidence["observation_ids"]) == 4
    assert c.evidence["prompt_ids"] == [str(world.dominated)]
    assert c.evidence["rivals"] == ["Adidas"]
    assert (c.reach, c.pressure, c.feasibility, c.priority) == (
        0.2,
        1.0,
        0.3,
        0.06,
    )


def test_content_names_the_reason_and_the_rivals(world):
    c = found(world)[("create_content", str(world.dominated))]
    assert c.evidence["reason"] == "competitor_dominance"
    assert (c.evidence["absent"], c.evidence["n"]) == (4, 4)
    assert "Adidas" in c.body
    assert c.priority == 0.08


def test_competitor_and_sampling_weights(world):
    all_ = found(world)
    puma = all_[("add_competitor", str(world.puma))]
    assert (puma.reach, round(puma.pressure, 4), puma.priority) == (
        1.0,
        0.6667,
        0.6,
    )
    sample = all_[("sample_more", str(world.close))]
    assert (sample.evidence["n"], sample.evidence["needs_samples"]) == (3, 4)
    assert (sample.pressure, sample.priority) == (1.0, 0.2)


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
        before = {r.subject_key: r.id for r in s.scalars(select(m.Recommendation))}
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


def test_refresh_drops_open_rows_the_evidence_no_longer_supports(
    owner, world
):
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    with owner() as s, s.begin():
        s.get(m.Competitor, world.puma).status = "active"
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        types = {r.type for r in s.scalars(select(m.Recommendation))}
    assert "add_competitor" not in types
```

Run: `uv run pytest -q tests/unit/test_recommend_copy.py tests/integration/test_recommend.py`. Expected: `ModuleNotFoundError: No module named 'bsi_core.recommend'`.

- [ ] **Step 2: Implement** `packages/core/bsi_core/recommend.py`:

```python
"""Recommendations: deterministic rules over a brand's stored evidence.

Rules decide what to recommend and templates decide how it reads. No model
is called, so nothing here can drift into promising an outcome; the
templates are tested for that directly.

Priority is reach x pressure x feasibility, every part stored beside the
product so the weighting is visible (PRD F12):

- reach: the share of the brand's active prompts the action touches;
- pressure: what is at stake there - the share of the relevant answers
  naming a rival, a suggestion's evidence, or the size of a gap waiting
  to be confirmed, depending on the type;
- feasibility: how cheaply the operator can act, per type, below.
"""

import uuid
from collections import Counter
from dataclasses import dataclass
from itertools import groupby
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import models as m
from .metrics import Filters, prompt_metrics
from .suggest import ANSWERS

# Confirming a competitor or scheduling samples takes minutes; content
# takes weeks; outreach takes weeks and depends on someone else.
FEASIBILITY = {
    "add_competitor": 0.9,
    "sample_more": 1.0,
    "create_content": 0.4,
    "pursue_citation_source": 0.3,
}
MIN_CITING_ANSWERS = 3
MIN_COMPETITOR_EVIDENCE = 2
# More samples than this is a change to sampling, not a task.
SAMPLE_MORE_WITHIN = 10
CONTENT_REASONS = ("competitor_dominance", "not_retrieved")


@dataclass
class Candidate:
    type: str
    subject_key: str
    title: str
    body: str
    evidence: dict[str, Any]
    reach: float
    pressure: float

    @property
    def feasibility(self) -> float:
        return FEASIBILITY[self.type]

    @property
    def priority(self) -> float:
        return round(self.reach * self.pressure * self.feasibility, 4)


def names(items: list[str]) -> str:
    """The first three, joined as a sentence would."""
    top = items[:3]
    if len(top) < 2:
        return "".join(top)
    return ", ".join(top[:-1]) + " and " + top[-1]


def citation_copy(
    brand: str, domain: str, k: int, rivals: list[str]
) -> tuple[str, str]:
    named = f" Those answers name {names(rivals)} instead." if rivals else ""
    return (
        f"Earn coverage on {domain}",
        f"{domain} is cited in {k} answers that do not mention {brand}."
        f"{named} Answer engines draw on it for these prompts. "
        f"Metric to watch: {brand}'s mention rate on the prompts that "
        "cite it.",
    )


def content_copy(
    brand: str,
    prompt: str,
    absent: int,
    n: int,
    reason: str,
    rivals: list[str],
) -> tuple[str, str]:
    if reason == "not_retrieved":
        why = (
            f"the extractor reports {brand} was not retrieved at all, which "
            "points at missing or hard-to-find content rather than "
            "competition"
        )
    else:
        led = f" ({names(rivals)})" if rivals else ""
        why = f"the extractor attributes this to answers led by rivals{led}"
    return (
        f"Publish content that answers “{prompt}”",
        f"{brand} is absent from {absent} of {n} answers to this prompt; "
        f"{why}. Metric to watch: {brand}'s mention rate on this prompt.",
    )


def competitor_copy(name: str, evidence: int) -> tuple[str, str]:
    return (
        f"Confirm {name} as a competitor",
        f"{name} appeared in {evidence} of the {ANSWERS} answers used to "
        "suggest competitors but is not yet measured: until it is "
        "confirmed it is left out of share of voice and every rival rate. "
        "Metric to watch: share of voice, which then includes it.",
    )


def sample_copy(
    brand: str, prompt: str, n: int, needs: int, rival: str
) -> tuple[str, str]:
    more = needs - n
    return (
        f"Take {more} more sample{'s' if more != 1 else ''} of “{prompt}”",
        f"At n={n} this prompt cannot yet tell {brand} apart from {rival}; "
        f"if the observed rates hold, it can at about n={needs}. This is a "
        "projection from current rates and moves as they do. Metric to "
        "watch: whether this prompt separates.",
    )


_RIVALS = (
    "FROM mention mn JOIN competitor cp ON cp.id = mn.entity_id "
    "WHERE mn.observation_id = ANY(:obs) AND mn.entity_type = 'competitor' "
    "AND cp.status = 'active'"
)


def _rivals(s: Session, obs: list[uuid.UUID]) -> tuple[list[str], float]:
    """Active rivals named in these answers, most often first, and the
    share of the answers that name at least one."""
    rows = s.execute(
        text(
            "SELECT cp.name, count(DISTINCT mn.observation_id) "
            f"{_RIVALS} GROUP BY cp.name ORDER BY 2 DESC, 1"
        ),
        {"obs": obs},
    ).all()
    named = s.scalar(
        text(f"SELECT count(DISTINCT mn.observation_id) {_RIVALS}"),
        {"obs": obs},
    )
    return [r[0] for r in rows], (named or 0) / len(obs)


def _citations(
    s: Session, brand_id: uuid.UUID, brand: str, active: int
) -> list[Candidate]:
    rows = s.execute(
        text(
            "SELECT c.domain, array_agg(DISTINCT o.id) AS obs, "
            "array_agg(DISTINCT o.prompt_id) AS prompts "
            "FROM citation c "
            "JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND p.status = 'active' AND NOT c.is_brand_owned "
            "AND NOT EXISTS (SELECT 1 FROM mention mn "
            "  WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') "
            "GROUP BY c.domain HAVING count(DISTINCT o.id) >= :min "
            "ORDER BY count(DISTINCT o.id) DESC, c.domain"
        ),
        {"brand": brand_id, "min": MIN_CITING_ANSWERS},
    ).all()
    out = []
    for row in rows:
        obs = sorted(row.obs, key=str)
        rivals, pressure = _rivals(s, obs)
        title, body = citation_copy(brand, row.domain, len(obs), rivals)
        out.append(
            Candidate(
                "pursue_citation_source",
                row.domain,
                title,
                body,
                {
                    "domain": row.domain,
                    "observation_ids": [str(o) for o in obs],
                    "prompt_ids": sorted(str(p) for p in row.prompts),
                    "rivals": rivals,
                },
                len(row.prompts) / active,
                pressure,
            )
        )
    return out


def _content(
    s: Session, brand_id: uuid.UUID, brand: str, active: int
) -> list[Candidate]:
    rows = s.execute(
        text(
            "SELECT o.prompt_id, p.text, o.id, "
            "EXISTS (SELECT 1 FROM mention mn "
            "  WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') AS present, "
            "e.absence_reason "
            "FROM observation o "
            "JOIN prompt p ON p.id = o.prompt_id "
            "LEFT JOIN extraction e ON e.observation_id = o.id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND p.status = 'active' "
            "ORDER BY p.text, o.prompt_id, o.requested_at, o.id"
        ),
        {"brand": brand_id},
    ).all()
    out = []
    for pid, group in groupby(rows, key=lambda r: r.prompt_id):
        answers = list(group)
        absent = [r for r in answers if not r.present]
        if not absent or len(absent) * 2 < len(answers):
            continue
        reasons = Counter(r.absence_reason for r in absent if r.absence_reason)
        if not reasons:
            continue
        reason = reasons.most_common(1)[0][0]
        if reason not in CONTENT_REASONS:
            continue
        obs = [r.id for r in absent]
        rivals, pressure = _rivals(s, obs)
        title, body = content_copy(
            brand, answers[0].text, len(absent), len(answers), reason, rivals
        )
        out.append(
            Candidate(
                "create_content",
                str(pid),
                title,
                body,
                {
                    "prompt_ids": [str(pid)],
                    "observation_ids": [str(o) for o in obs],
                    "reason": reason,
                    "absent": len(absent),
                    "n": len(answers),
                },
                1 / active,
                pressure,
            )
        )
    return out


def _competitors(s: Session, brand_id: uuid.UUID) -> list[Candidate]:
    rows = s.scalars(
        select(m.Competitor)
        .where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "suggested",
            m.Competitor.evidence >= MIN_COMPETITOR_EVIDENCE,
        )
        .order_by(m.Competitor.evidence.desc(), m.Competitor.name)
    ).all()
    out = []
    for c in rows:
        evidence = c.evidence or 0
        title, body = competitor_copy(c.name, evidence)
        out.append(
            Candidate(
                "add_competitor",
                str(c.id),
                title,
                body,
                {"competitor_id": str(c.id), "evidence": evidence},
                # Confirming a rival changes share of voice on every prompt.
                1.0,
                min(evidence / ANSWERS, 1.0),
            )
        )
    return out


def _sampling(
    s: Session, brand_id: uuid.UUID, brand: str, active: set[uuid.UUID]
) -> list[Candidate]:
    out = []
    for row in prompt_metrics(s, brand_id, Filters()):
        needs, n, top = row["needs_samples"], row["n"], row["top_competitor"]
        if (
            row["prompt_id"] not in active
            or row["separated"]
            or needs is None
            or top is None
            or not 0 < needs - n <= SAMPLE_MORE_WITHIN
        ):
            continue
        title, body = sample_copy(brand, row["text"], n, needs, top["name"])
        out.append(
            Candidate(
                "sample_more",
                str(row["prompt_id"]),
                title,
                body,
                {
                    "prompt_ids": [str(row["prompt_id"])],
                    "n": n,
                    "needs_samples": needs,
                },
                1 / len(active),
                abs(row["spread"] or 0.0),
            )
        )
    return out


def generate(s: Session, brand_id: uuid.UUID) -> list[Candidate]:
    """Every recommendation the brand's evidence supports, best first.

    Call in the brand's tenant session; row-level security scopes every
    query here.
    """
    brand = s.get_one(m.Brand, brand_id).name
    active = set(
        s.scalars(
            select(m.Prompt.id).where(
                m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
            )
        )
    )
    found = _competitors(s, brand_id)
    if active:
        found += [
            *_citations(s, brand_id, brand, len(active)),
            *_content(s, brand_id, brand, len(active)),
            *_sampling(s, brand_id, brand, active),
        ]
    return sorted(found, key=lambda c: (-c.priority, c.type, c.subject_key))


_REFRESHED = (
    "title",
    "body",
    "evidence",
    "reach",
    "pressure",
    "feasibility",
    "priority",
)


def refresh(s: Session, org_id: uuid.UUID, brand_id: uuid.UUID) -> int:
    """Store the brand's recommendations; returns how many the evidence
    supports.

    Open rows are refreshed in place. Accepted and dismissed rows are left
    exactly as they are: regeneration never undoes a decision. Open rows
    the evidence no longer supports are removed.
    """
    found = generate(s, brand_id)
    if found:
        stmt = insert(m.Recommendation).values(
            [
                {
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "type": c.type,
                    "subject_key": c.subject_key,
                    "title": c.title,
                    "body": c.body,
                    "evidence": c.evidence,
                    "reach": c.reach,
                    "pressure": c.pressure,
                    "feasibility": c.feasibility,
                    "priority": c.priority,
                }
                for c in found
            ]
        )
        s.execute(
            stmt.on_conflict_do_update(
                index_elements=["brand_id", "type", "subject_key"],
                set_={k: stmt.excluded[k] for k in _REFRESHED},
                where=m.Recommendation.status == "open",
            )
        )
    keep = {(c.type, c.subject_key) for c in found}
    # ponytail: loads the brand's open rows to find stale ones; fine for
    # hundreds, a NOT IN over the keys once there are thousands.
    for rec in s.scalars(
        select(m.Recommendation).where(
            m.Recommendation.brand_id == brand_id,
            m.Recommendation.status == "open",
        )
    ):
        if (rec.type, rec.subject_key) not in keep:
            s.delete(rec)
    return len(found)
```

If `mypy --strict` objects to attribute access on SQL result rows (`row.obs`, `r.present`), index them positionally instead (`row[1]`) rather than adding casts or `# type: ignore`.

- [ ] **Step 3: Run the tests; all pass.** If a weight assertion fails, recompute the expected value by hand from the fixture docstring before touching the code — the expectations were derived from the rules above, and a mismatch means one of them is wrong.
- [ ] **Step 4: Backend gate, commit** — `feat(core): rule-generated recommendations`

---

### Task 3: Impact — `bsi_core/impact.py` and the worker

**Files:**
- Create: `packages/core/bsi_core/impact.py`
- Modify: `apps/workers/bsi_workers/worker.py`
- Test: `tests/integration/test_impact.py` (create), `tests/integration/test_worker.py` (append)

**Interfaces:**
- Consumes: `m.Task` (Task 1); `metrics.brand_deltas(s, brand_id, f, days, to)`, `metrics.Filters`.
- Produces: `impact.LABELS`; `impact.measure(s, task) -> tuple[str, dict[str, Any]]`; `impact.close_window(org_id, task_id) -> str | None`; `worker.close_due_impact_windows() -> int`.

Windows: with `w = window_days` and `to = done_at + w`, `brand_deltas(..., days=w, to=to)` compares `[done_at − w, done_at)` with `[done_at, done_at + w)`. The metric is the mention rate on the task's prompts (the whole brand when `prompt_ids` is empty).

- [ ] **Step 1: Failing tests.**

```python
# tests/integration/test_impact.py
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


def test_measure_counts_only_the_tasks_prompts(
    owner, base, make_observation
):
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
```

Append to `tests/integration/test_worker.py` (its imports already include `worker`, `datetime`, `UTC`, `timedelta`, `select`, `m`); add `close_due_impact_windows` to the `from bsi_workers.worker import (...)` list:

```python
def _due_and_not_due(owner, org, bid):
    now = datetime.now(UTC)
    with owner() as s, s.begin():
        for title, ago in (("due", 15), ("open window", 1)):
            s.add(
                m.Task(
                    org_id=org.id,
                    brand_id=bid,
                    title=title,
                    status="done",
                    done_at=now - timedelta(days=ago),
                    window_days=14,
                )
            )


def test_close_due_impact_windows_serves_every_tenant(
    owner, make_org, make_brand
):
    for name in ("A", "B"):
        org = make_org(name)
        _due_and_not_due(owner, org, make_brand(org))
    assert close_due_impact_windows() == 2
    with owner() as s:
        rows = s.scalars(select(m.Task).order_by(m.Task.title)).all()
    # No observations anywhere, so each measured task honestly reports it.
    assert [(t.title, t.impact_label) for t in rows] == [
        ("due", "insufficient_data"),
        ("due", "insufficient_data"),
        ("open window", None),
        ("open window", None),
    ]


def test_one_failing_impact_window_does_not_block_the_rest(
    monkeypatch, owner, make_org, make_brand
):
    for name in ("A", "B"):
        org = make_org(name)
        _due_and_not_due(owner, org, make_brand(org))
    real, calls = worker.close_window, []

    def flaky(org_id, task_id):
        calls.append(task_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(org_id, task_id)

    monkeypatch.setattr(worker, "close_window", flaky)
    assert close_due_impact_windows() == 1
    assert len(calls) == 2
```

Run both files. Expected: `ModuleNotFoundError: No module named 'bsi_core.impact'`.

- [ ] **Step 2: Implement** `packages/core/bsi_core/impact.py`:

```python
"""Impact: did a finished task's prompts move?

Marking a task done opens a window on its prompts. When it closes, the
mention rate over the window_days before done_at is compared with the
window_days after, through brand_deltas - the same Newcombe interval and
the same refusal of mixed pipeline versions the dashboard uses. What it
finds is an association: anything else that changed in those weeks is
mixed in.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .db import tenant_session
from .metrics import Filters, brand_deltas

LABELS = {
    "increase": "improved",
    "decrease": "declined",
    "no significant change": "no_change",
    "insufficient data": "insufficient_data",
}


def measure(s: Session, task: m.Task) -> tuple[str, dict[str, Any]]:
    """The impact label and what it rests on. Call in the tenant session."""
    if task.done_at is None or task.window_days is None:
        raise ValueError("a task has a window only once it is done")
    days = task.window_days
    out = brand_deltas(
        s,
        task.brand_id,
        Filters(prompt_ids=list(task.prompt_ids) or None),
        days,
        task.done_at + timedelta(days=days),
    )
    payload: dict[str, Any] = {"metric": "mention_rate", "window_days": days}
    for side in ("before", "after"):
        payload[side] = {
            "from": out[side]["from"].isoformat(),
            "to": out[side]["to"].isoformat(),
            **out[side]["mention_rate"],
        }
    if not out["comparable"]:
        return "not_comparable", {**payload, "delta": None, "reason": out["reason"]}
    delta = out["deltas"]["mention_rate"]
    return LABELS[delta["label"]], {**payload, "delta": delta, "reason": None}


def close_window(org_id: uuid.UUID, task_id: uuid.UUID) -> str | None:
    """Measure one task whose window has closed; returns its label, or
    None if it was not due. Locks the row, so two workers cannot both
    measure it."""
    with tenant_session(org_id) as s:
        task = s.get(m.Task, task_id, with_for_update=True)
        if (
            task is None
            or task.status != "done"
            or task.done_at is None
            or task.window_days is None
        ):
            return None
        now = s.scalar(select(func.now()))
        if task.done_at + timedelta(days=task.window_days) > now:
            return None
        label, payload = measure(s, task)
        task.impact_label, task.impact = label, payload
        task.status = "impact_measured"
        return label
```

In `worker.py`: add `from bsi_core.impact import close_window` to the imports, add this after `run_due_schedules`, and call it in `main()`'s schedule-check block right after the `run_due_schedules()` `try`:

```python
def close_due_impact_windows() -> int:
    """Measure every task whose window has closed; returns how many.

    One task's failure never stops the others, as with schedules.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT task_id, org_id FROM due_impact_windows()")
        ).all()
    closed = 0
    for task_id, org_id in due:
        try:
            label = close_window(org_id, task_id)
            log.info("task %s impact: %s", task_id, label)
            closed += label is not None
        except Exception:
            log.exception("task %s impact failed", task_id)
    return closed
```

```python
            try:
                log.info("closed %d impact windows", close_due_impact_windows())
            except Exception:
                log.exception("close_due_impact_windows failed")
```

- [ ] **Step 3: Tests pass; backend gate; commit** — `feat: measure a finished task's impact`

---

### Task 4: The API

**Files:**
- Create: `apps/api/bsi_api/routers/recommendations.py`, `apps/api/bsi_api/routers/tasks.py`
- Modify: `apps/api/bsi_api/schemas.py`, `apps/api/bsi_api/main.py`, `tests/integration/test_isolation.py`
- Test: `tests/integration/test_api_recommendations.py` (create)

**Interfaces:**
- Consumes: `recommend.refresh` (Task 2); `m.Recommendation`, `m.Task`; `get_settings().impact_window_days`.
- Produces: `POST /v1/brands/{id}/recommendations/generate` → `list[RecommendationOut]` (open, priority desc); `GET /v1/brands/{id}/recommendations?status=open|accepted|dismissed`; `POST …/recommendations/{rid}/accept` → 201 `TaskOut` (409 if not open); `POST …/recommendations/{rid}/dismiss` body `{reason}` → `RecommendationOut` (422 on a blank reason, 409 if not open); `GET /v1/brands/{id}/tasks` → `list[TaskOut]`; `PATCH /v1/brands/{id}/tasks/{tid}` → `TaskOut`.

Status rules for PATCH: a person may move `open ⇄ in_progress` and either to `done`; setting the current status again is a no-op; nothing leaves `done`; `impact_measured` is set only by the worker. Moving to `done` stamps `done_at` from the database clock and `window_days` from settings.

- [ ] **Step 1: Failing tests.**

```python
# tests/integration/test_api_recommendations.py
import pytest
from bsi_core import models as m


@pytest.fixture
def scene(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Puma",
                status="suggested",
                evidence=3,
            )
        )
    return org, bid


def generate(client, org, bid):
    return client.post(
        f"/v1/brands/{bid}/recommendations/generate", headers=org.headers
    )


def test_generate_stores_and_lists_open_recommendations(client, scene):
    org, bid = scene
    r = generate(client, org, bid)
    assert r.status_code == 200
    (rec,) = r.json()
    assert (rec["type"], rec["status"]) == ("add_competitor", "open")
    assert rec["priority"] == pytest.approx(
        rec["reach"] * rec["pressure"] * rec["feasibility"], abs=1e-4
    )
    listed = client.get(
        f"/v1/brands/{bid}/recommendations", headers=org.headers
    )
    assert listed.json() == r.json()


def test_accept_creates_exactly_one_task(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    url = f"/v1/brands/{bid}/recommendations/{rec['id']}/accept"
    t = client.post(url, headers=org.headers)
    assert t.status_code == 201
    body = t.json()
    assert (body["title"], body["status"], body["recommendation_id"]) == (
        rec["title"],
        "open",
        rec["id"],
    )
    assert client.post(url, headers=org.headers).status_code == 409
    accepted = client.get(
        f"/v1/brands/{bid}/recommendations?status=accepted",
        headers=org.headers,
    ).json()
    assert [r["id"] for r in accepted] == [rec["id"]]


def test_accept_carries_the_evidence_prompts(
    client, owner, make_observation, scene
):
    org, bid = scene
    oid = make_observation(org, bid)
    with owner() as s, s.begin():
        pid = s.get(m.Observation, oid).prompt_id
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type="sample_more",
            subject_key=str(pid),
            title="t",
            body="b",
            evidence={"prompt_ids": [str(pid)]},
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        rid = rec.id
    t = client.post(
        f"/v1/brands/{bid}/recommendations/{rid}/accept", headers=org.headers
    ).json()
    assert t["prompt_ids"] == [str(pid)]


def test_dismissing_needs_a_reason_and_sticks(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    url = f"/v1/brands/{bid}/recommendations/{rec['id']}/dismiss"
    assert client.post(url, json={}, headers=org.headers).status_code == 422
    blank = client.post(url, json={"reason": "   "}, headers=org.headers)
    assert blank.status_code == 422
    ok = client.post(
        url, json={"reason": "tracked elsewhere"}, headers=org.headers
    ).json()
    assert (ok["status"], ok["dismiss_reason"]) == (
        "dismissed",
        "tracked elsewhere",
    )
    assert generate(client, org, bid).json() == []  # not resurrected


def test_task_status_rules(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    task = client.post(
        f"/v1/brands/{bid}/recommendations/{rec['id']}/accept",
        headers=org.headers,
    ).json()
    url = f"/v1/brands/{bid}/tasks/{task['id']}"

    def patch(body):
        return client.patch(url, json=body, headers=org.headers)

    assert patch({"status": "in_progress"}).json()["status"] == "in_progress"
    assert patch({"status": "in_progress"}).status_code == 200  # no-op
    done = patch({"status": "done"}).json()
    assert done["done_at"] and done["window_days"] == 14
    assert patch({"status": "open"}).status_code == 422
    assert patch({"status": "impact_measured"}).status_code == 422
    assert patch({"notes": "shipped the page"}).json()["notes"] == (
        "shipped the page"
    )
    assert patch({"title": None}).status_code == 422
    assert patch({"owner": "Asha"}).json()["owner"] == "Asha"
    assert patch({"owner": None}).json()["owner"] is None
    listed = client.get(f"/v1/brands/{bid}/tasks", headers=org.headers)
    assert [t["id"] for t in listed.json()] == [task["id"]]
```

In `tests/integration/test_isolation.py`, inside the `other` fixture before its `return`, create one recommendation and one task for org B:

```python
    with owner() as s, s.begin():
        rec = m.Recommendation(
            org_id=b.id,
            brand_id=bid,
            type="sample_more",
            subject_key="k",
            title="Secret",
            body="Secret",
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        task = m.Task(
            org_id=b.id, brand_id=bid, recommendation_id=rec.id, title="Secret"
        )
        s.add(task)
        s.flush()
        rid, tid = rec.id, task.id
```

add `"r": rid, "t": tid` to the returned dict, and append to `CASES`:

```python
    ("POST", "/v1/brands/{b}/recommendations/generate", None),
    ("GET", "/v1/brands/{b}/recommendations", None),
    ("POST", "/v1/brands/{b}/recommendations/{r}/accept", None),
    ("POST", "/v1/brands/{b}/recommendations/{r}/dismiss", {"reason": "x"}),
    ("GET", "/v1/brands/{b}/tasks", None),
    ("PATCH", "/v1/brands/{b}/tasks/{t}", {"notes": "x"}),
```

Run both files. Expected: the new tests fail with 404 on every new route.

- [ ] **Step 2: Schemas** — append to `apps/api/bsi_api/schemas.py` (add `date` to its `datetime` import, and `Annotated`, `StringConstraints` as needed):

```python
class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    type: str
    subject_key: str
    status: str
    dismiss_reason: str | None
    title: str
    body: str
    evidence: dict[str, Any]
    reach: float
    pressure: float
    feasibility: float
    priority: float
    created_at: datetime


class DismissIn(BaseModel):
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    recommendation_id: uuid.UUID | None
    title: str
    owner: str | None
    due_date: date | None
    status: str
    notes: str
    prompt_ids: list[uuid.UUID]
    done_at: datetime | None
    window_days: int | None
    impact_label: str | None
    impact: dict[str, Any] | None
    created_at: datetime


class TaskPatch(BaseModel):
    # Fields defaulting to Field(None) reject an explicit null with a 422;
    # owner and due_date are the two that may be cleared.
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "done", "impact_measured"] = Field(
        None
    )
    title: str = Field(None, min_length=1, max_length=300)
    notes: str = Field(None, max_length=5000)
    owner: str | None = Field(None, max_length=200)
    due_date: date | None = None
```

- [ ] **Step 3: Routers.**

```python
# apps/api/bsi_api/routers/recommendations.py
"""Recommendations: generate from evidence, then accept or dismiss."""

import uuid
from typing import Literal

from bsi_core import models as m
from bsi_core.recommend import refresh
from fastapi import APIRouter
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import DismissIn, RecommendationOut, TaskOut

router = APIRouter(prefix="/brands/{brand_id}", tags=["recommendations"])


def _listed(c: Ctx, brand_id: uuid.UUID, status: str) -> list[m.Recommendation]:
    return list(
        c.s.scalars(
            select(m.Recommendation)
            .where(
                m.Recommendation.brand_id == brand_id,
                m.Recommendation.status == status,
            )
            .order_by(
                m.Recommendation.priority.desc(),
                m.Recommendation.created_at,
                m.Recommendation.id,
            )
        )
    )


def _open(c: Ctx, brand_id: uuid.UUID, rec_id: uuid.UUID) -> m.Recommendation:
    rec: m.Recommendation = child_or_404(c, m.Recommendation, brand_id, rec_id)
    if rec.status != "open":
        raise Problem(409, "Recommendation is not open", f"It is {rec.status}.")
    return rec


@router.post(
    "/recommendations/generate", response_model=list[RecommendationOut]
)
def generate_recommendations(
    brand_id: uuid.UUID, c: Ctx = TENANT
) -> list[m.Recommendation]:
    brand_or_404(c, brand_id)
    refresh(c.s, c.org_id, brand_id)
    return _listed(c, brand_id, "open")


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    brand_id: uuid.UUID,
    status: Literal["open", "accepted", "dismissed"] = "open",
    c: Ctx = TENANT,
) -> list[m.Recommendation]:
    brand_or_404(c, brand_id)
    return _listed(c, brand_id, status)


@router.post(
    "/recommendations/{rec_id}/accept",
    response_model=TaskOut,
    status_code=201,
)
def accept(brand_id: uuid.UUID, rec_id: uuid.UUID, c: Ctx = TENANT) -> m.Task:
    rec = _open(c, brand_id, rec_id)
    rec.status = "accepted"
    task = m.Task(
        org_id=c.org_id,
        brand_id=brand_id,
        recommendation_id=rec.id,
        title=rec.title,
        prompt_ids=[uuid.UUID(p) for p in rec.evidence.get("prompt_ids", [])],
    )
    c.s.add(task)
    c.s.flush()
    return task


@router.post(
    "/recommendations/{rec_id}/dismiss", response_model=RecommendationOut
)
def dismiss(
    brand_id: uuid.UUID, rec_id: uuid.UUID, body: DismissIn, c: Ctx = TENANT
) -> m.Recommendation:
    rec = _open(c, brand_id, rec_id)
    rec.status, rec.dismiss_reason = "dismissed", body.reason
    return rec
```

```python
# apps/api/bsi_api/routers/tasks.py
"""Tasks: accepted recommendations, followed to a measured outcome."""

import uuid

from bsi_core import models as m
from bsi_core.config import get_settings
from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import TaskOut, TaskPatch

router = APIRouter(prefix="/brands/{brand_id}", tags=["tasks"])

# What a person may set. Nothing leaves done - a reopened task would make
# its window meaningless - and impact_measured belongs to the worker.
NEXT = {
    "open": {"in_progress", "done"},
    "in_progress": {"open", "done"},
    "done": set(),
    "impact_measured": set(),
}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[m.Task]:
    brand_or_404(c, brand_id)
    return list(
        c.s.scalars(
            select(m.Task)
            .where(m.Task.brand_id == brand_id)
            .order_by(m.Task.created_at.desc(), m.Task.id)
        )
    )


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    brand_id: uuid.UUID, task_id: uuid.UUID, body: TaskPatch, c: Ctx = TENANT
) -> m.Task:
    task: m.Task = child_or_404(c, m.Task, brand_id, task_id)
    fields = body.model_dump(exclude_unset=True)
    new = fields.pop("status", task.status)
    if new != task.status:
        if new not in NEXT[task.status]:
            raise Problem(
                422, "Illegal status change", f"{task.status} -> {new}"
            )
        if new == "done":
            task.done_at = c.s.scalar(select(func.now()))
            task.window_days = get_settings().impact_window_days
        task.status = new
    for name, value in fields.items():
        setattr(task, name, value)
    return task
```

Register both in `main.py`'s router tuple (import them in the `from .routers import (...)` list).

- [ ] **Step 4: Tests pass; backend gate; `cd apps/web && npm run gen && npm run gate`; commit** — `feat(api): recommendations and tasks`

---

### Task 5: The pages

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/recommendations/page.tsx`, `…/recommendations/actions.ts`, `…/tasks/page.tsx`, `…/tasks/actions.ts`
- Modify: `apps/web/src/lib/types.ts`, `apps/web/src/app/(app)/b/[id]/layout.tsx`, `apps/web/src/app/(app)/b/[id]/page.tsx`

**Interfaces:**
- Consumes: the Task 4 endpoints; `api`, `pct`, `ciText`, `pts` and the `Rate` type; the `.card`, `.tag`, `.row`, `.filters`, `.muted`, `.up`, `.down` classes.

- [ ] **Step 1: Types and tabs.** Add to `types.ts`:

```ts
export type Recommendation = S["RecommendationOut"];
export type Task = S["TaskOut"];
```

In `layout.tsx`, after the Prompts link:

```tsx
        <Link href={`/b/${id}/recommendations`}>Recommendations</Link>
        <Link href={`/b/${id}/tasks`}>Tasks</Link>
```

- [ ] **Step 2: Recommendations.**

```ts
// apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

const brand = (form: FormData) => String(form.get("brand_id"));
const rec = (form: FormData) =>
  `/brands/${brand(form)}/recommendations/${String(form.get("rec_id"))}`;

export async function generate(form: FormData) {
  await api(`/brands/${brand(form)}/recommendations/generate`, {
    method: "POST",
  });
  redirect(`/b/${brand(form)}/recommendations`);
}

export async function accept(form: FormData) {
  await api(`${rec(form)}/accept`, { method: "POST" });
  redirect(`/b/${brand(form)}/tasks`);
}

export async function dismiss(form: FormData) {
  await api(`${rec(form)}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
  });
  redirect(`/b/${brand(form)}/recommendations`);
}
```

```tsx
// apps/web/src/app/(app)/b/[id]/recommendations/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import type { Recommendation } from "@/lib/types";
import { accept, dismiss, generate } from "./actions";

const KIND: Record<string, string> = {
  pursue_citation_source: "Citation source",
  create_content: "Content",
  add_competitor: "Competitor",
  sample_more: "Measurement",
};

type Evidence = { prompt_ids?: string[]; observation_ids?: string[] };

export default async function Recommendations({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const recs = await api<Recommendation[]>(`/brands/${id}/recommendations`);
  return (
    <>
      <form action={generate} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Generate from current evidence</button>
        <span className="muted">
          Rules over the answers already stored; no model is called.
        </span>
      </form>
      {recs.length === 0 && (
        <p className="muted">
          No open recommendations. Generate to check the latest evidence.
        </p>
      )}
      {recs.map((r) => (
        <Card key={r.id} r={r} id={id} />
      ))}
    </>
  );
}

function Card({ r, id }: { r: Recommendation; id: string }) {
  const ev = r.evidence as Evidence;
  const prompts = ev.prompt_ids ?? [];
  const answers = ev.observation_ids ?? [];
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row">
        <span className="tag">{KIND[r.type] ?? r.type}</span>
        <strong>{r.title}</strong>
      </div>
      <p>{r.body}</p>
      <p className="muted">
        priority {r.priority.toFixed(3)} = reach {r.reach.toFixed(2)} ×
        pressure {r.pressure.toFixed(2)} × feasibility{" "}
        {r.feasibility.toFixed(2)}
      </p>
      {(prompts.length > 0 || answers.length > 0) && (
        <p className="muted">
          Evidence:{" "}
          {prompts.length === 1 && (
            <Link href={`/b/${id}/prompts/${prompts[0]}`}>the prompt</Link>
          )}
          {prompts.length > 1 && `${prompts.length} prompts`}
          {answers.slice(0, 5).map((o, i) => (
            <span key={o}>
              {" · "}
              <Link href={`/o/${o}`}>answer {i + 1}</Link>
            </span>
          ))}
          {answers.length > 5 && ` and ${answers.length - 5} more`}
        </p>
      )}
      <div className="row">
        <form action={accept}>
          <input type="hidden" name="brand_id" value={id} />
          <input type="hidden" name="rec_id" value={r.id} />
          <button className="primary">Accept as a task</button>
        </form>
        <form action={dismiss} className="row">
          <input type="hidden" name="brand_id" value={id} />
          <input type="hidden" name="rec_id" value={r.id} />
          <input
            name="reason"
            placeholder="Why dismiss it?"
            required
            pattern=".*\S.*"
            maxLength={500}
          />
          <button>Dismiss</button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Tasks.**

```ts
// apps/web/src/app/(app)/b/[id]/tasks/actions.ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function updateTask(form: FormData) {
  const id = String(form.get("brand_id"));
  const body: Record<string, unknown> = {
    owner: String(form.get("owner") ?? "") || null,
    due_date: String(form.get("due_date") ?? "") || null,
    notes: String(form.get("notes") ?? ""),
  };
  const status = form.get("status");
  if (status) body.status = String(status);
  await api(`/brands/${id}/tasks/${String(form.get("task_id"))}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  redirect(`/b/${id}/tasks`);
}
```

```tsx
// apps/web/src/app/(app)/b/[id]/tasks/page.tsx
import { api } from "@/lib/api";
import { ciText, pct, pts, type Rate } from "@/lib/format";
import type { Task } from "@/lib/types";
import { updateTask } from "./actions";

const IMPACT: Record<string, [string, string]> = {
  improved: ["Improved", "up"],
  declined: ["Declined", "down"],
  no_change: ["No significant change", "muted"],
  insufficient_data: ["Insufficient data", "muted"],
  not_comparable: ["Not comparable", "muted"],
};

type Impact = {
  before: Rate;
  after: Rate;
  delta: { value: number | null } | null;
  reason: string | null;
};

export default async function Tasks({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const tasks = await api<Task[]>(`/brands/${id}/tasks`);
  return (
    <>
      {tasks.length === 0 && (
        <p className="muted">
          No tasks yet. Accept a recommendation to start one.
        </p>
      )}
      {tasks.map((t) => (
        <Card key={t.id} t={t} id={id} />
      ))}
    </>
  );
}

function Card({ t, id }: { t: Task; id: string }) {
  const settled = t.status === "done" || t.status === "impact_measured";
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row">
        <span className="tag">{t.status.replace("_", " ")}</span>
        <strong>{t.title}</strong>
      </div>
      <form action={updateTask} className="filters">
        <input type="hidden" name="brand_id" value={id} />
        <input type="hidden" name="task_id" value={t.id} />
        {!settled && (
          <label>
            Status
            <select name="status" defaultValue={t.status}>
              <option value="open">open</option>
              <option value="in_progress">in progress</option>
              <option value="done">done</option>
            </select>
          </label>
        )}
        <label>
          Owner
          <input name="owner" defaultValue={t.owner ?? ""} maxLength={200} />
        </label>
        <label>
          Due
          <input type="date" name="due_date" defaultValue={t.due_date ?? ""} />
        </label>
        <label>
          Notes
          <textarea name="notes" defaultValue={t.notes} maxLength={5000} />
        </label>
        <button>Save</button>
      </form>
      {t.status === "done" && (
        <p className="muted">
          Done {t.done_at?.slice(0, 10)}. Impact is measured after{" "}
          {t.window_days} days, on{" "}
          {t.prompt_ids.length
            ? `${t.prompt_ids.length} prompt${t.prompt_ids.length > 1 ? "s" : ""}`
            : "every prompt"}
          .
        </p>
      )}
      {t.impact_label && <Outcome t={t} />}
    </div>
  );
}

function Outcome({ t }: { t: Task }) {
  const [label, tone] = IMPACT[t.impact_label ?? ""] ?? [t.impact_label, "muted"];
  const i = t.impact as Impact | null;
  return (
    <div>
      <p className={tone}>
        <strong>{label}</strong>
        {i?.delta?.value != null && ` (${pts(i.delta.value)})`}
      </p>
      {i && (
        <p className="muted">
          Mention rate before {pct(i.before.value)} ({ciText(i.before)}),
          after {pct(i.after.value)} ({ciText(i.after)}).
          {i.reason && ` ${i.reason}.`}
        </p>
      )}
      <p className="muted">
        An association, not a cause: anything else that changed in the same
        weeks is mixed in.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Top three on the overview.** In `(app)/b/[id]/page.tsx`: add `import Link from "next/link";`, add `Recommendation` to the `@/lib/types` import, add `api<Recommendation[]>(\`/brands/${id}/recommendations\`)` as a fourth entry of the `Promise.all` (destructure it as `recs`), and add after the share-of-voice table:

```tsx
      <h2>Top recommendations</h2>
      {recs.length === 0 ? (
        <p className="muted">
          None open. <Link href={`/b/${id}/recommendations`}>Generate</Link>{" "}
          from the current evidence.
        </p>
      ) : (
        <ol>
          {recs.slice(0, 3).map((r) => (
            <li key={r.id}>
              <Link href={`/b/${id}/recommendations`}>{r.title}</Link>{" "}
              <span className="muted">priority {r.priority.toFixed(3)}</span>
            </li>
          ))}
        </ol>
      )}
```

- [ ] **Step 5: Frontend gate.** `cd apps/web && npm run gate` — zero warnings.
- [ ] **Step 6: Verify in the real app** against the dev database. Start the API and `npm run dev`; mint a key for "Run 1" owner-side as `tests/conftest.py: make_org` does. With `curl --cookie "bsi_key=$KEY"`: the Recommendations page renders a Generate button; after generating, it lists recommendations with priority parts and evidence links that resolve (open one `/o/…` link); the overview shows the top three; accepting one lands on Tasks with it open. Record what you saw. **Do not change the task's status in the dev database here** — Task 6 does that deliberately.
- [ ] **Step 7: Commit** — `feat(web): recommendations and tasks pages`

---

### Task 6: The live loop, findings and docs

**Files:**
- Create: `docs/findings-slice6.md`
- Modify: `docs/README.md` (a findings row under `## Slice 6`, and the plan row)

- [ ] **Step 1: Generate on real data and record it.** Against the dev database (API running, "Run 1" key), `POST /v1/brands/{id}/recommendations/generate` and record: how many of each type; the top three with their priority parts; the three highest-cited citation domains. Expected from the data read during design: citation recommendations including forbes.com (cited in ~22 brand-absent answers); `create_content` for most prompts; `sample_more` for the n=4 prompts needing 7 or 11; no `add_competitor` ("Run 1" has no suggested competitors). Generate for "Slice4 check" too, and record whether `add_competitor` appears there.
- [ ] **Step 2: Walk one task through the whole loop.** Accept a `create_content` recommendation on "Run 1", move it `in_progress` then `done` through the API. Then, owner-side, backdate its `done_at` by 15 days (the tests' method — there is no clock freezing), and run `uv run python -c "from bsi_workers.worker import close_due_impact_windows as f; print(f())"`. Record the label. The expected, honest outcome is `insufficient_data`: every "Run 1" observation falls in the after window, so the before window is empty. Confirm the Tasks page shows the label and the "association, not a cause" caption.
- [ ] **Step 3: Restore the dev database.** Delete the task and the recommendations this task created for both orgs, owner-side, and confirm "Run 1" still has 80 observations, 1 `rec_label`, no schedules and no budget override.
- [ ] **Step 4: Write `docs/findings-slice6.md`**, in the style of `findings-slice5.md`: what generate produced on real data and whether the ranking reads as sensible; the loop end to end and why its first honest answer is "insufficient data"; the weights as set (`FEASIBILITY` and the three thresholds) and that they are judgement calls awaiting use; known gaps — the four audit-dependent types, LLM drafting and the critic loop, weekly regeneration, users and assignment, notifications, the board view, snooze, and that `add_competitor`'s reach of 1.0 will tend to put confirmations at the top.
- [ ] **Step 5: Index and commit** — add the plan and findings rows to `docs/README.md` under `## Slice 6`. Commit — `docs: slice 6 findings and index`.
