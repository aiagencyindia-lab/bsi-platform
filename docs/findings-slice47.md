# Slice 47 findings: the Brand SERP page says whether the brand is audited weekly

## 1. What was built

The Brand SERP page (`apps/web/src/app/(app)/b/[id]/serp/page.tsx`) used to say "Audited automatically once a week." for every brand. It now fetches the brand and its domains alongside the audits and shows one line from `serpSchedule(status, domains)` (`apps/web/src/lib/format.ts`): "Not audited automatically: the brand is archived." for any status other than `active`, "Not audited automatically: the brand has no declared domain." for an active brand with no domain, and "Audited automatically once a week." otherwise. These are the two conditions under which `due_serp_audits()` (migration 0024) considers a brand; its recency, job and failure conditions, missing DataForSEO credentials and budget room are not shown (spec, Context). This fixes the slice 43 deferred minor (findings-slice43 §3, R10). Web only: no API, migration or backend change.

Spec: docs/superpowers/specs/2026-10-07-slice47-serp-schedule-line-design.md (rulings R1–R4 and the correction to R3 as approved by the user at `70d0a4c`; R5 and R6 added during planning; R7, R8 and the last two deferred minors added by these docs commits). Plan: docs/superpowers/plans/2026-10-07-slice47-serp-schedule-line.md (Task 1). Merged via PR #96 (https://github.com/aiagencyindia-lab/bsi-platform/pull/96), main `eb5fb1d`.

**Code**: apps/web/src/lib/format.ts (`serpSchedule`); apps/web/src/lib/types.ts (`Domain`); apps/web/src/app/(app)/b/[id]/serp/page.tsx (three fetches in one `Promise.all`, the rendered line); apps/web/src/lib/format.test.ts (one test, four cases; web 49 → 50).

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the slice 43 once-a-week sentence for no-domain brands"; approach "Web only" (over an API field, or deleting the sentence) and copy "Say why" (over saying nothing, or one generic line), each after approaches written in chat; Section 1 and Section 2 approved in chat; the spec approved ("Approve, write plan", confirming "go ahead"); execution "Subagent-driven"; "Push and create a Pull Request" at the finishing menu."

**Results** (quoted from the ledger):
- "Task 1: implementer acbcdb3c4a9b1c4e4, commit 5e74f54 (trailer Opus 5.5 checked); report: red Tests 1 failed | 28 passed (29), green Tests 29 passed (29), gate exit 0, gate-task1.txt Tests  50 passed (50), Compiled successfully, gen:check no diff; controller check: the four files are byte-identical to the spec's proof copies."
- "Controller gates on 5e74f54: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 237.44s (0:03:57), mypy Success, metrics coverage 100%; web gate exit 0, Tests  50 passed (50), Compiled successfully."
- "PR #96 opened (https://github.com/aiagencyindia-lab/bsi-platform/pull/96) on head 5e74f54 after the user chose "2 PR" at the finishing menu (2026-10-07); the app could not bind it (repo is not this session's checkout); CI gates IN_PROGRESS at the first check."
- "CI run 37591785967: success on 5e74f54, 1753 passed, 2 deselected, 2 warnings in 150.12s (0:02:30); web Tests  50 passed (50), Compiled successfully."
- "PR #96 merged by the controller after the user said "go ahead" to "Should I merge PR #96?" (2026-10-07); merge commit eb5fb1d; local main fast-forwarded to eb5fb1d; remote branch deleted, local branch deleted by gh."
- "Gates on main eb5fb1d after merge: backend 1753 passed, 2 deselected, 2 warnings in 191.24s (0:03:11), coverage 100%; web Tests  50 passed (50), Compiled successfully."

**Reviews**, as the ledger records them (the User decisions line above and the spec and plan review lines were added to the ledger after the merge, from the chat and the review reports):
- "Spec review (af09cbf416947d149, 9228161): "Spec ready? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Spec re-review (a93fa1af2ddf5d188, 2c7ce54): "Spec ready? Yes"; 0 Critical, 0 Important, 1 Minor (the "only 'archived' is ever written" wording)."
- "Plan review (ac5492d2b1c12a649, 017693f and 70d0a4c): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Plan re-review (af86e01e9fb2168cf, 8af3242): "Ready to execute? Yes"; 0 findings."
- "Task 1: task review (a0ff63e05bdf8e1eb, 8af3242..5e74f54): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows Tests  50 passed (50), Compiled successfully and gen completing, and git status shows no openapi.json or schema.d.ts change, so gen:check passed; the report holds the RED and GREEN lines."
- "Final review (ab97f02a1a6ce7aff, 872b849..5e74f54): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; both deferred minors triaged "Not needed before merge"."

**Commits** (`git log --oneline --reverse 872b849..eb5fb1d^2`, oldest first):

| Commit | Subject |
|---|---|
| 9228161 | docs(spec): slice 47, the Brand SERP page says whether the brand is audited weekly |
| 2c7ce54 | docs(spec): slice 47 review fixes: other statuses, other skipped cases (R3) |
| 70d0a4c | docs(spec): slice 47 names the default status in the wording (R4) |
| 017693f | docs(plan): slice 47, the Brand SERP schedule line; spec proof names gen:check (R5) |
| 8af3242 | docs(plan): slice 47 plan review fixes: gen:check wording, live check (R6) |
| 5e74f54 | fix(web): the Brand SERP page says whether the brand is audited weekly |

## 2. Live check

Not run. The spec names it as optional and asked first. As the ledger records it:

- "Live check (2026-10-07): offered in chat after PR #96 opened, as optional ("I'll only run it if you say so"); the user's next messages were "check CI" three times and "go ahead" to the merge question; not run."

Dev's three brands with no domain (`cf2daeb5`, `1c184fe8`, `6eb29bf2`) would show the no-domain line. No migration; dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the helper's comment says "due_serp_audits() (migration 0024) only considers active brands with at least one declared domain" instead of the Section 2 text "mirrors due_serp_audits()". Found by: the controller, running the proof. Why: due_serp_audits() also has recency and job conditions, so "mirrors" overstated what the helper does. Cost if wrong: none to behaviour; comment wording only. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: no test covers the page's wiring (the three fetches and the arguments passed to serpSchedule); the vitest and the mutation table cover the helper only. Found by: the controller, running the proof. Why: the repo has no tests for Server Component pages, and adding a page-test harness is outside this slice; tsc pins the argument types. Cost if wrong: a wiring slip (for example passing aliases.length) would ship unnoticed by the gate. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R3. Decided: spec review Minor 1 is fixed by stating in the spec that any status other than active gets the archived line (only 'archived' is ever written), with no added test; Minor 2 is fixed by naming the two other cases where the page still says weekly (three failed audit_serp jobs in 7 days, and an org budget with no room) next to the missing-credentials case; Minor 3 (R2's example is narrow) is left. Found by: the spec reviewer (Opus 5.5), 2026-10-07. Why: Minor 1 and 2 were unstated or incomplete statements; a test pinning "paused" to the archived line would pin a wrong label for a status nobody writes; Minor 3 is accurate as written. Cost if wrong: if another brand status is ever added, its page says "archived" until the helper is changed. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R4. Decided: spec re-review Minor 1 is fixed: the spec's Design paragraph says "the only other value ever written is 'archived'" instead of "only 'archived' is ever written", and R3's same wording is corrected by a Correction to R3 line. Found by: the spec re-reviewer (Opus 5.5), 2026-10-07. Why: 'active' is also written, as the column default, so the old wording was loose. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the spec's Proof is corrected to say the scratch run's npm run gate passed typecheck, lint, test and build but its last step, gen:check, could not run there (the copy holds only apps/web, so scripts/export_openapi.py is missing); the plan's Step 2 expected output adds the "Failed Tests 1" banner line that its grep also prints; the plan records that its verification ran the same four steps. Found by: the controller, verifying the plan on a fresh copy of main. Why: the Proof listed the gate's passing lines without saying its last step failed in the scratch copy, and Step 2's expected output was incomplete. Cost if wrong: none to behaviour; gen:check runs in the implementer's web gate on the branch, where the backend exists. How named: in chat, 2026-10-07, after verifying the plan.

> Ruling: R6. Decided: the plan review's three minors are fixed: the spec's Proof says gen:check "failed" in the proof run (it ran and could not find scripts/export_openapi.py) and the plan says it "was not run" in the plan verification, naming which run each means (Minor 1); the Frontend constraint reads "Do not run npm run gen other than through the gate's gen:check" (Minor 2); a departure 7 says the spec's optional live check is left to the controller (Minor 3). Found by: the plan reviewer (Opus 5.5), 2026-10-07. Why: unclear or incomplete statements. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R7. Decided: no final fix wave. Minor 1 (any non-active status reads archived) is the deferred Task 1 minor; Minor 2 (the no-domain line names a fix the web app gives no way to make, since domains are declared only through the API) is deferred as a product question; Minors 3 and 4 (the plan's "Changes made during execution", the README rows, findings-slice47 and a slice 47 note in findings-slice43) are done by the post-merge docs commits. Found by: the final reviewer (Opus 5.5), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and both deferred minors triaged "not needed before merge". Cost if wrong: an operator reading the no-domain line has to find the domains API themselves. How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R8. Decided: the docs review's findings are fixed: the spec and findings say R5 and R6 were added during planning, after the user approved the spec at 70d0a4c, and only R7 by the post-merge docs commits (Important 1); a ledger line records the live-check offer and the findings cite it (Minor 1); the findings say only the last two deferred minors were added by these docs commits (Minor 2) and that the User decisions line was also added to the ledger after the merge (Minor 3). Found by: the docs reviewer (Opus 5.5, ae3f5f04aa8dcb9d2), 2026-10-07. Why: overstatements or unrecorded claims of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

The correction, verbatim:

> Correction to R3 (2026-10-07, from the spec re-review): "only 'archived' is ever written" means the only value other than 'active' (the column default) ever written is 'archived'.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec review minor 3, R2's cost line names aliases.length as the example; passing another array's .length (for example audits.length) would also type-check (R3)."
- "Task 1: minor (deferred): a brand status other than active or archived would read "the brand is archived"; only 'archived' is written today (R3)."
- "minor (deferred): final review minor 2, the no-domain line names a fix the web app gives no way to make; domains are declared only through the API (R7)."
