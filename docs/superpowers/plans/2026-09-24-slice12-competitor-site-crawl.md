# Slice 12: Competitor Site Crawl — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawl each active competitor's declared domains weekly (a sitemap snapshot plus a small page sample), store rival URLs with first- and last-seen dates, and show new pages and new structured data. They appear in their own Competitors-tab section and as evidence on change-feed entries.

**Architecture:**
- A pure module, `bsi_core/rivals.py`, turns one domain into a `Snapshot` using an injected fetch. It also answers `site_changes()` from two new RLS tables, `rival_crawl` and `rival_page`.
- A budgeted worker job, `crawl_rivals`, is queued weekly by a SECURITY DEFINER `due_rival_crawls()`. It reads, fetches with no transaction open, then writes.
- `competitors.visibility_changes` attaches each entry's rival site changes.
- The API and the Competitors tab expose all of it.
- A read-only script runs the live check.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, stdlib `xml.etree`/`json`/`time`, and the existing `crawl.http_fetch` SSRF-guarded fetcher. Frontend: Next.js 15 Server Components with server actions, openapi-typescript and vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-slice12-competitor-site-crawl-design.md`

## Global Constraints

- Python 3.13. ruff line length 80. `mypy --strict` over `packages/core/bsi_core`.
- **Tenant tables:** every tenant table has `org_id` and RLS via `_protect()` (ENABLE + FORCE, a `tenant` policy with USING and WITH CHECK, and grants to bsi_app). Each one is listed in `TENANT_TABLES` and populated in `org_b` (`tests/integration/test_rls.py`).
- **Routes:** every id-taking route has a `CASES` row in `tests/integration/test_isolation.py` plus an owner-2xx test. A foreign id returns 404.
- **Cross-tenant work** goes only through SECURITY DEFINER functions called from `system_session()`.
- **Transactions:** none may be open during an HTTP fetch.
- **SQL:** only fixed fragments are concatenated; every value is bound. Integer constants for LIMIT are fine.
- **No model spend in this slice.** `JOB_ESTIMATES["crawl_rivals"] = 0`.
- **Frontend:**
  - Server Components and server actions only, with no `"use client"`. The API key lives only in `lib/api.ts`.
  - The frontend sorts nothing and computes no statistic.
  - A link renders only when its URL starts with `http://` or `https://`, and carries `rel="noreferrer"`.
- **Tests:** expectations are computed from fixtures. Tests never touch the network; every fetch is an injected fake. Never touch the dev DB `bsi` in tests. Never run `worker.main()` or `worker.tick()`.
- **Commits:** use the trailer from the current session reminder (`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). Work on branch `slice12-competitor-site-crawl` (already created; spec committed).
- **Gate after every task:**
  ```bash
  cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  ```
  Web tasks also run `cd apps/web && npm run gate`.
- **Shell:** the cwd resets after every command. Prefix each command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Deviations from the spec, decided while planning (binding):**
  - (a) `rival_crawl` also gets a `baseline bool` column, so "new structured data" can exclude types first seen on a baseline crawl, per competitor, across domains.
  - (b) Feed evidence costs **two** statements for the whole feed (one over `rival_page`, one over `rival_crawl`), not one.
  - (c) Sitemap completeness means: the root element closed with no parse error, and every queued sitemap was read within `MAX_SITEMAP_FETCHES = 11` (the root sitemap plus 10 children). This catches truncation at the 512 KiB cap without a byte count.
  - (d) robots.txt answering 5xx or unreachable (status 0) means no sitemap or page fetches for that domain. The snapshot is `complete=False` with an error. A 4xx means no restrictions (RFC 9309 §2.3.1).

---

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0015_rival_crawl.py` | `rival_crawl` and `rival_page` tables with RLS; `due_rival_crawls()` |
| `packages/core/bsi_core/models.py` | `RivalCrawl` and `RivalPage` ORM classes |
| `packages/core/bsi_core/rivals.py` (new) | `parse_sitemap`, `snapshot_domain`, `Snapshot`, `with_deadline`, `OutOfTime`, `site_changes`, `feed_evidence` |
| `apps/workers/bsi_workers/worker.py` | `run_rival_crawl`, `queue_due_rival_crawls`, runner entry, `main()` call |
| `packages/core/bsi_core/competitors.py` | feed entries gain `new_pages` and `new_types` |
| `apps/api/bsi_api/routers/competitors.py`, `schemas.py` | `POST /competitors/crawl`, `GET /competitors/site-changes`, and the `ChangeOut` fields |
| `apps/web/src/app/(app)/b/[id]/competitors/{page.tsx,actions.ts}`, `lib/{format,types}.ts` | web |
| `scripts/snapshot_rival.py` (new) | read-only live check |
| `tests/unit/test_rivals.py`, `tests/integration/test_rival_crawl.py` (new); `test_rls.py`, `test_isolation.py`, `test_competitors.py`, `test_api_competitors.py` | tests |
| `docs/findings-slice12.md`, `docs/README.md` | findings |

---

### Task 1: Migration 0015, models, RLS

**Files:**
- Create: `migrations/versions/0015_rival_crawl.py`
- Modify: `packages/core/bsi_core/models.py` (after `PageAudit`)
- Modify: `tests/integration/test_rls.py` (`TENANT_TABLES`, `org_b`)
- Test: `tests/integration/test_rival_crawl.py` (new; due-function tests only in this task)

**Interfaces:**
- Produces:
  - `m.RivalCrawl(org_id, brand_id, competitor_id, job_id, domain, baseline, complete, urls_seen, new_urls, fetches, errors: list[str], types: dict[str, str])`
  - `m.RivalPage(org_id, brand_id, competitor_id, domain, url, first_seen_at, last_seen_at, baseline, types: list[str] | None)`
  - SQL `due_rival_crawls() RETURNS TABLE(brand_id uuid, org_id uuid)`
  - Constant `RIVAL_DAYS = 7` inside the migration.

- [ ] **Step 1: Failing tests**

In `tests/integration/test_rls.py`, append `"rival_crawl"` and `"rival_page"` to `TENANT_TABLES`. In `org_b`, after the `PageAudit` add (use the competitor `comp` already created there; read the fixture to confirm its variable name):

```python
        s.flush()
        s.add_all(
            [
                m.RivalCrawl(
                    org_id=b.id,
                    brand_id=bid,
                    competitor_id=comp.id,
                    domain="rival.com",
                    baseline=True,
                    complete=True,
                ),
                m.RivalPage(
                    org_id=b.id,
                    brand_id=bid,
                    competitor_id=comp.id,
                    domain="rival.com",
                    url="https://rival.com/p",
                    baseline=True,
                ),
            ]
        )
```

Create `tests/integration/test_rival_crawl.py`:

```python
"""Competitor site crawl (PRD F07): what is due, what the job stores,
and what counts as a change."""

from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import func, text, update


def _rival(owner, org, bid, name="Adidas", domains=("adidas.co.in",),
           status="active"):
    with owner() as s, s.begin():
        c = m.Competitor(org_id=org.id, brand_id=bid, name=name,
                         domains=list(domains), status=status)
        s.add(c)
        s.flush()
        return c.id


def _crawl(owner, org, bid, cid, domain, days_ago, baseline=False, types=None):
    with owner() as s, s.begin():
        c = m.RivalCrawl(org_id=org.id, brand_id=bid, competitor_id=cid,
                         domain=domain, baseline=baseline, complete=True,
                         types=types or {})
        s.add(c)
        s.flush()
        s.execute(
            update(m.RivalCrawl).where(m.RivalCrawl.id == c.id).values(
                created_at=func.now() - func.make_interval(0, 0, 0, days_ago)
            )
        )
        return c.id


def due():
    with system_session() as s:
        return [r[0] for r in s.execute(
            text("SELECT brand_id FROM due_rival_crawls()"))]


def test_a_brand_with_an_active_rival_domain_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike")
    bare = make_brand(org, "NoRivals")
    _rival(owner, org, bare, domains=())  # no domains: never due
    _rival(owner, org, bare, "Sugg", status="suggested")  # suggested: never
    _rival(owner, org, bid)
    assert due() == [bid]


def test_due_again_after_seven_days(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid)
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=6)
    assert due() == []
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=8)
    assert due() == []  # the 6-day-old crawl is the latest
    with owner() as s, s.begin():
        s.execute(text("DELETE FROM rival_crawl WHERE created_at > "
                       "now() - interval '7 days'"))
    assert due() == [bid]


def test_each_declared_domain_counts(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("a.com", "b.com"))
    _crawl(owner, org, bid, cid, "a.com", days_ago=1)
    assert due() == [bid]  # b.com never crawled


def test_archived_brands_are_never_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid)
    with owner() as s, s.begin():
        s.execute(update(m.Brand).where(m.Brand.id == bid)
                  .values(status="archived"))
    assert due() == []


def test_never_crawled_brands_come_first(owner, make_org, make_brand):
    org = make_org()
    old = make_brand(org, "Old")
    new = make_brand(org, "New")
    c_old = _rival(owner, org, old)
    _rival(owner, org, new)
    _crawl(owner, org, old, c_old, "adidas.co.in", days_ago=9)
    assert due() == [new, old]


def test_deleting_a_competitor_deletes_its_rows(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid)
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=1)
    with owner() as s, s.begin():
        s.add(m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=cid,
                          domain="adidas.co.in", url="https://adidas.co.in/x",
                          baseline=True))
    with owner() as s, s.begin():
        s.execute(text("DELETE FROM competitor WHERE id = :c"), {"c": cid})
    with owner() as s:
        assert s.scalar(text("SELECT count(*) FROM rival_crawl")) == 0
        assert s.scalar(text("SELECT count(*) FROM rival_page")) == 0
```

Run ruff format on the file after writing it.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rls.py tests/integration/test_rival_crawl.py -x`
Expected: FAIL with `AttributeError: ... has no attribute 'RivalCrawl'`.

- [ ] **Step 3: The migration**

```python
"""rival_crawl and rival_page tables; due_rival_crawls()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
RIVAL_DAYS = 7


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("competitor_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("baseline", sa.Boolean(), server_default="false",
                  nullable=False),
    ]


def _fks() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        # The competitor DELETE route is a hard delete.
        sa.ForeignKeyConstraint(["competitor_id"], ["competitor.id"],
                                ondelete="CASCADE"),
    ]


def upgrade() -> None:
    op.create_table(
        "rival_crawl",
        *_base(),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("complete", sa.Boolean(), server_default="false",
                  nullable=False),
        sa.Column("urls_seen", sa.Integer(), server_default="0",
                  nullable=False),
        sa.Column("new_urls", sa.Integer(), server_default="0",
                  nullable=False),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", postgresql.JSONB(), server_default="[]",
                  nullable=False),
        sa.Column("types", postgresql.JSONB(), server_default="{}",
                  nullable=False),
        *_fks(),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rival_crawl_latest", "rival_crawl",
                    ["brand_id", "competitor_id", "domain", "created_at"])
    _protect("rival_crawl")
    op.create_table(
        "rival_page",
        *_base(),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("types", postgresql.ARRAY(sa.Text())),
        *_fks(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competitor_id", "url"),
    )
    op.create_index("ix_rival_page_new", "rival_page",
                    ["brand_id", "competitor_id", "first_seen_at"])
    _protect("rival_page")
    op.execute(f"""
        CREATE FUNCTION due_rival_crawls()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          -- Due when any active competitor's declared domain has no crawl
          -- in the window. Never-crawled first, then the oldest latest.
          WITH pairs AS (
            SELECT c.brand_id, c.id AS cid, d.domain
            FROM competitor c
            CROSS JOIN LATERAL unnest(c.domains) AS d(domain)
            WHERE c.status = 'active'
          ), latest AS (
            SELECT p.brand_id, p.cid, p.domain,
                   (SELECT max(r.created_at) FROM rival_crawl r
                    WHERE r.competitor_id = p.cid
                      AND r.domain = p.domain) AS last
            FROM pairs p
          )
          SELECT b.id, b.org_id FROM brand b
          JOIN latest l ON l.brand_id = b.id
          WHERE b.status = 'active'
          GROUP BY b.id, b.org_id
          HAVING bool_or(l.last IS NULL
                   OR l.last <= now() - make_interval(days => {RIVAL_DAYS}))
          ORDER BY CASE WHEN bool_and(l.last IS NOT NULL)
                        THEN min(l.last) END NULLS FIRST,
                   b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_rival_crawls() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_rival_crawls() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_rival_crawls()")
    op.drop_table("rival_page")
    op.drop_table("rival_crawl")
```

Run `ruff format` on the file; the long lines above wrap. If mypy complains about the `_base` annotation, drop the annotation: migrations are outside mypy's path. Follow how migration 0014 is written and keep the style consistent.

- [ ] **Step 4: Models**

After `PageAudit` in `models.py` (add `Boolean` to the sqlalchemy imports only if `mapped_column` needs it; plain `Mapped[bool]` works):

```python
class RivalCrawl(Tenant, Base):
    """One crawl of one competitor domain. `baseline`: the domain's first
    crawl, whose pages and types never count as new. `types`: JSON-LD
    @type -> the first URL it was seen on, this crawl."""

    __tablename__ = "rival_crawl"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitor.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    domain: Mapped[str]
    baseline: Mapped[bool] = mapped_column(server_default="false")
    complete: Mapped[bool] = mapped_column(server_default="false")
    urls_seen: Mapped[int] = mapped_column(server_default="0")
    new_urls: Mapped[int] = mapped_column(server_default="0")
    fetches: Mapped[int] = mapped_column(server_default="0")
    errors: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    types: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    __table_args__ = (
        Index(
            "ix_rival_crawl_latest",
            "brand_id",
            "competitor_id",
            "domain",
            "created_at",
        ),
    )


class RivalPage(Tenant, Base):
    """One URL a competitor's sitemap listed; first and last seen."""

    __tablename__ = "rival_page"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitor.id", ondelete="CASCADE")
    )
    domain: Mapped[str]
    url: Mapped[str]
    first_seen_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    baseline: Mapped[bool] = mapped_column(server_default="false")
    types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    __table_args__ = (
        UniqueConstraint("competitor_id", "url"),
        Index(
            "ix_rival_page_new", "brand_id", "competitor_id", "first_seen_at"
        ),
    )
```

`errors` holds a JSON list; `Mapped[list[str]]` maps to `TEXT[]` by default, so the explicit `JSONB` is required. Check that `alembic check` shows no drift (`set -a && source .env && set +a && uv run alembic check`).

- [ ] **Step 5: Migrate dev (up/down/up) and run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && set -a && source .env && set +a && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head && uv run alembic check && uv run pytest -q tests/integration/test_rls.py tests/integration/test_rival_crawl.py`
Expected: the migration applies both ways, there is no drift, and all tests PASS. Do not write rows to dev.

- [ ] **Step 6: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0015_rival_crawl.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_rival_crawl.py && git commit -m "feat(db): rival_crawl and rival_page tables, due_rival_crawls() (0015)"
```

---

### Task 2: `rivals.py`, the snapshot of one domain

**Files:**
- Create: `packages/core/bsi_core/rivals.py`
- Test: `tests/unit/test_rivals.py`

**Interfaces:**
- Consumes (from `bsi_core.crawl`): `BROWSER_UA`, `Fetch`, `Response`, `Head`, `_types`, `_owned_sitemap`, `_robots_groups`, `robots_allows`. From `bsi_core.matching`: `is_owned`, `normalize_domain`.
- Produces:
  - `MAX_SITEMAP_FETCHES = 11`, `MAX_NEW_PAGES = 10`
  - `class OutOfTime(Exception)`
  - `with_deadline(fetch: Fetch, seconds: float, clock: Callable[[], float] = time.monotonic) -> Fetch`: raises `OutOfTime` on a call past the deadline
  - `parse_sitemap(body: str) -> tuple[str, list[tuple[str, str | None]], bool]`: returns (root kind: `"urlset"`, `"sitemapindex"` or another name, [(loc, lastmod)], closed_cleanly)
  - `@dataclass Snapshot(urls: dict[str, str | None], pages: list[dict[str, Any]], domain_types: dict[str, str], complete: bool, errors: list[str], fetches: int, skipped: list[str])`
  - `snapshot_domain(host: str, fetch: Fetch, known: set[str], *, pause: float = 0.0) -> Snapshot`

- [ ] **Step 1: Failing tests**

`tests/unit/test_rivals.py`:

```python
"""Competitor site crawl: sitemap parsing and the per-domain snapshot."""

import pytest
from bsi_core.crawl import BROWSER_UA, Response
from bsi_core.rivals import (
    MAX_NEW_PAGES,
    MAX_SITEMAP_FETCHES,
    OutOfTime,
    parse_sitemap,
    snapshot_domain,
    with_deadline,
)

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*locs):
    rows = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>"
        for u, d in locs
    )
    return f'<?xml version="1.0"?><urlset {NS}>{rows}</urlset>'


def index(*locs):
    rows = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs)
    return f"<sitemapindex {NS}>{rows}</sitemapindex>"


def site(pages, robots="User-agent: *\nAllow: /\n"):
    """A fake fetch over a dict url -> body (str) or Response."""
    calls = []

    def fetch(url, ua):
        calls.append(url)
        assert ua == BROWSER_UA
        if url == "https://r.com/robots.txt" and robots is not None:
            return Response(200, robots)
        v = pages.get(url)
        if v is None:
            return Response(404, "")
        return v if isinstance(v, Response) else Response(200, v)

    fetch.calls = calls
    return fetch


HOME = ('<html><script type="application/ld+json">'
        '{"@type":"Organization"}</script></html>')


def test_parse_urlset_and_index():
    kind, locs, ok = parse_sitemap(urlset(("https://r.com/a", "2026-09-01"),
                                          ("https://r.com/b", None)))
    assert (kind, ok) == ("urlset", True)
    assert locs == [("https://r.com/a", "2026-09-01"), ("https://r.com/b", None)]
    kind, locs, ok = parse_sitemap(index("https://r.com/s1.xml"))
    assert (kind, locs, ok) == ("sitemapindex", [("https://r.com/s1.xml", None)], True)


def test_truncated_or_garbage_sitemap_is_not_clean():
    body = urlset(("https://r.com/a", None), ("https://r.com/b", None))
    kind, locs, ok = parse_sitemap(body[: len(body) - 20])
    assert kind == "urlset" and ok is False
    assert ("https://r.com/a", None) in locs  # what was read is kept
    assert parse_sitemap("\x1f\x8b\x08garbage")[2] is False
    assert parse_sitemap("")[2] is False


def test_snapshot_reads_the_sitemap_home_and_new_pages():
    pages = {
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/old", "2026-01-01"),
            ("https://r.com/new1", "2026-09-02"),
            ("https://r.com/new2", "2026-09-03"),
            ("https://other.com/x", None),  # off-host: dropped
        ),
        "https://r.com/": HOME,
        "https://r.com/new2": '<script type="application/ld+json">'
                              '{"@graph":[{"@type":"Product"}]}</script>',
        "https://r.com/new1": "<p>no schema</p>",
    }
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known={"https://r.com/old"})
    assert set(snap.urls) == {"https://r.com/old", "https://r.com/new1",
                              "https://r.com/new2"}
    assert snap.complete is True and snap.errors == []
    # newest lastmod first; the known URL is never fetched
    assert fetch.calls == ["https://r.com/robots.txt",
                           "https://r.com/sitemap.xml", "https://r.com/",
                           "https://r.com/new2", "https://r.com/new1"]
    assert snap.fetches == len(fetch.calls)
    assert snap.domain_types == {"Organization": "https://r.com/",
                                 "Product": "https://r.com/new2"}
    by_url = {p["url"]: p for p in snap.pages}
    assert by_url["https://r.com/new2"]["types"] == ["Product"]
    assert by_url["https://r.com/new1"]["types"] == []


def test_robots_sitemap_lines_on_host_only():
    robots = ("User-agent: *\nAllow: /\nSitemap: https://evil.com/s.xml\n"
              "Sitemap: https://www.r.com/s.xml\n")
    fetch = site({"https://www.r.com/s.xml": urlset(("https://r.com/a", None)),
                  "https://r.com/": HOME}, robots=robots)
    snap = snapshot_domain("r.com", fetch, known=set())
    assert "https://evil.com/s.xml" not in fetch.calls
    assert "https://r.com/sitemap.xml" not in fetch.calls  # robots named one
    assert set(snap.urls) == {"https://r.com/a"}


def test_index_children_are_capped_and_mark_incomplete():
    children = [f"https://r.com/s{i}.xml" for i in range(MAX_SITEMAP_FETCHES + 2)]
    pages = {"https://r.com/sitemap.xml": index(*children), "https://r.com/": HOME}
    pages |= {u: urlset((u.replace(".xml", "/p"), None)) for u in children}
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known=set())
    sitemap_calls = [u for u in fetch.calls if u.endswith(".xml")]
    assert len(sitemap_calls) == MAX_SITEMAP_FETCHES
    assert snap.complete is False
    assert any("sitemap" in e for e in snap.errors)


def test_failed_child_or_truncated_sitemap_is_incomplete():
    body = urlset(*[(f"https://r.com/p{i}", None) for i in range(5)])
    fetch = site({"https://r.com/sitemap.xml": body[:-30], "https://r.com/": HOME})
    assert snapshot_domain("r.com", fetch, known=set()).complete is False
    fetch = site({"https://r.com/sitemap.xml": index("https://r.com/s1.xml"),
                  "https://r.com/": HOME})  # child 404
    assert snapshot_domain("r.com", fetch, known=set()).complete is False
    fetch = site({"https://r.com/": HOME})  # no sitemap at all
    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.complete is False and snap.urls == {}


def test_new_page_sample_is_capped_and_newest_first():
    locs = [(f"https://r.com/p{i:02d}", f"2026-09-{i + 1:02d}") for i in range(15)]
    pages = {"https://r.com/sitemap.xml": urlset(*locs), "https://r.com/": HOME}
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known=set())
    sampled = [u for u in fetch.calls if "/p" in u]
    assert sampled == [f"https://r.com/p{i:02d}" for i in range(14, 14 - MAX_NEW_PAGES, -1)]
    assert len(snap.urls) == 15  # every URL is still listed


def test_robots_disallowed_pages_are_skipped_not_fetched():
    robots = "User-agent: *\nDisallow: /private\n"
    pages = {"https://r.com/sitemap.xml": urlset(("https://r.com/private/a", "2026-09-09"),
                                                  ("https://r.com/ok", "2026-09-01")),
             "https://r.com/": HOME}
    fetch = site(pages, robots=robots)
    snap = snapshot_domain("r.com", fetch, known=set())
    assert "https://r.com/private/a" not in fetch.calls
    assert snap.skipped == ["https://r.com/private/a"]
    assert "https://r.com/ok" in fetch.calls


def test_robots_disallow_all_fetches_nothing_more():
    fetch = site({"https://r.com/sitemap.xml": urlset(("https://r.com/a", None))},
                 robots="User-agent: *\nDisallow: /\n")
    snap = snapshot_domain("r.com", fetch, known=set())
    assert fetch.calls == ["https://r.com/robots.txt"]
    assert snap.complete is False and snap.errors


@pytest.mark.parametrize("status", [0, 503])
def test_robots_unreachable_or_5xx_stops(status):
    def fetch(url, ua):
        return Response(status, "", "ConnectError" if status == 0 else None)

    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.fetches == 1 and snap.complete is False and snap.errors


def test_robots_4xx_means_no_restrictions():
    fetch = site({"https://r.com/sitemap.xml": urlset(("https://r.com/a", None)),
                  "https://r.com/": HOME}, robots=None)
    snap = snapshot_domain("r.com", fetch, known=set())
    assert set(snap.urls) == {"https://r.com/a"} and snap.complete is True


def test_deadline_wrapper_refuses_late_fetches():
    now = [0.0]
    inner = site({})
    fetch = with_deadline(inner, 10, clock=lambda: now[0])
    fetch("https://r.com/robots.txt", BROWSER_UA)
    now[0] = 11
    with pytest.raises(OutOfTime):
        fetch("https://r.com/", BROWSER_UA)
    assert inner.calls == ["https://r.com/robots.txt"]
```

Run ruff format on the test file after writing it.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsi_core.rivals'`.

- [ ] **Step 3: Implement `rivals.py` (snapshot half)**

```python
"""Competitor site crawl (PRD F07): a weekly snapshot of each active
competitor's declared domains (sitemap URLs plus a small page sample
read for JSON-LD @types), and the changes between snapshots.

snapshot_domain is pure: the caller passes the fetch (the SSRF-guarded
crawl.http_fetch in production), as crawl.audit_domain does."""

import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .crawl import (
    BROWSER_UA,
    Fetch,
    Head,
    Response,
    _owned_sitemap,
    _robots_groups,
    _types,
    robots_allows,
)
from .matching import is_owned, normalize_domain

# The root sitemap plus up to 10 children of an index.
MAX_SITEMAP_FETCHES = 11
MAX_NEW_PAGES = 10


class OutOfTime(Exception):
    """The job's time budget ran out mid-domain; nothing is stored."""


def with_deadline(
    fetch: Fetch,
    seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> Fetch:
    end = clock() + seconds

    def bounded(url: str, ua: str) -> Response:
        if clock() > end:
            raise OutOfTime(url)
        return fetch(url, ua)

    return bounded


def parse_sitemap(
    body: str,
) -> tuple[str, list[tuple[str, str | None]], bool]:
    """(root tag, [(loc, lastmod)], closed cleanly). A body cut at the
    fetch cap, gzip bytes, or malformed XML is not clean; whatever was
    read before the fault is still returned. Namespaces are ignored."""
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    root = ""
    closed = False
    locs: list[tuple[str, str | None]] = []
    loc: str | None = None
    lastmod: str | None = None
    try:
        parser.feed(body)
        for event, el in parser.read_events():
            if not isinstance(el, ET.Element):
                continue
            tag = str(el.tag).rsplit("}", 1)[-1]
            if event == "start":
                if not root:
                    root = tag
                continue
            if tag == "loc":
                loc = (el.text or "").strip()
            elif tag == "lastmod":
                lastmod = (el.text or "").strip() or None
            elif tag in ("url", "sitemap"):
                if loc:
                    locs.append((loc, lastmod))
                loc = lastmod = None
                el.clear()
            elif tag == root:
                closed = True
    except ET.ParseError:
        closed = False
    return root or "none", locs, closed


@dataclass
class Snapshot:
    urls: dict[str, str | None] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)
    domain_types: dict[str, str] = field(default_factory=dict)
    complete: bool = True
    errors: list[str] = field(default_factory=list)
    fetches: int = 0
    skipped: list[str] = field(default_factory=list)


def _page_types(body: str) -> list[str]:
    head = Head()
    head.feed(body)
    found: set[str] = set()
    for script in head.ld:
        try:
            found |= _types(json.loads(script))
        except (ValueError, RecursionError):
            continue
    return sorted(found)


def _on_host(host: str, url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(
        parts.hostname
    ) and is_owned(normalize_domain(parts.hostname or ""), [host])


def snapshot_domain(
    host: str, fetch: Fetch, known: set[str], *, pause: float = 0.0
) -> Snapshot:
    """One competitor domain: robots.txt, its sitemaps (an index followed
    to MAX_SITEMAP_FETCHES in all), the homepage and up to MAX_NEW_PAGES
    URLs not in `known`, newest <lastmod> first. Every fetch after
    robots.txt obeys its `*` group. Raises OutOfTime from a bounded
    fetch; never raises otherwise."""
    snap = Snapshot()

    def get(url: str) -> Response:
        if snap.fetches and pause:
            time.sleep(pause)
        snap.fetches += 1
        return fetch(url, BROWSER_UA)

    robots = get(f"https://{host}/robots.txt")
    if robots.status == 0 or robots.status >= 500:
        snap.complete = False
        snap.errors.append(
            f"robots.txt unavailable ({robots.error or robots.status}): "
            "nothing crawled"
        )
        return snap
    rules = ""
    sitemaps: list[str] = []
    if robots.ok:
        groups = _robots_groups(robots.body)
        rules = "\n".join(
            line for ts, ls in groups if "*" in ts for line in ls
        )
        sitemaps = [
            v.strip()
            for k, v, _ in _robots_lines(robots.body)
            if k == "sitemap" and _owned_sitemap(host, v.strip())
        ]

    def allowed(url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return robots_allows(rules, path)

    if not allowed("/"):
        snap.complete = False
        snap.errors.append("robots.txt disallows / for *: nothing crawled")
        return snap

    queue = sitemaps or [f"https://{host}/sitemap.xml"]
    seen: set[str] = set()
    read = 0
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if read == MAX_SITEMAP_FETCHES:
            snap.complete = False
            snap.errors.append(
                f"sitemap: more than {MAX_SITEMAP_FETCHES} sitemap files; "
                "the rest were not read"
            )
            break
        if not allowed(url):
            snap.skipped.append(url)
            snap.complete = False
            continue
        read += 1
        r = get(url)
        if not r.ok:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: {r.error or r.status}")
            continue
        kind, locs, clean = parse_sitemap(r.body)
        if not clean:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: cut off or not XML")
        if kind == "sitemapindex":
            queue += [loc for loc, _ in locs if _owned_sitemap(host, loc)]
        else:
            for loc, lastmod in locs:
                if _on_host(host, loc):
                    snap.urls[loc] = lastmod

    fresh = sorted(
        (u for u in snap.urls if u not in known),
        key=lambda u: (snap.urls[u] is None, snap.urls[u] or "", u),
    )
    # Newest lastmod first: sort descending on the date, None last.
    fresh = sorted(
        (u for u in fresh if snap.urls[u] is not None),
        key=lambda u: (snap.urls[u] or "", u),
        reverse=True,
    ) + [u for u in fresh if snap.urls[u] is None]
    targets = [f"https://{host}/"]
    for u in fresh:
        if len(targets) > MAX_NEW_PAGES:
            break
        if allowed(u):
            targets.append(u)
        else:
            snap.skipped.append(u)
    for url in targets:
        r = get(url)
        types = _page_types(r.body) if r.ok else []
        snap.pages.append({"url": url, "types": types, "status": r.status})
        for t in types:
            snap.domain_types.setdefault(t, url)
    return snap
```

Import `_robots_lines` from `.crawl` as well; the listing above uses it but it is missing from the import list. Simplify the double sort into one key if you can do it cleanly (the order is: lastmod descending, then URL descending among equal dates, with no-lastmod URLs last in URL order). The test fixes the observable order. `_page_types` must never raise on bad HTML; `HTMLParser.feed` does not raise.

- [ ] **Step 4: Run the tests and confirm they pass; run mypy**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py && uv run mypy`
Expected: PASS. If a test expectation contradicts these rules, fix the code first; change the expectation only when it misreads the spec, and report that in your task report.

- [ ] **Step 5: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/rivals.py tests/unit/test_rivals.py && git commit -m "feat(rivals): per-domain sitemap snapshot with a bounded page sample"
```

---

### Task 3: Worker job `crawl_rivals` and the weekly queue

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py`
- Test: `tests/integration/test_rival_crawl.py` (append)

**Interfaces:**
- Consumes: `m.RivalCrawl`, `m.RivalPage` (Task 1); `rivals.snapshot_domain`, `rivals.with_deadline`, `rivals.OutOfTime`, `rivals.Snapshot` (Task 2); `crawl.PAUSE_SECONDS`, `crawl.http_fetch`; `enqueue_job`.
- Produces:
  - `RIVAL_JOB_SECONDS = 420`, `RIVAL_UPSERT_CHUNK = 2_000`
  - `JOB_ESTIMATES["crawl_rivals"] = 0`
  - `run_rival_crawl(org_id, brand_id, job_id, fetch=http_fetch) -> int` (domains stored)
  - `queue_due_rival_crawls() -> int`

- [ ] **Step 1: Failing tests (append to `test_rival_crawl.py`)**

```python
import bsi_workers.worker as worker
from bsi_core.crawl import Response
from bsi_core.db import tenant_session
from sqlalchemy import select

from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender
from tests.unit.test_rivals import HOME, urlset


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(worker, "PAUSE_SECONDS", 0)


def _fake(sites):
    """sites: host -> {url: body}; robots allow-all everywhere."""
    calls = []

    def fetch(url, ua):
        calls.append(url)
        host = url.split("/")[2]
        if url.endswith("/robots.txt"):
            return Response(200, "User-agent: *\nAllow: /\n")
        body = sites.get(host, {}).get(url)
        return Response(200, body) if body is not None else Response(404, "")

    fetch.calls = calls
    return fetch


def _run(owner, org, bid, fetch):
    jid = _job(owner, org, bid, "crawl_rivals", "queued")
    _, gen, emb = _spender()
    worker.process_job(FakeAdapter(), gen, emb, fetch=fetch)
    return _load_job(owner, jid)


def _pages(owner, cid):
    with owner() as s:
        return {p.url: p for p in s.scalars(
            select(m.RivalPage).where(m.RivalPage.competitor_id == cid))}


def test_first_crawl_is_a_baseline(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    fetch = _fake({"r.com": {
        "https://r.com/sitemap.xml": urlset(("https://r.com/a", "2026-09-01")),
        "https://r.com/": HOME}})
    job = _run(owner, org, bid, fetch)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 0)
    with owner() as s:
        [c] = s.scalars(select(m.RivalCrawl)).all()
    assert (c.domain, c.baseline, c.complete, c.urls_seen, c.new_urls) == (
        "r.com", True, True, 1, 1)
    assert c.types == {"Organization": "https://r.com/"}
    assert c.fetches == len(fetch.calls)
    pages = _pages(owner, cid)
    assert set(pages) == {"https://r.com/a"} and pages["https://r.com/a"].baseline


def test_second_crawl_records_new_pages_not_baseline(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    one = {"https://r.com/sitemap.xml": urlset(("https://r.com/a", None)),
           "https://r.com/": HOME}
    _run(owner, org, bid, _fake({"r.com": one}))
    with owner() as s, s.begin():  # make it due again
        s.execute(update(m.RivalCrawl).values(
            created_at=func.now() - func.make_interval(0, 0, 0, 8)))
    two = {**one, "https://r.com/sitemap.xml": urlset(
        ("https://r.com/a", None), ("https://r.com/b", "2026-09-20"))}
    two["https://r.com/b"] = ('<script type="application/ld+json">'
                              '{"@type":"FAQPage"}</script>')
    fetch = _fake({"r.com": two})
    _run(owner, org, bid, fetch)
    assert "https://r.com/a" not in fetch.calls  # known: not re-sampled
    pages = _pages(owner, cid)
    assert pages["https://r.com/b"].baseline is False
    assert pages["https://r.com/b"].types == ["FAQPage"]
    assert pages["https://r.com/a"].last_seen_at > pages["https://r.com/a"].first_seen_at
    with owner() as s:
        latest = s.scalars(select(m.RivalCrawl).order_by(
            m.RivalCrawl.created_at.desc())).first()
    assert (latest.baseline, latest.new_urls) == (False, 1)


def test_only_due_domains_of_active_rivals_are_crawled(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    fresh = _rival(owner, org, bid, "Fresh", domains=("f.com",))
    _crawl(owner, org, bid, fresh, "f.com", days_ago=1)
    _rival(owner, org, bid, "Sugg", domains=("s.com",), status="suggested")
    _rival(owner, org, bid, "Due", domains=("d.com",))
    fetch = _fake({})
    _run(owner, org, bid, fetch)
    hosts = {u.split("/")[2] for u in fetch.calls}
    assert hosts == {"d.com"}


def test_a_crashing_domain_stores_nothing_and_stays_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("bad.com", "good.com"))

    def fetch(url, ua):
        if "bad.com" in url:
            raise RuntimeError("boom")
        return _fake({"good.com": {"https://good.com/": HOME}})(url, ua)

    job = _run(owner, org, bid, fetch)
    assert job.status == "done"
    with owner() as s:
        assert [c.domain for c in s.scalars(select(m.RivalCrawl))] == ["good.com"]
    assert due() == [bid]


def test_out_of_time_domain_is_not_stored(owner, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("r.com",))
    monkeypatch.setattr(worker, "RIVAL_JOB_SECONDS", -1)  # already late
    job = _run(owner, org, bid, _fake({}))
    assert job.status == "done"
    with owner() as s:
        assert s.scalar(select(func.count()).select_from(m.RivalCrawl)) == 0


def test_writes_are_chunked(owner, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    monkeypatch.setattr(worker, "RIVAL_UPSERT_CHUNK", 3)
    locs = [(f"https://r.com/p{i}", None) for i in range(10)]
    _run(owner, org, bid, _fake({"r.com": {
        "https://r.com/sitemap.xml": urlset(*locs), "https://r.com/": HOME}}))
    assert len(_pages(owner, cid)) == 10


def test_no_transaction_is_open_while_fetching(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("r.com",))
    seen = []

    def fetch(url, ua):
        with owner() as s:
            seen.append(s.scalar(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state = "
                "'idle in transaction' AND pid <> pg_backend_pid()")))
        return Response(200, "")

    _run(owner, org, bid, fetch)
    assert seen and set(seen) == {0}


def test_queue_due_rival_crawls_is_idempotent_within_the_hour(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid)
    assert worker.queue_due_rival_crawls() == 1
    assert worker.queue_due_rival_crawls() == 1
    with owner() as s:
        jobs = s.scalars(select(m.Job).where(m.Job.kind == "crawl_rivals")).all()
    assert len(jobs) == 1 and jobs[0].status == "queued"
```

Move the new imports to the top of the file (ruff enforces this) and run ruff format.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py`
Expected: FAIL. Jobs fail with "unknown kind", and `queue_due_rival_crawls` is missing.

- [ ] **Step 3: Implement**

In `worker.py`, add `from bsi_core.rivals import OutOfTime, snapshot_domain, with_deadline` and `from sqlalchemy.dialects.postgresql import insert as pg_insert` (check whether `insert` is already imported under another name). Then add the constants next to `PAGE_JOB_MICROS`:

```python
# Under claim_job's 10-minute stale cutoff; a domain cut short is not
# stored and stays due for the next hourly pass.
RIVAL_JOB_SECONDS = 420
RIVAL_UPSERT_CHUNK = 2_000  # 8 binds a row: far under the 65,535 limit
```

In `JOB_ESTIMATES`, add `"crawl_rivals": 0,  # HTTP only: no model, no spend`.

After `run_page_audit`:

```python
def _due_rival_domains(
    s: Session, brand_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, bool]]:
    """(competitor_id, domain, never crawled) for the brand's active
    competitors' declared domains with no crawl in 7 days, oldest first."""
    rows = s.execute(
        text(
            "SELECT c.id, d.domain, max(r.created_at) AS last "
            "FROM competitor c "
            "CROSS JOIN LATERAL unnest(c.domains) AS d(domain) "
            "LEFT JOIN rival_crawl r ON r.competitor_id = c.id "
            "  AND r.domain = d.domain "
            "WHERE c.brand_id = :brand AND c.status = 'active' "
            "GROUP BY c.id, d.domain "
            "HAVING max(r.created_at) IS NULL "
            "  OR max(r.created_at) <= now() - interval '7 days' "
            "ORDER BY max(r.created_at) NULLS FIRST, c.id, d.domain"
        ),
        {"brand": brand_id},
    ).all()
    return [(r.id, r.domain, r.last is None) for r in rows]


def run_rival_crawl(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    fetch: Fetch = http_fetch,
) -> int:
    """Snapshot each due competitor domain; returns how many were stored.

    Reads, then fetches with no transaction open, then writes. A domain
    that crashes or runs out of the job's time is not stored and stays
    due. The first crawl of a domain is its baseline."""
    with tenant_session(org_id) as s:
        due = _due_rival_domains(s, brand_id)
        cids = sorted({cid for cid, _, _ in due})
        known: dict[uuid.UUID, set[str]] = {cid: set() for cid in cids}
        for cid, url in s.execute(
            select(m.RivalPage.competitor_id, m.RivalPage.url).where(
                m.RivalPage.competitor_id.in_(cids)
            )
        ).tuples():
            known[cid].add(url)
    bounded = with_deadline(fetch, RIVAL_JOB_SECONDS)
    done = []
    for cid, domain, baseline in due:
        try:
            snap = snapshot_domain(
                domain, bounded, known[cid], pause=PAUSE_SECONDS
            )
        except OutOfTime:
            log.info("brand %s: rival crawl out of time at %s", brand_id, domain)
            break
        except Exception:
            log.exception("brand %s: rival crawl of %s failed", brand_id, domain)
            continue
        done.append((cid, domain, baseline, snap))
    with tenant_session(org_id) as s:
        for cid, domain, baseline, snap in done:
            fresh = [u for u in snap.urls if u not in known[cid]]
            s.add(
                m.RivalCrawl(
                    org_id=org_id,
                    brand_id=brand_id,
                    competitor_id=cid,
                    job_id=job_id,
                    domain=domain,
                    baseline=baseline,
                    complete=snap.complete,
                    urls_seen=len(snap.urls),
                    new_urls=len(fresh),
                    fetches=snap.fetches,
                    errors=snap.errors,
                    types=snap.domain_types,
                )
            )
            sampled = {p["url"]: p["types"] for p in snap.pages}
            rows = [
                {
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "competitor_id": cid,
                    "domain": domain,
                    "url": u,
                    "baseline": baseline,
                    "types": sampled.get(u),
                }
                for u in snap.urls
            ]
            for i in range(0, len(rows), RIVAL_UPSERT_CHUNK):
                stmt = pg_insert(m.RivalPage).values(
                    rows[i : i + RIVAL_UPSERT_CHUNK]
                )
                s.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["competitor_id", "url"],
                        set_={
                            "last_seen_at": func.now(),
                            "types": func.coalesce(
                                stmt.excluded.types, m.RivalPage.types
                            ),
                        },
                    )
                )
    return len(done)


def queue_due_rival_crawls() -> int:
    """Queue a rival crawl for every brand due one; returns how many.
    Same contract as queue_due_crawl_audits."""
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_rival_crawls()")
        ).all()
    queued = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                enqueue_job(
                    s, org_id, brand_id, "crawl_rivals", {},
                    requeue_failed=False,
                )
            queued += 1
        except Exception:
            log.exception("brand %s rival crawl queue failed", brand_id)
    return queued
```

In `runners`, add `"crawl_rivals": lambda: run_rival_crawl(org_id, brand_id, job_id, fetch),`. In `main()`, right after the `queue_due_crawl_audits` try-block, add:

```python
            try:
                log.info("queued %d rival crawls", queue_due_rival_crawls())
            except Exception:
                log.exception("queue_due_rival_crawls failed")
```

The bare `except Exception` around each domain matches `run_crawl_audit`'s pattern. `func` and `Session` come from sqlalchemy; check the existing imports. `stmt.excluded.types` is how you reference the incoming row. `func.now()` in `set_` is evaluated by the database, as the rest of the codebase does. `m.RivalPage.types` refers to the existing row.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py tests/integration/test_crawl_audit.py tests/integration/test_worker.py`
Expected: PASS. If `last_seen_at > first_seen_at` fails because both writes land in the same database second, keep the assertion, and in the test move the first crawl's `rival_page` rows back 8 days (`first_seen_at`/`last_seen_at`) along with the crawl rows. Compute; never loosen.

- [ ] **Step 5: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_rival_crawl.py && git commit -m "feat(worker): crawl_rivals job with a time budget and weekly queue"
```

---

### Task 4: `site_changes()` and feed evidence

**Files:**
- Modify: `packages/core/bsi_core/rivals.py` (append), `packages/core/bsi_core/competitors.py` (`visibility_changes`)
- Test: `tests/integration/test_rival_crawl.py` (append), `tests/integration/test_competitors.py` (append)

**Interfaces:**
- Consumes: the tables (Task 1).
- Produces:
  - `NEW_PAGES_CAP = 20`
  - `site_changes(s: Session, brand_id: uuid.UUID, days: int = 14, to: datetime | None = None) -> dict[str, Any]`, returning
    `{"window": {"start": dt, "to": dt}, "competitors": [{"competitor_id", "name", "new_pages_total", "new_pages": [{"url", "first_seen_at", "types"}], "new_types": [{"type", "url"}], "crawls": [{"domain", "crawled_at", "complete", "urls_seen", "errors"}]}]}`
  - `feed_evidence(s: Session, brand_id: uuid.UUID, cids: list[uuid.UUID], start: datetime, end: datetime) -> dict[uuid.UUID, dict[str, list[str]]]`, mapping each competitor to `{"new_pages": [...], "new_types": [...]}`, using **exactly two statements**.
  - Feed entries gain `new_pages: list[str]` and `new_types: list[str]`.

- [ ] **Step 1: Failing tests**

Append to `test_rival_crawl.py`:

```python
from bsi_core.rivals import NEW_PAGES_CAP, feed_evidence, site_changes


def _page(owner, org, bid, cid, url, days_ago, baseline=False, types=None,
          domain="r.com"):
    with owner() as s, s.begin():
        p = m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=cid,
                        domain=domain, url=url, baseline=baseline, types=types)
        s.add(p)
        s.flush()
        s.execute(update(m.RivalPage).where(m.RivalPage.id == p.id).values(
            first_seen_at=func.now() - func.make_interval(0, 0, 0, days_ago)))


def _changes(org, bid, **kw):
    with tenant_session(org.id) as s:
        return site_changes(s, bid, **kw)


def test_site_changes_lists_new_pages_types_and_crawl_status(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, "Adidas", domains=("r.com",))
    b = _rival(owner, org, bid, "Bata", domains=("b.com",))
    _crawl(owner, org, bid, a, "r.com", days_ago=20, baseline=True,
           types={"Organization": "https://r.com/"})
    _crawl(owner, org, bid, a, "r.com", days_ago=2,
           types={"Organization": "https://r.com/",
                  "FAQPage": "https://r.com/new"})
    _page(owner, org, bid, a, "https://r.com/base", 20, baseline=True)
    _page(owner, org, bid, a, "https://r.com/old", 30)  # before the window
    _page(owner, org, bid, a, "https://r.com/new", 2, types=["FAQPage"])
    _page(owner, org, bid, a, "https://r.com/new0", 1)
    out = _changes(org, bid)
    assert [c["name"] for c in out["competitors"]] == ["Adidas", "Bata"]
    ad = out["competitors"][0]
    assert ad["new_pages_total"] == 2
    assert [p["url"] for p in ad["new_pages"]] == ["https://r.com/new0",
                                                  "https://r.com/new"]
    assert ad["new_pages"][1]["types"] == ["FAQPage"]
    assert ad["new_types"] == [{"type": "FAQPage", "url": "https://r.com/new"}]
    assert [(c["domain"], c["complete"]) for c in ad["crawls"]] == [("r.com", True)]
    bata = out["competitors"][1]
    assert (bata["new_pages_total"], bata["crawls"]) == (0, [])
    assert b == bata["competitor_id"]


def test_new_pages_are_capped_and_types_first_seen_on_baseline_are_not_new(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, domains=("r.com", "s.com"))
    for i in range(NEW_PAGES_CAP + 3):
        _page(owner, org, bid, a, f"https://r.com/p{i:02d}", 3)
    # s.com's baseline crawl lands in the window with a type r.com never
    # had: still not new (baseline).
    _crawl(owner, org, bid, a, "s.com", days_ago=1, baseline=True,
           types={"Product": "https://s.com/"})
    ad = _changes(org, bid)["competitors"][0]
    assert ad["new_pages_total"] == NEW_PAGES_CAP + 3
    assert len(ad["new_pages"]) == NEW_PAGES_CAP
    assert ad["new_types"] == []


def test_feed_evidence_is_windowed_per_competitor_in_two_statements(
    owner, make_org, make_brand
):
    from sqlalchemy import event

    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, "A", domains=("r.com",))
    b = _rival(owner, org, bid, "B", domains=("b.com",))
    _page(owner, org, bid, a, "https://r.com/in", 2)
    _page(owner, org, bid, a, "https://r.com/out", 20)
    _page(owner, org, bid, b, "https://b.com/in", 2, domain="b.com")
    _crawl(owner, org, bid, a, "r.com", days_ago=20, baseline=True)
    _crawl(owner, org, bid, a, "r.com", days_ago=2,
           types={"HowTo": "https://r.com/in"})
    seen = []
    with tenant_session(org.id) as s:
        end = s.scalar(text("SELECT now()"))
        bind = s.get_bind()
        listener = lambda *args: seen.append(args[2])  # noqa: E731
        event.listen(bind, "before_cursor_execute", listener)
        try:
            ev = feed_evidence(s, bid, [a], end - timedelta(days=14), end)
        finally:
            event.remove(bind, "before_cursor_execute", listener)
    assert len(seen) == 2
    assert ev == {a: {"new_pages": ["https://r.com/in"], "new_types": ["HowTo"]}}
```

Append to `tests/integration/test_competitors.py`, reusing the `feed` fixture (competitor A qualifies; its after window is `[NOW−14d, NOW)`):

```python
def test_feed_entries_carry_the_rivals_site_changes(owner, feed):
    org, bid, ids = feed
    with owner() as s, s.begin():
        s.add_all([
            m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=ids["a"],
                        domain="a.com", url="https://a.com/new",
                        first_seen_at=NOW - timedelta(days=3)),
            m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=ids["a"],
                        domain="a.com", url="https://a.com/older",
                        first_seen_at=NOW - timedelta(days=20)),
            m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=ids["b"],
                        domain="b.com", url="https://b.com/new",
                        first_seen_at=NOW - timedelta(days=3)),
        ])
    [a] = changes(org, bid)["changes"]
    assert a["new_pages"] == ["https://a.com/new"]
    assert a["new_types"] == []
```

Add `timedelta` to that file's imports if it is missing. Run ruff format on both files after editing.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py tests/integration/test_competitors.py -k "site_changes or feed_evidence or new_pages or site_changes or carry"`
Expected: FAIL with ImportError or KeyError.

- [ ] **Step 3: Implement**

Append to `rivals.py`, and add `import uuid`, `from datetime import UTC, datetime, timedelta`, `from sqlalchemy import text`, `from sqlalchemy.orm import Session`:

```python
NEW_PAGES_CAP = 20

# @types first seen in [start, end) for a competitor, on a crawl that is
# not a baseline. A type any earlier (or baseline) crawl had is not new.
_FIRST_TYPES = (
    "SELECT r.competitor_id, t.key AS type, "
    "  (array_agg(t.value #>> '{}' ORDER BY r.created_at, r.id))[1] AS url, "
    "  min(r.created_at) AS first_at, "
    "  (array_agg(r.baseline ORDER BY r.created_at, r.id))[1] AS base "
    "FROM rival_crawl r CROSS JOIN LATERAL jsonb_each(r.types) AS t "
    "WHERE r.brand_id = :brand AND r.competitor_id = ANY(:cids) "
    "GROUP BY r.competitor_id, t.key"
)


def feed_evidence(
    s: Session,
    brand_id: uuid.UUID,
    cids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> dict[uuid.UUID, dict[str, list[str]]]:
    """Per competitor: pages first seen in [start, end) (not baseline,
    newest first, capped) and @types first seen there. Two statements."""
    out: dict[uuid.UUID, dict[str, list[str]]] = {
        c: {"new_pages": [], "new_types": []} for c in cids
    }
    if not cids:
        return out
    p = {"brand": brand_id, "cids": cids, "start": start, "end": end}
    for cid, url in s.execute(
        text(
            "SELECT competitor_id, url FROM ("
            "  SELECT competitor_id, url, row_number() OVER ("
            "    PARTITION BY competitor_id "
            "    ORDER BY first_seen_at DESC, url) AS n "
            "  FROM rival_page WHERE brand_id = :brand "
            "  AND competitor_id = ANY(:cids) AND NOT baseline "
            "  AND first_seen_at >= :start AND first_seen_at < :end) x "
            f"WHERE n <= {NEW_PAGES_CAP} ORDER BY competitor_id, n"
        ),
        p,
    ).tuples():
        out[cid]["new_pages"].append(url)
    for cid, type_ in s.execute(
        text(
            f"SELECT competitor_id, type FROM ({_FIRST_TYPES}) f "
            "WHERE NOT base AND first_at >= :start AND first_at < :end "
            "ORDER BY competitor_id, type"
        ),
        p,
    ).tuples():
        out[cid]["new_types"].append(type_)
    return out


def site_changes(
    s: Session,
    brand_id: uuid.UUID,
    days: int = 14,
    to: datetime | None = None,
) -> dict[str, Any]:
    """Every active competitor with its new pages, new @types and each
    declared domain's latest crawl, over [to - days, to). Ordered by new
    pages, then name. Four statements."""
    to = to or datetime.now(UTC)
    start = to - timedelta(days=days)
    rivals = s.execute(
        text(
            "SELECT id, name FROM competitor "
            "WHERE brand_id = :brand AND status = 'active' "
            "ORDER BY name, id"
        ),
        {"brand": brand_id},
    ).all()
    cids = [r.id for r in rivals]
    p = {"brand": brand_id, "cids": cids, "start": start, "end": to}
    pages: dict[uuid.UUID, list[dict[str, Any]]] = {c: [] for c in cids}
    totals: dict[uuid.UUID, int] = {c: 0 for c in cids}
    for r in s.execute(
        text(
            "SELECT competitor_id, url, first_seen_at, types, n, total FROM ("
            "  SELECT competitor_id, url, first_seen_at, types, "
            "    row_number() OVER (PARTITION BY competitor_id "
            "      ORDER BY first_seen_at DESC, url) AS n, "
            "    count(*) OVER (PARTITION BY competitor_id) AS total "
            "  FROM rival_page WHERE brand_id = :brand "
            "  AND competitor_id = ANY(:cids) AND NOT baseline "
            "  AND first_seen_at >= :start AND first_seen_at < :end) x "
            f"WHERE n <= {NEW_PAGES_CAP} ORDER BY competitor_id, n"
        ),
        p,
    ):
        totals[r.competitor_id] = int(r.total)
        pages[r.competitor_id].append(
            {"url": r.url, "first_seen_at": r.first_seen_at,
             "types": list(r.types or [])}
        )
    types: dict[uuid.UUID, list[dict[str, str]]] = {c: [] for c in cids}
    for r in s.execute(
        text(
            f"SELECT competitor_id, type, url FROM ({_FIRST_TYPES}) f "
            "WHERE NOT base AND first_at >= :start AND first_at < :end "
            "ORDER BY competitor_id, type"
        ),
        p,
    ):
        types[r.competitor_id].append({"type": r.type, "url": r.url})
    crawls: dict[uuid.UUID, list[dict[str, Any]]] = {c: [] for c in cids}
    for r in s.execute(
        text(
            "SELECT DISTINCT ON (r.competitor_id, r.domain) r.competitor_id, "
            "r.domain, r.created_at, r.complete, r.urls_seen, r.errors "
            "FROM rival_crawl r JOIN competitor c ON c.id = r.competitor_id "
            "  AND r.domain = ANY(c.domains) "
            "WHERE r.brand_id = :brand AND r.competitor_id = ANY(:cids) "
            "ORDER BY r.competitor_id, r.domain, r.created_at DESC, r.id DESC"
        ),
        p,
    ):
        crawls[r.competitor_id].append(
            {"domain": r.domain, "crawled_at": r.created_at,
             "complete": r.complete, "urls_seen": r.urls_seen,
             "errors": list(r.errors)}
        )
    rows = [
        {
            "competitor_id": r.id,
            "name": r.name,
            "new_pages_total": totals[r.id],
            "new_pages": pages[r.id],
            "new_types": types[r.id],
            "crawls": crawls[r.id],
        }
        for r in rivals
    ]
    rows.sort(key=lambda x: (-x["new_pages_total"], x["name"]))
    return {"window": {"start": start, "to": to}, "competitors": rows}
```

In `competitors.visibility_changes`, just before `entries.sort(...)`:

```python
    if entries:
        from .rivals import feed_evidence  # rivals imports crawl only

        site = feed_evidence(
            s, brand_id, sorted({e["competitor_id"] for e in entries}), mid, to
        )
        for e in entries:
            e.update(site[e["competitor_id"]])
```

A top-level import works too if it creates no cycle (`rivals` imports only `crawl` and `matching`); prefer the top-level import and drop the comment. Entries that fire must always have both keys, and the frontend reads them.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py tests/integration/test_competitors.py tests/integration/test_api_competitors.py && uv run mypy`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/rivals.py packages/core/bsi_core/competitors.py tests/integration/test_rival_crawl.py tests/integration/test_competitors.py && git commit -m "feat(rivals): site_changes and new-page evidence on feed entries"
```

---

### Task 5: API routes, schemas, isolation, types

**Files:**
- Modify: `apps/api/bsi_api/routers/competitors.py`, `apps/api/bsi_api/schemas.py`, `tests/integration/test_isolation.py`, `tests/integration/test_api_competitors.py`, the generated `apps/web/openapi.json` and `apps/web/src/lib/schema.d.ts`

**Interfaces:**
- Consumes: `rivals.site_changes` (Task 4), job kind `crawl_rivals` (Task 3), `queue_suggestion(c, brand_id, kind, params)`, `window_end(f)`, `filters` dependency.
- Produces:
  - `POST /v1/brands/{id}/competitors/crawl` → 202 `QueuedOut`
  - `GET /v1/brands/{id}/competitors/site-changes?days=` → `SiteChangesOut`
  - `ChangeOut.new_pages: list[str] = []` and `new_types: list[str] = []`
  - TS types `SiteChanges`

- [ ] **Step 1: Failing tests**

Append to `tests/integration/test_api_competitors.py` (import `m`, `update`, `select` as needed):

```python
def test_crawl_route_queues_one_job_per_hour(client, owner, scene):  # noqa: F811
    org, bid, _ = scene
    r = client.post(f"/v1/brands/{bid}/competitors/crawl", headers=org.headers)
    assert r.status_code == 202, r.text
    again = client.post(f"/v1/brands/{bid}/competitors/crawl", headers=org.headers)
    assert again.json()["job_id"] == r.json()["job_id"]
    with owner() as s:
        job = s.get(m.Job, r.json()["job_id"])
    assert (job.kind, job.status) == ("crawl_rivals", "queued")


def test_crawl_route_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    org, bid, _ = scene
    with owner() as s, s.begin():
        s.execute(update(m.Brand).where(m.Brand.id == bid).values(status="archived"))
    r = client.post(f"/v1/brands/{bid}/competitors/crawl", headers=org.headers)
    assert r.status_code == 409


def test_site_changes_route(client, owner, scene):  # noqa: F811
    org, bid, _ = scene
    with owner() as s:
        adidas = s.scalar(select(m.Competitor.id).where(
            m.Competitor.brand_id == bid, m.Competitor.name == "Adidas"))
    with owner() as s, s.begin():
        s.add(m.RivalPage(org_id=org.id, brand_id=bid, competitor_id=adidas,
                          domain="adidas.co.in", url="https://adidas.co.in/n"))
    r = client.get(f"/v1/brands/{bid}/competitors/site-changes",
                   headers=org.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["competitors"][0]["name"] == "Adidas"
    assert body["competitors"][0]["new_pages"][0]["url"] == "https://adidas.co.in/n"
    bad = client.get(f"/v1/brands/{bid}/competitors/site-changes",
                     params={"days": 0}, headers=org.headers)
    assert bad.status_code == 422
    refused = client.get(f"/v1/brands/{bid}/competitors/site-changes",
                         params={"date_from": "2026-01-01T00:00:00+00:00"},
                         headers=org.headers)
    assert refused.status_code == 422
```

Read the `scene` fixture in `test_competitors.py` first. Confirm Adidas exists there and is active, and adjust the lookup to the fixture's real names and ids (use its returned ids dict if Adidas is in it). In `test_isolation.py`, add to `CASES`:

```python
    ("POST", "/v1/brands/{b}/competitors/crawl", None),
    ("GET", "/v1/brands/{b}/competitors/site-changes", None),
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_competitors.py -k "crawl or site_changes"`
Expected: FAIL with 404 or 405.

- [ ] **Step 3: Implement**

`schemas.py`, next to `ChangeOut`:

```python
class NewPageOut(BaseModel):
    url: str
    first_seen_at: datetime
    types: list[str]


class NewTypeOut(BaseModel):
    type: str
    url: str


class RivalCrawlStatusOut(BaseModel):
    domain: str
    crawled_at: datetime
    complete: bool
    urls_seen: int
    errors: list[str]


class RivalChangesOut(BaseModel):
    competitor_id: uuid.UUID
    name: str
    new_pages_total: int
    new_pages: list[NewPageOut]
    new_types: list[NewTypeOut]
    crawls: list[RivalCrawlStatusOut]


class SiteChangesWindowOut(BaseModel):
    start: datetime
    to: datetime


class SiteChangesOut(BaseModel):
    window: SiteChangesWindowOut
    competitors: list[RivalChangesOut]
```

Add `new_pages: list[str] = []` and `new_types: list[str] = []` to `ChangeOut`.

`routers/competitors.py`:

```python
@router.post("/competitors/crawl", status_code=202, response_model=QueuedOut)
def queue_rival_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "crawl_rivals", {})


@router.get("/competitors/site-changes", response_model=SiteChangesOut)
def get_site_changes(
    brand_id: uuid.UUID,
    days: int = Query(14, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return site_changes(c.s, brand_id, days, window_end(f))
```

Import `QueuedOut`, `SiteChangesOut`, `queue_suggestion` (from `.runs`), and `site_changes`.

- [ ] **Step 4: Run the tests, regenerate types, run both gates**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_competitors.py tests/integration/test_isolation.py tests/integration/test_competitors.py`
Then `cd apps/web && npm run gen`, add `export type SiteChanges = S["SiteChangesOut"];` to `apps/web/src/lib/types.ts`, stage `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` and `apps/web/src/lib/types.ts`, and run `npm run gate`. Run the Python gate too.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api tests/integration/test_api_competitors.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts apps/web/src/lib/types.ts && git commit -m "feat(api): competitor crawl trigger and site-changes route"
```

---

### Task 6: Web — the site-changes section and feed evidence

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/competitors/actions.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/competitors/page.tsx`, `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts`

**Interfaces:**
- Consumes: `SiteChanges` and `Changes` types (Task 5), `api<T>()`, `note()` in `format.ts`.
- Produces: `crawlRivals(form: FormData)` and `crawlNote(status)`.

- [ ] **Step 1: Failing vitest**

In `format.test.ts`:

```ts
test("crawlNote says what the crawl button actually did", () => {
  const queued = "Queued; the worker crawls competitor sites within a few minutes.";
  expect(crawlNote("queued")).toBe(queued);
  expect(crawlNote("running")).toBe(queued);
  expect(crawlNote("done")).toBe("Already crawled this hour; a new crawl can start from the next hour.");
  expect(crawlNote("failed")).toBe("Queued again after a failed run.");
  expect(crawlNote(undefined)).toBeNull();
  expect(crawlNote("constructor")).toBeNull();
});
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run` → FAIL (`crawlNote` not exported).

- [ ] **Step 2: Implement**

`format.ts`, next to `PAGE_NOTES`:

```ts
const CRAWL_QUEUED = "Queued; the worker crawls competitor sites within a few minutes.";
const CRAWL_NOTES: Record<string, string> = {
  queued: CRAWL_QUEUED,
  running: CRAWL_QUEUED,
  done: "Already crawled this hour; a new crawl can start from the next hour.",
  failed: "Queued again after a failed run.",
};

/** What "Crawl competitor sites now" did, from the job status. */
export const crawlNote = (status: Params[string]) => note(CRAWL_NOTES, status);
```

`competitors/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function crawlRivals(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${id}/competitors/crawl`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/competitors?queued=${encodeURIComponent(job.status)}#site`);
}
```

`page.tsx`:
- Fetch `api<SiteChanges>(`/brands/${id}/competitors/site-changes?days=${FEED_DAYS}`)` inside the existing `Promise.all`.
- Add `const isWeb = (u: string) => u.startsWith("https://") || u.startsWith("http://");`.
- Inside each feed card, after the "New citing domains" line:

```tsx
          {c.new_pages.length > 0 && (
            <p className="muted">
              New pages on their site: {c.new_pages.length}{" "}
              {c.new_pages.slice(0, 5).map((u) =>
                isWeb(u) ? (
                  <a key={u} href={u} rel="noreferrer" style={{ marginRight: 6 }}>
                    {u}
                  </a>
                ) : null,
              )}
            </p>
          )}
          {c.new_types.length > 0 && (
            <p className="muted">New structured data: {c.new_types.join(", ")}</p>
          )}
```

- After the feed section:

```tsx
      <h2 id="site">Competitor site changes</h2>
      <form action={crawlRivals} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Crawl competitor sites now</button>
        {crawlNote(sp.queued) && <span className="muted">{crawlNote(sp.queued)}</span>}
      </form>
      <p className="muted">
        Pages first listed in a competitor&apos;s sitemap and structured data
        first seen between {date(site.window.start)} and {lastDay(site.window.to)}.
        A domain&apos;s first crawl is its baseline and never counts as new.
      </p>
      {site.competitors.every((r) => r.crawls.length === 0) && (
        <p className="muted">
          No crawl yet. Competitor domains are crawled weekly; declare domains
          on each competitor to include them.
        </p>
      )}
      {site.competitors.map((r) => (
        <div className="card" key={r.competitor_id}>
          <h3>{r.name}</h3>
          {r.crawls.length === 0 && <p className="muted">No domain crawled yet.</p>}
          {r.crawls.map((c) => (
            <p key={c.domain} className="muted">
              {c.domain}: crawled {date(c.crawled_at)} · {c.urls_seen} URLs ·{" "}
              {c.complete ? "complete" : "incomplete"}
              {c.errors.length > 0 && ` · ${c.errors.join("; ")}`}
            </p>
          ))}
          <p>{r.new_pages_total} new pages</p>
          {r.new_pages.length > 0 && (
            <ul>
              {r.new_pages.map((p) => (
                <li key={p.url}>
                  {isWeb(p.url) ? (
                    <a href={p.url} rel="noreferrer">{p.url}</a>
                  ) : (
                    p.url
                  )}{" "}
                  {p.types.map((t) => (
                    <span key={t} className="tag">{t}</span>
                  ))}
                </li>
              ))}
            </ul>
          )}
          {r.new_types.length > 0 && (
            <p>
              New structured data:{" "}
              {r.new_types.map((t) =>
                isWeb(t.url) ? (
                  <a key={t.type} href={t.url} rel="noreferrer" className="tag">
                    {t.type}
                  </a>
                ) : (
                  <span key={t.type} className="tag">{t.type}</span>
                ),
              )}
            </p>
          )}
        </div>
      ))}
```

Import `crawlNote`, `SiteChanges`, and `crawlRivals`. The page stays a Server Component.

- [ ] **Step 3: Gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`. Expected: PASS, with no build warnings (read the output).

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src && git commit -m "feat(web): competitor site changes section and feed evidence"
```

---

### Task 7: Read-only live-check script and docs

**Files:**
- Create: `scripts/snapshot_rival.py`, `docs/findings-slice12.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: `rivals.snapshot_domain`, `crawl.http_fetch`, `crawl.PAUSE_SECONDS`.

- [ ] **Step 1: The script**

```python
"""Snapshot one competitor domain, read-only: nothing is stored.

usage: uv run python scripts/snapshot_rival.py <host> [<host> ...]
No model spend; real HTTP fetches to the named hosts."""

import json
import sys

from bsi_core.crawl import PAUSE_SECONDS, http_fetch
from bsi_core.rivals import snapshot_domain

if len(sys.argv) < 2:
    sys.exit(__doc__)
for host in sys.argv[1:]:
    snap = snapshot_domain(host, http_fetch, set(), pause=PAUSE_SECONDS)
    print(
        json.dumps(
            {
                "host": host,
                "urls": len(snap.urls),
                "complete": snap.complete,
                "errors": snap.errors,
                "fetches": snap.fetches,
                "skipped": len(snap.skipped),
                "pages": snap.pages,
                "domain_types": snap.domain_types,
            },
            indent=2,
        )
    )
```

Match the style of the other scripts (read `scripts/score_page.py`). Do not run it against the network; the controller runs the live check.

- [ ] **Step 2: Docs**

Write the skeleton for `docs/findings-slice12.md`, with §1 fully written and §2 as a placeholder:

```markdown
# Findings: slice 12 — competitor site crawl

## 1. What was built
(one paragraph: rivals.py snapshot (robots, sitemap + index ≤ 11 files, homepage + ≤ 10 new pages read for JSON-LD @types, robots `*` obeyed); migration 0015 `rival_crawl`/`rival_page` + `due_rival_crawls()`; job `crawl_rivals` (weekly, 420 s budget, no spend); `site_changes` and feed evidence; `/competitors/crawl` and `/competitors/site-changes`; the Competitors-tab section; `scripts/snapshot_rival.py`.)

## 2. Live check
(to be filled after the live check: per domain — URLs, complete, errors, fetches, sampled types)

## 3. Deferred / decisions
- Removed URLs and lastmod changes are not reported; a domain's first crawl is a baseline.
- gzip sitemaps served without Content-Encoding are marked incomplete, not unzipped.
- A sitemap index is read to 11 files in all; counts are lower bounds when `complete` is false.
- robots.txt 5xx or unreachable: nothing crawled; 4xx: no restrictions (RFC 9309 §2.3.1).
- Pages are fetched with a browser user agent while obeying the `*` robots group.
- No recommendations from site changes; no topic matching of rival pages to clusters.
- Feed entries are still computed on read, not stored; no alerts (F15).
- Feed evidence uses two statements (pages, types) per feed.
- `rival_crawl.baseline` added (not in the spec) so types first seen on a baseline crawl never count as new.
```

Add a slice-12 section to `docs/README.md` with spec, plan and findings rows, in the format the slice-11 entry uses.

- [ ] **Step 3: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add scripts/snapshot_rival.py docs/findings-slice12.md docs/README.md && git commit -m "docs: slice 12 findings skeleton and read-only snapshot script"
```

---

## After the tasks (main session)

1. Run the whole-branch review, then the fix wave, then the scoped re-review (subagent-driven-development).
2. Live check (no model spend; real HTTP, read-only):
   ```bash
   cd /Users/vineet/Downloads/ADK/bsi-platform && uv run python scripts/snapshot_rival.py adidas.co.in bata.com campusshoes.com crocs.in skechers.in
   ```
   Fill in findings §2. Verify that dev's `rival_crawl`/`rival_page` tables and the job queue stay empty.
3. `finishing-a-development-branch`: PR, CI log read, merge only when the user says so, then update memory.
