# Slice 71 findings: vitest 3.2.7 → 5.0.4, vite pinned to ^7.3.6, and the redirect mock reset

## 1. What was built

Slice 71 moves the web app's test runner to vitest 5.0.4, a dev-only change for four Dependabot alerts. It merged as PR 151 (40aa797) at 2026-10-14T11:06:23Z.

In `apps/web/`, the command was `npm ci` then `npm install -D vitest@5.0.4 vite@7.3.6 --no-fund`, with npm 10.9.8 and Node v22.23.0. It changes 33 lock entries plus the root entry:
- 10 changed, among them vitest, @vitest/mocker and @vitest/spy 3.2.7 → 5.0.4;
- 19 removed, among them tinypool and vite-node;
- 3 added.

It also adds a direct `"vite": "^7.3.6"` devDependency, which keeps vite on 7.x; the lock holds 7.3.6. `vitest.config.ts` and the tests are unchanged.

A follow-up, PR 152 (df9f977, merged at 13:10:55Z), resets the `redirect` mock in `api.test.ts`'s `afterEach`. It is covered in §1.1.

| Alert | Package | Severity | Advisory | State after merge |
|---|---|---|---|---|
| 5 | @vitest/mocker | medium | GHSA-82fw-gwwq-j7x9 | fixed |
| 6 | vitest | medium | GHSA-82fw-gwwq-j7x9 | fixed |
| 8 | tinypool | critical | GHSA-85c8-ppgw-ccpr | fixed |
| 9 | tinypool | critical | GHSA-5gmw-xhrv-c9v3 | fixed |

**Why vite is pinned.**
- Dependabot's PRs 144 and 145 both failed `gates`, because their lock moved vite to 8.x. PR 145's run 38456124574 failed at `vitest.config.ts(7,14)`, TS2769 `'jsx' does not exist in type 'ESBuildOptions'`.
- The proof's plain `npm install -D vitest@5.0.4` did the same: vite 7.3.6 → 8.3.4, `tsc` exit 2, and 3 test files failed.
- With `vite@7.3.6` added to the command, vite stays 7.3.6, `tsc` exits 0, and the tests give `93 passed (93)`.
- The user chose the devDependency pin over Vite 8 or an npm `overrides` entry.

**Before the PR.**

- **Lock check.** A named allow-list of the 33 entries plus the lock's SHA-256 (`9702766f…6f99`).
  - The SHA-256 check was added after spec review round 1 found the first version of the script passed four tamper locks.
  - On the implementer's run the check printed `SHA256-OK`, `FROZEN-OK` for esbuild 0.28.2 and vite 7.3.6, 33 OK rows, `ok=33 other=0` and `lockdelta exit 0`. npm reported `added 3 packages, removed 19 packages, changed 10 packages`; the diff stat is 2 files, 124 insertions and 300 deletions.
- **Reproducibility.** The proof copy, the committed files and the plan check, run from the committed plan's own blocks on a fresh copy of main, gave byte-identical `package.json` and `package-lock.json`. `14b-plancheck71.txt` ends `driver exit 0`, then `cmp exit 0` for the two files and `cmp exit 0` for the script.
- **Audit.** `npm audit` listed none of the three advisories after the change (`target GHSA hits: 0`), and still exited 1 for the entries outside this slice.
- **Gates.**
  - Task 2's local gates: backend `1811 passed, 2 deselected in 174.72s` with no warnings; web `RUN v5.0.4`, `Test Files 9 passed (9)`, `Tests 93 passed (93)`, `Next.js 15.5.27`.
  - The controller's own gates on 2b5b79d, each after a saved pre-check: backend `1811 passed, 2 deselected in 168.01s`, `warning hits 0`; web `RUN v5.0.4`, `Tests 93 passed (93)`.
- **Reviews.**
  - The spec took five review rounds and the plan two; Task 1's and Task 2's reviews were clean.
  - The final review raised one Minor, about two commit messages:
    - 2b5b79d (then 9b48a1b) said "The vite line holds vite at 7.3.6"; it now reads "The vite ^7.3.6 line keeps vite on 7.x and the lock holds 7.3.6".
    - The spec commit said the npm command "closes" the alerts.
  - At the user's choice the controller rewrote the messages only. All eight trees are unchanged and every branch commit got a new SHA; a scoped re-review found both points addressed.

**After the merge.**
- PR 151's CI run 38553726954 passed `gates` in 3m43s.
- At the controller's first check (11:06:34Z), alert 5 read `fixed` with `fixed_at` 11:06:28Z, and alerts 6, 8 and 9 with 11:06:29Z.
- Dependabot closed PR 145 at 11:08:39Z and PR 144 at 11:08:41Z; the controller closed neither.
- It also closed PR 149 (next 15.5.27 → 16.4.0) at 11:08:45Z, saying `Looks like next is up-to-date now, so this is no longer needed.`, while postcss alerts 1 to 4 stay open. Why it closed 149 is unknown.

### 1.1 The follow-up: vitest 5 and `restoreAllMocks`

The docs review of this slice's first docs commit found that slice 63's R4 had closed a minor on a vitest 3.2.7 premise: that `vi.restoreAllMocks()` resets a module-mock `vi.fn` (findings-slice63 line 139). The controller probed both versions (out71f/07): test a calls a plain `vi.fn` and the `redirect` mock and queues a throwing once-impl on each, with `restoreAllMocks` in `afterEach`.

| Left for test b | vitest 3.2.7 | vitest 5.0.4 |
|---|---|---|
| call history | cleared | cleared |
| an unused `mockImplementationOnce` | dropped | fires in test b |

The history is cleared on 5.0.4 by its default `clearMocks: true` (3.2.7 defaults to `false`), which runs `vi.clearAllMocks()` before each test and keeps queued implementations. `restoreAllMocks` on 5.0.4 restores `vi.spyOn` spies only. The follow-up spec's review found this mechanism, and it was confirmed in the installed source.

The controller first told the user that history would also leak. That was wrong, and the ledger holds Corrections for it. As a result, the guard test first chosen (`expect(redirect).not.toHaveBeenCalled()` after the `/login` test) passed without the fix, so it guarded nothing. The user then chose the line only.

PR 152 adds three lines to `apps/web/src/lib/api.test.ts`'s `afterEach`, two comment lines and `vi.mocked(redirect).mockReset();`. No test in the suite leaves an unused once-impl today, so nothing failed before the change. The proof (out71f) uses a scratch-only test that queues a throwing once-impl and never uses it:

| Run | Result |
|---|---|
| without the fix, vitest 5.0.4 | the `/login` test fails, `expected [Function] to throw error including 'REDIRECT' but got 'LEAKED'`, `1 failed \| 28 passed (29)`, vitest exit 1 |
| with the fix, vitest 5.0.4 | `29 passed (29)`, exit 0 |
| without the fix, vitest 3.2.7 | `29 passed (29)`, exit 0 |
| the real change alone | `28 passed (28)`, exit 0 |
| web gate | `gate exit 0`, `Tests 93 passed (93)` |

How the follow-up went:
- The follow-up spec took one review round and a clean re-review, and the plan likewise.
- The plan check reproduced the proof copy's file byte for byte. Its first attempt stopped when the disk filled; it was re-run after the user freed space.
- Task 1 (38a54b1) was reviewed clean.
- Task 2's first run was blocked:
  - The test database container had exited (`Exited (255)`, cause unknown), so 692 tests errored on `Connection refused`.
  - The user ran `docker compose up -d db`. Postgres ran automatic recovery, `bsi_test` answered `select 1`, and dev still read migration 0026.
  - The re-run passed: backend `1811 passed, 2 deselected in 126.75s`, web `Tests 93 passed (93)`.
- Task 2's review raised one Minor, the implementer's unfounded report concern that two steps ran together; the report was corrected in a fix round.
- The final review found nothing, and reproduced the red and green runs itself.
- PR 152's CI run 38569039096 passed `gates` in 4m4s.

**Commits** (PR 151, after the message-only rewrite; the ledger names them by their earlier SHAs, see the Correction in §3):

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

**Commits** (PR 152):

| Commit | Subject |
|---|---|
| b19e85f | docs(slice71): spec for the redirect mock reset after vitest 5 |
| 5fda12d | docs(slice71): follow-up spec review round 1, the clearMocks default |
| 845e380 | docs(slice71): plan for the redirect mock reset |
| db7efb0 | docs(slice71): follow-up plan review round 1, two minors |
| 38a54b1 | test(web): reset the redirect mock after each api test |

**Handoff.**
- `apps/web/package.json` has a direct `vite` `^7.3.6` devDependency whose only job is to keep vite on 7.x for vitest 5. Moving to vite 8 means removing it and porting `vitest.config.ts`'s `esbuild: { jsx: "automatic" }` to vite 8's options.
- On vitest 5, a module-level `vi.fn` keeps queued once-impls across `restoreAllMocks` and the default `clearMocks`. `actions.test.ts` uses `redirect.mockClear()`, which keeps them too; no test there queues one.
- Five alerts stay open: postcss 1 to 4 (two high, two medium) and Mako 14 (medium). No Dependabot PR remains for postcss; PR 140 (mako) is the only open Dependabot PR.
- `npm audit` also lists braces GHSA-vfj7-8cjw-p6xm (high, through eslint-config-next). Dependabot alert 7 lists it, auto-dismissed at 2026-10-13T19:34:37Z as a development, transitive dependency.

## 2. Live check

None against the app. The slice's GitHub writes were PRs 151 and 152 and their merges.

## 3. Rulings, decisions, reviews and minors

Every `User decision`, `Review verdict`, `Ruling:`, `Correction`, `Final review:`, `Docs review:` and `Task N: minor` line in the two ledgers, verbatim, in ledger order. A line that holds `<` is quoted inside a code span, so the `<` shows as text and not as HTML.

### 3.1 Slice 71 ledger

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

> Review verdict (2026-10-14): docs review on 40aa797..6c74bb3 (Opus 5.5): Changes needed, 0 Critical, 2 Major, 3 Minor; §3 quotes (30, both ways), dated notes, README rows, R1's edit list, GitHub facts and the commit table checked accurate.

> Docs review: Major: findings line 61 (and ledger line 7) says no Dependabot alert lists braces GHSA-vfj7-8cjw-p6xm; alert 7 lists it, state auto_dismissed at 2026-10-13T19:34:37Z, scope development, relationship transitive - verified by the controller (gh api alerts/7); the controller's earlier check listed open alerts only.

> Correction (2026-10-14): to the Controller check that says no Dependabot alert lists braces GHSA-vfj7-8cjw-p6xm: Dependabot alert 7 lists it (high, apps/web/package-lock.json, development, transitive), auto_dismissed at 2026-10-13T19:34:37Z; the controller had listed open alerts only.

> Docs review: Major: findings line 133 says no deferred minor from findings 47 to 71 is open, but findings-slice63 line 139 (api.test.ts afterEach does not reset the redirect mock) was closed by slice 63's R4 on the premise that vi.restoreAllMocks() resets a vi.fn on vitest 3.2.7, and vitest 5.0.4 does not - verified by the controller (19b-restore-probe: v3.2.7 calls=1 threw=false; v5.0.4 calls=3 threw=true).

> Docs review: minor: some findings facts are held by saved outputs, git or GitHub but not by the ledger (@vitest/mocker and vite-node in §1, the alert table's packages and advisories, seven commit subjects, the plan note's reworded text, the scan hits) - open.

> Docs review: minor: plan line 303 says the findings doc quotes 14b-plancheck71.txt; findings line 27 paraphrases it without naming it - open.

> Docs review: minor: findings lines 5-8 'does three things' undercounts the 33-entry lock change - open.

> User decision (2026-10-14): "yes, start the follow-up fix": the restoreAllMocks regression is fixed in slice 71 through the full process (brainstorm, spec with proof, plan, subagent-driven execution, own PR); the docs PR waits and records it.

> User decision (2026-10-14): follow-up approach "One line in afterEach": vi.mocked(redirect).mockReset() next to the cookies reset in api.test.ts (options shown: one line in afterEach, recommended; mockReset: true in vitest.config.ts; resetAllMocks in api.test.ts).

> User decision (2026-10-14): add a guard test after the /login test asserting redirect has no calls (options shown: add guard test, recommended; no guard test).

> User decision (2026-10-14): follow-up design sections 1-4 approved in chat, one "yes" per section.

> Correction (2026-10-14): to the Docs review Major on findings line 133 and the Controller check on its impact: between tests, vitest 5.0.4 still clears a vi.fn's call history (07-between-tests-fixproof.txt), so the redirect history leak slice 63's minor described does not happen on vitest 5; only an unused queued mockImplementationOnce survives restoreAllMocks between tests. The 19b probe (calls=3) called restoreAllMocks inside one test. The controller told the user history would leak; that was wrong.

> Correction (2026-10-14): to the follow-up guard-test decision: the guard test as designed (expect(redirect).not.toHaveBeenCalled() after the /login test) passes without the afterEach line on vitest 5.0.4 (01-red-guard-only.txt, 29 passed), so it guards nothing; the choice is re-asked.

> User decision (2026-10-14): re-asked after the guard test proved useless: "Line only" - add vi.mocked(redirect).mockReset() to api.test.ts's afterEach, no guard test, tests stay 93 (options shown: line only, recommended; line + guard pair; no code change).

> User decision (2026-10-14): revised follow-up sections 1-4 approved in chat, one "yes" per section (line only; proof red m2b, green, vitest 3.2.7 contrast, exit codes recorded from files; Task 1 without a guard test; findings and the slice 63 note state the narrower fact).

> Review verdict (2026-10-14): follow-up spec review on b19e85f (Opus 5.5): Changes needed, 1 Important (§2 says the history clearing has an unknown mechanism and credits restoreAllMocks; it is vitest 5's default clearMocks: true, and restoreAllMocks clears neither history nor once-impls on 5.0.4), 1 Minor (§5 'the design's Section 2 text' is ambiguous with the spec's own §2); proof table, diff, line references and correctness checked accurate.

> Correction (2026-10-14): to the Controller check and Correction that say vitest 5.0.4 clears call history between tests by an unknown mechanism: the mechanism is vitest 5's default clearMocks: true (vitest defaults chunk line 57; 3.2.7 has clearMocks: false at line 84), which runs vi.clearAllMocks() before each test (index chunk line 8605) and keeps queued implementations; restoreAllMocks on 5.0.4 resets neither a vi.fn's history nor its once-impls - verified by the controller in the installed packages.

> Review verdict (2026-10-14): follow-up spec scoped re-review on 5fda12d (Opus 5.5): Approved, both findings resolved, no new findings; clearMocks defaults, clearAllMocks keeping once-impls and restoreAllMocks touching only spyOn restores checked in the vitest source.

> User decision (2026-10-14): "approved, write the plan" (follow-up spec at 5fda12d).

> Review verdict (2026-10-14): follow-up plan review on 845e380 (Opus 5.5): Approved with 2 Minor (1: the self-review says 'Departures from the spec: one' naming the red run, while its coverage note says red, green and m3 are all not repeated, and spec §5 plans only the gates at execution; 2: Review Focus 2 says Step 3 shows 'one hunk of 3 added lines' but Step 3's grep drops the @@ header, so it shows 3 added lines only); plan bytes, the plan check, every Expected, commands, gating, gates and spec coverage checked accurate.

> Review verdict (2026-10-14): follow-up plan scoped re-review on db7efb0 (Opus 5.5): Approved, both Minors resolved, no new findings; Task 1 Steps 2 and 3 unchanged from the plan-checked 845e380.

> Docs review: Major (findings line 61, braces) - fixed in-slice by R2: the findings handoff says Dependabot alert 7 lists braces GHSA-vfj7-8cjw-p6xm, auto-dismissed at 2026-10-13T19:34:37Z as a development, transitive dependency.

> Docs review: Major (findings line 133, deferred minors) - fixed in-slice by R2: PR 152 adds the redirect reset; a dated note sits under findings-slice63 line 139; the findings record the follow-up in §1.1 and the scan now finds only findings-slice64 line 101.

> Docs review: minor (facts not held by the ledger) - fixed in-slice by R2: Controller check lines now hold the lock rows, the alert packages and advisories, both PRs' commit subjects, 2b5b79d's reworded body text, the 14b-plancheck71.txt result lines and the scan result.

> Docs review: minor (14b-plancheck71.txt not quoted) - fixed in-slice by R2: findings §1 quotes its 'driver exit 0' and 'cmp exit 0' lines.

> Docs review: minor ('does three things') - fixed in-slice by R2: findings §1 gives the 33 lock entries as 10 changed, 19 removed and 3 added, plus the root entry.

> Ruling: R2. Decided: the second docs commit on docs-slice71 (after merging main df9f977 in 0bfc2b1) makes these edits, each from git diff --cached: in docs/README.md, the slice 71 findings row (line 320 as at main df9f977) is reworded to cover the follow-up and name 'every ruling (R1–R2)', with two rows before it for the follow-up's spec and plan; a dated note under findings-slice63 line 139 (as at main df9f977) saying R4's vitest 3.2.7 premise and PR 152's reset; docs/findings-slice71.md rebuilt: the title, §1's lock change as 10 changed, 19 removed and 3 added plus the root entry, the quoted 14b-plancheck71.txt result lines, the reworded commit body, §1.1 on the follow-up (the probe, the clearMocks default, the wrong history claim and the dropped guard test, the proof, Task 2's blocked run, PR 152's merge), PR 152's commit table, the handoff's braces line (alert 7, auto-dismissed) and mockClear line, §2 naming PRs 151 and 152, §3 quoting both ledgers under two headings through this ruling, and the deferred-minors and Still-open sentences; and the follow-up plan's 'Changes made during execution' filled with four bullets. Found by: the docs review of 6c74bb3 (2 Major, 3 Minor) and the follow-up's approved Section 4. Why: the docs review's findings are fixed in-slice, and the follow-up is part of slice 71. Cost if wrong: a findings sentence, note or row states something the ledgers do not hold; the docs re-review is there to catch it. How named: R2, in this ledger, in findings-slice71 §3 and in the README findings row.

> Correction to R2 (2026-10-14): the README findings row R2 names is line 320 as at 0bfc2b1 (the docs branch after merging main), not as at main df9f977, which holds no slice 71 README rows; R2's other references (findings-slice63 line 139 as at main df9f977) and edits stand.

### 3.2 Follow-up ledger (PR 152)

> User decision (2026-10-14): follow-up execution "Subagent-driven" (options shown: Subagent-driven, recommended; Native).

> Review verdict (2026-10-14): follow-up Task 1 review on db7efb0..38a54b1 (Opus 5.5): Spec compliant, Task quality Approved, no Critical/Important/Minor findings; 2 cannot-verify items (Step 1 results only in the report; the commit body's 'no longer' claim about older vitest).

> Review verdict (2026-10-14): follow-up Task 2 review at 38a54b1 (Opus 5.5): Spec compliant, Task quality Approved; 0 Critical, 0 Important, 1 Minor; every Expected line matched; file birth and modify times show each pre-check finished before its gate began.

> Task 2: minor: task-2-report.md's concern that Steps 3 and 4 may have run concurrently is unfounded: task-2-precheck-web.txt was last written at 1791982460.298 and task-2-web-gate.txt was created at 1791982460.357 (verified by the controller with os.stat); the report needs a correction - fix round 1 dispatched to the implementer.

> Task 2: minor fixed in-slice: the implementer appended 'Fix report (round 1)' to task-2-report.md (lines 50-62) withdrawing the concern with the two files' stat times; scoped re-review (Opus 5.5): ADDRESSED, the four gate and pre-check files untouched, tree clean at 38a54b1, no new breakage (note: the Edit tool rewrote the report file, birthtime equals mtime; lines 1-49 hold the original text).

> Final review: dispatched (Opus 5.5) on 40aa797..38a54b1, package review-40aa797..38a54b1.diff

> Final review: 40aa797..38a54b1 (Opus 5.5): Ready to merge: Yes; 0 Critical, 0 Important, 0 Minor; the reviewer reproduced red (LEAKED, 1 failed | 28 passed (29)) and green (29 passed) in its own copy and checked the clearMocks, clearAllMocks, restoreAllMocks and mockReset claims in the vitest 5.0.4 source; recommendation: the docs PR fills the plan's Changes, including Task 2's blocked first run and the report-correction fix round.

> User decision (2026-10-14): follow-up finishing option "Push and create a Pull Request" (options shown: 1 merge locally; 2 push and create a PR; 3 keep as-is).

> User decision (2026-10-14): "check ci then merge" for PR 152.

Deferred minors: none. Under the user's rule of 2026-10-13, a minor in a file the slice touches is fixed in-slice, and every minor above was fixed in this slice. The minor slice 63's R4 had closed on a vitest 3.2.7 premise is now covered by PR 152, with a dated note under findings-slice63 line 139.

Still open: a scripted scan of findings-slice47.md to findings-slice71.md for `minor (deferred)` list items with no dated note or Correction directly after them finds only findings-slice64 line 101. That item is closed by its own file's "Still open:" line (line 107 as at main df9f977). No deferred minor from findings 47 to 71 is open.
