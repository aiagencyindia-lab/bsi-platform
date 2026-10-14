# Slice 73 findings: Mako 1.4.1 → 1.4.2 in uv.lock

## 1. What was built

Slice 73 moves Mako from 1.4.1 to 1.4.2 in `uv.lock`, targeting Dependabot alert 14. It merged as PR 156 (85dd214) at 2026-10-14T18:47:46Z.

The change is one command at the repo root, `uv lock --upgrade-package mako==1.4.2` (uv 0.9.28). It changes three lines of `uv.lock`: Mako's version, its sdist URL and hash, and its wheel URL and hash. No `pyproject.toml` and no source file changes. Alembic 1.20.0 is Mako's only user; it requires Mako with no version bound, so no override is needed.

| Alert | Package | Severity | Advisory | First patched |
|---|---|---|---|---|
| 14 | Mako | medium | GHSA-5639-2j2p-m4mx | 1.4.2 |

The advisory is a path traversal through a Windows drive-letter URI in `TemplateLookup`. Alembic uses Mako to render `migrations/script.py.mako` when it generates a migration file (and its own templates on `alembic init`).

**Why our own branch.** Dependabot's PR 140 made the same change. The user chose our own branch with `uv lock` over merging PR 140 directly or dismissing the alert. Our lock is byte-identical to PR 140's (head 01777c2, `cmp exit 0`).

**Before the PR.**

- **Lock check.** `lockdelta73.py` checks a one-entry allow-list, every other package and the lock's header, the new URLs on `files.pythonhosted.org`, and the lock's SHA-256 (`e229c405…caa5f`).
  - Six tamper mutants each fail it, and an unchanged copy passes.
  - Its field checks have two blind spots, which the spec states: a duplicate entry hides behind its twin, and the URL test is a substring match. The SHA-256 check covers both.
  - The implementer's run printed `SHA256-OK`, `ok=1 other=0` and `lockdelta exit 0`. The commit was guarded on that and on the lock's SHA-256.
- **Reproducibility.** A second run on a fresh copy of main and the plan check both gave a byte-identical `uv.lock`.
- **Mako exercised.** `alembic revision` rendered `script.py.mako` with Mako 1.4.1 and with 1.4.2. The two files differ only in their `Create Date` line.
- **What changed in Mako.** The spec reviewer and the final reviewer diffed the two releases. The only code change is `os.path.normpath` to `posixpath.normpath`, which is the same function off Windows.
- **Gates.**
  - Task 2's gates: backend `1811 passed, 2 deselected in 183.73s`, no warnings; web `Tests 93 passed (93)`, `Next.js 15.5.27`.
  - The controller's gates on b5201e1, each after a saved pre-check: backend `1811 passed, 2 deselected in 219.82s`; web `Tests 93 passed (93)`.
- **Reviews.**
  - The spec took three review rounds and the plan three.
  - Task 1's review was clean.
  - Task 2's review raised one Minor: the implementer's report did not mention an `npm ci` deprecation warning for eslint 9.39.5. That warning was already on main, since main's lock pins eslint 9.39.5. A fix round added the note.
  - The final review said Ready to merge: Yes, with no findings. It ran `uv lock --check` and `uv sync --locked` (both exit 0) and rendered a migration with Mako 1.4.2.

**After the merge.**

- PR 156's CI run 38617503335 passed `gates` in 3m59s.
- **Alert 14 read `fixed`** with `fixed_at` 18:48:51Z, 65 seconds after the merge. The poll read it at its second reading, at 18:49:53Z, so spec §5's criterion was met. The dependency-graph SBOM lists mako 1.4.2.
- **PR 140 was closed by Dependabot** at 18:50:16Z, after it commented at 18:50:14Z: `Looks like mako is up-to-date now, so this is no longer needed.`
- **Postcss alerts 1 to 4 also read `fixed`** (read at 18:50:27Z), with `fixed_at` 18:48:50Z (1, 2) and 18:48:51Z (3, 4), beside alert 14's 18:48:51Z, and their dismissal fields are now empty. Slice 72 had dismissed them as `inaccurate` at 15:31Z.
  - The SBOM, created at 18:50:31Z, still lists postcss 8.4.31 alongside 8.5.28. That is consistent with slice 72's inference that GitHub's graph reads Next's declared postcss 8.4.31, which stays unconfirmed.
  - But the alerts turned fixed while that entry remained, so it is not supported that the entry kept them from closing, the reason slice 72's README row and handoff suggested.
  - Why the alerts did not close on slice 72's own merge but closed on this one is unknown.
  - Dated notes under findings-slice72 record this.
- All alerts now: 1 to 6 and 8 to 14 are fixed, and braces 7 is auto-dismissed. No alert and no PR is open.

**Commits** (PR 156):

| Commit | Subject |
|---|---|
| 4dcf9aa | docs(slice73): spec for Mako 1.4.2 in uv.lock |
| 8c3c89e | docs(slice73): spec review round 1, five minors |
| d7bec69 | docs(slice73): spec review round 2, the override reason and the sync logs |
| 82643aa | docs(slice73): plan for the Mako upgrade |
| 175f927 | docs(slice73): plan review round 1, four minors |
| 75455fa | docs(slice73): plan review round 2, the plan check's account |
| b5201e1 | build: upgrade Mako to 1.4.2 in uv.lock |

**Handoff.**
- No Dependabot alert is open and no PR is open.
- `npm ci` in `apps/web` warns that eslint 9.39.5 is deprecated. This was already the case before this slice.

## 2. Live check

None against the app. The slice's GitHub writes were the push of the branch, PR 156 and its merge (which deleted the remote branch). Dependabot closed PR 140 itself; the controller did not touch it.

## 3. Rulings, decisions, reviews and minors

Every `User decision`, `Review verdict`, `Ruling:`, `Correction`, `Final review:`, `Docs review:` and `Task N: minor` line in the ledger, verbatim, in ledger order. A line that holds `<` is quoted inside a code span, so the `<` shows as text and not as HTML.

> User decision (2026-10-14): "start slice 73 with the mako alert".

> User decision (2026-10-14): approach "Own branch, uv lock" (options shown: own branch with uv lock, recommended; merge PR 140 directly; dismiss the alert).

> User decision (2026-10-14): design sections 1-4 approved in chat, one "yes" per section.

> Review verdict (2026-10-14): spec review on 4dcf9aa (Opus 5.5): Changes needed, Minor only, 5 Minor (08-precheck mis-described; sync logs are empty; scope/relationship cited to 00 which lacks them; 'direct lock entry' unclear; lockdelta conditions 1-3 not independent - a duplicate entry hides in the index and the URL test is a substring, the SHA-256 is the backstop); alert, PR 140, PyPI hashes, repo facts, proof outputs, CI, Dependabot and the Mako 1.4.1 -> 1.4.2 code diff (posixpath.normpath only, identical off Windows) checked accurate.

> Review verdict (2026-10-14): spec re-review on 8c3c89e (Opus 5.5): Changes needed, the 5 Minors resolved, 2 new Minor (the 'uv sync -q' claim is in no file; 'own [[package]] entry' is not the reason no override is needed - alembic requires Mako unbounded).

> User decision (2026-10-14): "Fix, re-review" after spec review round 2 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-14): spec re-review on d7bec69 (Opus 5.5): Approved, both Minors resolved, no new findings.

> User decision (2026-10-14): "approved, write the plan" (spec at d7bec69).

> Review verdict (2026-10-14): plan review on 82643aa (Opus 5.5): Approved with 4 Minor (Step 1's grep not Mako-specific and not proving lock = main; working-directory exceptions omit Task 2 Step 4; Review Focus 5 overstates - the gate renders no template; Step 3 records no git diff exit and the branch push is not a listed write).

> Review verdict (2026-10-14): plan re-review on 175f927 (Opus 5.5): Changes needed, the 4 Minors resolved, 1 new Minor (the self-review paragraph said the check did not run Step 1's state check or Step 6, but 10-plancheck73.txt ends with both).

> User decision (2026-10-14): "Fix, re-review" after plan review round 2 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-14): plan re-review on 75455fa (Opus 5.5): Approved, the Minor resolved, prose only, 10-plancheck73.txt's header SHA-256 equals the plan at 175f927.

> User decision (2026-10-14): execution "Subagent-driven" (options shown: Subagent-driven, recommended; Native).

> Review verdict (2026-10-14): Task 1 review on 75455fa..b5201e1 (Opus 5.5): Spec compliant, Task quality Approved, no findings; lockdelta re-run exit 0, lock SHA-256 e229c405, Mako 1.4.2 installed, base lock equals main's.

> Review verdict (2026-10-14): Task 2 review at b5201e1 (Opus 5.5): Spec compliant, Task quality Approved; 0 Critical, 0 Important, 1 Minor; each pre-check finished before its gate (birth/modify times); every Expected line matched.

> Task 2: minor: task-2-report.md says no concerns but does not mention task-2-npm-ci.raw line 1, 'npm warn deprecated eslint@9.39.5: This version is no longer supported...' - fix round 1 dispatched to the implementer.

> Task 2: minor fixed in-slice: the implementer appended 'Fix report (round 1)' to task-2-report.md (the warning verbatim; git diff --stat 04388a7 HEAD -- apps/web empty; main's lock lines 3621-3623 pin eslint 9.39.5); scoped re-review (Opus 5.5): ADDRESSED, the gate and pre-check files untouched, tree clean at b5201e1, no new breakage; it notes 'npm ci exit 0' was echoed to the terminal only, not saved (the brief's command), consistent with npm-ci.raw's 'added 361 packages'.

> Final review: dispatched (Opus 5.5) on 04388a7..b5201e1, package review-04388a7..b5201e1.diff

> Final review: 04388a7..b5201e1 (Opus 5.5): Ready to merge: Yes; 0 Critical, 0 Important, 0 Minor; in its own copy uv lock --check and uv sync --locked exit 0 (Mako 1.4.2), alembic revision renders (Revises: 0026); Mako 1.4.1 -> 1.4.2 code diff is os.path.normpath -> posixpath.normpath plus the version; uv.lock SHA-256 equals PR 140's. Recommendation: report PR 140's state after the merge alongside alert 14's; only the user decides on closing it if it stays open.

> User decision (2026-10-15): finishing option "Push and create a Pull Request" (options shown: 1 merge locally; 2 push and create a PR; 3 keep as-is).

> User decision (2026-10-15): "check ci then merge" for PR 156.

> User decision (2026-10-15): "write them" (the controller writes the docs PR: findings-slice73.md, README rows, the plan's Changes, dated notes under findings-slice72 for alerts 1-4, the deferred-minor scan).

> Correction (2026-10-15): the scan line above ran before findings-slice73.md existed and so covered findings-slice47 to findings-slice72 (26 files); re-run after the findings were built, it covers 47 to 73 (27 files) with the same single hit, findings-slice64.md:101.

> Ruling: R1. Decided: the docs commit on docs-slice73 (from main 85dd214) makes these edits, each from git diff --cached: three rows in docs/README.md after the slice 72 findings row (line 325 as at main 85dd214) for the slice 73 spec, plan and findings, the findings row naming 'every ruling (R1)'; a new docs/findings-slice73.md (§1 the change, the alert table, why our own branch, the pre-PR proof, gates and reviews, the after-merge section with alert 14 fixed at 18:48:51Z, PR 140 closed by Dependabot, postcss alerts 1-4 turning fixed with the SBOM still listing 8.4.31, the commit table and handoff; §2 listing the GitHub writes; §3 quoting the ledger; the deferred-minor and Still-open sentences); the plan's 'Changes made during execution' filled with three bullets; and two dated notes in docs/findings-slice72.md, under its SBOM bullet (line 65 as at main 85dd214) and its handoff alerts bullet (line 86 as at main 85dd214). Found by: the after-merge readings. Why: the slice's results, and the correction to slice 72's inference, are recorded where the next slice will look. Cost if wrong: a docs sentence states something the ledger does not hold; the docs review is there to catch it. How named: R1, in this ledger, in findings-slice73 §3 and in the README findings row.

> Review verdict (2026-10-15): docs review on 85dd214..da5036b (Opus 5.5): Changes needed, 1 Major, 4 Minor; §3 exact both ways (24), the Still-open scan, R1's edits and line references, README placement, the notes' form, banned words, and the GitHub and saved-file facts checked accurate.

> Docs review: Major: the note under findings-slice72's SBOM bullet (and findings-slice73 §1) says slice 72's inference is not supported, but that bullet infers why the SBOM lists 8.4.31, which slice 73's SBOM still shows; only the separate link (the entry kept alerts 1-4 open, stated in slice 72's README row and handoff) is undercut - open.

> Docs review: minor: 'the same second' is wrong for alerts 1 and 2 (fixed_at 18:48:50Z; 3, 4 and 14 at 18:48:51Z) - open.

> Docs review: minor: findings-slice73 says Alembic uses Mako 'only' to render script.py.mako; alembic init also renders alembic.ini.mako and pyproject.toml.mako - open.

> Docs review: minor: findings-slice73 names 'in template.py', which no ledger line holds - open.

> Docs review: minor: the plan says alert 14 'read fixed 65 seconds later' (65 s is fixed_at minus the merge; first read at 18:49:53Z); the slice 72 notes give fixed_at times as read times; the spec README row says 'unchanged rendered migration template' (Create Date differs); 'this slice's merge' in the notes is ambiguous - open.

> Correction (2026-10-15): the Controller check on postcss alerts 1-4 above conflates two claims: slice 72's findings infer that GitHub's graph reads Next's declared postcss 8.4.31 (why the SBOM lists it) - still unconfirmed and consistent with the SBOM at 18:50:31Z; what slice 73's observation undercuts is only the link that this entry kept alerts 1-4 from closing. Also, 'the same second as alert 14' is inexact: 1 and 2 at 18:48:50Z, 3, 4 and 14 at 18:48:51Z.

> Docs review: Major (inference conflated) - fixed in-slice: the SBOM-bullet note and findings-slice73 §1 say the SBOM's 8.4.31 is consistent with slice 72's inference, which stays unconfirmed, and that only the link to alerts 1-4 staying closed is unsupported; the Correction above fixes the ledger line.

> Docs review: minor (same second) - fixed in-slice: 'within one second of alert 14', with 18:48:50Z for 1 and 2 and 18:48:51Z for 3 and 4.

> Docs review: minor (Mako 'only') - fixed in-slice: findings-slice73 adds that alembic init renders Alembic's own templates; the Controller check above holds it.

> Docs review: minor ('in template.py') - fixed in-slice: removed.

> Docs review: minor (read vs fixed_at, 'unchanged', 'this slice's merge') - fixed in-slice: the plan says alert 14's fixed_at was 65 seconds later (first read 18:49:53Z); the notes give fixed_at with the 18:50:27Z read and say 'after slice 72's merge'; the README spec row says 'unchanged apart from its Create Date line'.

> Correction to R1 (2026-10-15): R1's commit is amended (message reworded, content adds the docs review fixes): both findings-slice72 notes are reworded as above, and findings-slice73's Alembic sentence adds alembic init.

> Review verdict (2026-10-15): docs re-review on 7b78392 (Opus 5.5): Changes needed; M1 and m1-m4 addressed; 4 new Minor (N1 the fix lines and Correction to R1 describe the edits inexactly; N2 'within one second' exceeds second-precision fixed_at; N3 'it' in the README findings row and the commit message points at PR 140's closing; N4 the commit message says both notes call the 8.4.31 link unsupported, but only the SBOM-bullet note does); §3 exact both ways (37).

> Docs review: minor (N1, N2, N3, N4) - open.

> Correction (2026-10-15): the fix lines above describe the edits inexactly. The Major fix line should read 'only the link that the entry kept alerts 1-4 from closing is unsupported' (not 'staying closed'). The m4 fix line is wrong about the notes: the SBOM-bullet note says 'after slice 72's merge' and gives fixed_at; the handoff note gives fixed_at and the 18:50:27Z read, and it was rewritten to say only that alerts 1-4 are now fixed, not dismissed, with their dismissal fields empty (it dropped its earlier 'did not keep them open' and 'why ... unknown' clauses). The README findings row also changed 'slice 72's inference about why they stayed open' to 'slice 72's suggested reason they stayed open'.

> Docs review: minor (N1, N2, N3, N4) - fixed in-slice: the Correction above restates the fix lines; README findings row, both findings-slice72 notes and findings-slice73 §1 give the bare fixed_at times beside alert 14's 18:48:51Z and name alert 14; the commit message is reworded to match the notes.

> Correction to R1 (2026-10-15): the amended commit's edits are: findings-slice73 §1's postcss bullet and the README findings row give fixed_at 18:48:50Z to 18:48:51Z beside alert 14's 18:48:51Z and 'slice 72's suggested reason they stayed open'; the SBOM-bullet note says the 8.4.31 entry is consistent with slice 72's unconfirmed inference and that it is not supported that the entry kept alerts 1-4 from closing; the handoff note says alerts 1-4 are now fixed, not dismissed, with fixed_at, empty dismissal fields and the 18:50:27Z read; the README spec row says 'unchanged apart from its Create Date line'; the plan's Changes say alert 14's fixed_at was 65 seconds after the merge; findings-slice73's Alembic sentence adds alembic init.

> User decision (2026-10-15): "Fix, re-review" after docs review round 2 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-15): docs re-review on d772075 (Opus 5.5): Changes needed; N1-N4 resolved (fixed_at checked on GitHub: 1, 2 18:48:50Z; 3, 4, 14 18:48:51Z); 1 new Minor (P1: the latest Correction to R1 puts the README row's wording in findings-slice73 §1 too); §3 exact both ways (43).

> Docs review: minor (P1) - open.

> Correction (2026-10-15): the latest Correction to R1 is inexact about which file holds which wording. The README findings row gives 'fixed_at 18:48:50Z to 18:48:51Z, beside alert 14's 18:48:51Z' and 'slice 72's suggested reason they stayed open'. findings-slice73 §1's postcss bullet gives 'fixed_at 18:48:50Z (1, 2) and 18:48:51Z (3, 4), beside alert 14's 18:48:51Z', and its sub-bullet ends 'the reason slice 72's README row and handoff suggested'. The rest of that Correction to R1 stands.

> Docs review: minor (P1) - fixed in-slice: the Correction above gives each file its own wording; no docs text changed besides the §3 quotes.

> User decision (2026-10-15): "Fix, re-review" after docs review round 3 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-15): docs re-review on 19838a5 (Opus 5.5): Approved, P1 resolved, no new findings; §3 exact both ways (48). The commit that quotes this line is quote-only and unreviewed.

Deferred minors: none. Under the user's rule of 2026-10-13, a minor in a file the slice touches is fixed in-slice; every minor above was fixed in this slice.

Still open: a scripted scan of findings-slice47.md to findings-slice73.md for `minor (deferred)` list items with no dated note or Correction directly after them finds only findings-slice64 line 101, which its own file's "Still open:" line closes (line 107 as at main 85dd214). No deferred minor from findings 47 to 73 is open.
