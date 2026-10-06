# Slice 46 SERP Sweep Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `queue_due_serp_audits()` asks the budget for room for one estimate per waiting `audit_serp` job of the org plus the brand's own.

**Architecture:** In each brand's tenant session the sweep counts the org's `audit_serp` jobs that are `queued` or `running` and passes `SERP_JOB_MICROS * (waiting + 1)` to the existing `budget_fits`. Three tests pin it.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Postgres 16, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-slice46-serp-sweep-budget-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice46-serp-sweep-budget`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it and say so.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `95d32ad`): backend `1747 passed, 2 deselected`; tests/integration/test_serp_audit.py 32 test items. After Task 1: 38 items, backend `1753 passed, 2 deselected` (computed, not yet run). The web app is not touched.

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/workers/bsi_workers/worker.py` | `queue_due_serp_audits()`: the waiting-job count and its docstring | 1 |
| `tests/integration/test_serp_audit.py` | `_budget` and the three budget tests | 1 |

---

### Task 1: the sweep counts waiting SERP jobs against the budget

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (in `queue_due_serp_audits`)
- Test: `tests/integration/test_serp_audit.py`

**Interfaces:**
- Consumes: in worker.py the existing `select`, `func`, `m`, `tenant_session`, `budget_fits`, `SERP_JOB_MICROS`; in the test file the existing `configured`, `_declared`, `_serp_jobs`, `_job`, `worker`, `update`, `Decimal`, `pytest` and the fixtures `owner`, `make_org`, `make_brand`.
- Produces: no new names outside the test file (`_budget` is a test helper).

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_serp_audit.py`, add this block after the file's last line, separated from it by two blank lines:

```python
def _budget(owner, org, usd):
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal(usd))
        )


def test_one_sweep_queues_no_more_serp_jobs_than_the_budget_has_room_for(
    configured, owner, make_org, make_brand
):
    org = make_org()
    for name in ("A", "B", "C"):
        _declared(owner, org, make_brand(org, name))
    _budget(owner, org, "0.08")  # room for two $0.04 estimates
    assert worker.queue_due_serp_audits() == 2
    assert len(_serp_jobs(owner)) == 2


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_waiting_serp_job_takes_budget_room(
    configured, owner, make_org, make_brand, status
):
    org = make_org()
    other = make_brand(org, "Other")  # no domain, so never due
    _job(owner, org, other, "audit_serp", status)
    bid = _declared(owner, org, make_brand(org))
    _budget(owner, org, "0.04")
    assert worker.queue_due_serp_audits() == 0
    _budget(owner, org, "0.08")
    assert worker.queue_due_serp_audits() == 1
    assert bid in {j.brand_id for j in _serp_jobs(owner)}


@pytest.mark.parametrize("which", ["other-org", "other-kind", "done"])
def test_other_jobs_take_no_serp_budget_room(
    configured, owner, make_org, make_brand, which
):
    org = make_org()
    _declared(owner, org, make_brand(org))
    if which == "other-org":
        elsewhere = make_org("B")
        _job(owner, elsewhere, make_brand(elsewhere), "audit_serp", "queued")
    elif which == "other-kind":
        _job(owner, org, make_brand(org, "Other"), "audit_crawl", "queued")
    else:
        _job(owner, org, make_brand(org, "Other"), "audit_serp", "done")
    _budget(owner, org, "0.04")
    assert worker.queue_due_serp_audits() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `3 failed, 35 passed` (both cases of `test_a_waiting_serp_job_takes_budget_room` and `test_one_sweep_queues_no_more_serp_jobs_than_the_budget_has_room_for`).

- [ ] **Step 3: Write the implementation**

In `apps/workers/bsi_workers/worker.py`:

1. Replace

```python
    - a brand is skipped, with no job, while its org's budget has no
      room for the job's estimate. It stays due and is queued once
      there is room; process_job checks the budget again at claim time.
```

with

```python
    - a brand is skipped, with no job, while its org's budget has no
      room for the job's estimate plus one estimate for each of the
      org's audit_serp jobs still queued or running (those have
      recorded no cost yet). It stays due and is queued once there is
      room; process_job checks the budget again at claim time.
```

2. Replace

```python
            with tenant_session(org_id) as s:
                if not budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS):
                    continue
```

with

```python
            with tenant_session(org_id) as s:
                # ponytail: a "Run audit now" press committed after this
                # count is missed (the API takes no lock); process_job's
                # claim check still catches it. To close the gap, the press
                # and this sweep would both take the org's lock before
                # counting.
                waiting = s.scalar(
                    select(func.count()).where(
                        m.Job.kind == "audit_serp",
                        m.Job.status.in_(("queued", "running")),
                    )
                )
                extra = SERP_JOB_MICROS * ((waiting or 0) + 1)
                if not budget_fits(s, org_id, 0, extra_micros=extra):
                    continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `38 passed`.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate. Expected: `gate exit 0`; `gate-task1.txt` shows `1753 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py && git commit -m "fix(worker): the SERP sweep counts waiting SERP jobs against the budget

A queued or running audit_serp job has recorded no cost yet, so each
brand of an org was checked against the same room. The sweep now asks
for room for one estimate per waiting job plus the brand's own.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the docstring and the count → Step 3; the tests → Step 1; expected gates → Step 5.
- Departures from the spec:
  1. The code changes are whole-line replace blocks generated from the scratch proof's verified edits, not the spec's unified diff; the result is the same file.
  2. The spec's mutation table is not repeated in execution.
  3. The commit message is the plan's wording.
  4. The spec's expected web gate (49, unchanged) is not a plan step; the controller runs it before the finishing menu.
  5. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): Steps 1–4 were applied to a fresh scratch copy of main and run against bsi_test: Step 2 `3 failed, 35 passed`, Step 4 `38 passed`; the finished files equal the spec's proof copies. The gate (Step 5) was not run before execution.
- Placeholders: `<workspace>`.

## Changes made during execution

(Filled in by the post-merge docs commit.)
