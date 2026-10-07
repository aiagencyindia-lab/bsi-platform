# Slice 50 design: the refusal log lines are quoted, capped and give the length

## Context

Codebase facts: main `be011d5`, checked 2026-10-07.

Slice 49 added two refusal log lines to `apps/web/src/lib/api.ts`: `sendAsWritten` logs `console.error("API path refused", path)` and `seg` logs `console.error("API path value refused", value)`. Both print the raw value with no length cap, which the slice 49 final review deferred (findings-slice49 §3, R11). A hidden form field can carry a very long string or raw control characters such as a newline (route params arrive percent-encoded, so a newline there shows as `%0A`), so one refusal can write a very long log entry or split into several lines. Two tests assert those calls with the raw value (`api.test.ts`, the guard refusal cases and the `seg` refusal cases). The third log line in `api()` (`"API problem"`) is out of scope: it logs a path the guard has already passed.

Classification: **bounded** (two log lines and their tests), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decision approved in chat (2026-10-07), after approaches with trade-offs and a recommendation written in a chat message: log the value JSON-quoted and capped at 200 characters, plus its full length; over logging the length only, or closing the minor as won't-fix.

Design Section 1 (what is logged) and Section 2 (code and tests) were each shown in chat and approved.

## Design

A helper `shown(text)` returns `JSON.stringify(text).slice(0, 200)`: the text in double quotes with `\`, `"`, newlines and other control characters escaped, so a refusal is always one line, and at most 200 characters (a cut can end inside an escape; the length beside it shows the text was cut). The two lines become `console.error("API path refused", shown(path), path.length)` and `console.error("API path value refused", shown(value), value.length)`. For example `seg("a/b")` logs `API path value refused "a/b" 3`.

Unchanged: what is refused, the `notFound()` that follows, and the `"API problem"` log.

As a diff against main `be011d5` (generated from the proof below):

```diff
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -56,7 +56,11 @@ test.each([
   vi.stubGlobal("fetch", fetchMock);
   await expect(api(path)).rejects.toThrow("NOT_FOUND");
   expect(fetchMock).not.toHaveBeenCalled();
-  expect(log).toHaveBeenCalledWith("API path refused", path);
+  expect(log).toHaveBeenCalledWith(
+    "API path refused",
+    JSON.stringify(path),
+    path.length,
+  );
 });
 
 test("api sends a path with a query string as written", async () => {
@@ -95,6 +99,25 @@ test.each(["", "..", "a/b", "a%2Fb", "a?b", "a#b", "a b"])(
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
@@ -6,6 +6,9 @@ import { COOKIE } from "./cookie";
 export const API_URL = process.env.API_URL ?? "http://localhost:8000";
 export { COOKIE };
 
+/** A refused value for the log: quoted (one line), at most 200 characters. */
+const shown = (text: string) => JSON.stringify(text).slice(0, 200);
+
 // ponytail: a backstop for anything a call site misses. It refuses dot
 // segments in any spelling, '\', '#' and anything the URL parser would
 // re-encode; a '/', '%2F' or '?' inside a value passes it, and seg() at each
@@ -13,14 +16,14 @@ export { COOKIE };
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
- New `seg logs a long value quoted, capped and with its length`: for `"a\n"` followed by 500 `b`s, `seg` throws `NOT_FOUND`, the log call is `("API path value refused", <logged>, 502)`, and `<logged>` is 200 characters long, starts with `"a\n` (the newline escaped) and contains no newline.

Expected gates: web 72 vitest (71 on main plus 1), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the new tests: `Tests  16 failed | 6 passed (22)` in `api.test.ts`: the 8 guard refusal cases, the 7 `seg` refusal cases and the new test.
- Green, patched: `Tests  22 passed (22)`; typecheck, lint, test (`Tests  72 passed (72)`) and build (`Compiled successfully`) exit 0, with no refusal line in the output. The gate's `gen:check` was not run: the copy has no backend. No API file changes.
- Prettier is not in the gate; both changed files pass `prettier --check`.

Each change below fails tests (counts from `api.test.ts`, 22 tests):

| Mutant | Change | Result | Failing |
|---|---|---|---|
| M1 | no cap | `1 failed | 21 passed (22)` | `seg logs a long value quoted, capped and with its length` |
| M2 | no quoting (the raw text, capped) | `16 failed | 6 passed (22)` | the 8 guard and 7 `seg` refusal cases, and the new test |
| M3 | no length in `seg`'s log | `8 failed | 14 passed (22)` | the 7 `seg` refusal cases and the new test |
| M4 | no length in the guard's log | `8 failed | 14 passed (22)` | the 8 guard refusal cases |
| M5 | a cap of 2,000 | `1 failed | 21 passed (22)` | `seg logs a long value quoted, capped and with its length` |

## Rulings

None yet.

## Deferred minors

None yet.

## Live check

None: the change is two log lines, driven by the tests with a spied `console.error`.
