# Slice 48 Add-Domain Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Brand SERP page shows an add-domain form, with a spend warning, for an active brand with no declared domain; submitting it declares the domain through the API and returns to the page.

**Architecture:** A server action `addDomain` in the page's `actions.ts` posts the trimmed host to `POST /v1/brands/{id}/domains` with the existing `api()` helper and redirects back. The page renders the form under the schedule line when `brand.status === "active" && domains.length === 0`. Two vitest tests pin the action with mocked `fetch`, cookies and `redirect`.

**Tech Stack:** Next.js 15 App Router (Server Components, server actions), React 19, TypeScript, vitest 3.

**Spec:** `docs/superpowers/specs/2026-10-07-slice48-add-domain-form-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (or `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web &&` for npm and npx).
- **Branch:** `slice48-add-domain-form`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand. No backend file changes in this slice; do not run pytest.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Frontend:** Server Components and server actions only; do not add a Route Handler. Never call `redirect()` inside try/catch. Do not run `npm run gen` other than through the gate's `gen:check` (no API change).
- **Banned words:** copy (code, comments, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `5d6326f`): web `Tests  50 passed (50)`. After Task 1: web 52; the new `actions.test.ts` has 2 tests.

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/web/src/app/(app)/b/[id]/serp/actions.ts` | `addDomain(form)` server action | 1 |
| `apps/web/src/app/(app)/b/[id]/serp/page.tsx` | the form, its label and the warning, under the schedule line | 1 |
| `apps/web/src/app/(app)/b/[id]/serp/actions.test.ts` (new) | the two `addDomain` tests | 1 |

---

### Task 1: the add-domain form

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/serp/actions.test.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/serp/actions.ts` (append after `runSerpAudit`)
- Modify: `apps/web/src/app/(app)/b/[id]/serp/page.tsx`

**Interfaces:**
- Consumes: `api` from `@/lib/api` (throws on a non-2xx answer other than 401/404, after `console.error`), `redirect` from `next/navigation`; in page.tsx the existing `id`, `brand` (`Brand`), `domains` (`Domain[]`) and `serpSchedule`.
- Produces: `export async function addDomain(form: FormData): Promise<void>` in `./actions` (reads `brand_id` and `host`).

- [ ] **Step 1: Write the failing tests**

Create `apps/web/src/app/(app)/b/[id]/serp/actions.test.ts` with exactly:

```ts
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
const redirect = vi.fn();
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));

const { addDomain } = await import("./actions");

const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
const form = (host: string) => {
  const f = new FormData();
  f.set("brand_id", ID);
  f.set("host", host);
  return f;
};

beforeEach(() => cookieStore.get.mockReturnValue({ value: "bsi_key_1" }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  redirect.mockClear();
});

test("addDomain posts the trimmed host, then returns to the page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 201 })),
  );
  await addDomain(form("  walkaroo.in "));
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  const [url, init] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/brands/${ID}/domains`);
  expect(init).toEqual({
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer bsi_key_1",
    },
    body: '{"host":"walkaroo.in"}',
  });
  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp`);
});

test("addDomain does not redirect when the API refuses the host", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 422 })),
  );
  await expect(addDomain(form("localhost"))).rejects.toThrow(/^422/);
  expect(redirect).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run "src/app/(app)/b/[id]/serp/actions.test.ts" 2>&1 | grep -E "TypeError|Tests "`
Expected: a `Failed Tests 2` banner, `TypeError: addDomain is not a function` (twice) and `Tests  2 failed (2)`.

- [ ] **Step 3: Write the implementation**

1. In `apps/web/src/app/(app)/b/[id]/serp/actions.ts`, replace

```ts
  redirect(`/b/${id}/serp?queued=${encodeURIComponent(job.status)}`);
}
```

with

```ts
  redirect(`/b/${id}/serp?queued=${encodeURIComponent(job.status)}`);
}

export async function addDomain(form: FormData) {
  const id = String(form.get("brand_id"));
  const host = String(form.get("host") ?? "").trim();
  await api(`/brands/${id}/domains`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host }),
  });
  redirect(`/b/${id}/serp`);
}
```

2. In `apps/web/src/app/(app)/b/[id]/serp/page.tsx`:

   a. Replace

```tsx
import { runSerpAudit } from "./actions";
```

   with

```tsx
import { addDomain, runSerpAudit } from "./actions";
```

   b. Replace

```tsx
      <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
```

   with

```tsx
      <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
      {brand.status === "active" && domains.length === 0 && (
        <>
          <form action={addDomain} className="row">
            <input type="hidden" name="brand_id" value={id} />
            <label htmlFor="host">Domain</label>
            <input
              id="host"
              name="host"
              required
              pattern=".*\..*"
              title="A domain name such as example.com"
              placeholder="example.com"
              aria-describedby="host-cost"
            />
            <button>Add domain</button>
          </form>
          <p className="muted" id="host-cost">
            Adding a domain lets the weekly Brand SERP audit run for this brand:
            paid Google searches, counted against the daily budget. The first
            can run within minutes.
          </p>
        </>
      )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run "src/app/(app)/b/[id]/serp/actions.test.ts" 2>&1 | grep -E "FAIL|Tests "`
Expected: `Tests  2 passed (2)` and no `FAIL` line.

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/serp/actions.ts" "apps/web/src/app/(app)/b/[id]/serp/page.tsx" "apps/web/src/app/(app)/b/[id]/serp/actions.test.ts"`. Run the banned-word grep (expected: exit 0, no output). Run the Web gate. Expected: `gate exit 0`; `gate-task1.txt` shows `Tests  52 passed (52)` and `Compiled successfully`, and the file has no `API problem` line. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the three staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/serp/actions.ts" "apps/web/src/app/(app)/b/[id]/serp/page.tsx" "apps/web/src/app/(app)/b/[id]/serp/actions.test.ts" && git commit -m "feat(web): add a domain from the Brand SERP page

An active brand with no declared domain is never audited weekly, and
the web app had no way to declare one. The Brand SERP page now shows
an add-domain form, with a spend warning, in that case.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the form, its label, pattern and warning, and its condition → Step 3.2; `addDomain` → Step 3.1; the two tests → Step 1; the expected web gate (52) → Step 5.
- Departures from the spec:
  1. The code changes are a new file plus whole-line replace blocks taken from the scratch proof's final files, not the spec's unified diff; the result is the same files.
  2. The spec's mutation table, pattern check and Prettier check are not repeated in execution.
  3. The commit message is the plan's wording.
  4. The spec's expected backend gate (`1753 passed, 2 deselected`, unchanged) is not a plan step; the controller runs it before the finishing menu.
  5. The spec's optional live check (asked first) is not a plan step; the controller asks the user after the task.
  6. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): Steps 1–4 were applied mechanically from this plan's blocks to a fresh scratch copy of main's `apps/web`: Step 2 printed the banner, the two `TypeError` lines and `Tests  2 failed (2)`; Step 4 `Tests  2 passed (2)`; typecheck, lint, test (`Tests  52 passed (52)`, no `API problem` line) and build (`Compiled successfully`) exited 0; the three finished files are byte-identical to the spec's proof copies. The gate's `gen:check` step was not run there (the copy has no backend).
- Placeholders: `<workspace>`.

## Changes made during execution

- Task 1: commit 2692bd5; the task review says "✅ Spec compliant" and "Task quality: Approved"; no fix rounds. The three files are byte-identical to the spec's proof copies. Merged via PR #98 (main `29b03fa`).
- Gates and CI, as the ledger records them:
  - "Task 1: implementer a22b0d3c877621f8a, commit 2692bd5 (trailer Opus 5.5 checked); report: red 2x TypeError: addDomain is not a function, Tests 2 failed (2); green Tests 2 passed (2); gate exit 0, gate-task1.txt Tests  52 passed (52), Compiled successfully, no API problem line, gen:check no diff; controller check: the three files are byte-identical to the spec's proof copies."
  - "Controller gates on 2692bd5: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 189.19s (0:03:09), mypy Success, metrics coverage 100%; web gate exit 0, Tests  52 passed (52), Compiled successfully, no API problem line."
  - "PR opened for slice48-add-domain-form on head 2692bd5 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
  - "CI run 37602929691: success on 2692bd5, 1753 passed, 2 deselected, 2 warnings in 155.96s (0:02:35); web Tests  52 passed (52), Compiled successfully."
  - "PR #98 merged by the controller after the user said "go ahead" to "Should I merge PR #98?" (2026-10-07); merge commit 29b03fa; local main fast-forwarded to 29b03fa; branch deleted on GitHub and locally."
  - "Gates on main 29b03fa after merge: backend 1753 passed, 2 deselected, 2 warnings in 190.62s (0:03:10), coverage 100%; web Tests  52 passed (52), Compiled successfully."
- Reviews, as the ledger records them:
  - "Spec review (a862091404531fe1d, 08de0dc): "Spec ready? No"; 0 Critical, 1 Important, 7 Minor."
  - "Spec re-review (a5fdc2e90f6b2c82c, bec426a): "Spec ready? Yes"; 0 Critical, 0 Important, 4 Minor. (Both lines added to the ledger after the plan review, 2026-10-07, from the review reports.)"
  - "Plan review (a5ed8116671076bb7, e7e73a5 and 7f11bfa): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
  - "Plan re-review (a9464f5394b9268d3, 3243350): "Ready to execute? Yes"; 0 findings."
  - "Task 1: task review (a9ea918cd380d1fe6, 3243350..2692bd5): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows gen completing and git status shows no openapi.json or schema.d.ts change, so gen:check passed; the report holds the RED and GREEN lines."
  - "Final review (a7e496a90b2a79544, 5d6326f..2692bd5): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; every deferred minor triaged "Not required before merge"."
- R6 (made after the final review) and R7 (from the docs review) are quoted in the spec's "Rulings" section and in docs/findings-slice48.md §3, with every deferred minor.
