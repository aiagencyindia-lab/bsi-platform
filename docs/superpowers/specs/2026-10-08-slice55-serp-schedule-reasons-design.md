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

`SerpAudits` in apps/web/src/lib/types.ts is `S["SerpAuditsOut"]`, generated from the schema, so it gains `serp_configured: boolean` and `failed_7d: number` through `npm run gen`; types.ts is not edited by hand.

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
          ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
          : "Audited automatically once a week.";
```

The failures line interpolates the count (it can exceed 3: "Run audit now" jobs count too) and the threshold, so it stays true for any count and follows the constant (user decision after the spec review, 2026-10-08, re-asked because the first wording misstated counts above 3 and the resume condition). Precedence (user-approved): archived → no domain → not configured → failures → weekly. apps/web/src/app/(app)/b/[id]/serp/page.tsx passes `serp_configured` and `failed_7d` from the `/audits/serp` response it already fetches; no new request. `serpStatus(job)` still shows the latest job's error beneath. The add-domain form condition is unchanged. Budget is not mentioned. The copy holds none of the FORBIDDEN words of tests/unit/test_recommend_copy.py (checked by the commit grep).

## Section 3 — Testing

Backend, tests/integration/test_api_serp.py. The module adds `from bsi_api.routers import audits` and `from bsi_core.config import Settings`. Settings are patched with `monkeypatch.setattr(audits, "get_settings", lambda: Settings(dataforseo_login=…, dataforseo_password=…))` on the audits module (the router imports the name at module level, so the lambda bypasses `lru_cache`; explicit kwargs override `.env`), as test_serp_audit.py does for the worker. Every test that reads `serp_configured` patches it: `Settings` reads `.env`, which holds credentials in the main checkout and nothing in a worktree. Job rows come from `_job(owner, org, bid, "audit_serp", status, minutes=…, error=…)` (test_worker), which sets `scheduled_slot`, not `created_at`; `created_at` is `server_default=func.now()`, so every job whose age matters gets its `created_at` set by `update(m.Job).values(created_at=…)` as the existing `test_get_reports_the_latest_audit_serp_job` does, and each `audit_serp` job on one brand gets a distinct `minutes` (unique `(brand_id, kind, scheduled_slot)`).

- `test_get_reports_serp_configured`: login and password set → `serp_configured` true; login set, password empty → false; login empty, password set → false.
- `test_get_counts_failed_audit_serp_jobs_in_7_days`: on the brand, three failed `audit_serp` jobs with `created_at` at −1, −3 and −6 days → `failed_7d == 3`. Also present and excluded (the count is exactly 3): a failed `audit_serp` job at −8 days; a `done` `audit_serp` job at −2 days; a failed `audit_crawl` job at −2 days; two failed `audit_serp` jobs at −2 and −4 days on a second brand of the same org (RLS would hide another org's rows whether or not the query filters on brand, so the same-org brand is what proves the `brand_id` filter).
- `test_failed_7d_window_boundary`: two failed `audit_serp` jobs, `created_at` at −7 days + 1 minute and −7 days − 1 minute → `failed_7d == 1`. This proves the window exists and is 7 days; a one-minute margin against DB `now()` cannot tell `>` from `>=`, and the spec does not claim it does.
- `test_get_is_empty_before_any_audit` patches settings with both credentials set and asserts the whole body with `serp_configured: True` and `failed_7d: 0`.

Web: format.test.ts `serpSchedule` cases, asserting the exact strings:
- `("active", 1, true, 1)` → "Audited automatically once a week." (the existing case, now with the two new arguments);
- `("active", 1, true, 2)` → weekly;
- `("active", 1, true, 3)` → "Not audited automatically: 3 audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.";
- `("active", 1, true, 5)` → the same line with "5 audits failed";
- `("active", 1, false, 0)` → "Not audited automatically: the SERP provider is not configured.";
- `("active", 1, false, 3)` → not configured (precedence over failures);
- `("active", 0, false, 3)` → "Not audited automatically: the brand has no declared domain.";
- `("archived", 1, false, 3)` and `("archived", 0, true, 0)` → "Not audited automatically: the brand is archived."

api-paths.test.ts unchanged; `gen:check` proves schema.d.ts.

Proof: red on main, green patched, and a mutation table, each caught by a named test: M1 count without the `status == "failed"` filter (the `done` job); M2 without the 7-day window (the −8 days job and the boundary test); M3 without the `kind` filter (the `audit_crawl` job); M4 `configured` ignoring the password (the empty-password case); M5 `>` instead of `>=` in the web threshold (`("active", 1, true, 3)`); M6 precedence swapped, failures before not-configured (`("active", 1, false, 3)`); M7 count without the `brand_id` filter (the same-org second brand); M8 `configured` ignoring the login (the empty-login case).

Gates: both, run by the controller before the finishing menu; counts stated after running.

## Section 4 — Process, live check, docs

Spec → Opus review → scoped re-review → user review → "Approve, write plan" → writing-plans (prototype in a fresh scratchpad directory only the controller writes; replace blocks generated from the proof; verified on a fresh copy under both newline readings; every spec departure listed) → plan review → execution choice → subagent-driven-development on Opus 5.5 in worktree bsi-wt/slice55 → task review → final review → controller gates → finishing menu → PR → docs PR.

Live check: none (values on dev are predictable: configured true, Walkaroo failed_7d 0; any authenticated GET writes api_key.last_used_at). Dev DB untouched. Findings docs are controller-written on the session model (user's standing rule, 2026-10-08) and reviewed by an Opus 5.5 reviewer.

Out of scope: the budget-room skip; making the flag describe the worker's settings when they differ from the API's; a per-brand SQL variant of `due_serp_audits()`.

## Rulings

Every `Ruling:` line in the ledger, verbatim (later ones are appended by the docs commits):

> Ruling: R1. Decided: the spec review's other findings are fixed in the spec: a serpSchedule case ('active', 1, false, 3) -> not configured catches M6 (C1); test_get_is_empty_before_any_audit patches audits.get_settings and expects serp_configured true (I2); the count test adds failed audit_serp jobs on a second brand of the same org and a mutant M7 'count without the brand_id filter' (I3); every job's created_at is set by update() with a distinct minutes per job, the main case expects 3 and the window boundary is its own test expecting 1 of 2 jobs (I4); types.ts gains the fields through npm run gen, not by hand (m1); the boundary proves the window exists, not > versus >= (m2); an empty-login, set-password case expects false (m3); the (…, 5) case is written in full (m4); the test module imports the audits router (m5). Found by: the spec reviewer (Opus 5.5), 2026-10-08. Why: a test gap, two nondeterministic or ambiguous test designs, and loose wording of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 03:21 UTC)

## Deferred

- The page cannot say the sweep skipped for budget room.
- A page-render test for the SERP page (slice 54 M4) is still absent.
