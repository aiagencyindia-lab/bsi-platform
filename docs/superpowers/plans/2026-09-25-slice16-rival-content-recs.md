# Slice 16 Rival Content Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new recommendation type, `respond_to_rival_content`, raised when a competitor's new pages (from the weekly site crawl) match a prompt cluster where the brand is behind.

**Architecture:** Pure functions in `bsi_core/rivals.py` turn a URL path and a cluster topic into stemmed word sets; a new rule in `bsi_core/recommend.py` reads the last 14 days of non-baseline rival pages in one SQL statement, matches them to the clusters `generate` already computes, and emits one candidate per cluster. A migration widens the type check; the worker refreshes recommendations after each crawl; the web page and reports learn the label.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pytest; Next.js 15, vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-slice16-rival-content-recs-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`; the shell's cwd resets after every command, so every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases; never touch the dev DB, the network or the worker loop. Tests use the shared `bsi_test` DB; run only the files named in the task; check `pgrep -fl pytest` first and never run two suites at once.
- ruff line length 80, target py313; `mypy --strict` over `packages/core/bsi_core`; only fixed SQL fragments are concatenated, every value is bound.
- Copy: no string produced by `rival_content_copy` may contain `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain`; every body ends with `Metric to watch: …`.
- Constants from the spec: `RIVAL_DAYS = 14`, `RIVAL_PAGES_SATURATION = 5`, `RIVAL_PAGES_CAP = 10`, `FEASIBILITY["respond_to_rival_content"] = 0.4`, subject key `rival:{cluster_key}`, `reach = cluster.n / total`, `pressure = min(matched / 5, 1.0)`.
- Matching: `_stem` drops one trailing `s` when `len(word) > 3`; a page matches when every stemmed topic word is in the stemmed slug words and the topic has ≥ 1 word.
- Trigger: cluster `gap` is true, or `spread` is not None and `spread < 0`; only active competitors; only `NOT baseline` pages with `first_seen_at` in the last 14 days.
- `METHODOLOGY_VERSION` in `reports.py` is not bumped. `NO_IMPACT` in the API is unchanged.
- `tenant_session` opens a transaction and commits on exit; never `with tenant_session(...) as s, s.begin():`.
- Commit trailer: the `Co-Authored-By` line from the latest session reminder (Opus 5.5 during execution).

---

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/rivals.py` | `_stem`, `slug_words`, `topic_words` |
| `packages/core/bsi_core/models.py` | `REC_TYPES` gains the type |
| `migrations/versions/0018_respond_to_rival_content.py` | widen `ck_recommendation_type` |
| `packages/core/bsi_core/recommend.py` | constants, `FEASIBILITY`, `rival_content_copy`, `_rival_pages`, `_rival_content`, `generate` passes clusters once |
| `apps/workers/bsi_workers/worker.py` | `run_rival_crawl` ends with `refresh` |
| `packages/core/bsi_core/reports.py` | `REC_LABEL`, `SEO_REC_TYPES`, `CONTENT_REC_TYPES` |
| `apps/web/src/lib/format.ts`, `app/(app)/b/[id]/recommendations/page.tsx` | label; `evidence.pages` links |
| `tests/unit/test_rivals.py`, `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py`, `tests/integration/test_rival_crawl.py`, `tests/integration/test_api_recommendations.py`, `apps/web/src/lib/format.test.ts` | tests |
| `docs/findings-slice16.md`, `docs/README.md`, the spec's Rulings, the plan's changes section | docs |

---

### Task 1: Slug and topic word matching

**Files:**
- Modify: `packages/core/bsi_core/rivals.py` (append near the top, after the constants)
- Test: `tests/unit/test_rivals.py` (append)

**Interfaces:**
- Produces: `_stem(word: str) -> str`, `slug_words(url: str) -> frozenset[str]`, `topic_words(topic: str) -> frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_rivals.py` (add `_stem, slug_words, topic_words` to the `bsi_core.rivals` import):

```python
def test_stem_drops_one_trailing_s_on_longer_words():
    assert [_stem(w) for w in ("sneakers", "shoes", "kids", "bus", "glass")] == [
        "sneaker",
        "shoe",
        "kid",
        "bus",
        "glas",
    ]


def test_slug_words_reads_the_path_only():
    assert slug_words("https://skechers.in/kids/Light-Up_Sneakers?x=1#f") == {
        "kid",
        "light",
        "up",
        "sneaker",
    }
    assert slug_words("https://r.com/kids%20shoes/") == {"kid", "shoe"}
    assert slug_words("https://r.com/") == frozenset()
    assert slug_words("https://r.com") == frozenset()
    assert slug_words("https://r.com/p/12345") == {"p", "12345"}


def test_topic_words_match_slugs_by_subset():
    kids_shoes = topic_words("kids shoes")
    assert kids_shoes == {"kid", "shoe"}
    assert kids_shoes <= slug_words("https://r.com/kids/school-shoes-boys")
    assert not kids_shoes <= slug_words("https://r.com/kids/socks")
    assert topic_words("light-up sneakers") == {"light", "up", "sneaker"}
    assert topic_words("") == frozenset()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py`
Expected: FAIL with `ImportError: cannot import name '_stem'`.

- [ ] **Step 3: Implement**

In `packages/core/bsi_core/rivals.py`, add `import re` and `from urllib.parse import unquote, urlsplit` to the imports if absent, then after `MAX_TYPE_CHARS`:

```python
_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    """Drop one trailing s on words longer than three characters, so
    sneakers/sneaker and kids/kid meet. ponytail: crude on purpose (glass
    -> glas on both sides, which still matches); a real stemmer is the
    upgrade path if topic words start missing slugs."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in _WORD.findall(text.casefold()))


def slug_words(url: str) -> frozenset[str]:
    """The stemmed words of a URL's path; query and fragment are ignored.
    A bare host gives the empty set."""
    return _words(unquote(urlsplit(url).path))


def topic_words(topic: str) -> frozenset[str]:
    """The stemmed words of a cluster topic (one to three words from the
    labeller). A page matches a topic when topic_words <= slug_words."""
    return _words(topic)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/rivals.py tests/unit/test_rivals.py && git commit -q -F - <<'EOF'
feat(rivals): slug and topic word matching

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Type, migration, feasibility and copy

**Files:**
- Modify: `packages/core/bsi_core/models.py` (`REC_TYPES`), `packages/core/bsi_core/recommend.py` (`FEASIBILITY`, new constants, `rival_content_copy`)
- Create: `migrations/versions/0018_respond_to_rival_content.py`
- Test: `tests/unit/test_recommend_copy.py` (append), `tests/integration/test_constraints.py` (unchanged; it asserts the DB constraint equals `m.REC_TYPES`)

**Interfaces:**
- Produces: `m.REC_TYPES` with `"respond_to_rival_content"` last; `recommend.RIVAL_DAYS = 14`, `RIVAL_PAGES_SATURATION = 5`, `RIVAL_PAGES_CAP = 10`; `FEASIBILITY["respond_to_rival_content"] = 0.4`; `rival_content_copy(brand: str, topic: str, intent: str, page_type: str, pages_by_rival: list[tuple[str, list[str]]], n: int, brand_rate: float | None, top_rival: tuple[str, float | None] | None, gap: bool) -> tuple[str, str]` where each `pages_by_rival` entry is `(competitor name, [urls newest first])`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_recommend_copy.py` (add `rival_content_copy` to the `bsi_core.recommend` import):

```python
RIVAL_ONE = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [("Adidas", ["https://adidas.co.in/running-shoes/ultraboost-24"])],
    8,
    0.25,
    ("Adidas", 0.625),
    False,
)
RIVAL_FOUR = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [
        (
            "Adidas",
            [
                "https://adidas.co.in/running-shoes/a",
                "https://adidas.co.in/running-shoes/b",
                "https://adidas.co.in/running-shoes/c",
                "https://adidas.co.in/running-shoes/d",
            ],
        )
    ],
    8,
    0.25,
    ("Adidas", 0.625),
    False,
)
RIVAL_MANY = rival_content_copy(
    "Nike",
    "kids shoes",
    "commercial",
    "category page",
    [
        ("Adidas", ["https://adidas.co.in/kids-shoes"]),
        ("Puma", ["https://puma.com/kids/shoes"]),
        ("Bata", ["https://bata.com/kids-shoes/"]),
        ("Crocs", ["https://crocs.in/kids-shoes"]),
    ],
    10,
    0.3,
    ("Adidas", 0.7),
    False,
)
RIVAL_GAP = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [("Adidas", ["https://adidas.co.in/running-shoes/"])],
    8,
    0.25,
    ("Adidas", 0.625),
    True,
)
CASES += [RIVAL_ONE, RIVAL_FOUR, RIVAL_MANY, RIVAL_GAP]


def test_rival_content_copy_names_pages_standing_and_response():
    title, body = RIVAL_ONE
    assert title == "Adidas published 1 new running shoes page"
    assert "Adidas published 1 new page: ultraboost-24." in body
    assert "Nike is named in 25% of 8 answers; Adidas in 62%." in body
    assert "Publish a comparison page on running shoes" in body
    assert body.endswith(
        "Metric to watch: Nike's mention rate on the running shoes cluster."
    )
    title, body = RIVAL_FOUR
    assert title == "Adidas published 4 new running shoes pages"
    assert "4 new pages: a, b, c." in body  # three named, count kept
    title, body = RIVAL_MANY
    assert title == "4 new kids shoes pages from Adidas, Puma and Bata"
    assert "Crocs published 1 new page: kids-shoes." in body
    assert "Publish a category page on kids shoes" in body
    _, body = RIVAL_GAP
    assert "This cluster is a content gap for Nike." in body
    assert "named in" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py`
Expected: FAIL with `ImportError: cannot import name 'rival_content_copy'`.

- [ ] **Step 3: Type, feasibility, constants, copy**

In `packages/core/bsi_core/models.py`, append `"respond_to_rival_content",` as the last entry of `REC_TYPES`.

In `packages/core/bsi_core/recommend.py`, in `FEASIBILITY` after `"create_content"`'s line add:

```python
    # Writing content, as create_content; the rival's move is the prompt.
    "respond_to_rival_content": 0.4,
```

After `PAGE_SCORE_THRESHOLD` add:

```python
# Rival pages count as new for this long after first_seen_at.
RIVAL_DAYS = 14
# Five or more new rival pages on a topic is a full-pressure signal.
RIVAL_PAGES_SATURATION = 5
RIVAL_PAGES_CAP = 10
```

After `cluster_copy` add:

```python
def _last_segment(url: str) -> str:
    u = urlsplit(url)
    segs = [p for p in u.path.split("/") if p]
    return segs[-1] if segs else (u.hostname or url)


def rival_content_copy(
    brand: str,
    topic: str,
    intent: str,
    page_type: str,
    pages_by_rival: list[tuple[str, list[str]]],
    n: int,
    brand_rate: float | None,
    top_rival: tuple[str, float | None] | None,
    gap: bool,
) -> tuple[str, str]:
    """A competitor published on a topic where the brand is behind."""
    k = sum(len(urls) for _, urls in pages_by_rival)
    rivals = [name for name, _ in pages_by_rival]
    if len(rivals) == 1:
        title = f"{rivals[0]} published {k} new {topic} page{'s' if k != 1 else ''}"
    else:
        title = f"{k} new {topic} pages from {names(rivals)}"
    moves = " ".join(
        f"{name} published {len(urls)} new page{'s' if len(urls) != 1 else ''}: "
        + ", ".join(_last_segment(u) for u in urls[:3])
        + "."
        for name, urls in pages_by_rival
    )
    if gap or brand_rate is None or top_rival is None:
        standing = f"This cluster is a content gap for {brand}."
    else:
        name, rate_ = top_rival
        theirs = f"{rate_:.0%}" if rate_ is not None else "—"
        standing = (
            f"{brand} is named in {brand_rate:.0%} of {n} answers; "
            f"{name} in {theirs}."
        )
    # ponytail: first-letter rule; every PAGE_TYPES value reads right by it.
    art = "an" if page_type[0] in "aeiou" else "a"
    return (
        title,
        f"{moves} {standing} Publish {art} {page_type} on {topic} that "
        "answers these prompts directly, so engines have something of the "
        "brand's own to retrieve alongside the rival's. "
        f"Metric to watch: {brand}'s mention rate on the {topic} cluster.",
    )
```

`urlsplit` and `names` are already imported/defined in `recommend.py`.

Create `migrations/versions/0018_respond_to_rival_content.py`:

```python
"""recommendation type respond_to_rival_content"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

OLD_TYPES = ", ".join(
    f"'{t}'"
    for t in (
        "pursue_citation_source",
        "create_content",
        "add_competitor",
        "sample_more",
        "fix_crawlability",
        "fix_entity",
        "optimize_page",
    )
)
NEW_TYPES = OLD_TYPES + ", 'respond_to_rival_content'"


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    # Tasks keep their rows: recommendation_id is nullable and the task is
    # the operator's record of work accepted.
    op.execute(
        "UPDATE task SET recommendation_id = NULL WHERE recommendation_id IN "
        "(SELECT id FROM recommendation "
        " WHERE type = 'respond_to_rival_content')"
    )
    op.execute(
        "DELETE FROM recommendation WHERE type = 'respond_to_rival_content'"
    )
    _rec_type_check(OLD_TYPES)
```

Check `task.recommendation_id` is nullable with `grep -n "recommendation_id" packages/core/bsi_core/models.py` (it is `uuid.UUID | None`); if the FK has `ondelete` semantics that already null it, keep the explicit UPDATE anyway for clarity.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py tests/integration/test_constraints.py`
Expected: PASS (the constraints test migrates the test DB to 0018 and compares the CHECK to `m.REC_TYPES`).

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/models.py packages/core/bsi_core/recommend.py migrations/versions/0018_respond_to_rival_content.py tests/unit/test_recommend_copy.py && git commit -q -F - <<'EOF'
feat(recommend): respond_to_rival_content type, migration and copy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: The rule

**Files:**
- Modify: `packages/core/bsi_core/recommend.py` (`_rival_pages`, `_rival_content`, `generate`, `_content_clusters` signature)
- Test: `tests/integration/test_recommend.py` (append)

**Interfaces:**
- Consumes: Task 1's `slug_words`, `topic_words`; Task 2's constants and copy; `gaps.clusters` rows (`key, intent, topic, n, gap, spread, brand (rate dict), top_rival ({name, competitor_id, value, …} or None), prompts [{prompt_id,…}], absent_obs`).
- Produces: `_rival_pages(s, brand_id) -> Sequence[Row]` (columns `competitor_id, name, url, first_seen_at`); `_rival_content(s, brand_id, brand, total, rows) -> list[Candidate]`; `_content_clusters(s, brand_id, brand, total, rows)` now takes the cluster rows; `generate` computes `rows = clusters(s, brand_id, Filters())` once when `total` and passes it to both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_recommend.py`. Add imports: `from bsi_core.recommend import _rival_pages, generate, refresh` (extend the existing import line), `from tests.integration.test_gaps import scene  # noqa: F401`, `from tests.integration.test_rival_crawl import _page`.

```python
KEY = "rival:cluster:comparison:running shoes"


def _rival_found(scene):
    with tenant_session(scene.org.id) as s:
        return {
            c.subject_key: c
            for c in generate(s, scene.brand)
            if c.type == "respond_to_rival_content"
        }


def test_rival_rule_fires_on_new_matching_pages_where_brand_is_behind(
    owner, scene
):
    org, bid, A, B = scene.org, scene.brand, scene.adidas, scene.bata
    # The gap cluster (comparison, running shoes) is behind Adidas.
    _page(owner, org, bid, A, "https://adidas.co.in/running-shoes/new", 2)
    _page(owner, org, bid, A, "https://adidas.co.in/running-shoes/old", 2, baseline=True)
    _page(owner, org, bid, A, "https://adidas.co.in/running-shoes/stale", 20)
    _page(owner, org, bid, A, "https://adidas.co.in/socks", 2)
    _page(owner, org, bid, B, "https://bata.com/running-shoes", 2, domain="bata.com")
    # The (recommendation, kids) cluster has the brand ahead: 3/4 vs 2/4.
    _page(owner, org, bid, A, "https://adidas.co.in/kids/shoes", 2)
    found = _rival_found(scene)
    assert set(found) == {KEY}
    c = found[KEY]
    ev = c.evidence
    assert [p["url"] for p in ev["pages"]] == [
        "https://adidas.co.in/running-shoes/new"
    ]
    assert ev["pages"][0]["name"] == "Adidas"
    assert ev["pages"][0]["competitor_id"] == str(A)
    assert ev["pages_total"] == 1
    assert ev["cluster"] == {"intent": "comparison", "topic": "running shoes"}
    assert ev["cluster_key"] == "cluster:comparison:running shoes"
    assert ev["gap"] is True and ev["n"] == 8 and ev["spread"] < 0
    assert set(ev["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(ev["observation_ids"]) == 6
    assert (c.reach, c.pressure, c.feasibility) == (8 / 19, 0.2, 0.4)
    assert c.title == "Adidas published 1 new running shoes page"
    assert "This cluster is a content gap for Nike." in c.body


def test_rival_rule_behind_but_not_a_gap_uses_the_standing_wording(
    owner, scene
):
    A = scene.adidas
    # Brand present 2/4 (no absence reasons -> not a gap), Adidas 3/4.
    scene.add(
        "trail running shoes",
        "commercial",
        "trail shoes",
        [
            (True, [A], None, []),
            (True, [A], None, []),
            (False, [A], None, []),
            (False, [], None, []),
        ],
    )
    _page(owner, scene.org, scene.brand, A, "https://adidas.co.in/trail-shoes", 1)
    found = _rival_found(scene)
    c = found["rival:cluster:commercial:trail shoes"]
    assert c.evidence["gap"] is False and c.evidence["spread"] == -0.25
    assert "Nike is named in 50% of 4 answers; Adidas in 75%." in c.body
    assert "Publish a category page on trail shoes" in c.body


def test_rival_rule_pressure_saturates_and_evidence_is_capped(owner, scene):
    A = scene.adidas
    for i in range(2):
        _page(owner, scene.org, scene.brand, A, f"https://adidas.co.in/running-shoes/{i}", 1)
    assert _rival_found(scene)[KEY].pressure == 0.4
    for i in range(2, 12):
        _page(owner, scene.org, scene.brand, A, f"https://adidas.co.in/running-shoes/{i}", 1)
    c = _rival_found(scene)[KEY]
    assert c.pressure == 1.0
    assert len(c.evidence["pages"]) == 10 and c.evidence["pages_total"] == 12


def test_rival_rule_refresh_upserts_deletes_and_keeps_decisions(owner, scene):
    org, bid, A = scene.org, scene.brand, scene.adidas
    _page(owner, org, bid, A, "https://adidas.co.in/running-shoes/new", 2)

    def rows():
        with owner() as s:
            return s.scalars(
                select(m.Recommendation).where(
                    m.Recommendation.type == "respond_to_rival_content"
                )
            ).all()

    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
        refresh(s, org.id, bid)
    assert [r.subject_key for r in rows()] == [KEY]
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.type == "respond_to_rival_content")
            .values(status="accepted")
        )
        s.execute(delete(m.RivalPage))
    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
    assert [r.status for r in rows()] == ["accepted"]  # decided rows stay
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.type == "respond_to_rival_content")
            .values(status="open")
        )
    with tenant_session(org.id) as s:
        refresh(s, org.id, bid)
    assert rows() == []  # open rows without evidence are removed


def test_rival_pages_is_one_statement(owner, scene):
    from sqlalchemy import event

    _page(owner, scene.org, scene.brand, scene.adidas, "https://adidas.co.in/a", 1)
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(scene.org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            assert len(_rival_pages(s, scene.brand)) == 1
        finally:
            event.remove(bind, "before_cursor_execute", count)
    assert len(seen) == 1
```

Add `delete` to the `sqlalchemy` import line. `test_each_rule_fires_exactly_where_it_should` stays as is: the `world` fixture has no rival pages and no labelled prompts, so the new rule is silent there (state that in a one-line comment next to its expected set).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_recommend.py -k rival`
Expected: FAIL with `ImportError: cannot import name '_rival_pages'`.

- [ ] **Step 3: Implement the rule**

In `recommend.py`, add `from .rivals import slug_words, topic_words` to the imports (check for an import cycle: `rivals.py` must not import `recommend`; it does not today). Then, after `_content_clusters`:

```python
def _rival_pages(s: Session, brand_id: uuid.UUID) -> Sequence[Row[Any]]:
    """New (non-baseline) pages of active competitors seen in the last
    RIVAL_DAYS, newest first. One statement; values bound."""
    return s.execute(
        text(
            "SELECT p.competitor_id, c.name, p.url, p.first_seen_at "
            "FROM rival_page p JOIN competitor c ON c.id = p.competitor_id "
            "WHERE p.brand_id = :b AND c.status = 'active' "
            "  AND NOT p.baseline "
            "  AND p.first_seen_at >= now() - make_interval(days => :days) "
            "ORDER BY p.first_seen_at DESC, p.url"
        ),
        {"b": brand_id, "days": RIVAL_DAYS},
    ).all()


def _rival_content(
    s: Session,
    brand_id: uuid.UUID,
    brand: str,
    total: int,
    rows: list[dict[str, Any]],
) -> list[Candidate]:
    """One candidate per cluster where the brand is behind and a rival
    published matching pages in the last RIVAL_DAYS (spec slice 16)."""
    pages = [(r, slug_words(r.url)) for r in _rival_pages(s, brand_id)]
    if not pages:
        return []
    out = []
    for c in rows:
        behind = c["gap"] or (c["spread"] is not None and c["spread"] < 0)
        words = topic_words(c["topic"])
        if not behind or not words:
            continue
        matched = [r for r, slug in pages if words <= slug]
        if not matched:
            continue
        by_rival: dict[str, list[str]] = {}
        for r in matched:
            by_rival.setdefault(r.name, []).append(r.url)
        top = c["top_rival"]
        title, body = rival_content_copy(
            brand,
            c["topic"],
            c["intent"],
            PAGE_TYPES[c["intent"]],
            list(by_rival.items()),
            c["n"],
            c["brand"]["value"],
            (top["name"], top["value"]) if top else None,
            c["gap"],
        )
        out.append(
            Candidate(
                "respond_to_rival_content",
                f"rival:{c['key']}",
                title,
                body,
                {
                    "prompt_ids": [str(p["prompt_id"]) for p in c["prompts"]],
                    "observation_ids": [str(o) for o in c["absent_obs"]],
                    "cluster": {"intent": c["intent"], "topic": c["topic"]},
                    "cluster_key": c["key"],
                    "n": c["n"],
                    "spread": c["spread"],
                    "gap": c["gap"],
                    "pages": [
                        {
                            "competitor_id": str(r.competitor_id),
                            "name": r.name,
                            "url": r.url,
                            "first_seen_at": r.first_seen_at.isoformat(),
                        }
                        for r in matched[:RIVAL_PAGES_CAP]
                    ],
                    "pages_total": len(matched),
                },
                c["n"] / total,
                min(len(matched) / RIVAL_PAGES_SATURATION, 1.0),
            )
        )
    return out
```

`PAGE_TYPES` comes from `gaps`, which imports `CONTENT_REASONS` from `recommend`, so it cannot be imported at module top: put `from .gaps import PAGE_TYPES` as the first line inside `_rival_content`, the way `_content_clusters` imports `clusters`. Add `from sqlalchemy import text`, `from sqlalchemy.engine import Row` and `from collections.abc import Sequence` to the module imports if absent. `matched` is already newest first because `_rival_pages` orders that way.

Change `_content_clusters` to take the rows instead of calling `clusters` itself: signature `_content_clusters(s, brand_id, brand, total, rows)`; replace `for c in clusters(s, brand_id, Filters()):` with `for c in rows:`; keep the lazy `clusters` import because the sub-cluster lookup still calls it.

In `generate`, inside `if total:`:

```python
        from .gaps import clusters  # gaps imports CONTENT_REASONS from here

        rows = clusters(s, brand_id, Filters())
        rival_domains = _rival_domains(s, brand_id)
        found += [
            *_citations(s, brand_id, brand, total, rival_domains),
            *_content(s, brand_id, brand, total),
            *_content_clusters(s, brand_id, brand, total, rows),
            *_rival_content(s, brand_id, brand, total, rows),
            *_pages(s, brand_id, brand, total),
            *_sampling(s, brand_id, brand, active, total),
        ]
```

Nothing else changes in `generate`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_recommend.py tests/integration/test_gaps.py`
Expected: PASS. The expected `reach` of `8 / 19` counts the gaps `scene`'s done answers on active prompts: 8 running-shoes + 4 sizing + 4 kids + 3 on the unlabelled but active "old prompt". If the assertion fails on that literal, confirm the count with `select count(*) from observation o join prompt p on p.id = o.prompt_id where o.status = 'done' and p.status = 'active'` in the test, fix the literal, and say so in the report.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/recommend.py tests/integration/test_recommend.py && git commit -q -F - <<'EOF'
feat(recommend): respond_to_rival_content rule over new rival pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Refresh after a crawl; accept creates a measuring task

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (`run_rival_crawl` end)
- Test: `tests/integration/test_rival_crawl.py` (append), `tests/integration/test_api_recommendations.py` (parametrize)

**Interfaces:**
- Consumes: `recommend.refresh` (already imported in `worker.py`), Task 3's rule.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_rival_crawl.py` (add `from tests.integration.test_gaps import scene  # noqa: F401` and `from bsi_core import recommend`):

```python
def test_crawl_refreshes_recommendations(owner, scene):
    org, bid = scene.org, scene.brand
    with owner() as s, s.begin():
        s.execute(
            update(m.Competitor)
            .where(m.Competitor.id == scene.adidas)
            .values(domains=["adidas.co.in"])
        )
    one = {
        "https://adidas.co.in/sitemap.xml": urlset(("https://adidas.co.in/a", None)),
        "https://adidas.co.in/": HOME,
    }
    _run(owner, org, bid, _fake({"adidas.co.in": one}))
    with owner() as s, s.begin():  # make it due again
        s.execute(
            update(m.RivalCrawl).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 8)
            )
        )
    two = {
        **one,
        "https://adidas.co.in/sitemap.xml": urlset(
            ("https://adidas.co.in/a", None),
            ("https://adidas.co.in/running-shoes/ultra", "2026-09-20"),
        ),
        "https://adidas.co.in/running-shoes/ultra": HOME,
    }
    job = _run(owner, org, bid, _fake({"adidas.co.in": two}))
    assert job.status == "done"
    with owner() as s:
        recs = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "respond_to_rival_content"
            )
        ).all()
    assert [r.subject_key for r in recs] == [
        "rival:cluster:comparison:running shoes"
    ]
    assert recs[0].status == "open"


def test_a_failing_refresh_does_not_fail_the_crawl(owner, scene, monkeypatch):
    org, bid = scene.org, scene.brand
    with owner() as s, s.begin():
        s.execute(
            update(m.Competitor)
            .where(m.Competitor.id == scene.adidas)
            .values(domains=["adidas.co.in"])
        )

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "refresh", boom)
    site = {
        "https://adidas.co.in/sitemap.xml": urlset(("https://adidas.co.in/a", None)),
        "https://adidas.co.in/": HOME,
    }
    job = _run(owner, org, bid, _fake({"adidas.co.in": site}))
    assert job.status == "done"
    with owner() as s:
        assert s.scalar(select(func.count()).select_from(m.RivalCrawl)) == 1
```

In `tests/integration/test_api_recommendations.py`, extend the parametrize of `test_accept_carries_the_evidence_prompts` with `("respond_to_rival_content", True)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py -k "refresh" tests/integration/test_api_recommendations.py`
Expected: `test_crawl_refreshes_recommendations` FAILS (no recommendation rows); the failing-refresh test PASSES vacuously (refresh is not called yet) — note that in the report; the API test PASSES already (the accept route is type-agnostic). That is acceptable: the first test is the RED.

- [ ] **Step 3: Implement**

At the end of `run_rival_crawl`, replace `return stored` with:

```python
    if stored:
        # New pages may raise respond_to_rival_content recommendations at
        # once rather than at the weekly refresh. A failure here must not
        # fail the crawl job: the pages are stored either way. No
        # recs_refreshed_at stamp: the weekly pass keeps its cadence.
        try:
            with tenant_session(org_id) as s:
                refresh(s, org_id, brand_id)
        except Exception:
            log.exception("brand %s: refresh after rival crawl failed", brand_id)
    return stored
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py tests/integration/test_api_recommendations.py tests/integration/test_worker.py`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_rival_crawl.py tests/integration/test_api_recommendations.py && git commit -q -F - <<'EOF'
feat(worker): refresh recommendations after a rival crawl

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Labels, report type sets, web evidence links

**Files:**
- Modify: `packages/core/bsi_core/reports.py` (`REC_LABEL`, `SEO_REC_TYPES`, `CONTENT_REC_TYPES`), `apps/web/src/lib/format.ts` (`KIND`), `apps/web/src/lib/format.test.ts`, `apps/web/src/app/(app)/b/[id]/recommendations/page.tsx`
- Generated: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` (run `npm run gen`; expect no diff)

- [ ] **Step 1: Write the failing vitest test**

In `apps/web/src/lib/format.test.ts` after the `KIND` test:

```ts
test("KIND labels the rival-content recommendation", () =>
  expect(KIND.respond_to_rival_content).toBe("Rival content"));
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm test` → FAIL (undefined).

- [ ] **Step 2: Implement**

`format.ts` `KIND`: add `respond_to_rival_content: "Rival content",`.

`reports.py`: add `"respond_to_rival_content": "Rival content",` to `REC_LABEL`; append `"respond_to_rival_content",` to `SEO_REC_TYPES`; change `CONTENT_REC_TYPES` to `("create_content", "optimize_page", "respond_to_rival_content")`.

`recommendations/page.tsx`: extend the `Evidence` type with `pages?: { name?: string; url?: string; first_seen_at?: string }[]; pages_total?: number;` and, after the `Brief:` line, render:

```tsx
      {Array.isArray(ev.pages) && ev.pages.length > 0 && (
        <p className="muted">
          Rival pages:{" "}
          {ev.pages.slice(0, 10).map((p, i) => (
            <span key={i}>
              {i > 0 && " · "}
              {p.name && `${p.name}: `}
              {typeof p.url === "string" && /^https?:\/\//.test(p.url) ? (
                <a href={p.url} target="_blank" rel="noopener noreferrer">
                  {p.url}
                </a>
              ) : (
                String(p.url ?? "")
              )}
              {p.first_seen_at && ` (${p.first_seen_at.slice(0, 10)})`}
            </span>
          ))}
          {typeof ev.pages_total === "number" &&
            ev.pages_total > ev.pages.length &&
            ` and ${ev.pages_total - ev.pages.length} more`}
        </p>
      )}
```

- [ ] **Step 3: Regenerate and run the gates**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen && git -C /Users/vineet/Downloads/ADK/bsi-platform diff --stat -- apps/web/openapi.json apps/web/src/lib/schema.d.ts` → expect no changes (the type is a free string in the schema). Then `npm run gate` → PASS. And from the repo root: `uv run pytest -q tests/integration/test_reports.py` → PASS (report label lookups use `.get`).

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts "apps/web/src/app/(app)/b/[id]/recommendations/page.tsx" && git commit -q -F - <<'EOF'
feat(web,reports): label rival-content recommendations and link their pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Docs

**Files:**
- Create: `docs/findings-slice16.md`
- Modify: `docs/README.md` (a "## Slice 16: recommendations from competitor site changes" section after slice 15's, same table format: spec, plan, findings rows), the spec's `## Rulings` (every ruling from the execution ledger, in order, as plain sentences with decision, reason and cost), the plan's end (a `## Changes made during execution` section listing each deviation)

- [ ] **Step 1: Write the findings skeleton**

`docs/findings-slice16.md` with the four sections used by slices 13–15: `## 1. What was built` (matching helpers, the rule and its constants, migration 0018, the crawl-time refresh, labels and the web links; `git log --oneline main..HEAD` for the commit list), `## 2. Live check` (heading + "Run by the controller on dev before the finishing menu; filled in below." + an empty table `| Check | Result |`), `## 3. Deferred / decisions` (from the spec: crude stem and synonym limit; only descriptive slugs match; the weekly crawl samples only 10 pages for `@type` but every sitemap URL is eligible for matching; both `create_content` and this type can target one cluster; plus every "minor (deferred)" line from the ledger grouped by task with its cost), `## 4. Not covered by tests` (the rule on real crawl data — dev has only baseline pages; the web link rendering has no component test beyond the label).

- [ ] **Step 2: Run both gates**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
```
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
```

- [ ] **Step 3: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice16.md docs/README.md docs/superpowers/specs/2026-09-25-slice16-rival-content-recs-design.md docs/superpowers/plans/2026-09-25-slice16-rival-content-recs.md && git commit -q -F - <<'EOF'
docs: slice 16 findings, index and rulings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Verification (orchestrator, after the final review)

1. Both gates as in Task 6 step 2.
2. Live check on dev. **Ask the user before `alembic upgrade head` on dev** (0017 → 0018; it only rewrites the CHECK constraint). Then, with the API on :8000: `POST /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/recommendations/generate` with Run 1's key; confirm 200 and, read-only, `select count(*) from recommendation where type='respond_to_rival_content'` is 0 (dev's crawls are all baselines) and `select count(*) from rival_page where not baseline` is 0. Record both in findings §2 as observed. The worker is not started.
3. Finishing menu before pushing; PR with `GH_TOKEN=$(gh auth token -u aiagencyindia-lab)`; merge only on the user's say-so.

## Changes made during execution

Deviations from the text above, as recorded in the execution ledger (`.superpowers/sdd/2026-09-25-slice16-rival-content-recs/progress.md`); the spec's Rulings section gives the reasons.

- Preflight, Task 1: `_stem("glass") == "glas"` stands as the plan wrote it; the spec's §1 sentence was corrected instead (spec ruling 1).
- Preflight, Task 3: `test_each_rule_fires_exactly_where_it_should` keeps its expected set, with a comment that the `world` fixture has no labelled clusters or rival pages (spec ruling 2).
- Task 2: the copy test's fixture slug is `adizero-sl-2`, not `ultraboost-24`, because `boost` is a banned word and quoted slugs are exempt data (spec ruling 5).
- Task 3: `test_rival_pages_is_one_statement` became `test_rival_rule_adds_one_statement`, which computes the clusters before attaching the listener and counts the statements of a whole `_rival_content` call (one), so a later query inside the rule would fail it (review fix round 1, commit dadf538). The rival tests that take the imported `scene` fixture carry `# noqa: F811` on the `def` line or on the `scene` parameter line; two of those `def` lines exceed 80 characters.
- Task 4: the plan's `from bsi_core import recommend` import in `test_rival_crawl.py` was dropped as unused; the imported `scene` parameters carry `# noqa: F811` (spec ruling 3).
- Task 5: the evidence-pages markup lives in a new `apps/web/src/components/RivalPages.tsx` with `RivalPages.test.tsx`, not inline in `recommendations/page.tsx`; `Evidence.pages` and `pages_total` are typed `unknown` rather than the plan's object array and number, and the component checks each field's type (spec rulings 4 and 6). "And N more" counts from the pages shown (at most 10), not the stored array's length (a change visible in the code).
- Task 6: `run_rival_crawl` refreshes only when a domain was stored (`if stored:`); spec §4 was corrected to match, along with §4's web bullet and §3's metric line, article and downgrade wording (spec ruling 7).
- Final review: `_rival_pages` reads at most `RIVAL_PAGES_SCAN = 5_000` newest pages (`LIMIT :cap`), with `test_rival_rule_scans_only_the_newest_pages` (spec ruling 8).
- Final review: `test_rival_rule_skips_a_topic_with_no_words` covers the empty-topic guard; findings record over-matching, 14-day expiry, deploy order and the scan ceiling (spec ruling 9).
