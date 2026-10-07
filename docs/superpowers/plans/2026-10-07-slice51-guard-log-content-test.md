# Slice 51 Guard Log Content Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The guard's long-path log test asserts the exact logged text for a path that holds a double quote.

**Architecture:** One test in `apps/web/src/lib/api.test.ts` changes: its path gains a `"`, `expect.any(String)` becomes the exact 200-character literal, and the length-only line goes. No code change.

**Tech Stack:** Next.js 15, TypeScript, vitest 3.

**Spec:** `docs/superpowers/specs/2026-10-07-slice51-guard-log-content-test-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (or `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web &&` for npm and npx).
- **Branch:** `slice51-guard-log-content-test`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand. No backend or `apps/web/src/lib/api.ts` change; do not run pytest.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`. Do not redirect any output outside the repo or `<workspace>`.
- **Frontend:** do not run `npm run gen` other than through the gate's `gen:check`. Do not run Prettier (the plan's code is already formatted).
- **Banned words:** copy (code, comments, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `b44c2ac`): web `Tests  73 passed (73)`; `api.test.ts` 23 tests. After Task 1: the same counts.

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/web/src/lib/api.test.ts` | the guard's long-path log test | 1 |

---

### Task 1: the guard's long-path log test checks the logged text

**Files:**
- Test: `apps/web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: the existing `signedIn`, `api`, `vi` in the test file, and `api.ts` unchanged (the guard logs `("API path refused", shown(path), path.length)`).
- Produces: nothing new.

- [ ] **Step 1: Change the test**

In `apps/web/src/lib/api.test.ts`:

1. Replace these 8 lines (from the `const path` line through the `toHaveLength(200)` line, which is removed):

```ts
  const path = `/brands/x#${"y".repeat(500)}`;
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    expect.any(String),
    path.length,
  );
  expect(log.mock.calls[0][1]).toHaveLength(200);
```

   with these 7 lines:

```ts
  const path = `/brands/x#"${"y".repeat(500)}`;
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    `"/brands/x#\\"${"y".repeat(187)}`,
    path.length,
  );
```

- [ ] **Step 2: Run the test file**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api.test.ts 2>&1 | grep -E "^ +Tests |FAIL"`
Expected: `Tests  23 passed (23)` and no `FAIL` line. There is no failing run first: the code already logs this text, and the change makes a passing test stricter (the spec's mutants are its evidence).

- [ ] **Step 3: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.test.ts`. Run the banned-word grep (expected: exit 0, no output). Run the Web gate. Expected: `gate exit 0`; `gate-task1.txt` shows `Tests  73 passed (73)` and `Compiled successfully`, and the file has no `API path refused` or `API path value refused` line. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the staged file plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.test.ts && git commit -m "test(web): the guard's long-path log test checks the logged text

The test checked only that the guard's capped log text was 200
characters long. It now uses a path with a double quote and asserts
the exact text, so a wrong cut or a dropped quote escape fails.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the test change → Step 1; the expected counts (23, 73) → Steps 2 and 3.
- Departures from the spec:
  1. The change is one replace block taken from the scratch proof's final file (the whole changed run of lines, so no block deletes a line by replacing it with nothing), not the spec's unified diff; the result is the same file (R5).
  2. The spec's mutation table and Prettier check are not repeated in execution.
  3. The commit message is the plan's wording.
  4. The spec's expected backend gate (`1753 passed, 2 deselected`, unchanged) is not a plan step; the controller runs it before the finishing menu.
  5. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): Step 1 was applied mechanically from this plan's blocks (parsed from this file) to a fresh scratch copy of main's `apps/web`: Step 2 `Tests  23 passed (23)`; typecheck, lint, test (`Tests  73 passed (73)`) and build exit 0 with no refusal line; the test file is byte-identical to the spec's proof copy and `api.ts` is unchanged. After R5 the single block was re-checked on a fresh copy both with and without its trailing newline: both readings give the proof file, Step 2 `Tests  23 passed (23)`, and the four gate steps exit 0 (73 tests). The gate's `gen:check` step was not run there (the copy has no backend).
- Placeholders: `<workspace>`.

## Changes made during execution

None yet.
