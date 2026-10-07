# Slice 47 Brand SERP Schedule Line Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Brand SERP page says "Audited automatically once a week." only for an active brand with a declared domain, and otherwise says why it is not audited automatically.

**Architecture:** A pure helper `serpSchedule(status, domains)` in `apps/web/src/lib/format.ts` picks one of three lines. The page fetches the brand and its domains alongside the audits and renders the helper's line in place of the fixed sentence. One vitest pins the helper.

**Tech Stack:** Next.js 15 App Router (Server Components), React 19, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-07-slice47-serp-schedule-line-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (or `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web &&` for npm and npx).
- **Branch:** `slice47-serp-schedule-line`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand. No backend file changes in this slice; do not run pytest.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Frontend:** Server Components and server actions only; do not add a Route Handler. Do not run `npm run gen` other than through the gate's `gen:check` (no API change).
- **Banned words:** copy (code, comments, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `872b849`): web `Tests  49 passed (49)`; `src/lib/format.test.ts` 28 tests. After Task 1: web 50, `format.test.ts` 29.

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/web/src/lib/format.ts` | `serpSchedule(status, domains)` | 1 |
| `apps/web/src/lib/types.ts` | `Domain` type alias | 1 |
| `apps/web/src/app/(app)/b/[id]/serp/page.tsx` | fetches brand and domains; renders the line | 1 |
| `apps/web/src/lib/format.test.ts` | the `serpSchedule` test | 1 |

---

### Task 1: the Brand SERP page's schedule line

**Files:**
- Modify: `apps/web/src/lib/format.ts` (after `serpStatus`)
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/serp/page.tsx`
- Test: `apps/web/src/lib/format.test.ts`

**Interfaces:**
- Consumes: the existing `api` (`@/lib/api`), `Brand` and `SerpAudits` (`@/lib/types`), and the generated `components["schemas"]["DomainOut"]` (via `S` in types.ts).
- Produces: `export const serpSchedule: (status: string, domains: number) => string` in `@/lib/format`; `export type Domain = S["DomainOut"]` in `@/lib/types`.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`:

1. Replace

```ts
  serpError,
  serpStatus,
```

with

```ts
  serpError,
  serpSchedule,
  serpStatus,
```

2. Replace

```ts
test("ownershipText gives the count and a whole percentage", () => {
```

with

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

test("ownershipText gives the count and a whole percentage", () => {
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | grep -E "FAIL|Tests "`
Expected: three lines: a `⎯⎯⎯ Failed Tests 1 ⎯⎯⎯` banner, `FAIL  src/lib/format.test.ts > serpSchedule says whether the weekly sweep audits the brand`, and `Tests  1 failed | 28 passed (29)`.

- [ ] **Step 3: Write the implementation**

1. In `apps/web/src/lib/format.ts`, replace

```ts
/** "3 of 10 (30%)"; no percentage when the page has no organic results. */
```

with

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

/** "3 of 10 (30%)"; no percentage when the page has no organic results. */
```

2. In `apps/web/src/lib/types.ts`, replace

```ts
export type Competitor = S["CompetitorOut"];
```

with

```ts
export type Competitor = S["CompetitorOut"];
export type Domain = S["DomainOut"];
```

3. In `apps/web/src/app/(app)/b/[id]/serp/page.tsx`:

   a. Replace

```tsx
  serpError,
  serpStatus,
```

   with

```tsx
  serpError,
  serpSchedule,
  serpStatus,
```

   b. Replace

```tsx
import type { SerpAudits } from "@/lib/types";
```

   with

```tsx
import type { Brand, Domain, SerpAudits } from "@/lib/types";
```

   c. Replace

```tsx
  const { job, audits } = await api<SerpAudits>(`/brands/${id}/audits/serp`);
```

   with

```tsx
  const [{ job, audits }, brand, domains] = await Promise.all([
    api<SerpAudits>(`/brands/${id}/audits/serp`),
    api<Brand>(`/brands/${id}`),
    api<Domain[]>(`/brands/${id}/domains`),
  ]);
```

   d. Replace

```tsx
      <p className="muted">Audited automatically once a week.</p>
```

   with

```tsx
      <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | grep -E "FAIL|Tests "`
Expected: `Tests  29 passed (29)` and no `FAIL` line.

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/types.ts "apps/web/src/app/(app)/b/[id]/serp/page.tsx" apps/web/src/lib/format.test.ts`. Run the banned-word grep (expected: exit 0, no output). Run the Web gate. Expected: `gate exit 0`; `gate-task1.txt` shows `Tests  50 passed (50)` and `Compiled successfully`. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the four staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/types.ts "apps/web/src/app/(app)/b/[id]/serp/page.tsx" apps/web/src/lib/format.test.ts && git commit -m "fix(web): the Brand SERP page says whether the brand is audited weekly

The page said \"Audited automatically once a week.\" for every brand,
but the weekly sweep only considers active brands with a declared
domain. It now says why a brand is not audited automatically.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the three lines and their order → Step 3.1; the page's fetches and the rendered line → Step 3.3; the `Domain` type → Step 3.2; the four-case test → Step 1; the expected web gate (50) → Step 5.
- Departures from the spec:
  1. The code changes are whole-line replace blocks taken from the scratch proof's final files, not the spec's unified diff; the result is the same files.
  2. The spec's mutation table is not repeated in execution.
  3. The commit message is the plan's wording.
  4. The spec's expected backend gate (`1753 passed, 2 deselected`, unchanged) is not a plan step; the controller runs it before the finishing menu.
  5. The implementer does not run Prettier (not in the gate; the spec notes `format.test.ts` already fails `prettier --check` on main).
  6. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
  7. The spec's optional live check (asked first) is not a plan step; the controller asks the user after the task (R6).
- Verified before execution (2026-10-07): Steps 1–4 were applied mechanically from this plan's replace blocks to a fresh scratch copy of main's `apps/web`: Step 2 printed the expected three lines, Step 4 `Tests  29 passed (29)`; typecheck, lint, test (`Tests  50 passed (50)`) and build (`Compiled successfully`) exited 0; the four finished files are byte-identical to the spec's proof copies. The gate's `gen:check` step was not run in this verification (the copy has no backend); in the spec's proof run it ran and failed for the same reason (R5, R6).
- Placeholders: `<workspace>`.

## Changes made during execution

- Task 1: commit 5e74f54; the task review says "✅ Spec compliant" and "Task quality: Approved"; no fix rounds. The four files are byte-identical to the spec's proof copies. Merged via PR #96 (main `eb5fb1d`).
- Gates and CI, as the ledger records them:
  - "Task 1: implementer acbcdb3c4a9b1c4e4, commit 5e74f54 (trailer Opus 5.5 checked); report: red Tests 1 failed | 28 passed (29), green Tests 29 passed (29), gate exit 0, gate-task1.txt Tests  50 passed (50), Compiled successfully, gen:check no diff; controller check: the four files are byte-identical to the spec's proof copies."
  - "Controller gates on 5e74f54: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 237.44s (0:03:57), mypy Success, metrics coverage 100%; web gate exit 0, Tests  50 passed (50), Compiled successfully."
  - "PR #96 opened (https://github.com/aiagencyindia-lab/bsi-platform/pull/96) on head 5e74f54 after the user chose "2 PR" at the finishing menu (2026-10-07); the app could not bind it (repo is not this session's checkout); CI gates IN_PROGRESS at the first check."
  - "CI run 37591785967: success on 5e74f54, 1753 passed, 2 deselected, 2 warnings in 150.12s (0:02:30); web Tests  50 passed (50), Compiled successfully."
  - "PR #96 merged by the controller after the user said "go ahead" to "Should I merge PR #96?" (2026-10-07); merge commit eb5fb1d; local main fast-forwarded to eb5fb1d; remote branch deleted, local branch deleted by gh."
  - "Gates on main eb5fb1d after merge: backend 1753 passed, 2 deselected, 2 warnings in 191.24s (0:03:11), coverage 100%; web Tests  50 passed (50), Compiled successfully."
- Reviews, as the ledger records them:
  - "Spec review (af09cbf416947d149, 9228161): "Spec ready? Yes"; 0 Critical, 0 Important, 3 Minor."
  - "Spec re-review (a93fa1af2ddf5d188, 2c7ce54): "Spec ready? Yes"; 0 Critical, 0 Important, 1 Minor (the "only 'archived' is ever written" wording)."
  - "Plan review (ac5492d2b1c12a649, 017693f and 70d0a4c): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
  - "Plan re-review (af86e01e9fb2168cf, 8af3242): "Ready to execute? Yes"; 0 findings."
  - "Task 1: task review (a0ff63e05bdf8e1eb, 8af3242..5e74f54): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows Tests  50 passed (50), Compiled successfully and gen completing, and git status shows no openapi.json or schema.d.ts change, so gen:check passed; the report holds the RED and GREEN lines."
  - "Final review (ab97f02a1a6ce7aff, 872b849..5e74f54): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; both deferred minors triaged "Not needed before merge"."
- R7 (made after the final review) is quoted in the spec's "Rulings" section and in docs/findings-slice47.md §3, with every deferred minor.
