# Slice 72: Next's postcss overridden to 8.5.28 (design)

Date: 2026-10-14 (IST). Base: main 52aac7e. Session model Opus 5.5.

## 1. Goal

Close the four open Dependabot alerts on postcss, alerts 1 to 4, in one reviewed change. All four are on the postcss copy that Next pins, 8.4.31. This change keeps Next 15.5.27 and uses a scoped npm `overrides` entry to move that copy to 8.5.28. No source file changes.

## 2. Facts the design rests on

- The four alerts, open at main 52aac7e (`00-alerts-red.txt`, from `gh api …/dependabot/alerts/<n>` with the `aiagencyindia-lab` token). Each is runtime scope and transitive. **8.5.23 or later closes all four.**

| Alert | Severity | Advisory | First patched | Issue |
|---|---|---|---|---|
| 1 | medium | GHSA-qx2v-qp2m-jg93 | 8.5.10 | XSS via unescaped `</style>` in CSS stringify output |
| 2 | high | GHSA-6g55-p6wh-862q | 8.5.12 | arbitrary file read via attacker-controlled `sourceMappingURL` |
| 3 | high | GHSA-r28c-9q8g-f849 | 8.5.18 | path traversal in previous source-map auto-loading |
| 4 | medium | GHSA-fxqj-rqcc-2cmp | 8.5.23 | incomplete fix of GHSA-6g55-p6wh-862q |

- **Next pins postcss exactly** (npm metadata):
  - next 15.5.27, the newest 15.x, pins `postcss` 8.4.31, and so do next 16.0 to 16.2;
  - next 16.3.0 and 16.4.0 pin 8.5.23.
  - So no Next 15 release closes these alerts.
- **The lock on main holds two postcss copies:**
  - `node_modules/postcss` 8.4.31, Next's, hoisted to the top level, production;
  - `node_modules/vite/node_modules/postcss` 8.5.28, vite's, dev.
  - `npm ls` on main shows `next@15.5.27 → postcss@8.4.31` and `vite@7.3.6 → postcss@8.5.28` (`01-red-npm-ls.txt`).
  - `npm audit` on main lists all four advisories (`02-audit-main.txt`).
- **What postcss processes here.** Next runs postcss at build time on the app's one stylesheet, `src/app/globals.css`, imported by `src/app/layout.tsx`. There is no `postcss.config` and no Tailwind. All four advisories concern attacker-controlled CSS or source maps; this app's CSS is its own.
- **postcss releases:** 8.5.23 on 2026-07-24, 8.5.28 on 2026-09-03, and 8.5.30 (the newest) on 2026-10-12.

## 3. User decisions

1. Slice 72 is the postcss alerts ("start slice 72 with the postcss alerts").
2. Approach: a scoped npm `overrides` entry (options shown: scoped overrides, recommended; upgrade to Next 16.4.0; dismiss the alerts).
3. Version: 8.5.28 (options shown: 8.5.28, recommended; 8.5.23; 8.5.30).
4. Design sections 1–4 approved in chat, one "yes" per section.

## 4. The change

In `apps/web/`, with npm 10.9.8 and Node v22.23.0, starting from main's installed tree (`npm ci` first), run two commands:

```
npm pkg set overrides.next.postcss=8.5.28
npm install --no-fund
```

Both exit 0 (`03-patch.txt`). `npm install` reports `added 1 package, removed 1 package`.

Two runs, each on its own copy of main, produce byte-identical `package-lock.json` and `package.json` (`03-patch.txt`, `03b-run2.txt`, `03c-run-cmp.txt`). The lock's SHA-256 is `14238de8f0184d6e11aa66e9bbae6f228f418085959c3fdc6a0450044d4acdd4`. If a run at execution produces any other lock, `lockdelta72.py` fails on its SHA-256 check and the slice stops for a user decision.

`git diff --stat` (`13-diffstat.txt`): `apps/web/package-lock.json | 56`, `apps/web/package.json | 5`, 33 insertions and 28 deletions. The `package.json` change (`12-package-json-diff.txt`):

```diff
diff --git a/apps/web/package.json b/apps/web/package.json
index 1ef3c8a..8e6c91b 100644
--- a/apps/web/package.json
+++ b/apps/web/package.json
@@ -29,5 +29,10 @@
     "typescript": "^5.6.0",
     "vite": "^7.3.6",
     "vitest": "^5.0.4"
+  },
+  "overrides": {
+    "next": {
+      "postcss": "8.5.28"
+    }
   }
 }
```

The lockfile delta (`04-lockdelta.txt`) is two entries. Next's copy moves out of the top level and is nested under Next:

| Kind | Entry | Version |
|---|---|---|
| Removed | `node_modules/postcss` | 8.4.31 |
| Added | `node_modules/next/node_modules/postcss` | 8.5.28 |

- The root entry `""`, `node_modules/next` (15.5.27), every `node_modules/@next/*` entry, and `node_modules/vite` (7.3.6) are byte-identical to main's.
- No top-level lock key changes. npm does not record `overrides` in the lock.
- vite's own 8.5.28 copy stays where it was.
- `npm ls` after the change shows `next@15.5.27 overridden` with `postcss@8.5.28 overridden` under it (`05-green-npm-ls.txt`).

`lockdelta72.py` (Python standard library only) takes main's lock (`git show 52aac7e:apps/web/package-lock.json`) and the patched one. It exits 1 on any of these:

1. an added, removed or changed entry not on the allow-list above, at the listed versions;
2. an entry whose version is unchanged but whose content changed;
3. any change to the root entry, to `node_modules/next`, to any `node_modules/@next/*` entry, or to `node_modules/vite`;
4. any postcss entry below 8.5.23;
5. any change to a top-level lock key other than `packages`;
6. a patched lock whose SHA-256 is not the proof's.

It also counts its OK rows and fails unless there are exactly 2. The script is embedded in the plan.

## 5. Proof

All runs are on scratch copies of main 52aac7e, with outputs in `out72/`. Each numbered `.txt` output has a UTC header and records the exit status of its main commands, captured from the command itself; where a command's output is filtered, its raw output is saved to a `.raw` file first. The exceptions are:

- `08-precheck.txt`, which is a process listing;
- the `shasum` lines in `03c` and `11`, and the `npm ls` line in `07`, which have no exit line of their own;
- `ci-main.txt` and `ci-proof.txt`, which are raw `npm ci` logs with no header.

The two `.json` files are raw `npm audit` output, summarised in the matching `.txt`.

**Red:**
- Alerts 1–4 are `open` (`00`).
- `npm ls` shows Next's postcss as 8.4.31 (`01`).
- `npm audit` lists all four advisories and exits 1 (`02`).

**Green:**
- `npm ls` shows Next's postcss as `8.5.28 overridden` (`05`).
- `npm audit` lists none of the four. It still exits 1, for the five braces-chain entries (`@next/eslint-plugin-next`, `braces`, `eslint-config-next`, `fast-glob`, `micromatch`), and the totals drop from 7 to 5 (`06`).
- The web gate on the patched copy, after a saved pytest pre-check (`08`: no pytest of this repo running), gives `gate exit 0`: `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)`, `▲ Next.js 15.5.27`, `gen:check` clean (`09`).

**Lock check** (`04`): `lockdelta72.py` prints `SHA256-OK`, `FROZEN-OK` for the root entry, `next` 15.5.27 and `vite` 7.3.6, the two OK rows, `POSTCSS-OK` for both copies at 8.5.28, and `ok=2 other=0`, then exits 0.

`mutants72.py` writes each mutant the way npm writes a lock. The control m0, an unchanged round-trip, is byte-identical and exits 0 (`04m0`). Each tamper mutant exits 1 and prints `OTHER sha256` (`04m1` to `04m6`):

| Mutant | Change | What the check prints |
|---|---|---|
| m1 | a `left-pad` entry added | `OTHER added 'node_modules/left-pad'` |
| m2 | `react`'s `integrity` changed, version kept | `OTHER changed 'node_modules/react' ('19.3.0', '19.3.0')` |
| m3 | `next`'s version set to 16.4.0 | `OTHER frozen-changed 'node_modules/next'` |
| m4 | Next's postcss put back to 8.4.31 | `OTHER added … 8.4.31`, `OTHER postcss below 8.5.23`, and `expected 2 OK rows, got 1` |
| m5 | a root `devDependencies` change | `OTHER frozen-changed ''` |
| m6 | a foreign `resolved` and `integrity` on Next's postcss, version kept | only `OTHER sha256` |

**Floor mutant** (`07`): the override at `8.5.22` instead, on a fresh copy. `npm audit` still lists postcss with GHSA-fxqj-rqcc-2cmp, which is alert 4. So 8.5.23 is the floor that closes the last alert. The file's count of 1 for GHSA-6g55-p6wh-862q comes from alert 4's own title, which names that advisory.

**CSS output** (`10`, `11`): `next build` on the main copy (postcss 8.4.31) and the gate's build on the patched copy (8.5.28) each emit one stylesheet, `.next/static/css/b80fc7d37d2ab1c3.css`. Both are 1,979 bytes with SHA-256 `1f03afaf…afb8`, and `cmp` exits 0. What the browser receives is unchanged.

**Planned at execution:** both local gates, each after a saved pytest pre-check (§6).

**After the merge:**
- Criterion: alerts 1–4 read `fixed` in `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh api repos/aiagencyindia-lab/bsi-platform/dependabot/alerts/<n>`. Check a few minutes apart for up to 30 minutes, and ledger each observation when it is made.
- Any state other than `fixed` after 30 minutes is a finding, reported to the user before the docs PR.
- The alerts are re-listed in all states, not only `open`, together with the open PRs.

## 6. Verification and merge

1. Pytest pre-check as its own command, output saved. Backend gate expected: `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, coverage 100%, `1811 passed, 2 deselected`, no warnings summary.
2. Pre-check again, saved. Web gate expected: `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)` after stripping ANSI codes, `▲ Next.js 15.5.27`, `gen:check` clean.
3. The §5 checks on the branch (`npm ls`, `npm audit` expected to exit 1 with none of the four advisories, and `lockdelta72.py`), saved with UTC headers and exit statuses.
4. Open the PR. On "check ci": one `gh pr checks --watch`; `gates` must pass; merge with `--merge --delete-branch`; then `git ls-remote --heads origin slice72-postcss-override`.
5. After the merge: the §5 criterion.
6. No live checks against the app, no database migration, no worker, no model or DataForSEO spend. The only GitHub writes are this slice's PRs and their merges.

## 7. Out of scope

- Next 16. When the app moves to 16.3.0 or later, which pin postcss 8.5.23 or newer themselves, this override should be removed.
- Mako, alert 14, PR 140.
- The braces chain (alert 7, auto-dismissed) and the other `npm audit` entries.
- postcss 8.5.30 and any range override.
- vite's own postcss copy, which is already 8.5.28.
