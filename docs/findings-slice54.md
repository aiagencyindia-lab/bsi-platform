# Slice 54 findings: a refused or duplicate domain shows a note on the Brand SERP page

## 1. What was built

The add-domain form on the Brand SERP page (slice 48) posts to `POST /v1/brands/{id}/domains`. A host the browser `pattern` passes but the API refuses (an IP address, `walkaroo.`, `www.walkaroo`: 422) or a host already declared (409) used to land on the generic error page, because `api()` throws on any non-2xx other than 401 and 404. Now `addDomain` in `apps/web/src/app/(app)/b/[id]/serp/actions.ts` catches an error whose message starts with `422 ` or `409 `, sets a code (`refused` or `exists`), rethrows anything else, and after the try/catch redirects to `/b/{id}/serp?domain=<code>`. `domainNote()` in `apps/web/src/lib/format.ts` maps the code through the existing `hasOwn` `note()` helper to one of two fixed strings ("Not added: enter a public domain name such as example.com, not an IP address." and "Not added: that domain is already declared for this brand."), and the page renders it under the schedule line, outside the add-domain form's condition, so it still shows after a 409 hides the form. This mirrors the catch-and-note convention of `products/actions.ts`. The `api()` path template is unchanged, so the slice 49 source-scan test still passes. This fixes the slice 48 deferred minor (findings-slice48 §3, the first Task 1 minor).

**This reverses a slice 48 user decision.** Slice 48 chose the browser `pattern` over catch-and-note, and its findings §1 says a refused host or duplicate shows the error page. The user approved the reversal in the slice 54 design, in chat on 2026-10-08, after the approaches were written out. The slice 48 findings file is history and is not edited beyond the dated note under the fixed minor.

**Still reaching the error page:** two submits of the same host at the same moment give a 500 from the unique constraint (findings-slice48 R2) and are rethrown; the domain is added anyway. A 422 from any cause gets the `refused` note: an IP, a host without a dot, or an entry that trims to fewer than 3 characters (`DomainIn.host` has `min_length=3`; the browser `pattern` already stops a whitespace-only entry unless it holds a dot, such as `" . "`). The API has no upper length cap on a host (the final-review minor quoted in §3 says over 200 characters; that is wrong, see the note there). The copy names IPs specifically and is still correct advice for the rest.

Bounded path: no spec or plan file. The design was approved in chat on 2026-10-08 and lives in the Claude plan file `/Users/vineet/.claude/plans/let-s-do-item-1-2-3-playful-duckling.md`, outside the repo. Merged via PR #108 (https://github.com/aiagencyindia-lab/bsi-platform/pull/108), merge commit `0c1ad47`, which is main after the three slice PRs.

**Code**: apps/web/src/app/(app)/b/[id]/serp/actions.ts (`addDomain`), apps/web/src/app/(app)/b/[id]/serp/page.tsx (the note), apps/web/src/lib/format.ts (`DOMAIN_NOTES`, `domainNote`). **Tests**: apps/web/src/app/(app)/b/[id]/serp/actions.test.ts (2 → 4: refused, exists, a 500 still throws), apps/web/src/lib/format.test.ts (+1, `domainNote`, four cases). Web 73 → 76. No API change: `openapi.json` and `schema.d.ts` untouched.

**User decisions**, as the ledger records them:
- "User decision (2026-10-08 02:45 UTC): the slice 47 weekly-line minor is deferred (architectural: needs a new API field); items 1, 2 and 3b proceed as slices 52, 53, 54."
- "User decision (2026-10-08 02:45 UTC): designs for all three approved in chat (bounded path, no spec file); three branches, three PRs, three parallel implementer agents."
- "User decision (2026-10-08 02:53 UTC): finishing menu option 2, push and create a PR, for all three slices."
- "User decision (2026-10-08 02:55 UTC): merge."
- "User decision (2026-10-08 02:58 UTC): the controller writes the slices 52-54 findings docs in this session (Fable 5.1) after the harness refused the subagent's file write; an Opus 5.5 reviewer reviews them as usual."

**Results** (quoted from the ledger):
- "Task 1: implementer DONE 2026-10-08 02:47 UTC, commit 81dcbf1 (target files red 3 failed/31 passed then green 34 passed; web suite 76 passed, was 73; typecheck, lint, build pass; banned-word grep clean; gen:check skipped, needs backend; openapi.json and schema.d.ts untouched; M2 also failed the 409 test besides the expected 500 test)."
- "Controller web gate 2026-10-08 02:49 UTC on 81dcbf1: typecheck, lint pass; Test Files 8 passed (8), Tests 76 passed (76); build Compiled successfully. gen:check skipped (needs the backend; openapi.json and schema.d.ts untouched)."
- "Controller backend gate 2026-10-08 02:52 UTC on 81dcbf1: ruff format --check, ruff check, mypy (31 files, no issues) pass; pytest 1753 passed, 2 deselected, 2 warnings in 177.22s; bsi_core.metrics coverage 100%."
- "Pushed and opened PR #108 2026-10-08 02:54 UTC (body passed the banned-word grep)."
- "PR #108 merged 2026-10-08 02:55 UTC, merge commit 0c1ad47; main now 0c1ad47."

CI was not checked by the controller before the merge; the ledger records the user's answer to the merge question as "merge" and holds no CI line.

**Mutation table** (from the implementer's report; the two test files run after each mutant, then reverted):

| Mutant | Change | Result |
|---|---|---|
| M1 | `addDomain` without the try/catch (the original code) | the refused and exists tests fail |
| M2 | every error mapped to `refused`, no rethrow | the 500 test fails, and the exists test |
| M3 | `domainNote` without `hasOwn` | the `constructor` case fails |
| M4 | the note moved inside the add-domain form's condition | nothing fails: no test renders the page (deferred) |

Note (2026-10-09, after slice 58, PR #116): the Brand SERP page now has a render test (docs/findings-slice58.md §1); its "with a domain and no room" case now kills M4.

**Reviews**, as the ledger records them:
- "Task 1: task review 2026-10-08 02:49 UTC: spec compliance pass, quality Approved; 2 Minor, 0 Important, 0 Critical (reviewer checked counts: actions.test.ts 4 tests, format.test.ts 30, two-file run 34, suite 76; an empty 422 body gives '422  (request null)' which still starts with '422 '; NEXT_REDIRECT/NEXT_NOT_FOUND are rethrown). Cannot-verify items resolved by controller: the web gate is re-run by the controller at finishing; gen:check skip allowed by the brief."
- "Final whole-branch review 2026-10-08 02:50 UTC: mergeable; 0 Critical, 0 Important, 3 Minor; both deferred minors (M4 page-render gap; import order) triaged as stay-deferred. No fix dispatch needed."
- Docs review: see the docs PR.

**Commits** (`git log --oneline 3b8d2cd..81dcbf1`):

| Commit | Subject |
|---|---|
| 81dcbf1 | feat(web): show a note when an added domain is refused or exists |

## 2. Live check

None. The plan file offered one (ports 8100 and 3100, `www.walkaroo` on a no-domain brand), to run only if the user asked; the user did not ask, and no ledger line records an offer made in chat. It would write `api_key.last_used_at`. Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R2. Decided: one docs PR covers slices 52, 53 and 54 (three findings files, README rows, dated notes under the fixed minors in findings-slice51 and findings-slice48), with one review round instead of three separate docs PRs. Found by: controller, after the three merges. Why: the three slices were planned, built and merged together; one PR keeps one review loop and one merge. Cost if wrong: a problem in one findings file holds up all three; the PR can be split if the review asks. How named: quoted in chat. (2026-10-08 02:55 UTC)

> Ruling: R3. Decided: the docs commit for slices 52-54 carries the trailer Co-Authored-By: Claude Fable 5.1, not Opus 5.5, because the controller wrote those docs on this Fable 5.1 session under the user's decision; the standing Opus 5.5 trailer rule covers work done on Opus. Found by: controller, right after the first commit (a9fecfd, trailer Opus 5.5) and before any push; amended to d2ca0a6. Why: an Opus trailer on Fable-written text would overstate who wrote it. Cost if wrong: an attribution line; no behaviour. How named: quoted in chat. (2026-10-08 03:00 UTC)

> Ruling: R4. Decided: the docs review's findings are fixed in a second docs commit: slice 54 findings 1 no longer says a host over 200 characters gets a 422 (DomainIn.host has only min_length=3; the final-review minor that said so is quoted verbatim in findings 3 with a note that the cap does not exist) (Important 1); the whitespace-only case says the browser pattern already stops it unless the entry holds a dot (Minor 1); slice 53 says the bare pipe cut the Result cell and dropped the Failing text, not that it added a column (Minor 2); the three findings say the ledger records the merge decision as 'merge', without quoting chat words (Minor 3); slice 53 drops 'with awk' and says the rendering fault was raised in the chat handoff, not in a repo file (Minor 4); slice 52 says M2 was run against the old test and M1 was not (Minor 5); slice 54 says the live check was offered in the plan file and the user did not ask for one (Minor 6). Found by: the docs reviewer (Opus 5.5), 2026-10-08. Why: a false claim and overstatements of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 03:04 UTC)

The slice 54 ledger has no R1: the R1 of slices 52 and 53 (no separate final review for a one-commit branch) was not applied here, because slice 54 changes source and got a final whole-branch review.

There is no `Correction to R` line in the ledger.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): mutation M4 (the domain note rendered inside the add-domain form condition) is caught by no test because no test renders the SERP page; a 409 note would then be hidden with the form."
  - Note (2026-10-09, after slice 58, PR #116): fixed by the page render test (docs/findings-slice58.md §1).
- "Task 1: minor (deferred): format.test.ts:8 imports domainNote between ciText and crawlNote, out of alphabetical order; lint passes, cosmetic."
  - Note (2026-10-09, after slice 58, PR #116): fixed: `domainNote` now follows `crawlNote` (docs/findings-slice58.md §1).
- "Final review: minor (deferred): two simultaneous submits of the same host still give a 500 from the unique constraint and reach the error page (findings-slice48 R2); the domain is added anyway. The slice 54 findings must say so."
  - Note (2026-10-11, after slice 59, PR #118): fixed: a simultaneous duplicate now gets 409, through one INSERT … ON CONFLICT DO NOTHING (docs/findings-slice59.md §1).
- "Final review: minor (deferred): this reverses the slice 48 user decision (browser pattern over catch-and-note, findings-slice48 lines 13 and 77, and line 5 says a refused host shows the error page); the slice 54 findings must name the reversal and the user decision that authorised it (the chat approval of the slice 54 design on 2026-10-08). The historical doc is not edited."
  - Note (2026-10-12, slice 62): closed: findings-slice54 §1 names the reversal ("This reverses a slice 48 user decision") and the user's approval of the slice 54 design in chat on 2026-10-08, and findings-slice48 carries a dated note under the minor about refused hosts; the chat approval itself cannot be checked from the repo.
- "Final review: minor (deferred): one note text covers every 422 cause (IP, no dot, whitespace-only after trim, over 200 characters); the copy names IPs specifically but is still correct advice for the rest."
  - Note (2026-10-08, docs review): "over 200 characters" is wrong; `DomainIn.host` (apps/api/bsi_api/routers/brands.py) has `min_length=3` and no upper cap, so a long host with a dot is accepted. The other causes stand.
  - Note (2026-10-11, after slice 59, PR #118): fixed: `DomainIn.host` is capped at 200 like the other host fields, so the one note covers every 422 the form can cause (docs/findings-slice59.md §1).
