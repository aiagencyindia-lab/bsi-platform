# Slice 49 findings: every value in an API path goes through seg()

## 1. What was built

`apps/web/src/lib/api.ts` gains `seg(value)`, which returns a value of one or more letters, digits, `-` or `_` and otherwise logs `API path value refused` and calls `notFound()`, and `sendAsWritten(path)`, called first in `api()` and `publicApi()`, which refuses a path `fetch` would not send as written (dot segments in any spelling, `\`, `#`, anything the URL parser re-encodes, a bare trailing `?`), logging `API path refused`. Every value interpolated into an `api()`/`publicApi()` path in 28 files under `apps/web/src/app` (55 path templates: route params, form fields, values from API answers) is wrapped in `seg()`; `URLSearchParams` query strings and `redirect()` targets are unchanged. A source-scan test (`api-paths.test.ts`) fails if a path argument is not one literal or a value in a `src/app` path template skips `seg()`. This fixes the slice 48 deferred minor (findings-slice48 §3, R6). The change keeps requests on their intended route; the request already carried the operator's own key and the call site's method, so it is not a privilege fix. Web only: no API, migration or backend change.

Spec: docs/superpowers/specs/2026-10-07-slice49-api-path-guard-design.md (R1 and R2 entered in `6a55903`, R3 and R4 in `c2253d5`, R5 and the Correction to R3 in `ef3b796`, R6 in `9daba5a`, R7 in `90ee504`, R8 in `23c1ae8`, where the user approved the spec; R9 and the Correction to R8 in `718b8df` and R10 in `d5edba8`, during planning; R11 and the five later deferred minors added by the first post-merge docs commit, R12 and R13 by the docs-review fix commits). Plan: docs/superpowers/plans/2026-10-07-slice49-api-path-guard.md (Tasks 1 and 2). Merged via PR #100 (https://github.com/aiagencyindia-lab/bsi-platform/pull/100), main `e3b3f61`.

**Code**: apps/web/src/lib/api.ts (`seg`, `sendAsWritten`); 28 call-site files under apps/web/src/app; apps/web/src/lib/api.test.ts (18 new tests); apps/web/src/lib/api-paths.test.ts (new, 1 test). Web 52 → 71.

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the brand_id encoding deferred minor"; approach "Guard in api()" (over validating each id, or encodeURIComponent at each site) and refusal "notFound() + log" (over throwing an error), each after approaches written in chat; Section 1 and Section 2 approved in chat."
- "User decisions (2026-10-07, after the spec review of 6a55903 showed a '/' or '%2F' inside a value passes the guard, the fact behind the approach choice; re-asked): "Guard + seg()" (over the guard only with the gaps stated, or closing the minor as won't-fix), after approaches written in chat; the revised Section 1 (seg() on every interpolated value, the guard kept, the source-scan test, the review's corrections) and the revised Section 2 (seg() in api.ts, 26 call-site files, 8 seg tests, the scan test, web 52 -> 70) were shown in chat and approved."
- "User decisions (2026-10-07, after the second spec review): both test hardenings, "Harden scan" (fail on a non-literal path argument; each ${…} exactly one seg(…) call) and "Query refusal case" (/brands/x?a=b'c; web 70 -> 71), after approaches written in chat."
- "User decision (2026-10-07): after "go ahead" and the confirming question, "Approve, write plan" approved the spec as it stood at 23c1ae8 (including that unreviewed commit)."
- "User decision (2026-10-07): execution "Subagent-driven"."
- Paraphrased, since the ledger line spells out the banned token itself: on 2026-10-07 the banned-word grep blocked "PR #100"; asked, the user chose "Allow PR numbers", so the grep now blocks the ranking token only when no digit follows it, and PR numbers #100–#199 pass.

**Results** (quoted from the ledger):
- "Task 1: implementer abb1354587c39f771, commit c44ac3f (trailer Opus 5.5 checked); report: red Tests 17 failed | 4 passed (21), green Tests 21 passed (21); gate exit 0, gate-task1.txt Tests  70 passed (70), Compiled successfully, no refusal line, gen:check no diff; controller check: api.ts and api.test.ts are byte-identical to the spec's proof copies."
- "Task 2: implementer a2d9fd3db78da39ab, commit 4660364 (trailer Opus 5.5 checked); report: red Tests 1 failed (1), green Tests 22 passed (22) with api.test.ts; staged 29; gate exit 0, gate-task2.txt Tests  71 passed (71), Compiled successfully, no refusal line, gen:check no diff; controller check: all 31 slice files are byte-identical to the spec's proof copies."
- "Controller gates on 4660364: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 235.68s (0:03:55), mypy Success, metrics coverage 100%; web gate exit 0, Tests  71 passed (71), Compiled successfully, no refusal line."
- "PR opened for slice49-api-path-guard on head 4660364 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
- "CI run 37614186076: success on 4660364, 1753 passed, 2 deselected, 2 warnings in 129.64s (0:02:09); web Tests  71 passed (71), Compiled successfully."
- "PR #100 merged by the controller after the user said "go ahead" to "Should I merge PR #100?" (2026-10-07); merge commit e3b3f61; local main fast-forwarded to e3b3f61; branch deleted on GitHub and locally."
- "Gates on main e3b3f61 after merge: backend 1753 passed, 2 deselected, 2 warnings in 256.79s (0:04:16), coverage 100%; web Tests  71 passed (71), Compiled successfully."

**Reviews**, as the ledger records them:
- "Spec review (ad3141fc576bdde33, 6a55903): "Spec ready? No"; 0 Critical, 3 Important, 6 Minor."
- "Spec review (a015dcf18c3d22bd2, c2253d5): "Spec ready? No"; 0 Critical, 1 Important, 7 Minor."
- "Spec re-review (a698f8d3a147689af, ef3b796): "Spec ready? No"; 0 Critical, 1 Important, 2 Minor."
- "Spec re-review (a63daf67355d2d13a, 9daba5a): "Spec ready? No"; 0 Critical, 1 Important (a regression: the R5 comment reverted), 2 Minor."
- "Spec re-review (a0abfd1c7e77ff3bb, 90ee504): "Spec ready? Yes" once Minor 1 is recorded; 0 Critical, 0 Important, 2 Minor."
- "Plan review (adbe523df7912402a, 23c1ae8 and 761252f): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Plan re-review (acc9e70f6a69ca2f7, 718b8df): "Ready to execute? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Task 1: task review (a43a23dfe41844d65, d5edba8..c44ac3f): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows Tests  70 passed (70), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; api.ts and api.test.ts are byte-identical to the proof."
- "Task 2: task review (a1ab877d3884b5e50, c44ac3f..4660364): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1; gate-task2.txt shows Tests  71 passed (71), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; all 31 slice files are byte-identical to the proof."
- "Final review (a9f3c63a8276cb04c, c45a729..4660364): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; every deferred minor triaged "Not before merge"."

**Commits** (`git log --oneline --reverse c45a729..e3b3f61^2`, oldest first):

| Commit | Subject |
|---|---|
| 6a55903 | docs(spec): slice 49, api() refuses a path fetch would not send as written |
| c2253d5 | docs(spec): slice 49 rewritten for seg() on every API path value (R3, R4) |
| ef3b796 | docs(spec): slice 49 second review fixes: scan hardening, query case, Prettier facts (R5) |
| 9daba5a | docs(spec): slice 49 scan requires one whole literal path argument (R6) |
| 90ee504 | docs(spec): slice 49 restores the R5 guard comment; comment-limits wording (R7) |
| 23c1ae8 | docs(spec): slice 49 records the last review minors (R8) |
| 761252f | docs(plan): slice 49, seg() on every API path value and the api() guard |
| 718b8df | docs(plan): slice 49 plan review fixes (R9, correction to R8) |
| d5edba8 | docs(plan): slice 49 architecture line names the scan's scope (R10) |
| c44ac3f | feat(web): api() refuses a path fetch would not send as written; add seg() |
| 4660364 | fix(web): every value in an API path goes through seg() |

## 2. Live check

Not run. The spec names it as optional (page views only) and asked first after merge; it was offered after PR #100 opened, before the merge. As the ledger records it:

- "Live check (2026-10-07): offered in chat after PR #100 opened, as optional ("I'll only run it if you say so"); the user's next messages were "check CI" twice and "go ahead" to the merge question; not run."

No migration; dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the refusal tests sign in with a mocked cookie (a signedIn() helper) and silence console.error with vi.spyOn, and afterEach calls vi.restoreAllMocks(); none of this was in the Section 2 text. Found by: the controller, running the proof: without a cookie, mutant M4 (the guard moved after fetch) failed only because api() crashed reading an undefined cookie store, not on the "fetch not called" assertion. Why: each mutant then fails on the assertion that names its fault, and the gate output stays free of "API path refused" lines. Cost if wrong: an unexpected console.error in those tests would be hidden. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: no test checks that every real call site's path passes the guard; the paths are built from UUIDs (route params and hidden form fields), report type slugs and URLSearchParams query strings, which the URL parser leaves unchanged, and the one query-string test pins that case. Found by: the controller, writing the design (named in Section 2). Why: the call sites are about 40 Server Component and server action paths with no page-test harness in the repo. Cost if wrong: a page whose path the URL parser re-encodes would show the not-found page, with "API path refused" and the path in the web server log. How named: in chat, 2026-10-07, in Section 2 and after the proof run.

> Ruling: R3. Decided: the proof departs from the revised Section 2 text in four ways: 28 call-site files changed, not "about 25"/26 (the count missed two); the recommendations helper rec() now returns only the rec_id and both calls inline the path with seg() on each value, so the scan test sees seg(...) at every interpolation; the seg refusal test titles use %j so the empty string shows; recommendations/actions.ts and reports/actions.ts, Prettier-clean on main, are rewrapped by Prettier after the edit (the other changed files were not Prettier-clean on main and are left as edited). Found by: the controller, running the proof. Why: facts of the edit, not design changes. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R4. Decided: the spec review's other findings are fixed in the rewritten spec: route params can be set by any link (GET-only, the operator's own key) (Important 3); the live check is possible read-only from the address bar, and is offered after merge, asked first (Important 2); `../..` can leave /v1 (Minor 4); the counts are 55 path templates in 28 files (Minor 5); the value lists name observation_id, entity_id, rec_id and pid (Minor 6); the claim that api() checks before reading the cookie is kept and pinned by no test, stated as such (Minor 7); the publicApi refusal test does not assert the log line, stated (Minor 8); the "?" gap no longer exists for interpolated values, since seg() refuses "?" (Minor 9). Found by: the spec reviewer (Opus 5.5, ad3141fc576bdde33), 2026-10-07. Why: wrong or incomplete statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R5. Decided: the second spec review's other findings are fixed: the Proof and R3's Prettier statement is corrected by a Correction to R3 line (11 changed call-site files were Prettier-clean on main and stay clean, 2 of them rewrapped; 17 were not clean on main) (Important 1); R2's "about 40" gets a note that 55 path templates were counted later (R4) (Minor 3); the live check is called "page views only", not read-only, since each view writes api_key.last_used_at (Minor 4); feedQuery is described as apiQuery output plus "&days=" and the constant FEED_DAYS (Minor 5); the ponytail comment on sendAsWritten says seg() at each call site refuses "/", "%2F" and "?" (Minor 6); the Design says a refusal in a server action relies on Next handling notFound() there, which api() already relies on for an API 404 (Minor 7). Found by: the spec reviewer (Opus 5.5, a015dcf18c3d22bd2), 2026-10-07. Why: wrong or incomplete statements of mine, one in a code comment. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the second spec review.

> Ruling: R6. Decided: the spec re-review's findings are fixed: the scan test now requires the whole first argument of each api()/publicApi() call to be one quoted or template literal followed by "," or ")", so a literal joined with "+" fails, as the user's "Harden scan" choice said (Important 1; mutants M14 and M15 added); feedQuery is described as apiQuery output plus "days=" and the constant FEED_DAYS, joined with "&" or "?" (Minor 1); the spec states the comment skipping's limits (a code line starting with "*" or "/* … */" is skipped; a block-comment line not starting with "*" is scanned, which can only fail the test) (Minor 2). Found by: the spec re-reviewer (Opus 5.5, a698f8d3a147689af), 2026-10-07. Why: the test fell short of the user's approved choice, and two statements were inexact. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R7. Decided: the R6 commit's regression is fixed: the proof's api.ts had been restored after the R6 mutant run from a copy taken before R5's comment change, which put back the old ponytail comment on sendAsWritten; the R5 wording ("a '/', '%2F' or '?' inside a value passes it, and seg() at each call site refuses those") is restored in the proof and the spec's diff, and the other proof files were checked against their latest versions (Important 1); the comment-limits text says a scanned block-comment line could also add to the template count, not only fail the test (Minor 2). Found by: the spec re-reviewer (Opus 5.5, a63daf67355d2d13a), 2026-10-07. Why: a regression from my own file restore, and an overstatement. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R8. Decided: the 9daba5a re-review's Minor 1 (the api.ts hunk headers changed with the content; the reviewer said no action needed) is left, unrecorded by R7 until now; the 90ee504 re-review's Minor 2 (a scanned block-comment line holding an unclosed api(` could also hide a later template from the scan; none exists today) is deferred. Found by: the spec re-reviewer (Opus 5.5, a0abfd1c7e77ff3bb), 2026-10-07. Why: Minor 1 needs no change; Minor 2 needs a contrived comment that no file has. Cost if wrong: such a comment, if ever written, could let one unwrapped value past the scan; seg() at that call site and the api() guard still apply at run time only if the value is wrapped or would be re-encoded. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R9. Decided: the plan review's Minor 1 is fixed by the Correction to R8 line; Minor 2 is fixed: the Task 2 commit message says the scan "fails if a value in an src/app path template skips it"; Minor 3 (Task 1's commit step stages again, Task 2's relies on Step 5) is left as harmless. Found by: the plan reviewer (Opus 5.5, adbe523df7912402a), 2026-10-07. Why: an overstated risk and an overstated commit message of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R10. Decided: the plan re-review's Minor 1 is fixed: the plan's Architecture line says the scan test "fails if a value in an src/app path template skips seg()"; its Minor 2 (the Correction to R8 does not list the bare trailing "?" and simplifies the whitespace before "," or ")") is left, since nothing it says is false. No further review round: the commit changes one sentence. Found by: the plan re-reviewer (Opus 5.5, acc9e70f6a69ca2f7), 2026-10-07. Why: the same overstatement R9 fixed in the commit message. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan re-review.

> Ruling: R11. Decided: no final fix wave. Minor 1 (the spec's Deferred minors list quotes only the spec-phase minor) is fixed by the post-merge docs commit, which adds the four task-review minors, and the PR body lists all five; Minor 2 (the refusal log lines record the value or path uncapped) is deferred; Minor 3 (the scan drops code lines that start with a comment marker) is the limit the spec already states. Found by: the final reviewer (Opus 5.5, a9f3c63a8276cb04c), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and every deferred minor triaged "Not before merge". Cost if wrong: a very long tampered value is logged in full (log noise only). How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R12. Decided: the docs review's three minors are fixed: R11 and the five later deferred minors are credited to the first post-merge docs commit, in the findings and the spec (Minor 1); the paraphrased grep decision says the grep blocked "PR #100", as the ledger does, without the added "docs commit" detail (Minor 2); the findings and the spec say the live check was offered after PR #100 opened, before its merge, not after merge as the spec planned (Minor 3). Found by: the docs reviewer (Opus 5.5, a588d4b509344bc75), 2026-10-07. Why: inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

> Ruling: R13. Decided: the docs re-review's Minor 1 is fixed: the findings and the spec say R12 was added by the docs-review fix commit, not "the second" (three post-merge docs commits touched these files; R12's is the third); then a third scoped re-review, as the user chose "Fix, re-review" when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5, ac9628805f52ac61e), 2026-10-07. Why: an off-by-one statement of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

Every `Correction to R` line, verbatim:

> Correction to R3 (2026-10-07, from the second spec review): 11 of the 28 changed call-site files were Prettier-clean on main and all 11 stay clean (recommendations/actions.ts and reports/actions.ts rewrapped); the other 17 were not clean on main and are left as edited.

> Correction to R8 (2026-10-07, from the plan review): a scanned block-comment line holding an unclosed api(` hides the next template's values from the PATH check, but the test still fails on "path is not one literal" unless the next backtick after it is followed by "," or ")"; and the api() guard refuses dot segments, "\", "#" and re-encoded characters, not only re-encoded ones. The deferred minor quoted with R8 overstates the risk in the same way.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec re-review (90ee504) minor 2, a scanned block-comment line holding an unclosed api(` could make the scan's PATH regex run on to the next real template and hide its interpolations; none exists today (R8)."
  - Note (2026-10-11, after slice 60, PR #120): already guarded: the first path scan fails on a block comment holding an unclosed api(`, because its literal check needs the whole first argument to be one literal; mutant M10 shows it on main and on the patched scan, so no code changed (docs/findings-slice60.md §1).
- "Task 1: minor (deferred): publicApi refuses a dot segment stubs console.error but does not assert the "API path refused" log line (plan-mandated, stated in the spec)."
  - Note (2026-10-09, after slice 58, PR #116): fixed: the test asserts the "API path refused" log line and its count (docs/findings-slice58.md §1).
- "Task 1: minor (deferred): vi.restoreAllMocks() does not clear the cookies mockResolvedValue between tests; harmless, since every test that needs a cookie calls signedIn()."
  - Note (2026-10-09, after slice 58, PR #116): fixed: `afterEach` calls `vi.mocked(cookies).mockReset()` (docs/findings-slice58.md §1).
- "Task 2: minor (deferred): the scan's QUERIES allowlist exempts q, dq, wq, feedQuery and apiQuery(sp) by name, so a raw value later stored in one of them would pass (plan-mandated, stated in the spec)."
- "Task 2: minor (deferred): the scan reads only src/app; no api()/publicApi() caller exists outside it today (plan-mandated, stated in the spec)."
- "minor (deferred): final review minor 2, the refusal log lines in seg() and sendAsWritten record the raw value or path with no length cap (R11)."
  - Note (2026-10-07, after slice 50, PR #102): fixed; both refusal log lines print the value JSON-quoted and capped at 200 code units, plus its full length (docs/findings-slice50.md §1).
