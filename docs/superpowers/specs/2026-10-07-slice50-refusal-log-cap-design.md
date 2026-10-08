# Slice 50 design: the refusal log lines are quoted, capped and give the length

## Context

Codebase facts: main `be011d5`, checked 2026-10-07.

Slice 49 added two refusal log lines to `apps/web/src/lib/api.ts`: `sendAsWritten` logs `console.error("API path refused", path)` and `seg` logs `console.error("API path value refused", value)`. Both print the raw value with no length cap, which the slice 49 final review deferred (findings-slice49 §3, R11). A hidden form field can carry a very long string or raw control characters such as a newline (route params reach the page still percent-encoded, per the slice 49 spec's Context, so a newline there shows as `%0A`), so one refusal can write a very long log entry or split into several lines. Two parameterised tests (15 cases) assert those calls with the raw value (`api.test.ts`, the guard refusal cases and the `seg` refusal cases). The third log line in `api()` (`"API problem"`) is out of scope: it logs a path the guard has already passed.

Classification: **bounded** (two log lines and their tests), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. Log the value JSON-quoted and capped at 200 characters, plus its full length; over logging the length only, or closing the minor as won't-fix.
2. After the spec review showed the guard's own cap was untested: add a long-path guard test; over stating it as untested.

Design Section 1 (what is logged) and Section 2 (code and tests) were each shown in chat and approved.

## Design

A helper `shown(text)` returns `JSON.stringify(text).slice(0, 200)`: the text in double quotes with `\`, `"` and the C0 control characters (U+0000 to U+001F, newlines among them) escaped, so a refusal is one line in a plain terminal, and at most 200 UTF-16 code units (a cut can end inside an escape or split a surrogate pair; the length beside it shows the text was cut). `JSON.stringify` leaves U+007F, U+0085, U+2028 and U+2029 unescaped; some log viewers treat the last three as line breaks. The two lines become `console.error("API path refused", shown(path), path.length)` and `console.error("API path value refused", shown(value), value.length)`. For example `seg("a/b")` logs `API path value refused "a/b" 3`.

Unchanged: what is refused, the `notFound()` that follows, and the `"API problem"` log.

As a diff against main `be011d5` (generated from the proof below):

```diff
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -56,7 +56,25 @@ test.each([
   vi.stubGlobal("fetch", fetchMock);
   await expect(api(path)).rejects.toThrow("NOT_FOUND");
   expect(fetchMock).not.toHaveBeenCalled();
-  expect(log).toHaveBeenCalledWith("API path refused", path);
+  expect(log).toHaveBeenCalledWith(
+    "API path refused",
+    JSON.stringify(path),
+    path.length,
+  );
+});
+
+test("api logs a long refused path quoted, capped and with its length", async () => {
+  signedIn();
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  vi.stubGlobal("fetch", vi.fn());
+  const path = `/brands/x#${"y".repeat(500)}`;
+  await expect(api(path)).rejects.toThrow("NOT_FOUND");
+  expect(log).toHaveBeenCalledWith(
+    "API path refused",
+    expect.any(String),
+    path.length,
+  );
+  expect(log.mock.calls[0][1]).toHaveLength(200);
 });
 
 test("api sends a path with a query string as written", async () => {
@@ -95,6 +113,25 @@ test.each(["", "..", "a/b", "a%2Fb", "a?b", "a#b", "a b"])(
   (value) => {
     const log = vi.spyOn(console, "error").mockImplementation(() => {});
     expect(() => seg(value)).toThrow("NOT_FOUND");
-    expect(log).toHaveBeenCalledWith("API path value refused", value);
+    expect(log).toHaveBeenCalledWith(
+      "API path value refused",
+      JSON.stringify(value),
+      value.length,
+    );
   },
 );
+
+test("seg logs a long value quoted, capped and with its length", () => {
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  const value = `a\n${"b".repeat(500)}`;
+  expect(() => seg(value)).toThrow("NOT_FOUND");
+  expect(log).toHaveBeenCalledWith(
+    "API path value refused",
+    expect.any(String),
+    502,
+  );
+  const logged = log.mock.calls[0][1] as string;
+  expect(logged).toHaveLength(200);
+  expect(logged.startsWith('"a\\n')).toBe(true);
+  expect(logged).not.toContain("\n");
+});
diff --git a/apps/web/src/lib/api.ts b/apps/web/src/lib/api.ts
--- a/apps/web/src/lib/api.ts
+++ b/apps/web/src/lib/api.ts
@@ -6,6 +6,10 @@ import { COOKIE } from "./cookie";
 export const API_URL = process.env.API_URL ?? "http://localhost:8000";
 export { COOKIE };
 
+/** A refused value for the log: quoted (C0 control characters escaped), at
+ * most 200 UTF-16 code units. */
+const shown = (text: string) => JSON.stringify(text).slice(0, 200);
+
 // ponytail: a backstop for anything a call site misses. It refuses dot
 // segments in any spelling, '\', '#' and anything the URL parser would
 // re-encode; a '/', '%2F' or '?' inside a value passes it, and seg() at each
@@ -13,14 +17,14 @@ export { COOKIE };
 function sendAsWritten(path: string) {
   const u = new URL(path, "http://api.invalid");
   if (u.pathname + u.search === path) return;
-  console.error("API path refused", path);
+  console.error("API path refused", shown(path), path.length);
   notFound();
 }
 
 /** One path segment from a route param, form field or API value. */
 export function seg(value: string): string {
   if (/^[A-Za-z0-9_-]+$/.test(value)) return value;
-  console.error("API path value refused", value);
+  console.error("API path value refused", shown(value), value.length);
   notFound();
 }
 
```

## Testing

In `apps/web/src/lib/api.test.ts` (the diff above):
- The guard refusal cases assert `("API path refused", JSON.stringify(path), path.length)`; the `seg` refusal cases assert `("API path value refused", JSON.stringify(value), value.length)` (every test value is short, so nothing is cut).
- New `api logs a long refused path quoted, capped and with its length`: for `/brands/x#` followed by 500 `y`s, signed in, `api(path)` rejects with `NOT_FOUND`, the log call is `("API path refused", <logged>, path.length)`, and `<logged>` is 200 characters long.
- New `seg logs a long value quoted, capped and with its length`: for `"a\n"` followed by 500 `b`s, `seg` throws `NOT_FOUND`, the log call is `("API path value refused", <logged>, 502)`, and `<logged>` is 200 characters long, starts with `"a\n` (the newline escaped) and contains no newline.

Expected gates: web 73 vitest (71 on main plus 2), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked; rebuilt after the spec review in a fresh directory (R2).

- Red, main's code with the new tests: `Tests  17 failed | 6 passed (23)` in `api.test.ts`: the 8 guard refusal cases, the 7 `seg` refusal cases and the two new tests.
- Green, patched: `Tests  23 passed (23)`; typecheck, lint, test (`Tests  73 passed (73)`) and build (`Compiled successfully`) exit 0, with no refusal line in the output. The gate's `gen:check` was not run: the copy has no backend. No API file changes.
- Prettier is not in the gate; both changed files pass `prettier --check`.

Each change below fails tests (counts from `api.test.ts`, 23 tests):

| Mutant | Change | Result | Failing |
|---|---|---|---|
| M1 | no cap | `2 failed \| 21 passed (23)` | the two long-value tests |
| M2 | no quoting (the raw text, capped) | `16 failed \| 7 passed (23)` | the 8 guard and 7 `seg` refusal cases, and `seg logs a long value…` |
| M3 | no length in `seg`'s log | `8 failed \| 15 passed (23)` | the 7 `seg` refusal cases and `seg logs a long value…` |
| M4 | no length in the guard's log | `9 failed \| 14 passed (23)` | the 8 guard refusal cases and `api logs a long refused path…` |
| M5 | a cap of 2,000 | `2 failed \| 21 passed (23)` | the two long-value tests |
| M6 | the guard's log quoted but uncapped | `1 failed \| 22 passed (23)` | `api logs a long refused path quoted, capped and with its length` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the spec review's wording findings are fixed: "always one line" becomes "C0 control characters escaped" in the spec and in the shown() comment, which also says "200 UTF-16 code units", and the spec states that U+2028, U+2029, NEL and DEL stay unescaped and a cut can split a surrogate pair (Minors 1 and 3); the route-param encoding claim cites slice 49's observation on Next 15.5.25 (findings-slice49 §1) (Minor 4); "two tests" becomes "two parameterised tests (15 cases)" (Minor 6); Minor 5 (chat approvals and the backend count cannot be checked offline) is left. Found by: the spec reviewer (Opus 5.5, abaf5a03f31a8dfdb), 2026-10-07. Why: overstated or loose statements of mine, one in a code comment. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R2. Decided: the proof was rebuilt in a fresh scratch directory (s50b) from main plus the spec's diff plus the new guard test, and red, the six mutants and the gate steps were re-run there; the first proof directory (s50) is not used again. Found by: the controller, after the spec review: the reviewer worked in s50 (its own report says so), and afterwards s50 had no git history, the api50.green snapshot was gone and two unknown files (orig.ts, spec.diff) were present. Why: a proof must come from a directory only the controller has written. Cost if wrong: none; s50b's api.ts matched s50's byte for byte before the comment change. How named: in chat, 2026-10-07, after the rebuild.

> Correction to R1 (2026-10-07, from the controller's check before the spec edit): the route-param encoding claim is recorded in the slice 49 spec's Context ("Next passes route params to the page still percent-encoded"), not in findings-slice49 §1, and it names no Next version; the spec cites that.

Rulings made after this spec was approved (R3 and R4 added by the first post-merge docs commit, R5 and R6 by the docs-review fix commits), quoted from the ledger:

> Ruling: R3. Decided: the plan review's three minors need no change: Step 1's first block opens the new guard test and the file's existing "});" closes it, which applies exactly (Minor 1); the "byte-identical to the proof" claim could not be checked by the reviewer, who was kept out of the scratchpad, but it confirmed the plan gives the spec's diff (Minor 2); the one placeholder is defined (Minor 3). No re-review: the plan is unchanged. Found by: the plan reviewer (Opus 5.5, ab86501954b7a3d30), 2026-10-07. Why: no statement is wrong. Cost if wrong: an implementer might pause on the open block; the brief's exact blocks still apply. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R4. Decided: no final fix wave. Minor 1 (the api long-path test checks the length, not the content) is the already deferred Task 1 minor; Minor 2 (the plan's "Changes made during execution" still says "None yet.") is done by the post-merge docs commit, as in every slice. Found by: the final reviewer (Opus 5.5, abdfc26968fa43d67), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and both deferred minors triaged "does not need fixing before merge". Cost if wrong: a wrong slice offset in the guard's log alone would go unnoticed by the tests. How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R5. Decided: the docs review's findings are fixed: the findings and the plan quote the ledger's Note correcting "/tmp/null was empty" right after the spec re-review line (Important 1); the plan's sub-list heading becomes "Execution, gates and CI, as the ledger records them" (Minor 1); the findings say R1, R2 and the Correction to R1 entered in 7261182, "the version the user approved" (Minor 2). Found by: the docs reviewer (Opus 5.5, a6462c0907b1bf8e2), 2026-10-07. Why: a quoted statement the ledger marks as wrong, and two inexact phrasings of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

> Ruling: R6. Decided: the docs re-review's three minors are fixed: the findings credit R3 and R4 to the first post-merge docs commit and R5 and R6 to the docs-review fix commits (Minor 1); the spec says the second deferred minor was added by the first post-merge docs commit, 7a5a214 (Minor 2); the findings' and the plan's reviews lists quote the docs review and re-review lines (Minor 3); no further review, as the user chose "Fix, stop" when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5, a7148395d07f8da65), 2026-10-07. Why: incomplete or ambiguous statements of mine. Cost if wrong: none to behaviour; the fix commit is unreviewed. How named: in chat, 2026-10-07, before the fix commit.

## Deferred minors

Every deferred minor, quoted from the ledger (the second added by the first post-merge docs commit, `7a5a214`):

- "minor (deferred): spec review minor 5, the chat approvals and the backend count "1753 passed, 2 deselected" cannot be checked from the repo offline (R1)."
- "Task 1: minor (deferred): the api long-path test checks the logged text's length (200) but not its content, so a wrong slice offset in the guard's log alone would pass; the seg long-value test checks the content through the shared shown() (plan-mandated)."

## Live check

None: the change is two log lines, driven by the tests with a spied `console.error`.
