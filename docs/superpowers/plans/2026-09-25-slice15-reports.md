# Slice 15 Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five report types per brand (CMO, SEO, content, PR, agency), generated weekly/monthly by the worker or on demand, frozen as JSON snapshots, viewable through a revocable public link and downloadable as a PDF.

**Architecture:** One builder per type in `bsi_core/reports.py` turns the existing metric functions into a `Document` (sections of paragraphs and pre-formatted tables) that `report_run.document` stores. `generate()` is called by the API for manual runs and by a new `due_report_runs()` worker sweep for scheduled ones. Two dumb renderers read the stored document: a Next.js public page and `bsi_core/pdf.py` (reportlab). Public lookup goes through one SECURITY DEFINER `report_run_by_token()` and then a normal tenant session.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI, reportlab (new), Next.js 15 App Router, vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-slice15-reports-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`; the shell's cwd resets after every command, so every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases; never touch the dev DB, the network or the worker loop. Tests use the shared `bsi_test` DB; run only the files named in the task, never two suites at once (`pgrep -fl "pytest"` first).
- ruff line length 80, target py313; `mypy --strict` over `packages/core/bsi_core`; every value in SQL is bound, only fixed fragments are concatenated.
- No transaction may be open during any HTTP call or model call. Reports make neither.
- Copy: no string in any document may contain `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain` (the `FORBIDDEN` list in `tests/unit/test_recommend_copy.py`). The product name appears in no document.
- `METHODOLOGY_VERSION = "1"`. Every rate cell is `value [low, high] n=N`; `n=0` renders `— (n=0)`.
- Every tenant table: `_protect()` in the migration, a row in `TENANT_TABLES` and the `org_b` fixture (`tests/integration/test_rls.py`); every id-taking route a row in `CASES` (`tests/integration/test_isolation.py`).
- `tenant_session` opens a transaction and commits on exit; never `with tenant_session(...) as s, s.begin():`.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (or the trailer in the latest session reminder).
- Decisions taken while planning (record in the spec's Rulings section during execution): signs in delta cells are ASCII (`-0.09`, `+0.01`), not the Unicode minus the spec's example shows; a malformed share token (not `[A-Za-z0-9_-]{20,64}`) is a 422, an unknown one a 404.

---

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0017_reports.py` | tables `report`, `report_run`; three brand columns; `due_report_runs()`, `report_run_by_token()` |
| `packages/core/bsi_core/models.py` | `REPORT_TYPES`, `REPORT_CADENCES`, `RUN_SOURCES`, `Report`, `ReportRun`, `Brand.report_*` |
| `packages/core/bsi_core/reports.py` | document models, formatters, five builders, `definition()`, `generate()` |
| `packages/core/bsi_core/pdf.py` | `render_pdf(document) -> bytes` |
| `apps/workers/bsi_workers/worker.py` | `generate_due_reports()` in the minute loop |
| `apps/api/bsi_api/schemas.py` | `ReportOut`, `CadenceIn`, `ReportRunListOut`, `ReportRunOut` |
| `apps/api/bsi_api/routers/reports.py` | tenant routes |
| `apps/api/bsi_api/routers/public.py` | `/r/{token}` and `/r/{token}.pdf` |
| `apps/api/bsi_api/routers/brands.py` | `BrandPatch`/`BrandOut` branding fields |
| `apps/web/src/lib/{api,format,types}.ts` | `publicApi`, `REPORT_TYPE`, `reportNote`, types |
| `apps/web/src/components/ReportBody.tsx` | pure document renderer (shared by the public page and its test) |
| `apps/web/src/app/r/[token]/page.tsx` | public page |
| `apps/web/src/app/(app)/b/[id]/reports/{page,actions}.tsx` | Reports tab |
| `tests/unit/test_reports.py`, `tests/unit/test_pdf.py` | formatters, models, PDF |
| `tests/integration/test_reports.py` | builders, generate, due function, worker sweep, copy ban |
| `tests/integration/test_api_reports.py` | tenant and public routes |
| `docs/findings-slice15.md`, `docs/README.md` | findings and index |

---

### Task 1: Migration, ORM and tenancy fixtures

**Files:**
- Create: `migrations/versions/0017_reports.py`
- Modify: `packages/core/bsi_core/models.py` (after `ALERT_TYPES`, after `Brand.webhook_url`, after `class Alert`)
- Modify: `tests/integration/test_rls.py` (`TENANT_TABLES`, `org_b`)
- Test: `tests/integration/test_rls.py`, `tests/integration/test_reports.py` (new)

**Interfaces:**
- Produces: `m.REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")`, `m.REPORT_CADENCES = ("off", "weekly", "monthly")`, `m.RUN_SOURCES = ("scheduled", "manual")`, `m.Report(brand_id, type, cadence, generated_at)`, `m.ReportRun(brand_id, report_id, type, source, period_from, period_to, compare_from, document, methodology_version, share_token)`, `m.Brand.report_logo_url / report_accent / report_prepared_by`, SQL `due_report_runs()` → `(report_id, brand_id, org_id, report_type, cadence)`, SQL `report_run_by_token(token)` → `(run_id, org_id)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_reports.py`:

```python
"""Reports: due function, builders, generate, worker sweep."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import text, update


def due_runs():
    with system_session() as s:
        return [
            (r.report_id, r.report_type)
            for r in s.execute(
                text(
                    "SELECT report_id, report_type, cadence "
                    "FROM due_report_runs()"
                )
            )
        ]


def _definition(owner, org, bid, type_="cmo", cadence="weekly", stamp=None):
    with owner() as s, s.begin():
        r = m.Report(
            org_id=org.id,
            brand_id=bid,
            type=type_,
            cadence=cadence,
            generated_at=stamp,
        )
        s.add(r)
        s.flush()
        return r.id


def test_due_needs_cadence_on_active_brand_and_old_stamp(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    now = datetime.now(UTC)
    never = _definition(owner, org, bid, "cmo", "weekly", None)
    _definition(owner, org, bid, "seo", "off", None)
    fresh_w = _definition(owner, org, bid, "content", "weekly", now)
    old_w = _definition(
        owner, org, bid, "pr", "weekly", now - timedelta(days=8)
    )
    # 8 days is old for weekly but fresh for monthly.
    _definition(owner, org, bid, "agency", "monthly", now - timedelta(days=8))
    assert due_runs() == [(never, "cmo"), (old_w, "pr")]
    with owner() as s, s.begin():
        s.execute(
            update(m.Report)
            .where(m.Report.id == fresh_w)
            .values(generated_at=now - timedelta(days=31))
        )
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due_runs() == []


def test_token_lookup_crosses_tenants_only_by_exact_token(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    rid = _definition(owner, org, bid)
    with owner() as s, s.begin():
        run = m.ReportRun(
            org_id=org.id,
            brand_id=bid,
            report_id=rid,
            type="cmo",
            source="manual",
            period_from=datetime.now(UTC),
            period_to=datetime.now(UTC),
            compare_from=datetime.now(UTC),
            document={},
            methodology_version="1",
            share_token="tok-abcdefghijklmnopqrstuvwxyz",
        )
        s.add(run)
        s.flush()
        run_id = run.id
    q = text("SELECT run_id, org_id FROM report_run_by_token(:t)")
    with system_session() as s:
        hit = s.execute(q, {"t": "tok-abcdefghijklmnopqrstuvwxyz"}).first()
        miss = s.execute(q, {"t": "tok-abcdefghijklmnopqrstuvwxy"}).first()
        none = s.execute(q, {"t": ""}).first()
    assert hit is not None and (hit.run_id, hit.org_id) == (run_id, org.id)
    assert miss is None and none is None
```

In `tests/integration/test_rls.py`, add `"report", "report_run"` to `TENANT_TABLES` after `"alert"`, and in `org_b`, after the `m.Alert(...)` add:

```python
        rep = m.Report(org_id=b.id, brand_id=bid, type="cmo")
        s.add(rep)
        s.flush()
        s.add(
            m.ReportRun(
                org_id=b.id,
                brand_id=bid,
                report_id=rep.id,
                type="cmo",
                source="manual",
                period_from=datetime.now(UTC),
                period_to=datetime.now(UTC),
                compare_from=datetime.now(UTC),
                document={},
                methodology_version="1",
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py tests/integration/test_rls.py`
Expected: FAIL (`AttributeError: module 'bsi_core.models' has no attribute 'Report'`, and `test_tenant_table_list_matches_the_schema` fails on the set difference).

- [ ] **Step 3: Add the ORM**

In `packages/core/bsi_core/models.py`, after `ALERT_TYPES`:

```python
REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")
REPORT_CADENCES = ("off", "weekly", "monthly")
RUN_SOURCES = ("scheduled", "manual")
```

After `webhook_url` on `Brand`:

```python
    # Agency-report branding; all optional. Copied into the document at
    # build time, so the public route never reads this row.
    report_logo_url: Mapped[str | None]
    report_accent: Mapped[str | None]
    report_prepared_by: Mapped[str | None]
```

After `class Alert`:

```python
class Report(Tenant, Base):
    """The definition: one row per (brand, type), created lazily.
    generated_at is stamped by the worker's scheduled pass only; a manual
    run must not defer the next scheduled one."""

    __tablename__ = "report"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    cadence: Mapped[str] = mapped_column(server_default="off")
    generated_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_type"),
        CheckConstraint(
            _in("cadence", REPORT_CADENCES), name="ck_report_cadence"
        ),
        UniqueConstraint("brand_id", "type", name="uq_report_brand_type"),
    )


class ReportRun(Tenant, Base):
    """One rendered report. `document` is the whole content, frozen at
    generation; the HTML page and the PDF only render it."""

    __tablename__ = "report_run"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report.id"))
    type: Mapped[str]
    source: Mapped[str]
    period_from: Mapped[datetime] = mapped_column(TSZ)
    period_to: Mapped[datetime] = mapped_column(TSZ)
    # The prior period is [compare_from, period_from).
    compare_from: Mapped[datetime] = mapped_column(TSZ)
    document: Mapped[dict[str, Any]]
    methodology_version: Mapped[str]
    # NULL = link revoked (or never shared).
    share_token: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_run_type"),
        CheckConstraint(
            _in("source", RUN_SOURCES), name="ck_report_run_source"
        ),
        Index("ix_report_run_list", "brand_id", "created_at"),
        Index(
            "ix_report_run_token",
            "share_token",
            unique=True,
            postgresql_where=text("share_token IS NOT NULL"),
        ),
    )
```

- [ ] **Step 4: Write the migration**

Create `migrations/versions/0017_reports.py`:

```python
"""report and report_run tables; brand.report_logo_url, report_accent,
report_prepared_by; due_report_runs(), report_run_by_token()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")
REPORT_CADENCES = ("off", "weekly", "monthly")
RUN_SOURCES = ("scheduled", "manual")
WEEKLY_DAYS = 7
MONTHLY_DAYS = 30


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _row_columns() -> list[sa.Column]:
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
        sa.Column("brand_id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    for col in ("report_logo_url", "report_accent", "report_prepared_by"):
        op.add_column("brand", sa.Column(col, sa.String()))
    op.create_table(
        "report",
        *_row_columns(),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "cadence", sa.String(), server_default="off", nullable=False
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_type"),
        sa.CheckConstraint(
            _in("cadence", REPORT_CADENCES), name="ck_report_cadence"
        ),
        sa.UniqueConstraint("brand_id", "type", name="uq_report_brand_type"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _protect("report")
    op.create_table(
        "report_run",
        *_row_columns(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compare_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("methodology_version", sa.String(), nullable=False),
        sa.Column("share_token", sa.String()),
        sa.CheckConstraint(
            _in("type", REPORT_TYPES), name="ck_report_run_type"
        ),
        sa.CheckConstraint(
            _in("source", RUN_SOURCES), name="ck_report_run_source"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["report.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_report_run_list", "report_run", ["brand_id", "created_at"]
    )
    op.create_index(
        "ix_report_run_token",
        "report_run",
        ["share_token"],
        unique=True,
        postgresql_where=sa.text("share_token IS NOT NULL"),
    )
    _protect("report_run")
    op.execute(f"""
        CREATE FUNCTION due_report_runs()
        RETURNS TABLE(report_id uuid, brand_id uuid, org_id uuid,
                      report_type text, cadence text)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT r.id, r.brand_id, r.org_id, r.type, r.cadence
          FROM report r JOIN brand b ON b.id = r.brand_id
          WHERE b.status = 'active'
            AND r.cadence <> 'off'
            AND (r.generated_at IS NULL
                 OR r.generated_at <= now() - make_interval(days =>
                      CASE r.cadence WHEN 'weekly' THEN {WEEKLY_DAYS}
                                     ELSE {MONTHLY_DAYS} END))
          ORDER BY r.generated_at NULLS FIRST, r.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_report_runs() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_report_runs() TO bsi_app")
    op.execute("""
        CREATE FUNCTION report_run_by_token(token text)
        RETURNS TABLE(run_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT rr.id, rr.org_id FROM report_run rr
          WHERE rr.share_token = token
        $$""")
    op.execute(
        "REVOKE ALL ON FUNCTION report_run_by_token(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION report_run_by_token(text) TO bsi_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION report_run_by_token(text)")
    op.execute("DROP FUNCTION due_report_runs()")
    op.drop_table("report_run")
    op.drop_table("report")
    for col in ("report_prepared_by", "report_accent", "report_logo_url"):
        op.drop_column("brand", col)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py tests/integration/test_rls.py`
Expected: PASS. If `Can't locate revision`, the test DB was migrated by another worktree at a different head; do not create databases, report it.

- [ ] **Step 6: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`
Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0017_reports.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): report and report_run tables, due and token functions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 2: Document models and formatters

**Files:**
- Create: `packages/core/bsi_core/reports.py`
- Test: `tests/unit/test_reports.py`

**Interfaces:**
- Produces: `METHODOLOGY_VERSION`, `Period`, `Branding`, `Paragraph`, `Table`, `Block`, `Section`, `Document`, `fmt_rate(r) -> str`, `fmt_delta(d) -> str`, `fmt_pct(v) -> str`, `fmt_signed(v) -> str`, `fmt_day(dt) -> str`, `footer(versions, at) -> str`, `empty(what) -> Paragraph`, `table_or_empty(columns, rows, what) -> Block`, `METRIC_LABEL`, `REC_LABEL`, `ALERT_LABEL`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reports.py`:

```python
from datetime import UTC, datetime

from bsi_core.reports import (
    METHODOLOGY_VERSION,
    Document,
    Paragraph,
    Period,
    Section,
    Table,
    fmt_delta,
    fmt_pct,
    fmt_rate,
    fmt_signed,
    footer,
    table_or_empty,
)

AT = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


def test_fmt_rate_prints_value_interval_and_n():
    r = {"value": 0.4166, "n": 12, "ci_low": 0.194, "ci_high": 0.6749}
    assert fmt_rate(r) == "0.42 [0.19, 0.67] n=12"
    assert fmt_rate({"value": None, "n": 0, "ci_low": 0, "ci_high": 1}) == (
        "— (n=0)"
    )


def test_fmt_delta_prints_signed_interval_and_label():
    d = {"value": -0.09, "ci_low": -0.18, "ci_high": 0.005, "label": "x"}
    assert fmt_delta(d) == "-0.09 [-0.18, +0.01] x"
    assert fmt_delta({"value": None, "label": "insufficient data"}) == (
        "insufficient data"
    )
    assert fmt_delta(None) == "—"


def test_fmt_pct_and_signed():
    assert fmt_pct(0.1234) == "12.3%" and fmt_pct(None) == "—"
    assert fmt_signed(0.25) == "+0.25" and fmt_signed(None) == "—"


def test_footer_names_methodology_and_pipeline_versions():
    f = footer(["2"], AT)
    assert f.startswith(f"Methodology v{METHODOLOGY_VERSION} · pipeline v2")
    assert "95% Wilson" in f and "95% Newcombe" in f
    assert f.endswith("generated 2026-09-25 09:00 UTC")
    assert "pipeline v1, 2" in footer(["2", "1"], AT)
    assert "pipeline v—" in footer([], AT)


def test_table_or_empty():
    assert table_or_empty(["a"], [], "cited sources") == Paragraph(
        text="No cited sources in this period."
    )
    t = table_or_empty(["a"], [["1"]], "x")
    assert isinstance(t, Table) and t.rows == [["1"]]


def test_document_round_trips_through_json_with_from_alias():
    doc = Document(
        title="t",
        brand="Nike",
        type="cmo",
        period=Period(from_=AT, to=AT, compare_from=AT),
        sections=[Section(heading="h", blocks=[Paragraph(text="p")])],
        footer="f",
    )
    data = doc.model_dump(mode="json", by_alias=True)
    assert data["period"]["from"] == "2026-09-25T09:00:00Z"
    assert data["sections"][0]["blocks"][0] == {"kind": "p", "text": "p"}
    assert Document.model_validate(data) == doc
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_reports.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsi_core.reports'`.

- [ ] **Step 3: Write the module**

Create `packages/core/bsi_core/reports.py` (builders and `generate` come in Tasks 3–5; this task writes the head of the file):

```python
"""Reports: a frozen document per run, built from the same metric
functions the dashboard uses, so report and API agree for one window.

Every cell is a pre-formatted string, so the HTML page and the PDF only
render. No links or ids: readers are outside the app. Fixed copy only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Bump whenever a builder changes what it computes or how a cell is
# formatted: a reader comparing two runs must know they are comparable.
METHODOLOGY_VERSION = "1"

METRIC_LABEL = {
    "mention_rate": "Mention rate",
    "recommendation_rate": "Recommendation rate",
    "citation_rate": "Citation rate",
    "prompt_coverage": "Prompt coverage",
    "sov": "Share of voice",
}
REC_LABEL = {
    "pursue_citation_source": "Citation source",
    "create_content": "Content",
    "add_competitor": "Competitor",
    "sample_more": "Measurement",
    "fix_crawlability": "Site fix",
    "fix_entity": "Entity fix",
    "optimize_page": "Page fix",
}
ALERT_LABEL = {
    "mention_drop": "Mention drop",
    "competitor_shift": "Competitor shift",
    "new_source": "New source",
}


class Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: datetime = Field(alias="from")
    to: datetime
    compare_from: datetime


class Branding(BaseModel):
    logo_url: str | None = None
    accent: str | None = None
    prepared_by: str | None = None


class Paragraph(BaseModel):
    kind: Literal["p"] = "p"
    text: str


class Table(BaseModel):
    kind: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]


Block = Annotated[Paragraph | Table, Field(discriminator="kind")]


class Section(BaseModel):
    heading: str
    blocks: list[Block]


class Document(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    title: str
    brand: str
    type: str
    period: Period
    branding: Branding | None = None
    sections: list[Section]
    footer: str


def fmt_rate(r: Mapping[str, Any]) -> str:
    if r["n"] == 0 or r["value"] is None:
        return "— (n=0)"
    return (
        f"{r['value']:.2f} [{r['ci_low']:.2f}, {r['ci_high']:.2f}] "
        f"n={r['n']}"
    )


def fmt_delta(d: Mapping[str, Any] | None) -> str:
    if d is None:
        return "—"
    if d["value"] is None:
        return str(d["label"])
    return (
        f"{d['value']:+.2f} [{d['ci_low']:+.2f}, {d['ci_high']:+.2f}] "
        f"{d['label']}"
    )


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def fmt_signed(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}"


def fmt_day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def footer(versions: Sequence[str], at: datetime) -> str:
    seen = ", ".join(sorted(set(versions))) or "—"
    return (
        f"Methodology v{METHODOLOGY_VERSION} · pipeline v{seen} · "
        "rates: 95% Wilson interval · deltas: 95% Newcombe interval · "
        f"generated {at.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def empty(what: str) -> Paragraph:
    return Paragraph(text=f"No {what} in this period.")


def table_or_empty(
    columns: list[str], rows: list[list[str]], what: str
) -> Paragraph | Table:
    return Table(columns=columns, rows=rows) if rows else empty(what)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_reports.py`
Expected: PASS. (`model_dump(mode="json")` renders UTC datetimes as `...Z`; if it gives `+00:00`, change the test's expected string to that: both are ISO and the API consumer parses either.)

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py tests/unit/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): document models and cell formatters

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 3: Opening section, CMO and agency builders

**Files:**
- Modify: `packages/core/bsi_core/reports.py` (append)
- Test: `tests/integration/test_reports.py` (append)

**Interfaces:**
- Consumes: `metrics.brand_deltas(s, brand_id, f, days, to)`, `metrics.brand_sov(s, brand_id, f)`, `metrics.DELTA_METRICS`, `competitors.entity_metrics(s, brand_id, f)`, `citations.sources(s, brand_id, f)`, `recommend.top_by_type(ranked)`.
- Produces: `Builder = Callable[[Session, m.Brand, int, datetime], Document]`; `build_cmo(s, brand, days, to, *, client_facing=False) -> Document`; `build_agency(s, brand, days, to) -> Document`; helpers `_opening`, `_open_recommendations(s, brand_id, types=None)`, `_rec_rows`, `_alert_rows`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_reports.py`. Add these imports at the top of the file:

```python
from bsi_core.citations import sources
from bsi_core.competitors import entity_metrics
from bsi_core.metrics import DELTA_METRICS, Filters, brand_deltas
from bsi_core.reports import (
    METRIC_LABEL,
    Document,
    build_agency,
    build_cmo,
    fmt_delta,
    fmt_rate,
)

from tests.integration.test_competitors import (  # noqa: F401
    NOW,
    _answers,
    _cite,
    _mention,
    _prompt,
)
```

Then the scene and tests:

```python
def _scene(owner, make_org, make_brand):
    """Nike (nike.com) v Adidas (adidas.com). One prompt; 6 answers in the
    last 7 days, 6 in the 7 before. This period: Nike named 4/6 (one
    negative), Adidas 3/6; forbes.com cited on every answer, nike.com on
    2. Prior period: Nike 1/6. One open recommendation, one done task
    with a measured impact, one alert inside the period."""
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        comp = m.Competitor(
            org_id=org.id, brand_id=bid, name="Adidas", domains=["adidas.com"]
        )
        s.add(comp)
        s.flush()
        cid = comp.id
    p = _prompt(owner, org, bid, "best shoes")
    before = _answers(owner, org, bid, p, NOW - timedelta(days=10), 6)
    after = _answers(owner, org, bid, p, NOW - timedelta(days=2), 6)
    rows = [_mention(org, before[0], "brand", bid)]
    rows += [_mention(org, o, "brand", bid) for o in after[:3]]
    rows.append(
        _mention(org, after[3], "brand", bid, rec="negative", sent="negative")
    )
    rows += [_mention(org, o, "competitor", cid) for o in after[:3]]
    rows += [_cite(org, o, "forbes.com") for o in after]
    rows += [_cite(org, o, "nike.com", owned=True) for o in after[:2]]
    with owner() as s, s.begin():
        s.add_all(rows)
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type="pursue_citation_source",
            subject_key="forbes.com",
            title="Pitch forbes.com",
            body="b",
            reach=0.5,
            pressure=0.5,
            feasibility=0.5,
            priority=0.125,
        )
        s.add(rec)
        s.flush()
        s.add(
            m.Task(
                org_id=org.id,
                brand_id=bid,
                recommendation_id=rec.id,
                title="Pitch forbes.com",
                owner="Priya",
                status="impact_measured",
                done_at=NOW - timedelta(days=3),
                impact_label="improved",
                impact={
                    "delta": {
                        "value": 0.2,
                        "ci_low": 0.1,
                        "ci_high": 0.3,
                        "label": "increase",
                    }
                },
            )
        )
        s.add(
            m.Alert(
                org_id=org.id,
                brand_id=bid,
                type="new_source",
                subject_key="forbes.com",
                title="forbes.com is a new source",
                detail={"domain": "forbes.com", "answers": 6},
                window_from=NOW - timedelta(days=7),
                window_to=NOW,
                created_at=NOW - timedelta(days=1),
            )
        )
    return org, bid


def _section(doc: Document, heading: str):
    return next(sec for sec in doc.sections if sec.heading == heading)


def _table(doc: Document, heading: str):
    block = _section(doc, heading).blocks[0]
    assert block.kind == "table", (heading, block)
    return block


def test_cmo_opening_agrees_with_brand_deltas(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        doc = build_cmo(s, brand, 7, NOW)
        out = brand_deltas(s, bid, Filters(), 7, NOW)
    assert doc.type == "cmo" and doc.brand == "Nike"
    assert doc.period.from_ == out["after"]["from"]
    assert doc.period.compare_from == out["before"]["from"]
    assert doc.sections[0].heading == "Period"
    vis = _table(doc, "Visibility")
    assert vis.columns == ["Metric", "This period", "Prior period", "Change"]
    assert vis.rows == [
        [
            METRIC_LABEL[k],
            fmt_rate(out["after"][k]),
            fmt_rate(out["before"][k]),
            fmt_delta(out["deltas"][k]),
        ]
        for k in DELTA_METRICS
    ]
    assert vis.rows[0][1] == "0.67 [0.30, 0.90] n=6"
    assert doc.footer.startswith("Methodology v1 · pipeline v")


def test_cmo_sections_agree_with_the_dashboard_functions(
    owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    f = Filters(date_from=NOW - timedelta(days=7), date_to=NOW)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        doc = build_cmo(s, brand, 7, NOW)
        ents = entity_metrics(s, bid, f)
        srcs = sources(s, bid, f)
    assert [sec.heading for sec in doc.sections] == [
        "Period",
        "Visibility",
        "Share of voice",
        "Competitors",
        "Top cited sources",
        "Recommendations",
        "Tasks",
        "Alerts",
    ]
    comp = _table(doc, "Competitors")
    assert [r[0] for r in comp.rows] == [e["name"] for e in ents]
    assert comp.rows[0][1] == fmt_rate(ents[0]["mention_rate"])
    src = _table(doc, "Top cited sources")
    assert src.rows == [
        [x["domain"], x["owner"], str(x["answers"]), str(x["prompts"])]
        for x in srcs[:10]
    ]
    assert _table(doc, "Recommendations").rows == [
        ["Citation source", "Pitch forbes.com", "0.12"]
    ]
    assert _table(doc, "Tasks").columns == [
        "Task",
        "Owner",
        "Status",
        "Impact",
        "Change",
    ]
    assert _table(doc, "Tasks").rows == [
        [
            "Pitch forbes.com",
            "Priya",
            "impact_measured",
            "improved",
            "+0.20 [+0.10, +0.30] increase",
        ]
    ]
    alerts = _table(doc, "Alerts")
    assert alerts.rows[0][:2] == ["New source", "forbes.com is a new source"]


def test_empty_brand_gets_a_complete_report(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Fresh")
    with tenant_session(org.id) as s:
        doc = build_cmo(s, s.get_one(m.Brand, bid), 7, NOW)
    assert len(doc.sections) == 8
    vis = _table(doc, "Visibility")
    assert vis.rows[0][1] == "— (n=0)"
    assert vis.rows[0][3].startswith("not comparable: ")
    assert _section(doc, "Competitors").blocks[0].kind == "p"
    assert _section(doc, "Tasks").blocks[0].text == "No tasks in this period."


def test_agency_is_client_facing_cmo(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == bid)
            .values(
                report_logo_url="https://nike.com/logo.png",
                report_accent="#112233",
                report_prepared_by="Acme Agency",
            )
        )
    with tenant_session(org.id) as s:
        doc = build_agency(s, s.get_one(m.Brand, bid), 7, NOW)
    assert doc.type == "agency" and doc.title == "Nike visibility report"
    assert doc.branding is not None
    assert doc.branding.model_dump() == {
        "logo_url": "https://nike.com/logo.png",
        "accent": "#112233",
        "prepared_by": "Acme Agency",
    }
    assert doc.sections[0].blocks[-1].text == "Prepared by Acme Agency."
    tasks = _table(doc, "Tasks")
    assert tasks.columns == ["Task", "Status", "Impact", "Change"]
    assert "Priya" not in str(doc.model_dump())
```

Add `from bsi_core.db import system_session, tenant_session` to the imports (replace the earlier `system_session`-only import).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py`
Expected: FAIL with `ImportError: cannot import name 'build_cmo'`.

- [ ] **Step 3: Write the builders**

Append to `packages/core/bsi_core/reports.py`. Add to the imports at the top: `import uuid`, `from collections.abc import Callable`, `from sqlalchemy import select`, `from sqlalchemy.orm import Session`, `from . import models as m`, `from .citations import sources`, `from .competitors import entity_metrics`, `from .metrics import DELTA_METRICS, Filters, brand_deltas, brand_sov`, `from .recommend import top_by_type`. Then:

```python
SOV_ROWS = 10
COMPETITOR_ROWS = 10
SOURCE_ROWS = 10
REC_ROWS = 10


def _opening(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> tuple[Period, list[Section], list[str]]:
    """The Period paragraph, the Visibility table, and the pipeline
    versions seen in either window. Reads brand_deltas so report and
    dashboard agree."""
    out = brand_deltas(s, brand.id, Filters(), days, to)
    period = Period(
        from_=out["after"]["from"],
        to=to,
        compare_from=out["before"]["from"],
    )
    rows = []
    for k in DELTA_METRICS:
        change = (
            fmt_delta(out["deltas"][k])
            if out["comparable"]
            else f"not comparable: {out['reason']}"
        )
        rows.append(
            [
                METRIC_LABEL[k],
                fmt_rate(out["after"][k]),
                fmt_rate(out["before"][k]),
                change,
            ]
        )
    versions = [
        *out["after"]["pipeline_versions"],
        *out["before"]["pipeline_versions"],
    ]
    sections = [
        Section(
            heading="Period",
            blocks=[
                Paragraph(
                    text=(
                        f"{fmt_day(period.from_)} to {fmt_day(to)}, "
                        f"compared with {fmt_day(period.compare_from)} "
                        f"to {fmt_day(period.from_)}. Each rate is "
                        "value [95% interval] n=answers."
                    )
                )
            ],
        ),
        Section(
            heading="Visibility",
            blocks=[
                Table(
                    columns=["Metric", "This period", "Prior period", "Change"],
                    rows=rows,
                )
            ],
        ),
    ]
    return period, sections, versions


def _window(period: Period) -> Filters:
    return Filters(date_from=period.from_, date_to=period.to)


def _open_recommendations(
    s: Session, brand_id: uuid.UUID, types: tuple[str, ...] | None = None
) -> list[m.Recommendation]:
    q = (
        select(m.Recommendation)
        .where(
            m.Recommendation.brand_id == brand_id,
            m.Recommendation.status == "open",
        )
        .order_by(m.Recommendation.priority.desc(), m.Recommendation.id)
    )
    if types is not None:
        q = q.where(m.Recommendation.type.in_(types))
    return list(s.scalars(q))


def _rec_rows(recs: Sequence[m.Recommendation]) -> list[list[str]]:
    return [
        [REC_LABEL.get(r.type, r.type), r.title, f"{r.priority:.2f}"]
        for r in recs[:REC_ROWS]
    ]


def _rec_section(
    heading: str, recs: Sequence[m.Recommendation]
) -> Section:
    return Section(
        heading=heading,
        blocks=[
            table_or_empty(
                ["Type", "Recommendation", "Priority"],
                _rec_rows(recs),
                "open recommendations",
            )
        ],
    )


def _alerts_in(
    s: Session, brand_id: uuid.UUID, period: Period, type_: str | None = None
) -> list[m.Alert]:
    q = (
        select(m.Alert)
        .where(
            m.Alert.brand_id == brand_id,
            m.Alert.created_at >= period.from_,
            m.Alert.created_at < period.to,
        )
        .order_by(m.Alert.created_at.desc(), m.Alert.id)
    )
    if type_ is not None:
        q = q.where(m.Alert.type == type_)
    return list(s.scalars(q))


def _alert_rows(alerts: Sequence[m.Alert]) -> list[list[str]]:
    return [
        [
            ALERT_LABEL.get(a.type, a.type),
            a.title,
            f"{fmt_day(a.window_from)} to {fmt_day(a.window_to)}",
        ]
        for a in alerts
    ]


def _task_rows(
    s: Session, brand_id: uuid.UUID, period: Period, *, client_facing: bool
) -> list[list[str]]:
    q = (
        select(m.Task)
        .where(
            m.Task.brand_id == brand_id,
            (m.Task.done_at.is_(None)) | (m.Task.done_at >= period.from_),
        )
        .order_by(m.Task.created_at.desc(), m.Task.id)
    )
    rows = []
    for t in s.scalars(q):
        impact = t.impact or {}
        row = [
            t.title,
            t.owner or "—",
            t.status,
            t.impact_label or "—",
            fmt_delta(impact.get("delta")),
        ]
        if client_facing:
            del row[1]
        rows.append(row)
    return rows


def build_cmo(
    s: Session,
    brand: m.Brand,
    days: int,
    to: datetime,
    *,
    client_facing: bool = False,
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    sov_rows = [
        [
            r["name"],
            f"{fmt_pct(r['share'])} [{fmt_pct(r['ci_low'])}, "
            f"{fmt_pct(r['ci_high'])}]",
            str(r["mentions"]),
        ]
        for r in brand_sov(s, brand.id, f)[:SOV_ROWS]
    ]
    comp_rows = [
        [
            e["name"],
            fmt_rate(e["mention_rate"]),
            fmt_pct(e["sov"]["value"]),
            fmt_signed(e["sentiment"]["index"]),
        ]
        for e in entity_metrics(s, brand.id, f)[:COMPETITOR_ROWS]
    ]
    src_rows = [
        [x["domain"], x["owner"], str(x["answers"]), str(x["prompts"])]
        for x in sources(s, brand.id, f)[:SOURCE_ROWS]
    ]
    task_columns = ["Task", "Owner", "Status", "Impact", "Change"]
    if client_facing:
        task_columns.remove("Owner")
    sections += [
        Section(
            heading="Share of voice",
            blocks=[
                table_or_empty(
                    ["Entity", "Share [95% interval]", "Mentions"],
                    sov_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Competitors",
            blocks=[
                table_or_empty(
                    ["Entity", "Mention rate", "Share of voice", "Sentiment"],
                    comp_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Top cited sources",
            blocks=[
                table_or_empty(
                    ["Domain", "Owner", "Answers", "Prompts"],
                    src_rows,
                    "cited sources",
                )
            ],
        ),
        _rec_section(
            "Recommendations", top_by_type(_open_recommendations(s, brand.id))
        ),
        Section(
            heading="Tasks",
            blocks=[
                table_or_empty(
                    task_columns,
                    _task_rows(
                        s, brand.id, period, client_facing=client_facing
                    ),
                    "tasks",
                )
            ],
        ),
        Section(
            heading="Alerts",
            blocks=[
                table_or_empty(
                    ["Type", "Alert", "Window"],
                    _alert_rows(_alerts_in(s, brand.id, period)),
                    "alerts",
                )
            ],
        ),
    ]
    if client_facing:
        title = f"{brand.name} visibility report"
        branding = Branding(
            logo_url=brand.report_logo_url,
            accent=brand.report_accent,
            prepared_by=brand.report_prepared_by,
        )
        if brand.report_prepared_by:
            sections[0].blocks.append(
                Paragraph(text=f"Prepared by {brand.report_prepared_by}.")
            )
    else:
        title = f"{brand.name}: CMO summary"
        branding = None
    return Document(
        title=title,
        brand=brand.name,
        type="agency" if client_facing else "cmo",
        period=period,
        branding=branding,
        sections=sections,
        footer=footer(versions, to),
    )


def build_agency(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    return build_cmo(s, brand, days, to, client_facing=True)
```

Note: `top_by_type` takes `ranked` in priority order; `_open_recommendations` orders by priority desc.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py`
Expected: PASS. If the `0.67 [0.30, 0.90] n=6` literal differs in the last digit, print `fmt_rate(out["after"]["mention_rate"])`, confirm it is Wilson for 4/6 (0.6667, [0.3000, 0.9032]) and fix the literal only if the maths agrees.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py tests/integration/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): opening section, CMO and agency builders

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 4: SEO, content and PR builders, copy ban

**Files:**
- Modify: `packages/core/bsi_core/reports.py` (append)
- Test: `tests/integration/test_reports.py` (append)

**Interfaces:**
- Consumes: `gaps.clusters(s, brand_id, f)` rows with `topic, intent, key, prompts, brand, top_rival, gap, brief`; `metrics.prompt_metrics(s, brand_id, f)` rows with `topic, brand (rate), top_competitor`; `metrics._where(brand_id, f)`; `m.SiteAudit.checks` items with `code, ok, severity, observed, expected`; `m.PageAudit.score/suggestions`.
- Produces: `build_seo`, `build_content`, `build_pr` (same signature as `build_cmo` without `client_facing`), `BUILDERS: dict[str, Builder]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_reports.py` (add `build_content, build_pr, build_seo, BUILDERS` to the `bsi_core.reports` import and `from tests.unit.test_recommend_copy import FORBIDDEN`):

```python
def _audits(owner, org, bid):
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                checks=[
                    {
                        "code": "robots_ok",
                        "ok": True,
                        "severity": "high",
                        "observed": "200",
                        "expected": "200",
                        "url": "https://nike.com/robots.txt",
                    },
                    {
                        "code": "llms_txt",
                        "ok": False,
                        "severity": "low",
                        "observed": "404",
                        "expected": "200",
                        "url": "https://nike.com/llms.txt",
                    },
                ],
            )
        )
        s.add(
            m.PageAudit(
                org_id=org.id,
                brand_id=bid,
                url="https://nike.com/best-shoes",
                cluster_key="cluster:commercial:shoes",
                status=200,
                weights_version="v1",
                score=61,
                suggestions={
                    "add": [{"text": "Add an FAQ block"}],
                    "remove": [],
                    "rewrite": [],
                    "evidence_to_add": [],
                },
            )
        )


def test_seo_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        doc = build_seo(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Cited sources",
        "Site audit",
        "Page citability",
        "Content gaps",
        "Recommendations",
    ]
    src = _table(doc, "Cited sources")
    assert src.columns == ["Domain", "Owner", "Answers", "Prompts", "Gap"]
    assert _table(doc, "Site audit").rows == [
        ["nike.com", "llms_txt", "low", "404 (expected 200)"]
    ]
    assert _table(doc, "Page citability").rows == [
        ["https://nike.com/best-shoes", "cluster:commercial:shoes", "61"]
    ]
    assert _table(doc, "Recommendations").rows[0][1] == "Pitch forbes.com"


def test_content_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        doc = build_content(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Prompt performance by topic",
        "Content gaps",
        "Page citability",
        "Recommendations",
    ]
    topics = _table(doc, "Prompt performance by topic")
    assert topics.columns == ["Topic", "Prompts", "Mention rate", "Top rival"]
    assert topics.rows == [["untopiced", "1", "0.67 [0.30, 0.90] n=6", "Adidas"]]
    assert _table(doc, "Page citability").rows == [
        ["https://nike.com/best-shoes", "61", "Add an FAQ block"]
    ]
    assert _section(doc, "Recommendations").blocks[0].kind == "p"


def test_pr_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        doc = build_pr(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Sentiment mix",
        "Negative mentions",
        "Competitor sentiment",
        "Third-party sources naming the brand",
        "New sources",
    ]
    mix = _table(doc, "Sentiment mix")
    assert mix.rows == [["neutral", "3", "75.0%"], ["negative", "1", "25.0%"]]
    neg = _table(doc, "Negative mentions")
    assert len(neg.rows) == 1 and neg.rows[0][1] == "best shoes"
    third = _table(doc, "Third-party sources naming the brand")
    assert third.rows == [["forbes.com", "6", "1"]]
    assert _table(doc, "New sources").rows == [
        ["forbes.com", "forbes.com is a new source", f"{(NOW - timedelta(days=7)).strftime('%Y-%m-%d')} to {NOW.strftime('%Y-%m-%d')}"]
    ]


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_copy_never_promises(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        docs = [b(s, brand, 7, NOW) for b in BUILDERS.values()]
    assert set(BUILDERS) == set(m.REPORT_TYPES)
    for doc in docs:
        for text_ in _strings(doc.model_dump(mode="json", by_alias=True)):
            low = text_.lower()
            assert not any(w in low for w in FORBIDDEN), (doc.type, text_)
            assert "bsi" not in low and "lumenca" not in low, text_
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py`
Expected: FAIL with `ImportError: cannot import name 'build_seo'`.

- [ ] **Step 3: Write the builders**

Append to `reports.py`. Add imports: `from collections import Counter`, `from sqlalchemy import text`, `from .gaps import clusters`, `from .metrics import _where, prompt_metrics`. Then:

```python
SEO_SOURCE_ROWS = 20
GAP_ROWS = 10
NEGATIVE_ROWS = 20
SEO_REC_TYPES = (
    "pursue_citation_source",
    "fix_crawlability",
    "fix_entity",
    "optimize_page",
)
CONTENT_REC_TYPES = ("create_content", "optimize_page")


def _latest_site_audits(s: Session, brand_id: uuid.UUID) -> list[m.SiteAudit]:
    """The latest audit per currently declared domain (the Site tab's
    query)."""
    q = (
        select(m.SiteAudit)
        .join(
            m.Domain,
            (m.Domain.brand_id == m.SiteAudit.brand_id)
            & (m.Domain.host == m.SiteAudit.domain),
        )
        .where(m.SiteAudit.brand_id == brand_id)
        .order_by(
            m.SiteAudit.domain,
            m.SiteAudit.created_at.desc(),
            m.SiteAudit.id.desc(),
        )
        .distinct(m.SiteAudit.domain)
    )
    return list(s.scalars(q))


def _latest_page_audits(s: Session, brand_id: uuid.UUID) -> list[m.PageAudit]:
    """The latest scored audit per (cluster, url), best score first."""
    q = (
        select(m.PageAudit)
        .where(m.PageAudit.brand_id == brand_id)
        .order_by(
            m.PageAudit.cluster_key,
            m.PageAudit.url,
            m.PageAudit.created_at.desc(),
            m.PageAudit.id.desc(),
        )
        .distinct(m.PageAudit.cluster_key, m.PageAudit.url)
    )
    rows = [a for a in s.scalars(q) if a.score is not None]
    rows.sort(key=lambda a: (-(a.score or 0), a.url))
    return rows


def _gap_rows(s: Session, brand_id: uuid.UUID, f: Filters) -> list[dict[str, Any]]:
    return [c for c in clusters(s, brand_id, f) if c["gap"]][:GAP_ROWS]


def build_seo(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    src_rows = [
        [
            x["domain"],
            x["owner"],
            str(x["answers"]),
            str(x["prompts"]),
            "yes" if x["gap"] else "no",
        ]
        for x in sources(s, brand.id, f)[:SEO_SOURCE_ROWS]
    ]
    audit_rows = [
        [
            a.domain,
            str(c.get("code", "")),
            str(c.get("severity", "")),
            f"{c.get('observed', '')} (expected {c.get('expected', '')})",
        ]
        for a in _latest_site_audits(s, brand.id)
        for c in a.checks
        if not c.get("ok", True)
    ]
    page_rows = [
        [a.url, a.cluster_key, str(a.score)]
        for a in _latest_page_audits(s, brand.id)
    ]
    gap_rows = [
        [
            c["topic"],
            str(len(c["prompts"])),
            fmt_rate(c["brand"]),
            (
                f"{c['top_rival']['name']} {fmt_rate(c['top_rival'])}"
                if c["top_rival"]
                else "—"
            ),
        ]
        for c in _gap_rows(s, brand.id, f)
    ]
    sections += [
        Section(
            heading="Cited sources",
            blocks=[
                table_or_empty(
                    ["Domain", "Owner", "Answers", "Prompts", "Gap"],
                    src_rows,
                    "cited sources",
                )
            ],
        ),
        Section(
            heading="Site audit",
            blocks=[
                table_or_empty(
                    ["Domain", "Check", "Severity", "Observed"],
                    audit_rows,
                    "failing site checks",
                )
            ],
        ),
        Section(
            heading="Page citability",
            blocks=[
                table_or_empty(
                    ["URL", "Cluster", "Score"], page_rows, "scored pages"
                )
            ],
        ),
        Section(
            heading="Content gaps",
            blocks=[
                table_or_empty(
                    ["Topic", "Prompts", "Brand mention rate", "Top rival"],
                    gap_rows,
                    "content gaps",
                )
            ],
        ),
        _rec_section(
            "Recommendations",
            _open_recommendations(s, brand.id, SEO_REC_TYPES),
        ),
    ]
    return Document(
        title=f"{brand.name}: SEO report",
        brand=brand.name,
        type="seo",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


def _topic_rows(s: Session, brand_id: uuid.UUID, f: Filters) -> list[list[str]]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for p in prompt_metrics(s, brand_id, f):
        by_topic.setdefault(p["topic"] or "untopiced", []).append(p)
    rows = []
    for topic, ps in sorted(by_topic.items()):
        n = sum(p["brand"]["n"] for p in ps)
        # rate() stores k/n; k is recovered exactly by rounding.
        k = sum(round(p["brand"]["value"] * p["brand"]["n"]) for p in ps if p["brand"]["value"] is not None)
        tops = Counter(
            p["top_competitor"]["name"] for p in ps if p["top_competitor"]
        )
        top = tops.most_common(1)[0][0] if tops else "—"
        rows.append([topic, str(len(ps)), fmt_rate(rate(k, n)), top])
    return rows


def build_content(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    gap_rows = []
    for c in _gap_rows(s, brand.id, f):
        b = c["brief"] or {}
        gap_rows.append(
            [
                c["topic"],
                str(b.get("page_type", "—")),
                "; ".join(b.get("structure", [])[:3]) or "—",
                str(b.get("prompts_total", len(c["prompts"]))),
            ]
        )
    page_rows = []
    for a in _latest_page_audits(s, brand.id):
        sug = a.suggestions or {}
        first = next(
            (
                str(x.get("text", ""))
                for key in ("add", "rewrite", "remove", "evidence_to_add")
                for x in sug.get(key, [])
                if x.get("text")
            ),
            "—",
        )
        page_rows.append([a.url, str(a.score), first])
    sections += [
        Section(
            heading="Prompt performance by topic",
            blocks=[
                table_or_empty(
                    ["Topic", "Prompts", "Mention rate", "Top rival"],
                    _topic_rows(s, brand.id, f),
                    "answered prompts",
                )
            ],
        ),
        Section(
            heading="Content gaps",
            blocks=[
                table_or_empty(
                    ["Topic", "Page type", "Structure", "Prompts"],
                    gap_rows,
                    "content gaps",
                )
            ],
        ),
        Section(
            heading="Page citability",
            blocks=[
                table_or_empty(
                    ["URL", "Score", "Next step"], page_rows, "scored pages"
                )
            ],
        ),
        _rec_section(
            "Recommendations",
            _open_recommendations(s, brand.id, CONTENT_REC_TYPES),
        ),
    ]
    return Document(
        title=f"{brand.name}: content report",
        brand=brand.name,
        type="content",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


_MENTIONS = (
    "FROM mention mn JOIN observation o ON o.id = mn.observation_id "
    "WHERE o.status = 'done' AND mn.entity_type = 'brand' AND "
)


def build_pr(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    where, params = _where(brand.id, f)
    mix = s.execute(
        text(
            "SELECT mn.sentiment, count(*) AS k "
            + _MENTIONS
            + where
            + " GROUP BY mn.sentiment ORDER BY k DESC, mn.sentiment"
        ),
        params,
    ).all()
    total = sum(r.k for r in mix)
    mix_rows = [
        [r.sentiment, str(r.k), fmt_pct(r.k / total if total else None)]
        for r in mix
    ]
    negatives = s.execute(
        text(
            "SELECT o.requested_at, p.text, mn.evidence_sentence "
            "FROM mention mn JOIN observation o ON o.id = mn.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            "WHERE o.status = 'done' AND mn.entity_type = 'brand' "
            "AND mn.sentiment = 'negative' AND "
            + where
            + " ORDER BY o.requested_at DESC, mn.id LIMIT :cap"
        ),
        {**params, "cap": NEGATIVE_ROWS},
    ).all()
    neg_rows = [
        [fmt_day(r.requested_at), r.text, r.evidence_sentence or "—"]
        for r in negatives
    ]
    comp_rows = [
        [
            e["name"],
            fmt_rate(e["sentiment"]["positive"]),
            fmt_rate(e["sentiment"]["negative"]),
            fmt_signed(e["sentiment"]["index"]),
        ]
        for e in entity_metrics(s, brand.id, f)[:COMPETITOR_ROWS]
    ]
    third_rows = [
        [x["domain"], str(x["answers"]), str(x["prompts"])]
        for x in sources(s, brand.id, f)
        if x["brand_named"] and x["owner"] == "third_party"
    ][:SEO_SOURCE_ROWS]
    new_rows = [
        [
            str(a.detail.get("domain", a.subject_key)),
            a.title,
            f"{fmt_day(a.window_from)} to {fmt_day(a.window_to)}",
        ]
        for a in _alerts_in(s, brand.id, period, "new_source")
    ]
    sections += [
        Section(
            heading="Sentiment mix",
            blocks=[
                table_or_empty(
                    ["Sentiment", "Mentions", "Share"], mix_rows, "mentions"
                )
            ],
        ),
        Section(
            heading="Negative mentions",
            blocks=[
                table_or_empty(
                    ["Date", "Prompt", "Evidence"],
                    neg_rows,
                    "negative mentions",
                )
            ],
        ),
        Section(
            heading="Competitor sentiment",
            blocks=[
                table_or_empty(
                    ["Entity", "Positive", "Negative", "Index"],
                    comp_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Third-party sources naming the brand",
            blocks=[
                table_or_empty(
                    ["Domain", "Answers", "Prompts"],
                    third_rows,
                    "third-party sources naming the brand",
                )
            ],
        ),
        Section(
            heading="New sources",
            blocks=[
                table_or_empty(
                    ["Domain", "Alert", "Window"], new_rows, "new sources"
                )
            ],
        ),
    ]
    return Document(
        title=f"{brand.name}: PR report",
        brand=brand.name,
        type="pr",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


Builder = Callable[[Session, m.Brand, int, datetime], Document]
BUILDERS: dict[str, Builder] = {
    "cmo": build_cmo,
    "seo": build_seo,
    "content": build_content,
    "pr": build_pr,
    "agency": build_agency,
}
```

Add `rate` to the `.metrics` import for `_topic_rows`. The sentiment-mix query orders `k DESC, mn.sentiment`, which is what makes the test's `[["neutral","3","75.0%"],["negative","1","25.0%"]]` hold.

Note on `_where`: it aliases the observation as `o` and binds `brand_id`; the fragments above join `mention mn` to `observation o`, so its clauses apply unchanged. Only fixed fragments are concatenated.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py`
Expected: PASS. If the `New sources` window literal fails because `NOW` is one minute in the future across midnight, replace the expected cell with `f"{fmt_day(NOW - timedelta(days=7))} to {fmt_day(NOW)}"` (import `fmt_day`).

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py tests/integration/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): SEO, content and PR builders; copy ban test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 5: generate(), definition(), worker sweep

**Files:**
- Modify: `packages/core/bsi_core/reports.py` (append)
- Modify: `apps/workers/bsi_workers/worker.py` (after `scan_due_alerts`; the `main()` loop after `deliver_due_alerts`)
- Test: `tests/integration/test_reports.py` (append), `tests/integration/test_worker.py` (append)

**Interfaces:**
- Produces: `reports.WEEKLY_DAYS = 7`, `reports.MONTHLY_DAYS = 30`, `reports.days_for(cadence) -> int`, `reports.definition(s, org_id, brand_id, type_) -> m.Report` (get-or-create, `ON CONFLICT DO NOTHING`), `reports.generate(s, org_id, brand_id, type_, *, days, to, source) -> m.ReportRun`, `reports.new_token() -> str`, `worker.generate_due_reports() -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_reports.py` (add `definition, generate, days_for` to the reports import, `from bsi_workers.worker import generate_due_reports`, and `from sqlalchemy import select`):

```python
def test_definition_is_created_once(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        a = definition(s, org.id, bid, "cmo")
        b = definition(s, org.id, bid, "cmo")
        assert a.id == b.id and a.cadence == "off"


def test_generate_freezes_the_document(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        run = generate(s, org.id, bid, "cmo", days=7, to=NOW, source="manual")
        run_id, token, doc = run.id, run.share_token, run.document
    assert token is not None and len(token) >= 40
    assert doc["type"] == "cmo" and doc["title"] == "Nike: CMO summary"
    before = Document.model_validate(doc)
    # New answers after generation must not change the stored run.
    p = _prompt(owner, org, bid, "more shoes")
    _answers(owner, org, bid, p, NOW - timedelta(days=1), 6)
    with tenant_session(org.id) as s:
        run = s.get_one(m.ReportRun, run_id)
        assert Document.model_validate(run.document) == before
        assert run.methodology_version == "1"
        assert run.period_to == NOW
        assert run.period_from == NOW - timedelta(days=7)
        assert run.compare_from == NOW - timedelta(days=14)
        assert run.report_id == definition(s, org.id, bid, "cmo").id
        assert s.get_one(m.Report, run.report_id).generated_at is None


def test_days_for():
    assert (days_for("weekly"), days_for("monthly")) == (7, 30)


def test_worker_generates_due_runs_and_stamps(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    other = make_brand(make_org("B"))
    _definition(owner, org, bid, "cmo", "weekly")
    with owner() as s, s.begin():
        s.add(
            m.Report(
                org_id=s.get_one(m.Brand, other).org_id,
                brand_id=other,
                type="pr",
                cadence="monthly",
            )
        )
    assert generate_due_reports() == 2
    with owner() as s:
        runs = s.scalars(select(m.ReportRun)).all()
        stamps = s.scalars(select(m.Report.generated_at)).all()
    assert sorted((r.type, r.source) for r in runs) == [
        ("cmo", "scheduled"),
        ("pr", "scheduled"),
    ]
    pr = next(r for r in runs if r.type == "pr")
    assert pr.period_to - pr.period_from == timedelta(days=30)
    assert all(t is not None for t in stamps)
    assert generate_due_reports() == 0


def test_worker_survives_one_failing_brand(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    a, b = make_brand(org, "A"), make_brand(org, "B")
    _definition(owner, org, a, "cmo", "weekly")
    _definition(owner, org, b, "cmo", "weekly")
    from bsi_core import reports

    real = reports.BUILDERS["cmo"]

    def boom(s, brand, days, to):
        if brand.name == "A":
            raise RuntimeError("boom")
        return real(s, brand, days, to)

    monkeypatch.setitem(reports.BUILDERS, "cmo", boom)
    assert generate_due_reports() == 1
    with owner() as s:
        stamped = s.scalars(
            select(m.Report.brand_id).where(m.Report.generated_at.isnot(None))
        ).all()
    assert stamped == [b]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py`
Expected: FAIL with `ImportError: cannot import name 'definition'`.

- [ ] **Step 3: Write generate and the sweep**

Append to `reports.py` (add `import secrets`, `from datetime import timedelta`, `from sqlalchemy.dialects.postgresql import insert as pg_insert`):

```python
WEEKLY_DAYS = 7
MONTHLY_DAYS = 30


def days_for(cadence: str) -> int:
    return MONTHLY_DAYS if cadence == "monthly" else WEEKLY_DAYS


def new_token() -> str:
    return secrets.token_urlsafe(32)


def definition(
    s: Session, org_id: uuid.UUID, brand_id: uuid.UUID, type_: str
) -> m.Report:
    """The (brand, type) definition row, created with cadence off if
    absent. ON CONFLICT DO NOTHING so two first runs cannot collide."""
    s.execute(
        pg_insert(m.Report)
        .values(org_id=org_id, brand_id=brand_id, type=type_)
        .on_conflict_do_nothing(constraint="uq_report_brand_type")
    )
    return s.scalars(
        select(m.Report).where(
            m.Report.brand_id == brand_id, m.Report.type == type_
        )
    ).one()


def generate(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    type_: str,
    *,
    days: int,
    to: datetime,
    source: str,
) -> m.ReportRun:
    """Build and store one run. SQL only: no HTTP, no model call, no
    spend. Runs inside the caller's tenant session; never stamps
    report.generated_at (the worker does that for scheduled runs)."""
    brand = s.get_one(m.Brand, brand_id)
    rep = definition(s, org_id, brand_id, type_)
    doc = BUILDERS[type_](s, brand, days, to)
    run = m.ReportRun(
        org_id=org_id,
        brand_id=brand_id,
        report_id=rep.id,
        type=type_,
        source=source,
        period_from=to - timedelta(days=days),
        period_to=to,
        compare_from=to - timedelta(days=2 * days),
        document=doc.model_dump(mode="json", by_alias=True),
        methodology_version=METHODOLOGY_VERSION,
        share_token=new_token(),
    )
    s.add(run)
    s.flush()
    return run
```

In `apps/workers/bsi_workers/worker.py`, add `from bsi_core.reports import days_for, generate as generate_report` to the imports, and after `scan_due_alerts`:

```python
def generate_due_reports() -> int:
    """Generate every due scheduled report; returns how many were made.

    SQL only, no spend, so it runs inline like the alert scan. The stamp
    is set in the same transaction as the run, so a failed build leaves
    the definition due. One brand's failure never stops the others.
    """
    with system_session() as s:
        due = s.execute(
            text(
                "SELECT report_id, brand_id, org_id, report_type, cadence "
                "FROM due_report_runs()"
            )
        ).all()
    done = 0
    for report_id, brand_id, org_id, report_type, cadence in due:
        try:
            with tenant_session(org_id) as s:
                generate_report(
                    s,
                    org_id,
                    brand_id,
                    report_type,
                    days=days_for(cadence),
                    to=datetime.now(UTC),
                    source="scheduled",
                )
                s.get_one(m.Report, report_id).generated_at = func.now()
            log.info("brand %s: %s report generated", brand_id, report_type)
            done += 1
        except Exception:
            log.exception("brand %s %s report failed", brand_id, report_type)
    return done
```

In `main()`, after the `deliver_due_alerts` try block:

```python
            try:
                log.info("generated %d reports", generate_due_reports())
            except Exception:
                log.exception("generate_due_reports failed")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_reports.py tests/integration/test_worker.py`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py apps/workers/bsi_workers/worker.py tests/integration/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): generate runs on demand and on schedule

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 6: PDF renderer

**Files:**
- Create: `packages/core/bsi_core/pdf.py`
- Modify: `packages/core/pyproject.toml` (add `"reportlab>=4.2"`), `pyproject.toml` (mypy override)
- Test: `tests/unit/test_pdf.py`

**Interfaces:**
- Consumes: `reports.Document`.
- Produces: `pdf.render_pdf(doc: Document) -> bytes`.

- [ ] **Step 1: Add the dependency**

In `packages/core/pyproject.toml` add `"reportlab>=4.2",` to `dependencies`. In the root `pyproject.toml` after `[tool.mypy]`:

```toml
[[tool.mypy.overrides]]
module = ["reportlab.*"]
ignore_missing_imports = true
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv sync` (this updates `uv.lock`; commit it with the task).

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_pdf.py`:

```python
import re
import time
from datetime import UTC, datetime

from bsi_core.pdf import render_pdf
from bsi_core.reports import (
    Branding,
    Document,
    Paragraph,
    Period,
    Section,
    Table,
)

AT = datetime(2026, 9, 25, tzinfo=UTC)
PAGE = re.compile(rb"/Type\s*/Page(?!s)")


def _doc(rows: int, sections: int = 1, branding=None) -> Document:
    table = Table(
        columns=["Domain", "Owner", "Answers"],
        rows=[[f"site-{i}.example.com/a/long/path", "third_party", str(i)] for i in range(rows)],
    )
    return Document(
        title="Nike: CMO summary",
        brand="Nike",
        type="cmo",
        period=Period(from_=AT, to=AT, compare_from=AT),
        branding=branding,
        sections=[
            Section(heading=f"Section {j}", blocks=[Paragraph(text="p & <q>"), table])
            for j in range(sections)
        ],
        footer="Methodology v1 · pipeline v2",
    )


def test_small_document_is_one_page_pdf():
    pdf = render_pdf(_doc(3))
    assert pdf.startswith(b"%PDF-") and len(PAGE.findall(pdf)) == 1


def test_long_table_spans_pages():
    assert len(PAGE.findall(render_pdf(_doc(300)))) > 1


def test_branding_accent_and_escaping_do_not_break_rendering():
    pdf = render_pdf(_doc(2, branding=Branding(accent="#112233", prepared_by="Acme")))
    assert pdf.startswith(b"%PDF-")


def test_twenty_pages_render_within_the_prd_budget():
    start = time.monotonic()
    pdf = render_pdf(_doc(60, sections=12))
    assert time.monotonic() - start < 30
    assert len(PAGE.findall(pdf)) >= 20
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pdf.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsi_core.pdf'`.

- [ ] **Step 4: Write the renderer**

Create `packages/core/bsi_core/pdf.py`:

```python
"""PDF rendering of a report Document with reportlab. Pure function of
the stored document: nothing is fetched and nothing is written to disk.
No logo in the PDF (an image fetch inside a request is out); the accent
colour and the prepared-by line carry the branding."""

import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .reports import Document, fmt_day

MARGIN = 15 * mm
WIDTH = A4[0] - 2 * MARGIN


def render_pdf(doc: Document) -> bytes:
    styles = getSampleStyleSheet()
    accent = (
        colors.HexColor(doc.branding.accent)
        if doc.branding and doc.branding.accent
        else colors.black
    )
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=accent)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent)
    body = styles["BodyText"]
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    footer = doc.footer

    def on_page(canvas: Any, d: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(MARGIN, 10 * mm, footer[:180])
        canvas.drawRightString(A4[0] - MARGIN, 10 * mm, f"page {d.page}")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph(escape(doc.title), h1),
        Paragraph(
            escape(
                f"{fmt_day(doc.period.from_)} to {fmt_day(doc.period.to)}"
            ),
            body,
        ),
        Spacer(1, 4 * mm),
    ]
    for sec in doc.sections:
        blocks = [_block(b, body, cell) for b in sec.blocks]
        story.append(KeepTogether([Paragraph(escape(sec.heading), h2), *blocks[:1]]))
        story += blocks[1:]
        story.append(Spacer(1, 3 * mm))
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=18 * mm,
        title=doc.title,
    )
    pdf.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _block(b: Any, body: ParagraphStyle, cell: ParagraphStyle) -> Any:
    if b.kind == "p":
        return Paragraph(escape(b.text), body)
    data = [[Paragraph(escape(c), cell) for c in b.columns]]
    data += [[Paragraph(escape(c), cell) for c in row] for row in b.rows]
    widths = [WIDTH / len(b.columns)] * len(b.columns)
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pdf.py`
Expected: PASS. If the 20-page test reports fewer pages, raise `sections=12` to `16`; the point is ≥ 20 pages under 30 s.

- [ ] **Step 6: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/pdf.py packages/core/pyproject.toml pyproject.toml uv.lock tests/unit/test_pdf.py && git commit -q -F - <<'EOF'
feat(reports): PDF renderer with reportlab

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 7: Tenant API routes and branding fields

**Files:**
- Create: `apps/api/bsi_api/routers/reports.py`
- Modify: `apps/api/bsi_api/schemas.py` (append), `apps/api/bsi_api/routers/brands.py` (`BrandPatch`, `BrandOut`), `apps/api/bsi_api/main.py` (import + tuple)
- Test: `tests/integration/test_api_reports.py`, `tests/integration/test_isolation.py`

**Interfaces:**
- Consumes: `reports.definition`, `reports.generate`, `reports.new_token`, `reports.WEEKLY_DAYS`, `reports.Document`.
- Produces: routes in the spec's §4 table; schemas `ReportOut(type, cadence, generated_at)`, `CadenceIn(cadence)`, `ReportRunListOut(id, brand_id, type, source, period_from, period_to, compare_from, methodology_version, share_token, created_at)`, `ReportRunOut(ReportRunListOut + document: Document)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_api_reports.py`:

```python
import pytest
from bsi_core import models as m
from sqlalchemy import select

from tests.integration.test_reports import NOW, _definition, _scene  # noqa: F401


def test_list_synthesises_off_for_missing_definitions(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _definition(owner, org, bid, "seo", "monthly", NOW)
    r = client.get(f"/v1/brands/{bid}/reports", headers=org.headers)
    assert r.status_code == 200
    rows = r.json()
    assert [x["type"] for x in rows] == ["cmo", "seo", "content", "pr", "agency"]
    assert [x["cadence"] for x in rows] == ["off", "monthly", "off", "off", "off"]
    assert rows[0]["generated_at"] is None and rows[1]["generated_at"]


def test_put_cadence_upserts_and_resets_the_stamp(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    url = f"/v1/brands/{bid}/reports/cmo"
    r = client.put(url, headers=org.headers, json={"cadence": "weekly"})
    assert r.status_code == 200 and r.json()["cadence"] == "weekly"
    with owner() as s, s.begin():
        rep = s.scalars(select(m.Report)).one()
        rep.generated_at = NOW
    # weekly -> monthly keeps the stamp; off -> anything clears it.
    client.put(url, headers=org.headers, json={"cadence": "monthly"})
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is not None
    client.put(url, headers=org.headers, json={"cadence": "off"})
    with owner() as s, s.begin():
        s.scalars(select(m.Report)).one().generated_at = NOW
    client.put(url, headers=org.headers, json={"cadence": "weekly"})
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is None
    assert (
        client.put(url, headers=org.headers, json={"cadence": "daily"}).status_code
        == 422
    )
    assert (
        client.put(
            f"/v1/brands/{bid}/reports/weekly_digest",
            headers=org.headers,
            json={"cadence": "weekly"},
        ).status_code
        == 422
    )


def test_manual_run_returns_document_and_leaves_the_stamp(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    r = client.post(f"/v1/brands/{bid}/reports/pr/runs", headers=org.headers)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["type"] == "pr" and run["source"] == "manual"
    assert run["document"]["title"] == "Nike: PR report"
    assert run["share_token"] and run["methodology_version"] == "1"
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is None
    assert (
        client.post(f"/v1/brands/{bid}/reports/x/runs", headers=org.headers).status_code
        == 422
    )


def test_archive_is_newest_first_without_documents(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    for t in ("cmo", "seo", "content"):
        client.post(f"/v1/brands/{bid}/reports/{t}/runs", headers=org.headers)
    r = client.get(f"/v1/brands/{bid}/reports/runs", headers=org.headers)
    assert [x["type"] for x in r.json()] == ["content", "seo", "cmo"]
    assert "document" not in r.json()[0]
    two = client.get(
        f"/v1/brands/{bid}/reports/runs?limit=2", headers=org.headers
    )
    assert len(two.json()) == 2
    one = client.get(
        f"/v1/brands/{bid}/reports/runs/{r.json()[2]['id']}",
        headers=org.headers,
    )
    assert one.status_code == 200 and one.json()["document"]["type"] == "cmo"


def test_share_and_revoke(client, owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    run = client.post(
        f"/v1/brands/{bid}/reports/cmo/runs", headers=org.headers
    ).json()
    first = run["share_token"]
    url = f"/v1/brands/{bid}/reports/runs/{run['id']}/share"
    assert client.delete(url, headers=org.headers).status_code == 204
    listed = client.get(
        f"/v1/brands/{bid}/reports/runs", headers=org.headers
    ).json()
    assert listed[0]["share_token"] is None
    again = client.post(url, headers=org.headers)
    assert again.status_code == 200
    assert again.json()["share_token"] not in (None, first)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"report_logo_url": "https://nike.com/logo.png"}, 200),
        ({"report_logo_url": "http://nike.com/logo.png"}, 422),
        ({"report_accent": "#1A2b3C"}, 200),
        ({"report_accent": "red"}, 422),
        ({"report_prepared_by": "x" * 80}, 200),
        ({"report_prepared_by": "x" * 81}, 422),
        (
            {
                "report_logo_url": None,
                "report_accent": None,
                "report_prepared_by": None,
            },
            200,
        ),
    ],
)
def test_branding_validation(client, make_org, make_brand, body, code):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(f"/v1/brands/{bid}", headers=org.headers, json=body)
    assert r.status_code == code, r.text
    if code == 200:
        for k, v in body.items():
            assert r.json()[k] == v
```

In `tests/integration/test_isolation.py`, in `other` after the alert add:

```python
        rep = m.Report(org_id=b.id, brand_id=bid, type="cmo")
        s.add(rep)
        s.flush()
        run = m.ReportRun(
            org_id=b.id,
            brand_id=bid,
            report_id=rep.id,
            type="cmo",
            source="manual",
            period_from=datetime.now(UTC),
            period_to=datetime.now(UTC),
            compare_from=datetime.now(UTC),
            document={"title": "Secret"},
            methodology_version="1",
            share_token="Secret-token-Secret-token-Secret",
        )
        s.add(run)
        s.flush()
```

Include `"rr": run.id` in the returned dict (the `rid, tid, aid = ...` line becomes `rid, tid, aid, rrid = rec.id, task.id, audit.id, run.id`; add `"rr": rrid`). Append to `CASES`:

```python
    ("GET", "/v1/brands/{b}/reports", None),
    ("PUT", "/v1/brands/{b}/reports/cmo", {"cadence": "weekly"}),
    ("POST", "/v1/brands/{b}/reports/cmo/runs", None),
    ("GET", "/v1/brands/{b}/reports/runs", None),
    ("GET", "/v1/brands/{b}/reports/runs/{rr}", None),
    ("POST", "/v1/brands/{b}/reports/runs/{rr}/share", None),
    ("DELETE", "/v1/brands/{b}/reports/runs/{rr}/share", None),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_reports.py tests/integration/test_isolation.py`
Expected: FAIL (404s on the new paths; branding PATCH returns 200 without the fields, so `r.json()[k]` KeyErrors).

- [ ] **Step 3: Schemas, branding fields, router**

Append to `apps/api/bsi_api/schemas.py` (add `from bsi_core.reports import Document` to its imports):

```python
class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str
    cadence: str
    generated_at: datetime | None


class CadenceIn(BaseModel):
    cadence: Literal["off", "weekly", "monthly"]


class ReportRunListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    type: str
    source: str
    period_from: datetime
    period_to: datetime
    compare_from: datetime
    methodology_version: str
    share_token: str | None
    created_at: datetime


class ReportRunOut(ReportRunListOut):
    document: Document
```

(`Literal` is imported from `typing` in schemas.py already or add it.)

In `apps/api/bsi_api/routers/brands.py`, after `WebhookUrl`:

```python
LogoUrl = Annotated[str, Field(max_length=2000), AfterValidator(_webhook_url)]
Accent = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
```

Add to `BrandPatch`: `report_logo_url: LogoUrl | None = None`, `report_accent: Accent | None = None`, `report_prepared_by: str | None = Field(None, max_length=80)`. Add to `BrandOut`: `report_logo_url: str | None`, `report_accent: str | None`, `report_prepared_by: str | None`. `_patch` already copies every field in `model_fields_set`, so nothing else changes.

Create `apps/api/bsi_api/routers/reports.py`:

```python
"""Reports: cadence per type, manual runs, the archive, share links."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from bsi_core import models as m
from bsi_core.reports import WEEKLY_DAYS, definition, generate, new_token
from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..schemas import CadenceIn, ReportOut, ReportRunListOut, ReportRunOut

router = APIRouter(prefix="/brands/{brand_id}/reports", tags=["reports"])

ReportType = Literal["cmo", "seo", "content", "pr", "agency"]


@router.get("", response_model=list[ReportOut])
def list_reports(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[dict[str, object]]:
    brand_or_404(c, brand_id)
    rows = {
        r.type: r
        for r in c.s.scalars(
            select(m.Report).where(m.Report.brand_id == brand_id)
        )
    }
    return [
        {
            "type": t,
            "cadence": rows[t].cadence if t in rows else "off",
            "generated_at": rows[t].generated_at if t in rows else None,
        }
        for t in m.REPORT_TYPES
    ]


@router.put("/{type}", response_model=ReportOut)
def set_cadence(
    brand_id: uuid.UUID, type: ReportType, body: CadenceIn, c: Ctx = TENANT
) -> m.Report:
    brand_or_404(c, brand_id)
    rep = definition(c.s, c.org_id, brand_id, type)
    if rep.cadence == "off" and body.cadence != "off":
        # Due at once: the first scheduled run follows within a minute.
        rep.generated_at = None
    rep.cadence = body.cadence
    return rep


@router.post("/{type}/runs", status_code=201, response_model=ReportRunOut)
def run_now(
    brand_id: uuid.UUID, type: ReportType, c: Ctx = TENANT
) -> m.ReportRun:
    """Generate now, with the weekly window. SQL only, so it runs inline.
    Does not stamp report.generated_at: an operator's click must not
    defer the scheduled run."""
    brand_or_404(c, brand_id)
    return generate(
        c.s,
        c.org_id,
        brand_id,
        type,
        days=WEEKLY_DAYS,
        to=datetime.now(UTC),
        source="manual",
    )


@router.get("/runs", response_model=list[ReportRunListOut])
def list_runs(
    brand_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    c: Ctx = TENANT,
) -> list[m.ReportRun]:
    brand_or_404(c, brand_id)
    q = (
        select(m.ReportRun)
        .where(m.ReportRun.brand_id == brand_id)
        .order_by(m.ReportRun.created_at.desc(), m.ReportRun.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.get("/runs/{run_id}", response_model=ReportRunOut)
def get_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> m.ReportRun:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    return run


@router.post("/runs/{run_id}/share", response_model=ReportRunOut)
def share_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> m.ReportRun:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    run.share_token = new_token()
    return run


@router.delete("/runs/{run_id}/share", status_code=204)
def revoke_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> Response:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    run.share_token = None
    return Response(status_code=204)
```

Route order matters: FastAPI matches in declaration order, and `/{type}` with `Literal` rejects `runs` with a 422 rather than falling through, so declare `/runs...` routes **before** `/{type}` and `/{type}/runs`. Reorder the file accordingly: `list_reports`, `list_runs`, `get_run`, `share_run`, `revoke_run`, then `set_cadence`, `run_now`.

Register in `main.py`: import `reports` in the routers import list and add `reports.router,` after `alerts.router,` in the tuple.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_reports.py tests/integration/test_isolation.py tests/integration/test_api_alerts.py`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/routers/reports.py apps/api/bsi_api/routers/brands.py apps/api/bsi_api/schemas.py apps/api/bsi_api/main.py tests/integration/test_api_reports.py tests/integration/test_isolation.py && git commit -q -F - <<'EOF'
feat(reports): tenant routes, cadence, archive, share links, branding

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 8: Public routes

**Files:**
- Create: `apps/api/bsi_api/routers/public.py`
- Modify: `apps/api/bsi_api/main.py`
- Test: `tests/integration/test_api_reports.py` (append)

**Interfaces:**
- Consumes: SQL `report_run_by_token`, `pdf.render_pdf`, `ReportRunOut`.
- Produces: `GET /v1/r/{token}` → `ReportRunOut`; `GET /v1/r/{token}.pdf` → `application/pdf`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_api_reports.py` (add `from bsi_core.db import system_session` and `from sqlalchemy import text`):

```python
def _idle_in_transaction() -> int:
    with system_session() as s:
        return s.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                "current_database() AND state LIKE 'idle in transaction%' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar_one()


def test_public_page_and_pdf_follow_the_token(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    run = client.post(
        f"/v1/brands/{bid}/reports/agency/runs", headers=org.headers
    ).json()
    tok = run["share_token"]
    r = client.get(f"/v1/r/{tok}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["document"]["title"] == "Nike visibility report"
    pdf = client.get(f"/v1/r/{tok}.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith(
        'attachment; filename="nike-agency-'
    )
    assert pdf.content.startswith(b"%PDF-")
    assert _idle_in_transaction() == 0
    client.delete(
        f"/v1/brands/{bid}/reports/runs/{run['id']}/share", headers=org.headers
    )
    assert client.get(f"/v1/r/{tok}").status_code == 404
    assert client.get(f"/v1/r/{tok}.pdf").status_code == 404
    new = client.post(
        f"/v1/brands/{bid}/reports/runs/{run['id']}/share", headers=org.headers
    ).json()["share_token"]
    assert client.get(f"/v1/r/{new}").status_code == 200
    assert client.get(f"/v1/r/{tok}").status_code == 404
    assert client.get("/v1/r/unknown-token-unknown-token-x").status_code == 404
    assert client.get("/v1/r/short").status_code == 422
    assert "Secret" not in client.get("/v1/r/unknown-token-unknown-token-x").text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_reports.py -k public`
Expected: FAIL with 404 on `/v1/r/{tok}` (route absent) at the first assert.

- [ ] **Step 3: Write the router**

Create `apps/api/bsi_api/routers/public.py`:

```python
"""Share links: a report run by its token, no API key.

The only cross-tenant read is report_run_by_token(); the run itself is
loaded through a tenant session, so RLS stays in force. The PDF is
rendered after the session closes."""

import re
import uuid
from typing import Annotated

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from bsi_core.pdf import render_pdf
from bsi_core.reports import Document
from fastapi import APIRouter, Path, Response
from sqlalchemy import text

from ..problems import Problem
from ..schemas import ReportRunOut

router = APIRouter(prefix="/r", tags=["public"])

Token = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{20,64}$")]
NO_STORE = {"Cache-Control": "no-store"}


def _run(token: str) -> tuple[m.ReportRun, str]:
    with system_session() as s:
        row = s.execute(
            text("SELECT run_id, org_id FROM report_run_by_token(:t)"),
            {"t": token},
        ).first()
    if row is None:
        raise Problem(404, "Not found")
    with tenant_session(uuid.UUID(str(row.org_id))) as s:
        run = s.get(m.ReportRun, row.run_id)
        if run is None:
            raise Problem(404, "Not found")
        name = s.get_one(m.Brand, run.brand_id).name
        s.expunge(run)
    return run, name


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "brand"


@router.get("/{token}.pdf")
def public_pdf(token: Token) -> Response:
    run, name = _run(token)
    pdf = render_pdf(Document.model_validate(run.document))
    filename = f"{_slug(name)}-{run.type}-{run.period_to:%Y-%m-%d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            **NO_STORE,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/{token}", response_model=ReportRunOut)
def public_run(token: Token, response: Response) -> m.ReportRun:
    run, _ = _run(token)
    response.headers.update(NO_STORE)
    return run
```

`/{token}.pdf` is declared before `/{token}` so a `.pdf` suffix is not swallowed by the JSON route (tokens never contain a dot, so the pattern also keeps them apart). Register `public.router` in `main.py`'s tuple after `reports.router`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_reports.py`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/routers/public.py apps/api/bsi_api/main.py tests/integration/test_api_reports.py && git commit -q -F - <<'EOF'
feat(reports): public share-link routes for the page and the PDF

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 9: Web: generated types, format helpers, Reports tab

**Files:**
- Modify: `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts`, `apps/web/src/lib/types.ts`, `apps/web/src/app/(app)/b/[id]/layout.tsx`
- Create: `apps/web/src/app/(app)/b/[id]/reports/page.tsx`, `apps/web/src/app/(app)/b/[id]/reports/actions.ts`
- Generated: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts`

**Interfaces:**
- Consumes: the Task 7/8 API.
- Produces: `REPORT_TYPE: Record<string, string>`, `reportNote(status)`, types `Report`, `ReportRun`, `ReportDocument`.

- [ ] **Step 1: Regenerate the schema**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen`
Expected: `openapi.json` and `src/lib/schema.d.ts` change; `components["schemas"]` now has `ReportOut`, `ReportRunListOut`, `ReportRunOut`, `Document`, `CadenceIn`.

- [ ] **Step 2: Write the failing vitest tests**

Append to `apps/web/src/lib/format.test.ts` (add `REPORT_TYPE, reportNote` to the import):

```ts
test("reportNote says what the reports forms did", () => {
  expect(reportNote("cadence")).toBe("Schedule saved.");
  expect(reportNote("generated")).toBe("Report generated; it is first in the archive.");
  expect(reportNote("shared")).toBe("New link created; the old one no longer works.");
  expect(reportNote("revoked")).toBe("Link revoked.");
  expect(reportNote("branding")).toBe("Branding saved; it applies to new agency reports.");
  expect(reportNote(undefined)).toBeNull();
  expect(reportNote("constructor")).toBeNull();
});

test("REPORT_TYPE labels every report type", () =>
  expect(REPORT_TYPE).toEqual({
    cmo: "CMO summary",
    seo: "SEO",
    content: "Content",
    pr: "PR",
    agency: "Agency client",
  }));
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm test`
Expected: FAIL (`reportNote` is not exported).

- [ ] **Step 4: Helpers, types, tab, page, actions**

In `format.ts` after `alertNote`:

```ts
export const REPORT_TYPE: Record<string, string> = {
  cmo: "CMO summary",
  seo: "SEO",
  content: "Content",
  pr: "PR",
  agency: "Agency client",
};

const REPORT_NOTES: Record<string, string> = {
  cadence: "Schedule saved.",
  generated: "Report generated; it is first in the archive.",
  shared: "New link created; the old one no longer works.",
  revoked: "Link revoked.",
  branding: "Branding saved; it applies to new agency reports.",
};

/** What the reports forms did. */
export const reportNote = (status: Params[string]) =>
  note(REPORT_NOTES, status);
```

In `types.ts` append:

```ts
export type Report = S["ReportOut"];
export type ReportRun = S["ReportRunListOut"];
export type ReportRunDetail = S["ReportRunOut"];
export type ReportDocument = S["Document"];
```

In `layout.tsx` add `<Link href={`/b/${id}/reports`}>Reports</Link>` after the Alerts link.

Create `apps/web/src/app/(app)/b/[id]/reports/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

const back = (id: string, status: string) =>
  redirect(`/b/${id}/reports?queued=${status}`);

export async function setCadence(form: FormData) {
  const id = String(form.get("brand_id"));
  const type = String(form.get("type"));
  await api(`/brands/${id}/reports/${type}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cadence: String(form.get("cadence")) }),
  });
  back(id, "cadence");
}

export async function generateNow(form: FormData) {
  const id = String(form.get("brand_id"));
  const type = String(form.get("type"));
  await api(`/brands/${id}/reports/${type}/runs`, { method: "POST" });
  back(id, "generated");
}

export async function share(form: FormData) {
  const id = String(form.get("brand_id"));
  const run = String(form.get("run_id"));
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "POST" });
  back(id, "shared");
}

export async function revoke(form: FormData) {
  const id = String(form.get("brand_id"));
  const run = String(form.get("run_id"));
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "DELETE" });
  back(id, "revoked");
}

export async function setBranding(form: FormData) {
  const id = String(form.get("brand_id"));
  const field = (k: string) => {
    const v = String(form.get(k) ?? "").trim();
    return v === "" ? null : v;
  };
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report_logo_url: field("report_logo_url"),
      report_accent: field("report_accent"),
      report_prepared_by: field("report_prepared_by"),
    }),
  });
  back(id, "branding");
}
```

Create `apps/web/src/app/(app)/b/[id]/reports/page.tsx`:

```tsx
import { API_URL, api } from "@/lib/api";
import { REPORT_TYPE, reportNote, type Params } from "@/lib/format";
import type { Brand, Report, ReportRun } from "@/lib/types";
import {
  generateNow,
  revoke,
  setBranding,
  setCadence,
  share,
} from "./actions";

const CADENCES = ["off", "weekly", "monthly"] as const;

export default async function Reports({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [brand, reports, runs] = await Promise.all([
    api<Brand>(`/brands/${id}`),
    api<Report[]>(`/brands/${id}/reports`),
    api<ReportRun[]>(`/brands/${id}/reports/runs`),
  ]);
  const msg = reportNote(sp.queued);
  return (
    <>
      {msg && <p className="muted">{msg}</p>}
      <h2>Schedules</h2>
      <table>
        <thead>
          <tr>
            <th>Report</th>
            <th>Cadence</th>
            <th>Last scheduled run</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.type}>
              <td>{REPORT_TYPE[r.type] ?? r.type}</td>
              <td colSpan={3}>
                <form action={setCadence} className="row">
                  <input type="hidden" name="brand_id" value={id} />
                  <input type="hidden" name="type" value={r.type} />
                  <select name="cadence" defaultValue={r.cadence}>
                    {CADENCES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <span className="muted">
                    {r.generated_at ? r.generated_at.slice(0, 16) : "never"}
                  </span>
                  <button>Save</button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Weekly reports cover the last 7 days against the 7 before; monthly
        the last 30 against the 30 before. The worker generates due reports
        within a minute of them falling due.
      </p>
      <form action={generateNow} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <select name="type" defaultValue="cmo">
          {reports.map((r) => (
            <option key={r.type} value={r.type}>
              {REPORT_TYPE[r.type] ?? r.type}
            </option>
          ))}
        </select>
        <button className="primary">Generate now</button>
        <span className="muted">7-day window, ending now.</span>
      </form>
      <h2>Agency branding</h2>
      <form action={setBranding} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="report_logo_url"
          pattern="https://.*"
          placeholder="https://…/logo.png"
          defaultValue={brand.report_logo_url ?? ""}
        />
        <input
          name="report_accent"
          pattern="#[0-9a-fA-F]{6}"
          placeholder="#1a2b3c"
          defaultValue={brand.report_accent ?? ""}
          size={8}
        />
        <input
          name="report_prepared_by"
          maxLength={80}
          placeholder="Prepared by"
          defaultValue={brand.report_prepared_by ?? ""}
        />
        <button>Save branding</button>
      </form>
      <h2>Archive</h2>
      {runs.length === 0 && <p className="muted">No reports yet.</p>}
      {runs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Report</th>
              <th>Period</th>
              <th>Source</th>
              <th>Created</th>
              <th>Link</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{REPORT_TYPE[r.type] ?? r.type}</td>
                <td className="muted">
                  {r.period_from.slice(0, 10)} – {r.period_to.slice(0, 10)}
                </td>
                <td>{r.source}</td>
                <td className="muted">{r.created_at.slice(0, 16)}</td>
                <td>
                  {r.share_token ? (
                    <>
                      <a href={`/r/${r.share_token}`}>View</a>{" "}
                      <a href={`${API_URL}/v1/r/${r.share_token}.pdf`}>PDF</a>
                    </>
                  ) : (
                    <span className="muted">not shared</span>
                  )}
                </td>
                <td>
                  <form action={share} className="row">
                    <input type="hidden" name="brand_id" value={id} />
                    <input type="hidden" name="run_id" value={r.id} />
                    <button>{r.share_token ? "Re-share" : "Share"}</button>
                  </form>
                  {r.share_token && (
                    <form action={revoke} className="row">
                      <input type="hidden" name="brand_id" value={id} />
                      <input type="hidden" name="run_id" value={r.id} />
                      <button>Revoke</button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
```

`API_URL` is exported by `lib/api.ts` (server-side value; in dev both are localhost, which the findings note as the limit of this slice).

- [ ] **Step 5: Run the web checks**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run typecheck && npm run lint && npm test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/openapi.json apps/web/src/lib/schema.d.ts apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts apps/web/src/lib/types.ts "apps/web/src/app/(app)/b/[id]/layout.tsx" "apps/web/src/app/(app)/b/[id]/reports" && git commit -q -F - <<'EOF'
feat(web): Reports tab with schedules, archive, share links, branding

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 10: Web: public report page and its renderer

**Files:**
- Modify: `apps/web/src/lib/api.ts` (add `publicApi`)
- Create: `apps/web/src/components/ReportBody.tsx`, `apps/web/src/components/ReportBody.test.tsx`, `apps/web/src/app/r/[token]/page.tsx`

**Interfaces:**
- Consumes: `GET /v1/r/{token}` → `ReportRunDetail`.
- Produces: `publicApi<T>(path)`, `ReportBody({ doc, pdfHref })`.

- [ ] **Step 1: Write the failing vitest test**

Create `apps/web/src/components/ReportBody.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { ReportDocument } from "@/lib/types";
import { ReportBody } from "./ReportBody";

const doc: ReportDocument = {
  title: "Nike visibility report",
  brand: "Nike",
  type: "agency",
  period: {
    from: "2026-09-18T09:00:00Z",
    to: "2026-09-25T09:00:00Z",
    compare_from: "2026-09-11T09:00:00Z",
  },
  branding: { logo_url: "https://nike.com/logo.png", accent: "#112233", prepared_by: "Acme" },
  sections: [
    {
      heading: "Visibility",
      blocks: [
        { kind: "p", text: "2026-09-18 to 2026-09-25 & more" },
        {
          kind: "table",
          columns: ["Metric", "This period"],
          rows: [["Mention rate", "0.67 [0.30, 0.90] n=6"]],
        },
      ],
    },
    { heading: "Tasks", blocks: [{ kind: "p", text: "No tasks in this period." }] },
  ],
  footer: "Methodology v1 · pipeline v2",
};

test("renders every heading, cell and the footer, escaped", () => {
  const html = renderToStaticMarkup(
    <ReportBody doc={doc} pdfHref="http://localhost:8000/v1/r/t.pdf" />,
  );
  for (const s of [
    "Nike visibility report",
    "Visibility",
    "Tasks",
    "Metric",
    "This period",
    "Mention rate",
    "0.67 [0.30, 0.90] n=6",
    "No tasks in this period.",
    "Methodology v1 · pipeline v2",
    "&amp; more",
    'href="http://localhost:8000/v1/r/t.pdf"',
    'src="https://nike.com/logo.png"',
    "--accent:#112233",
  ]) {
    expect(html).toContain(s);
  }
});

test("logo renders only for https and never for a missing branding", () => {
  const plain = { ...doc, branding: null };
  expect(renderToStaticMarkup(<ReportBody doc={plain} pdfHref="x" />)).not.toContain("<img");
  const bad = { ...doc, branding: { ...doc.branding!, logo_url: "http://x/l.png" } };
  expect(renderToStaticMarkup(<ReportBody doc={bad} pdfHref="x" />)).not.toContain("<img");
});
```

If `vitest.config.*` does not enable JSX/TSX, check `apps/web/vitest.config.ts` (or `vite.config.ts`); the Next 15 template's vitest config uses `@vitejs/plugin-react` or `esbuild` JSX by default. If the test fails to parse TSX, add `esbuild: { jsx: "automatic" }` to that config and nothing else.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm test`
Expected: FAIL (`Cannot find module './ReportBody'`).

- [ ] **Step 3: Write the component, the helper and the page**

Create `apps/web/src/components/ReportBody.tsx`:

```tsx
import type { CSSProperties } from "react";
import type { ReportDocument } from "@/lib/types";

const https = (u: string | null | undefined) =>
  typeof u === "string" && u.startsWith("https://") ? u : null;

/** Renders a stored report document. Pure: no fetches, no app chrome. */
export function ReportBody({
  doc,
  pdfHref,
}: {
  doc: ReportDocument;
  pdfHref: string;
}) {
  const accent = doc.branding?.accent ?? null;
  const logo = https(doc.branding?.logo_url);
  const style = (accent ? { "--accent": accent } : {}) as CSSProperties;
  return (
    <article className="report" style={style}>
      <header>
        {logo && <img src={logo} alt="" height={40} />}
        <h1>{doc.title}</h1>
        <p className="muted">
          {doc.period.from.slice(0, 10)} to {doc.period.to.slice(0, 10)},
          compared with {doc.period.compare_from.slice(0, 10)} to{" "}
          {doc.period.from.slice(0, 10)}
        </p>
        <p className="no-print">
          <a href={pdfHref}>Download PDF</a>
        </p>
      </header>
      {doc.sections.map((sec) => (
        <section key={sec.heading}>
          <h2>{sec.heading}</h2>
          {sec.blocks.map((b, i) =>
            b.kind === "p" ? (
              <p key={i}>{b.text}</p>
            ) : (
              <table key={i}>
                <thead>
                  <tr>
                    {b.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, j) => (
                    <tr key={j}>
                      {row.map((cell, k) => (
                        <td key={k}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ),
          )}
        </section>
      ))}
      <footer className="muted">{doc.footer}</footer>
    </article>
  );
}
```

Check `ReportDocument["sections"][number]["blocks"][number]` in the generated `schema.d.ts`: openapi-typescript renders the discriminated union as `Paragraph | Table` with `kind: "p"` / `kind: "table"`, so the `b.kind === "p"` narrowing type-checks. If it generated `kind?: "p"`, narrow with `"text" in b` instead.

In `lib/api.ts` append:

```ts
/** Server-side call to a public /v1 route: no cookie, no key. */
export async function publicApi<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}/v1${path}`, { cache: "no-store" });
  if (res.status === 404) notFound();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
```

Create `apps/web/src/app/r/[token]/page.tsx`:

```tsx
import { ReportBody } from "@/components/ReportBody";
import { API_URL, publicApi } from "@/lib/api";
import type { ReportRunDetail } from "@/lib/types";

export default async function PublicReport({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const run = await publicApi<ReportRunDetail>(`/r/${encodeURIComponent(token)}`);
  return (
    <main className="report-page">
      <style>{`
        .report { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
        .report h2 { color: var(--accent, inherit); margin-top: 32px; }
        .report table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .report th, .report td { border: 1px solid #ddd; padding: 4px 6px; text-align: left; vertical-align: top; }
        .report footer { margin-top: 32px; font-size: 12px; }
        @media print { .no-print { display: none; } .report { padding: 0; } }
      `}</style>
      <ReportBody
        doc={run.document}
        pdfHref={`${API_URL}/v1/r/${encodeURIComponent(token)}.pdf`}
      />
    </main>
  );
}
```

The page lives outside `(app)`, so the app layout's navigation and cookie check do not apply; the root `app/layout.tsx` still wraps it (global CSS and `<html>`), which is what we want. If the root layout renders login-only chrome, check `apps/web/src/app/layout.tsx` first and keep the public page free of it.

- [ ] **Step 4: Run the web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`
Expected: PASS (typecheck, lint, vitest, build, gen:check).

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.ts apps/web/src/components/ReportBody.tsx apps/web/src/components/ReportBody.test.tsx "apps/web/src/app/r" && git commit -q -F - <<'EOF'
feat(web): public report page rendering the stored document

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 11: Docs

**Files:**
- Create: `docs/findings-slice15.md`
- Modify: `docs/README.md` (the per-slice index; add the slice-15 spec, plan and findings rows in the same format as slice 14's), `docs/superpowers/specs/2026-09-25-slice15-reports-design.md` (Rulings section: the two planning decisions from Global Constraints, plus any made during execution)

- [ ] **Step 1: Write the findings skeleton**

`docs/findings-slice15.md` with the four sections the other findings files use (`## 1. What was built`, `## 2. Live check`, `## 3. Deferred / decisions`, `## 4. Not covered by tests`). §1 lists the tables, functions, routes, pages and the reportlab dependency. §2 is left as "Filled in by the operator's live check on dev" with the table header `| Type | Pages | Bytes | Seconds |` for the orchestrator to fill (the subagent never touches dev). §3 lists: no logo in the PDF; the PDF link uses the server's `API_URL` (dev-only assumption that the browser can reach it); calendar-month periods; tokens are not rate-limited; the `"untopiced"` label; `k` recovered by rounding in `_topic_rows`. §4 lists: the Next.js public page is tested only through `ReportBody` (the route itself is exercised in the live check).

- [ ] **Step 2: Run both gates**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
```
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
```
Expected: both pass; the pytest count is 1302 + the new tests.

- [ ] **Step 3: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice15.md docs/README.md docs/superpowers/specs/2026-09-25-slice15-reports-design.md && git commit -q -F - <<'EOF'
docs: slice 15 findings and index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

## Verification (orchestrator, after the final review)

1. Both gates as in Task 11 step 2.
2. Live check on dev (writes only `report_run` rows; the worker stays stopped): `docker compose up -d`, `uv run alembic upgrade head`, start the API on :8000 and the web app on :3000, then for each type `curl -s -X POST -H "Authorization: Bearer $KEY" localhost:8000/v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/reports/$t/runs | jq -r .share_token`, time `curl -o /tmp/$t.pdf -w '%{size_download} %{time_total}\n' localhost:8000/v1/r/$TOKEN.pdf`, count pages with `grep -ac '/Type /Page' /tmp/$t.pdf`, and open `http://localhost:3000/r/$TOKEN` in the browser pane. Record the table in `docs/findings-slice15.md` §2 as observed.
3. Finishing menu (merge locally / push and PR / keep) before pushing; `gh pr create` with `GH_TOKEN=$(gh auth token -u aiagencyindia-lab)`; watch `gh pr checks N --watch`; merge only on the user's say-so.
