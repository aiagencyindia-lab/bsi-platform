# Slice 72 findings: Next's postcss overridden to 8.5.28

## 1. What was built

Slice 72 moves the postcss copy that Next 15.5.27 pins from 8.4.31 to 8.5.28, using a scoped npm `overrides` entry, and targets Dependabot alerts 1 to 4. It merged as PR 154 (126ae2d) at 2026-10-14T14:53:37Z.

In `apps/web/` the commands were `npm ci`, then `npm pkg set overrides.next.postcss=8.5.28` and `npm install --no-fund` (npm 10.9.8, Node v22.23.0). They add this block to `package.json`:

```json
"overrides": {
  "next": {
    "postcss": "8.5.28"
  }
}
```

The lock changes in exactly two entries:
- `node_modules/postcss` 8.4.31 is removed;
- `node_modules/next/node_modules/postcss` 8.5.28 is added.

Next stays at 15.5.27. The root entry, `node_modules/next`, every `@next/*` entry and `node_modules/vite` are byte-identical to main's. vite's own postcss copy was already 8.5.28 and stays where it was. No source file changes.

| Alert | Severity | Advisory | First patched |
|---|---|---|---|
| 1 | medium | GHSA-qx2v-qp2m-jg93 | 8.5.10 |
| 2 | high | GHSA-6g55-p6wh-862q | 8.5.12 |
| 3 | high | GHSA-r28c-9q8g-f849 | 8.5.18 |
| 4 | medium | GHSA-fxqj-rqcc-2cmp | 8.5.23 |

**Why an override.** No Next 15 release fixes these alerts:
- next 15.5.27 is the newest 15.x and pins `postcss` 8.4.31 exactly;
- next 16.0 to 16.2 pin 8.4.31 too, and 16.3.0 and 16.4.0 pin 8.5.23.

The user chose the scoped override over a Next 16.4.0 upgrade or dismissing the alerts. They chose 8.5.28 over 8.5.23 and 8.5.30: 8.5.28 was already in the lock through vite, and 8.5.30 was two days old.

Next runs postcss on the app's one stylesheet, `src/app/globals.css`. There is no `postcss.config` and no Tailwind.

**Before the PR.**

- **Lock check.** `lockdelta72.py` checks a named two-entry allow-list, the frozen root, `next`, `@next/*` and `vite` entries, a postcss floor of 8.5.23, and the lock's SHA-256 (`14238de8…acdd4`).
  - Six tamper mutants each fail it, and an unchanged round-trip passes.
  - The implementer's run printed `SHA256-OK`, `ok=2 other=0` and `lockdelta exit 0`.
  - The commit was guarded on that and on `package.json`'s SHA-256 (`ceea9248…7f3f`).
- **Reproducibility.** Three runs on fresh copies of main gave byte-identical files (`cmp package-lock.json exit 0`, `cmp package.json exit 0`), and so did the plan check.
- **Audit.** `npm audit` on main listed all four advisories, with 7 entries in total. After the change it listed none of them and had 5 entries: the braces chain, which is out of scope.
- **Floor.** With the override at `8.5.22` instead, GHSA-fxqj-rqcc-2cmp (alert 4) was still listed. That is consistent with its first patched version, 8.5.23.
- **CSS output.** `next build` on main and on the patched copy each emit `.next/static/css/b80fc7d37d2ab1c3.css`: 1,979 bytes, SHA-256 `1f03afaf…afb8`, `cmp exit 0`. What the browser receives is unchanged.
- **Gates.**
  - Task 2's gates: backend `1811 passed, 2 deselected in 160.07s`, no warnings; web `RUN v5.0.4`, `Tests 93 passed (93)`, `Next.js 15.5.27`.
  - The controller's gates on 86237bf, each after a saved pre-check: backend `1811 passed, 2 deselected in 144.52s`; web `Tests 93 passed (93)`.
- **Reviews.**
  - The spec took four review rounds. The plan took one, plus a re-review.
  - The plan check had three earlier attempts:
    - one failed on the controller's driver bug (the script was written as `lockdelta71.py`);
    - one exposed a plan defect (`npm ls` printed Unicode tree characters where the plan expected ASCII), fixed with `--unicode=false`;
    - one ran clean before the plan review's fixes.
  - Task 1's and Task 2's reviews were clean.
  - The final review said Ready to merge: Yes, with no findings. It ran `npm ci` on a fresh copy of HEAD (override honoured, no 8.4.31 left), checked that Next's `require('postcss')` resolves to the nested 8.5.28, and rebuilt to the same CSS.

**After the merge.**

- PR 154's CI run 38583992566 passed `gates` in 3m14s.
- **Alerts 1 to 4 did not close.** Every reading from 14:56:04Z to 15:24:42Z, at two-minute intervals, showed all four `open` with `fixed_at` null, so spec §5's 30-minute criterion was not met.
- Main's lock installs postcss only as `node_modules/next/node_modules/postcss` 8.5.28 and vite's 8.5.28. The only `8.4.31` left in it is Next's own declared dependency: the `"postcss": "8.4.31"` line in `node_modules/next`'s `dependencies`, which npm keeps under an override and which the lock check froze by design.
- GitHub's dependency-graph SBOM, built at 15:25Z, still listed postcss 8.4.31 next to 8.5.28. The likely cause is that GitHub reads Next's declared dependency as an installed version. This is an inference and was not confirmed.
- The user chose to dismiss the four alerts as `inaccurate` (options shown: dismiss, recommended; leave open; wait and recheck). They were dismissed at 15:31:39Z to 15:31:43Z with a comment citing PR 154, and read back as dismissed.
- All alerts now: Mako 14 is open; 5, 6 and 8 to 13 are fixed; braces 7 is auto-dismissed; postcss 1 to 4 are dismissed. PR 140 (mako) is the only open PR.
- The controller session that ran the dismissals was a fork of an earlier controller session, and both wrote the finding to the ledger. The poll log has paired readings a few seconds apart from 14:58Z to 15:24Z. The ledger records two explanations that were not reconciled: the first poll still running beside the restarted one, and the earlier session's own poll. Before the dismissals the user said they had closed the earlier session.

**Commits** (PR 154):

| Commit | Subject |
|---|---|
| d3c8401 | docs(slice72): spec for postcss 8.5.28 under a scoped npm override |
| c242815 | docs(slice72): spec review round 1, three minors and the package.json check |
| 557391b | docs(slice72): spec review round 2, run 3 records each cmp |
| 4563547 | docs(slice72): spec review round 3, run 3 cited and the proof copy named |
| 7af6371 | docs(slice72): plan for the postcss override |
| c685401 | docs(slice72): plan pins npm ls to ASCII tree characters |
| 224edb0 | docs(slice72): plan review round 1, package.json hash pinned and two Step 1 minors |
| 86237bf | build(web): override Next's postcss to 8.5.28 |

**Handoff.**
- `apps/web/package.json` now has `overrides.next.postcss` set to `8.5.28`. Remove it in the same change that moves Next to a 16.3 or 16.4 release; all ten, 16.3.0 to 16.4.0, pin postcss 8.5.23 themselves (releases after 16.4.0 were not checked).
- The pin is exact. A future postcss advisory on Next's copy needs a manual bump of `overrides.next.postcss`.
- Alerts 1 to 4 are dismissed as `inaccurate`, not `fixed`. GitHub's graph still listed postcss 8.4.31 (the SBOM at 15:25Z), apparently from Next's declared dependency (not confirmed). A future postcss advisory may open the same way on that declared version; check `npm ls postcss` before acting on it.
- The main checkout's own `apps/web/node_modules` was stale (`next@15.5.25 invalid`). No gate uses it.

## 2. Live check

None against the app. The slice's GitHub writes were the push of the branch, PR 154, its merge (which deleted the remote branch), and the dismissal of alerts 1 to 4. The dismissals depart from spec §6.6, which planned only the slice's PRs and their merges; they were the user's choice after the after-merge finding.

## 3. Rulings, decisions, reviews and minors

These are every `User decision`, `Review verdict`, `Ruling:`, `Correction`, `Final review:`, `Docs review:` and `Task N: minor` line in the ledger, verbatim and in ledger order. A line that holds `<` is quoted inside a code span, so the `<` shows as text and not as HTML.

> User decision (2026-10-14): "start slice 72 with the postcss alerts".

> User decision (2026-10-14): approach "Scoped npm overrides" (options shown: scoped overrides, recommended; upgrade to Next 16.4.0; dismiss the alerts).

> User decision (2026-10-14): override version "8.5.28" (options shown: 8.5.28, recommended; 8.5.23; 8.5.30).

> User decision (2026-10-14): design sections 1-4 approved in chat, one "yes" per section.

> Review verdict (2026-10-14): spec review on d3c8401 (Opus 5.5): Approved with 3 Minor (three audit .json files, not two; "8.5.23 is the floor" overstates the 8.5.22 run; release dates are UTC); CI npm ci honours the override, lockdelta72.py, mutants, registry and GitHub facts and the CSS proof checked accurate.

> Review verdict (2026-10-14): spec re-review on c242815 (Opus 5.5): Changes needed, the 3 Minors and the package.json-check observation resolved, 1 new Minor (03c's single cmp exit 0 claimed to cover both files via a command 03c does not record).

> Review verdict (2026-10-14): spec re-review on 557391b (Opus 5.5): Changes needed, the Minor resolved, 2 new Minor (the 'Three runs' sentence did not cite 03d; 'the proof copy' was not identified).

> User decision (2026-10-14): "Fix, re-review" after spec review round 3 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-14): spec re-review on 4563547 (Opus 5.5): Approved, both Minors resolved, no new findings.

> User decision (2026-10-14): "approved, write the plan" (spec at 4563547).

> Review verdict (2026-10-14): plan review on c685401 (Opus 5.5): Changes needed, 3 Minor (package.json check narrower than spec §6.3 and not hash-pinned; Step 1's grep -c exits 1 on success; Step 1's npm ci output discarded).

> Review verdict (2026-10-14): plan re-review on 224edb0 (Opus 5.5): Approved, all 3 Minors resolved, no new findings; the guard tested with the proof file (0), a one-space change (1), main's file (1) and a missing file (1).

> User decision (2026-10-14): execution "Subagent-driven" (options shown: Subagent-driven, recommended; Native).

> Review verdict (2026-10-14): Task 1 review on 224edb0..86237bf (Opus 5.5): Spec compliant, Task quality Approved, no Critical/Important/Minor findings, no cannot-verify items; committed blobs' SHA-256s match the spec pins, lockdelta72.py re-run exits 0.

> Review verdict (2026-10-14): Task 2 review at 86237bf (Opus 5.5): Spec compliant, Task quality Approved, no findings; file birth and modify times show each pre-check finished before its gate.

> Final review: dispatched (Opus 5.5) on 52aac7e..86237bf, package review-52aac7e..86237bf.diff

> Final review: 52aac7e..86237bf (Opus 5.5): Ready to merge: Yes; 0 Critical, 0 Important, 0 Minor; the reviewer ran npm ci on a fresh copy of HEAD (override honoured, no 8.4.31 left), checked Next's require('postcss') resolves to node_modules/next/node_modules/postcss 8.5.28, rebuilt (b80fc7d37d2ab1c3.css, 1979 bytes, same SHA-256), and checked the registry facts (all 33 Next 16.0-16.2 releases pin 8.4.31, all 10 16.3-16.4 releases pin 8.5.23). Recommendations for the docs PR: say the override goes when Next moves to 16.3 or later, and that the exact pin means a future postcss advisory on Next's copy needs a manual bump of overrides.next.postcss.

> User decision (2026-10-14): finishing option "Push and create a Pull Request" (options shown: 1 merge locally; 2 push and create a PR; 3 keep as-is).

> User decision (2026-10-14): "check ci then merge" for PR 154.

> User decision (2026-10-14): "write them" (the controller writes the docs PR: findings-slice72.md, README rows, the plan's Changes, the deferred-minor scan; the after-merge section waits for the alert poll).

> User decision (2026-10-14): "continue here, I'll close the other session" (this session is a fork of 'BSI platform handoff and continuation'; that session ran a second alert poll and wrote the two Controller check lines before this session's two near-identical ones; the duplicates are both kept as written).

> User decision (2026-10-14): alerts 1-4 "Dismiss as inaccurate" (options shown: dismiss as inaccurate, recommended; leave open; wait and recheck). Held until the original session 'BSI platform handoff and continuation' is closed (ListAgents still shows it waiting).

> User decision (2026-10-14): "closed it, go ahead and dismiss" (ListAgents still listed the original session as waiting; no ledger line, alert-log write or docs commit from it since this session's last ledger line).

> Ruling: R1. Decided: the docs commit on docs-slice72 (from main 126ae2d) makes these edits, each from git diff --cached: three rows in docs/README.md after the slice 71 findings row (line 322 as at main 126ae2d) for the slice 72 spec, plan and findings, the findings row naming 'every ruling (R1)'; a new docs/findings-slice72.md (§1 the change, the alert table, why an override, the pre-PR proof, gates and reviews, the after-merge section with the 30-minute poll, the lock's remaining declared 8.4.31, the SBOM, the dismissal and the fork, the commit table and handoff; §2; §3 quoting the ledger; the deferred-minor and Still-open sentences); the plan's 'Changes made during execution' filled with three bullets; and a dated note under spec §5's after-merge list (line 137 as at main 126ae2d). Found by: the after-merge finding and the user's dismissal decision. Why: the slice's results and the alerts' unexpected outcome are recorded where the next slice will look. Cost if wrong: a docs sentence states something the ledger does not hold; the docs review is there to catch it. How named: R1, in this ledger, in findings-slice72 §3 and in the README findings row.

> Review verdict (2026-10-14): docs review on 126ae2d..2842dc1 (Opus 5.5): Changes needed, 2 Major, 5 Minor; §3 exact both ways (24), the Still-open scan, R1's edits and line references, README placement, the dated note's form, banned words and the GitHub, lock and alert facts checked accurate.

> Docs review: Major: the alerts' cause is stated as fact in the README findings row, the findings handoff and 2842dc1's commit message, while the ledger holds it as an inference - open.

> Docs review: Major: findings §2 says the slice's GitHub writes were PR 154 and its merge, omitting the push, the remote branch deletion and the four alert dismissals, and the departure from spec §6.6 is not stated - open.

> Docs review: minor: the fork paragraph states the paired readings' cause, 'about 30 minutes' and the session's closure as fact, and 'this session' is ambiguous - open.

> Docs review: minor: the handoff says releases '16.3 or later' pin postcss 8.5.23; only 16.3.0 and 16.4.0 releases were checked - open.

> Docs review: minor: 'plus a scoped re-review' - 'scoped' is not in the ledger - open.

> Docs review: minor: the README plan row reads as if the plan's blocks were compared, not run and their output compared - open.

> Docs review: minor: the Still-open scan result is not in the ledger - open.

> Docs review: Major (cause stated as fact) - fixed in-slice: the README row and the handoff say 'apparently ... not confirmed'; the docs commit is amended so its message does too.

> Docs review: Major (§2 GitHub writes) - fixed in-slice: §2 lists the push, PR 154, the merge with its branch deletion and the four dismissals, and says the dismissals depart from spec §6.6; the spec note says so too.

> Docs review: minor (fork paragraph) - fixed in-slice: it names the controller session that ran the dismissals, gives 14:58Z to 15:24Z, says the two explanations were not reconciled, and says the user said they had closed the earlier session.

> Docs review: minor (16.3 or later) - fixed in-slice: 16.3.0 or 16.4.0, later releases not checked.

> Docs review: minor ('scoped re-review') - fixed in-slice: 're-review'.

> Docs review: minor (README plan row) - fixed in-slice: 'run and their output checked byte-identical'.

> Docs review: minor (scan result not in the ledger) - fixed in-slice: the Controller check above holds it.

> Correction to R1 (2026-10-14): R1's commit is amended (message reworded; content adds the docs review fixes): §2 also lists the push, the branch deletion and the four dismissals with the spec §6.6 departure, and the dated note under spec §5 also says the dismissals were GitHub writes beyond §6.6's plan.

> Review verdict (2026-10-14): docs re-review on 6ea3934 (Opus 5.5): Changes needed; M1, M2 and m1, m3, m4, m5 addressed; m2's fix wrong (N1, minor): the handoff's '16.3.0 or 16.4.0 ... later releases were not checked' contradicts the Final review line (all 10 16.3-16.4 releases pin 8.5.23); §3 exact both ways (40).

> Docs review: minor (N1): the handoff names only 16.3.0 and 16.4.0 and says later releases were not checked, against the Final review's check of all ten - open.

> Correction (2026-10-14): the docs review's m2 premise ('only 16.3.0 and 16.4.0 releases were checked') and its fixed line ('16.3.0 or 16.4.0, later releases not checked') were wrong: the Final review checked all ten 16.3-16.4 releases; the controller accepted the premise without checking the ledger.

> Docs review: minor (N1) - fixed in-slice: the handoff says a 16.3 or 16.4 release, all ten (16.3.0 to 16.4.0) pinning postcss 8.5.23, releases after 16.4.0 not checked.

> Correction to R1 (2026-10-14): the amended commit's handoff line on removing the override reads 'a 16.3 or 16.4 release; all ten, 16.3.0 to 16.4.0, pin postcss 8.5.23 themselves (releases after 16.4.0 were not checked)'.

> User decision (2026-10-14): "Fix, re-review" after docs review round 2 (options shown: Fix, re-review, recommended; Fix, stop).

> Review verdict (2026-10-14): docs re-review on 98e3589 (Opus 5.5): Approved, N1 resolved, no new findings; §3 exact both ways (46). The commit that quotes this line is quote-only and unreviewed.

Deferred minors: none. Under the user's rule of 2026-10-13, a minor in a file the slice touches is fixed in-slice; every minor above was fixed in this slice.

Still open: a scripted scan of findings-slice47.md to findings-slice72.md for `minor (deferred)` list items with no dated note or Correction directly after them finds only findings-slice64 line 101. That item is closed by its own file's "Still open:" line (line 107 as at main 126ae2d). No deferred minor from findings 47 to 72 is open.
