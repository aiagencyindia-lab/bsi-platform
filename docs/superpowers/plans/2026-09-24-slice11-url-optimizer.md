# Slice 11: URL Optimizer and AI Citability Score — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score a brand page (0–100, nine visible components, versioned weights) against one content-gap cluster and turn the shortfall into cited suggestions and an `optimize_page` recommendation.

**Architecture:** A new pure module `bsi_core/pages.py` parses HTML and scores it against a `Target` built from a gap cluster; the worker job `optimize_url` reads the cluster, fetches the page once with no transaction open, embeds its sections once, and stores a `page_audit` row; `recommend._pages` turns low scores into recommendations; the API queues jobs and lists audits; the Clusters tab submits URLs and a new Pages tab shows results.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, stdlib `html.parser`/`json`/`re`/`math`, `gemini-embedding-001` via `bsi_core.suggest.embed`; Next.js 15 App Router (Server Components + server actions), openapi-typescript, vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-slice11-url-optimizer-design.md`

## Global Constraints

- Python 3.13; ruff line length 80; `mypy --strict` over `packages/core/bsi_core` (new module must type-check).
- Every tenant table: `org_id`, RLS via `_protect()`, listed in `TENANT_TABLES` and populated in `org_b` (`tests/integration/test_rls.py`).
- Every id-taking route: a row in `CASES` (`tests/integration/test_isolation.py`) plus an owner-2xx test.
- No transaction open during a fetch or a model call.
- SQL: only fixed fragments concatenated; every value bound.
- Money in micros; `JOB_ESTIMATES[kind]` gates the budget.
- Recommendation copy never contains: `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain`; body contains `Metric to watch:`.
- Frontend: Server Components and server actions only; no `"use client"`; API key only in `lib/api.ts`; no sorting or statistics in the frontend; links only when the URL starts with `http://` or `https://`, with `rel="noreferrer"`.
- Tests compute expectations from fixtures; no network; fakes return 768-dim vectors.
- Commit trailer from the current session reminder (`Co-Authored-By: …`). Work on branch `slice11-url-optimizer` (already created; spec committed).
- Gate after every task: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100` (web tasks add `cd apps/web && npm run gate`).
- The shell's cwd resets after every command: prefix each with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Deviation from the spec, decided while planning: no `final_url` column — `crawl.http_fetch` returns `Response(status, body, error)` without the final URL, so there is nothing to store.

---

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0014_page_audit_and_optimize_page.py` | `page_audit` table + RLS; `optimize_page` rec type |
| `packages/core/bsi_core/models.py` | `PageAudit` ORM; `REC_TYPES` |
| `packages/core/bsi_core/pages.py` (new) | `Page` parser, `Target`, `score()`, suggestions, `normalize_url()`, `cosine()` |
| `packages/core/bsi_core/recommend.py` | `FEASIBILITY["optimize_page"]`, `PAGE_SCORE_THRESHOLD`, `page_copy()`, `_pages()` |
| `apps/workers/bsi_workers/worker.py` | `PAGE_JOB_MICROS`, `cited_urls()`, `audit_page()`, `run_page_audit()`, runner entry |
| `apps/api/bsi_api/schemas.py`, `routers/pages.py` (new), `routers/runs.py`, `main.py` | routes and schemas |
| `apps/web/src/app/(app)/b/[id]/pages/page.tsx` (new), `clusters/{page,actions}.tsx`, `layout.tsx`, `lib/{format,types}.ts` | web |
| `scripts/score_page.py` (new) | read-only live check |
| `tests/unit/test_pages.py`, `tests/integration/test_page_audit.py`, `tests/integration/test_api_pages.py` (new); `test_rls.py`, `test_isolation.py`, `test_recommend.py`, `test_recommend_copy.py` | tests |
| `docs/findings-slice11.md`, `docs/README.md` | findings |

---

### Task 1: Migration 0014, `PageAudit` model, rec type

**Files:**
- Create: `migrations/versions/0014_page_audit_and_optimize_page.py`
- Modify: `packages/core/bsi_core/models.py` (`REC_TYPES` at line 39; add `PageAudit` after `SiteAudit`, ~line 436)
- Modify: `tests/integration/test_rls.py` (`TENANT_TABLES` line 10; `org_b` fixture ~line 100)

**Interfaces:**
- Produces: `m.PageAudit(org_id, brand_id, job_id, url, cluster_key, status, error, weights_version, score, components, suggestions, evidence, fetches)`; `"optimize_page" in m.REC_TYPES`.

- [ ] **Step 1: Add the RLS expectation (failing test)**

In `tests/integration/test_rls.py`, append `"page_audit"` to `TENANT_TABLES` and, in `org_b` right after the `m.SiteAudit(...)` add, insert:

```python
        s.add(
            m.PageAudit(
                org_id=b.id,
                brand_id=bid,
                url="https://b.com/p",
                cluster_key="cluster:guide:x",
                status=200,
                weights_version="v1",
                score=50,
            )
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rls.py -x`
Expected: FAIL — `AttributeError: module 'bsi_core.models' has no attribute 'PageAudit'`.

- [ ] **Step 3: Write the migration**

```python
"""page_audit table; optimize_page rec type"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
OLD_TYPES = (
    "'pursue_citation_source', 'create_content', "
    "'add_competitor', 'sample_more', 'fix_crawlability', 'fix_entity'"
)
NEW_TYPES = OLD_TYPES + ", 'optimize_page'"


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    op.create_table(
        "page_audit",
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
        sa.Column("job_id", sa.Uuid()),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("cluster_key", sa.String(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("weights_version", sa.String(), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column(
            "components",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "suggestions",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "evidence", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_audit_latest",
        "page_audit",
        ["brand_id", "cluster_key", "url", "created_at"],
    )
    _protect("page_audit")
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM task WHERE recommendation_id IN "
        "(SELECT id FROM recommendation WHERE type = 'optimize_page')"
    )
    op.execute("DELETE FROM recommendation WHERE type = 'optimize_page'")
    _rec_type_check(OLD_TYPES)
    op.drop_index("ix_page_audit_latest", table_name="page_audit")
    op.drop_table("page_audit")
```

- [ ] **Step 4: Add the model and the rec type**

In `models.py`, add `"optimize_page",` as the last entry of `REC_TYPES`, and after `SiteAudit`:

```python
class PageAudit(Tenant, Base):
    """One scoring of one URL against one gap cluster; the latest row per
    (cluster_key, url) is what the Pages tab and the optimize_page rule
    read. A failed fetch is stored too (score NULL, error set)."""

    __tablename__ = "page_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    url: Mapped[str]
    cluster_key: Mapped[str]
    status: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None]
    weights_version: Mapped[str]
    score: Mapped[int | None]
    components: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    suggestions: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    fetches: Mapped[int] = mapped_column(server_default="0")
    __table_args__ = (
        Index(
            "ix_page_audit_latest", "brand_id", "cluster_key", "url", "created_at"
        ),
    )
```

- [ ] **Step 5: Migrate dev and run the RLS tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head && uv run pytest -q tests/integration/test_rls.py tests/integration/test_recommend.py`
Expected: migrations apply both ways; all tests PASS (the test DB migrates to head in `conftest`).

- [ ] **Step 6: Gate and commit**

Run the gate. Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0014_page_audit_and_optimize_page.py packages/core/bsi_core/models.py tests/integration/test_rls.py && git commit -m "feat(db): page_audit table and optimize_page rec type (0014)"
```

---

### Task 2: `pages.py` — the parser and `normalize_url`

**Files:**
- Create: `packages/core/bsi_core/pages.py`
- Test: `tests/unit/test_pages.py`

**Interfaces:**
- Produces:
  - `Section(level: int, heading: str, text: str)` with `.embed_text() -> str` (`f"{heading}\n{text}"`).
  - `Page` attributes: `title: str | None`, `description: str | None`, `author: str | None`, `ld: list[str]`, `headings: list[tuple[int, str]]`, `sections: list[Section]`, `tables: int`, `lists: int`, `ordered_lists: int`, `links: list[tuple[str, str]]` (href, rel), `byline: bool`, `words: int`, `h1_count` property.
  - `parse(html: str) -> Page`.
  - `normalize_url(url: str) -> str` (raises `ValueError`).
  - Constants `SECTION_CAP = 60`, `SECTION_CHARS = 2_000`.

- [ ] **Step 1: Write the failing parser tests**

`tests/unit/test_pages.py`:

```python
"""URL optimizer (PRD F11): the page parser, the score, the suggestions."""

import pytest
from bsi_core import pages
from bsi_core.pages import SECTION_CAP, SECTION_CHARS, normalize_url, parse

ARTICLE = """<html><head><title>Best school shoes for kids</title>
<meta name="description" content="Acme picks the best school shoes">
<meta name="author" content="Jane Doe">
<script type="application/ld+json">{"@type":"Article","author":
{"@type":"Person","name":"Jane"}}</script>
<script>var x = 1;</script></head><body>
<nav><a href="/home">Home</a> nav words here</nav>
<h1>Best school shoes for kids</h1>
<p>Acme has sold school shoes for years.</p>
<h2>Which school shoes last longest?</h2>
<p>Leather uppers last longest. They cost more but outlast canvas.</p>
<table><tr><th>Shoe</th><th>Price</th></tr><tr><td>A</td><td>1</td></tr>
</table>
<h2>Our picks</h2>
<ol><li>One</li><li>Two</li><li>Three</li></ol>
<h3>Budget</h3><p>Under 1000.</p>
<div class="byline">By Jane</div>
<a href="https://forbes.com/x" rel="nofollow">Forbes</a>
<a href="https://acme.com/about">About</a>
<h2>FAQ</h2>
<footer>footer words</footer>
</body></html>"""


def test_parse_collects_head_fields_and_skips_boilerplate():
    p = parse(ARTICLE)
    assert p.title == "Best school shoes for kids"
    assert p.description == "Acme picks the best school shoes"
    assert p.author == "Jane Doe"
    assert len(p.ld) == 1 and '"Article"' in p.ld[0]
    assert p.h1_count == 1
    assert p.headings == [
        (1, "Best school shoes for kids"),
        (2, "Which school shoes last longest?"),
        (2, "Our picks"),
        (3, "Budget"),
        (2, "FAQ"),
    ]
    assert p.tables == 1 and p.lists == 1 and p.ordered_lists == 1
    assert p.links == [
        ("https://forbes.com/x", "nofollow"),
        ("https://acme.com/about", ""),
    ]
    assert p.byline is True
    # nav, footer and script text never reach the word count.
    assert "nav" not in " ".join(s.text for s in p.sections)
    assert p.words == len(
        "Acme has sold school shoes for years. Leather uppers last longest. "
        "They cost more but outlast canvas. Shoe Price A 1 One Two Three "
        "Under 1000. By Jane Forbes About".split()
    )


def test_sections_follow_headings_and_keep_their_text():
    p = parse(ARTICLE)
    assert [s.heading for s in p.sections] == [h for _, h in p.headings]
    first = p.sections[1]
    assert first.level == 2
    assert first.text.startswith("Leather uppers last longest.")
    assert "Shoe Price" in first.text  # table text belongs to its section
    assert first.embed_text() == f"{first.heading}\n{first.text}"


def test_tables_and_lists_need_two_rows_and_three_items():
    p = parse("<h1>x</h1><table><tr><td>1</td></tr></table><ul><li>a</li>"
              "<li>b</li></ul><ol><li>a</li><li>b</li><li>c</li></ol>")
    assert (p.tables, p.lists, p.ordered_lists) == (0, 1, 1)


def test_sections_are_capped():
    html = "<h1>t</h1>" + "".join(
        f"<h2>h{i}</h2><p>{'w ' * 3000}</p>" for i in range(SECTION_CAP + 5)
    )
    p = parse(html)
    assert len(p.sections) == SECTION_CAP
    assert all(len(s.text) <= SECTION_CHARS for s in p.sections)
    assert len(p.headings) == SECTION_CAP + 6  # every heading still counted


def test_author_from_rel_or_class_or_id():
    assert parse('<a rel="author" href="/j">J</a>').byline is True
    assert parse('<span id="post-author">J</span>').byline is True
    assert parse("<p>By nobody</p>").byline is False


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("HTTPS://Acme.com/Shoes?x=1#top", "https://acme.com/Shoes?x=1"),
        ("http://acme.com", "http://acme.com/"),
    ],
)
def test_normalize_url(raw, clean):
    assert normalize_url(raw) == clean


@pytest.mark.parametrize(
    "bad",
    ["ftp://acme.com/x", "acme.com/x", "http://user:pw@acme.com/", "http:///x"],
)
def test_normalize_url_refuses(bad):
    with pytest.raises(ValueError):
        normalize_url(bad)


def test_module_states_the_score_is_a_diagnostic():
    assert "not a promised outcome" in pages.NOTE
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pages.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'bsi_core.pages'`.

- [ ] **Step 3: Write the parser**

`packages/core/bsi_core/pages.py`:

```python
"""URL optimizer and AI Citability Score (PRD F11, second half).

`parse` reads one HTML page into the few things the score looks at;
`score` compares that page with one content-gap cluster (a `Target`) and
returns nine weighted components, a 0-100 score and four suggestion
lists. Pure: the caller fetches and embeds."""

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

NOTE = (
    "The AI Citability Score is a diagnostic of the page against this "
    "cluster's prompts and sources, not a promised outcome."
)
SECTION_CAP = 60
SECTION_CHARS = 2_000
_SKIP = frozenset(
    {"script", "style", "nav", "header", "footer", "aside", "noscript",
     "template", "svg"}
)
_LEVELS = {"h1": 1, "h2": 2, "h3": 3}


@dataclass
class Section:
    level: int
    heading: str
    text: str = ""

    def embed_text(self) -> str:
        return f"{self.heading}\n{self.text}"


def _squash(s: str) -> str:
    return " ".join(s.split())


class Page(HTMLParser):
    """Collects what the score looks at, and nothing else."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.author: str | None = None
        self.ld: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.sections: list[Section] = []
        self.tables = 0
        self.lists = 0
        self.ordered_lists = 0
        self.links: list[tuple[str, str]] = []
        self.byline = False
        self.words = 0
        self._skip = 0
        self._in: str | None = None
        self._heading: tuple[int, list[str]] | None = None
        self._section: Section | None = None
        self._rows: list[int] = []
        self._items: list[tuple[str, int]] = []

    @property
    def h1_count(self) -> int:
        return sum(1 for level, _ in self.headings if level == 1)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == (
            "application/ld+json"
        ):
            self._in = "ld"
            self.ld.append("")
            return
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        marker = f"{a.get('class', '')} {a.get('id', '')}".lower()
        if "author" in marker or "byline" in marker:
            self.byline = True
        if tag == "title":
            self._in = "title"
            self.title = self.title or ""
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description":
                self.description = a.get("content", "")
            elif name == "author":
                self.author = a.get("content", "")
        elif tag in _LEVELS:
            self._in = "heading"
            self._heading = (_LEVELS[tag], [])
        elif tag == "table":
            self._rows.append(0)
        elif tag == "tr" and self._rows:
            self._rows[-1] += 1
        elif tag in ("ol", "ul"):
            self._items.append((tag, 0))
        elif tag == "li" and self._items:
            kind, n = self._items[-1]
            self._items[-1] = (kind, n + 1)
        elif tag == "a" and a.get("href"):
            rel = a.get("rel", "").lower()
            self.links.append((a["href"], rel))
            if "author" in rel.split():
                self.byline = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in == "ld":
            self._in = None
            return
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "title":
            self._in = None
        elif tag in _LEVELS and self._heading is not None:
            level, chunks = self._heading
            text = _squash("".join(chunks))
            self.headings.append((level, text))
            if len(self.sections) < SECTION_CAP:
                self._section = Section(level, text)
                self.sections.append(self._section)
            else:
                self._section = None
            self._heading = None
            self._in = None
        elif tag == "table" and self._rows:
            if self._rows.pop() >= 2:
                self.tables += 1
        elif tag in ("ol", "ul") and self._items:
            kind, n = self._items.pop()
            if n >= 3:
                self.lists += 1
                if kind == "ol":
                    self.ordered_lists += 1

    def handle_data(self, data: str) -> None:
        if self._in == "ld":
            self.ld[-1] += data
            return
        if self._skip:
            return
        if self._in == "title" and self.title is not None:
            self.title += data
        elif self._in == "heading" and self._heading is not None:
            self._heading[1].append(data)
        else:
            self.words += len(data.split())
            s = self._section
            if s is not None and len(s.text) < SECTION_CHARS:
                s.text = (s.text + " " + data)[:SECTION_CHARS]


def parse(html: str) -> Page:
    page = Page()
    page.feed(html)
    page.close()
    if page.title is not None:
        page.title = _squash(page.title)
    for s in page.sections:
        s.text = _squash(s.text)
    return page


def normalize_url(url: str) -> str:
    """http(s), a host, no userinfo; scheme and host lower-cased, fragment
    dropped, an empty path made '/'. ValueError otherwise."""
    u = urlsplit(url.strip())
    scheme = u.scheme.lower()
    if scheme not in ("http", "https") or not u.hostname or u.username:
        raise ValueError(f"not an http(s) URL: {url!r}")
    host = u.hostname.lower() + (f":{u.port}" if u.port else "")
    return urlunsplit((scheme, host, u.path or "/", u.query, ""))
```

(Task 3 adds the imports it needs — `math`, `re`, `field`, `Any`, and the `entity`/`matching` helpers — so ruff stays clean after this task.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pages.py`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/pages.py tests/unit/test_pages.py && git commit -m "feat(pages): HTML parser and URL normalisation for the optimizer"
```

---

### Task 3: `pages.py` — `Target`, `score()` and suggestions

**Files:**
- Modify: `packages/core/bsi_core/pages.py`
- Test: `tests/unit/test_pages.py`

**Interfaces:**
- Consumes: `Page`, `parse`, `Section.embed_text` (Task 2); `entity._ld_nodes(scripts) -> list[dict]`, `entity._types(node) -> set[str]`, `entity._names_in(text, names: set[str]) -> bool`; `matching.is_owned(domain, hosts) -> bool`; `gaps.PAGE_TYPES`.
- Produces:
  - `WEIGHTS_VERSION = "v1"`, `WEIGHTS: dict[str, int]` (ordered, weight desc), `COS_FLOOR = 0.55`, `COS_SPAN = 0.30`, `COS_COVERED = 0.70`, `FIRST_SENTENCE_WORDS = 40`, `MIN_WORDS = 300`.
  - `cosine(a: list[float], b: list[float]) -> float`.
  - `Target(intent, topic, queries: list[tuple[str, str]], rivals: list[str], brand: str, aliases: list[str], brand_hosts: list[str], rival_hosts: list[str], cited: list[dict[str, Any]], observation_ids: list[str])` where each `cited` item is `{"url", "domain", "answers", "observation_ids"}` and `queries` are `(prompt_id, text)`.
  - `score(page: Page, t: Target, query_vectors: list[list[float] | None], section_vectors: list[list[float]]) -> dict[str, Any]` returning `{"score": int, "weights_version": str, "components": list[dict], "suggestions": dict[str, list[dict]]}`; component `{"code", "weight", "value", "points", "observed", "evidence": list[str]}`; suggestion `{"text", "urls", "prompt_ids", "observation_ids"}` under keys `add`, `remove`, `rewrite`, `evidence_to_add`.

- [ ] **Step 1: Write the failing score tests**

Append to `tests/unit/test_pages.py`:

```python
import hashlib

from bsi_core.pages import (
    COS_COVERED,
    COS_FLOOR,
    COS_SPAN,
    WEIGHTS,
    WEIGHTS_VERSION,
    Target,
    cosine,
    score,
)


def bow(text):
    """Deterministic 768-dim bag-of-words vector; cosine is meaningful."""
    v = [0.0] * 768
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.sha1(w.encode()).hexdigest(), 16) % 768] += 1.0
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else [0.0] * 767 + [1.0]


def vectors(page, queries):
    return [bow(q) for _, q in queries], [bow(s.embed_text()) for s in page.sections]


def target(**kw):
    base = dict(
        intent="recommendation",
        topic="school shoes",
        queries=[("p1", "best school shoes for kids"), ("p2", "durable school shoes")],
        rivals=["Bata", "Campus"],
        brand="Acme",
        aliases=[],
        brand_hosts=["acme.com"],
        rival_hosts=["bata.in"],
        cited=[
            {
                "url": "https://forbes.com/x",
                "domain": "forbes.com",
                "answers": 3,
                "observation_ids": ["o1", "o2", "o3"],
            },
            {
                "url": "https://bata.in/school",
                "domain": "bata.in",
                "answers": 2,
                "observation_ids": ["o1", "o4"],
            },
        ],
        observation_ids=["o1", "o2", "o3", "o4"],
    )
    return Target(**{**base, **kw})


def by_code(result):
    return {c["code"]: c for c in result["components"]}


def test_weights_sum_to_100_and_are_in_weight_order():
    assert sum(WEIGHTS.values()) == 100
    assert list(WEIGHTS.values()) == sorted(WEIGHTS.values(), reverse=True)


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_score_is_the_weighted_sum_and_components_are_in_weight_order():
    p = parse(ARTICLE)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    assert r["weights_version"] == WEIGHTS_VERSION
    assert [c["code"] for c in r["components"]] == list(WEIGHTS)
    for c in r["components"]:
        assert c["weight"] == WEIGHTS[c["code"]]
        assert c["points"] == round(c["weight"] * c["value"], 2)
        assert 0.0 <= c["value"] <= 1.0
    assert r["score"] == round(sum(c["points"] for c in r["components"]))


def test_topic_coverage_is_mean_best_cosine_mapped_and_names_uncovered():
    p = parse(ARTICLE)
    t = target()
    qv, sv = vectors(p, t.queries)
    r = score(p, t, qv, sv)
    best = [max(cosine(q, s) for s in sv) for q in qv]
    expect = sum(min(1.0, max(0.0, (b - COS_FLOOR) / COS_SPAN)) for b in best)
    c = by_code(r)["topic_coverage"]
    assert c["value"] == pytest.approx(round(expect / len(best), 4))
    uncovered = [t.queries[i] for i, b in enumerate(best) if b < COS_COVERED]
    adds = [
        s for s in r["suggestions"]["add"]
        if s["text"].startswith("Add a section that answers")
    ]
    assert [s["prompt_ids"] for s in adds] == [[pid] for pid, _ in uncovered]
    for s in adds:
        assert s["observation_ids"] == t.observation_ids


def test_topic_coverage_without_prompt_vectors_is_zero():
    p = parse(ARTICLE)
    t = target()
    r = score(p, t, [None, None], vectors(p, t.queries)[1])
    c = by_code(r)["topic_coverage"]
    assert c["value"] == 0.0 and "no prompt embeddings" in c["observed"]


def test_intent_fit_by_page_type():
    p = parse(ARTICLE)  # a table, a list, 3 H2, > 30 words, no Product schema
    comparison = target(intent="comparison")
    r = score(p, comparison, *vectors(p, comparison.queries))
    # comparison page: table (yes) + two rivals named (no) -> 0.5
    assert by_code(r)["intent_fit"]["value"] == 0.5
    product = target(intent="transactional")
    r = score(p, product, *vectors(p, product.queries))
    assert by_code(r)["intent_fit"]["value"] == 0.0
    assert any("Product" in s["text"] for s in r["suggestions"]["add"])


def test_entity_coverage():
    p = parse(ARTICLE)
    t = target()  # Acme in title and body and description -> 1.0
    assert by_code(score(p, t, *vectors(p, t.queries)))["entity_coverage"]["value"] == 1.0
    t2 = target(brand="Zed")
    c = by_code(score(p, t2, *vectors(p, t2.queries)))["entity_coverage"]
    assert c["value"] == 0.0
    t3 = target(intent="comparison", rivals=["Bata", "Campus"], brand="Zed")
    body = ARTICLE.replace("<p>Acme has", "<p>Bata and Acme has")
    p3 = parse(body)
    c = by_code(score(p3, t3, *vectors(p3, t3.queries)))["entity_coverage"]
    assert c["value"] == pytest.approx(0.25 * 0.5)  # one of two rivals


def test_evidence_links_to_cited_domains_and_other_third_parties():
    p = parse(ARTICLE)  # forbes.com (cited) linked; acme.com is owned
    t = target()
    c = by_code(score(p, t, *vectors(p, t.queries)))["evidence"]
    assert c["value"] == pytest.approx(0.6 * (1 / 3) + 0.4 * 0)
    r = score(p, t, *vectors(p, t.queries))
    ev = r["suggestions"]["evidence_to_add"]
    # forbes is already linked; the Bata page is a cited competitor page.
    assert [s["urls"] for s in ev] == [["https://bata.in/school"]]
    assert ev[0]["observation_ids"] == ["o1", "o4"]


def test_author_structure_faqs_tables_direct_answers():
    p = parse(ARTICLE)
    t = target()
    c = by_code(score(p, t, *vectors(p, t.queries)))
    assert c["author_attribution"]["value"] == 1.0
    # one H1 (0.3) + 3 H2 (0.3) + no level skipped (0.2) + < 300 words (0)
    assert c["structure"]["value"] == pytest.approx(0.8)
    # no FAQPage schema; one heading ends in "?" and one contains "FAQ"
    assert c["faqs"]["value"] == 0.6
    assert c["tables"]["value"] == 1.0
    # H2 sections: "Which school shoes..." (direct), "Our picks" (direct),
    # "FAQ" (empty text -> not direct)
    assert c["direct_answers"]["value"] == pytest.approx(2 / 3)


def test_direct_answer_boundaries():
    long = "word " * 41
    html = f"<h1>t</h1><h2>a</h2><p>{long}.</p><h2>b</h2><p>In this article we cover x.</p><h2>c</h2><p>Yes.</p>"
    p = parse(html)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    assert by_code(r)["direct_answers"]["value"] == pytest.approx(1 / 3)
    texts = [s["text"] for s in r["suggestions"]["rewrite"]]
    assert any("“a”" in x for x in texts) and any("“b”" in x for x in texts)
    assert any("“b”" in s["text"] for s in r["suggestions"]["remove"])


def test_faqpage_schema_and_extra_h1_and_no_h2():
    html = (
        '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        "<h1>a</h1><h1>b</h1><p>x</p>"
    )
    p = parse(html)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    c = by_code(r)
    assert c["faqs"]["value"] == 1.0
    assert c["structure"]["value"] == pytest.approx(0.2)  # levels fine only
    assert c["direct_answers"]["value"] == 0.0
    assert any("extra H1" in s["text"] for s in r["suggestions"]["remove"])


def test_every_suggestion_cites_an_id_or_a_url():
    p = parse("<h1>Nothing here</h1><p>x</p>")
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    items = [s for lst in r["suggestions"].values() for s in lst]
    assert items
    for s in items:
        assert s["urls"] or s["prompt_ids"] or s["observation_ids"], s
```

Add `import math` and `import re` at the top of the test file.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pages.py`
Expected: FAIL — `ImportError: cannot import name 'Target'`.

- [ ] **Step 3: Write the scorer**

Append to `packages/core/bsi_core/pages.py` (and extend the imports at the top of the module to):

```python
import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .entity import _ld_nodes, _names_in, _types
from .matching import is_owned
```

then:

```python
WEIGHTS_VERSION = "v1"
# Weight order is display order; the frontend sorts nothing.
WEIGHTS = {
    "topic_coverage": 25,
    "evidence": 15,
    "intent_fit": 10,
    "entity_coverage": 10,
    "structure": 10,
    "faqs": 10,
    "direct_answers": 10,
    "author_attribution": 5,
    "tables": 5,
}
# ponytail: hand-picked for gemini-embedding-001 from the slice-4 probe
# (unrelated ~0.5, paraphrase ~0.8); recalibrate after real pages.
COS_FLOOR = 0.55
COS_SPAN = 0.30
COS_COVERED = 0.70
FIRST_SENTENCE_WORDS = 40
MIN_WORDS = 300
_OPENERS = re.compile(r"^\s*in this (article|post|guide|page)\b", re.I)
_FAQ = re.compile(r"\b(faqs?|questions)\b", re.I)

# Page-type signals (gaps.PAGE_TYPES values). Each is (what to add, ok).
_LIST_AND_H2 = ("a list", "at least two H2 sections")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Target:
    """What the score compares the page with: one gap cluster."""

    intent: str
    topic: str
    queries: list[tuple[str, str]]  # (prompt_id, text), worst first
    rivals: list[str]
    brand: str
    aliases: list[str]
    brand_hosts: list[str]
    rival_hosts: list[str]
    cited: list[dict[str, Any]]  # {url, domain, answers, observation_ids}
    observation_ids: list[str]  # the cluster's absent answers
    page_type: str = field(init=False)

    def __post_init__(self) -> None:
        from .gaps import PAGE_TYPES  # gaps imports recommend imports pages

        self.page_type = PAGE_TYPES[self.intent]


def _suggestion(
    text: str,
    *,
    urls: list[str] | None = None,
    prompt_ids: list[str] | None = None,
    observation_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "urls": urls or [],
        "prompt_ids": prompt_ids or [],
        "observation_ids": observation_ids or [],
    }


def _first_sentence_words(text: str) -> int:
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return len(first.split())


def _signals(t: Target, page: Page, rivals_named: int) -> list[tuple[str, bool]]:
    h2 = sum(1 for level, _ in page.headings if level == 2)
    types = {x for n in _ld_nodes(page.ld) for x in _types(n)}
    pt = t.page_type
    if pt == "comparison page":
        return [
            ("a comparison table", page.tables >= 1),
            ("at least two rivals named", rivals_named >= 2),
        ]
    if pt == "best-of round-up":
        return [
            ("a list of at least three picks", page.lists >= 1),
            ("at least three H2 sections", h2 >= 3),
        ]
    if pt == "guide":
        return [
            ("at least three H2 sections", h2 >= 3),
            (f"at least {MIN_WORDS} words", page.words >= MIN_WORDS),
        ]
    if pt in ("product page", "category page"):
        return [
            (
                "Product, Offer or ItemList schema",
                bool(types & {"Product", "Offer", "ItemList"}),
            )
        ]
    if pt == "how-to":
        return [
            (
                "HowTo schema or an ordered list of steps",
                "HowTo" in types or page.ordered_lists >= 1,
            )
        ]
    return [(_LIST_AND_H2[0], page.lists >= 1), (_LIST_AND_H2[1], h2 >= 2)]


def score(
    page: Page,
    t: Target,
    query_vectors: list[list[float] | None],
    section_vectors: list[list[float]],
) -> dict[str, Any]:
    """Nine components, the weighted score and the suggestion lists.

    `query_vectors` is aligned with `t.queries` (None: no embedding);
    `section_vectors` with `page.sections`."""
    obs = t.observation_ids
    values: dict[str, tuple[float, str, list[str]]] = {}
    add: list[dict[str, Any]] = []
    remove: list[dict[str, Any]] = []
    rewrite: list[dict[str, Any]] = []
    evidence_to_add: list[dict[str, Any]] = []

    # topic_coverage
    best: list[tuple[str, str, float]] = []
    for (pid, q), qv in zip(t.queries, query_vectors, strict=True):
        if qv is None or not section_vectors:
            continue
        best.append((pid, q, max(cosine(qv, sv) for sv in section_vectors)))
    if best:
        mapped = [
            min(1.0, max(0.0, (b - COS_FLOOR) / COS_SPAN)) for *_, b in best
        ]
        value = round(sum(mapped) / len(mapped), 4)
        uncovered = [(pid, q) for pid, q, b in best if b < COS_COVERED]
        observed = (
            f"{len(best) - len(uncovered)} of {len(best)} prompts covered"
        )
        for pid, q in uncovered:
            add.append(
                _suggestion(
                    f"Add a section that answers “{q}” directly.",
                    prompt_ids=[pid],
                    observation_ids=obs,
                )
            )
        values["topic_coverage"] = (value, observed, [q for _, q in uncovered])
    else:
        values["topic_coverage"] = (0.0, "no prompt embeddings or sections", [])

    # text the entity and rival checks read
    body = " ".join(
        [page.title or "", *(h for _, h in page.headings)]
        + [s.text for s in page.sections]
    )
    names = {t.brand, *t.aliases}
    rivals_named = [r for r in t.rivals if _names_in(body, {r})]

    # evidence
    page_hosts = [*t.brand_hosts]
    cited_domains = [c["domain"] for c in t.cited]
    linked_cited: set[str] = set()
    other: set[str] = set()
    for href, _ in page.links:
        host = urlsplit(href).hostname if href.startswith(("http:", "https:")) else None
        if not host or is_owned(host, page_hosts) or is_owned(host, t.rival_hosts):
            continue
        (linked_cited if is_owned(host, cited_domains) else other).add(host)
    value = round(
        0.6 * min(1.0, len(linked_cited) / 3) + 0.4 * min(1.0, len(other) / 5), 4
    )
    linked = sorted(linked_cited)
    for c in t.cited:
        # Already linked: the cited domain is one of (or under) a linked
        # host, or a linked host is under the cited domain.
        if is_owned(c["domain"], linked) or any(
            is_owned(h, [c["domain"]]) for h in linked
        ):
            continue
        evidence_to_add.append(
                _suggestion(
                    f"Cite {c['url']}: {c['answers']} answers in this cluster "
                    "draw on it.",
                    urls=[c["url"]],
                    observation_ids=list(c["observation_ids"]),
                )
            )
    values["evidence"] = (
        value,
        f"{len(linked_cited)} cited domains linked, {len(other)} other "
        "third-party domains",
        sorted(linked_cited),
    )

    # intent_fit
    signals = _signals(t, page, len(rivals_named))
    value = round(sum(ok for _, ok in signals) / len(signals), 4)
    for what, ok in signals:
        if not ok:
            add.append(
                _suggestion(
                    f"Add {what}: a {t.page_type} is expected to have it.",
                    observation_ids=obs,
                )
            )
    values["intent_fit"] = (
        value,
        f"{t.page_type}: " + ", ".join(f"{w} {'yes' if ok else 'no'}" for w, ok in signals),
        [],
    )

    # entity_coverage
    head = f"{page.title or ''} {' '.join(h for l, h in page.headings if l == 1)}"
    in_head = _names_in(head, names)
    in_body = _names_in(body, names)
    value = 0.5 * in_head + 0.25 * in_body
    if t.intent in ("comparison", "alternative"):
        value += 0.25 * (len(rivals_named) / len(t.rivals) if t.rivals else 1.0)
        for r in t.rivals:
            if r not in rivals_named:
                add.append(
                    _suggestion(
                        f"Name {r}: the cluster's answers name it.",
                        prompt_ids=[pid for pid, _ in t.queries],
                        observation_ids=obs,
                    )
                )
    else:
        value += 0.25 * _names_in(page.description or "", names)
    if not in_head:
        rewrite.append(
            _suggestion(
                f"Name {t.brand} in the title or H1.", observation_ids=obs
            )
        )
    values["entity_coverage"] = (
        round(value, 4),
        f"brand in title/H1 {'yes' if in_head else 'no'}, in body "
        f"{'yes' if in_body else 'no'}, rivals named {len(rivals_named)}",
        rivals_named,
    )

    # structure
    levels = [level for level, _ in page.headings]
    skipped = any(b - a > 1 for a, b in zip(levels, levels[1:], strict=False))
    h2 = levels.count(2)
    value = (
        0.3 * (page.h1_count == 1)
        + 0.3 * (h2 >= 3)
        + 0.2 * (not skipped)
        + 0.2 * (page.words >= MIN_WORDS)
    )
    if page.h1_count > 1:
        remove.append(
            _suggestion(
                f"Remove the {page.h1_count - 1} extra H1 heading(s); keep one.",
                observation_ids=obs,
            )
        )
    elif page.h1_count == 0:
        add.append(_suggestion("Add one H1 naming the topic.", observation_ids=obs))
    if h2 < 3:
        add.append(
            _suggestion(
                "Add H2 sections, one per prompt the cluster asks.",
                prompt_ids=[pid for pid, _ in t.queries],
                observation_ids=obs,
            )
        )
    if skipped:
        rewrite.append(
            _suggestion("Fix skipped heading levels (H1 to H3).", observation_ids=obs)
        )
    if page.words < MIN_WORDS:
        rewrite.append(
            _suggestion(
                f"Expand the page: {page.words} words, under {MIN_WORDS}.",
                observation_ids=obs,
            )
        )
    values["structure"] = (
        round(value, 4),
        f"{page.h1_count} H1, {h2} H2, {'levels skipped' if skipped else 'levels in order'}, {page.words} words",
        [],
    )

    # faqs
    nodes = _ld_nodes(page.ld)
    faq_blocks = sum("FAQPage" in _types(n) for n in nodes)
    questions = sum(h.endswith("?") for _, h in page.headings)
    faq_heading = any(_FAQ.search(h) for _, h in page.headings)
    if faq_blocks:
        value, observed = 1.0, f"FAQPage schema ({faq_blocks})"
    elif questions >= 3 or faq_heading:
        value, observed = 0.6, f"{questions} question headings, no FAQPage schema"
    else:
        value, observed = 0.0, "no FAQ"
    if value < 1.0:
        add.append(
            _suggestion(
                "Add an FAQ section with FAQPage schema answering the "
                "cluster's prompts.",
                prompt_ids=[pid for pid, _ in t.queries],
                observation_ids=obs,
            )
        )
    if faq_blocks > 1:
        remove.append(
            _suggestion("Remove the duplicate FAQPage blocks; keep one.", observation_ids=obs)
        )
    values["faqs"] = (value, observed, [])

    # direct_answers
    h2_sections = [s for s in page.sections if s.level == 2]
    direct = 0
    for s in h2_sections:
        opener = bool(_OPENERS.match(s.text))
        short = 0 < _first_sentence_words(s.text) <= FIRST_SENTENCE_WORDS
        if short and not opener:
            direct += 1
            continue
        if opener:
            remove.append(
                _suggestion(
                    f"Remove the “in this article” opener under “{s.heading}”.",
                    observation_ids=obs,
                )
            )
        rewrite.append(
            _suggestion(
                f"Open “{s.heading}” with a direct answer of at most "
                f"{FIRST_SENTENCE_WORDS} words.",
                observation_ids=obs,
            )
        )
    value = round(direct / len(h2_sections), 4) if h2_sections else 0.0
    values["direct_answers"] = (
        value,
        f"{direct} of {len(h2_sections)} H2 sections open with a direct answer",
        [],
    )

    # author_attribution
    author = bool(
        page.author
        or page.byline
        or any("author" in n or "Person" in _types(n) for n in nodes)
    )
    if not author:
        add.append(
            _suggestion(
                "Add an author byline or Article schema with an author.",
                observation_ids=obs,
            )
        )
    values["author_attribution"] = (
        float(author),
        "author found" if author else "no author",
        [],
    )

    # tables
    if not page.tables:
        add.append(
            _suggestion(
                "Add a table (a comparison or a specification) with at "
                "least two rows.",
                observation_ids=obs,
            )
        )
    values["tables"] = (float(page.tables >= 1), f"{page.tables} tables", [])

    components = [
        {
            "code": code,
            "weight": w,
            "value": values[code][0],
            "points": round(w * values[code][0], 2),
            "observed": values[code][1],
            "evidence": values[code][2],
        }
        for code, w in WEIGHTS.items()
    ]
    return {
        "score": round(sum(c["points"] for c in components)),
        "weights_version": WEIGHTS_VERSION,
        "components": components,
        "suggestions": {
            "add": add,
            "remove": remove,
            "rewrite": rewrite,
            "evidence_to_add": evidence_to_add,
        },
    }
```

Note for the implementer: the `evidence_to_add.append(...)` call after the `continue` keeps the same arguments as before (text, `urls=[c["url"]]`, `observation_ids=list(c["observation_ids"])`), re-indented one level out. Run ruff format; the long f-strings above need wrapping to 80 columns.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_pages.py`
Expected: PASS. If `test_entity_coverage`'s `0.25 * 0.5` case or `test_evidence…` disagree by a rounding step, fix the code, not the expectation, unless the expectation misreads the spec.

- [ ] **Step 5: mypy, gate, commit**

Run the gate (mypy strict covers `pages.py`; annotate everything).

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/pages.py tests/unit/test_pages.py && git commit -m "feat(pages): AI Citability Score v1 with cited suggestions"
```

---

### Task 4: `recommend.py` — `optimize_page` rule and copy

**Files:**
- Modify: `packages/core/bsi_core/recommend.py` (`FEASIBILITY` line 53; copy after `cluster_copy` ~line 163; rule before `generate` ~line 650; call inside `generate`'s `if total:` block)
- Modify: `apps/api/bsi_api/routers/recommendations.py` — **no change** to `NO_IMPACT` (impact is measured); just confirm.
- Test: `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py`

**Interfaces:**
- Consumes: `m.PageAudit` (Task 1); `WEIGHTS_VERSION` from `pages` (Task 3).
- Produces: `PAGE_SCORE_THRESHOLD = 70`; `page_copy(brand: str, url: str, topic: str, n_prompts: int, score: int, suggestions: dict[str, list[dict[str, Any]]]) -> tuple[str, str]`; `_pages(s, brand_id, brand, total) -> list[Candidate]`.

- [ ] **Step 1: Failing copy tests**

In `tests/unit/test_recommend_copy.py`, import `page_copy` and add:

```python
PAGE_SUGGESTIONS = {
    "add": [{"text": "Add a section that answers “best school shoes” directly.", "urls": [], "prompt_ids": ["p"], "observation_ids": []}],
    "remove": [],
    "rewrite": [{"text": "Name Nike in the title or H1.", "urls": [], "prompt_ids": [], "observation_ids": ["o"]}],
    "evidence_to_add": [{"text": "Cite https://forbes.com/x: 3 answers in this cluster draw on it.", "urls": ["https://forbes.com/x"], "prompt_ids": [], "observation_ids": ["o"]}],
}
CASES += [
    page_copy("Nike", "https://nike.com/kids/school", "school shoes", 4, 62, PAGE_SUGGESTIONS),
    page_copy("Nike", "https://nike.com/", "school shoes", 1, 0, {"add": [], "remove": [], "rewrite": [], "evidence_to_add": []}),
]


def test_page_copy_names_the_page_score_and_first_steps():
    title, body = page_copy(
        "Nike", "https://nike.com/kids/school", "school shoes", 4, 62, PAGE_SUGGESTIONS
    )
    assert title == "Improve nike.com/kids/school for school shoes"
    assert "62/100" in body and "v1" in body
    assert "best school shoes" in body and "forbes.com" in body
    assert "4 prompts" in body and "Metric to watch:" in body
```

- [ ] **Step 2: Failing rule tests**

Append to `tests/integration/test_recommend.py`:

```python
def _page_audit(owner, org, bid, url, score, key="cluster:comparison:running shoes", obs=3, prompts=2):
    with owner() as s, s.begin():
        a = m.PageAudit(
            org_id=org.id,
            brand_id=bid,
            url=url,
            cluster_key=key,
            status=200 if score is not None else 0,
            error=None if score is not None else "ConnectError",
            weights_version="v1",
            score=score,
            components=[],
            suggestions={"add": [], "remove": [], "rewrite": [], "evidence_to_add": []},
            evidence={
                "prompt_ids": [f"p{i}" for i in range(prompts)],
                "observation_ids": [f"o{i}" for i in range(obs)],
                "cluster": {"intent": "comparison", "topic": "running shoes"},
            },
            fetches=1,
        )
        s.add(a)
        s.flush()
        return a.id


def _pages_found(world):
    with tenant_session(world.org.id) as s:
        return {
            c.subject_key: c
            for c in generate(s, world.brand)
            if c.type == "optimize_page"
        }


def test_a_low_page_score_is_an_optimize_page_candidate(owner, world):
    aid = _page_audit(owner, world.org, world.brand, "https://nike.com/run", 62)
    found = _pages_found(world)
    key = "page:cluster:comparison:running shoes:https://nike.com/run"
    assert set(found) == {key}
    c = found[key]
    # world: 4 + 4 + 2 + 3 + 3 = 16 done answers on active prompts.
    assert (c.reach, c.pressure, c.feasibility) == (
        pytest.approx(3 / 16),
        pytest.approx(0.38),
        0.6,
    )
    assert c.priority == round(3 / 16 * 0.38 * 0.6, 4)
    assert c.title == "Improve nike.com/run for running shoes"
    assert "Metric to watch:" in c.body
    assert c.evidence["page_audit_id"] == str(aid)
    assert c.evidence["prompt_ids"] == ["p0", "p1"]
    assert c.evidence["score"] == 62 and c.evidence["url"] == "https://nike.com/run"


def test_a_page_at_the_threshold_or_a_failed_fetch_is_not_raised(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/a", 70)
    _page_audit(owner, world.org, world.brand, "https://nike.com/b", None)
    assert _pages_found(world) == {}


def test_only_the_latest_audit_per_url_counts(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 40)
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 80)
    assert _pages_found(world) == {}
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 50)
    assert list(_pages_found(world)) == [
        "page:cluster:comparison:running shoes:https://nike.com/run"
    ]


def test_rescoring_above_the_threshold_drops_the_open_rec(owner, world):
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 40)
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    _page_audit(owner, world.org, world.brand, "https://nike.com/run", 90)
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        left = s.scalars(
            select(m.Recommendation).where(m.Recommendation.type == "optimize_page")
        ).all()
    assert left == []


def test_pages_rule_is_one_statement(owner, world):
    from sqlalchemy import event
    from bsi_core.recommend import _pages

    for i in range(3):
        _page_audit(owner, world.org, world.brand, f"https://nike.com/{i}", 30)
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(world.org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            _pages(s, world.brand, "Nike", 16)
        finally:
            event.remove(bind, "before_cursor_execute", count)
    assert len(seen) == 1
```

Check the `world` fixture's real done-answer total before trusting `16`: run `uv run pytest -q tests/integration/test_recommend.py -k content` and read the existing assertion on `reach` (the denominator there is the total). Use that number.

- [ ] **Step 3: Run to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py tests/integration/test_recommend.py -k "page"`
Expected: FAIL — `ImportError: cannot import name 'page_copy'`.

- [ ] **Step 4: Implement**

In `recommend.py`:

```python
from urllib.parse import urlsplit

from .pages import WEIGHTS_VERSION
```

`FEASIBILITY` gains, after `"fix_entity": 0.7,`:

```python
    # Editing a page that exists is less work than writing one.
    "optimize_page": 0.6,
```

After `CONTENT_REASONS`:

```python
# Below this AI Citability Score a scored page is worth a task.
PAGE_SCORE_THRESHOLD = 70
```

After `cluster_copy`:

```python
def page_copy(
    brand: str,
    url: str,
    topic: str,
    n_prompts: int,
    score: int,
    suggestions: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    u = urlsplit(url)
    where = f"{u.hostname}{u.path if u.path != '/' else ''}"
    steps = [
        s["text"]
        for key in ("add", "rewrite", "evidence_to_add")
        for s in suggestions.get(key, [])
    ][:3]
    first = f" First steps: {' '.join(steps)}" if steps else ""
    return (
        f"Improve {where} for {topic}",
        f"{url} scores {score}/100 on the AI Citability Score "
        f"({WEIGHTS_VERSION}) against the {topic} cluster.{first} "
        f"Metric to watch: {brand}'s mention rate on the cluster's "
        f"{n_prompts} prompts.",
    )
```

Before `generate`:

```python
def _pages(
    s: Session, brand_id: uuid.UUID, brand: str, total: int
) -> list[Candidate]:
    """One candidate per (cluster, url) whose latest scored audit is below
    PAGE_SCORE_THRESHOLD. Failed fetches (score NULL) never count; the
    Pages tab shows them. Reach and evidence come from the audit row,
    captured when it was scored: no cluster query here."""
    rows = s.execute(
        text(
            "SELECT DISTINCT ON (a.cluster_key, a.url) a.id, a.url, "
            "a.cluster_key, a.score, a.suggestions, a.evidence "
            "FROM page_audit a "
            "WHERE a.brand_id = :brand AND a.score IS NOT NULL "
            "ORDER BY a.cluster_key, a.url, a.created_at DESC, a.id DESC"
        ),
        {"brand": brand_id},
    ).all()
    out = []
    for r in rows:
        if r.score >= PAGE_SCORE_THRESHOLD:
            continue
        ev = r.evidence or {}
        prompt_ids = list(ev.get("prompt_ids", []))
        observation_ids = list(ev.get("observation_ids", []))
        topic = (ev.get("cluster") or {}).get("topic") or r.cluster_key
        title, body = page_copy(
            brand, r.url, topic, len(prompt_ids), r.score, r.suggestions or {}
        )
        out.append(
            Candidate(
                "optimize_page",
                f"page:{r.cluster_key}:{r.url}",
                title,
                body,
                {
                    "page_audit_id": str(r.id),
                    "url": r.url,
                    "cluster_key": r.cluster_key,
                    "score": r.score,
                    "prompt_ids": prompt_ids,
                    "observation_ids": observation_ids,
                    "cluster": ev.get("cluster"),
                },
                len(observation_ids) / total,
                (100 - r.score) / 100,
            )
        )
    return out
```

In `generate`, add `*_pages(s, brand_id, brand, total),` after `*_content_clusters(...)`.

- [ ] **Step 5: Run to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py tests/integration/test_recommend.py tests/integration/test_gaps.py`
Expected: PASS (existing cluster/gap tests unaffected: no `page_audit` rows there).

- [ ] **Step 6: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/recommend.py tests/unit/test_recommend_copy.py tests/integration/test_recommend.py && git commit -m "feat(recommend): optimize_page rule from the latest page audits"
```

---

### Task 5: Worker — `optimize_url` job

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (imports; `JOB_ESTIMATES` line 46; new functions after `run_crawl_audit` ~line 208; `runners` ~line 406)
- Test: `tests/integration/test_page_audit.py`

**Interfaces:**
- Consumes: `pages.parse`, `pages.Target`, `pages.score`, `pages.normalize_url`, `pages.WEIGHTS_VERSION` (Tasks 2–3); `m.PageAudit` (Task 1); `gaps.clusters(s, brand_id, Filters())`; `competitors._entities_and_hosts(s, brand_id) -> (entities, hosts: dict[uuid, list[str]])`; `competitors.owner_of`; `crawl.BROWSER_UA`, `crawl.http_fetch`, `crawl.Response`; `recommend.refresh`.
- Produces:
  - `PAGE_JOB_MICROS = 2_000`; `JOB_ESTIMATES["optimize_url"]`.
  - `cited_urls(s, brand_id, prompt_ids: list[uuid.UUID], brand_hosts, rival_hosts) -> list[dict]` (top 10 non-owned cited URLs: `{url, domain, owner, answers, observation_ids}`).
  - `audit_page(org_id, brand_id, params: dict, embedder, fetch=http_fetch) -> dict[str, Any]` — the row's columns, nothing written. Raises `ValueError("unknown cluster")` / `ValueError` from `normalize_url`.
  - `run_page_audit(org_id, brand_id, job_id, params, embedder, fetch=http_fetch) -> None` — `audit_page` + write + `refresh`.

- [ ] **Step 1: Failing tests**

`tests/integration/test_page_audit.py`:

```python
"""The optimize_url job: what it reads, fetches, embeds and stores."""

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.crawl import Response
from bsi_core.db import tenant_session
from bsi_core.pages import WEIGHTS_VERSION
from sqlalchemy import select, text, update

from tests.integration.test_gaps import scene  # noqa: F401
from tests.integration.test_worker import FakeAdapter, _job, _load_job
from tests.unit.test_pages import bow

KEY = "cluster:comparison:running shoes"
URL = "https://nike.com/run"
PAGE = """<html><head><title>Nike vs Adidas running shoes</title></head>
<body><h1>Nike vs Adidas: running shoes compared</h1>
<h2>Which is the best running shoe brand?</h2><p>Nike, for most runners.</p>
<h2>Nike vs Adidas</h2><p>Nike is lighter; Adidas is softer.</p>
<table><tr><th>Shoe</th></tr><tr><td>Pegasus</td></tr></table>
<a href="https://forbes.com/x">Forbes</a></body></html>"""


def _embedder(texts):
    return [bow(t) for t in texts], 55


def _fetch(pages=None):
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        return (pages or {}).get(url, Response(200, PAGE))

    fetch.calls = calls
    return fetch


def _embed_prompts(owner, ids):
    with owner() as s, s.begin():
        for pid, txt in [(ids.vs, "nike vs adidas"), (ids.best, "best running shoe brand")]:
            s.execute(update(m.Prompt).where(m.Prompt.id == pid).values(embedding=bow(txt)))


def _run(owner, scene, params, fetch=None, embedder=_embedder):  # noqa: F811
    jid = _job(owner, scene.org, scene.brand, "optimize_url", "queued", params=params)
    worker.process_job(FakeAdapter(), None, embedder, fetch=fetch or _fetch())
    with owner() as s:
        rows = s.scalars(select(m.PageAudit).order_by(m.PageAudit.created_at)).all()
        return _load_job(owner, jid), rows


def test_job_stores_a_scored_row_and_refreshes_recs(owner, scene):  # noqa: F811
    _embed_prompts(owner, scene)
    fetch = _fetch()
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": KEY}, fetch)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 55)
    assert fetch.calls == [(URL, worker.BROWSER_UA)]
    [a] = rows
    assert (a.url, a.cluster_key, a.status, a.error, a.fetches) == (URL, KEY, 200, None, 1)
    assert a.weights_version == WEIGHTS_VERSION and 0 <= a.score <= 100
    assert [c["code"] for c in a.components][:2] == ["topic_coverage", "evidence"]
    assert set(a.evidence["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(a.evidence["observation_ids"]) == 6
    assert a.evidence["cluster"] == {"intent": "comparison", "topic": "running shoes"}
    # forbes.com is linked; shop.adidas.co.in (rival) is cited but not linked
    ev = a.suggestions["evidence_to_add"]
    assert [s["urls"] for s in ev] == [["https://shop.adidas.co.in/y"]]
    with owner() as s:
        recs = s.scalars(select(m.Recommendation).where(m.Recommendation.type == "optimize_page")).all()
    assert [r.subject_key for r in recs] == ([f"page:{KEY}:{URL}"] if a.score < 70 else [])


def test_unknown_cluster_fails_the_job_and_stores_nothing(owner, scene):  # noqa: F811
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": "cluster:x:y"})
    assert job.status == "failed" and "unknown cluster" in job.error
    assert rows == []


def test_bad_url_fails_the_job(owner, scene):  # noqa: F811
    job, rows = _run(owner, scene, {"url": "ftp://x", "cluster_key": KEY})
    assert job.status == "failed" and rows == []


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (Response(0, "", "ConnectError('down')"), "ConnectError"),
        (Response(404, "<h1>x</h1>"), "HTTP 404"),
        (Response(200, "<html><body><p>no headings</p></body></html>"), "no headings"),
    ],
)
def test_a_failed_fetch_is_a_stored_finding(owner, scene, response, error):  # noqa: F811
    _embed_prompts(owner, scene)
    calls = []
    job, rows = _run(
        owner, scene, {"url": URL, "cluster_key": KEY},
        _fetch({URL: response}), lambda texts: (calls.append(texts), ([], 0))[1],
    )
    assert job.status == "done"
    [a] = rows
    assert a.score is None and error in a.error and a.status == response.status
    assert calls == []  # nothing embedded


def test_budget_gate_refuses_when_the_estimate_does_not_fit(owner, scene):  # noqa: F811
    with owner() as s, s.begin():
        s.execute(update(m.Organization).where(m.Organization.id == scene.org.id).values(daily_budget_usd=0))
    job, rows = _run(owner, scene, {"url": URL, "cluster_key": KEY})
    assert (job.status, job.error) == ("failed", "budget") and rows == []


def test_no_transaction_is_open_while_fetching_or_embedding(owner, scene):  # noqa: F811
    _embed_prompts(owner, scene)
    seen = []

    def idle():
        with owner() as s:
            return s.scalar(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE state = 'idle in transaction' AND pid <> pg_backend_pid()"
            ))

    def fetch(url, ua):
        seen.append(idle())
        return Response(200, PAGE)

    def embedder(texts):
        seen.append(idle())
        return [bow(t) for t in texts], 1

    _run(owner, scene, {"url": URL, "cluster_key": KEY}, fetch, embedder)
    assert len(seen) == 2 and set(seen) == {0}


def test_cited_urls_are_top_non_owned_by_answers(owner, scene):  # noqa: F811
    with tenant_session(scene.org.id) as s:
        rows = worker.cited_urls(s, scene.brand, [scene.vs, scene.best], ["nike.com"], ["adidas.co.in"])
    # scene: forbes.com/x in 4 absent answers, shop.adidas.co.in/y in 2,
    # nike.com/run is owned -> excluded.
    assert [(r["url"], r["owner"], r["answers"]) for r in rows] == [
        ("https://forbes.com/x", "third_party", 4),
        ("https://shop.adidas.co.in/y", "rival", 2),
    ]
    assert len(rows[0]["observation_ids"]) == 4
```

Check `daily_budget_usd` is the right knob for `budget_fits` by reading `scheduling.budget_fits` first; if the gate reads a settings value instead, patch that (the `label_prompts` budget test in `test_gaps.py`/`test_worker.py` shows the pattern — copy it).

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_page_audit.py`
Expected: FAIL — `unknown kind` job failures / `AttributeError: cited_urls`.

- [ ] **Step 3: Implement**

In `worker.py` add imports:

```python
import json
from typing import Any

from bsi_core.competitors import _entities_and_hosts, owner_of
from bsi_core.crawl import BROWSER_UA
from bsi_core.gaps import clusters
from bsi_core.metrics import Filters
from bsi_core.pages import WEIGHTS_VERSION, Target, normalize_url, parse, score
from sqlalchemy import Text, cast, select, text
```

`JOB_ESTIMATES` gains `"optimize_url": PAGE_JOB_MICROS,` with, above it:

```python
# 60 sections x ~250 tokens of gemini-embedding-001 at $0.15/M, rounded up.
PAGE_JOB_MICROS = 2_000
CITED_URLS_CAP = 10
```

After `run_crawl_audit`:

```python
def cited_urls(
    s: Session,
    brand_id: uuid.UUID,
    prompt_ids: list[uuid.UUID],
    brand_hosts: list[str],
    rival_hosts: list[str],
) -> list[dict[str, Any]]:
    """The cluster's most-cited pages that the brand does not own: the
    evidence a page can add. Answers counted per URL; rivals' pages
    stay in, marked, because they are the competitor pages that win."""
    rows = s.execute(
        text(
            "SELECT c.url, c.domain, count(DISTINCT o.id) AS answers, "
            "array_agg(DISTINCT o.id::text) AS obs "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND o.prompt_id = ANY(:ids) AND NOT c.is_brand_owned "
            "GROUP BY 1, 2 ORDER BY 3 DESC, 1"
        ),
        {"brand": brand_id, "ids": prompt_ids},
    ).all()
    out = []
    for r in rows:
        owner = owner_of(r.domain, brand_hosts, rival_hosts)
        if owner == "brand":
            continue
        out.append(
            {
                "url": r.url,
                "domain": r.domain,
                "owner": owner,
                "answers": int(r.answers),
                "observation_ids": sorted(r.obs),
            }
        )
        if len(out) == CITED_URLS_CAP:
            break
    return out


def audit_page(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    params: dict[str, Any],
    embedder: Any,
    fetch: Fetch = http_fetch,
) -> dict[str, Any]:
    """Read the cluster, fetch the page, embed its sections, score. Returns
    the page_audit columns; writes nothing. The read session is closed
    before the fetch and the embed."""
    url = normalize_url(str(params.get("url", "")))
    key = str(params.get("cluster_key", ""))
    with tenant_session(org_id) as s:
        brand = s.get_one(m.Brand, brand_id)
        name, aliases = brand.name, list(brand.aliases)
        _, hosts = _entities_and_hosts(s, brand_id)
        brand_hosts = hosts[brand_id]
        rival_hosts = [h for e, hs in hosts.items() if e != brand_id for h in hs]
        cluster = next(
            (c for c in clusters(s, brand_id, Filters()) if c["key"] == key),
            None,
        )
        if cluster is None:
            raise ValueError(f"unknown cluster {key!r}")
        pids = [p["prompt_id"] for p in cluster["prompts"]]
        # The vector as text, parsed here: the ORM never loads it.
        vectors = {
            pid: json.loads(v) if v else None
            for pid, v in s.execute(
                select(m.Prompt.id, cast(m.Prompt.embedding, Text)).where(
                    m.Prompt.id.in_(pids)
                )
            ).all()
        }
        cited = cited_urls(s, brand_id, pids, brand_hosts, rival_hosts)
    page_host = urlsplit(url).hostname or ""
    target = Target(
        intent=cluster["intent"],
        topic=cluster["topic"],
        queries=[(str(p["prompt_id"]), p["text"]) for p in cluster["prompts"]],
        rivals=[r["name"] for r in cluster["rivals"]],
        brand=name,
        aliases=aliases,
        brand_hosts=[*brand_hosts, page_host],
        rival_hosts=rival_hosts,
        cited=cited,
        observation_ids=[str(o) for o in cluster["absent_obs"]],
    )
    row: dict[str, Any] = {
        "url": url,
        "cluster_key": key,
        "status": 0,
        "error": None,
        "weights_version": WEIGHTS_VERSION,
        "score": None,
        "components": [],
        # Every key present even when unscored: the API schema and the
        # generated TS type treat the four lists as required.
        "suggestions": {
            "add": [],
            "remove": [],
            "rewrite": [],
            "evidence_to_add": [],
        },
        "evidence": {
            "prompt_ids": [str(p) for p in pids],
            "observation_ids": target.observation_ids,
            "cluster": {"intent": cluster["intent"], "topic": cluster["topic"]},
        },
        "fetches": 1,
    }
    resp = fetch(url, BROWSER_UA)
    row["status"] = resp.status
    if resp.error or not resp.ok:
        row["error"] = resp.error or f"HTTP {resp.status}"
        return row
    page = parse(resp.body)
    if not page.sections:
        row["error"] = "no headings found (is the page rendered by JavaScript?)"
        return row
    section_vectors, _ = embedder([sec.embed_text() for sec in page.sections])
    result = score(
        page, target, [vectors.get(p) for p in pids], section_vectors
    )
    row.update(
        score=result["score"],
        components=result["components"],
        suggestions=result["suggestions"],
    )
    return row


def run_page_audit(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    params: dict[str, Any],
    embedder: Any,
    fetch: Fetch = http_fetch,
) -> None:
    row = audit_page(org_id, brand_id, params, embedder, fetch)
    with tenant_session(org_id) as s:
        s.add(m.PageAudit(org_id=org_id, brand_id=brand_id, job_id=job_id, **row))
        s.flush()
        refresh(s, org_id, brand_id)
```

`urlsplit` comes from `urllib.parse`. In `runners`, add:

```python
        "optimize_url": lambda: run_page_audit(
            org_id, brand_id, job_id, params, meter.embed, fetch
        ),
```

Note: `meter.embed` returns `(vectors, cost)` and accumulates cost — check `_Meter.embed`'s return shape and adapt `section_vectors, _ = embedder(...)` accordingly. `_entities_and_hosts` returns `hosts` keyed by entity id including the brand — confirm by reading `competitors.py:44-75`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_page_audit.py tests/integration/test_crawl_audit.py tests/integration/test_worker.py`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_page_audit.py && git commit -m "feat(worker): optimize_url job scores a page against a gap cluster"
```

---

### Task 6: API — `/brands/{id}/pages`

**Files:**
- Create: `apps/api/bsi_api/routers/pages.py`
- Modify: `apps/api/bsi_api/schemas.py` (after `SiteAuditOut`), `apps/api/bsi_api/routers/runs.py` (`queue_suggestion`, line 32), `apps/api/bsi_api/main.py`
- Test: `tests/integration/test_api_pages.py`, `tests/integration/test_isolation.py`

**Interfaces:**
- Consumes: `m.PageAudit`; `gaps.clusters`; `pages.normalize_url`; `enqueue_job(s, org_id, brand_id, kind, params, slot=None)`; `Problem(status, title, detail)`; `child_or_404`.
- Produces: `POST /v1/brands/{b}/pages/optimize` (202 `QueuedOut`), `GET /v1/brands/{b}/pages[?cluster_key=]` (`list[PageAuditOut]`), `GET /v1/brands/{b}/pages/{id}` (`PageAuditOut`); schemas `PageOptimizeIn`, `ComponentOut`, `SuggestionOut`, `SuggestionsOut`, `PageAuditOut`.

- [ ] **Step 1: Failing tests**

`tests/integration/test_api_pages.py`:

```python
from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_gaps import scene  # noqa: F401
from tests.integration.test_recommend import _page_audit

KEY = "cluster:comparison:running shoes"


def test_optimize_queues_one_job_per_request(client, owner, scene):  # noqa: F811
    body = {"url": "HTTPS://Nike.com/run#top", "cluster_key": KEY}
    r1 = client.post(f"/v1/brands/{scene.brand}/pages/optimize", json=body, headers=scene.org.headers)
    r2 = client.post(f"/v1/brands/{scene.brand}/pages/optimize", json=body, headers=scene.org.headers)
    assert r1.status_code == 202 and r2.status_code == 202, r1.text
    assert r1.json()["job_id"] != r2.json()["job_id"]
    with owner() as s:
        job = s.get(m.Job, r1.json()["job_id"])
    assert (job.kind, job.status) == ("optimize_url", "queued")
    assert job.params == {"url": "https://nike.com/run", "cluster_key": KEY}


def test_optimize_rejects_bad_urls_and_unknown_clusters(client, scene):  # noqa: F811
    base = f"/v1/brands/{scene.brand}/pages/optimize"
    for url in ["ftp://nike.com/x", "nike.com/x", "http://u:p@nike.com/"]:
        r = client.post(base, json={"url": url, "cluster_key": KEY}, headers=scene.org.headers)
        assert r.status_code == 422, url
    r = client.post(base, json={"url": "https://nike.com/", "cluster_key": "cluster:x:y"}, headers=scene.org.headers)
    assert r.status_code == 422 and "cluster" in r.json()["detail"].lower()


def test_optimize_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    with owner() as s, s.begin():
        s.execute(update(m.Brand).where(m.Brand.id == scene.brand).values(status="archived"))
    r = client.post(f"/v1/brands/{scene.brand}/pages/optimize", json={"url": "https://nike.com/", "cluster_key": KEY}, headers=scene.org.headers)
    assert r.status_code == 409


def test_list_is_latest_per_url_newest_first(client, owner, scene):  # noqa: F811
    _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 40)
    newer = _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 80)
    other = _page_audit(owner, scene.org, scene.brand, "https://nike.com/b", None, key="cluster:informational:sizing")
    r = client.get(f"/v1/brands/{scene.brand}/pages", headers=scene.org.headers)
    assert r.status_code == 200, r.text
    assert [a["id"] for a in r.json()] == [str(other), str(newer)]
    assert r.json()[0]["score"] is None and r.json()[0]["error"] == "ConnectError"
    filtered = client.get(f"/v1/brands/{scene.brand}/pages", params={"cluster_key": KEY}, headers=scene.org.headers)
    assert [a["id"] for a in filtered.json()] == [str(newer)]


def test_get_one(client, owner, scene):  # noqa: F811
    aid = _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 40)
    r = client.get(f"/v1/brands/{scene.brand}/pages/{aid}", headers=scene.org.headers)
    assert r.status_code == 200 and r.json()["url"] == "https://nike.com/a"
    assert r.json()["evidence"]["prompt_ids"] == ["p0", "p1"]
```

In `tests/integration/test_isolation.py`, add to the `other` fixture (after the task insert):

```python
        audit = m.PageAudit(
            org_id=b.id,
            brand_id=bid,
            url="https://secret.com/p",
            cluster_key="cluster:guide:Secret",
            status=200,
            weights_version="v1",
            score=1,
            error="Secret",
        )
        s.add(audit)
        s.flush()
        rid, tid, aid = rec.id, task.id, audit.id
```

return `"a": aid`, and add to `CASES`:

```python
    ("POST", "/v1/brands/{b}/pages/optimize", {"url": "https://x.com/", "cluster_key": "cluster:guide:Secret"}),
    ("GET", "/v1/brands/{b}/pages", None),
    ("GET", "/v1/brands/{b}/pages/{a}", None),
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_pages.py tests/integration/test_isolation.py -k "pages"`
Expected: FAIL with 404s (routes missing).

- [ ] **Step 3: Implement**

`schemas.py`, after `SiteAuditOut`:

```python
class PageOptimizeIn(BaseModel):
    url: str = Field(max_length=2048)
    cluster_key: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        from bsi_core.pages import normalize_url

        try:
            return normalize_url(v)
        except ValueError as e:
            raise ValueError(str(e)) from e


class ComponentOut(BaseModel):
    code: str
    weight: int
    value: float
    points: float
    observed: str
    evidence: list[str]


class SuggestionOut(BaseModel):
    text: str
    urls: list[str]
    prompt_ids: list[str]
    observation_ids: list[str]


class SuggestionsOut(BaseModel):
    # Defaults so a row inserted without suggestions (fixtures, the
    # server default '{}') still renders; the runner always writes all four.
    add: list[SuggestionOut] = []
    remove: list[SuggestionOut] = []
    rewrite: list[SuggestionOut] = []
    evidence_to_add: list[SuggestionOut] = []


class PageAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    job_id: uuid.UUID | None
    url: str
    cluster_key: str
    status: int
    error: str | None
    weights_version: str
    score: int | None
    components: list[ComponentOut]
    suggestions: SuggestionsOut
    evidence: dict[str, Any]
    fetches: int
```

`routers/runs.py`: give `queue_suggestion` a keyword `slot: datetime | None = None` and pass `slot=slot` to `enqueue_job`.

`routers/pages.py`:

```python
"""The URL optimizer (PRD F11): score a page against a gap cluster."""

import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core import models as m
from bsi_core.gaps import clusters
from bsi_core.metrics import Filters
from fastapi import APIRouter
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import PageAuditOut, PageOptimizeIn, QueuedOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/pages", tags=["pages"])


@router.post("/optimize", status_code=202, response_model=QueuedOut)
def optimize(
    brand_id: uuid.UUID, body: PageOptimizeIn, c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    if body.cluster_key not in {
        r["key"] for r in clusters(c.s, brand_id, Filters())
    }:
        raise Problem(
            422, "Unknown cluster", f"No cluster {body.cluster_key!r}."
        )
    # A full timestamp, not the hour: every request is its own job.
    return queue_suggestion(
        c,
        brand_id,
        "optimize_url",
        {"url": body.url, "cluster_key": body.cluster_key},
        slot=datetime.now(UTC),
    )


@router.get("", response_model=list[PageAuditOut])
def list_audits(
    brand_id: uuid.UUID, cluster_key: str | None = None, c: Ctx = TENANT
) -> list[m.PageAudit]:
    """The latest audit per (cluster, url), newest first; failed fetches
    included."""
    brand_or_404(c, brand_id)
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
    if cluster_key is not None:
        q = q.where(m.PageAudit.cluster_key == cluster_key)
    rows = list(c.s.scalars(q))
    rows.sort(key=lambda a: (a.created_at, a.id), reverse=True)
    return rows


@router.get("/{audit_id}", response_model=PageAuditOut)
def get_audit(
    brand_id: uuid.UUID, audit_id: uuid.UUID, c: Ctx = TENANT
) -> m.PageAudit:
    audit: m.PageAudit = child_or_404(c, m.PageAudit, brand_id, audit_id)
    return audit
```

Check how `Problem` renders 422 vs pydantic's 422 (`problems.py`) so `r.json()["detail"]` matches the test; adjust the test's key if the body uses `title`/`detail` differently. `main.py`: import `pages` and add `pages.router` to the tuple.

- [ ] **Step 4: Run to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_pages.py tests/integration/test_isolation.py tests/integration/test_api_gaps.py`
Expected: PASS.

- [ ] **Step 5: Regenerate the OpenAPI types, gate, commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen && cd .. && git add apps/web/openapi.json apps/web/src/lib/schema.d.ts` then the full gate (both halves).

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api tests/integration/test_api_pages.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(api): /brands/{id}/pages — queue a URL score, list and read audits"
```

---

### Task 7: Web — score form on Clusters, Pages tab

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/pages/page.tsx`
- Modify: `apps/web/src/app/(app)/b/[id]/clusters/actions.ts`, `clusters/page.tsx` (inside the `<details>` brief, after the Evidence paragraph), `layout.tsx` (add a Link after Site), `apps/web/src/lib/types.ts`, `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts`

**Interfaces:**
- Consumes: generated `S["PageAuditOut"]`, `S["QueuedOut"]` (Task 6); `api<T>(path, init)`; `note()` helper in `format.ts`.
- Produces: `optimizeUrl(form: FormData)` server action; `pageNote(status)`; `PageAudit` type.

- [ ] **Step 1: Failing vitest**

In `format.test.ts`, import `pageNote` and add:

```ts
test("pageNote says what the score button actually did", () => {
  const queued = "Queued; the worker scores it within a minute.";
  expect(pageNote("queued")).toBe(queued);
  expect(pageNote("running")).toBe(queued);
  expect(pageNote("done")).toBe("Already scored.");
  expect(pageNote("failed")).toBe("Queued again after a failed run.");
  expect(pageNote(undefined)).toBeNull();
  expect(pageNote("constructor")).toBeNull();
});
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run` — Expected: FAIL (`pageNote` not exported).

- [ ] **Step 2: Implement**

`format.ts`, next to `LABEL_NOTES`:

```ts
const PAGE_QUEUED = "Queued; the worker scores it within a minute.";
const PAGE_NOTES: Record<string, string> = {
  queued: PAGE_QUEUED,
  running: PAGE_QUEUED,
  done: "Already scored.",
  failed: "Queued again after a failed run.",
};

/** What "Score a URL" did, from the job status the API returned. */
export const pageNote = (status: Params[string]) => note(PAGE_NOTES, status);
```

`types.ts`: `export type PageAudit = S["PageAuditOut"];`

`clusters/actions.ts`, append:

```ts
export async function optimizeUrl(form: FormData) {
  const id = String(form.get("brand_id"));
  await api<Queued>(`/brands/${id}/pages/optimize`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      url: String(form.get("url")),
      cluster_key: String(form.get("cluster_key")),
    }),
  });
  redirect(`/b/${id}/pages?queued=queued`);
}
```

(Check how other POST-with-body actions in `apps/web/src/app/(app)` pass JSON — e.g. the competitors or recommendations actions — and copy that exact `api()` usage; `api` may already set the content type.)

`clusters/page.tsx`: import `optimizeUrl`; inside the `<details>` after the Evidence `<p>`:

```tsx
                      <form action={optimizeUrl} className="row">
                        <input type="hidden" name="brand_id" value={id} />
                        <input type="hidden" name="cluster_key" value={c.key} />
                        <input
                          type="url"
                          name="url"
                          required
                          placeholder="https://your-site.com/page"
                          style={{ minWidth: 280 }}
                        />
                        <button>Score a URL</button>
                      </form>
```

`layout.tsx`: `<Link href={`/b/${id}/pages`}>Pages</Link>` after Site.

`pages/page.tsx`:

```tsx
import Link from "next/link";
import { api } from "@/lib/api";
import { pageNote, type Params } from "@/lib/format";
import type { PageAudit } from "@/lib/types";

const isWeb = (u: string) => u.startsWith("https://") || u.startsWith("http://");
const LISTS: [keyof PageAudit["suggestions"], string][] = [
  ["add", "Add"],
  ["rewrite", "Rewrite"],
  ["remove", "Remove"],
  ["evidence_to_add", "Evidence to add"],
];

export default async function Pages({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  // Newest first, latest per (cluster, url): the API orders it.
  const audits = await api<PageAudit[]>(`/brands/${id}/pages`);
  return (
    <>
      {pageNote(sp.queued) && <p className="muted">{pageNote(sp.queued)}</p>}
      {audits.length === 0 && (
        <p className="muted">
          No pages scored yet. Open a gap on the{" "}
          <Link href={`/b/${id}/clusters`}>Clusters</Link> tab and score a
          URL against it.
        </p>
      )}
      {audits.map((a) => (
        <div className="card" key={a.id} style={{ marginTop: 12 }}>
          <div className="row">
            <strong>
              {isWeb(a.url) ? (
                <a href={a.url} rel="noreferrer">
                  {a.url}
                </a>
              ) : (
                a.url
              )}
            </strong>
            <span className="tag">{a.cluster_key.replace(/^cluster:/, "")}</span>
            <span className="muted">
              {a.created_at.slice(0, 16).replace("T", " ")} UTC
            </span>
          </div>
          {a.score == null ? (
            <p className="down">Not scored: {a.error ?? `HTTP ${a.status}`}</p>
          ) : (
            <>
              <p>
                <strong>{a.score} / 100</strong>{" "}
                <span className="muted">
                  AI Citability Score (weights {a.weights_version})
                </span>
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Points</th>
                    <th>Observed</th>
                  </tr>
                </thead>
                <tbody>
                  {a.components.map((c) => (
                    <tr key={c.code} className={c.value < 1 ? "low" : undefined}>
                      <td>{c.code.replace(/_/g, " ")}</td>
                      <td>
                        {c.points} / {c.weight}
                      </td>
                      <td className="muted">{c.observed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {LISTS.map(([key, label]) =>
                (a.suggestions[key] ?? []).length ? (
                  <div key={key}>
                    <strong>{label}</strong>
                    <ul>
                      {(a.suggestions[key] ?? []).map((s, i) => (
                        <li key={i}>
                          {s.text}{" "}
                          {s.urls.filter(isWeb).map((u) => (
                            <a key={u} href={u} rel="noreferrer" style={{ marginRight: 6 }}>
                              {u}
                            </a>
                          ))}
                          {s.observation_ids.slice(0, 5).map((o) => (
                            <Link key={o} href={`/o/${o}`} style={{ marginRight: 6 }}>
                              {o.slice(0, 8)}
                            </Link>
                          ))}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}
            </>
          )}
        </div>
      ))}
    </>
  );
}
```

- [ ] **Step 3: Gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate` — Expected: PASS (types, lint, vitest, build). Then the Python gate is unchanged.

- [ ] **Step 4: Smoke the pages**

With the API (`uv run uvicorn bsi_api.main:app --port 8000`) and web (`npm run dev`) running, and `.env` sourced:

```bash
curl -s -b "bsi_key=bsi_d4bffda8357293d18944a77797e4a98920431e91d97bfc577a81b2b3d69fc0b3" http://localhost:3000/b/34db213a-f484-4991-a969-c52cfa5e1c10/pages | grep -c "No pages scored yet"
```

Expected: `1` or more (the string appears in HTML and the RSC payload). Do **not** submit the form on dev (it would queue a job and, once processed, write recs).

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src && git commit -m "feat(web): score a URL from a gap cluster; Pages tab"
```

---

### Task 8: Read-only live-check script and docs

**Files:**
- Create: `scripts/score_page.py`, `docs/findings-slice11.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: `worker.audit_page(org_id, brand_id, params, embedder, fetch)` (Task 5); `suggest.embed`; `crawl.http_fetch`; `db.owner_engine()`.

- [ ] **Step 1: The script**

```python
"""Score one URL against one gap cluster, read-only: nothing is stored.

usage: set -a && source .env && set +a
       uv run python scripts/score_page.py <brand_id> <cluster_key> <url>
Spend: one embedding call (about $0.002)."""

import json
import sys
import uuid

from bsi_core import models as m
from bsi_core.crawl import http_fetch
from bsi_core.db import owner_engine
from bsi_core.suggest import embed
from bsi_workers.worker import audit_page
from sqlalchemy import select
from sqlalchemy.orm import Session

brand_id = uuid.UUID(sys.argv[1])
with Session(owner_engine()) as s:
    org_id = s.scalar(select(m.Brand.org_id).where(m.Brand.id == brand_id))
if org_id is None:
    sys.exit(f"no brand {brand_id}")
spent = []


def metered(texts: list[str]) -> tuple[list[list[float]], int]:
    vectors, micros = embed(texts)
    spent.append(micros)
    return vectors, micros


row = audit_page(
    org_id,
    brand_id,
    {"url": sys.argv[3], "cluster_key": sys.argv[2]},
    metered,
    http_fetch,
)
print(json.dumps(row, indent=2, default=str))
print(f"spend: {sum(spent)} micros", file=sys.stderr)
```

Confirm `owner_engine()` exists in `bsi_core/db.py` with that name (the handoff lists it); adapt if it takes arguments.

- [ ] **Step 2: Docs**

`docs/findings-slice11.md` skeleton (the live-check numbers are filled in by the session running the check, not the implementer):

```markdown
# Findings: slice 11 — URL optimizer and AI Citability Score

## 1. What was built
(one paragraph: pages.py, optimize_url job, page_audit, optimize_page rule, routes, tabs)

## 2. Live check
(brand, cluster, URL, score, components table, top suggestions, spend; run read-only via scripts/score_page.py)

## 3. Calibration notes
(COS_FLOOR / COS_SPAN / COS_COVERED against the real cosines seen)

## 4. Deferred
- Competitor pages are cited, not fetched.
- brand_urls are not scored automatically.
- No judge call; entity coverage is name matching.
- No per-engine score; no scheduled re-scoring.
- URLs are not restricted to declared domains (SSRF guard is the boundary).
- Threshold 70 and weights v1 are first guesses.
```

Add a line for slice 11 to `docs/README.md`'s per-slice index (follow the existing entries' format).

- [ ] **Step 3: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add scripts/score_page.py docs/findings-slice11.md docs/README.md && git commit -m "docs: slice 11 findings skeleton and read-only score script"
```

---

## After the tasks (main session, not a subagent)

1. Whole-branch review, fix wave, scoped re-review (subagent-driven-development).
2. Live check (≈ $0.002, approved): `set -a && source .env && set +a && uv run python scripts/score_page.py 34db213a-f484-4991-a969-c52cfa5e1c10 "cluster:recommendation:school shoes" <a real page URL the user names>`; fill findings §2–3; verify dev tables stay empty: `docker compose exec -T db psql -U bsi_owner -d bsi -tAc "select (select count(*) from page_audit), (select count(*) from recommendation), (select count(*) from task), (select count(*) from job where status='queued')"` → `0|0|0|0`.
3. `finishing-a-development-branch`: push, `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh pr create`, watch CI, read the run log (`gh run view <id> --log | grep -E " passed, |Compiled"`), merge only when the user says so, then update memory (spend, migration 0014, slice 11 merged).
