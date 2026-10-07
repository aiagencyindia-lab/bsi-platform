# Slice 51 design: the guard's long-path log test checks the logged text

## Context

Codebase facts: main `b44c2ac`, checked 2026-10-07.

Slice 50 made the guard (`sendAsWritten` in `apps/web/src/lib/api.ts`) log `("API path refused", shown(path), path.length)`, where `shown(text) = JSON.stringify(text).slice(0, 200)`. Its test `api logs a long refused path quoted, capped and with its length` (`apps/web/src/lib/api.test.ts`) sends `/brands/x#` plus 500 `y`s and checks the log call with `expect.any(String)` and the logged text's length (200), not its content, which the slice 50 task review deferred (findings-slice50 §3). The short-path refusal cases assert `JSON.stringify(path)` exactly, and the `seg` long-value test checks `seg`'s own log line for its length, opening characters (`"a\n`) and escaping, not its full content.

Classification: **bounded** (one existing test, no code change), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decision approved in chat (2026-10-07), after approaches with trade-offs and a recommendation written in a chat message: assert the exact logged text written out as a literal; over recomputing `JSON.stringify(path).slice(0, 200)` in the test (it copies the implementation's expression), or closing the minor as won't-fix.

Design Section 1 (what the test checks) and Section 2 (the edit and its proof) were each shown in chat and approved.

## Design

The test keeps its setup (signed in, a stubbed `fetch`, the path `/brands/x#` + 500 `y`s, `api(path)` rejecting with `NOT_FOUND`) and checks one log call: `("API path refused", `"/brands/x#${"y".repeat(189)}`, path.length)`. The second argument is the opening `"`, `/brands/x#` (10 characters) and 189 `y`s: 200 characters, no closing quote. The separate `toHaveLength(200)` line is removed; the literal fixes the length. No code change.

As a diff against main `b44c2ac` (generated from the proof below):

```diff
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -71,10 +71,9 @@ test("api logs a long refused path quoted, capped and with its length", async ()
   await expect(api(path)).rejects.toThrow("NOT_FOUND");
   expect(log).toHaveBeenCalledWith(
     "API path refused",
-    expect.any(String),
+    `"/brands/x#${"y".repeat(189)}`,
     path.length,
   );
-  expect(log.mock.calls[0][1]).toHaveLength(200);
 });
 
 test("api sends a path with a query string as written", async () => {
```

## Testing

The same test, stronger; web stays at 73 vitest, `api.test.ts` at 23. Expected gates: lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in a fresh scratchpad directory written only by the controller, on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- No red run: main's code already logs the expected text, so the edited test passes on main (`Tests  23 passed (23)`); the change strengthens a passing test.
- Green: typecheck, lint, test (`Tests  73 passed (73)`) and build (`Compiled successfully`) exit 0. The gate's `gen:check` was not run: the copy has no backend. Prettier passes on the changed file.

Mutants of the guard's log line only (`api.ts` otherwise as on main), each run with the old test file and the new one (counts from `api.test.ts`, 23 tests):

| Mutant | Guard's second argument | Old test | New test |
|---|---|---|---|
| M1 | `JSON.stringify(path).slice(-200)` | `23 passed (23)` | `1 failed | 22 passed (23)` (the long-path test) |
| M4 | `JSON.stringify(path.slice(0, 198))` | `23 passed (23)` | `1 failed | 22 passed (23)` (the long-path test) |
| M5 | `JSON.stringify(path.slice(-198))` | `23 passed (23)` | `1 failed | 22 passed (23)` (the long-path test) |
| M2 | `path.slice(0, 200)` | `8 failed | 15 passed (23)` (the short-path refusal cases) | `9 failed | 14 passed (23)` (the same 8 and the long-path test) |
| M3 | `JSON.stringify(path).slice(1, 201)` | `8 failed | 15 passed (23)` (the short-path refusal cases) | `9 failed | 14 passed (23)` (the same 8 and the long-path test) |

M1, M4 and M5 pass the old test and fail the new one; M2 and M3 were already caught (R1). The new test's boundary (R2): a mutant that changes the output only for paths longer than 200 characters in a way that leaves this path's text unchanged, such as dropping the escaping only for long paths, still passes, because the long path holds nothing `JSON.stringify` escapes.

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the proof's evidence is three mutants of the guard's log line that pass the old test and fail the new one: JSON.stringify(path).slice(-200) (M1), JSON.stringify(path.slice(0, 198)) (M4) and JSON.stringify(path.slice(-198)) (M5); Section 2 had also named path.slice(0, 200) (M2) and JSON.stringify(path).slice(1, 201) (M3) as passing the old test, but both already fail it through the short-path refusal cases, and the spec records them as such. Found by: the controller, running the proof. Why: Section 2's claim about M2 and M3 was wrong; the approach is unaffected, since the new literal still catches what the old test missed. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: the spec review's findings are fixed: the Context says the seg long-value test checks the logged text's length, opening characters and escaping, not its full content (Minor 1); the mutation table's M2 and M3 rows say the new count is the 8 short-path cases plus the long-path test (Minor 2); the spec states the reviewer's boundary that only a contrived length-dependent mutant (dropping the escaping only for paths over 200 characters) passes the new test, because the long path holds nothing JSON.stringify escapes; the optional notes that cannot be checked offline are a deferred minor. Found by: the spec reviewer (Opus 5.5, af3e879d99a9f5e90), 2026-10-07. Why: an overstatement and an unclear table row of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the spec review.

## Deferred minors

Quoted from the ledger:

- "minor (deferred): spec review notes, the proof directory being written only by the controller, the chat approvals and the backend count cannot be checked from the repo offline (R2)."

## Live check

None: a test-only change.
