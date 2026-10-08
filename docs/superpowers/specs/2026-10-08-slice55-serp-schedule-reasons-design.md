# Slice 55 design: the Brand SERP page says why the weekly sweep skips a brand

Classification: architectural — said first in chat on 2026-10-08, before the first question. Session model Fable 5.1 for the brainstorm and planning; implementation and review on Opus 5.5.

## Context

Slice 47 added `serpSchedule(status, domains)` (apps/web/src/lib/format.ts) so the Brand SERP page says "Audited automatically once a week." or why not (archived; no declared domain). Its deferred minor: the page still says "weekly" for an active brand with a domain that `queue_due_serp_audits()` (apps/workers/bsi_workers/worker.py) actually skips, in three cases: (1) the DataForSEO login or password is empty, the sweep returns 0 before reading `due_serp_audits()`; (2) three `audit_serp` jobs failed in the last 7 days, encoded in `due_serp_audits()` (migration 0024, `MAX_FAILURES = 3`, `AUDIT_DAYS = 7`); (3) the org's daily budget has no room for `SERP_JOB_MICROS` (the sweep `continue`s). None of these is logged or persisted; `GET /v1/brands/{id}/audits/serp` returns only the latest job's `status` and `error` and the latest page per (country, language, kind), so the web app cannot tell.

Approaches offered in chat: (A) a configured flag plus a 7-day failure count on the audits response; (B) the failure count only; (C) one server-computed reason string including budget. The user chose A on 2026-10-08. Budget stays out: it is computed live under the org's advisory lock and would flicker; the Ops page already shows spend.

## Section 1 — API

`SerpAuditsOut` (apps/api/bsi_api/schemas.py) gains:

```python
class SerpAuditsOut(BaseModel):
    job: SerpJobOut | None
    audits: list[SerpAuditOut]
    serp_configured: bool
    failed_7d: int
```

`latest_serp` (apps/api/bsi_api/routers/audits.py) fills them next to the existing `job` query:

- `serp_configured = bool(s.dataforseo_login and s.dataforseo_password.get_secret_value())` with `s = get_settings()` (import `from bsi_core.config import get_settings`, as routers/metrics.py and routers/tasks.py do). This is the expression `queue_due_serp_audits()` tests. Limit, stated here: it describes the API process's settings; today the API and the worker read the same `.env`.
- `failed_7d`: one count in the tenant session mirroring the last predicate of `due_serp_audits()`: `select(func.count()).select_from(m.Job).where(m.Job.brand_id == brand_id, m.Job.kind == "audit_serp", m.Job.status == "failed", m.Job.created_at > func.now() - timedelta(days=7))`. DB `now()`, not Python time. The constants 7 and 3 stay in migration 0024; the API returns the raw count and the web holds the threshold (user decision: raw count over a boolean).

No new route (test_isolation.py unchanged), no migration, dev untouched. After the change: `npm run gen`; commit `apps/web/openapi.json` and `apps/web/src/lib/schema.d.ts`.

## Section 2 — Web

`SerpAudits` in apps/web/src/lib/types.ts gains `serp_configured: boolean` and `failed_7d: number`.

apps/web/src/lib/format.ts:

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
          ? "Not audited automatically: 3 audits failed in the last 7 days; the sweep tries again when the oldest failure is more than 7 days old."
          : "Audited automatically once a week.";
```

Precedence (user-approved): archived → no domain → not configured → failures → weekly. apps/web/src/app/(app)/b/[id]/serp/page.tsx passes `serp_configured` and `failed_7d` from the `/audits/serp` response it already fetches; no new request. `serpStatus(job)` still shows the latest job's error beneath. The add-domain form condition is unchanged. Budget is not mentioned. The copy holds none of the FORBIDDEN words of tests/unit/test_recommend_copy.py (checked by the commit grep).

## Section 3 — Testing

Backend, tests/integration/test_api_serp.py (helpers: `_job(owner, org, bid, "audit_serp", status, minutes=…, error=…)` from test_worker; settings via `monkeypatch.setattr(audits, "get_settings", lambda: Settings(...))` on the audits module, as test_serp_audit.py does for the worker):

- `test_get_reports_serp_configured`: login and password set → `serp_configured` true; password empty → false.
- `test_get_counts_failed_audit_serp_jobs_in_7_days`: three failed jobs at −1, −3 and −6 days → `failed_7d == 3`; excluded (count stays 3): a failed job at −8 days, a `done` job at −2 days, a failed `audit_crawl` job at −2 days, another org's brand's failed jobs (org_b). Boundary: −7 days + 1 minute counts, −7 days − 1 minute does not (`created_at` set by `update()` as the existing test does).
- `test_get_is_empty_before_any_audit` asserts the whole body and gains the two keys (`failed_7d: 0`).

Web: format.test.ts `serpSchedule` cases: `("active", 1, false, 0)` → not configured; `("active", 1, true, 3)` and `(…, 5)` → failures; `("active", 1, true, 2)` → weekly; `("active", 0, false, 3)` → no domain; `("archived", 1, false, 3)` → archived. api-paths.test.ts unchanged; `gen:check` proves schema.d.ts.

Proof: red on main, green patched, and a mutation table, each caught by a named test: M1 count without the `status == "failed"` filter; M2 without the 7-day window; M3 without the `kind` filter; M4 `configured` ignoring the password; M5 `>` instead of `>=` in the web threshold; M6 precedence swapped (not-configured after failures).

Gates: both, run by the controller before the finishing menu; counts stated after running.

## Section 4 — Process, live check, docs

Spec → Opus review → scoped re-review → user review → "Approve, write plan" → writing-plans (prototype in a fresh scratchpad directory only the controller writes; replace blocks generated from the proof; verified on a fresh copy under both newline readings; every spec departure listed) → plan review → execution choice → subagent-driven-development on Opus 5.5 in worktree bsi-wt/slice55 → task review → final review → controller gates → finishing menu → PR → docs PR.

Live check: none (values on dev are predictable: configured true, Walkaroo failed_7d 0; any authenticated GET writes api_key.last_used_at). Dev DB untouched. Findings docs are controller-written on the session model (user's standing rule, 2026-10-08) and reviewed by an Opus 5.5 reviewer.

Out of scope: the budget-room skip; making the flag describe the worker's settings when they differ from the API's; a per-brand SQL variant of `due_serp_audits()`.

## Rulings

None at spec time. (Rulings made later are appended here by the docs commits, with the ledger line quoted.)

## Deferred

- The page cannot say the sweep skipped for budget room.
- A page-render test for the SERP page (slice 54 M4) is still absent.
