# Slice 71 findings: vitest 3.2.7 → 5.0.4, vite pinned to ^7.3.6

## 1. What was built

Slice 71 moves the web app's test runner to vitest 5.0.4. It is a dev-only change, and it covers four Dependabot alerts (PR 151, merged as 40aa797 at 2026-10-14T11:06:23Z). In `apps/web/`, `npm ci` then `npm install -D vitest@5.0.4 vite@7.3.6 --no-fund` (npm 10.9.8, Node v22.23.0) does three things:
- moves vitest and @vitest/mocker from 3.2.7 to 5.0.4;
- removes tinypool and vite-node;
- adds a direct `"vite": "^7.3.6"` devDependency, which keeps vite on 7.x; the lock holds 7.3.6.

`vitest.config.ts` and the tests are unchanged.

| Alert | Package | Severity | Advisory | State after merge |
|---|---|---|---|---|
| 5 | @vitest/mocker | medium | GHSA-82fw-gwwq-j7x9 | fixed |
| 6 | vitest | medium | GHSA-82fw-gwwq-j7x9 | fixed |
| 8 | tinypool | critical | GHSA-85c8-ppgw-ccpr | fixed |
| 9 | tinypool | critical | GHSA-5gmw-xhrv-c9v3 | fixed |

**Why vite is pinned.** Dependabot's PRs 144 and 145 both failed `gates` because their lock moved vite to 8.x. PR 145's run 38456124574 failed at `vitest.config.ts(7,14)` with TS2769: `'jsx' does not exist in type 'ESBuildOptions'`. The proof's plain `npm install -D vitest@5.0.4` did the same: it moved vite 7.3.6 to 8.3.4, `tsc` exited 2, and 3 test files failed. With `vite@7.3.6` added to the command, vite stays 7.3.6, `tsc` exits 0, and the tests give `93 passed (93)`. The user chose the devDependency pin over moving to Vite 8 or an npm `overrides` entry.

**Before the PR.**

- **Lock check.** It compares the lock against a named allow-list of 33 entries plus the lock's SHA-256 (`9702766f…6f99`).
  - The SHA-256 check was added after spec review round 1. That round found the first version of the script passed four tamper locks.
  - On the implementer's run, the check printed `SHA256-OK`, `FROZEN-OK` for esbuild 0.28.2 and vite 7.3.6, 33 OK rows, `ok=33 other=0` and `lockdelta exit 0`.
  - npm reported `added 3 packages, removed 19 packages, changed 10 packages`, and the diff stat is 2 files, 124 insertions and 300 deletions.
- **Byte-identical locks.** The proof, a plan check run from the committed plan's own blocks on a fresh copy of main, and the committed files are byte-identical.
- **`npm audit`.** It listed none of the three advisories after the change (`target GHSA hits: 0`) and still exited 1 for the entries outside this slice.
- **Gates.**
  - Task 2's local gates: backend `1811 passed, 2 deselected in 174.72s` with no warnings; web `RUN v5.0.4`, `Test Files 9 passed (9)`, `Tests 93 passed (93)` and `Next.js 15.5.27`.
  - The controller's own gates on 2b5b79d, each after a saved pre-check: backend `1811 passed, 2 deselected in 168.01s`, `warning hits 0`; web `RUN v5.0.4` and `Tests 93 passed (93)`.
- **Reviews.**
  - The spec took five review rounds, and the plan two.
  - Task 1's review and Task 2's review were clean.
  - The final review raised one Minor about two commit messages. At the user's choice the controller rewrote the messages only; all eight trees are unchanged, and every branch commit got a new SHA. A scoped re-review found both points addressed.

**After the merge.**
- PR 151's CI run 38553726954 passed `gates` in 3m43s.
- At the controller's first check (11:06:34Z), alert 5 read `fixed` with `fixed_at` 11:06:28Z, and alerts 6, 8 and 9 with 11:06:29Z.
- Dependabot closed PR 145 at 11:08:39Z and PR 144 at 11:08:41Z; the controller closed neither.
- It also closed PR 149 (next 15.5.27 → 16.4.0) at 11:08:45Z, saying `Looks like next is up-to-date now, so this is no longer needed.`, while postcss alerts 1 to 4 stay open. Why it closed 149 is unknown.

**Commits** (PR 151):

| Commit | Subject |
|---|---|
| c079319 | docs(slice71): spec for vitest 5.0.4 with vite pinned to ^7.3.6 |
| 09c60b1 | docs(slice71): spec review round 1, whole-lock SHA-256 and six minors |
| 9860867 | docs(slice71): spec review round 2, three minors |
| 23441ae | docs(slice71): spec review round 3, two wording minors |
| 3a4a58f | docs(slice71): spec review round 4, a comma and the npm ci flags |
| 887f2bb | docs(slice71): plan for vitest 5.0.4 with vite pinned to ^7.3.6 |
| ac1786c | docs(slice71): plan review round 1, six minors and a commit guard |
| 2b5b79d | build(web): bump vitest 3.2.7 → 5.0.4, pin vite ^7.3.6 |

These are the commits after the message-only rewrite. The ledger names them by their earlier SHAs: df4654f, a18822d, 17aa361, be429b5, 327ca73, 0a4baa5, f7874cc and 9b48a1b (see the Correction in §3).

**Handoff.**
- `apps/web/package.json` now has a direct `vite` `^7.3.6` devDependency. Its only job is to keep vite on 7.x for vitest 5. Moving to vite 8 means removing it and porting `vitest.config.ts`'s `esbuild: { jsx: "automatic" }` to vite 8's options.
- Five alerts stay open: postcss 1 to 4 (two high, two medium) and Mako 14 (medium). After PR 149 closed, no Dependabot PR remains for postcss; PR 140 (mako) is the only open Dependabot PR.
- `npm audit` also lists braces GHSA-vfj7-8cjw-p6xm (high, through eslint-config-next), which no Dependabot alert lists. Why is unknown. It is out of this slice's scope and is to be raised with the user.

## 2. Live check

None against the app. The slice's GitHub writes were PR 151 and its merge.

## 3. Rulings, decisions, reviews and minors

Every `User decision`, `Review verdict`, `Ruling:`, `Correction`, `Final review:`, `Docs review:` and `Task N: minor` line in the ledger, verbatim, in ledger order. A line that holds `<` is quoted inside a code span, so the `<` shows as text and not as HTML:

> User decision (2026-10-14): "yes, start slice 71 with Vitest" (the controller's recommended next slice; options shown: vitest 3.2.7 to 5.x; postcss alerts 1-4; mako 14).

> User decision (2026-10-14): approach "Vitest 5, keep Vite 7" (options shown: Vitest 5 keeping Vite 7, recommended; Vitest 5 with Vite 8, as Dependabot did; Vitest 4.1.x).

> User decision (2026-10-14): design sections 1-4 approved in chat, one "yes" per section.

> User decision (2026-10-14): pin vite ^7.3.6 as a devDependency (options shown: pin as devDependency, recommended; go to Vite 8; npm overrides for vite).

> User decision (2026-10-14): revised section 1 approved ("yes"), revised section 2 approved ("yes"), sections 3 and 4 with the new install command confirmed ("yes").

> Review verdict: spec review round 1 (df4654f): Changes needed, 2 Important (I1 caret-range claim false; I2 lockdelta71.py passes four tamper locks), 6 Minor (M1 headers and audit exit status; M2 "second run" ran first; M3 npm ci first and baseline lock; M4 13a gate run before pre-check undisclosed; M5 PR 144 evidence uncited; M6 alerts API needs the aiagencyindia-lab token)

> User decision (2026-10-14): I2 fix = add a whole-lock SHA-256 check as condition 6 (options shown: whole-lock SHA-256, recommended; full-entry comparison; reword only).

> Review verdict: spec review round 2 (a18822d): Changes needed, all 8 round-1 findings resolved (M1 mostly, M6 as to the token), 3 new Minor (line 78 "every .txt has exit status" overstates: 12, 11, 11b pipe; line 98 HTTP 403 claim unevidenced; line 43 "after npm ci" unevidenced for run 1, and the mutants71.py docstring says five)

> Review verdict: spec review round 3 (17aa361): Changes needed, the 3 round-2 findings resolved (finding 1 mostly), 2 new Minor (A: line 78 exception list omits the shasum lines in 03c-run-cmp.txt; B: line 43 "the §4 command" but 03b records it with --no-fund)

> User decision (2026-10-14): "Fix, re-review" after spec review round 3 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict: spec review round 4 (be429b5): Changes needed, A and B resolved, 1 new Minor (line 78 comma lost after exit code 2), 1 optional Minor (line 43 npm ci flags omitted)

> User decision (2026-10-14): "Fix, re-review" after spec review round 4 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict: spec review round 5 (327ca73): Approved, both round-4 findings resolved, no new findings

> User decision (2026-10-14): "approved, write the plan" (spec at 327ca73).

> Review verdict: plan review round 1 (0a4baa5): Approved with 6 Minor (1 plan-check scope overstated; 2 plan check ran on the uncommitted draft; 3 Global Constraints command lacks --no-fund; 4 cd rule omits W and bsi-platform exceptions; 5 W "already exists" untrue until the controller creates it; 6 "condition 2" undefined in the plan and gen:check unnamed), 1 optional (gate Step 6's commit on lockdelta exit 0)

> Review verdict: plan review round 2 (f7874cc): Approved, all 6 round-1 Minors and the optional guard resolved, no new findings

> User decision (2026-10-14): execution "Subagent-driven" (options shown: Subagent-driven, recommended; Native).

> Review verdict (2026-10-14): Task 1 review on f7874cc..9b48a1b (Opus 5.5): Spec compliant, Task quality Approved, no Critical/Important/Minor findings; 2 cannot-verify items (lock produced by npm ci plus the one command rather than by hand; Step 1 results held only in the report).

> Review verdict (2026-10-14): Task 2 review at 9b48a1b (Opus 5.5): Spec compliant, Task quality Approved, no Critical/Important/Minor findings; one observation (the Next serverActions Experiments notice in task-2-web-gate.txt, from the unchanged next.config.ts).

> Final review: dispatched (Opus 5.5) on 7368942..9b48a1b, package review-7368942..9b48a1b.diff

> Final review: 7368942..9b48a1b (Opus 5.5): With fixes, 0 Critical, 0 Important, 1 Minor (9b48a1b body "The vite line holds vite at 7.3.6" overstates, the ^7.3.6 range keeps vite on 7.x and the lock holds 7.3.6; df4654f body "closes Dependabot alerts 5, 6, 8 and 9" claims a post-merge outcome; reviewer placed it in the subject, it is in the body)

> User decision (2026-10-14): "Reword both": message-only rewrite of df4654f and 9b48a1b, trees unchanged, branch unpushed (options shown: Reword both, recommended; Reword 9b48a1b only; Leave both).

> Correction (2026-10-14): after the message-only rewrite the slice71-vitest5 commits are renamed, same trees: df4654f -> c079319, a18822d -> 09c60b1, 17aa361 -> 9860867, be429b5 -> 23441ae, 327ca73 -> 3a4a58f, 0a4baa5 -> 887f2bb, f7874cc -> ac1786c, 9b48a1b -> 2b5b79d; earlier ledger lines keep the old SHAs.

> Final review: fix = message-only rewrite (user's choice), new HEAD 2b5b79d; scoped re-review dispatched (Opus 5.5) on the message changes

> Final review: scoped re-review of the rewrite (Opus 5.5): both findings ADDRESSED; trees, parents, authors, committers and dates identical in all 8 pairs; only the two message lines changed; no new breakage; one style note (ragged wrap in c079319), not an error.

> Final review: complete, clean after the message-only fix; HEAD 2b5b79d.

> User decision (2026-10-14): finishing option "Push and create a Pull Request" (options shown: 1 merge locally; 2 push and create a PR; 3 keep as-is).

> User decision (2026-10-14): "check ci then merge".

> User decision (2026-10-14): "write them" (the controller writes the docs PR: findings-slice71.md, README rows, the plan's Changes made during execution, open-minor scan).

> Ruling: R1. Decided: the docs PR (branch docs-slice71 from 40aa797) makes these edits, each from git diff --cached: a spec note under line 98 (the after-merge criterion met at the first check, 11:06:34Z) and one under line 99 (Dependabot closed PRs 145 and 144 itself, and also PR 149, why unknown), as at main 40aa797; a plan note under line 241 (Step 6's commit body line reworded after the final review, message only, the commit became 2b5b79d); the plan's 'Changes made during execution' filled with four bullets (Task 1, Task 2, the final review's message-only rewrite, the merge and the alerts); three README rows after the slice 70 findings row (line 317 as at main 40aa797), the findings row naming 'every ruling (R1)'; and docs/findings-slice71.md, whose §3 quotes every ledger line of the quoted kinds through this ruling. Found by: the controller, following the process's docs-PR step after the user's 'write them'. Why: the process records each slice in a findings file, README rows and dated notes, and never edits historical spec or plan text. Cost if wrong: a note, row or findings sentence states something the ledger does not hold; the docs review is there to catch it. How named: R1, in this ledger, in findings-slice71 §3 and in the README findings row.

Deferred minors: none. Under the user's rule of 2026-10-13, a minor in a file the slice touches is fixed in-slice; every minor above was fixed in this slice.

Still open: a scripted scan of findings-slice47.md to findings-slice70.md for `minor (deferred)` list items with no dated note or Correction directly after them finds findings-slice63 line 139 and findings-slice64 line 101. Both are closed in their own file's §3: findings-slice63 line 139 by that slice's R4, and findings-slice64 line 101 by that file's "Still open:" line (line 107 as at main 40aa797). No deferred minor from findings 47 to 71 is open.
