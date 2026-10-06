# Slice 44 Brand SERP Drop Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `serp_drop` alert fires when a brand's own-site organic results on two later Brand SERP pages are both below a baseline page, the three pages a day or more apart and in the same query and locale.

**Architecture:** Migration 0025 adds `serp_drop` to `ck_alert_type`; `models.ALERT_TYPES` and the reports' `ALERT_LABEL` gain it. A fourth detector, `detect_serp_drop`, joins `DETECTORS` in packages/core/bsi_core/alerts.py, so the existing daily scan, duplicate check and webhook carry it. The web app labels it and links it to the Brand SERP page.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, Postgres 16, pytest; Next.js 15, vitest.

**Spec:** `docs/superpowers/specs/2026-10-06-slice44-serp-drop-alert-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice44-serp-drop-alert`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model. Never run `alembic` by hand: the test session applies migrations to `bsi_test` itself.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it and say so.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-web.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `ae465d3`): backend `1728 passed, 2 deselected`; tests/integration/test_alerts.py 14 tests and tests/integration/test_constraints.py 18 items (32 together); web 49 vitest. After Task 1: the two files 34, backend `1730 passed, 2 deselected`. After Task 2: 50, backend `1746 passed, 2 deselected`. (Backend totals computed, not yet run.) Task 3: web 49.

## File map

| File | Responsibility | Task |
|---|---|---|
| `migrations/versions/0025_serp_drop_alert.py` (new) | `ck_alert_type` gains `serp_drop` | 1 |
| `packages/core/bsi_core/models.py` | `ALERT_TYPES` gains `serp_drop`; the `subject_key` comment | 1 |
| `packages/core/bsi_core/reports.py` | `ALERT_LABEL["serp_drop"]` | 1 |
| `packages/core/bsi_core/alerts.py` | `SERP_GAP`, `serp_copy`, `detect_serp_drop`, `DETECTORS`; two docstrings | 2 |
| `tests/integration/test_alerts.py` | the type and label tests (Task 1); the helpers and detector tests (Task 2) | 1, 2 |
| `apps/web/src/lib/format.ts`, `format.test.ts` | `ALERT_KIND["serp_drop"]` | 3 |
| `apps/web/src/app/(app)/b/[id]/alerts/page.tsx` | the explanation line; the Brand SERP link | 3 |

---

### Task 1: the `serp_drop` alert type

**Files:**
- Create: `migrations/versions/0025_serp_drop_alert.py`
- Modify: `packages/core/bsi_core/models.py`, `packages/core/bsi_core/reports.py`
- Test: `tests/integration/test_alerts.py`

**Interfaces:**
- Consumes: the test file's `_alert(owner, org, bid, **kw)` helper and the fixtures `owner`, `make_org`, `make_brand`; `m.ALERT_TYPES` (read by the existing tests/integration/test_constraints.py, which compares it with the live `ck_alert_type`).
- Produces: alert type `serp_drop` accepted by the database; `m.ALERT_TYPES` ending with `"serp_drop"`; `ALERT_LABEL["serp_drop"] == "Brand SERP drop"`; the test file's imports `pytest`, `ALERT_LABEL` and `IntegrityError`.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_alerts.py`:

1. In `tests/integration/test_alerts.py`: Replace

```python
from bsi_core import models as m
```

with

```python
import pytest
from bsi_core import models as m
```

2. In `tests/integration/test_alerts.py`: Replace

```python
from bsi_core.metrics import Filters, brand_deltas
```

with

```python
from bsi_core.metrics import Filters, brand_deltas
from bsi_core.reports import ALERT_LABEL
```

3. In `tests/integration/test_alerts.py`: Replace

```python
from sqlalchemy import func, select, text, update
```

with

```python
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
```

4. Add this block after the file's last line, separated from it by two blank lines:

```python
def test_the_alert_type_check_accepts_serp_drop(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    assert _alert(owner, org, bid, type="serp_drop", subject_key="brand:IN:en")
    with pytest.raises(IntegrityError, match="ck_alert_type"):
        _alert(owner, org, bid, type="serp_change")


def test_every_alert_type_has_a_report_label():
    assert set(ALERT_LABEL) == set(m.ALERT_TYPES)
    assert ALERT_LABEL["serp_drop"] == "Brand SERP drop"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_alerts.py tests/integration/test_constraints.py 2>&1 | tail -1`
Expected: a line starting with `2 failed, 32 passed`. One failure is an `IntegrityError` naming `ck_alert_type` (the insert of a `serp_drop` alert); the other is `KeyError: 'serp_drop'` in `test_every_alert_type_has_a_report_label`.

- [ ] **Step 3: Write the implementation**

1. In `packages/core/bsi_core/models.py`: Replace

```python
ALERT_TYPES = ("mention_drop", "competitor_shift", "new_source")
```

with

```python
ALERT_TYPES = (
    "mention_drop",
    "competitor_shift",
    "new_source",
    "serp_drop",
)
```

2. In `packages/core/bsi_core/models.py`: Replace

```python
    # mention_rate | <competitor_id>:<up|down> | <domain>
```

with

```python
    # mention_rate | <competitor_id>:<up|down> | <domain>
    # | <kind>:<country>:<language> (serp_drop)
```

3. In `packages/core/bsi_core/reports.py`: Replace

```python
    "new_source": "New source",
}
```

with

```python
    "new_source": "New source",
    "serp_drop": "Brand SERP drop",
}
```

4. Create `migrations/versions/0025_serp_drop_alert.py` with the Write tool:

```python
"""alert type serp_drop: the Brand SERP drop alert (slice 44, PRD F15)"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OLD = ("mention_drop", "competitor_shift", "new_source")
NEW = (*OLD, "serp_drop")


def _check(types: tuple[str, ...]) -> None:
    op.drop_constraint("ck_alert_type", "alert")
    op.create_check_constraint(
        "ck_alert_type",
        "alert",
        "type IN (" + ", ".join(f"'{t}'" for t in types) + ")",
    )


def upgrade() -> None:
    _check(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM alert WHERE type = 'serp_drop'")
    _check(OLD)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_alerts.py tests/integration/test_constraints.py 2>&1 | tail -1`
Expected: a line starting with `34 passed`. The test session applies migration 0025 to `bsi_test` itself.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0025_serp_drop_alert.py packages/core/bsi_core/models.py packages/core/bsi_core/reports.py tests/integration/test_alerts.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1730 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the four staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0025_serp_drop_alert.py packages/core/bsi_core/models.py packages/core/bsi_core/reports.py tests/integration/test_alerts.py && git commit -m "feat(alerts): the serp_drop alert type

Migration 0025 adds serp_drop to ck_alert_type; ALERT_TYPES and the
reports' ALERT_LABEL gain it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `detect_serp_drop` in the daily scan

**Files:**
- Modify: `packages/core/bsi_core/alerts.py`
- Test: `tests/integration/test_alerts.py`

**Interfaces:**
- Consumes: Task 1's `serp_drop` type and the imports `pytest`, `ALERT_LABEL`, `IntegrityError`; in alerts.py the existing `Candidate`, `scan`, `is_duplicate`, `m`, `select`, `Session`, `Any`, `timedelta`; `ownership(results) -> (owned, organic)` from packages/core/bsi_core/serp.py; `m.SERP_KINDS` and `m.SerpAudit`.
- Produces: `SERP_GAP = timedelta(days=1)`; `serp_copy(query, country, language, pages) -> str`; `detect_serp_drop(s, brand_id, to) -> list[Candidate]`, the fourth entry of `DETECTORS`.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_alerts.py`:

1. In `tests/integration/test_alerts.py`: Replace

```python
    detect_new_source,
```

with

```python
    detect_new_source,
    detect_serp_drop,
```

2. Insert the helpers and tests before Task 1's first test: Replace

```python
def test_the_alert_type_check_accepts_serp_drop(owner, make_org, make_brand):
```

with

```python
T0 = datetime(2026, 10, 5, 12, tzinfo=UTC)
WEEK = timedelta(days=7)
LATER = T0 + timedelta(days=60)


def _serp(
    owner,
    org,
    bid,
    at,
    owned,
    organic=6,
    *,
    kind="brand",
    error=None,
    country="IN",
    language="en",
    query=None,
    snippet=False,
):
    """One stored page with `owned` official organic results of
    `organic`; snippet adds an official featured snippet."""
    results = [
        {
            "position": i + 1,
            "item_type": "organic",
            "result_type": "official" if i < owned else "other",
            "url": f"https://site{i}.in/",
            "domain": f"site{i}.in",
            "title": "t",
            "sitelinks": False,
        }
        for i in range(organic)
    ]
    if snippet:
        results.insert(
            0,
            {
                "position": 0,
                "item_type": "featured_snippet",
                "result_type": "official",
                "url": "https://walkaroo.in/",
                "domain": "walkaroo.in",
                "title": "t",
                "sitelinks": False,
            },
        )
    if query is None:
        query = "Walkaroo" if kind == "brand" else "Walkaroo reviews"
    with owner() as s, s.begin():
        row = m.SerpAudit(
            org_id=org.id,
            brand_id=bid,
            kind=kind,
            query=query,
            country=country,
            language=language,
            results=results,
            fetched_at=at,
            error=error,
        )
        s.add(row)
        s.flush()
        return row.id


def _weekly(owner, org, bid, owned, kind="brand"):
    """One page a week from T0, with these own-site counts of 6."""
    return [
        _serp(owner, org, bid, T0 + i * WEEK, n, kind=kind)
        for i, n in enumerate(owned)
    ]


def _drops(org, bid, to=LATER):
    with tenant_session(org.id) as s:
        return detect_serp_drop(s, bid, to)


def test_serp_drop_fires_when_two_later_pages_have_fewer_own_results(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    b = _serp(owner, org, bid, T0, 1, 6)
    p = _serp(owner, org, bid, T0 + WEEK, 0, 3)
    last = _serp(owner, org, bid, T0 + 2 * WEEK, 0, 5)
    (c,) = _drops(org, bid)
    assert (c.type, c.subject_key) == ("serp_drop", "brand:IN:en")
    assert c.title == (
        'Own-site results for "Walkaroo" (IN/en) fell from 1 of 6 to '
        "0 of 5 (0 of 3 on the previous page compared)"
    )
    assert (c.window_from, c.window_to) == (T0, T0 + 2 * WEEK)
    assert c.detail == {
        "kind": "brand",
        "query": "Walkaroo",
        "country": "IN",
        "language": "en",
        "pages": [
            {"serp_audit_id": b, "fetched_at": T0, "owned": 1, "organic": 6},
            {
                "serp_audit_id": p,
                "fetched_at": T0 + WEEK,
                "owned": 0,
                "organic": 3,
            },
            {
                "serp_audit_id": last,
                "fetched_at": T0 + 2 * WEEK,
                "owned": 0,
                "organic": 5,
            },
        ],
        "prompt_ids": [],
        "observation_ids": [],
    }


@pytest.mark.parametrize(
    "owned",
    [[1, 0, 1], [1, 1, 0], [1, 1, 1], [0, 1, 1]],
    ids=["recovered", "latest-only", "flat", "rise"],
)
def test_serp_drop_needs_both_later_pages_below_a_baseline(
    owner, make_org, make_brand, owned
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, owned)
    assert _drops(org, bid) == []


def test_serp_drop_needs_three_pages(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    assert _drops(org, bid) == []


def test_serp_drop_reads_only_pages_fetched_before_to(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    assert _drops(org, bid, to=T0 + 2 * WEEK) == []
    (c,) = _drops(org, bid, to=T0 + 2 * WEEK + timedelta(seconds=1))
    assert c.window_to == T0 + 2 * WEEK


def test_serp_drop_counts_a_gap_of_exactly_one_day(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + timedelta(days=1), 0)
    _serp(owner, org, bid, T0 + timedelta(days=2), 0)
    (c,) = _drops(org, bid)
    assert c.window_from == T0


def test_serp_drop_pages_are_at_least_a_day_apart(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    # A second press an hour after the latest page cannot confirm it.
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + WEEK, 0)
    _serp(owner, org, bid, T0 + WEEK + timedelta(hours=1), 0)
    assert _drops(org, bid) == []
    # With a page a week later, the hour-later page is the previous page
    # and the page an hour before it is skipped: T0 is the baseline.
    _serp(owner, org, bid, T0 + 2 * WEEK, 0)
    (c,) = _drops(org, bid)
    assert c.window_from == T0
    assert [p["fetched_at"] for p in c.detail["pages"]] == [
        T0,
        T0 + WEEK + timedelta(hours=1),
        T0 + 2 * WEEK,
    ]


def test_serp_drop_ignores_error_and_empty_pages(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, error="timeout")
    _serp(owner, org, bid, T0 + 4 * WEEK, 0, 0)  # no organic result
    (c,) = _drops(org, bid)
    assert c.window_to == T0 + 2 * WEEK
    # An empty page in the middle is skipped too: no baseline is left.
    other = make_brand(org, "Other")
    _serp(owner, org, other, T0, 1)
    _serp(owner, org, other, T0 + WEEK, 0, 0)
    _serp(owner, org, other, T0 + 2 * WEEK, 0)
    _serp(owner, org, other, T0 + 3 * WEEK, 0, error="http")
    assert _drops(org, other) == []


def test_serp_drop_compares_only_the_latest_pages_locale(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, country="US")
    assert _drops(org, bid) == []  # one US page; the IN pages are skipped
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, country="IN")
    (c,) = _drops(org, bid)  # IN is latest again; the US page is skipped
    assert c.subject_key == "brand:IN:en"
    assert c.window_to == T0 + 3 * WEEK
    # Another language is another series: two IN/hi pages under an IN/en
    # baseline are not a drop.
    other = make_brand(org, "Other")
    _serp(owner, org, other, T0, 1)
    _serp(owner, org, other, T0 + WEEK, 0, language="hi")
    _serp(owner, org, other, T0 + 2 * WEEK, 0, language="hi")
    assert _drops(org, other) == []


def test_serp_drop_compares_only_the_latest_pages_query(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, query="Walkaroo Footwear")
    assert _drops(org, bid) == []  # a renamed brand starts a new series


def test_serp_drop_judges_each_query_kind_on_its_own(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    _weekly(owner, org, bid, [1, 1, 1], kind="reviews")
    assert [c.subject_key for c in _drops(org, bid)] == ["brand:IN:en"]
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, kind="reviews")
    _serp(owner, org, bid, T0 + 4 * WEEK, 0, kind="reviews")
    found = _drops(org, bid)
    assert [c.subject_key for c in found] == ["brand:IN:en", "reviews:IN:en"]
    assert found[1].title.startswith('Own-site results for "Walkaroo reviews"')


def test_serp_drop_counts_only_organic_official_results(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + WEEK, 0, snippet=True)
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, snippet=True)
    (c,) = _drops(org, bid)
    assert [p["owned"] for p in c.detail["pages"]] == [1, 0, 0]


def test_scan_stores_a_serp_drop_once_and_a_further_drop_again(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    weeks = [T0 + i * WEEK for i in range(5)]
    for at, n in zip(weeks[:3], [2, 1, 1], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (row,) = scan(s, org.id, bid, LATER, deliver=False)
        assert (row.type, row.window_to) == ("serp_drop", weeks[2])
        base = row.detail["pages"][0]["fetched_at"]
        assert datetime.fromisoformat(base) == weeks[0]
    with tenant_session(org.id) as s:
        assert scan(s, org.id, bid, LATER, deliver=False) == []
    for at in weeks[3:]:
        _serp(owner, org, bid, at, 0)
    with tenant_session(org.id) as s:
        (again,) = scan(s, org.id, bid, LATER, deliver=False)
        assert (again.window_from, again.window_to) == (weeks[2], weeks[4])
    with owner() as s:
        assert s.scalar(select(func.count(m.Alert.id))) == 2


def test_scan_stores_a_new_serp_drop_after_a_recovery(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    weeks = [T0 + i * WEEK for i in range(7)]
    for at, n in zip(weeks[:3], [1, 0, 0], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (first,) = scan(s, org.id, bid, LATER, deliver=False)
    for at, n in zip(weeks[3:], [1, 1, 0, 0], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (again,) = scan(s, org.id, bid, LATER, deliver=False)
    assert (first.window_from, first.window_to) == (weeks[0], weeks[2])
    assert (again.window_from, again.window_to) == (weeks[4], weeks[6])


def test_the_alert_type_check_accepts_serp_drop(owner, make_org, make_brand):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_alerts.py 2>&1 | tail -3`
Expected: the run stops at collection with `ImportError: cannot import name 'detect_serp_drop' from 'bsi_core.alerts'` and ends `1 error` (the spec's R1).

- [ ] **Step 3: Write the implementation**

1. In `packages/core/bsi_core/alerts.py`: Replace

```python
from .recommend import _rival_domains
```

with

```python
from .recommend import _rival_domains
from .serp import ownership
```

2. In `packages/core/bsi_core/alerts.py`: Replace

```python
NEW_SOURCE_MIN_ANSWERS = 5
```

with

```python
NEW_SOURCE_MIN_ANSWERS = 5
# Pages compared by the Brand SERP drop alert are at least this far
# apart, so two quick audits never confirm each other.
SERP_GAP = timedelta(days=1)
```

3. In `packages/core/bsi_core/alerts.py`: Replace

```python
Each detector reads rolling windows of stored answers, so nothing here can
fire from a single observation. `to` is a parameter everywhere so tests
are deterministic. Copy states what was observed and never promises.
```

with

```python
Each detector reads rolling windows of stored answers, or a run of stored
Brand SERP pages, so nothing here can fire from a single observation or
page. `to` is a parameter everywhere so tests are deterministic. Copy
states what was observed and never promises.
```

4. In `packages/core/bsi_core/alerts.py`: Replace

```python
    starts. Windows of a type have one length, so that is "younger than
    the window"."""
```

with

```python
    starts. For the fixed-length windows that is "younger than the
    window"; for serp_drop it means the alert's latest page is after
    this one's baseline page."""
```

5. In `packages/core/bsi_core/alerts.py`: Replace

```python
DETECTORS = (detect_mention_drop, detect_competitor_shift, detect_new_source)
```

with

```python
def serp_copy(
    query: str, country: str, language: str, pages: list[dict[str, Any]]
) -> str:
    """pages: baseline, previous, latest."""
    base, prev, last = pages
    return (
        f'Own-site results for "{query}" ({country}/{language}) fell from '
        f"{base['owned']} of {base['organic']} to "
        f"{last['owned']} of {last['organic']} "
        f"({prev['owned']} of {prev['organic']} on the previous page compared)"
    )


def detect_serp_drop(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    """A Brand SERP page whose own-site organic results fell, confirmed
    by an earlier page: the latest page (L), the newest page at least
    SERP_GAP before it (P) and the newest at least SERP_GAP before P (B,
    the baseline). Fires when L and P both have fewer than B.

    Only good pages count: no error and at least one organic result. Only
    pages with the latest page's query, country and language are compared,
    so a renamed brand or a new locale starts a new series.
    """
    # ponytail: loads every page of the brand; weekly pages stay few. Add
    # a lookback window if the table grows.
    rows = s.scalars(
        select(m.SerpAudit)
        .where(
            m.SerpAudit.brand_id == brand_id,
            m.SerpAudit.error.is_(None),
            m.SerpAudit.fetched_at < to,
        )
        .order_by(m.SerpAudit.fetched_at.desc(), m.SerpAudit.id.desc())
    ).all()
    out = []
    for kind in m.SERP_KINDS:
        pages = [(r, *ownership(r.results)) for r in rows if r.kind == kind]
        pages = [p for p in pages if p[2] > 0]
        if not pages:
            continue
        latest = pages[0][0]
        here = (latest.query, latest.country, latest.language)
        picked = [pages[0]]
        for p in pages[1:]:
            if (p[0].query, p[0].country, p[0].language) != here:
                continue
            if picked[-1][0].fetched_at - p[0].fetched_at >= SERP_GAP:
                picked.append(p)
                if len(picked) == 3:
                    break
        if len(picked) < 3:
            continue
        (last, last_owned, _), (_, prev_owned, _), (base, base_owned, _) = (
            picked
        )
        if not (last_owned < base_owned and prev_owned < base_owned):
            continue
        detail_pages = [
            {
                "serp_audit_id": r.id,
                "fetched_at": r.fetched_at,
                "owned": owned,
                "organic": organic,
            }
            for r, owned, organic in reversed(picked)
        ]
        out.append(
            Candidate(
                "serp_drop",
                f"{kind}:{last.country}:{last.language}",
                serp_copy(
                    last.query, last.country, last.language, detail_pages
                ),
                {
                    "kind": kind,
                    "query": last.query,
                    "country": last.country,
                    "language": last.language,
                    "pages": detail_pages,
                    "prompt_ids": [],
                    "observation_ids": [],
                },
                base.fetched_at,
                last.fetched_at,
            )
        )
    return out


DETECTORS = (
    detect_mention_drop,
    detect_competitor_shift,
    detect_new_source,
    detect_serp_drop,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_alerts.py tests/integration/test_constraints.py 2>&1 | tail -1`
Expected: a line starting with `50 passed`.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/alerts.py tests/integration/test_alerts.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1746 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/alerts.py tests/integration/test_alerts.py && git commit -m "feat(alerts): detect a Brand SERP drop in the daily scan

detect_serp_drop compares a brand's latest Brand SERP page, an earlier
page and a baseline, each at least a day apart and in the same query
and locale, and fires when both later pages have fewer own-site
organic results than the baseline.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: the alerts page labels and links the alert

**Files:**
- Modify: `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts`, `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`

**Interfaces:**
- Consumes: nothing from Tasks 1 and 2 at build time (the API's `AlertOut` already carries `type`).
- Produces: `ALERT_KIND["serp_drop"] === "Brand SERP drop"`; a "Brand SERP" link on `serp_drop` rows; one changed explanation line.

- [ ] **Step 1: Write the failing test**

1. In `apps/web/src/lib/format.test.ts`: Replace

```ts
    new_source: "New source",
```

with

```ts
    new_source: "New source",
    serp_drop: "Brand SERP drop",
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -5`
Expected: one failed test, `ALERT_KIND labels every alert type`.

- [ ] **Step 3: Write the implementation**

1. In `apps/web/src/lib/format.ts`: Replace

```ts
  new_source: "New source",
};
```

with

```ts
  new_source: "New source",
  serp_drop: "Brand SERP drop",
};
```

2. In `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`: Replace

```tsx
        The worker scans every active brand daily over rolling windows; no
        alert comes from a single answer. Each new alert is posted to the
```

with

```tsx
        The worker scans every active brand daily over rolling windows; no
        alert comes from a single answer or a single Google page. Each new
        alert is posted to the
```

3. In `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`: Replace

```tsx
                    {typeof domain === "string" && <code>{domain}</code>}
```

with

```tsx
                    {typeof domain === "string" && <code>{domain}</code>}
                    {a.type === "serp_drop" && (
                      <Link href={`/b/${id}/serp`}>Brand SERP</Link>
                    )}
```

- [ ] **Step 4: The web gate**

Run the Web gate. Expected: `gate exit 0`; `gate-web.txt` shows `Tests  49 passed (49)` and `Compiled successfully`.

- [ ] **Step 5: Banned-word grep, then commit**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts "apps/web/src/app/(app)/b/[id]/alerts/page.tsx"`. Run the banned-word grep (expected: exit 0, no output). Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts "apps/web/src/app/(app)/b/[id]/alerts/page.tsx" && git commit -m "feat(web): label the Brand SERP drop alert and link its page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: only the untracked `.DS_Store` and `packages/.DS_Store`).

---

## Self-review (plan vs spec)

- Spec coverage: the migration → Task 1 Step 3; `ALERT_TYPES`, the `subject_key` comment and `ALERT_LABEL` → Task 1 Step 3; the detector, `SERP_GAP`, `serp_copy`, `DETECTORS` and the two docstrings → Task 2 Step 3; the web label, the page line and the link → Task 3; the tests → Task 1 Step 1 (2 tests) and Task 2 Step 1 (the helpers and 13 tests, 16 items); expected gates → Task 2 Step 5 and Task 3 Step 4; copy → each task's banned-word grep. The post-merge docs are controller work.
- Testing check, name by name: the spec's Testing block is the helpers plus 15 tests; Task 1 Step 1 has its last two tests and Task 2 Step 1 the rest, with the same bodies, so the finished file matches the spec's block in order.
- Departures from the spec:
  1. The code changes are replace blocks generated from the scratch proof's verified edits, not the spec's unified diffs; the result is the same files.
  2. Three tasks, each with its own commit; the spec sets no task boundaries.
  3. The spec prints the new tests as one block; the plan adds the last two tests in Task 1 and inserts the rest before them in Task 2, so the finished file is the spec's.
  4. Task 1's red step is two failing tests; Task 2's is the import error (the spec's R1, which covered the whole change). Per-task counts (34 and 1730 after Task 1) are the plan's arithmetic.
  5. The spec's mutation table is not repeated in execution.
  6. Task 3 adds a vitest red step on format.test.ts; the spec only names the changed test.
  7. The commit messages are the plan's wording.
  8. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Fixtures and copy: the fixture values (`Walkaroo`, `Walkaroo reviews`, `Walkaroo Footwear`, `site<i>.in`, `walkaroo.in`, `timeout`, `http`, `serp_change`) and the labels contain no banned word.
- Verified before execution (R5, quoted below): Tasks 1 and 2 were applied step by step to a fresh copy of main and run against bsi_test: Task 1 red `2 failed, 32 passed`, green `34 passed`; Task 2 red `1 error` (the ImportError), green `50 passed`; the finished files equal the proof's. Task 3's edits were applied and match the proof's files, but its vitest and web gate steps were not run (vitest runs only inside the repo).
- Placeholders: `<workspace>` and `<N>`.
- Type consistency: `detect_serp_drop(s, brand_id, to) -> list[Candidate]` in Task 2's tests and code; Task 1's tests use only `_alert`, `ALERT_LABEL` and `m.ALERT_TYPES`.

## Rulings made while planning

Quoted from the ledger:

> Ruling: R5. Decided: the plan was verified by applying Tasks 1 and 2 step by step to a fresh scratch copy of main's backend and running each step against bsi_test (Task 1 red 2 failed 32 passed, green 34 passed; Task 2 red 1 error, green 50 passed; finished files equal the proof's), then running migration 0025 down to 0024 by alembic. A first verification run aborted midway and left bsi_test at 0025, which made the next run's Task 1 red show 33 errors; the controller downgraded and re-ran. Task 3's vitest and web gate steps were not run before execution. Found by: the controller, verifying the plan. Why: the plan's code is generated from the proof, and each step's expected output is checked by running it. Cost if wrong: Task 3's red step could differ from the plan; the implementer reports it. How named: in chat, 2026-10-06, before the plan commit.

## Changes made during execution

- Task 1: commit 3279e70; Task 2: commit 621e804; Task 3: commit 01c8612. Each task review says "✅ Spec compliant" and "Task quality: Approved"; no fix rounds. Merged via PR #90 (main `b58f646`).
- Task 2's implementer ran the red step twice, because `tail -3` cut off the ImportError line (disclosed in its report). Task 3's implementer staged and grepped before a commit command without its own `git add` (the same three files).
- Gates and CI, as the ledger records them:
- "Task 1: implementer ae9e6ad519e1abe6c, commit 3279e70 (trailer Opus 5.5 checked); report: red 2 failed 32 passed (IntegrityError ck_alert_type; KeyError 'serp_drop'), green 34 passed, gate exit 0, gate-task1.txt 1730 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 2: implementer a604833a51713c66e, commit 621e804 (trailer Opus 5.5 checked); report: red 1 error (ImportError detect_serp_drop; the red run was repeated once to capture the error line, disclosed), green 50 passed, gate exit 0, gate-task2.txt 1746 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 3: implementer a68a6fc93ca6542d4, commit 01c8612 (trailer Opus 5.5 checked); report: vitest red 1 failed | 27 passed (28) on "ALERT_KIND labels every alert type", web gate exit 0, Tests 49 passed (49), Compiled successfully. Departure disclosed: staged the files and ran the grep before a commit command without its own git add; the same three files."
- "Controller gates on 01c8612: backend gate exit 0, 1746 passed, 2 deselected, 2 warnings in 289.12s (0:04:49), mypy Success; web gate exit 0, Tests  49 passed (49), Compiled successfully."
- "CI run 37514507785: success, 1746 passed, 2 deselected, 2 warnings in 144.70s (0:02:24); web Compiled successfully. PR #90 merged by the controller after the user said "go ahead" to "Should I merge PR #90?" (2026-10-07)."
- "Gates on main b58f646 after merge: backend 1746 passed, 2 deselected, 2 warnings in 247.60s (0:04:07); web Tests  49 passed (49)."
- Reviews, as the ledger records them:
- "Spec review (ac4276b16901f2691, b47492a): 0 Critical, 3 Important, 7 Minor."
- "Spec re-review (ac4276b16901f2691, 0af3c70): "All findings addressed? Yes"; 3 new Minor."
- "Plan review (a8ce26d4916f0a951, dee54b0): "Ready to execute? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Task 1: task review (a70bd55c332f4ad9e, 893fc26..3279e70): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the report holds the red and green lines; bsi_test reads 0025 and the dev DB bsi reads 0024 (alembic_version)."
- "Task 2: task review (a259cea5c95f8eab7, 3279e70..621e804): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor. ⚠️ items resolved by the controller: the report holds the ImportError, "1 error" and "50 passed" lines; the mutant table is the spec's proof evidence, not re-run (plan departure 5)."
- "Task 3: task review (a1badcb174169eb3f, 621e804..01c8612): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor. ⚠️ items resolved by the controller: the report holds the red run, the grep exit and the post-commit status; the build lists /b/[id]/serp."
- "Final review (a60f6db7e4fbc9d55, ae465d3..01c8612): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; every deferred minor triaged "no fix" before merge."
- Rulings made after the spec was approved (R5–R7) are quoted in the spec's "Rulings" section and in docs/findings-slice44.md §3, with every deferred minor.
