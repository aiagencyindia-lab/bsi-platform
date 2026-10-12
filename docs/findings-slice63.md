# Slice 63 findings: the seven open test minors

## 1. What was built

Slice 63 closes the seven deferred test minors that slice 62 left open (findings-slice49.md lines 108 and 109, findings-slice60.md lines 141 to 143, findings-slice61.md lines 103 and 104, as at main 7682ffd). It changes four test files and nothing else: no product code, migration, API or generated file, no live check and no spend.

- **49:108, the `QUERIES` exemption.** `QUERIES` maps each exempt name to the statements it needs. A `${name}` in an API path passes only where its file has each statement exactly once: `const q = apiQuery(...)` (the same for `dq` and `wq`); for `feedQuery`, its exact current line plus `const fq = apiQuery(...)` and `const FEED_DAYS = <digits>;`. Outside those statements, the name may appear only as `${name}`. Inline `${apiQuery(sp)}` stays exempt. Two contrived gaps are documented in the test comment and the spec, not closed (R2): a statement on a line the comment filter drops, and a local or differently-imported `apiQuery`.
- **49:109, the scope.** Both scans read every non-test `.ts`/`.tsx` file under `src/` through one shared `SOURCES` list. A `(?<!function )` lookbehind keeps api.ts's own `api`/`publicApi` definitions from being read as calls.
- **60:141, the receiver.** The formSeg scan flags `.get(<id or type key>)` on any receiver, in `"…"`, `'…'` or template-literal quotes, with or without a trailing `!` or `as string`; a variable key inside `String(…)` with an optional `!`; and `seg(String(`. The ban covers all of `src/`, so the test is renamed "path values are read with formSeg()".
- **60:142, `signedIn()`.** api.test.ts gains two tests: `api()` sends `Authorization: Bearer bsi_key_1` with `cache: "no-store"`, and with no key cookie (a cookie under another name only) it redirects to `/login` without calling the API. A wrong cookie name and a wrong scheme were already caught on main by page.test.tsx's `render()`; the new tests add a pin in api.test.ts and catch a dropped key check and a changed cache mode, which main missed.
- **60:143, the fixture.** `audit()` defaults to owned 0 / organic 0 / no results, and the first audit card sets `owned: 1, organic: 1` beside its rows (decision A′, after the Correction below). This is consistency, not a pin: the old 1/1 default restored on the patched file leaves every test green (M20).
- **61:103 and 61:104, the probe refusal.** `test_a_rerun_refuses_to_start_while_outputs_exist` is parametrized over `left`: `results` (only the results file) and `raw` (only `<raw_store_dir>/experiments/engine/gemini-3.8-flash/`, the last model). The `raw` case asserts the full path in the refusal, so a wrong raw path, a cut-down model list and a substituted directory each fail it (M17 to M19).

Line numbers: the dated notes this docs PR adds move later lines in those files. findings-slice62.md's 60:144 (the "2 warnings" line) is now 60:147, and the seven minors now sit at 49:108, 49:110, 60:141, 60:143, 60:145, 61:103 and 61:105.

Counts: the three web test files 37 tests; web vitest 91 → 93; tests/unit/test_engine_probe.py 20 → 21; backend 1810 → 1811. Of the 25 product-code mutants, 22 pass main's tests and fail the patched ones; M12, M13 and M15 were already red on main.

Spec: docs/superpowers/specs/2026-10-12-slice63-test-minors-design.md (commits 0a16fb4, 80dc511, 524c8c4; decisions 1 to 6, rulings R1 and R2). Plan: docs/superpowers/plans/2026-10-12-slice63-test-minors.md (commits a711b70, 473df75; R3). R4 was made at execution. Merged via PR #126 (https://github.com/aiagencyindia-lab/bsi-platform/pull/126), main `1cb75a9`.

**Code**:
- apps/web/src/lib/api-paths.test.ts: `QUERIES`, `SOURCES`, `CALL`, `PATH`, `encoded()`, both tests.
- apps/web/src/lib/api.test.ts: the `redirect` import, two new tests.
- apps/web/src/app/(app)/b/[id]/serp/page.test.tsx: the `audit()` defaults, the first card's counts.
- tests/unit/test_engine_probe.py: the refusal test, parametrized.
- 4 files, +118 −27.

**User decisions**, as the ledger records them:

- "User decision (2026-10-12): scope is exactly the seven minors 49:108, 49:109, 60:141, 60:142, 60:143, 61:103, 61:104, nothing else ("Yes, exactly these 7, nothing else")."
- "User decision (2026-10-12): 49:108 closed by checking the declaration (option A), over inlining apiQuery() into the page templates and a won't-fix note."
- "User decision (2026-10-12): 60:143 zero default (option A), over one matching result row."
- "User decision (2026-10-12): 60:143 asked again: zero default with the first audit card passing owned: 1, organic: 1 explicitly (A′), over the one-row default."
- "User decision (2026-10-12): Sections 1 to 4 each approved after their text was shown in chat ("Yes, Section N approved")."
- "User decision (2026-10-12): after the spec review, tighten the declaration match and ban every other use of an exempt name (option 1), over the TypeScript compiler API (option 2) and documenting the gaps only (option 3)."
- "User decision (2026-10-12): spec approved ("approved, write the plan")."
- "User decision (2026-10-12): execution subagent-driven ("Subagent-driven")."
- "User decision (2026-10-12): finishing option 2, push and create a PR ("2 PR"), after both gates were run by the controller on 1fb88b2 (backend 1811 passed, 2 deselected, 2 warnings, coverage 100%; web gate exit 0, 93 tests)."
- "User decision (2026-10-12): "check ci then merge" after PR 126 was opened."
- "User decision (2026-10-12): "yes, start the docs PR"."

**Correction**, as the ledger records it:

- "Correction (2026-10-12, during the proof): the 60:143 approaches text and the approved Section 2 said both cases using audit() override owned/organic; only the failed reviews card does, and the first card relied on the default 1/1. The choice was asked again."

**Results** (selected ledger lines, quoted; in the ledger only: the header, the pre-flight scan, the ⚠️ resolution lines and the "Docs:" lines):

- "Task 1: implementer (Opus 5.5) DONE, commit 9182686 (BASE 473df75); Step 2 37 passed; all 23 mutants matched their Expected lines (M20 survived as designed); typecheck and lint exit 0; self-reported process departures: the mutants run in one bash loop, typecheck and lint as two commands."
- "Task 1: complete (commits 473df75..9182686, review clean)"
- "Task 2: implementer (Opus 5.5) DONE, commit 1fb88b2 (BASE 9182686); probe tests 21 passed; M17, M18, M19 each 1 failed, 20 passed ([raw] only); ruff/mypy clean; backend gate 1811 passed, 2 deselected, 2 warnings, metrics coverage 100%; web gate exit 0, 93 vitest; no departures reported."
- "Task 2: complete (commits 9182686..1fb88b2, review clean)"
- "Final review: no fix wave (nothing to fix)."
- "Finishing: branch slice63-test-minors pushed; PR https://github.com/aiagencyindia-lab/bsi-platform/pull/126 opened against main (head 1fb88b2); CI not checked yet."
- "Finishing: CI run 38201439115 on 1fb88b2: gates pass (4m31s). PR 126 merged with a merge commit, 1cb75a9 (main); local main fast-forwarded to 1cb75a9."
- "Finishing (2026-10-12): CI check gates pass (4m31s) on PR 126; merged with --merge --delete-branch, merge commit 1cb75a9; git ls-remote --heads origin slice63-test-minors prints nothing (remote branch deleted)."

**Mutation table** (the spec's Evidence, after the spec review; the implementers' runs of the patched column matched it):

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 49:108 | competitors `const q = String(sp.q ?? "")` | green | red: every value in an API path goes through seg() |
| M2 | 49:108 | overview `let q = apiQuery(sp)` then `q = String(sp.raw)` | green | red: same test |
| M3 | 49:108 | competitors `const fq = String(sp.date_from ?? "")` (reaches `feedQuery`) | green | red: same test |
| M4 | 49:108 | competitors `const wq = String(sp.days ?? "") \|\| apiQuery(` | green | red: same test |
| M5 | 49:109 | format.ts gains ``api(`/brands/${raw}`)`` | green | red: same test |
| M6 | 49:109 | components/RivalPages.tsx gains `publicApi(p)` | green | red: same test |
| M7 | 60:141 | serp actions `String((await req.formData()).get("brand_id"))` | green | red: path values are read with formSeg() |
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
| M21 | 49:108 | competitors `const q = apiQuery(sp) + String(sp.raw ?? "")` (review probe A) | green | red: every value in an API path goes through seg() |
| M22 | 49:108 | feedQuery's `days=${FEED_DAYS}` becomes `days=${String(sp.days)}` (probe B) | green | red: same test |
| M23 | 49:108 | competitors gains ``(q: string) => api(`/brands/x${q}`)`` (probe C) | green | red: same test |
| M24 | 49:108 | competitors gains ``for (const wq of xs) await api(`/brands/x${wq}`)`` (probe D) | green | red: same test |
| M25 | 49:108 | `const FEED_DAYS = String(process.env.FEED_DAYS)` | green | red: same test |
| M26 | 49:108 | overview gains `q **= n` at module scope (review finding 3; tests the scan's text rule only, since `q` is out of scope there and `tsc` would reject it) | green | red: same test |

**Reviews**, as the ledger records them:

- "Review verdict (2026-10-12): spec review (Opus 5.5) of 0a16fb4: approve after fixes; findings 1 and 2 important (the 49:108 declaration check matched only how a declaration starts, and per file not per scope; probes A to D reproduced by the controller), 3 to 6 minor wording."
- "Review verdict (2026-10-12): spec scoped re-review (Opus 5.5) of 80dc511: all six first-review findings resolved, "22 of the 25" true; two minor (an incomplete Ceiling, probes PA and PB reproduced by the controller; a stale M7 cell) and one informational (M26 does not compile as written)."
- "Review verdict (2026-10-12): 524c8c4 (the R2 wording commit) was not reviewed; disclosed in chat."
- "Review verdict (2026-10-12): plan review (Opus 5.5) of a711b70: Approve with minors; all 11 blocks reproduce the spec's diff, blob hashes included; every mutant's Expected line reproduced; three minors."
- "Review verdict (2026-10-12): Task 1 task review (Opus 5.5) of 473df75..9182686: spec ✅, task quality Approved; no critical or important; two minors; one ⚠️ item (the mutation outputs, typecheck/lint and banned grep are seen only as the report's pasted lines; Step 0's uv sync/npm ci result is paraphrased, not pasted)."
- "Review verdict (2026-10-12): Task 2 task review (Opus 5.5) of 9182686..1fb88b2: spec ✅, task quality Approved; no critical or important; one minor; one ⚠️ item (the mutant and gate results are the report's claims)."
- "Review verdict (2026-10-12): final whole-branch review (Opus 5.5) of 7682ffd..1fb88b2: ready to merge (Yes); no critical or important; one new minor; the four deferred minors triaged all "leave"; the four test files' blob hashes match the spec's diff."
- "Review verdict (2026-10-12): docs review (Opus 5.5) of 791c0fc: Approve with minors; no important; four minors (the Results header's "in the ledger only" list omits the merge line with the remote-branch deletion; the closing "none of the seven ... five minors ... deferred (the redirect one is closed by R4)" sentence is ambiguous; the new notes move lines findings-slice62 calls current, 60:144 now 60:147, with nothing saying so; the 49:108 note reads as if `FEED_DAYS` came from apiQuery()). All 35 quotes, the counts, the tables, the note placements and the README rows verified; the CI run facts rest on the ledger (gh returned 404 to the reviewer)."

**Commits** (`git log --oneline --reverse 7682ffd..1cb75a9^2`, oldest first):

| Commit | Subject |
|---|---|
| 0a16fb4 | docs: slice 63 spec, the seven open test minors |
| 80dc511 | docs: slice 63 spec, spec review fixes (decision 6, R1) |
| 524c8c4 | docs: slice 63 spec, re-review wording (R2) |
| a711b70 | docs: slice 63 plan, the seven open test minors |
| 473df75 | docs: slice 63 plan, plan review minors (R3) |
| 9182686 | test(web): path scans read all of src and check exempt query names, formSeg scan ignores the receiver, api() auth tests, zero audit fixture |
| 1fb88b2 | test(probe): the re-run refusal covers a leftover raw model directory alone |

CI (2026-10-12): PR run 38201439115 on 1fb88b2, check `gates` passed (4m31s). The push run on main after the merge was not checked.

## 2. Live check

None: the slice changes tests only; nothing was called and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the ledger from the spec, R3 from the plan, when it was created):

> Ruling: R1. Decided: the spec review's findings 3 to 6 are applied as wording and comment fixes in the second spec commit: the compound-assignment overstatement (finding 3) goes with the assignment regex it described, replaced under decision 6; the `\b` on `String`/`seg` is called a precaution (finding 4); the formSeg comment drops the stale "label's actions read ids that way" clause and the spec says every `String(<x>.get(<variable>))` read goes through `?? ""` (finding 5); Section 1 says the `.get(<id/type key>)` ban covers any receiver anywhere in `src/` and the test is renamed "path values are read with formSeg()" (finding 6). Found by: the spec reviewer (Opus 5.5), 2026-10-12. Why: an overstated claim, a necessity that was only a precaution, a stale comment clause, an imprecise code claim, and a ban wider than the test's name, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the spec re-review's three findings are applied as wording in a third spec commit, without a further review: the Ceiling sentence and the test comment name the two gaps the re-reviewer reproduced (a rebinding on a line the comment filter drops; `apiQuery` matched by name, not resolved), the M7 cell names the patched test, and the M26 row says it tests the scan's text rule only. The alternative the re-reviewer offered (read unfiltered source and require `apiQuery` imported from `@/lib/format`) is not taken, both cases being contrived. Found by: the spec re-reviewer (Opus 5.5), 2026-10-12; both probes reproduced by the controller. Why: an incomplete Ceiling, an overstating test comment and a stale cell, all mine. Cost if wrong: a raw value bound on a comment-prefixed line, or through a shadowing `apiQuery`, would pass the scan. How named: this spec and chat.

> Ruling: R3. Decided: the plan review's three minors are fixed in a second plan commit: M14 says to delete the whole line, its newline included; Step 0's `git status --short` carries the worktree `cd` prefix; M7 says the old line occurs twice in serp/actions.ts and the first is replaced (M7 to M12). Found by: the plan reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (all 11 blocks reproduce the spec's diff, blob hashes included; every mutant's Expected line reproduced). Why: a deletion with two readings, a command against the plan's own cwd rule, and a repeated old text that could make an implementer stop to ask, all mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R4. Decided: the redirect-reset minor is closed without a change: on vitest 3.2.7 (this repo's version) `vi.restoreAllMocks()` resets a module-mock vi.fn's call history and drops a queued `mockImplementationOnce`. Found by: the Task 1 reviewer (Opus 5.5), 2026-10-12; checked by the controller with a scratch test in the proof copy (test a calls `redirect` and queues a throwing once-impl; after `restoreAllMocks`, test b saw `calls 0` and no throw), the scratch file deleted after. Why: the reviewer's premise about vitest 3 is wrong for 3.2.7, as the spec reviewer had also found. Cost if wrong: a later vitest release that stops resetting vi.fn state in `restoreAllMocks` would let the redirect assertion pass on a stale call; the fix then is one `vi.mocked(redirect).mockReset()` in the afterEach. How named: this ledger and chat.

> Ruling: R5. Decided: the docs review's four minors are fixed in a second docs commit: the merge line (remote branch deleted) is quoted under Results; the closing sentence says none of findings 47 to 61 stays open, slice 63 adds five deferred minors and R4 closes one, so four stay open; §1 says the dated notes moved lines (findings-slice62's 60:144 "2 warnings" is now 60:147, and the seven minors now sit at 49:108, 49:110, 60:141, 60:143, 60:145, 61:103, 61:105, checked by grep); the 49:108 note's parenthesis names the `fq` and `FEED_DAYS` statements; the findings quote this verdict and ruling. Found by: the docs reviewer (Opus 5.5), 2026-10-12; the moved lines checked by the controller. Why: an incomplete list, an ambiguous sentence, an unstated line shift and a misleading parenthesis, all mine. Cost if wrong: none to behaviour. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): api.test.ts's afterEach does not reset the `redirect` mock, so `toHaveBeenCalledWith("/login")` could pass on an earlier test's call and an unused `mockImplementationOnce` could leak to the next test (reviewer: under vitest ^3 `restoreAllMocks` leaves vi.fn call history alone)."
- `` Task 1: minor (deferred): `encoded()` matches `\b<name>\b` over the whole file, so in a file that interpolates `${q}` any other `q` (a `"q"` string, `sp.q`, an object key) fails the scan; intended strictness that errs only toward false failures (the comment states the rule). ``
- "Task 1: minor (deferred): Step 0's `uv sync` and `npm ci` results are paraphrased, not pasted as the Global Constraints ask; the dependencies are shown working by Step 2's vitest run and Step 4's typecheck and lint."
- "Task 2: minor (deferred): test_engine_probe.py builds `raw` in the results case too, where it is unused (the brief's block; harmless, keeps the branches symmetric)."
- "Final review: minor (deferred): the formSeg RAW pattern does not catch a variable key with a cast, `String(form.get(k) as string)` (only `!` is allowed after `.get(\w+)`); not a regression (main did not catch it) and not named by 60:141."

Still open from findings 47 to 61: none. Slice 63 adds the five deferred minors above; R4 closes the redirect one, so four stay open.
