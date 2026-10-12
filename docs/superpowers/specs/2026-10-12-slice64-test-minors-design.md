# Slice 64 design: the four open deferred minors of slice 63

Classification: architectural, said first in chat on 2026-10-12, before the first question: two small test edits and two notes, which the skill would call bounded, but this project gives every slice a spec and a plan ("brainstorm + spec even for small changes"), so the heavier path was taken. Session model Opus 5.5 for the brainstorm, the proof and this spec; implementation and reviews on Opus 5.5 (dispatches omit the `model` param).

## Context

Slice 63 (PRs #126 and #127, main ac26289) closed the last open deferred minors of findings 47 to 61 and recorded five new ones in docs/findings-slice63.md §3. R4 closed the first (line 139, the `redirect` mock reset). Four stay open, lines as at main ac26289:

- docs/findings-slice63.md:140: `encoded()` matches `\b<name>\b` over the whole file, so in a file that interpolates `${q}` any other `q` (a `"q"` string, `sp.q`, an object key) fails the scan.
- docs/findings-slice63.md:141: Step 0's `uv sync` and `npm ci` results were paraphrased, not pasted as the Global Constraints ask.
- docs/findings-slice63.md:142: test_engine_probe.py builds `raw` in the results case too, where it is unused.
- docs/findings-slice63.md:143: the formSeg RAW pattern does not catch a variable key with a cast, `String(form.get(k) as string)`.

The slice changes two test files and adds notes: no product code, no migration, no API change, no spend, no live check.

User decisions (2026-10-12), with the approaches text shown in chat before each choice:
1. Scope: exactly these four, nothing else ("Yes, exactly these four, nothing else"); the R4-closed line 139 stays as it is.
2. 63:140: keep the strictness and close with a won't-fix note (A), over loosening the match to skip string literals and property access (B).
3. 63:142: build `raw` and the expected text inside each branch (A), over a won't-fix note (B).
4. Sections 1 to 3 each approved after their text was shown in chat ("Yes, Section N approved").

## Section 1 — The two code changes (63:142, 63:143)

- 63:142, tests/unit/test_engine_probe.py: in `test_a_rerun_refuses_to_start_while_outputs_exist`, each `left` branch builds its own output and sets `named`, the text the refusal must contain: `results` writes eval/results/engine_probe_v0.json and sets `named = "engine_probe_v0.json"`; `raw` builds `raw = tmp_path / "data" / "experiments" / "engine" / FLASH`, makes it and sets `named = str(raw)`. The comment on the raw case moves into its branch. The trailing `named = … if left == "results" else str(raw)` line goes. The setup, the client guard, both assertions and the parametrize ids are unchanged.
- 63:143, apps/web/src/lib/api-paths.test.ts: the formSeg test's variable-key branch of `RAW` changes from `\bString\([^\n]*?\.get\(\w+\)!?\)` to `\bString\([^\n]*?\.get\(\w+\)(?:!|\s+as\s+string)?\)`, so `String(form.get(k) as string)` is caught as well as `String(form.get(k))` and `String(form.get(k)!)`. Literal id or type keys with `as string` were already caught by the `.get(<key>)` ban. The test comment's "nor String(<x>.get(<variable>))" gains "with or without `!` or `as string`". Today's only variable-key read inside `String(` is reports/actions.ts:48, which goes through `?? ""`, so the scan stays green on main.

## Section 2 — The two notes-only minors (63:140, 63:141) and the docs

In the docs PR after the merge, under the minor lines of docs/findings-slice63.md (as at main ac26289):

- 63:140: `  - Note (2026-10-12, after slice 64, PR #N): won't-fix: the file-wide match is the scan's safety margin; any other appearance of an exempt name fails the scan loudly, naming the file and the name, and renaming the unrelated variable or property clears it; nothing hits it today (docs/findings-slice64.md).`
- 63:141: `  - Note (2026-10-12, after slice 64, PR #N): closed: a process observation about how Task 1's report recorded Step 0; nothing in the repo to change, and Step 2's vitest run and Step 4's typecheck and lint showed the dependencies working.`
- 63:142 and 63:143: "fixed" notes naming the change and the proof mutants.

The docs PR also adds findings-slice64.md (quoting every ledger line), the plan's "Changes made during execution" and README rows. The four notes shift findings-slice63.md's later lines; findings-slice64.md states the minors' new positions.

## Section 3 — Testing

- 63:143, red on main: M1 (`String(form.get(k) as string)` with `const k = "brand_id"`, in place of the first `formSeg(form, "brand_id")` in serp/actions.ts) passes main's scan and fails the patched one. M2 (`String(form.get(k)!)`) and M3 (`String(form.get(k))`) are regression rows, red on both.
- 63:142 is a refactor of a passing test, so it has no red-on-main row. The four probe mutants are run on main's test and the patched test: a wrong raw path (M4), `MODELS[:1]` (M5) and a substituted raw directory (M6) each fail only `[raw]`; a substituted results path (M7) fails only `[results]`. Same outcome on both, which is what a refactor must keep.
- Green, patched: web `npm run gate` exits 0 with 93 vitest (unchanged); backend 1811 passed, 2 deselected, 2 warnings (unchanged), metrics coverage 100.00%, `ruff format --check` (185 files already formatted), `ruff check` and `mypy` clean.
- No live check: nothing is called and no server is started.

## The change

Generated from the proof (a scratchpad copy of main ac26289 with the change applied) with `git diff`, over the two files:

```diff
diff --git a/apps/web/src/lib/api-paths.test.ts b/apps/web/src/lib/api-paths.test.ts
index 450d4d7..726869e 100644
--- a/apps/web/src/lib/api-paths.test.ts
+++ b/apps/web/src/lib/api-paths.test.ts
@@ -103,12 +103,12 @@ test("path values are read with formSeg()", () => {
   // field with .get() at all (FormData, URLSearchParams, Headers or Map
   // alike), whatever the receiver ((await req.formData()).get,
   // this.form.get), the quote style (template literals too) or a trailing
-  // `!` or `as string`; nor String(<x>.get(<variable>)). The leading \b on
-  // String and seg is a precaution: it keeps a future toString(...) line
-  // from matching.
+  // `!` or `as string`; nor String(<x>.get(<variable>)), with or without
+  // `!` or `as string`. The leading \b on String and seg is a precaution:
+  // it keeps a future toString(...) line from matching.
   const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|\x60[a-z_]*_id\x60|"type"|'type'|\x60type\x60)`;
   const RAW = new RegExp(
-    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)!?\)|\bseg\(String\(`,
+    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)(?:!|\s+as\s+string)?\)|\bseg\(String\(`,
     "g",
   );
   const bad = SOURCES.flatMap((f) =>
diff --git a/tests/unit/test_engine_probe.py b/tests/unit/test_engine_probe.py
index 17c1abc..452aeb1 100644
--- a/tests/unit/test_engine_probe.py
+++ b/tests/unit/test_engine_probe.py
@@ -347,13 +347,15 @@ def test_a_rerun_refuses_to_start_while_outputs_exist(
     monkeypatch.chdir(tmp_path)
     results = tmp_path / "eval" / "results"
     results.mkdir(parents=True)
-    # The raw case uses the last model, so main() must pass every model and
-    # <raw_store_dir>/experiments/engine to existing_outputs().
-    raw = tmp_path / "data" / "experiments" / "engine" / FLASH
     if left == "results":
         (results / "engine_probe_v0.json").write_text("{}")
+        named = "engine_probe_v0.json"
     else:
+        # The last model, so main() must pass every model and
+        # <raw_store_dir>/experiments/engine to existing_outputs().
+        raw = tmp_path / "data" / "experiments" / "engine" / FLASH
         raw.mkdir(parents=True)
+        named = str(raw)
     # Present, so a missing refusal reaches the client guard below.
     (tmp_path / "eval" / "run1.json").write_text(
         json.dumps(
@@ -378,6 +380,5 @@ def test_a_rerun_refuses_to_start_while_outputs_exist(
     monkeypatch.setattr(engine_probe.genai, "Client", no_client)
     with pytest.raises(SystemExit) as refused:
         engine_probe.main()
-    named = "engine_probe_v0.json" if left == "results" else str(raw)
     assert named in str(refused.value)
     assert "move them first" in str(refused.value)
```

## Evidence

Proof directory: a fresh scratchpad detached worktree of main ac26289 (`proof64`), written only by the controller through assert-counted replacements. Mutation script `mutate64.py` beside it (slice 63's script with this slice's mutants): for each mutant it applies one replacement, runs api-paths.test.ts (or the probe test file) with the test files at main's version and then as patched, records the failing test names and restores the file. Baselines: main and patched green on both sides.

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 63:143 | serp actions `const k = "brand_id"; const id = String(form.get(k) as string);` | green | red: path values are read with formSeg() |
| M2 | 63:143 | `const k = "brand_id"; const id = String(form.get(k)!);` | red: same test | red: same test |
| M3 | 63:143 | `const k = "brand_id"; const id = String(form.get(k));` | red: same test | red: same test |
| M4 | 63:142 | `main()` raw path `"experiment" / "engine"` | red: [raw] | red: [raw] |
| M5 | 63:142 | `existing_outputs(OUT, raw_dir, MODELS[:1])` | red: [raw] | red: [raw] |
| M6 | 63:142 | `existing_outputs(OUT, Path("nowhere"), MODELS)` | red: [raw] | red: [raw] |
| M7 | 63:142 | `existing_outputs(Path("nowhere"), raw_dir, MODELS)` | red: [results] | red: [results] |

## Departures from the section text shown in chat

- Section 1: the raw-case comment is reworded as it moves (`# The last model, so main() must pass every model and` … in place of `# The raw case uses the last model, so main() must pass every model and` …), since inside the branch the case is implied.
- Section 3: M7 (a substituted results path) was described in chat as "a mutant that makes the refusal message drop the results file name"; the mutant drops the results path from `existing_outputs`, so no refusal happens and the client guard fails `[results]`.

## Out of scope

- docs/findings-slice63.md:139 (closed by R4).
- Loosening `encoded()` (decision 2), any product code, and widening `RAW` beyond the `as string` shape.

## Docs follow-ups

- Dated notes under docs/findings-slice63.md lines 140 to 143 (as at main ac26289) in the docs PR after the merge; README rows for the spec, plan and findings.
