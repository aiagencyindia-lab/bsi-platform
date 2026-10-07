# Slice 50 Refusal Log Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The two refusal log lines in `apps/web/src/lib/api.ts` print the value JSON-quoted and capped at 200 UTF-16 code units, plus its full length.

**Architecture:** A helper `shown(text) = JSON.stringify(text).slice(0, 200)`; `sendAsWritten` logs `("API path refused", shown(path), path.length)` and `seg` logs `("API path value refused", shown(value), value.length)`. Tests in `api.test.ts` pin the new call shape and both caps.

**Tech Stack:** Next.js 15, TypeScript, vitest 3.

**Spec:** `docs/superpowers/specs/2026-10-07-slice50-refusal-log-cap-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (or `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web &&` for npm and npx).
- **Branch:** `slice50-refusal-log-cap`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand. No backend file changes in this slice; do not run pytest.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`. Do not redirect any output outside the repo or `<workspace>`.
- **Frontend:** do not run `npm run gen` other than through the gate's `gen:check` (no API change). Do not run Prettier (the plan's code is already formatted).
- **Banned words:** copy (code, comments, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `be011d5`): web `Tests  71 passed (71)`; `api.test.ts` 21 tests. After Task 1: web 73; `api.test.ts` 23.

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/web/src/lib/api.ts` | `shown()` and the two refusal log lines | 1 |
| `apps/web/src/lib/api.test.ts` | the updated asserts and the two long-value tests | 1 |

---

### Task 1: quoted, capped refusal logs with the length

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: the existing `sendAsWritten`, `seg`, `api` in api.ts; in the test file the existing `signedIn`, `api`, `seg`, `vi`.
- Produces: no new exports (`shown` is module-private).

- [ ] **Step 1: Write the failing tests**

In `apps/web/src/lib/api.test.ts`:

1. Replace

```ts
  expect(log).toHaveBeenCalledWith("API path refused", path);
```

   with

```ts
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    JSON.stringify(path),
    path.length,
  );
});

test("api logs a long refused path quoted, capped and with its length", async () => {
  signedIn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn());
  const path = `/brands/x#${"y".repeat(500)}`;
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    expect.any(String),
    path.length,
  );
  expect(log.mock.calls[0][1]).toHaveLength(200);
```

2. Replace

```ts
    expect(log).toHaveBeenCalledWith("API path value refused", value);
```

   with

```ts
    expect(log).toHaveBeenCalledWith(
      "API path value refused",
      JSON.stringify(value),
      value.length,
    );
```

3. Replace

```ts
  },
);
```

   with

```ts
  },
);

test("seg logs a long value quoted, capped and with its length", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const value = `a\n${"b".repeat(500)}`;
  expect(() => seg(value)).toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path value refused",
    expect.any(String),
    502,
  );
  const logged = log.mock.calls[0][1] as string;
  expect(logged).toHaveLength(200);
  expect(logged.startsWith('"a\\n')).toBe(true);
  expect(logged).not.toContain("\n");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api.test.ts 2>&1 | grep -E "^ +Tests "`
Expected: `Tests  17 failed | 6 passed (23)`.

- [ ] **Step 3: Write the implementation**

In `apps/web/src/lib/api.ts`:

1. Replace

```ts

// ponytail: a backstop for anything a call site misses. It refuses dot
```

   with

```ts

/** A refused value for the log: quoted (C0 control characters escaped), at
 * most 200 UTF-16 code units. */
const shown = (text: string) => JSON.stringify(text).slice(0, 200);

// ponytail: a backstop for anything a call site misses. It refuses dot
```

2. Replace

```ts
  console.error("API path refused", path);
```

   with

```ts
  console.error("API path refused", shown(path), path.length);
```

3. Replace

```ts
  console.error("API path value refused", value);
```

   with

```ts
  console.error("API path value refused", shown(value), value.length);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api.test.ts 2>&1 | grep -E "^ +Tests |FAIL"`
Expected: `Tests  23 passed (23)` and no `FAIL` line.

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.ts apps/web/src/lib/api.test.ts`. Run the banned-word grep (expected: exit 0, no output). Run the Web gate. Expected: `gate exit 0`; `gate-task1.txt` shows `Tests  73 passed (73)` and `Compiled successfully`, and the file has no `API path refused` or `API path value refused` line. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.ts apps/web/src/lib/api.test.ts && git commit -m "fix(web): refusal logs are quoted, capped and give the length

The two refusal log lines printed the raw value, so a long or
multi-line value made a long or split log entry. They now print it
JSON-quoted and capped at 200 code units, with its full length.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: `shown()` and both log lines → Step 3; the updated asserts and the two long-value tests → Step 1; the expected web gate (73) → Step 5.
- Departures from the spec:
  1. The code changes are replace blocks generated by script from the scratch proof's final files (each widened until it occurs once), not the spec's unified diff; the result is the same files.
  2. The spec's mutation table and Prettier check are not repeated in execution.
  3. The commit message is the plan's wording.
  4. The spec's expected backend gate (`1753 passed, 2 deselected`, unchanged) is not a plan step; the controller runs it before the finishing menu.
  5. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): Steps 1–4 were applied mechanically from this plan's blocks (parsed from this file) to a fresh scratch copy of main's `apps/web`: Step 2 `Tests  17 failed | 6 passed (23)`, Step 4 `Tests  23 passed (23)`; typecheck, lint, test (`Tests  73 passed (73)`) and build exit 0 with no refusal line; both finished files are byte-identical to the spec's proof copies (R2's rebuilt proof). The gate's `gen:check` step was not run there (the copy has no backend).
- Placeholders: `<workspace>`.

## Changes made during execution

- Task 1: commit 08645d3; the first dispatch returned NEEDS_CONTEXT because the brief lacked the Global Constraints (a controller script error), and the resumed implementer finished it; the task review says "✅ Spec compliant" and "Task quality: Approved"; no fix rounds. Both files are byte-identical to the spec's rebuilt proof. Merged via PR #102 (main `eeecd0b`).
- Execution, gates and CI, as the ledger records them:
  - "Task 1: implementer a2134b4b98115cf55 reported NEEDS_CONTEXT: the brief lacked the Global Constraints, because the controller's append script failed with a Python f-string error; the controller appended them and resumed the implementer."
  - "Task 1: implementer a2134b4b98115cf55 (resumed), commit 08645d3 (trailer Opus 5.5 checked); report: red Tests 17 failed | 6 passed (23), green Tests 23 passed (23); gate exit 0, gate-task1.txt Tests  73 passed (73), Compiled successfully, no refusal line, gen:check no diff; controller check: api.ts and api.test.ts are byte-identical to the rebuilt proof (s50b)."
  - "Controller gates on 08645d3: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 205.70s (0:03:25), mypy Success, metrics coverage 100%; web gate exit 0, Tests  73 passed (73), Compiled successfully, no refusal line."
  - "PR opened for slice50-refusal-log-cap on head 08645d3 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
  - "PR #102's description first said R1–R3 are quoted in the spec; the spec quotes R1, R2 and the Correction to R1 only; corrected through gh api PATCH (2026-10-07)."
  - "CI run 37620460567: success on 08645d3, 1753 passed, 2 deselected, 2 warnings in 109.18s (0:01:49); web Tests  73 passed (73), Compiled successfully."
  - "PR #102 merged by the controller after the user said "go ahead" to "Should I merge PR #102?" (2026-10-07); merge commit eeecd0b; local main fast-forwarded to eeecd0b; branch deleted on GitHub and locally."
  - "Gates on main eeecd0b after merge (exact): backend 1753 passed, 2 deselected, 2 warnings in 341.40s (0:05:41), coverage 100%; web Tests  73 passed (73), Compiled successfully."
- Reviews, as the ledger records them:
  - "Spec review (abaf5a03f31a8dfdb, c5abbd6): "Spec ready? Yes"; 0 Critical, 0 Important, 6 Minor."
  - "Spec re-review (a207c2739f349dbd6, 7261182): "Spec ready? Yes"; 0 Critical, 0 Important, 1 Minor (noted only, no change needed). The reviewer worked in its own new directory and reported a stray /tmp/null holding tsc output; the controller looked at it (empty) and removed it."
  - "Note (2026-10-07): the line above says /tmp/null was empty; it held 29 bytes, the npm script header "> typecheck" and "> tsc --noEmit", and was removed after that was seen."
  - "Plan review (ab86501954b7a3d30, d51944a): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
  - "Task 1: task review (aeda51a1c7222e82c, d51944a..08645d3): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1; gate-task1.txt shows Tests  73 passed (73), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; both files are byte-identical to the rebuilt proof."
  - "Final review (abdfc26968fa43d67, be011d5..08645d3): "Ready to merge? Yes"; 0 Critical, 0 Important, 2 Minor; both deferred minors triaged "does not need fixing before merge"."
- R3 (from the plan review), R4 (from the final review) and R5 (from the docs review) are quoted in the spec's "Rulings" section and in docs/findings-slice50.md §3, with every deferred minor.
