# Slice 63 design: the seven open test minors

Classification: architectural, said first in chat on 2026-10-12, before the first question: every change is to existing tests, which the skill would call bounded, but this project gives every slice a spec and a plan ("brainstorm + spec even for small changes"), so the heavier path was taken. Session model Opus 5.5 for the brainstorm, the approaches, the proof and this spec; implementation and reviews on Opus 5.5 (dispatches omit the `model` param).

## Context

"Fix every item" (user, 2026-10-09) closed 70 of 77 deferred minors in findings 47 to 61 over slices 59 to 62. Seven stayed open, all test work (docs/findings-slice62.md, "Still open"). Lines as at main 7682ffd:

- docs/findings-slice49.md:108: the scan's `QUERIES` allowlist exempts `q`, `dq`, `wq`, `feedQuery` and `apiQuery(sp)` by name, so a raw value later stored in one of them would pass.
- docs/findings-slice49.md:109: the scan reads only `src/app`.
- docs/findings-slice60.md:141: the formSeg scan's receiver is a bare `\w+`, so `(await req.formData()).get`, `this.form.get`, a template-literal key and a trailing `!` are not matched.
- docs/findings-slice60.md:142: `signedIn()` in api.test.ts pins nothing yet.
- docs/findings-slice60.md:143: `audit()` in page.test.tsx defaults to owned 1 / organic 1 with `results: []`.
- docs/findings-slice61.md:103: the refusal test creates only the results file, so `main()` is never tested refusing on a raw directory alone.
- docs/findings-slice61.md:104: no test checks the `raw_dir` wiring in `main()`.

The slice changes four test files and nothing else: no product code, no migration, no API change (no `npm run gen`), no spend, no live check.

User decisions (2026-10-12), with the approaches text shown in chat before each choice:
1. Scope: exactly these seven minors, nothing else ("Yes, exactly these 7, nothing else"), in answer to the understanding note.
2. 49:108: check the declaration (A), over inlining `apiQuery()` into the page templates (B, product code) and a won't-fix note (C).
3. 60:143, first ask: a zero default (A), over one matching result row (B).
4. 60:143, asked again after the proof showed a fact behind decision 3 was wrong (see Correction 1): zero default with the first audit card passing `owned: 1, organic: 1` explicitly (A′), over the one-row default (B).
5. Sections 1 to 4 each approved after their text was shown in chat ("Yes, Section N approved").

Correction 1 (2026-10-12, during the proof): the decision 3 approaches text and the approved Section 2 said both cases that use `audit()` override `owned` and `organic`. Only the failed "reviews" card does; the first card in "each audit gets a card…" passes only `results` and relied on the default 1/1 for "Ownership: 1 of 1 (100%)", which the zero default turned red. The choice was asked again (decision 4) and Section 2 below carries the answer.

## Section 1 — Web scans (49:108, 49:109, 60:141)

File: apps/web/src/lib/api-paths.test.ts.

- 49:109, scope: both scans read every non-test `.ts`/`.tsx` file under `src/` (one shared `SOURCES` list), not only `src/app`. That adds `src/lib/*` (api.ts, format.ts, cookie.ts, types.ts, schema.d.ts), `src/middleware.ts` and `src/components/*`. The call and path patterns gain a `(?<!function )` lookbehind so api.ts's own `function api<T>(path` and `function publicApi<T>(path` are not read as calls; the comment lines that mention `api()` are already skipped by the existing comment filter. The `templates >= 40` floor stays. Widening the formSeg scan is a side effect of the shared list, not a new minor; server actions live only in `src/app` today, so it changes nothing now.
- 49:108, declaration check: `QUERIES` becomes a `Map` from each exempt name to the declarations it needs. A `${name}` in an API path passes only when that file assigns each needed name exactly once, and that once is `const <name> = <from>`: `q`, `dq` and `wq` from `apiQuery(`; `feedQuery` from `` `${fq}`` `` and `fq` from `apiQuery(`. A `let`/`var` declaration, a reassignment or a compound assignment anywhere in the file counts against it. Inline `${apiQuery(sp)}` stays exempt as the encoder call itself. A failure reads `<file>: <name> is not assigned once from apiQuery()`. Ceiling: it is a regex scan; a destructuring assignment (`({ q } = x)`) is not counted, and an unrelated `q=` in the same file (a `"?q=..."` literal) fails safe.
- 60:141, receiver-agnostic formSeg scan: the pattern no longer depends on the receiver. It flags any `.get(<key>)` whose key is an `_id` or `type` name in `"…"`, `'…'` or `` `…` `` quotes (with or without a trailing `!` or `as string`, which this subsumes), a variable key inside `String(…)` on one line (`String(` … `.get(\w+)` with an optional `!`, then `)`), and `seg(String(`. `String` and `seg` get a leading `\b` so `toString(` in format.ts is not read as `String(`. Today's code has no `.get(` with an id or type key, and its variable-key reads all go through `?? ""` (body values, not path values), so the scan is green on main.

## Section 2 — `api()` auth and the audit fixture (60:142, 60:143)

- 60:142, apps/web/src/lib/api.test.ts, two new tests:
  1. "api sends the cookie's key as a Bearer token": `signedIn()`, a 200 fetch stub, `api("/brands/x")`; fetch's `init.headers` equals `{ Authorization: "Bearer bsi_key_1" }` and `init.cache` is `"no-store"`.
  2. "api with no key cookie redirects to /login without calling the API": `cookies()` answers only for a name other than `COOKIE`; `redirect` throws once (`mockImplementationOnce`; Next's real `redirect` throws, the module mock is a silent `vi.fn()`); `api()` rejects, `redirect` was called with `"/login"`, and fetch was never called.
  The proof shows what main's suite already caught: page.test.tsx's `render()` checks fetch received the cookie's key, so a wrong cookie name (M13) and a wrong scheme (M15) were already red on main. What the two tests add is a pin in api.test.ts itself plus the two mutants main missed: a dropped key check (M14) and a changed cache mode (M16).
- 60:143, apps/web/src/app/(app)/b/[id]/serp/page.test.tsx (decision 4): `audit()` defaults to `owned: 0, organic: 0, results: []`, a real state (an audit with no organic results), and the first card in "each audit gets a card…" passes `owned: 1, organic: 1` beside the two rows they describe. The page cases stay at 7, all green. This is a fixture-consistency fix, not a behaviour pin: the old 1/1 default restored on the patched file (M20) leaves every test green, as expected.

## Section 3 — Engine probe refusal (61:103, 61:104)

File: tests/unit/test_engine_probe.py. `test_a_rerun_refuses_to_start_while_outputs_exist` is parametrized over which output exists, the setup otherwise unchanged (settings stub, ledger at `LEDGER_FLOOR`, `db_micros` 0, `run1.json` present, the `genai.Client` guard):

1. `results`: only eval/results/engine_probe_v0.json exists; the message names `engine_probe_v0.json` and contains "move them first" (today's assertions).
2. `raw`: only `<tmp>/data/experiments/engine/gemini-3.8-flash/` exists; the message names that full path and contains "move them first".

Case 2 closes 61:103 and pins 61:104: a wrong raw path in `main()` finds nothing, the client gets built and the guard fails the test; and because the case uses the last model (`FLASH`), `main()` passing a cut-down model list (`MODELS[:1]`) fails too.

## Section 4 — Testing

- Red on main: each mutant is run against main's versions of the four test files and against the patched ones. 16 of the 19 code mutants pass main's tests and fail the patched ones; M12 (the original `String(form.get("brand_id"))` shape) and M13/M15 (see Section 2) were already red on main and stay red. M20 is test-side and survives, as Section 2 says.
- Green, patched: web `npm run gate` exits 0 with 93 vitest (91 + the two api.test.ts tests); backend 1811 passed (1810 + the parametrized case), 2 deselected, 2 warnings, metrics coverage 100.00%, `ruff format --check` (185 files already formatted), `ruff check` and `mypy` clean.
- No live check: nothing is called and no server is started.

## The change

Generated from the proof (a scratchpad copy of main 7682ffd with the change applied) with `git diff`, over the four files:

```diff
diff --git a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
index a6fe003..32b083c 100644
--- a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
@@ -60,8 +60,8 @@ const audit = (over: Partial<Audit> = {}): Audit => ({
   fetched_at: "2026-10-11T09:30:00Z",
   cost_micros: 4000,
   error: null,
-  owned: 1,
-  organic: 1,
+  owned: 0,
+  organic: 0,
   results: [],
   ...over,
 });
@@ -176,6 +176,8 @@ test("each audit gets a card: ownership, panels, the results, or the error", asy
       budget_room: true,
       audits: [
         audit({
+          owned: 1,
+          organic: 1,
           results: [
             {
               position: 1,
diff --git a/apps/web/src/lib/api-paths.test.ts b/apps/web/src/lib/api-paths.test.ts
index 1ba73b0..2bdb2fc 100644
--- a/apps/web/src/lib/api-paths.test.ts
+++ b/apps/web/src/lib/api-paths.test.ts
@@ -2,13 +2,31 @@ import { readdirSync, readFileSync } from "node:fs";
 import { join } from "node:path";
 import { expect, test } from "vitest";
 
-// Query strings built by URLSearchParams, which encodes them already.
-const QUERIES = new Set(["q", "dq", "wq", "feedQuery", "apiQuery(sp)"]);
-const APP = join(__dirname, "..", "app");
-const CALL = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
+// Query strings built by apiQuery(), which encodes them with URLSearchParams.
+// A name passes only where its file assigns it once, as `const <name> =
+// <from>` (feedQuery from fq, which comes from apiQuery()); apiQuery(sp)
+// inline is the encoder itself.
+const QUERIES = new Map<string, [string, string][]>([
+  ["q", [["q", "apiQuery("]]],
+  ["dq", [["dq", "apiQuery("]]],
+  ["wq", [["wq", "apiQuery("]]],
+  [
+    "feedQuery",
+    [
+      ["feedQuery", "`${fq}"],
+      ["fq", "apiQuery("],
+    ],
+  ],
+]);
+const SRC = join(__dirname, "..");
+const SOURCES = readdirSync(SRC, { recursive: true, encoding: "utf8" }).filter(
+  (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
+);
+// api.ts's own `function api<T>(path` is a definition, not a call.
+const CALL = /(?<!function )\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
 // The whole first argument is one literal, followed by "," or ")".
 const LITERAL = /^(`[^`]*`|"[^"]*"|'[^']*')\s*[,)]/;
-const PATH = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;
+const PATH = /(?<!function )\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;
 
 /** True for exactly one seg(...) call: its "(" closes at the last character. */
 const isSeg = (expr: string) => {
@@ -22,14 +40,25 @@ const isSeg = (expr: string) => {
   return false;
 };
 
-test("every value in an API path goes through seg()", () => {
-  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
-    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
+/** True when code assigns name exactly once, and that once is
+ * `const <name> = <from>`: a let/var, a reassignment or a compound
+ * assignment anywhere in the file counts against it. */
+const assignedOnce = (code: string, name: string, from: string) => {
+  const writes = new RegExp(
+    String.raw`\b(?:let|var)\s+${name}\b|\b${name}\s*(?:[-+*/%&|^]|\?\?|&&|\|\|)?=(?![=>])`,
+    "g",
   );
+  return (
+    [...code.matchAll(writes)].length === 1 &&
+    code.split(`const ${name} = ${from}`).length === 2
+  );
+};
+
+test("every value in an API path goes through seg()", () => {
   const bad: string[] = [];
   let templates = 0;
-  for (const f of files) {
-    const code = readFileSync(join(APP, f), "utf8")
+  for (const f of SOURCES) {
+    const code = readFileSync(join(SRC, f), "utf8")
       .split("\n")
       .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
       .join("\n");
@@ -41,7 +70,12 @@ test("every value in an API path goes through seg()", () => {
     for (const [, path] of code.matchAll(PATH)) {
       templates += 1;
       for (const [, expr] of path.matchAll(/\$\{([^}]*)\}/g)) {
-        if (!isSeg(expr) && !QUERIES.has(expr)) bad.push(`${f}: \${${expr}}`);
+        if (isSeg(expr) || expr === "apiQuery(sp)") continue;
+        const needs = QUERIES.get(expr);
+        if (!needs) bad.push(`${f}: \${${expr}}`);
+        else if (!needs.every(([n, from]) => assignedOnce(code, n, from))) {
+          bad.push(`${f}: ${expr} is not assigned once from apiQuery()`);
+        }
       }
     }
   }
@@ -51,19 +85,18 @@ test("every value in an API path goes through seg()", () => {
 
 test("server actions read path values with formSeg()", () => {
   // String(form.get(...)) turns a missing field into "null", which seg()
-  // passes; formSeg() refuses it. A field named by a variable
-  // (String(form.get(k))) is caught too: label's actions read ids that way.
-  // Any receiver name, either quote style, and the `as string` cast count.
-  const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|"type"|'type')`;
+  // passes; formSeg() refuses it. No code reads an id or type field with
+  // .get() at all, whatever the receiver ((await req.formData()).get,
+  // this.form.get), the quote style (template literals too) or a trailing
+  // `!` or `as string`. A field named by a variable inside String(...) is
+  // caught too: label's actions read ids that way.
+  const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|\x60[a-z_]*_id\x60|"type"|'type'|\x60type\x60)`;
   const RAW = new RegExp(
-    String.raw`String\(\w+\.get\(${ID}\)\)|String\(\w+\.get\(\w+\)\)|seg\(String\(|\w+\.get\(${ID}\)\s+as\s+string`,
+    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)!?\)|\bseg\(String\(`,
     "g",
   );
-  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
-    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
-  );
-  const bad = files.flatMap((f) =>
-    [...readFileSync(join(APP, f), "utf8").matchAll(RAW)].map(
+  const bad = SOURCES.flatMap((f) =>
+    [...readFileSync(join(SRC, f), "utf8").matchAll(RAW)].map(
       (m) => `${f}: ${m[0]}`,
     ),
   );
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
index a5a11db..197c27f 100644
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -11,6 +11,7 @@ vi.mock("next/navigation", () => ({
 
 const { api, COOKIE, formSeg, publicApi, seg } = await import("./api");
 const { cookies } = await import("next/headers");
+const { redirect } = await import("next/navigation");
 
 const stub = (status: number) =>
   vi.stubGlobal(
@@ -96,6 +97,35 @@ test("api sends a path with a query string as written", async () => {
   );
 });
 
+test("api sends the cookie's key as a Bearer token", async () => {
+  signedIn();
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 200 })),
+  );
+  await api("/brands/x");
+  const init = vi.mocked(fetch).mock.calls[0][1];
+  expect(init?.headers).toEqual({ Authorization: "Bearer bsi_key_1" });
+  expect(init?.cache).toBe("no-store");
+});
+
+test("api with no key cookie redirects to /login without calling the API", async () => {
+  // A cookie under another name only: api() must read COOKIE, not any.
+  vi.mocked(cookies).mockResolvedValue({
+    get: (name: string) =>
+      name === COOKIE ? undefined : { value: "bsi_key_1" },
+  } as never);
+  // Next's redirect() throws; the module mock is a silent vi.fn().
+  vi.mocked(redirect).mockImplementationOnce(() => {
+    throw new Error("REDIRECT");
+  });
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  await expect(api("/brands/x")).rejects.toThrow("REDIRECT");
+  expect(redirect).toHaveBeenCalledWith("/login");
+  expect(fetchMock).not.toHaveBeenCalled();
+});
+
 test("publicApi refuses a dot segment", async () => {
   const log = vi.spyOn(console, "error").mockImplementation(() => {});
   const fetchMock = vi.fn();
diff --git a/tests/unit/test_engine_probe.py b/tests/unit/test_engine_probe.py
index fe583e9..17c1abc 100644
--- a/tests/unit/test_engine_probe.py
+++ b/tests/unit/test_engine_probe.py
@@ -340,11 +340,20 @@ def test_existing_outputs_names_what_a_rerun_would_overwrite(tmp_path):
     ]
 
 
-def test_a_rerun_refuses_to_start_while_outputs_exist(tmp_path, monkeypatch):
+@pytest.mark.parametrize("left", ["results", "raw"])
+def test_a_rerun_refuses_to_start_while_outputs_exist(
+    tmp_path, monkeypatch, left
+):
     monkeypatch.chdir(tmp_path)
     results = tmp_path / "eval" / "results"
     results.mkdir(parents=True)
-    (results / "engine_probe_v0.json").write_text("{}")
+    # The raw case uses the last model, so main() must pass every model and
+    # <raw_store_dir>/experiments/engine to existing_outputs().
+    raw = tmp_path / "data" / "experiments" / "engine" / FLASH
+    if left == "results":
+        (results / "engine_probe_v0.json").write_text("{}")
+    else:
+        raw.mkdir(parents=True)
     # Present, so a missing refusal reaches the client guard below.
     (tmp_path / "eval" / "run1.json").write_text(
         json.dumps(
@@ -369,5 +378,6 @@ def test_a_rerun_refuses_to_start_while_outputs_exist(tmp_path, monkeypatch):
     monkeypatch.setattr(engine_probe.genai, "Client", no_client)
     with pytest.raises(SystemExit) as refused:
         engine_probe.main()
-    assert "engine_probe_v0.json" in str(refused.value)
+    named = "engine_probe_v0.json" if left == "results" else str(raw)
+    assert named in str(refused.value)
     assert "move them first" in str(refused.value)
```

## Evidence

Proof directory: a fresh scratchpad detached worktree of main 7682ffd (`proof63`), written only by the controller through assert-counted replacements (`api-paths.test.ts` written whole). Mutation script `mutate63.py` beside it: for each mutant it applies one replacement, runs the three web test files (or the probe test file) with the test files at main's version and then as patched, records the failing test names and restores the file.

Baselines: web main and patched green; probe tests main and patched green (21 patched).

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 49:108 | competitors `const q = String(sp.q ?? "")` | green | red: every value in an API path goes through seg() |
| M2 | 49:108 | overview `let q = apiQuery(sp)` then `q = String(sp.raw)` | green | red: same test |
| M3 | 49:108 | competitors `const fq = String(sp.date_from ?? "")` (reaches `feedQuery`) | green | red: same test |
| M4 | 49:108 | competitors `const wq = String(sp.days ?? "") \|\| apiQuery(` | green | red: same test |
| M5 | 49:109 | format.ts gains ``api(`/brands/${raw}`)`` | green | red: same test |
| M6 | 49:109 | components/RivalPages.tsx gains `publicApi(p)` | green | red: same test |
| M7 | 60:141 | serp actions `String((await req.formData()).get("brand_id"))` | green | red: server actions read path values with formSeg() |
| M8 | 60:141 | `String(this.form.get("brand_id"))` | green | red: same test |
| M9 | 60:141 | ``String(form.get(`brand_id`))`` | green | red: same test |
| M10 | 60:141 | `String(form.get("brand_id")!)` | green | red: same test |
| M11 | 60:141 | `const k = "brand_id"; String(form.get(k)!)` | green | red: same test |
| M12 | 60:141 | `String(form.get("brand_id"))` (the shape main already catches) | red: same test | red: same test |
| M13 | 60:142 | api.ts reads cookie `"session"` | red: the 7 serp page cases | red: the 7 serp page cases and both new api tests |
| M14 | 60:142 | api.ts drops `if (!key) redirect("/login")` | green | red: api with no key cookie redirects to /login without calling the API |
| M15 | 60:142 | api.ts sends `Token ${key}` | red: the 7 serp page cases | red: the 7 serp page cases and api sends the cookie's key as a Bearer token |
| M16 | 60:142 | api.ts `cache: "force-cache"` | green | red: api sends the cookie's key as a Bearer token |
| M17 | 61:103/104 | `main()` raw path `"experiment" / "engine"` | green | red: test_a_rerun_refuses_to_start_while_outputs_exist[raw] |
| M18 | 61:103/104 | `existing_outputs(OUT, raw_dir, MODELS[:1])` | green | red: same, [raw] |
| M19 | 61:103/104 | `existing_outputs(OUT, Path("nowhere"), MODELS)` | green | red: same, [raw] |
| M20 | 60:143 | the patched page test's default back to owned 1 / organic 1 | not run | green (expected: not a pin) |

## Departures from the section text shown in chat

- Section 1: the leading `\b` on `String(` and `seg(` was not in the chat text; it keeps `toString(` from being read as `String(` now that the scan reads format.ts.
- Section 1: the scan's file list is hoisted to one module-level `SOURCES` constant shared by both tests (the chat text said "one file list" without naming where it lives).
- Section 2: test 1 asserts the whole `init.headers` object equals `{ Authorization: "Bearer bsi_key_1" }`, stricter than the chat text's "Authorization equals".
- Section 2: the 60:143 change follows decision 4 (Correction 1), not the approved text's "their assertions stay as they are".

## Out of scope

- The "2 warnings" (a dependency upgrade).
- Any product code change, and widening the scans beyond what the seven minors name.

## Docs follow-ups

- Dated notes under findings-slice49.md lines 108 and 109, findings-slice60.md lines 141, 142 and 143, and findings-slice61.md lines 103 and 104 (as at main 7682ffd), and one under findings-slice62.md's "Still open" paragraph, in the docs PR after the merge; README rows for the spec, plan and findings.
