# Slice 55: schedule reasons on the Brand SERP page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /v1/brands/{id}/audits/serp` returns `serp_configured` and `failed_7d`, and the Brand SERP page's schedule line says when the weekly sweep skips the brand for missing credentials or three failed audits in 7 days.

**Architecture:** Two fields on the existing `SerpAuditsOut` response, filled in `latest_serp` from the API's `Settings` and one count query that mirrors the last predicate of `due_serp_audits()` (migration 0024). The web app regenerates its types, extends `serpSchedule(status, domains, configured, failed7d)` with two branches, and the page passes the two values it already fetches.

**Tech Stack:** FastAPI 0.141 + SQLAlchemy 2 + pydantic 2 (Python 3.13, uv); Next.js 15 App Router + vitest 3 (Node 22); `openapi-typescript` via `npm run gen`.

**Spec:** docs/superpowers/specs/2026-10-08-slice55-serp-schedule-reasons-design.md

Every block below was applied by script to a fresh copy of a790162 and verified on a second fresh copy: each "replace" block occurs exactly once in its file, ends on a whole line, and matches with or without its trailing newline. Apply the blocks as written; do not retype them.

## Global Constraints

- Every shell command starts with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && …` (the cwd resets after each command).
- Added copy must not contain any word in `FORBIDDEN` of tests/unit/test_recommend_copy.py. Banned-word grep (must block the commit): `! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; }` — it gates every commit and must print nothing.

- No migration; no new route; `tests/integration/test_isolation.py` unchanged; the dev DB is not touched.
- `created_at` comparisons use DB `now()` (`func.now()`), never Python time, in production code.
- The failures threshold is `SERP_MAX_FAILURES = 3` in `format.ts` only; the API returns the raw count.
- ruff line length 80; `apps/api/**` ignores B008.
- Commit trailer, after a blank line: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Shared test DB `bsi_test` on :5433: run `pgrep -fl pytest` before any pytest run and wait if one is running.
- Never run Prettier (it is not in the gate and would rewrap the template line in format.test.ts); never `rm`; no heredoc file writes except the commit messages shown; never stage `.DS_Store`.
- Report every command's one-line summary, pasted, not paraphrased; count before stating a number.

---

### Task 1: API fields `serp_configured` and `failed_7d`

**Files:**
- Modify: `apps/api/bsi_api/schemas.py` (class `SerpAuditsOut`)
- Modify: `apps/api/bsi_api/routers/audits.py` (imports; the end of `latest_serp`)
- Test: `tests/integration/test_api_serp.py`
- Generated: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` (via `npm run gen`)

**Interfaces:**
- Produces: `SerpAuditsOut.serp_configured: bool`, `SerpAuditsOut.failed_7d: int`; the web type `SerpAudits` (`S["SerpAuditsOut"]` in apps/web/src/lib/types.ts, not edited by hand) gains both after `npm run gen`.

- [ ] **Step 0: Install the worktree's dependencies**

The worktree is a fresh checkout: no `.venv`, no `apps/web/node_modules`. Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && uv sync && cd apps/web && npm ci`
Expected: both finish without error; `git status` shows no tracked file changed (both directories are gitignored).

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_api_serp.py` (the imports at the top), replace this block (it occurs exactly once; the block ends on a whole line):

```python
from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_worker import _job
```

with:

```python
from datetime import UTC, datetime, timedelta

from bsi_api.routers import audits
from bsi_core import models as m
from bsi_core.config import Settings
from sqlalchemy import update

from tests.integration.test_worker import _job
```

In `tests/integration/test_api_serp.py` (the end of `_audit` and the first test's `def` line), replace this block (it occurs exactly once; the block ends on a whole line):

```python
                error=error,
            )
        )


def test_post_queues_a_serp_audit_job(client, owner, make_org, make_brand):
```

with:

```python
                error=error,
            )
        )


def _configured(monkeypatch, login="me", password="pw"):
    """The API's DataForSEO settings, patched where audits.py reads them
    (the lambda bypasses get_settings' lru_cache; explicit kwargs win
    over .env)."""
    monkeypatch.setattr(
        audits,
        "get_settings",
        lambda: Settings(dataforseo_login=login, dataforseo_password=password),
    )


def _aged(owner, job_id, ago):
    """Set a job's created_at (_job sets scheduled_slot only; created_at
    is the server default) to now() - ago."""
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job_id)
            .values(created_at=datetime.now(UTC) - ago)
        )


def test_post_queues_a_serp_audit_job(client, owner, make_org, make_brand):
```

In `tests/integration/test_api_serp.py`, replace this block (it occurs exactly once; the block ends on a whole line):

```python
def test_get_is_empty_before_any_audit(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"job": None, "audits": []}
```

with:

```python
def test_get_is_empty_before_any_audit(
    client, make_org, make_brand, monkeypatch
):
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "job": None,
        "audits": [],
        "serp_configured": True,
        "failed_7d": 0,
    }
```

Append to the end of `tests/integration/test_api_serp.py` (its last line, `    }`, ends with a newline). The appended text begins with two blank lines, so that ruff's two-blank-lines-between-functions rule holds; the block below shows them:

```python


def test_get_reports_serp_configured(client, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    for login, password, expected in (
        ("me", "pw", True),
        ("me", "", False),
        ("", "pw", False),
    ):
        _configured(monkeypatch, login, password)
        r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
        assert r.status_code == 200, r.text
        assert r.json()["serp_configured"] is expected, (login, password)


def test_get_counts_failed_audit_serp_jobs_in_7_days(
    client, owner, make_org, make_brand, monkeypatch
):
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    # Counted: three failed audit_serp jobs inside the window. Each
    # audit_serp job on a brand needs its own scheduled_slot (minutes).
    for i, days in enumerate((1, 3, 6)):
        job = _job(owner, org, bid, "audit_serp", "failed", minutes=-i)
        _aged(owner, job, timedelta(days=days))
    # Not counted: outside the window; not failed; another kind.
    _aged(
        owner,
        _job(owner, org, bid, "audit_serp", "failed", minutes=-10),
        timedelta(days=8),
    )
    _aged(
        owner,
        _job(owner, org, bid, "audit_serp", "done", minutes=-20),
        timedelta(days=2),
    )
    _aged(
        owner,
        _job(owner, org, bid, "audit_crawl", "failed", minutes=-30),
        timedelta(days=2),
    )
    # Not counted: another brand of the same org (RLS would hide another
    # org's rows whether or not the query filters on brand).
    other = make_brand(org, name="Other")
    for i, days in enumerate((2, 4)):
        job = _job(owner, org, other, "audit_serp", "failed", minutes=-i)
        _aged(owner, job, timedelta(days=days))
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()["failed_7d"] == 3


def test_failed_7d_window_boundary(
    client, owner, make_org, make_brand, monkeypatch
):
    """A one-minute margin against DB now(): proves the window is 7
    days, not whether its edge is > or >=."""
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    inside = _job(owner, org, bid, "audit_serp", "failed", minutes=-1)
    outside = _job(owner, org, bid, "audit_serp", "failed", minutes=-2)
    _aged(owner, inside, timedelta(days=7) - timedelta(minutes=1))
    _aged(owner, outside, timedelta(days=7) + timedelta(minutes=1))
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()["failed_7d"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && uv run pytest tests/integration/test_api_serp.py -q`
Expected (proof run): `4 failed, 4 passed, 2 warnings`; each new test fails with `AttributeError: <module 'bsi_api.routers.audits' …> has no attribute 'get_settings'` (raised by `_configured`). Paste the summary line in the report.

- [ ] **Step 3: Implement**

In `apps/api/bsi_api/schemas.py`, replace this block (it occurs exactly once; the block ends on a whole line):

```python
class SerpAuditsOut(BaseModel):
    job: SerpJobOut | None
    audits: list[SerpAuditOut]
```

with:

```python
class SerpAuditsOut(BaseModel):
    job: SerpJobOut | None
    audits: list[SerpAuditOut]
    # The API process's DataForSEO credentials: the sweep queues nothing
    # without them (queue_due_serp_audits).
    serp_configured: bool
    # Failed audit_serp jobs in the last 7 days; due_serp_audits()
    # (migration 0024) stops at 3. The web holds the threshold.
    failed_7d: int
```

In `apps/api/bsi_api/routers/audits.py` (the imports), replace this block (it occurs exactly once; the block ends on a whole line):

```python
import uuid
from typing import Any

from bsi_core import models as m
from fastapi import APIRouter
from sqlalchemy import select
```

with:

```python
import uuid
from datetime import timedelta
from typing import Any

from bsi_core import models as m
from bsi_core.config import get_settings
from fastapi import APIRouter
from sqlalchemy import func, select
```

In `apps/api/bsi_api/routers/audits.py` (the end of `latest_serp`), replace this block (it occurs exactly once; the block ends on a whole line):

```python
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
        .limit(1)
    ).first()
    return {"job": job, "audits": audits}
```

with:

```python
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
        .limit(1)
    ).first()
    # The last predicate of due_serp_audits() (migration 0024), on the
    # DB clock: failed audit_serp jobs created in the last 7 days.
    failed = c.s.scalar(
        select(func.count())
        .select_from(m.Job)
        .where(
            m.Job.brand_id == brand_id,
            m.Job.kind == "audit_serp",
            m.Job.status == "failed",
            m.Job.created_at > func.now() - timedelta(days=7),
        )
    )
    settings = get_settings()
    return {
        "job": job,
        "audits": audits,
        "serp_configured": bool(
            settings.dataforseo_login
            and settings.dataforseo_password.get_secret_value()
        ),
        "failed_7d": failed or 0,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && uv run pytest tests/integration/test_api_serp.py -q`
Expected (proof run): `8 passed, 2 warnings`.

- [ ] **Step 5: Mutation table**

Apply each mutant to the file named, run the test file, paste the summary, then restore the file with `git checkout -- <file>` and confirm `git status` shows no change to it. Proof results in the last column.

| Mutant | Change in `apps/api/bsi_api/routers/audits.py` | Failing test | Proof |
|---|---|---|---|
| M1 | delete the line `m.Job.status == "failed",` | `test_get_counts_failed_audit_serp_jobs_in_7_days` | `1 failed, 7 passed` |
| M2 | delete the line `m.Job.created_at > func.now() - timedelta(days=7),` | the count test and `test_failed_7d_window_boundary` | `2 failed, 6 passed` |
| M3 | delete the line `m.Job.kind == "audit_serp",` | the count test | `1 failed, 7 passed` |
| M4 | `"serp_configured": bool(settings.dataforseo_login),` in place of the 4-line `bool(... and ...)` | `test_get_reports_serp_configured` | `1 failed, 7 passed` |
| M7 | delete the line `m.Job.brand_id == brand_id,` | the count test | `1 failed, 7 passed` |
| M8 | `bool(settings.dataforseo_password.get_secret_value())` in place of the login-and-password expression | `test_get_reports_serp_configured` | `1 failed, 7 passed` |

- [ ] **Step 6: Regenerate the web types**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55/apps/web && npm run gen`
(`gen` runs `scripts/export_openapi.py` against the app object and then `openapi-typescript`; no server and no `.env` are needed.)
Expected: `openapi.json` gains the two properties (about +11 or +12 lines, −1; report what you see) and `src/lib/schema.d.ts` +4; `git diff --stat` shows exactly those two generated files changed under apps/web; both contain `serp_configured` and `failed_7d`.

- [ ] **Step 7: Lint, type-check and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && uv run ruff format --check apps/api tests && uv run ruff check apps/api tests/integration/test_api_serp.py && uv run mypy`
Expected (proof run): all files already formatted; `All checks passed!`; `Success: no issues found in 31 source files`.

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && git add apps/api/bsi_api/schemas.py apps/api/bsi_api/routers/audits.py tests/integration/test_api_serp.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -F - <<'EOF' # Banned-word grep (must block the commit)
feat(api): serp_configured and failed_7d on the Brand SERP audits response

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: the schedule line says why the sweep skips

**Files:**
- Modify: `apps/web/src/lib/format.ts` (`serpSchedule`)
- Modify: `apps/web/src/app/(app)/b/[id]/serp/page.tsx` (the `Promise.all` destructuring and the schedule line)
- Test: `apps/web/src/lib/format.test.ts` (the `serpSchedule` test)

**Interfaces:**
- Consumes: `SerpAudits.serp_configured: boolean`, `SerpAudits.failed_7d: number` from Task 1's regenerated `schema.d.ts` (Task 1 must be committed first).
- Produces: `serpSchedule(status: string, domains: number, configured: boolean, failed7d: number): string`.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`, replace this block (it occurs exactly once; the block ends on a whole line):

```ts
test("serpSchedule says whether the weekly sweep audits the brand", () => {
  const weekly = "Audited automatically once a week.";
  const noDomain =
    "Not audited automatically: the brand has no declared domain.";
  const archived = "Not audited automatically: the brand is archived.";
  expect(serpSchedule("active", 1)).toBe(weekly);
  expect(serpSchedule("active", 0)).toBe(noDomain);
  expect(serpSchedule("archived", 0)).toBe(archived);
  expect(serpSchedule("archived", 2)).toBe(archived);
});
```

with:

```ts
test("serpSchedule says whether the weekly sweep audits the brand", () => {
  const weekly = "Audited automatically once a week.";
  const noDomain =
    "Not audited automatically: the brand has no declared domain.";
  const archived = "Not audited automatically: the brand is archived.";
  const unconfigured =
    "Not audited automatically: the SERP provider is not configured.";
  const failed = (n: number) =>
    `Not audited automatically: ${n} audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.`;
  expect(serpSchedule("active", 1, true, 1)).toBe(weekly);
  expect(serpSchedule("active", 1, true, 2)).toBe(weekly);
  expect(serpSchedule("active", 1, true, 3)).toBe(failed(3));
  expect(serpSchedule("active", 1, true, 5)).toBe(failed(5));
  expect(serpSchedule("active", 1, false, 0)).toBe(unconfigured);
  // Not configured outranks the failure pause.
  expect(serpSchedule("active", 1, false, 3)).toBe(unconfigured);
  expect(serpSchedule("active", 0, false, 3)).toBe(noDomain);
  expect(serpSchedule("archived", 1, false, 3)).toBe(archived);
  expect(serpSchedule("archived", 0, true, 0)).toBe(archived);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55/apps/web && npx vitest run src/lib/format.test.ts`
Expected (proof run): the test `serpSchedule says whether the weekly sweep audits the brand` fails: `expected 'Audited automatically once a week.' to be 'Not audited automatically: 3 audits f…'`; the file has 30 tests, so 1 failed and 29 passed. `npm run typecheck` reports `TS2554: Expected 2 arguments, but got 4.` on the new calls until Step 3.

- [ ] **Step 3: Implement**

In `apps/web/src/lib/format.ts`, replace this block (it occurs exactly once; the block ends on a whole line):

```ts
/**
 * The Brand SERP page's schedule line. due_serp_audits() (migration 0024)
 * only considers active brands with at least one declared domain.
 */
export const serpSchedule = (status: string, domains: number) =>
  status !== "active"
    ? "Not audited automatically: the brand is archived."
    : domains === 0
      ? "Not audited automatically: the brand has no declared domain."
      : "Audited automatically once a week.";
```

with:

```ts
/** failed audit_serp jobs in 7 days that stop the sweep (migration 0024). */
const SERP_MAX_FAILURES = 3;

/**
 * The Brand SERP page's schedule line. due_serp_audits() (migration 0024)
 * only considers active brands with at least one declared domain, and
 * stops after SERP_MAX_FAILURES failed jobs in 7 days; the sweep itself
 * queues nothing without DataForSEO credentials.
 */
export const serpSchedule = (
  status: string,
  domains: number,
  configured: boolean,
  failed7d: number,
) =>
  status !== "active"
    ? "Not audited automatically: the brand is archived."
    : domains === 0
      ? "Not audited automatically: the brand has no declared domain."
      : !configured
        ? "Not audited automatically: the SERP provider is not configured."
        : failed7d >= SERP_MAX_FAILURES
          ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
          : "Audited automatically once a week.";
```

In `apps/web/src/app/(app)/b/[id]/serp/page.tsx` (the three fetches), replace this block (it occurs exactly once; the block ends on a whole line):

```tsx
  const [{ job, audits }, brand, domains] = await Promise.all([
    api<SerpAudits>(`/brands/${seg(id)}/audits/serp`),
    api<Brand>(`/brands/${seg(id)}`),
    api<Domain[]>(`/brands/${seg(id)}/domains`),
  ]);
```

with:

```tsx
  const [{ job, audits, serp_configured, failed_7d }, brand, domains] =
    await Promise.all([
      api<SerpAudits>(`/brands/${seg(id)}/audits/serp`),
      api<Brand>(`/brands/${seg(id)}`),
      api<Domain[]>(`/brands/${seg(id)}/domains`),
    ]);
```

In `apps/web/src/app/(app)/b/[id]/serp/page.tsx` (the schedule line), replace this block (it occurs exactly once; the block ends on a whole line):

```tsx
      <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
```

with:

```tsx
      <p className="muted">
        {serpSchedule(brand.status, domains.length, serp_configured, failed_7d)}
      </p>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55/apps/web && npx vitest run src/lib/format.test.ts && npm run typecheck`
Expected (proof run): `Tests 30 passed (30)`; typecheck prints nothing.

- [ ] **Step 5: Mutation table**

Apply each mutant to `apps/web/src/lib/format.ts`, run the test file, paste the failing line, then `git checkout -- apps/web/src/lib/format.ts`.

| Mutant | Change | Failing case | Proof |
|---|---|---|---|
| M5 | `failed7d > SERP_MAX_FAILURES` in place of `>=` | `("active", 1, true, 3)` gets the weekly line | the serpSchedule test fails |
| M6 | the `failed7d >= …` branch moved before the `!configured` branch | `("active", 1, false, 3)` gets the failures line | the serpSchedule test fails |

- [ ] **Step 6: Web gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice55/apps/web && npm run typecheck && npm run lint && npm run test && npm run build && npm run gen:check`
Expected (proof run, except build and gen:check which the proof did not run): lint clean; `Tests 76 passed (76)` (the count does not change: the serpSchedule test is one `test()` with more `expect`s); build compiled; `gen:check` no diff (Task 1 committed the generated files). State the numbers you see.

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice55 && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts "apps/web/src/app/(app)/b/[id]/serp/page.tsx" && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -F - <<'EOF' # Banned-word grep (must block the commit)
feat(web): the Brand SERP schedule line says why the sweep skips the brand

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Departures from the spec

1. Spec Section 3 gives the count test's rows in prose; the plan fixes each `_job` call's `minutes` (brand: −0, −1, −2 for the counted jobs, −10, −20, −30 for the excluded ones; the second brand: −0, −1) and names the second brand `"Other"` (`make_brand(org, name="Other")`), which the spec leaves open.
2. Spec Section 1 shows `select(func.count()).select_from(m.Job).where(…)`; the plan returns `failed or 0`, because `Session.scalar()` is typed `int | None`.
3. Spec Section 3 says `test_get_is_empty_before_any_audit` "patches settings"; the plan adds `monkeypatch` to its fixtures and calls the shared `_configured` helper, and defines `_configured` and `_aged` helpers the spec does not name.
4. Spec Section 2 shows the page passing the two values; the plan reformats the `Promise.all` destructuring across two lines (eslint-neutral; the proof's eslint run is clean) and wraps the schedule `<p>` over three lines.
5. The spec's "red on main" for the web is one failing `expect` inside the existing `serpSchedule` test (the file keeps 30 tests, the suite 76), not a new test.
6. Spec Section 1's `SerpAuditsOut` block has no comments; the plan adds a two-line comment above each new field. Fields and types are identical.
7. Spec Section 1 names the settings variable `s`; the plan names it `settings`, to keep it apart from the session `c.s`; the expression is the same, wrapped over four lines for the 80-column limit.

## Changes made during execution

- Task 1 and Task 2, Step 5 (R4): restoring a mutated file with `git checkout -- <file>` restores HEAD and would wipe the task's uncommitted implementation. The Task 1 implementer staged the implemented file before the mutants, so the restore came from the index; Task 2's dispatch carried the same instruction. Code unchanged.
- Task 1, Step 6: `npm run gen` changed `openapi.json` by +11/−1 (the plan said +11 or +12) and `schema.d.ts` by +4.
- No other departure was reported. Both task reviewers applied their brief's blocks (extracted from this plan) by script to the task's base and found the files those blocks produce byte-identical; the generated `openapi.json` and `schema.d.ts` were checked to hold exactly the two new properties.
