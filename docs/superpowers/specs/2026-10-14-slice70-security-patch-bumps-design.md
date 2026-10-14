# Slice 70: next 15.5.27, sharp 0.35.5, source-map-js 1.2.2 (design)

Date: 2026-10-14 (IST). Base: main 108a82a. Session model Opus 5.5.

## 1. Goal

Close four open Dependabot alerts on the web app's production dependencies with patch-level bumps, in one reviewed change: alert 10 (source-map-js, high), alert 11 (sharp, high), alerts 12 and 13 (next, medium). Dependabot opened them as PRs 139, 142 and 146; this slice applies the same bumps on its own branch, and those three PRs are closed once it merges. The four postcss alerts (1 to 4) and the dev-only vitest and tinypool alerts are later slices.

## 2. Facts the design rests on

- The four alerts, open at main 108a82a (`01-red-on-main.txt`, from `gh api …/dependabot/alerts/<n>`):

| Alert | Package | Severity | Advisory |
|---|---|---|---|
| 10 | source-map-js | high | GHSA-68fv-2mgg-jv7q (event-loop denial of service) |
| 11 | sharp | high | GHSA-wq5f-xc86-pv6w (librsvg dependency) |
| 12 | next | medium | GHSA-mcj8-r9mp-w47p (SSG/ISR cache poisoning) |
| 13 | next | medium | GHSA-4jqv-mc3x-m676 (SSG/ISR cache poisoning, self-hosted) |

- In `apps/web`, `next` is a direct dependency (`"next": "^15.0.0"`); `sharp` comes through next, and `source-map-js` through postcss. `npm ls` on main: next 15.5.25, its postcss 8.4.31 with source-map-js 1.2.1, sharp 0.35.4; vitest 3.2.7's vite carries postcss 8.5.28, which shares the hoisted source-map-js (`01-red-on-main.txt`).
- next 15.5.27 still pins `postcss` 8.4.31 (its npm metadata), and so do next 16.0.0 to 16.2.x; next 16.3.0 is the first release that pins 8.5.23 (16.4.0, the latest, too). So this slice cannot close the postcss alerts and does not try.
- `npm audit --omit=dev` on main reports eight advisories: the four above and four for postcss (GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849, GHSA-qx2v-qp2m-jg93, GHSA-fxqj-rqcc-2cmp) (`02-audit-main.json`).
- Dependabot's PRs 139, 142 and 146 each passed the `gates` check on their own branches (base 35fe8b3).

## 3. User decisions

1. Take PRs 139, 142 and 146 together, as one slice.
2. Approach A: one `slice70` branch where npm applies all three bumps, one PR, and the three Dependabot PRs closed with a pointer afterwards (options shown: A; B, merge the three Dependabot PRs in turn; C, merge their three branches into one and resolve the lockfile).
3. Design sections 1 to 4 approved in chat, one "yes" per section.

## 4. The change

In `apps/web/`, with npm 10.9.8 and Node v22.23.0:

1. `npm install next@15.5.27`
2. `npm update sharp source-map-js`

Both commands exit 0, and a second run on a fresh copy of main produces a `package-lock.json` and `package.json` byte-identical to the first (`03-patch.txt`). If a run at execution resolves a different version for any target (a newer sharp 0.35.x or source-map-js 1.2.x published since, which `npm update` would take), `lockdelta70.py` fails its target check and the slice stops for a user decision, as slice 67 did for truststore. `git diff --stat` on the scratch copy (`10-diffstat.txt`): `apps/web/package-lock.json | 322`, `apps/web/package.json | 2`, 162 insertions and 162 deletions. The `package.json` change, generated from the scratch copy (`09-package-json.diff`):

```diff
diff --git a/apps/web/package.json b/apps/web/package.json
index 991c6bf..bba7269 100644
--- a/apps/web/package.json
+++ b/apps/web/package.json
@@ -13,7 +13,7 @@
     "gate": "npm run typecheck && npm run lint && npm test && npm run build && npm run gen:check"
   },
   "dependencies": {
-    "next": "^15.0.0",
+    "next": "^15.5.27",
     "react": "^19.0.0",
     "react-dom": "^19.0.0",
     "server-only": "^0.0.1"
```

The lockfile delta (`04-lockdelta.txt`, from `lockdelta70.py`) is 38 entries, every one allowed. The script compares every `packages` entry's version between main's lock and the patched one (the root entry is skipped); a version change is allowed only for next, sharp, source-map-js and packages under `@next/`, `@img/` or `@emnapi/` (a scoped allow-list, not a check of what each new version pins), and a same-version entry whose `resolved` or `integrity` changed is never allowed:

| Entries | Versions |
|---|---|
| `next` | 15.5.25 → 15.5.27 |
| `@next/env` and the eight `@next/swc-*` binaries | 15.5.25 → 15.5.27 |
| `sharp` | 0.35.4 → 0.35.5 |
| sharp's 16 `@img/sharp-*` platform packages | 0.35.4 → 0.35.5 |
| sharp's 10 `@img/sharp-libvips-*` packages | 1.3.3 → 1.3.4 |
| `source-map-js` | 1.2.1 → 1.2.2 |

No other entry changes; `node_modules/postcss` stays 8.4.31. Nothing outside `apps/web/` changes.

## 5. Proof

**Before the PR** (scratch copies of main 108a82a, saved outputs):

- Red: `npm ls` shows next 15.5.25, sharp 0.35.4, source-map-js 1.2.1; alerts 10 to 13 are `open`; `npm audit --omit=dev` reports all four advisories (`01`, `02`).
- Green: after §4's two commands, `npm ls` shows next 15.5.27, sharp 0.35.5, source-map-js 1.2.2, postcss 8.4.31 (`05-green-npm-ls.txt`); `npm audit --omit=dev` reports only the four postcss advisories (`06-audit-patched.json`).
- Lock delta: `lockdelta70.py` prints 38 changed entries, 0 outside the allowed set, the three target versions met and postcss unchanged, then `lockdelta PASS` (`04-lockdelta.txt`).
- Mutations, each on its own copy of main:
  - `npm update sharp source-map-js` without the next bump leaves next 15.5.25, and `npm audit --omit=dev` still reports GHSA-4jqv-mc3x-m676 and GHSA-mcj8-r9mp-w47p (`07-mutant-no-next.txt`): the next bump is needed for alerts 12 and 13.
  - `npm install next@15.5.27` without the update leaves sharp 0.35.4 and source-map-js 1.2.1, and `npm audit --omit=dev` still reports GHSA-68fv-2mgg-jv7q and GHSA-wq5f-xc86-pv6w (`07b-mutant-install-only.txt`): the update is needed for alerts 10 and 11.
- Against Dependabot: the union of the three PRs' lock deltas (139: 1 entry, 142: 27, 146: 10) is the same 38 entries at the same versions as ours (`08-dependabot-union-compare.txt`).
- Planned, at execution: both local gates, each after a saved pytest pre-check (§6). The web gate (typecheck, lint, 93 tests, build, `gen:check`) is what exercises next 15.5.27.

**After the merge:**

- Criterion: alerts 10, 11, 12 and 13 read `fixed` in `gh api repos/aiagencyindia-lab/bsi-platform/dependabot/alerts/<n>`, checked a few minutes apart for up to 30 minutes; each observation goes into the ledger when made.
- PRs 139, 142 and 146: if Dependabot has not closed them by then, the controller closes each with a comment naming this slice's PR.
- Any state other than `fixed` after 30 minutes (`open`, `dismissed` or `auto_dismissed`) is a finding reported to the user before the docs PR.

## 6. Verification and merge

1. Pytest pre-check as its own command, output saved; backend gate: expected `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, coverage 100%, `1811 passed, 2 deselected`, no warnings summary.
2. Pre-check again, saved; web gate: expected `Tests  93 passed (93)` after stripping ANSI codes, build green, `gen:check` clean.
3. The §5 checks on the committed branch, saved with UTC headers and exit statuses.
4. PR opened; on "check ci": one `gh pr checks --watch`; `gates` must pass; merge with `--merge --delete-branch`; `git ls-remote --heads origin slice70`.
5. After the merge, the §5 criterion, then closing whichever of PRs 139, 142 and 146 is still open.
6. No live checks against the app, no database migration, no worker, no model or DataForSEO spend. GitHub writes are this slice's PR, its merge and the closing comments only.

## 7. Out of scope

- postcss (alerts 1 to 4) and next 16.3.0 or later (PR 141 bumps to 16.4.0).
- vitest, @vitest/mocker and tinypool (alerts 5, 6, 8, 9; PRs 144 and 145).
- mako (alert 14; PR 140).
- Any repository setting, including Dependabot's.

## 8. Handoff note

`apps/web/package.json` now asks for `next` `^15.5.27`. The postcss copy next 15 pins (8.4.31) keeps alerts 1 to 4 open until a later slice either moves to next 16.3.0 or later (postcss 8.5.23) or overrides that postcss.
