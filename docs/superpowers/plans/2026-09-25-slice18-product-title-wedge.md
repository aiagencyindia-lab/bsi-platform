# Slice 18 Product-Title Wedge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import a brand's products (CSV or Google Merchant feed), run a batch job that infers each product's generic shopper keyword, compares the product title with the titles that rank for that keyword, and stores a rewritten title with a rule-check badge; show it in a Products tab and export it as CSV.

**Architecture:** Two new RLS tables (`product`, `keyword_search`); pure functions in `bsi_core/products.py` for parsing, voting, missing-keyword detection and the rule check; a `product_run` job in the worker that batches 20 products per model call and searches once per distinct keyword through the grounded engine; a `products` router; a Products tab with the app's second Route Handler for the CSV download.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI, google-genai (through the existing `judge.generate` and `GeminiGroundingAdapter`), stdlib `csv`/`xml.etree`/`zlib`; Next.js 15 App Router, vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-slice18-product-title-wedge-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`; the shell's cwd resets after every command, so every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases; never touch the dev DB, the network or the worker loop. Tests use the shared `bsi_test` DB; check `pgrep -fl pytest` first and never run two suites at once.
- ruff line length 80; `mypy --strict` over `packages/core/bsi_core`.
- Every tenant table: `_protect()` in the migration, `TENANT_TABLES` and `org_b` in `tests/integration/test_rls.py`, a "Secret" row in `tests/integration/test_isolation.py`'s `other` fixture, and a `CASES` row for every id-taking route.
- `tenant_session` opens a transaction and commits on exit. Never `with tenant_session(...) as s, s.begin():`. No transaction may be open during a fetch or a model call.
- SQL: only fixed fragments are concatenated; every value is bound.
- Constants, exact: `MAX_PRODUCTS = 1_000`, `CSV_MAX_BYTES = 4 * 1024 * 1024`, `FEED_CAP_BYTES = 8 * 1024 * 1024`, `BATCH = 20`, `SAMPLES = 3`, `KEYWORD_TEMPERATURE = 0.4`, `MAX_KEYWORDS = 5`, `KEYWORD_CAP = 100`, `SEARCH_TTL_DAYS = 7`, `SEARCH_MICROS = 45_000`, `PRODUCT_JOB_MICROS = 20_000`, `TOP_TITLES = 5`, `MIN_TITLES = 2`, `MAX_MISSING = 8`, `MAX_TITLE_CHARS = 150`, `MAX_BULLETS = 3`, `MAX_BULLET_CHARS = 200`.
- Job kinds `product_run` (estimate `PRODUCT_JOB_MICROS`) and `import_feed` (estimate 0). The search phase re-checks `budget_fits(s, org_id, 0, extra_micros=n_new * SEARCH_MICROS)`; failure = job `failed`, `error = "budget"`, keywords kept.
- Copy (notes, badges, empty state, status line, Problem titles) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain`. Model prompts avoid them too. Test fixtures avoid them.
- Second Route Handler only at `apps/web/src/app/(app)/b/[id]/products/export.csv/route.ts`. The API key stays in `lib/api.ts` (and this route reads the cookie itself).
- After the API lands: `npm run gen`; commit `openapi.json` and `schema.d.ts`.
- Commit trailer: the `Co-Authored-By` line from the latest session reminder.

---

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0019_products.py` | `product`, `keyword_search`, RLS |
| `packages/core/bsi_core/models.py` | `Product`, `KeywordSearch`, `PRODUCT_SOURCES`, `RULE_CHECKS` |
| `packages/core/bsi_core/products.py` | parsing, upsert, export rows, keyword vote, missing, rule check, prompts, schemas, `run_products` |
| `apps/workers/bsi_workers/worker.py` | `run_import_feed`, job kinds, `OverBudget`/`CatalogueCap` error mapping |
| `apps/api/bsi_api/routers/products.py`, `schemas.py`, `main.py` | the products API |
| `apps/web/src/lib/format.ts`, `types.ts`, `next.config.ts` | notes, types, body limit |
| `apps/web/src/app/(app)/b/[id]/layout.tsx`, `products/page.tsx`, `products/actions.ts` | the tab |
| `apps/web/src/app/(app)/b/[id]/products/export.csv/route.ts` (+ test) | the download proxy |
| `tests/unit/test_products.py`, `tests/integration/test_api_products.py`, `tests/integration/test_products_run.py`, additions to `test_rls.py`, `test_isolation.py`, `test_worker.py`, `test_recommend_copy.py` | tests |
| `docs/findings-slice18.md`, `docs/README.md`, spec Rulings, this plan's changes section | docs |

---

### Task 1: Migration 0019 and the models

**Files:**
- Create: `migrations/versions/0019_products.py`
- Modify: `packages/core/bsi_core/models.py` (constants after `RUN_SOURCES`; classes after `ReportRun`)
- Modify: `tests/integration/test_rls.py` (`TENANT_TABLES`, `org_b`)
- Modify: `tests/integration/test_isolation.py` (`other` fixture)

**Interfaces:**
- Produces: `m.Product`, `m.KeywordSearch`, `m.PRODUCT_SOURCES = ("csv", "feed")`, `m.RULE_CHECKS = ("pass", "adjusted")`; constraint names `uq_product_brand_external`, `uq_keyword_search_brand_keyword`.

- [ ] **Step 1: Add the failing RLS entries**

In `tests/integration/test_rls.py`, append `"product"` and `"keyword_search"` to `TENANT_TABLES` after `"report_run"`. In `org_b`, after the `m.ReportRun(...)` add (inside the same `with owner() as s, s.begin():` block, after the report run's `s.add(...)`):

```python
        s.add(
            m.Product(
                org_id=b.id,
                brand_id=bid,
                external_id="b-1",
                title="Org B sandal",
                source="csv",
            )
        )
        s.add(
            m.KeywordSearch(
                org_id=b.id, brand_id=bid, keyword="b sandals", query="b"
            )
        )
```

In `tests/integration/test_isolation.py`'s `other` fixture, before `rid, tid, aid, rrid = ...`:

```python
        s.add(
            m.Product(
                org_id=b.id,
                brand_id=bid,
                external_id="secret-1",
                title="Secret",
                source="csv",
                keyword="secret",
                suggested_title="Secret",
            )
        )
        s.add(
            m.KeywordSearch(
                org_id=b.id,
                brand_id=bid,
                keyword="secret",
                query="secret buy online",
                titles=[{"title": "Secret", "domain": "secret.example"}],
            )
        )
```

- [ ] **Step 2: Run the RLS test to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rls.py -k "tenant_table_list or populates" 2>&1 | tail -5`
Expected: FAIL (`AttributeError: module 'bsi_core.models' has no attribute 'Product'`).

- [ ] **Step 3: Add the constants and models**

In `packages/core/bsi_core/models.py`, after `RUN_SOURCES = ("scheduled", "manual")`:

```python
PRODUCT_SOURCES = ("csv", "feed")
RULE_CHECKS = ("pass", "adjusted")
```

After the `ReportRun` class:

```python
class Product(Tenant, Base):
    """One catalogue item (PRD F16). The catalogue columns are upserted
    on (brand_id, external_id) by every import; the result columns are
    written only by a product_run job, so a re-import keeps them."""

    __tablename__ = "product"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    external_id: Mapped[str]
    title: Mapped[str]
    description: Mapped[str | None]
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    url: Mapped[str | None]
    price: Mapped[str | None]
    category: Mapped[str | None]
    source: Mapped[str]
    imported_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    keyword: Mapped[str | None]
    keywords: Mapped[list[str] | None]
    missing_keywords: Mapped[list[str] | None]
    suggested_title: Mapped[str | None]
    suggested_bullets: Mapped[list[str] | None]
    rule_check: Mapped[str | None]
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    result_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        CheckConstraint(
            _in("source", PRODUCT_SOURCES), name="ck_product_source"
        ),
        CheckConstraint(
            "rule_check IS NULL OR " + _in("rule_check", RULE_CHECKS),
            name="ck_product_rule_check",
        ),
        UniqueConstraint(
            "brand_id", "external_id", name="uq_product_brand_external"
        ),
        Index("ix_product_list", "brand_id", "title"),
    )


class KeywordSearch(Tenant, Base):
    """The cached comparison set for one (brand, keyword): the product
    titles that rank for it, from one grounded answer. Reused for
    SEARCH_TTL_DAYS. This is the seam a SERP provider would replace."""

    __tablename__ = "keyword_search"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    keyword: Mapped[str]
    query: Mapped[str]
    titles: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    model: Mapped[str] = mapped_column(server_default="")
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    searched_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    error: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint(
            "brand_id", "keyword", name="uq_keyword_search_brand_keyword"
        ),
    )
```

- [ ] **Step 4: Write the migration**

`migrations/versions/0019_products.py`:

```python
"""product and keyword_search tables (slice 18, PRD F16)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
PRODUCT_SOURCES = ("csv", "feed")
RULE_CHECKS = ("pass", "adjusted")


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
    op.create_table(
        "product",
        *_row_columns(),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("url", sa.String()),
        sa.Column("price", sa.String()),
        sa.Column("category", sa.String()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("keyword", sa.String()),
        sa.Column("keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("missing_keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("suggested_title", sa.String()),
        sa.Column("suggested_bullets", postgresql.ARRAY(sa.Text())),
        sa.Column("rule_check", sa.String()),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("result_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            _in("source", PRODUCT_SOURCES), name="ck_product_source"
        ),
        sa.CheckConstraint(
            "rule_check IS NULL OR " + _in("rule_check", RULE_CHECKS),
            name="ck_product_rule_check",
        ),
        sa.UniqueConstraint(
            "brand_id", "external_id", name="uq_product_brand_external"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_list", "product", ["brand_id", "title"])
    _protect("product")
    op.create_table(
        "keyword_search",
        *_row_columns(),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column(
            "titles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.String(), server_default="", nullable=False),
        sa.Column(
            "cost_micros", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "searched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.String()),
        sa.UniqueConstraint(
            "brand_id", "keyword", name="uq_keyword_search_brand_keyword"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _protect("keyword_search")


def downgrade() -> None:
    op.drop_table("keyword_search")
    op.drop_table("product")
```

- [ ] **Step 5: Run the RLS and isolation suites**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rls.py tests/integration/test_isolation.py 2>&1 | tail -5`
Expected: all PASS (the test DB migrates to 0019 through `conftest`).

- [ ] **Step 6: Gate the slice so far and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q tests/integration/test_rls.py tests/integration/test_isolation.py tests/integration/test_constraints.py 2>&1 | tail -3`
Expected: clean and PASS.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0019_products.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_isolation.py && git commit -m "feat(products): product and keyword_search tables (migration 0019)"
```

---

### Task 2: Parsing — CSV, Merchant feed, export rows

**Files:**
- Create: `packages/core/bsi_core/products.py` (part 1)
- Create: `tests/unit/test_products.py` (part 1)

**Interfaces:**
- Produces: `parse_attributes(cell: str) -> dict[str, str]`; `parse_csv(text: str) -> tuple[list[dict[str, Any]], int]` (rows, skipped); `parse_feed(body: bytes) -> tuple[list[dict[str, Any]], str | None]` (rows, note); `EXPORT_COLUMNS`; `export_rows(products: Iterable[Any]) -> list[list[str]]`; constants `MAX_PRODUCTS`, `CSV_MAX_BYTES`, `FEED_CAP_BYTES`, `FEED_FETCH`, `CatalogueCap`. A row dict has keys `external_id, title, description, attributes, url, price, category`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_products.py`:

```python
"""Pure functions of the product-title wedge (slice 18)."""

import gzip
import hashlib
from types import SimpleNamespace

from bsi_core.products import (
    EXPORT_COLUMNS,
    export_rows,
    parse_attributes,
    parse_csv,
    parse_feed,
)

CSV = """Title,Id,Description,Attributes,LINK,Price,Category,material
Walkaroo Boys Sandal,W-1,Light sandal,Size: 10; Color: Blue,https://walkaroo.in/p/1,499 INR,Sandals,EVA
No id row,,,,,,,
,W-3,Missing title,,,,,
Url only,,,,https://walkaroo.in/p/4,,,
"""


def test_parse_csv_maps_headers_case_insensitively():
    rows, skipped = parse_csv(CSV)
    assert skipped == 1
    first = rows[0]
    assert first["external_id"] == "W-1"
    assert first["title"] == "Walkaroo Boys Sandal"
    assert first["description"] == "Light sandal"
    assert first["url"] == "https://walkaroo.in/p/1"
    assert first["price"] == "499 INR"
    assert first["category"] == "Sandals"
    assert first["attributes"] == {
        "size": "10",
        "color": "blue",
        "material": "EVA",
    }


def test_parse_csv_external_id_falls_back_to_url_then_title_hash():
    rows, _ = parse_csv(CSV)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Url only"]["external_id"] == "https://walkaroo.in/p/4"
    expected = hashlib.sha1(b"No id row").hexdigest()
    assert by_title["No id row"]["external_id"] == expected
    assert by_title["No id row"]["description"] is None


def test_parse_attributes_splits_on_semicolon_and_colon():
    assert parse_attributes("Size: 10; Color: Blue; junk") == {
        "size": "10",
        "color": "blue",
    }
    assert parse_attributes("") == {}


RSS = b"""<?xml version="1.0"?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0"><channel>
<title>Feed</title>
<item><g:id>F-1</g:id><title>Kids Sandal Red</title>
<description>Soft sandal</description><link>https://x.in/1</link>
<g:price>799.00 INR</g:price><g:product_type>Footwear &gt; Sandals</g:product_type>
<g:color>Red</g:color><g:brand>Walkaroo</g:brand></item>
<item><g:id>F-2</g:id><title>Kids Sandal Blue</title>
<link>https://x.in/2</link><g:google_product_category>187</g:google_product_category>
</item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:g="http://base.google.com/ns/1.0">
<entry><g:id>A-1</g:id><title>Atom sandal</title>
<link href="https://x.in/a1"/><g:price>10 USD</g:price></entry>
</feed>"""


def test_parse_feed_reads_rss_items():
    rows, note = parse_feed(RSS)
    assert note is None
    assert [r["external_id"] for r in rows] == ["F-1", "F-2"]
    first = rows[0]
    assert first["title"] == "Kids Sandal Red"
    assert first["description"] == "Soft sandal"
    assert first["url"] == "https://x.in/1"
    assert first["price"] == "799.00 INR"
    assert first["category"] == "Footwear > Sandals"
    assert first["attributes"] == {"color": "Red", "brand": "Walkaroo"}
    assert rows[1]["category"] == "187"
    assert rows[1]["attributes"] == {}


def test_parse_feed_reads_atom_entries_and_link_href():
    rows, note = parse_feed(ATOM)
    assert note is None
    assert len(rows) == 1
    assert rows[0]["external_id"] == "A-1"
    assert rows[0]["url"] == "https://x.in/a1"
    assert rows[0]["price"] == "10 USD"


def test_parse_feed_inflates_gzip():
    rows, note = parse_feed(gzip.compress(RSS))
    assert note is None and len(rows) == 2


def test_parse_feed_cut_mid_item_keeps_complete_items():
    cut = RSS[: RSS.index(b"<item><g:id>F-2") + 30]
    rows, note = parse_feed(cut)
    assert [r["external_id"] for r in rows] == ["F-1"]
    assert note == "malformed"


def test_export_rows_joins_lists_and_blanks_none():
    p = SimpleNamespace(
        external_id="W-1",
        url=None,
        title="Walkaroo Boys Sandal",
        keyword="kids sandals",
        missing_keywords=["summer", "kids"],
        suggested_title="Walkaroo Kids Summer Sandal for Boys",
        suggested_bullets=["Light EVA sole", "Washable"],
        rule_check="pass",
    )
    q = SimpleNamespace(
        external_id="W-2",
        url="https://walkaroo.in/p/2",
        title="Other",
        keyword=None,
        missing_keywords=None,
        suggested_title=None,
        suggested_bullets=None,
        rule_check=None,
    )
    assert EXPORT_COLUMNS == [
        "external_id",
        "url",
        "title",
        "keyword",
        "missing_keywords",
        "suggested_title",
        "suggested_bullets",
        "rule_check",
    ]
    assert export_rows([p, q]) == [
        [
            "W-1",
            "",
            "Walkaroo Boys Sandal",
            "kids sandals",
            "summer|kids",
            "Walkaroo Kids Summer Sandal for Boys",
            "Light EVA sole|Washable",
            "pass",
        ],
        ["W-2", "https://walkaroo.in/p/2", "Other", "", "", "", "", ""],
    ]
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py 2>&1 | tail -3`
Expected: FAIL (`ModuleNotFoundError: No module named 'bsi_core.products'`).

- [ ] **Step 3: Write products.py, part 1**

`packages/core/bsi_core/products.py`:

```python
"""Product-title wedge (PRD F16): import a catalogue, infer each
product's generic shopper keyword, compare its title with the titles that
rank for that keyword, and rewrite it.

Parsing, voting, the missing-keyword rule and the rule check are pure.
`run_products` orchestrates the job in short tenant sessions, with no
transaction open during a model call, the `suggest_competitors` shape.
"""

import csv
import hashlib
import io
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Iterable
from functools import partial
from typing import Any

from .crawl import Fetch, http_fetch

MAX_PRODUCTS = 1_000  # per brand, the PRD's run ceiling
CSV_MAX_BYTES = 4 * 1024 * 1024
FEED_CAP_BYTES = 8 * 1024 * 1024
FEED_FETCH: Fetch = partial(http_fetch, cap=FEED_CAP_BYTES, raw=True)

# CSV header (lowercased) -> row key. Any other header is an attribute.
CSV_FIELDS = {
    "id": "external_id",
    "title": "title",
    "description": "description",
    "url": "url",
    "link": "url",
    "price": "price",
    "category": "category",
}
# Merchant feed tags (namespace stripped) kept as attributes.
FEED_ATTRS = (
    "brand",
    "color",
    "size",
    "material",
    "gender",
    "age_group",
    "condition",
)
EXPORT_COLUMNS = [
    "external_id",
    "url",
    "title",
    "keyword",
    "missing_keywords",
    "suggested_title",
    "suggested_bullets",
    "rule_check",
]


class CatalogueCap(ValueError):
    """An import would take the brand past MAX_PRODUCTS."""


def _external_id(row: dict[str, Any]) -> str:
    return str(
        row.get("external_id")
        or row.get("url")
        or hashlib.sha1(str(row["title"]).encode()).hexdigest()
    )


def parse_attributes(cell: str) -> dict[str, str]:
    """`Size: 10; Color: Blue` -> {"size": "10", "color": "blue"}. A
    fragment without a colon is dropped."""
    out: dict[str, str] = {}
    for frag in cell.split(";"):
        key, sep, value = frag.partition(":")
        if sep and key.strip():
            out[key.strip().lower()] = value.strip().lower()
    return out


def _blank_row() -> dict[str, Any]:
    return {
        "external_id": None,
        "title": None,
        "description": None,
        "attributes": {},
        "url": None,
        "price": None,
        "category": None,
    }


def parse_csv(text: str) -> tuple[list[dict[str, Any]], int]:
    """(rows, rows skipped for an empty title). Headers are matched
    case-insensitively after stripping; unknown headers become
    attributes keyed by the lowercased header."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw in csv.DictReader(io.StringIO(text)):
        row = _blank_row()
        for header, cell in raw.items():
            if header is None:  # a row with more cells than headers
                continue
            key = header.strip().lower()
            value = (cell or "").strip()
            if key == "attributes":
                row["attributes"].update(parse_attributes(value))
            elif key in CSV_FIELDS:
                row[CSV_FIELDS[key]] = value or None
            elif key and value:
                row["attributes"][key] = value
        if not row["title"]:
            skipped += 1
            continue
        row["external_id"] = _external_id(row)
        rows.append(row)
    return rows, skipped


def _feed_row(fields: dict[str, str]) -> dict[str, Any] | None:
    title = fields.get("title")
    if not title:
        return None
    row = _blank_row()
    row.update(
        external_id=fields.get("id") or None,
        title=title,
        description=fields.get("description") or None,
        url=fields.get("link") or None,
        price=fields.get("price") or None,
        category=fields.get("product_type")
        or fields.get("google_product_category")
        or None,
        attributes={k: fields[k] for k in FEED_ATTRS if fields.get(k)},
    )
    row["external_id"] = _external_id(row)
    return row


def parse_feed(body: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """(rows, note). Reads RSS <item> and Atom <entry> elements with the
    XMLPullParser pattern of rivals.parse_sitemap: namespaces are
    stripped, so g:id and id both read as "id"; an Atom <link href> is
    read from the attribute. Gzip is inflated under FEED_CAP_BYTES.
    Malformed or cut XML returns what was read, with note "malformed"."""
    note: str | None = None
    if body[:2] == b"\x1f\x8b":
        z = zlib.decompressobj(47)
        try:
            body = z.decompress(body, FEED_CAP_BYTES)
        except zlib.error:
            return [], "gzip error"
        if z.unconsumed_tail:
            note = "truncated"
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    rows: list[dict[str, Any]] = []
    depth = 0
    entry_depth = 0
    fields: dict[str, str] = {}
    try:
        parser.feed(body)
        for ev in parser.read_events():
            event, el = ev[0], ev[-1]
            if not isinstance(el, ET.Element):
                continue
            tag = str(el.tag).rsplit("}", 1)[-1]
            if event == "start":
                depth += 1
                if tag in ("item", "entry") and not entry_depth:
                    entry_depth, fields = depth, {}
                continue
            if entry_depth and depth == entry_depth:
                row = _feed_row(fields)
                if row:
                    rows.append(row)
                entry_depth = 0
                el.clear()
            elif entry_depth and depth == entry_depth + 1:
                value = (el.text or "").strip()
                if tag == "link" and not value:
                    value = (el.get("href") or "").strip()
                fields.setdefault(tag, value)
            depth -= 1
    except ET.ParseError:
        note = note or "malformed"
    return rows, note


def export_rows(products: Iterable[Any]) -> list[list[str]]:
    """One CSV row per product in EXPORT_COLUMNS order; lists are
    '|'-joined and None is blank."""

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "|".join(str(v) for v in value)
        return str(value)

    return [[cell(getattr(p, c)) for c in EXPORT_COLUMNS] for p in products]
```

- [ ] **Step 4: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py 2>&1 | tail -3`
Expected: 8 PASS. If `test_parse_feed_cut_mid_item_keeps_complete_items` fails because `read_events` raised before yielding F-1, move `parser.feed(body)` inside the `try` (it already is) and check that the `except` runs after the loop consumed the events read so far; `XMLPullParser.feed` raises only after buffering, so F-1's events are still returned by `read_events()` — if not, call `parser.feed` in 64 KiB chunks and process events after each chunk.

- [ ] **Step 5: Lint, type-check and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy 2>&1 | tail -2`
Expected: clean.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py && git commit -m "feat(products): parse CSV and Merchant feeds; export rows"
```

---

### Task 3: The keyword, missing-keyword and rule-check functions, prompts and schemas

**Files:**
- Modify: `packages/core/bsi_core/products.py` (part 2, appended)
- Modify: `tests/unit/test_products.py` (part 2)
- Modify: `tests/unit/test_recommend_copy.py` (`PRODUCT_CASES`)

**Interfaces:**
- Produces: `tokens(text) -> list[str]`; `brand_tokens(names) -> frozenset[str]`; `vote(samples: Sequence[Sequence[str]]) -> list[str]`; `drop_brand_terms(keywords, brand_names) -> list[str]`; `missing(product_title, titles: Sequence[str], brand_names) -> list[str]`; `rule_check(original, suggestion, brand_names) -> tuple[str, str]`; `keep_present(titles: list[dict[str, Any]], text) -> list[dict[str, str]]`; pydantic `KeywordSet`, `TitleSet`, `RewriteSet`; `keyword_prompt(brand, products)`, `titles_prompt(keyword, text, domains)`, `rewrite_prompt(brand, products)`; `STOPWORDS`; constants of the Global Constraints.

- [ ] **Step 1: Write the failing tests**

Extend the top-level `from bsi_core.products import (...)` in `tests/unit/test_products.py` with `KeywordSet, RewriteSet, TitleSet, drop_brand_terms, keep_present, keyword_prompt, missing, rewrite_prompt, rule_check, titles_prompt, vote` (alphabetical, one name per line), then append:

```python
BRAND = ("Walkaroo", "WKR")


def test_vote_picks_the_most_frequent_rank_one():
    samples = [
        ["kids shoes", "running shoes"],
        ["kids shoes"],
        ["running shoes", "kids shoes"],
    ]
    assert vote(samples) == ["kids shoes", "running shoes"]


def test_vote_ties_go_to_the_first_sample_and_cap_at_five():
    samples = [["a", "b", "c"], ["d", "e", "f"], ["g", "h"]]
    assert vote(samples) == ["a", "b", "c", "d", "e"]
    assert vote([[], [], []]) == []


def test_drop_brand_terms_matches_tokens():
    assert drop_brand_terms(
        ["walkaroo sandals", "kids sandals", "wkr shoes"], BRAND
    ) == ["kids sandals"]
    assert drop_brand_terms(["walkaroo sandals"], BRAND) == []


TITLES = [
    "Kids Sandals for Boys Summer Sandal",
    "Boys Summer Sandals Lightweight",
    "Summer Sandals Kids",
]


def test_missing_keywords_need_two_titles_and_skip_present_tokens():
    assert missing("Walkaroo Boys Sandal Blue", TITLES, BRAND) == [
        "sandals",
        "summer",
        "kids",
    ]


def test_missing_skips_brand_stopwords_numbers_and_caps_at_eight():
    titles = [
        "walkaroo for online 2024 alpha beta gamma delta eps zeta eta theta iota",
        "walkaroo for online 2024 alpha beta gamma delta eps zeta eta theta iota",
    ]
    out = missing("Plain", titles, BRAND)
    assert len(out) == 8
    for bad in ("walkaroo", "for", "online", "2024"):
        assert bad not in out


def test_rule_check_removes_repeated_tokens():
    assert rule_check("Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes", BRAND) == (
        "Walkaroo Kids Shoes",
        "adjusted",
    )


def test_rule_check_restores_the_brand_the_original_had():
    assert rule_check("Walkaroo Boys Sandal", "Boys Summer Sandal", BRAND) == (
        "Walkaroo Boys Summer Sandal",
        "adjusted",
    )
    # The original had no brand: none is added.
    assert rule_check("Boys Sandal", "Boys Summer Sandal", BRAND) == (
        "Boys Summer Sandal",
        "pass",
    )


def test_rule_check_trims_to_150_at_a_word_boundary():
    words = [f"w{i}" for i in range(60)]  # "w0 w1 ... w59" = 229 chars
    fixed, status = rule_check("Plain", " ".join(words), BRAND)
    assert status == "adjusted"
    assert len(fixed) <= 150
    assert fixed == " ".join(words)[: len(fixed)]
    assert not fixed.endswith(" ") and fixed.split()[-1] in words


def test_rule_check_passes_an_unchanged_suggestion():
    assert rule_check("Walkaroo Boys Sandal", "Walkaroo Boys Summer Sandal", BRAND) == (
        "Walkaroo Boys Summer Sandal",
        "pass",
    )


def test_keep_present_drops_titles_absent_from_the_text():
    text = "Top picks:\n1. **Kids  Sandals for Boys** on amazon.in\n2. other"
    titles = [
        {"title": "Kids Sandals for Boys", "domain": "Amazon.in"},
        {"title": "Invented Sandal", "domain": "x.in"},
    ]
    assert keep_present(titles, text) == [
        {"title": "Kids Sandals for Boys", "domain": "amazon.in"}
    ]


def test_prompts_carry_the_inputs_and_parse_with_their_schemas():
    products = [
        {
            "index": 0,
            "title": "Walkaroo Boys Sandal",
            "description": "Light sandal",
            "attributes": {"color": "blue"},
            "category": "Sandals",
            "keyword": "kids sandals",
            "missing": ["summer"],
        }
    ]
    kp = keyword_prompt("Walkaroo", products)
    assert "Walkaroo Boys Sandal" in kp and "Light sandal" in kp
    KeywordSet.model_validate_json(
        '{"products": [{"index": 0, "keywords": ["kids sandals"]}]}'
    )
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert "kids sandals" in tp and "answer text" in tp and "amazon.in" in tp
    TitleSet.model_validate_json(
        '{"titles": [{"title": "Kids Sandals", "domain": "amazon.in"}]}'
    )
    rp = rewrite_prompt("Walkaroo", products)
    assert "summer" in rp and "150" in rp
    RewriteSet.model_validate_json(
        '{"products": [{"index": 0, "title": "t", "bullets": ["b"]}]}'
    )
```

In `tests/unit/test_recommend_copy.py`, add `from bsi_core.products import keyword_prompt, rewrite_prompt, titles_prompt` to the top imports, then after `ALERT_CASES`:

```python
# Fixed wording of the Products tab and API, mirrored from
# apps/web/src/lib/format.ts PRODUCT_NOTES, products/page.tsx and
# routers/products.py Problem titles. Keep in step by hand.
PRODUCT_CASES = [
    "Imported.",
    "Choose a CSV file first.",
    "Catalogue cap is 1,000 products; nothing was imported.",
    "Queued; the worker runs it within a minute.",
    "Done.",
    "Failed; see the status line.",
    "Products cleared.",
    "No products to run.",
    "No products yet.",
    "Run in progress",
    "Last run: done",
    "Last run failed",
    "Feed import",
    "pass",
    "adjusted",
    "Catalogue cap is 1,000 products",
    "CSV too large",
    "Only http(s) feed URLs",
    "Download CSV",
]
# The prompts' fixed wording is not user-facing, but it is ours.
PRODUCT_CASES += [
    keyword_prompt("Acme", []),
    titles_prompt("kids shoes", "", []),
    rewrite_prompt("Acme", []),
]


@pytest.mark.parametrize("copy", PRODUCT_CASES)
def test_product_copy_never_promises_an_outcome(copy):
    text = copy.lower()
    for word in FORBIDDEN:
        assert word not in text, word
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py tests/unit/test_recommend_copy.py 2>&1 | tail -3`
Expected: FAIL (`ImportError: cannot import name 'vote'`).

- [ ] **Step 3: Append part 2 to products.py**

Add to the imports at the top of `packages/core/bsi_core/products.py`:

```python
import json
import re
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel
```

Append after `export_rows`:

```python
BATCH = 20
SAMPLES = 3
KEYWORD_TEMPERATURE = 0.4
MAX_KEYWORDS = 5
KEYWORD_CAP = 100  # grounded searches per run
SEARCH_TTL_DAYS = 7
# 35,000 micros grounding + tokens + the flash-lite parse call.
SEARCH_MICROS = 45_000
# The keyword phase: 150 flash-lite calls for 1,000 products.
PRODUCT_JOB_MICROS = 20_000
TOP_TITLES = 5
MIN_TITLES = 2
MAX_MISSING = 8
MAX_TITLE_CHARS = 150
MAX_BULLETS = 3
MAX_BULLET_CHARS = 200
MAX_DESCRIPTION_CHARS = 300  # in prompts
MAX_ATTRIBUTES = 10  # in prompts

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "and for the with from your our this that are you all any buy online "
    "free shop shopping sale offer offers price prices deal deals off "
    "new".split()
)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def brand_tokens(names: Sequence[str]) -> frozenset[str]:
    return frozenset(t for n in names for t in tokens(n))


def vote(samples: Sequence[Sequence[str]]) -> list[str]:
    """One product's ranked keywords from SAMPLES ranked lists: rank 1 is
    the keyword most often at rank 1 (ties: sample order), then the union
    in first-seen order, capped at MAX_KEYWORDS."""
    firsts = [s[0] for s in samples if s]
    if not firsts:
        return []
    counts = Counter(firsts)
    top = max(firsts, key=lambda k: (counts[k], -firsts.index(k)))
    out = [top]
    for sample in samples:
        for keyword in sample:
            if keyword not in out:
                out.append(keyword)
    return out[:MAX_KEYWORDS]


def drop_brand_terms(
    keywords: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Drop any keyword sharing a token with the brand name or an alias."""
    bt = brand_tokens(brand_names)
    return [k for k in keywords if not (set(tokens(k)) & bt)]


def missing(
    product_title: str, titles: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Tokens of the ranking titles the product title lacks: at least 3
    characters, not a number, not a stopword or brand token, in at least
    MIN_TITLES titles; by title count then alphabetically; MAX_MISSING."""
    have = set(tokens(product_title)) | brand_tokens(brand_names)
    counts: Counter[str] = Counter()
    for title in titles:
        for tok in set(tokens(title)):
            if (
                len(tok) >= 3
                and not tok.isdigit()
                and tok not in STOPWORDS
                and tok not in have
            ):
                counts[tok] += 1
    ranked = sorted(
        (tok for tok, n in counts.items() if n >= MIN_TITLES),
        key=lambda tok: (-counts[tok], tok),
    )
    return ranked[:MAX_MISSING]


def _brand_in(text: str, brand_names: Sequence[str]) -> str | None:
    """The first brand name (name, then aliases) whose tokens all appear."""
    have = set(tokens(text))
    for name in brand_names:
        bt = tokens(name)
        if bt and set(bt) <= have:
            return name
    return None


def rule_check(
    original: str, suggestion: str, brand_names: Sequence[str]
) -> tuple[str, str]:
    """(title, "pass" | "adjusted"). Fixes rather than retries: repeated
    tokens are dropped (first occurrence kept), the brand is prepended
    if the original had it and the suggestion lost it, and the title is
    trimmed to MAX_TITLE_CHARS at a word boundary."""
    seen: set[str] = set()
    kept: list[str] = []
    for word in suggestion.split():
        key = "".join(tokens(word))
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(word)
    title = " ".join(kept)
    brand = _brand_in(original, brand_names)
    if brand and _brand_in(title, [brand]) is None:
        title = f"{brand} {title}".strip()
    if len(title) > MAX_TITLE_CHARS:
        cut = title[: MAX_TITLE_CHARS + 1]
        space = cut.rfind(" ")
        title = cut[:space].rstrip() if space > 0 else title[:MAX_TITLE_CHARS]
    return title, ("pass" if title == suggestion else "adjusted")


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def keep_present(
    titles: list[dict[str, Any]], text: str
) -> list[dict[str, str]]:
    """Only titles found verbatim in the answer text (case and
    whitespace ignored), at most TOP_TITLES, domains lowercased."""
    hay = _squash(text)
    out: list[dict[str, str]] = []
    for t in titles:
        title = str(t.get("title") or "").strip()
        if title and _squash(title) in hay:
            out.append(
                {"title": title, "domain": str(t.get("domain") or "").strip().lower()}
            )
    return out[:TOP_TITLES]


class KeywordItem(BaseModel):
    index: int
    keywords: list[str]


class KeywordSet(BaseModel):
    products: list[KeywordItem]


class TitleItem(BaseModel):
    title: str
    domain: str = ""


class TitleSet(BaseModel):
    titles: list[TitleItem]


class RewriteItem(BaseModel):
    index: int
    title: str
    bullets: list[str]


class RewriteSet(BaseModel):
    products: list[RewriteItem]


def _product_lines(products: Sequence[dict[str, Any]], *keys: str) -> str:
    rows = []
    for p in products:
        row: dict[str, Any] = {"index": p["index"], "title": p["title"]}
        for k in keys:
            v = p.get(k)
            if k == "description" and isinstance(v, str):
                v = v[:MAX_DESCRIPTION_CHARS]
            if k == "attributes" and isinstance(v, dict):
                v = dict(list(v.items())[:MAX_ATTRIBUTES])
            if v:
                row[k] = v
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def keyword_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    """The ADK keyword-finding prompt, one call per batch, JSON out."""
    return (
        "You find the keywords shoppers type when looking for products "
        f"like these from the brand {brand!r}.\n"
        "For each product give up to "
        f"{MAX_KEYWORDS} keywords, lowercase, generic first: rank 1 is "
        "the shortest phrase naming the audience plus the product "
        'category (for example "kids shoes"), more specific phrases '
        "after it. Never include the brand name. One keyword per entry. "
        "Given the same products, choose the same rank 1.\n"
        "Return JSON {\"products\": [{\"index\": <index>, "
        "\"keywords\": [...]}, ...]} with one entry per input index.\n"
        "Products:\n"
        + _product_lines(products, "description", "attributes", "category")
    )


def titles_prompt(keyword: str, text: str, domains: Sequence[str]) -> str:
    """Parse a grounded answer into the product titles it names."""
    return (
        f"The text below answers a search for {keyword!r} buy online.\n"
        f"List up to {TOP_TITLES} distinct product titles that appear "
        "verbatim in the text, in the order they appear, each with the "
        "seller's domain when the text names it (else an empty string). "
        "Do not invent titles or shorten them.\n"
        f"Known source domains: {', '.join(domains) or 'none'}\n"
        "Return JSON {\"titles\": [{\"title\": ..., \"domain\": ...}]}.\n"
        f"Text:\n{text}"
    )


def rewrite_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    return (
        f"Rewrite each product title for the brand {brand!r}.\n"
        f"Each new title: at most {MAX_TITLE_CHARS} characters; keep the "
        "brand name if the original has it; work in the keyword and the "
        "missing terms naturally; repeat no word; no keyword stuffing. "
        f"Also give {MAX_BULLETS} short description bullet points.\n"
        "Return JSON {\"products\": [{\"index\": <index>, \"title\": ..., "
        "\"bullets\": [...]}, ...]} with one entry per input index.\n"
        "Products:\n"
        + _product_lines(
            products, "keyword", "missing", "description", "attributes"
        )
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py tests/unit/test_recommend_copy.py 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 5: Lint, type-check and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy 2>&1 | tail -2`
Expected: clean.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py tests/unit/test_recommend_copy.py && git commit -m "feat(products): keyword vote, missing keywords, rule check and prompts"
```

---

### Task 4: Upsert, the products API and its tests

**Files:**
- Modify: `packages/core/bsi_core/products.py` (add `upsert`)
- Modify: `apps/api/bsi_api/schemas.py` (append `ProductOut`, `ImportOut`, `FeedIn`, `ProductJobOut`, `ProductRunsOut`)
- Create: `apps/api/bsi_api/routers/products.py`
- Modify: `apps/api/bsi_api/main.py` (import + router tuple after `reports.router`)
- Create: `tests/integration/test_api_products.py`
- Modify: `tests/integration/test_isolation.py` (`CASES`)

**Interfaces:**
- Consumes: `parse_csv`, `parse_feed` (Task 2), `m.Product`, `m.KeywordSearch` (Task 1), `queue_suggestion` (`routers/runs.py`), `Problem(status, title, detail)`.
- Produces: `upsert(s, org_id, brand_id, rows, source) -> tuple[int, int]` raising `CatalogueCap`; routes under `/v1/brands/{brand_id}/products`: `GET ""`, `GET /export.csv`, `GET /runs`, `POST /import/csv` (201), `POST /import/feed` (202), `POST /run` (202), `DELETE ""` (204). Job params: `product_run` → `{"locale": {"country", "language"}, "product_count"}`; `import_feed` → `{"url"}`.

- [ ] **Step 1: Write the failing API tests**

`tests/integration/test_api_products.py`:

```python
"""The products API (slice 18): import, run, export, delete."""

import pytest
from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import select, text

CSV = (
    "title,id,url,attributes\n"
    "Walkaroo Boys Sandal,W-1,https://walkaroo.in/p/1,Size: 10\n"
    "Walkaroo Kids Shoe,W-2,,\n"
    ",W-3,,\n"
)
CSV_HEADERS = {"Content-Type": "text/csv"}


def _import(client, org, bid, body=CSV):
    return client.post(
        f"/v1/brands/{bid}/products/import/csv",
        content=body,
        headers={**org.headers, **CSV_HEADERS},
    )


def _products(owner, bid):
    with owner() as s:
        return list(
            s.scalars(
                select(m.Product)
                .where(m.Product.brand_id == bid)
                .order_by(m.Product.external_id)
            )
        )


def test_csv_import_round_trip_keeps_result_columns(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    r = _import(client, org, bid)
    assert r.status_code == 201, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 1, "total": 2}
    rows = _products(owner, bid)
    assert [p.external_id for p in rows] == ["W-1", "W-2"]
    assert rows[0].attributes == {"size": "10"} and rows[0].source == "csv"
    with owner() as s, s.begin():
        p = s.get(m.Product, rows[0].id)
        p.keyword, p.suggested_title, p.rule_check = "kids sandals", "X", "pass"
    r = _import(client, org, bid, CSV.replace("Boys Sandal", "Boys Sandal 2"))
    assert r.json() == {"created": 0, "updated": 2, "skipped": 1, "total": 2}
    rows = _products(owner, bid)
    assert rows[0].title == "Walkaroo Boys Sandal 2"
    assert (rows[0].keyword, rows[0].suggested_title) == ("kids sandals", "X")


def test_csv_import_refuses_the_catalogue_cap_and_writes_nothing(
    client, owner, make_org, make_brand, monkeypatch
):
    from bsi_core import products

    monkeypatch.setattr(products, "MAX_PRODUCTS", 1)
    org = make_org()
    bid = make_brand(org)
    r = _import(client, org, bid)
    assert r.status_code == 422
    assert r.json()["title"] == "Catalogue cap is 1,000 products"
    assert _products(owner, bid) == []


def test_csv_import_refuses_a_large_body(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    big = "title\n" + ("x" * 1024 + "\n") * (5 * 1024)
    r = _import(client, org, bid, big)
    assert r.status_code == 413


def test_feed_import_queues_a_job_and_rejects_non_http(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.post(
        f"/v1/brands/{bid}/products/import/feed",
        json={"url": "ftp://x.in/feed.xml"},
        headers=org.headers,
    )
    assert r.status_code == 422
    r = client.post(
        f"/v1/brands/{bid}/products/import/feed",
        json={"url": "https://x.in/feed.xml"},
        headers=org.headers,
    )
    assert r.status_code == 202 and r.json()["status"] == "queued"
    with owner() as s:
        job = s.scalars(select(m.Job).where(m.Job.kind == "import_feed")).one()
    assert job.params == {"url": "https://x.in/feed.xml"}


def test_run_needs_products_then_queues_with_the_locale(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/products/run", headers=org.headers)
    assert r.status_code == 422 and r.json()["title"] == "No products to run"
    _import(client, org, bid)
    r = client.post(f"/v1/brands/{bid}/products/run", headers=org.headers)
    assert r.status_code == 202
    with owner() as s:
        job = s.scalars(select(m.Job).where(m.Job.kind == "product_run")).one()
    assert job.params == {
        "locale": {"country": "IN", "language": "en"},
        "product_count": 2,
    }
    r = client.get(f"/v1/brands/{bid}/products/runs", headers=org.headers)
    body = r.json()
    assert [j["kind"] for j in body["jobs"]] == ["product_run"]
    assert (body["done"], body["total"]) == (0, 2)


def test_list_and_export(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    with owner() as s, s.begin():
        p = s.scalars(
            select(m.Product).where(m.Product.external_id == "W-1")
        ).one()
        p.keyword = "kids sandals"
        p.missing_keywords = ["summer", "kids"]
        p.suggested_title = "Walkaroo Kids Summer Sandal for Boys"
        p.suggested_bullets = ["Light", "Washable"]
        p.rule_check = "adjusted"
    r = client.get(f"/v1/brands/{bid}/products", headers=org.headers)
    assert [p["external_id"] for p in r.json()] == ["W-1", "W-2"]
    assert r.json()[0]["missing_keywords"] == ["summer", "kids"]
    r = client.get(
        f"/v1/brands/{bid}/products/export.csv", headers=org.headers
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == (
        f'attachment; filename="products-{bid}.csv"'
    )
    lines = r.text.splitlines()
    assert lines[0] == (
        "external_id,url,title,keyword,missing_keywords,"
        "suggested_title,suggested_bullets,rule_check"
    )
    assert lines[1] == (
        "W-1,https://walkaroo.in/p/1,Walkaroo Boys Sandal,kids sandals,"
        "summer|kids,Walkaroo Kids Summer Sandal for Boys,Light|Washable,"
        "adjusted"
    )
    assert lines[2] == "W-2,,Walkaroo Kids Shoe,,,,,"


def test_delete_clears_products_and_searches(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id, brand_id=bid, keyword="kids sandals", query="q"
            )
        )
    r = client.delete(f"/v1/brands/{bid}/products", headers=org.headers)
    assert r.status_code == 204
    with owner() as s:
        assert s.scalar(select(m.Product).limit(1)) is None
        assert s.scalar(select(m.KeywordSearch).limit(1)) is None


def test_csv_import_into_another_orgs_brand_is_404(
    client, make_org, make_brand
):
    org_a, org_b = make_org("A"), make_org("B")
    bid_b = make_brand(org_b, "Secret")
    r = _import(client, org_a, bid_b)
    assert r.status_code == 404 and "Secret" not in r.text


def test_no_request_leaves_an_idle_transaction(
    client, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    client.get(f"/v1/brands/{bid}/products/export.csv", headers=org.headers)
    with system_session() as s:
        idle = s.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                "current_database() AND state LIKE 'idle in transaction%' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
    assert idle == 0
```

Add to `CASES` in `tests/integration/test_isolation.py`:

```python
    ("GET", "/v1/brands/{b}/products", None),
    ("GET", "/v1/brands/{b}/products/export.csv", None),
    ("GET", "/v1/brands/{b}/products/runs", None),
    (
        "POST",
        "/v1/brands/{b}/products/import/feed",
        {"url": "https://secret.example/feed.xml"},
    ),
    ("POST", "/v1/brands/{b}/products/run", None),
    ("DELETE", "/v1/brands/{b}/products", None),
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_products.py 2>&1 | tail -3`
Expected: FAIL with 404s (no router).

- [ ] **Step 3: Add `upsert` to products.py**

Add imports at the top of `packages/core/bsi_core/products.py`:

```python
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m
```

Append after `export_rows`:

```python
_CATALOGUE = (
    "external_id",
    "title",
    "description",
    "attributes",
    "url",
    "price",
    "category",
)


def upsert(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    rows: Sequence[dict[str, Any]],
    source: str,
) -> tuple[int, int]:
    """(created, updated). One INSERT ... ON CONFLICT on
    (brand_id, external_id) that rewrites only the catalogue columns,
    source and imported_at; the result columns are kept. Raises
    CatalogueCap, before writing, if the brand would exceed MAX_PRODUCTS.
    A later row with the same external_id wins."""
    by_id = {str(r["external_id"]): r for r in rows}
    if not by_id:
        return 0, 0
    existing = set(
        s.scalars(
            select(m.Product.external_id).where(m.Product.brand_id == brand_id)
        )
    )
    new_ids = set(by_id) - existing
    if len(existing) + len(new_ids) > MAX_PRODUCTS:
        raise CatalogueCap(f"{len(existing) + len(new_ids)} > {MAX_PRODUCTS}")
    values = [
        {
            "org_id": org_id,
            "brand_id": brand_id,
            "source": source,
            "imported_at": func.now(),
            **{k: r[k] for k in _CATALOGUE},
        }
        for r in by_id.values()
    ]
    stmt = pg_insert(m.Product).values(values)
    s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_product_brand_external",
            set_={
                c: getattr(stmt.excluded, c)
                for c in (*_CATALOGUE, "source", "imported_at")
            },
        )
    )
    return len(new_ids), len(by_id) - len(new_ids)
```

- [ ] **Step 4: Schemas**

Append to `apps/api/bsi_api/schemas.py`:

```python
class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    brand_id: uuid.UUID
    external_id: str
    title: str
    description: str | None
    attributes: dict[str, Any]
    url: str | None
    price: str | None
    category: str | None
    source: str
    imported_at: datetime
    keyword: str | None
    keywords: list[str] | None
    missing_keywords: list[str] | None
    suggested_title: str | None
    suggested_bullets: list[str] | None
    rule_check: str | None
    job_id: uuid.UUID | None
    result_at: datetime | None


class ImportOut(BaseModel):
    created: int
    updated: int
    skipped: int
    total: int


class FeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class ProductJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    status: str | None
    error: str | None
    cost_micros: int
    created_at: datetime
    started_at: datetime | None


class ProductRunsOut(BaseModel):
    jobs: list[ProductJobOut]
    done: int
    total: int
```

- [ ] **Step 5: The router**

`apps/api/bsi_api/routers/products.py`:

```python
"""The product-title wedge (PRD F16): catalogue import, the run, export."""

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from bsi_core import models as m
from bsi_core.products import (
    CSV_MAX_BYTES,
    CatalogueCap,
    export_rows,
    parse_csv,
    upsert,
)
from fastapi import APIRouter, Body, Query, Response
from sqlalchemy import delete, func, select

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem
from ..schemas import FeedIn, ImportOut, ProductOut, ProductRunsOut, QueuedOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/products", tags=["products"])
RUN_KINDS = ("product_run", "import_feed")


def _count(c: Ctx, brand_id: uuid.UUID) -> int:
    return int(
        c.s.scalar(
            select(func.count())
            .select_from(m.Product)
            .where(m.Product.brand_id == brand_id)
        )
        or 0
    )


@router.get("", response_model=list[ProductOut])
def list_products(
    brand_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=1000),
    c: Ctx = TENANT,
) -> list[m.Product]:
    brand_or_404(c, brand_id)
    q = (
        select(m.Product)
        .where(m.Product.brand_id == brand_id)
        .order_by(m.Product.title, m.Product.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.get("/export.csv")
def export_csv(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    brand_or_404(c, brand_id)
    q = (
        select(m.Product)
        .where(m.Product.brand_id == brand_id)
        .order_by(m.Product.title, m.Product.id)
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    from bsi_core.products import EXPORT_COLUMNS

    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(export_rows(c.s.scalars(q)))
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="products-{brand_id}.csv"'
            )
        },
    )


@router.get("/runs", response_model=ProductRunsOut)
def list_runs(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    jobs = list(
        c.s.scalars(
            select(m.Job)
            .where(m.Job.brand_id == brand_id, m.Job.kind.in_(RUN_KINDS))
            .order_by(m.Job.created_at.desc(), m.Job.id)
            .limit(20)
        )
    )
    latest = next((j for j in jobs if j.kind == "product_run"), None)
    done = 0
    if latest is not None:
        done = int(
            c.s.scalar(
                select(func.count())
                .select_from(m.Product)
                .where(
                    m.Product.brand_id == brand_id,
                    m.Product.job_id == latest.id,
                )
            )
            or 0
        )
    return {"jobs": jobs, "done": done, "total": _count(c, brand_id)}


@router.post("/import/csv", status_code=201, response_model=ImportOut)
def import_csv(
    brand_id: uuid.UUID,
    body: Annotated[bytes, Body(media_type="text/csv")],
    c: Ctx = TENANT,
) -> dict[str, int]:
    brand_or_404(c, brand_id)
    if len(body) > CSV_MAX_BYTES:
        raise Problem(413, "CSV too large", "The limit is 4 MiB.")
    rows, skipped = parse_csv(body.decode("utf-8-sig", errors="replace"))
    try:
        created, updated = upsert(c.s, c.org_id, brand_id, rows, "csv")
    except CatalogueCap as e:
        raise Problem(
            422, "Catalogue cap is 1,000 products", str(e)
        ) from e
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": _count(c, brand_id),
    }


@router.post("/import/feed", status_code=202, response_model=QueuedOut)
def import_feed(
    brand_id: uuid.UUID, body: FeedIn, c: Ctx = TENANT
) -> dict[str, Any]:
    if not body.url.startswith(("http://", "https://")):
        raise Problem(422, "Only http(s) feed URLs", body.url[:200])
    return queue_suggestion(
        c,
        brand_id,
        "import_feed",
        {"url": body.url},
        slot=datetime.now(UTC),
    )


@router.post("/run", status_code=202, response_model=QueuedOut)
def run(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    total = _count(c, brand_id)
    if total == 0:
        raise Problem(422, "No products to run", "Import products first.")
    locale = c.s.scalars(
        select(m.Locale)
        .where(m.Locale.brand_id == brand_id)
        .order_by(m.Locale.created_at, m.Locale.id)
        .limit(1)
    ).first()
    country = locale.country if locale else "IN"
    language = locale.language if locale else "en"
    return queue_suggestion(
        c,
        brand_id,
        "product_run",
        {
            "locale": {"country": country, "language": language},
            "product_count": total,
        },
        slot=datetime.now(UTC),
    )


@router.delete("", status_code=204)
def clear(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    brand_or_404(c, brand_id)
    c.s.execute(
        delete(m.KeywordSearch).where(m.KeywordSearch.brand_id == brand_id)
    )
    c.s.execute(delete(m.Product).where(m.Product.brand_id == brand_id))
    return Response(status_code=204)
```

Move the `EXPORT_COLUMNS` import to the top-level `from bsi_core.products import (...)` list (it is shown inline above only to keep the excerpt self-contained). In `main.py` add `products,` to the `from .routers import (...)` list (alphabetical, after `prompts`) and `products.router,` to the tuple after `reports.router,`.

If FastAPI does not hand the raw body to the `bytes` parameter (test 1 returns 422 "value is not a valid..."), switch `import_csv` to `async def import_csv(brand_id, request: Request, c: Ctx = TENANT)` with `body = await request.body()`; everything else stays.

- [ ] **Step 6: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_products.py tests/integration/test_isolation.py 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 7: Regenerate the OpenAPI types, gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen 2>&1 | tail -2`
Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy 2>&1 | tail -2`
Expected: `schema.d.ts` and `openapi.json` changed; lint clean.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py apps/api/bsi_api/schemas.py apps/api/bsi_api/routers/products.py apps/api/bsi_api/main.py tests/integration/test_api_products.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(api): products import, run, export and clear routes"
```

---

### Task 5: `run_products`, `run_import_feed` and the worker wiring

**Files:**
- Modify: `packages/core/bsi_core/products.py` (part 3: `OverBudget`, `run_products`)
- Modify: `apps/workers/bsi_workers/worker.py` (`run_import_feed`, `JOB_ESTIMATES`, `runners`, error mapping in `process_job`)
- Create: `tests/integration/test_products_run.py`
- Modify: `tests/integration/test_worker.py` (one dispatch test)

**Interfaces:**
- Consumes: Tasks 2–4; `Generator` from `bsi_core.suggest`; `EngineAdapter`; `budget_fits`; `JudgeFailed`; worker `_Meter` (has `.query`, `.parse`, `.generate`).
- Produces: `run_products(org_id, job_id, brand_id, params, generator, adapter, now=None) -> str`; `class OverBudget(RuntimeError)` with `.cost_micros`; worker `run_import_feed(org_id, brand_id, job_id, params, fetch=http_fetch, feed_fetch=None) -> str`; `JOB_ESTIMATES["product_run"] = PRODUCT_JOB_MICROS`, `JOB_ESTIMATES["import_feed"] = 0`; `process_job` records `error="budget"` for `OverBudget` and `error="cap"` for `CatalogueCap`.

- [ ] **Step 1: Write the failing run tests**

`tests/integration/test_products_run.py`:

```python
"""The product_run and import_feed jobs (slice 18)."""

import json
from datetime import UTC, datetime, timedelta

import bsi_workers.worker as worker
from bsi_core import models as m
from bsi_core import products
from bsi_core.crawl import Response
from bsi_core.providers.base import EngineResult, ParsedAnswer
from sqlalchemy import select, text, update

from tests.integration.test_worker import _job, _load_job

ANSWER = (
    "Popular picks: **Kids Sandals for Boys Summer** on amazon.in, "
    "**Boys Summer Sandals Lightweight** at flipkart.com."
)


class FakeEngine:
    """query returns one ok answer per call; parse returns its text."""

    code = "gemini"

    def __init__(self, results=None):
        self.results = list(results or [])
        self.prompts = []

    def query(self, prompt, country, language):
        self.prompts.append((prompt, country, language))
        if self.results:
            return self.results.pop(0)
        return EngineResult(
            "ok", raw={"text": ANSWER}, model="fake-1", cost_micros=35_000
        )

    def parse(self, raw):
        return ParsedAnswer(raw.get("text", ""), [("u", "amazon.in")])

    def cost(self, raw):
        return 0

    def health(self):
        return True

    def rate_budget(self):
        return 60


def _generator(owner=None, fail_on=None):
    """Answers each schema with fixed JSON; records the call kinds and,
    when `owner` is given, how many products had a keyword at call time."""
    calls = []

    def generate(prompt, schema, temperature):
        kind = {
            products.KeywordSet: "keywords",
            products.TitleSet: "titles",
            products.RewriteSet: "rewrite",
        }[schema]
        if owner is not None:
            with owner() as s:
                n = s.scalar(
                    text("SELECT count(*) FROM product WHERE keyword IS NOT NULL")
                )
            calls.append((kind, temperature, n))
        else:
            calls.append((kind, temperature))
        if fail_on is not None and len(calls) == fail_on:
            raise RuntimeError("model down")
        indexes = [
            p["index"] for p in json.loads(prompt.split("Products:\n", 1)[1])
        ] if "Products:\n" in prompt else []
        if kind == "keywords":
            body = {
                "products": [
                    {"index": i, "keywords": ["kids sandals", "walkaroo kids"]}
                    for i in indexes
                ]
            }
        elif kind == "titles":
            body = {
                "titles": [
                    {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
                    {"title": "Boys Summer Sandals Lightweight", "domain": ""},
                    {"title": "Invented Sandal", "domain": "x"},
                ]
            }
        else:
            body = {
                "products": [
                    {
                        "index": i,
                        "title": "Walkaroo Kids Summer Sandals Sandals",
                        "bullets": ["Light", "Washable", "Soft", "Extra"],
                    }
                    for i in indexes
                ]
            }
        return json.dumps(body), 700, "fake-model"

    generate.calls = calls
    return generate


def _seed(owner, org, bid, n):
    with owner() as s, s.begin():
        for i in range(n):
            s.add(
                m.Product(
                    org_id=org.id,
                    brand_id=bid,
                    external_id=f"W-{i}",
                    title=f"Walkaroo Boys Sandal {i}",
                    source="csv",
                )
            )


def _run(owner, org, bid, generator, engine=None, **params):
    jid = _job(
        owner,
        org,
        bid,
        "product_run",
        "queued",
        params={"locale": {"country": "IN", "language": "en"}, **params},
    )
    worker.process_job(engine or FakeEngine(), generator, None)
    with owner() as s:
        rows = s.scalars(
            select(m.Product).order_by(m.Product.external_id)
        ).all()
        searches = s.scalars(select(m.KeywordSearch)).all()
    return _load_job(owner, jid), rows, searches


def test_keywords_are_written_per_batch(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 21)
    gen = _generator(owner)
    job, rows, searches = _run(owner, org, bid, gen)
    assert (job.status, job.error) == ("done", None)
    keyword_calls = [c for c in gen.calls if c[0] == "keywords"]
    assert len(keyword_calls) == 6  # 2 batches x 3 samples
    assert [c[1] for c in keyword_calls] == [0.4] * 6
    assert [c[2] for c in keyword_calls] == [0, 0, 0, 20, 20, 20]
    assert all(p.keyword == "kids sandals" for p in rows)
    assert rows[0].keywords == ["kids sandals"]  # brand keyword dropped


def test_one_search_per_distinct_keyword_and_the_rewrite_is_checked(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 3)
    engine = FakeEngine()
    gen = _generator()
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert job.status == "done"
    assert engine.prompts == [("kids sandals buy online", "IN", "en")]
    assert len(searches) == 1
    assert searches[0].keyword == "kids sandals"
    assert searches[0].titles == [
        {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
        {"title": "Boys Summer Sandals Lightweight", "domain": ""},
    ]
    assert searches[0].cost_micros == 35_700 and searches[0].error is None
    p = rows[0]
    # "sandals" and "summer" are in both ranking titles and absent from
    # "Walkaroo Boys Sandal 0"; "kids" and "lightweight" are in one only.
    assert p.missing_keywords == ["sandals", "summer"]
    assert p.suggested_title == "Walkaroo Kids Summer Sandals"
    assert p.rule_check == "adjusted"
    assert p.suggested_bullets == ["Light", "Washable", "Soft"]
    assert p.job_id == job.id and p.result_at is not None
    assert [c[0] for c in gen.calls] == [
        "keywords",
        "keywords",
        "keywords",
        "titles",
        "rewrite",
    ]
    assert job.cost_micros == 35_000 + 5 * 700


def test_a_fresh_search_is_reused_and_a_stale_one_redone(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query="q",
                titles=[{"title": "Cached Summer Sandals", "domain": "c"}],
                searched_at=datetime.now(UTC) - timedelta(days=6),
            )
        )
    engine = FakeEngine()
    job, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert engine.prompts == [] and rows[0].missing_keywords == []
    with owner() as s, s.begin():
        s.execute(
            update(m.KeywordSearch).values(
                searched_at=datetime.now(UTC) - timedelta(days=8)
            )
        )
    job, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert len(engine.prompts) == 1 and len(searches) == 1
    assert searches[0].titles[0]["title"] == "Kids Sandals for Boys Summer"


def test_budget_failure_after_keywords_keeps_them(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    # $0.04: PRODUCT_JOB_MICROS (20,000) fits at claim; one search
    # (45,000) does not.
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=0.04)
        )
    engine = FakeEngine()
    gen = _generator()
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert (job.status, job.error) == ("failed", "budget")
    assert rows[0].keyword == "kids sandals" and rows[0].suggested_title is None
    assert engine.prompts == [] and searches == []
    assert job.cost_micros == 3 * 700


def test_a_failed_search_is_stored_and_the_run_goes_on(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    engine = FakeEngine([EngineResult("fatal", error="400 bad", model="f")])
    job, rows, searches = _run(owner, org, bid, _generator(), engine)
    assert job.status == "done"
    assert searches[0].error == "400 bad" and searches[0].titles == []
    assert rows[0].missing_keywords == []
    assert rows[0].suggested_title == "Walkaroo Kids Summer Sandals"


def test_a_model_failure_in_batch_two_keeps_batch_one(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 21)
    gen = _generator(fail_on=4)  # first call of the second batch
    job, rows, searches = _run(owner, org, bid, gen)
    assert job.status == "failed" and "model down" in (job.error or "")
    assert job.cost_micros == 3 * 700
    assert sum(1 for p in rows if p.keyword) == 20
    assert all(p.suggested_title is None for p in rows)


def test_no_transaction_is_open_during_model_calls(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    seen = []

    def idle():
        with owner() as s:
            return s.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'idle in transaction' "
                    "AND pid <> pg_backend_pid()"
                )
            )

    inner = _generator()

    def generator(prompt, schema, temperature):
        seen.append(idle())
        return inner(prompt, schema, temperature)

    class Engine(FakeEngine):
        def query(self, prompt, country, language):
            seen.append(idle())
            return super().query(prompt, country, language)

    _run(owner, org, bid, generator, Engine())
    assert len(seen) == 6 and set(seen) == {0}


RSS = b"""<rss xmlns:g="http://base.google.com/ns/1.0"><channel>
<item><g:id>F-1</g:id><title>Feed Sandal</title><link>https://x.in/1</link></item>
</channel></rss>"""


def _feed_job(owner, org, bid, fetch):
    jid = _job(
        owner, org, bid, "import_feed", "queued", params={"url": "https://x.in/f"}
    )
    worker.process_job(FakeEngine(), _generator(), None, fetch=fetch)
    return _load_job(owner, jid)


def test_import_feed_fetches_parses_and_upserts(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        return Response(200, RSS.decode("latin-1"))

    job = _feed_job(owner, org, bid, fetch)
    assert (job.status, job.error) == ("done", None)
    assert calls == [("https://x.in/f", worker.BROWSER_UA)]
    with owner() as s:
        p = s.scalars(select(m.Product)).one()
    assert (p.external_id, p.title, p.source) == ("F-1", "Feed Sandal", "feed")


def test_import_feed_failures(owner, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    job = _feed_job(
        owner, org, bid, lambda u, ua: Response(0, error="refused")
    )
    assert job.status == "failed" and "fetch 0: refused" in (job.error or "")
    monkeypatch.setattr(products, "MAX_PRODUCTS", 0)
    job = _feed_job(owner, org, bid, lambda u, ua: Response(200, RSS.decode()))
    assert (job.status, job.error) == ("failed", "cap")
```

Add to `tests/integration/test_worker.py`, after `test_a_queued_prompts_job_runs_and_is_marked_done`:

```python
def test_product_kinds_are_known_and_estimated():
    assert worker.JOB_ESTIMATES["product_run"] == worker.PRODUCT_JOB_MICROS
    assert worker.PRODUCT_JOB_MICROS == 20_000
    assert worker.JOB_ESTIMATES["import_feed"] == 0
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py tests/integration/test_worker.py -k "product" 2>&1 | tail -3`
Expected: FAIL (jobs fail with `unknown kind`; `KeyError: 'product_run'`).

- [ ] **Step 3: Append `OverBudget` and `run_products` to products.py**

Add imports at the top of `packages/core/bsi_core/products.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from .db import tenant_session
from .judge import JudgeFailed
from .providers.base import EngineAdapter
from .scheduling import budget_fits
from .suggest import Generator
```

Append:

```python
class OverBudget(RuntimeError):
    """The search phase does not fit the org's budget; the keywords
    already written stay. The worker records error "budget"."""

    def __init__(self, cost_micros: int) -> None:
        super().__init__("budget")
        self.cost_micros = cost_micros


def _batches[T](items: Sequence[T]) -> list[list[T]]:
    return [list(items[i : i + BATCH]) for i in range(0, len(items), BATCH)]


def _clean(keyword: str) -> str:
    return " ".join(keyword.casefold().split())


def run_products(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    brand_id: uuid.UUID,
    params: dict[str, Any],
    generator: Generator,
    adapter: EngineAdapter,
    now: datetime | None = None,
) -> str:
    """The product_run job (spec §3): keywords per batch, one grounded
    search per distinct keyword, missing keywords, rewrite, rule check.
    Reads and writes in short tenant sessions; no transaction is open
    during a model call. Raises OverBudget before the search phase when
    it does not fit, and JudgeFailed (with the spend) on any other
    failure, so the money is recorded either way."""
    now = now or datetime.now(UTC)
    locale = params.get("locale") or {}
    country = str(locale.get("country") or "IN")
    language = str(locale.get("language") or "en")
    spent = 0
    try:
        with tenant_session(org_id) as s:
            brand = s.get_one(m.Brand, brand_id)
            names = [brand.name, *brand.aliases]
            products: list[dict[str, Any]] = [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "attributes": p.attributes,
                    "category": p.category,
                }
                for p in s.scalars(
                    select(m.Product)
                    .where(m.Product.brand_id == brand_id)
                    .order_by(m.Product.title, m.Product.id)
                )
            ]
        # 1. Keywords, written per batch: the progress signal.
        for batch in _batches(products):
            for i, p in enumerate(batch):
                p["index"] = i
            samples: list[dict[int, list[str]]] = []
            for _ in range(SAMPLES):
                raw, cost, _model = generator(
                    keyword_prompt(brand.name, batch),
                    KeywordSet,
                    KEYWORD_TEMPERATURE,
                )
                spent += cost
                got = KeywordSet.model_validate_json(raw)
                samples.append(
                    {
                        item.index: [_clean(k) for k in item.keywords if k.strip()]
                        for item in got.products
                    }
                )
            for i, p in enumerate(batch):
                ranked = vote([sm.get(i, []) for sm in samples])
                p["keywords"] = drop_brand_terms(ranked, names)
                p["keyword"] = p["keywords"][0] if p["keywords"] else None
            with tenant_session(org_id) as s:
                for p in batch:
                    s.execute(
                        update(m.Product)
                        .where(m.Product.id == p["id"])
                        .values(keyword=p["keyword"], keywords=p["keywords"])
                    )
        # 2. One grounded search per distinct keyword, cached 7 days.
        counts = Counter(p["keyword"] for p in products if p["keyword"])
        ordered = sorted(counts, key=lambda k: (-counts[k], k))[:KEYWORD_CAP]
        fresh_after = now - timedelta(days=SEARCH_TTL_DAYS)
        with tenant_session(org_id) as s:
            titles_by_kw: dict[str, list[dict[str, Any]]] = {
                row.keyword: list(row.titles)
                for row in s.scalars(
                    select(m.KeywordSearch).where(
                        m.KeywordSearch.brand_id == brand_id,
                        m.KeywordSearch.keyword.in_(ordered),
                        m.KeywordSearch.searched_at > fresh_after,
                    )
                )
            }
            new = [k for k in ordered if k not in titles_by_kw]
            fits = not new or budget_fits(
                s, org_id, 0, extra_micros=len(new) * SEARCH_MICROS
            )
        if not fits:
            raise OverBudget(spent)
        for keyword in new:
            query = f"{keyword} buy online"
            result = adapter.query(query, country, language)
            spent += result.cost_micros
            row: dict[str, Any] = {
                "query": query,
                "titles": [],
                "model": result.model,
                "cost_micros": result.cost_micros,
                "error": None,
            }
            if result.kind != "ok" or result.raw is None:
                row["error"] = result.error or "no answer"
            else:
                parsed = adapter.parse(result.raw)
                domains = sorted({d for _, d in parsed.citations if d})
                raw, cost, _model = generator(
                    titles_prompt(keyword, parsed.text, domains), TitleSet, 0.0
                )
                spent += cost
                row["cost_micros"] += cost
                row["titles"] = keep_present(
                    [t.model_dump() for t in TitleSet.model_validate_json(raw).titles],
                    parsed.text,
                )
            with tenant_session(org_id) as s:
                stmt = pg_insert(m.KeywordSearch).values(
                    org_id=org_id,
                    brand_id=brand_id,
                    keyword=keyword,
                    searched_at=now,
                    **row,
                )
                s.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_keyword_search_brand_keyword",
                        set_={
                            c: getattr(stmt.excluded, c)
                            for c in (*row, "searched_at")
                        },
                    )
                )
            titles_by_kw[keyword] = row["titles"]
        # 3-6. Missing keywords, rewrite, rule check, write, per batch.
        for batch in _batches([p for p in products if p["keyword"]]):
            for i, p in enumerate(batch):
                p["index"] = i
                p["missing"] = missing(
                    p["title"],
                    [t["title"] for t in titles_by_kw.get(p["keyword"], [])],
                    names,
                )
            raw, cost, _model = generator(
                rewrite_prompt(brand.name, batch), RewriteSet, 0.0
            )
            spent += cost
            got = {
                item.index: item
                for item in RewriteSet.model_validate_json(raw).products
            }
            with tenant_session(org_id) as s:
                for i, p in enumerate(batch):
                    item = got.get(i)
                    suggestion = (item.title.strip() if item else "") or p["title"]
                    title, status = rule_check(p["title"], suggestion, names)
                    bullets = [
                        b.strip()[:MAX_BULLET_CHARS]
                        for b in (item.bullets if item else [])
                        if b.strip()
                    ][:MAX_BULLETS]
                    s.execute(
                        update(m.Product)
                        .where(m.Product.id == p["id"])
                        .values(
                            missing_keywords=p["missing"],
                            suggested_title=title,
                            suggested_bullets=bullets,
                            rule_check=status,
                            job_id=job_id,
                            result_at=now,
                        )
                    )
        return (
            f"products:{len(products)} keywords:{len(ordered)} "
            f"searched:{len(new)}"
        )
    except OverBudget:
        raise
    except Exception as e:
        raise JudgeFailed(e, spent) from e
```

- [ ] **Step 4: Wire the worker**

In `apps/workers/bsi_workers/worker.py`:

Imports: add `from bsi_core.products import (FEED_FETCH, PRODUCT_JOB_MICROS, CatalogueCap, OverBudget, parse_feed, run_products, upsert)`.

`JOB_ESTIMATES`: add

```python
    "product_run": PRODUCT_JOB_MICROS,  # the keyword phase; the search
    # phase re-checks the budget itself (products.run_products)
    "import_feed": 0,  # HTTP only: no model, no spend
```

After `run_page_audit`, add:

```python
def run_import_feed(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    params: dict[str, Any],
    fetch: Fetch = http_fetch,
    feed_fetch: Fetch | None = None,
) -> str:
    """Fetch a Google Merchant feed with no transaction open, parse it,
    upsert the products. A failed fetch fails the job; CatalogueCap is
    recorded as error "cap" by process_job. A cut feed imports what was
    read; the note is in the summary (ruling: not stored on the job)."""
    files = feed_fetch or (FEED_FETCH if fetch is http_fetch else fetch)
    url = str(params.get("url", ""))
    resp = files(url, BROWSER_UA)
    if not resp.ok:
        raise RuntimeError(f"fetch {resp.status}: {resp.error or ''}".strip())
    rows, note = parse_feed(resp.body.encode("latin-1", "replace"))
    if resp.truncated:
        note = "truncated"
    with tenant_session(org_id) as s:
        created, updated = upsert(s, org_id, brand_id, rows, "feed")
    return f"created:{created} updated:{updated} note:{note}"
```

In `process_job`'s `runners` dict add:

```python
        "product_run": lambda: run_products(
            org_id, job_id, brand_id, params, meter.generate, meter
        ),
        "import_feed": lambda: run_import_feed(
            org_id, brand_id, job_id, params, fetch
        ),
```

In `process_job`'s `except Exception as e:` branch replace the `_finish_job(...)` call with:

```python
        if isinstance(e, OverBudget):
            error = "budget"
        elif isinstance(e, CatalogueCap):
            error = "cap"
        else:
            error = repr(e)[:2000]
        _finish_job(
            org_id, job_id, "failed", error, getattr(e, "cost_micros", 0)
        )
```

- [ ] **Step 5: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py tests/integration/test_worker.py tests/integration/test_page_audit.py 2>&1 | tail -3`
Expected: all PASS.

- [ ] **Step 6: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q 2>&1 | tail -3`
Expected: clean; the whole backend suite passes.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py apps/workers/bsi_workers/worker.py tests/integration/test_products_run.py tests/integration/test_worker.py && git commit -m "feat(worker): product_run and import_feed jobs"
```

---

### Task 6: The Products tab

**Files:**
- Modify: `apps/web/src/lib/format.ts` (append `PRODUCT_NOTES`, `productNote`), `apps/web/src/lib/format.test.ts`
- Modify: `apps/web/src/lib/types.ts` (append `Product`, `ProductRuns`, `ImportResult`)
- Modify: `apps/web/next.config.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx` (tab link)
- Create: `apps/web/src/app/(app)/b/[id]/products/page.tsx`, `apps/web/src/app/(app)/b/[id]/products/actions.ts`

**Interfaces:**
- Consumes: `S["ProductOut"]`, `S["ProductRunsOut"]`, `S["ImportOut"]`, `S["QueuedOut"]` from the regenerated schema (Task 4); `api<T>()`.
- Produces: `productNote(status)`; the page at `/b/[id]/products`; a "Download CSV" link to `/b/[id]/products/export.csv` (served by Task 7).

- [ ] **Step 1: Write the failing format test**

Append to `apps/web/src/lib/format.test.ts` (add `productNote` to the import list):

```ts
test("productNote says what the products forms did", () => {
  expect(productNote("imported")).toBe("Imported.");
  expect(productNote("nofile")).toBe("Choose a CSV file first.");
  expect(productNote("cap")).toBe(
    "Catalogue cap is 1,000 products; nothing was imported.",
  );
  expect(productNote("queued")).toBe("Queued; the worker runs it within a minute.");
  expect(productNote("running")).toBe("Queued; the worker runs it within a minute.");
  expect(productNote("done")).toBe("Done.");
  expect(productNote("failed")).toBe("Failed; see the status line.");
  expect(productNote("cleared")).toBe("Products cleared.");
  expect(productNote("empty")).toBe("No products to run.");
  expect(productNote(undefined)).toBeNull();
  expect(productNote("constructor")).toBeNull();
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -5`
Expected: FAIL (`productNote` is not exported).

- [ ] **Step 3: Notes, types, config**

Append to `apps/web/src/lib/format.ts`:

```ts
const PRODUCT_QUEUED = "Queued; the worker runs it within a minute.";
const PRODUCT_NOTES: Record<string, string> = {
  imported: "Imported.",
  nofile: "Choose a CSV file first.",
  cap: "Catalogue cap is 1,000 products; nothing was imported.",
  queued: PRODUCT_QUEUED,
  running: PRODUCT_QUEUED,
  done: "Done.",
  failed: "Failed; see the status line.",
  cleared: "Products cleared.",
  empty: "No products to run.",
};

/** What the products forms did. */
export const productNote = (status: Params[string]) =>
  note(PRODUCT_NOTES, status);
```

Append to `apps/web/src/lib/types.ts`:

```ts
export type Product = S["ProductOut"];
export type ProductRuns = S["ProductRunsOut"];
export type ImportResult = S["ImportOut"];
```

`apps/web/next.config.ts`:

```ts
import type { NextConfig } from "next";

// A 1,000-product CSV is a few hundred KB; the default Server Action
// body limit is 1 MB.
const config: NextConfig = {
  experimental: { serverActions: { bodySizeLimit: "4mb" } },
};
export default config;
```

In `layout.tsx`, after the Reports link add `<Link href={`/b/${id}/products`}>Products</Link>`.

- [ ] **Step 4: Actions**

`apps/web/src/app/(app)/b/[id]/products/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { ImportResult, Queued } from "@/lib/types";

const back = (id: string, status: string, extra = "") =>
  redirect(`/b/${id}/products?queued=${status}${extra}`);

// api() throws `${status} ${title}…` on a non-ok response; a 422 here
// is one of the two Problems the API raises on purpose (the cap, or
// no products), which the note explains instead of the error page.
const is422 = (e: unknown) => e instanceof Error && e.message.startsWith("422 ");

export async function importCsv(form: FormData) {
  const id = String(form.get("brand_id"));
  const file = form.get("csv");
  if (!(file instanceof File) || file.size === 0) return back(id, "nofile");
  let r: ImportResult;
  try {
    r = await api<ImportResult>(`/brands/${id}/products/import/csv`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: await file.text(),
    });
  } catch (e) {
    if (is422(e)) return back(id, "cap");
    throw e;
  }
  back(id, "imported", `&n=${r.total}`);
}

export async function importFeed(form: FormData) {
  const id = String(form.get("brand_id"));
  const url = String(form.get("url") ?? "").trim();
  const job = await api<Queued>(`/brands/${id}/products/import/feed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  back(id, encodeURIComponent(job.status));
}

export async function runProducts(form: FormData) {
  const id = String(form.get("brand_id"));
  let job: Queued;
  try {
    job = await api<Queued>(`/brands/${id}/products/run`, { method: "POST" });
  } catch (e) {
    if (is422(e)) return back(id, "empty");
    throw e;
  }
  back(id, encodeURIComponent(job.status));
}

export async function clearProducts(form: FormData) {
  const id = String(form.get("brand_id"));
  await api(`/brands/${id}/products`, { method: "DELETE" });
  back(id, "cleared");
}
```

- [ ] **Step 5: The page**

`apps/web/src/app/(app)/b/[id]/products/page.tsx`:

```tsx
import { api } from "@/lib/api";
import { productNote, type Params } from "@/lib/format";
import type { Product, ProductRuns } from "@/lib/types";
import { clearProducts, importCsv, importFeed, runProducts } from "./actions";

type Job = ProductRuns["jobs"][number];

function statusLine(runs: ProductRuns) {
  const run = runs.jobs.find((j) => j.kind === "product_run");
  if (!run) return null;
  if (run.status === "running" || run.status === "queued") {
    return `Run in progress: ${runs.done} of ${runs.total} products`;
  }
  if (run.status === "failed") return `Last run failed: ${run.error ?? ""}`;
  return "Last run: done";
}

function feedLine(jobs: Job[]) {
  const feed = jobs.find((j) => j.kind === "import_feed");
  if (!feed) return null;
  const detail = feed.status === "failed" && feed.error ? ` (${feed.error})` : "";
  return `Feed import: ${feed.status ?? "queued"}${detail}`;
}

const link = (url: string | null) =>
  url && /^https?:\/\//.test(url) ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {url}
    </a>
  ) : (
    url ?? ""
  );

export default async function Products({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [products, runs] = await Promise.all([
    api<Product[]>(`/brands/${id}/products`),
    api<ProductRuns>(`/brands/${id}/products/runs`),
  ]);
  let msg = productNote(sp.queued);
  if (msg && sp.queued === "imported" && typeof sp.n === "string") {
    msg = `${msg} ${sp.n} products in the catalogue.`;
  }
  const status = statusLine(runs);
  const feed = feedLine(runs.jobs);
  return (
    <>
      <form action={importCsv} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input type="file" name="csv" accept=".csv,text/csv" required />
        <button className="primary">Import CSV</button>
      </form>
      <form action={importFeed} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="url"
          required
          placeholder="https://example.com/merchant-feed.xml"
          style={{ minWidth: 360 }}
        />
        <button>Import Merchant feed</button>
      </form>
      <form action={runProducts} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary" disabled={products.length === 0}>
          Run
        </button>
        <button formAction={clearProducts} formNoValidate>
          Clear products
        </button>
        {products.length > 0 && (
          <a href={`/b/${id}/products/export.csv`}>Download CSV</a>
        )}
        {msg && <span className="muted">{msg}</span>}
      </form>
      {status && <p className="muted">{status}</p>}
      {feed && <p className="muted">{feed}</p>}
      <p className="muted">
        The run infers each product&apos;s generic shopper keyword, compares
        the title with titles that rank for that keyword, and suggests a
        rewrite. Suggestions are drafts to review, not changes to the
        catalogue.
      </p>
      {products.length === 0 && <p className="muted">No products yet.</p>}
      {products.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Keyword</th>
              <th>Missing keywords</th>
              <th>Suggested title</th>
              <th>Check</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.title}
                  {p.url && (
                    <>
                      <br />
                      <span className="muted">{link(p.url)}</span>
                    </>
                  )}
                </td>
                <td>{p.keyword ?? "—"}</td>
                <td>{(p.missing_keywords ?? []).join(", ") || "—"}</td>
                <td>
                  {p.suggested_title ?? "—"}
                  {(p.suggested_bullets ?? []).length > 0 && (
                    <ul className="muted">
                      {(p.suggested_bullets ?? []).map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>
                  {p.rule_check && <span className="tag">{p.rule_check}</span>}
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

- [ ] **Step 6: Run the web checks**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run typecheck && npm run lint && npx vitest run 2>&1 | tail -5`
Expected: clean; the format test passes.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts apps/web/src/lib/types.ts apps/web/next.config.ts "apps/web/src/app/(app)/b/[id]/layout.tsx" "apps/web/src/app/(app)/b/[id]/products" && git commit -m "feat(web): Products tab with CSV and feed import, run and results"
```

---

### Task 7: The CSV download Route Handler

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/products/export.csv/route.ts`
- Create: `apps/web/src/app/(app)/b/[id]/products/export.csv/route.test.ts`

**Interfaces:**
- Consumes: `API_URL`, `COOKIE` from `@/lib/api`; the API's `GET /v1/brands/{id}/products/export.csv` (Task 4).
- Produces: `GET /b/{id}/products/export.csv`.

- [ ] **Step 1: Write the failing test**

`apps/web/src/app/(app)/b/[id]/products/export.csv/route.test.ts`:

```ts
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
const redirect = vi.fn();
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));

const { GET } = await import("./route");

const ID = "34db213a-f484-4991-a969-c52cfa5e1c10";
const call = (id: string) =>
  GET(new Request(`http://web.test/b/${id}/products/export.csv`), {
    params: Promise.resolve({ id }),
  });

beforeEach(() => cookieStore.get.mockReturnValue({ value: "bsi_key_1" }));
afterEach(() => {
  vi.unstubAllGlobals();
  redirect.mockClear();
});

test("streams the API's CSV with the key from the cookie", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("external_id,url\nW-1,\n", {
          status: 200,
          headers: {
            "content-type": "text/csv; charset=utf-8",
            "content-disposition": `attachment; filename="products-${ID}.csv"`,
          },
        }),
    ),
  );
  const res = await call(ID);
  expect(res?.status).toBe(200);
  expect(await res?.text()).toBe("external_id,url\nW-1,\n");
  expect(res?.headers.get("content-type")).toBe("text/csv; charset=utf-8");
  expect(res?.headers.get("content-disposition")).toBe(
    `attachment; filename="products-${ID}.csv"`,
  );
  expect(res?.headers.get("cache-control")).toBe("no-store");
  const [url, init] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/brands/${ID}/products/export.csv`);
  expect(init).toMatchObject({
    cache: "no-store",
    headers: { Authorization: "Bearer bsi_key_1" },
  });
  expect(init?.signal).toBeInstanceOf(AbortSignal);
});

test("a missing cookie redirects to /login without calling the API", async () => {
  cookieStore.get.mockReturnValue(undefined);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await call(ID);
  expect(redirect).toHaveBeenCalledWith("/login");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("a malformed id is 404 and the API is never called", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const res = await call("not-a-uuid");
  expect(res?.status).toBe(404);
  expect(await res?.text()).toBe("Not found");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("API 401 redirects to /login; 404 is 404; 500 and a throw are 502", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  await call(ID);
  expect(redirect).toHaveBeenCalledWith("/login");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  let res = await call(ID);
  expect(res?.status).toBe(404);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
  res = await call(ID);
  expect(res?.status).toBe(502);
  expect(await res?.text()).toBe("Export unavailable");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("ECONNREFUSED http://api.internal:8000");
    }),
  );
  res = await call(ID);
  expect(res?.status).toBe(502);
  expect(await res?.text()).toBe("Export unavailable");
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run "src/app/(app)/b/[id]/products/export.csv" 2>&1 | tail -5`
Expected: FAIL (cannot find `./route`).

- [ ] **Step 3: The route**

`apps/web/src/app/(app)/b/[id]/products/export.csv/route.ts`:

```ts
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_URL, COOKIE } from "@/lib/api";

// The app's second Route Handler (the first is /r/[token]/pdf): a
// same-origin download of the API's products CSV, so the browser never
// sees the API host or the key. It reads the cookie itself because
// api() only returns JSON.
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UPSTREAM_TIMEOUT_MS = 30_000;

const plain = (body: string, status: number) =>
  new Response(body, {
    status,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!ID.test(id)) return plain("Not found", 404);
  const key = (await cookies()).get(COOKIE)?.value;
  if (!key) return redirect("/login");
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/brands/${id}/products/export.csv`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return plain("Export unavailable", 502);
  }
  if (upstream.status === 401) return redirect("/login");
  if (upstream.status === 404) return plain("Not found", 404);
  if (!upstream.ok) return plain("Export unavailable", 502);
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of ["content-type", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
```

Update the comment at the top of `apps/web/src/app/r/[token]/pdf/route.ts` from "The only Route Handler in the app" to "One of the app's two Route Handlers (the other is /b/[id]/products/export.csv)".

- [ ] **Step 4: Run the full web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate 2>&1 | tail -8`
Expected: typecheck, lint, tests, build and `gen:check` all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/products/export.csv" "apps/web/src/app/r/[token]/pdf/route.ts" && git commit -m "feat(web): same-origin products CSV download route"
```

---

### Task 8: Docs — findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice18.md`
- Modify: `docs/README.md` (three rows after the slice 17 rows)
- Modify: the spec's `## Rulings` section
- Modify: this plan (append `## Changes made during execution`)

- [ ] **Step 1: Findings**

`docs/findings-slice18.md` with sections `## 1. What was built` (tables, module, job kinds, routes, the tab, the route handler, the commit table from `git log --oneline main..HEAD`), `## 2. Live check on dev` (left as "not yet run" until the controller runs it after the user's OK to migrate dev; then the observed spend, the writes: `product`, `keyword_search`, `job`, `api_key.last_used_at`), `## 3. Deferred and untested`, seeded from the spec's Out of scope plus every ledger minor, at least:
- a cut feed's note is not stored on the job (ruling);
- the run covers all products in the brand's first locale;
- `keep_present` matches titles as substrings, so a title that is a prefix of a longer one is kept;
- `STOPWORDS` is a short English list;
- `is422` in the web actions keys on the message prefix `api()` builds;
- Shopify OAuth, a SERP provider, history, feed URL on the brand, marketplace check, push to Shopify.

- [ ] **Step 2: README rows**

After the slice 17 rows in `docs/README.md` add rows for the spec, the plan and `findings-slice18.md`, in the same table format.

- [ ] **Step 3: Rulings**

Under the spec's `## Rulings`, record every ruling said in chat during execution, at least: R1 the web notes gain `nofile` and `cap` and the actions map a 422 to `cap`/`empty`; R2 a cut feed's note goes in the job summary, not `job.error`; R3 `keep_present` lowercases domains; plus any made during review.

- [ ] **Step 4: Plan changes**

Append `## Changes made during execution` to this plan listing every deviation from the tasks above.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 18 findings, index and rulings"
```

---

## Self-review

- Spec coverage: §1 → Task 1; §2 → Tasks 2, 4, 5 (feed job), 6; §3 → Tasks 3, 5; §4 → Task 4; §5 → Tasks 6, 7; §6 → the test steps of every task (unit: Tasks 2–3; copy: Task 3; API: Task 4; run: Task 5; RLS/isolation: Tasks 1, 4; web: Tasks 6–7); §7 (live check) and the docs → Task 8 and the controller. The spec's `error = "truncated"` on a done feed job is replaced by ruling R2 (the summary carries the note) — recorded in Task 8.
- Placeholders: none; every step has its code. Task 8 describes docs content rather than quoting it because it depends on the commit hashes and rulings of the run.
- Type consistency: `run_products(org_id, job_id, brand_id, params, generator, adapter, now=None)` matches the worker lambda; `run_import_feed(org_id, brand_id, job_id, params, fetch, feed_fetch=None)` matches its lambda; `upsert(s, org_id, brand_id, rows, source)` is used identically by the router and the worker; `ProductRuns["jobs"][number]` fields match `ProductJobOut`; `EXPORT_COLUMNS` is asserted in Task 2 and printed by Task 4; `OverBudget.cost_micros` is read by `process_job`.
- Spec Testing values checked word for word: `vote` samples and result; `drop_brand_terms` names and result; `missing` example → `["sandals", "summer", "kids"]`; `rule_check` four cases; `keep_present`; export joins; API cases (round trip, cap 422, 413, feed queue + `ftp://`, run 422/202, export header and rows, delete, idle probe); run cases (21 products → two writes, one search per keyword, 6/8-day cache, budget keeps keywords, adjusted, batch-two failure, idle probe); RLS and isolation; `productNote` and the route tests.
- Fixtures: no banned word appears in any fixture string above (`sandal`, `summer`, `kids`, `Walkaroo`, `Secret`, `Light`, `Washable`).

## Changes made during execution

Deviations from the tasks above, by task. Rulings R1–R13 are recorded in the spec's `## Rulings`; R1 (the `nofile` and `cap` notes and the 422 mapping), R3 (lowercased domains in `keep_present`), R4 (Next's `redirect()`, 307) and R8 (the `titles_prompt` name) were already in this plan's code, so they changed the spec, not the code.

Task 2 (0f55f44)
- R5: `parse_feed` sets `closed = True` when the root element ends and, if it never closed, sets the note `malformed` (keeping `truncated` when the gzip cap already set it). The plan's code returned no note for a cut feed and failed `test_parse_feed_cut_mid_item_keeps_complete_items`.
- Fixture reflow for ruff E501: `CSV` became an implicit concatenation of string literals (byte-identical), and `RSS` gained a newline between `</g:price>` and `<g:product_type>` (whitespace between sibling elements; the parse is unchanged).

Task 3 (78fb225, fix 6411ede)
- Reflow for ruff E501: the long titles in the `missing` fixture are split by implicit concatenation, two `rule_check` asserts are wrapped, `keep_present` puts the domain expression in a local `domain`, and the prompts' JSON-shape lines use single-quoted Python literals instead of `\"` escapes (the strings are identical).
- Fix round (review finding): `drop_brand_terms` also drops keywords with no tokens (`""`, `"!!!"`); `test_drop_brand_terms_matches_tokens` gained that case.
- R7: `rule_check` works at the token level: brand prepended first, then any word that shares a token with an earlier kept word is dropped, punctuation-only words kept, then the trim. Three cases added: `Kids-Sandal Sandal` and `Red Tape Tape Shoes` (in `test_rule_check_drops_a_word_that_repeats_an_earlier_token`) and `Walkaroo - Sandal | Kids` (`test_rule_check_keeps_punctuation_only_words`, `pass`). The four planned `rule_check` tests are unchanged.

Task 4 (f7747f7)
- R6: `FORMULA_START` and the apostrophe in `export_rows`, with `test_export_rows_neutralises_formula_cells`.
- Added `test_duplicate_ids_in_one_import_keep_the_last_row` (two `W-1` rows: one product, the second title, `created 1`) and `test_csv_import_ignores_a_leading_bom` (a BOM-prefixed CSV imports as usual).
- Removed the unused `import pytest` from `test_api_products.py` (ruff F401).

Task 5 (f1a7960, fix d89077f)
- In `run_products` the rewrite-phase dict `got` is renamed `rewrites`; reusing `got` clashed with the earlier `got: KeywordSet` under mypy. Behaviour unchanged.
- ruff RUF059 renames in `test_products_run.py`: `searches` → `_searches` in two tests and an unused `job` → `_`. No assertion changed.
- R9: the freshness read filters on `KeywordSearch.error IS NULL`; added `test_an_error_search_is_not_reused`.
- R10: the search-phase check is `budget_fits(s, org_id, 0, extra_micros=spent + len(new) * SEARCH_MICROS)`; added `test_keyword_spend_counts_against_the_search_budget`.

Task 6 (bc88442)
- `PRODUCT_CASES` in `tests/unit/test_recommend_copy.py` gained the page's fixed copy the plan left out: the explanatory paragraph and the button labels `Import CSV`, `Import Merchant feed`, `Run` and `Clear products`.
- R11: `feedLine` kept as planned (an error only on a failed job); the review's Important finding was ruled, not fixed.

Task 7 (66f328a)
- None beyond the plan.

Task 8
- The spec's §1, §2, §3, §4 and §5 were updated to match R2, R5–R11, the tokenless-keyword drop, the last-row-wins dedupe and the `bytes` CSV body; `findings-slice18.md` and the README rows were added. The live check (§2 of the findings) is left to the controller.

Final review fix (bb56ad4)
- R12: `run_products` reads products ordered by `result_at NULLS FIRST, title, id` and runs keywords, searches, rewrite and write for one batch before the next. `PRODUCT_JOB_SECONDS = 480` and an injectable `clock=time.monotonic` stop the run before a batch (never before the first); the summary is then `out of time after {done} of {total} products`. The budget check (R10) and `KEYWORD_CAP` are applied per batch and counted across the run; `titles_by_kw` is kept across batches and seeded per batch.
- R13: a product whose keyword drops has `missing_keywords`, `suggested_title`, `suggested_bullets` and `rule_check` cleared and `job_id`, `result_at` set in the keyword write.
- `test_a_model_failure_in_batch_two_keeps_batch_one` changed meaning: batch one now finishes, suggestions included, before batch two, so `fail_on` is 6 (batch two's first keyword call), 20 products have a keyword and a suggestion, the 21st has neither, and `cost_micros` is `3*700 + 35_000 + 700 + 700`.
- Added `test_a_run_stops_at_the_time_budget` (41 products, a clock that reads 0 then 481; `run_products` called directly for the summary), `test_a_second_run_continues_with_the_oldest_results` (25 products; the second run's first rewrite prompt starts with the 5 unrun titles) and `test_a_product_whose_keyword_drops_loses_its_old_suggestion`. `_generator` gained a `keywords` argument.
- The summary's keyword count is the run's distinct rank-1 keywords.
