# Slice 48 findings: an add-domain form on the Brand SERP page

## 1. What was built

For an active brand with no declared domain, the Brand SERP page (`apps/web/src/app/(app)/b/[id]/serp/page.tsx`) now shows, under "Not audited automatically: the brand has no declared domain.", a form with a visible "Domain" label and field (`required`, `pattern=".*\..*"`, so the browser refuses a host with no dot), an "Add domain" button, and the warning "Adding a domain lets the weekly Brand SERP audit run for this brand: paid Google searches, counted against the daily budget. The first can run within minutes." (linked with `aria-describedby`). A new server action, `addDomain` (`serp/actions.ts`), posts the trimmed host to the existing `POST /v1/brands/{id}/domains` and redirects to `/b/{id}/serp`, where the line then reads "Audited automatically once a week." A host the browser passes but the API refuses, or a duplicate, shows the error page: a generic message in production, the status, title and any detail in development. This fixes the slice 47 deferred minor (findings-slice47 §3, R7). Web only: no API, migration or backend change. The weekly site audit a domain also enables spends nothing (`"audit_crawl": 0`, R6).

Spec: docs/superpowers/specs/2026-10-07-slice48-add-domain-form-design.md (R1 entered in `08de0dc`, R2 and R3 in `bec426a`, R4 in `e7e73a5`, where the user approved the spec; R5 added during planning in `3243350`; R6, R7, R8 and the last three deferred minors added by the post-merge docs commits). Plan: docs/superpowers/plans/2026-10-07-slice48-add-domain-form.md (Task 1). Merged via PR #98 (https://github.com/aiagencyindia-lab/bsi-platform/pull/98), main `29b03fa`.

**Code**: apps/web/src/app/(app)/b/[id]/serp/actions.ts (`addDomain`); apps/web/src/app/(app)/b/[id]/serp/page.tsx (the form, label and warning, shown when `brand.status === "active" && domains.length === 0`); apps/web/src/app/(app)/b/[id]/serp/actions.test.ts (new, two tests; web 50 → 52).

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the no-domain line deferred minor"; approach "Add-domain form" (over naming the API route, or a full domains screen) and form copy "Warning only" (over warning plus a note, or no warning), each after approaches written in chat; Section 1 and Section 2 approved in chat."
- "User decisions (2026-10-07, after the spec review, re-asked because the error-page fact behind Section 1 was wrong): "Browser pattern" for a refused host (over catching the error and returning with a note, or leaving it as is), and "Visible label" (over aria-label only), each after approaches written in chat."
- "User decision (2026-10-07, after the spec re-review): the revised Section 1 (visible label, pattern, the reworded warning, the corrected error behaviour) was shown in chat and approved ("Yes")."
- "User decisions (2026-10-07, added to the ledger after the docs review, from the chat): after "go ahead" and the confirming question, "Approve, write plan" approved the spec as it stood at e7e73a5 (including that unreviewed commit); execution "Subagent-driven"; "Push and create a Pull Request" at the finishing menu."

**Results** (quoted from the ledger):
- "Task 1: implementer a22b0d3c877621f8a, commit 2692bd5 (trailer Opus 5.5 checked); report: red 2x TypeError: addDomain is not a function, Tests 2 failed (2); green Tests 2 passed (2); gate exit 0, gate-task1.txt Tests  52 passed (52), Compiled successfully, no API problem line, gen:check no diff; controller check: the three files are byte-identical to the spec's proof copies."
- "Controller gates on 2692bd5: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 189.19s (0:03:09), mypy Success, metrics coverage 100%; web gate exit 0, Tests  52 passed (52), Compiled successfully, no API problem line."
- "PR opened for slice48-add-domain-form on head 2692bd5 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
- "CI run 37602929691: success on 2692bd5, 1753 passed, 2 deselected, 2 warnings in 155.96s (0:02:35); web Tests  52 passed (52), Compiled successfully."
- "PR #98 merged by the controller after the user said "go ahead" to "Should I merge PR #98?" (2026-10-07); merge commit 29b03fa; local main fast-forwarded to 29b03fa; branch deleted on GitHub and locally."
- "Gates on main 29b03fa after merge: backend 1753 passed, 2 deselected, 2 warnings in 190.62s (0:03:10), coverage 100%; web Tests  52 passed (52), Compiled successfully."

**Reviews**, as the ledger records them (the spec review and re-review lines were added to the ledger after the plan review, from the review reports):
- "Spec review (a862091404531fe1d, 08de0dc): "Spec ready? No"; 0 Critical, 1 Important, 7 Minor."
- "Spec re-review (a5fdc2e90f6b2c82c, bec426a): "Spec ready? Yes"; 0 Critical, 0 Important, 4 Minor. (Both lines added to the ledger after the plan review, 2026-10-07, from the review reports.)"
- "Plan review (a5ed8116671076bb7, e7e73a5 and 7f11bfa): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Plan re-review (a9464f5394b9268d3, 3243350): "Ready to execute? Yes"; 0 findings."
- "Task 1: task review (a9ea918cd380d1fe6, 3243350..2692bd5): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows gen completing and git status shows no openapi.json or schema.d.ts change, so gen:check passed; the report holds the RED and GREEN lines."
- "Final review (a7e496a90b2a79544, 5d6326f..2692bd5): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; every deferred minor triaged "Not required before merge"."

**Commits** (`git log --oneline --reverse 5d6326f..29b03fa^2`, oldest first):

| Commit | Subject |
|---|---|
| 08de0dc | docs(spec): slice 48, an add-domain form on the Brand SERP page |
| bec426a | docs(spec): slice 48 review fixes: error page facts, pattern, label, warning (R2, R3) |
| e7e73a5 | docs(spec): slice 48 re-review wording fixes (R4) |
| 7f11bfa | docs(plan): slice 48, the add-domain form |
| 3243350 | docs(plan): slice 48 plan review fixes (R5) |
| 2692bd5 | feat(web): add a domain from the Brand SERP page |

## 2. Live check

Not run. The spec names it as optional and asked first. As the ledger records it:

- "Live check (2026-10-07): offered in chat after PR #98 opened, as optional ("I'll only run it if you say so"); the user's next messages were "check CI" twice and "go ahead" to the merge question; not run."

Dev's three brands with no domain (`cf2daeb5`, `1c184fe8`, `6eb29bf2`) are active and would show the form. No migration; dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the error test silences console.error with vi.spyOn (api() logs every non-2xx answer) and afterEach calls vi.restoreAllMocks(); neither was in the Section 2 text. Found by: the controller, running the proof. Why: the gate's test output stays free of a logged "API problem" line, and the spy does not leak into other tests. Cost if wrong: an unexpected console.error in that test would be hidden. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: the spec review's other findings are fixed: the spec states what a refused host shows (production: a generic error with a digest, the API problem in the web server log; development: "422 Validation failed (request …)" with no reason, since the 422 carries its reasons in errors[] and no detail) (Important 1); "no web page adds a domain" replaces "no web page calls the domains API" (Minor 1); a later duplicate submit is a 409 and a same-moment double submit is a 500 from the unique constraint, both after the domain was added (Minor 2); the warning says "lets the weekly Brand SERP audit run for this brand" instead of "starts" (Minor 3); the live check removes the domain before the worker next starts and names the delete's re-flag (Minor 5); the untested page condition is its own ruling, R3 (Minor 7). Minor 6 (chat-only claims) is left. Found by: the spec reviewer (Opus 5.5, a862091404531fe1d), 2026-10-07. Why: wrong or overstated statements of mine. Cost if wrong: none to behaviour beyond the warning's wording. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R3. Decided: no test covers the page's form condition (brand.status === "active" && domains.length === 0) or its attributes (label, pattern, aria-describedby); the action tests cover addDomain only. Found by: the spec reviewer (Minor 7) and the controller. Why: the repo has no tests for Server Component pages; the condition is the case serpSchedule's test pins for the no-domain line. Cost if wrong: a wiring slip (the form shown for an archived brand, or hidden for a no-domain brand, or a dropped pattern) would ship unnoticed by the gate. How named: in chat, 2026-10-07, after the spec review.

Note (2026-10-09, after slice 58, PR #116): the Brand SERP page now has a render test (docs/findings-slice58.md §1); it checks the form's condition, label, `pattern`, `aria-describedby` and cost paragraph.

> Ruling: R4. Decided: the spec re-review's minors are fixed: the Design names walkaroo. and www.walkaroo as hosts the pattern passes and the API refuses (Minor 1); the error text gives the development message for each cause (422, 409, 500) (Minor 2); the live check keeps the worker's conditions (credentials, budget room) and says an active brand with no domain (Minor 3); the Context records that the revised Section 1 was shown and approved (Minor 4). Found by: the spec re-reviewer (Opus 5.5, a5fdc2e90f6b2c82c), 2026-10-07. Why: incomplete statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the plan review's three minors are fixed: Step 2 names "a Failed Tests 2 banner" instead of quoting its dashes (Minor 1); Step 5 says the gate file, not its stdout, has no API problem line (Minor 2); departure 2 adds the spec's Prettier check (Minor 3). Found by: the plan reviewer (Opus 5.5, a5ed8116671076bb7), 2026-10-07. Why: inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R6. Decided: no final fix wave. Minor 1 (a brand deleted between render and submit shows the not-found page) and Minor 4 (no real issue) need no change; Minor 2 (does the site audit cost money?) is answered no: JOB_ESTIMATES sets "audit_crawl": 0 with the comment "HTTP only: no model, no spend" (apps/workers/bsi_workers/worker.py:142), so the warning names the only paid audit; Minor 3 (brand_id from the hidden field is put into the path unencoded, as in runSerpAudit and setWebhook) is deferred for a change across all actions. The Task 1 brand_id minor's outcome is a 422 from the API's UUID path check, shown on the error page, as the reviewer corrected. Found by: the final reviewer (Opus 5.5, a7e496a90b2a79544), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and every deferred minor triaged "Not required before merge". Cost if wrong: a crafted brand_id could reach another /v1 route with the same tenant key and method, with no privilege gain. How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R7. Decided: the docs review's findings are fixed: the findings name the commit each ruling entered (R1 08de0dc, R2 and R3 bec426a, R4 e7e73a5, R5 3243350) and cite the user's approval of the spec at e7e73a5 from a ledger line added for it (Important 1); "these docs commits" and "the post-merge docs commits" count the commits correctly (Minor 1); the findings say the generic error page is what production shows, and that development shows the status (Minor 2). Found by: the docs reviewer (Opus 5.5, ae42920beb0944161), 2026-10-07. Why: an unrecorded claim and inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

> Ruling: R8. Decided: the docs re-review's two minors are fixed: findings §1 says development shows "the status, title and any detail" (a duplicate's 409 includes the host) (Minor 1); the spec says the last three deferred minors and the live-check note were added by the first post-merge docs commit, a2d82f7 (Minor 2); then a third scoped re-review, as the user chose "Fix, re-review" when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5, a88335378dae7b06f), 2026-10-07. Why: inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

There is no `Correction to R` line in the ledger.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec review minor 6, the classification line, the chat approvals and the ledger quotes cannot be checked from the repo (R2)."
- "Task 1: minor (deferred): a host the pattern passes but the API refuses (an IP address, walkaroo., www.walkaroo) lands on the error page, not an inline message; the user chose this (browser pattern over catch-and-note)."
  - Note (2026-10-08, after slice 54, PR #108): fixed; a 422 or 409 from the add-domain post now redirects to the Brand SERP page with a note, reversing the browser-pattern decision above with the user's approval of the slice 54 design (docs/findings-slice54.md §1). Two simultaneous submits still reach the error page through the unique-constraint 500 (R2 above).
- "Task 1: minor (deferred): a missing brand_id becomes the string "null" and posts to /brands/null/domains; the hidden field always sets it, and runSerpAudit has the same pattern."
- "minor (deferred): final review minor 3, brand_id from the hidden field goes into the API path without encodeURIComponent; the same in runSerpAudit and setWebhook; fix across all server actions together (R6)."
  - Note (2026-10-07, after slice 49, PR #100): fixed; every value in an API path, in server actions and pages, now goes through seg(), and api() refuses a path fetch would not send as written (docs/findings-slice49.md §1).
