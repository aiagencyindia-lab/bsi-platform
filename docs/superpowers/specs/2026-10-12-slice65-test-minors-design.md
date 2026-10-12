# Slice 65 design: the two open deferred minors of slice 64

Classification: architectural, said first in chat on 2026-10-12, before the first question: two one-line test edits, which the skill would call bounded, but this project gives every slice a spec and a plan ("brainstorm + spec even for small changes"), so the heavier path was taken. Session model: the brainstorm began on Opus 5.5 and the session switched to Fable 5.1 (the user's `/model claude-fable-5-1`) before the first design question; the proof and this spec are Fable 5.1's, with the Fable 5.1 commit trailer. Implementation and reviews run on Opus 5.5 (every dispatch passes `model: opus`).

## Context

Slice 64 (PRs #128 and #129, main a456260) closed the four open deferred minors of slice 63 and recorded three new ones in docs/findings-slice64.md §3. Line 101 (a stray `/tmp/null`) is already closed. Two stay open, lines as at main a456260:

- docs/findings-slice64.md:102: the RAW variable-key branch allows `!` or `as string` but not both, so `String(x.get(k)! as string)` is not matched.
- docs/findings-slice64.md:103: in the results case the expected text is the bare file name `engine_probe_v0.json`, so the assert passes whatever directory the refusal names.

The slice changes two test files, one line each plus a comment phrase: no product code, no migration, no API change, no spend, no live check.

User decisions (2026-10-12), with the approaches text shown in chat before each choice:
1. Scope: exactly these two, nothing else ("yes" to the understanding note); line 101 stays as it is.
2. 64:102: widen the suffix so `!` and `as string` may both follow the key (A), over a won't-fix note (B).
3. 64:103: assert `str(engine_probe.OUT)`, the relative path `main()` names (A), over comparing the whole refusal message (B) and a won't-fix note (C).
4. Sections 1 and 2 each approved after their text was shown in chat ("yes").
5. After the spec review (finding 1, reproduced by the controller: a refusal naming `data/eval/results/engine_probe_v0.json` still passed the substring assert): anchor the match in both branches, `assert f"exist: {named};" in str(refused.value)` (A), over keeping the substring and listing prefix directories as out of scope (B).

The brainstorm ran under the harness's plan mode: the design questions and sections were answered in chat, a plan-mode file recorded the approved design, and the proof, this spec and the plan followed after the user approved leaving plan mode.

## Section 1 — The two code changes (64:102, 64:103)

- 64:102, apps/web/src/lib/api-paths.test.ts: in the formSeg test's `RAW`, the variable-key branch changes from `\bString\([^\n]*?\.get\(\w+\)(?:!|\s+as\s+string)?\)` to `\bString\([^\n]*?\.get\(\w+\)!?(?:\s+as\s+string)?\)`, so `String(form.get(k)! as string)` is caught along with the bare, `!` and `as string` shapes. The comment's "with or without `!` or `as string`" becomes "with or without `!`, `as string`, or both". The literal-key branch and `seg(String(` are unchanged. Today's only variable-key read inside `String(` is reports/actions.ts:48, through `?? ""`, so the scan stays green on main.
- 64:103, tests/unit/test_engine_probe.py: in the `results` branch of `test_a_rerun_refuses_to_start_while_outputs_exist`, `named = "engine_probe_v0.json"` becomes `named = str(engine_probe.OUT)`. The test `chdir`s to `tmp_path` and `OUT` is the relative `Path("eval/results/engine_probe_v0.json")`, which `main()` joins into the refusal with `", ".join(str(p) for p in left)`, and, by decision 5, the final assert in both branches becomes `assert f"exist: {named};" in str(refused.value)` with a one-line comment. The refusal reads `earlier probe outputs exist: <paths>; move them first …` and each case leaves exactly one path, so the two delimiters pin the whole path text: a prefixed, renamed or dropped directory fails, in the `results` case and the `raw` case alike. The setup, the client guard, the `"move them first"` assert and the parametrize ids are unchanged.

## Section 2 — Testing, docs, out of scope

- 64:102, red on main: M1 (`const k = "brand_id"; const id = String(form.get(k)! as string);` in place of the first `formSeg(form, "brand_id")` in serp/actions.ts) passes main's scan and fails the patched one. M2 to M4 (bare, `!`, `as string`) are regression rows, red on both.
- 64:103: M10 (`main()` joins `str(Path("data") / p)`, a prefix directory; the `raw` path is absolute, so it is unchanged) is the whole-test green-to-red proof: green on main, red patched in `[results]` only. M5 (`main()` joins `p.name` in place of `str(p)`) is green-to-red for the `results` case alone: on main it fails only `[raw]` (that case already asserted a full path) and `[results]` passes; patched it fails both. M6 to M9 (slice 64's four probe mutants: a wrong raw path, `MODELS[:1]`, a substituted raw directory, a substituted results path) are regression rows with the same outcome on both.
- Green, patched (outputs saved beside the proof, each headed with its UTC run time): `gate65-backend.txt` ran at 08:17:39Z after the anchored asserts of decision 5; `gate65.txt` ran at 08:09:59Z before them, and stands because the web gate does not read tests/unit/test_engine_probe.py and api-paths.test.ts's bytes are unchanged since (blob 20f800a in the diff below; its mtime moved later because the mutation script rewrote it with the same text). Web `npm run gate` exits 0 with 93 vitest (unchanged); backend 1811 passed, 2 deselected, 2 warnings (unchanged), metrics coverage 100.00%, `ruff format --check` (185 files already formatted), `ruff check` and `mypy` clean.
- Docs PR after the merge: findings-slice65.md quoting every ledger line; the plan's "Changes made during execution"; README rows; "fixed" dated notes under docs/findings-slice64.md lines 102 and 103 (as at main a456260). The two notes move that file's later lines; findings-slice65.md states the new positions.
- No live check: nothing is called and no server is started.

## The change

Generated from the proof (a scratchpad copy of main a456260 with the change applied) with `git diff`, over the two files:

```diff
diff --git a/apps/web/src/lib/api-paths.test.ts b/apps/web/src/lib/api-paths.test.ts
index 726869e..20f800a 100644
--- a/apps/web/src/lib/api-paths.test.ts
+++ b/apps/web/src/lib/api-paths.test.ts
@@ -104,11 +104,11 @@ test("path values are read with formSeg()", () => {
   // alike), whatever the receiver ((await req.formData()).get,
   // this.form.get), the quote style (template literals too) or a trailing
   // `!` or `as string`; nor String(<x>.get(<variable>)), with or without
-  // `!` or `as string`. The leading \b on String and seg is a precaution:
-  // it keeps a future toString(...) line from matching.
+  // `!`, `as string`, or both. The leading \b on String and seg is a
+  // precaution: it keeps a future toString(...) line from matching.
   const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|\x60[a-z_]*_id\x60|"type"|'type'|\x60type\x60)`;
   const RAW = new RegExp(
-    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)(?:!|\s+as\s+string)?\)|\bseg\(String\(`,
+    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)!?(?:\s+as\s+string)?\)|\bseg\(String\(`,
     "g",
   );
   const bad = SOURCES.flatMap((f) =>
diff --git a/tests/unit/test_engine_probe.py b/tests/unit/test_engine_probe.py
index 36e54e6..66f538f 100644
--- a/tests/unit/test_engine_probe.py
+++ b/tests/unit/test_engine_probe.py
@@ -349,7 +349,7 @@ def test_a_rerun_refuses_to_start_while_outputs_exist(
     results.mkdir(parents=True)
     if left == "results":
         (results / "engine_probe_v0.json").write_text("{}")
-        named = "engine_probe_v0.json"
+        named = str(engine_probe.OUT)
     else:
         # Uses the last model, so main() must pass every model and
         # <raw_store_dir>/experiments/engine to existing_outputs().
@@ -380,5 +380,6 @@ def test_a_rerun_refuses_to_start_while_outputs_exist(
     monkeypatch.setattr(engine_probe.genai, "Client", no_client)
     with pytest.raises(SystemExit) as refused:
         engine_probe.main()
-    assert named in str(refused.value)
+    # One path is left in each case, so the delimiters pin its whole text.
+    assert f"exist: {named};" in str(refused.value)
     assert "move them first" in str(refused.value)
```

## Evidence

Proof directory: a fresh scratchpad detached worktree of main a456260 (`proof65`), written only by the controller through assert-counted replacements. Mutation script `mutate65.py` beside it (slice 64's script with this slice's mutants): for each mutant it applies one replacement, runs api-paths.test.ts (or the probe test file) with the test files at main's version and then as patched, records the failing test names and restores the file. Baselines: main and patched green on both sides.

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 64:102 | serp actions `const k = "brand_id"; const id = String(form.get(k)! as string);` | green | red: path values are read with formSeg() |
| M2 | 64:102 | `const k = "brand_id"; const id = String(form.get(k));` | red: same test | red: same test |
| M3 | 64:102 | `const k = "brand_id"; const id = String(form.get(k)!);` | red: same test | red: same test |
| M4 | 64:102 | `const k = "brand_id"; const id = String(form.get(k) as string);` | red: same test | red: same test |
| M5 | 64:103 | `main()` joins `p.name` in place of `str(p)` | red: [raw] only | red: [raw] and [results] |
| M6 | 64:103 | `main()` raw path `"experiment" / "engine"` | red: [raw] | red: [raw] |
| M7 | 64:103 | `existing_outputs(OUT, raw_dir, MODELS[:1])` | red: [raw] | red: [raw] |
| M8 | 64:103 | `existing_outputs(OUT, Path("nowhere"), MODELS)` | red: [raw] | red: [raw] |
| M9 | 64:103 | `existing_outputs(Path("nowhere"), raw_dir, MODELS)` | red: [results] | red: [results] |
| M10 | 64:103 | `main()` joins `str(Path("data") / p)` (a prefix directory; review probe X2) | green | red: [results] |

Saved gate outputs: `gate65-backend.txt` (run 2026-10-12T08:17:39Z, after decision 5's edit) and `gate65.txt` (run 2026-10-12T08:09:59Z, before it; valid as Section 2 explains), both on the patched proof copy. The table is the run after decision 5's edit; M1 to M9 kept their first-run outcomes.

## Departures from the section text shown in chat

- Section 1 in chat said "Nothing else in the test changes" and named only the `results` branch; decision 5 (after the spec review) changes the final assert in both branches, as Section 1 above says.
- Section 2 in chat said M5 would "pass main's test and fail the patched `[results]` case"; the run shows M5 already fails `[raw]` on main, so the green-to-red step is the `[results]` case alone. The table and Section 2 above say so.

## Rulings

Ruling: R1. Decided: the spec review's findings 2 and 3 are applied in the second spec commit alongside decision 5 (finding 1): M10, the prefix-directory mutant, is added as the whole-test green-to-red proof for 64:103; `String(form.get(k)!as string)` (no space after `!`, which Prettier normalises away) is listed as not caught under Out of scope; Section 1 drops the overstated "requires the path main() names" for the anchored assert's exact effect. Found by: the spec reviewer (Opus 5.5), 2026-10-12; finding 1 reproduced by the controller in the proof. Why: a substring claim wider than what it pinned, a proof that showed only a per-case change, and an unlisted miss, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

## Out of scope

- docs/findings-slice64.md:101 (closed).
- Wider casts (`as unknown as string`, `as string | null`, `as String`), `String(form.get(k)!as string)` with no space after `!`, `.get( k )` with spaces, the `\s+` newline crossing (a stated fail-safe limit since slice 64), and any product code.

## Docs follow-ups

- Dated notes under docs/findings-slice64.md lines 102 and 103 (as at main a456260) in the docs PR after the merge; README rows for the spec, plan and findings.
