# Slice 71: vitest 3.2.7 to 5.0.4, vite pinned to ^7.3.6 (design)

Date: 2026-10-14 (IST). Base: main 7368942. Session model Opus 5.5.

## 1. Goal

Close four open Dependabot alerts on the web app's dev tooling in one reviewed change: alerts 8 and 9 (tinypool, critical) and alerts 5 and 6 (@vitest/mocker and vitest, medium). Dependabot opened the bump as PRs 144 and 145 (the same change); both fail the `gates` check. This slice applies vitest 5.0.4 on its own branch, keeps vite on 7.x so the test setup needs no change, and those two PRs are closed once it merges. The postcss alerts (1 to 4) and mako (14) are later slices.

## 2. Facts the design rests on

- The four alerts, open at main 7368942 (`00-alerts-red.txt`, from `gh api …/dependabot/alerts/<n>`):

| Alert | Package | Severity | Advisory | Vulnerable | First patched |
|---|---|---|---|---|---|
| 5 | @vitest/mocker | medium | GHSA-82fw-gwwq-j7x9 | >= 2.1.0, < 4.1.11 | 4.1.11 |
| 6 | vitest | medium | GHSA-82fw-gwwq-j7x9 | >= 2.1.0, < 4.1.11 | 4.1.11 |
| 8 | tinypool | critical | GHSA-85c8-ppgw-ccpr | < 2.1.2 | 2.1.2 |
| 9 | tinypool | critical | GHSA-5gmw-xhrv-c9v3 | <= 2.1.0 | 2.1.1 |

- In `apps/web`, `vitest` is a direct devDependency (`"vitest": "^3.0.0"`). `npm ls` on main: vitest 3.2.7, @vitest/mocker 3.2.7, tinypool 1.1.1, vite-node 3.2.4, vite 7.3.6 (`01-red-npm-ls.txt`). `npm audit` on main lists all three advisories above (`02-audit-main.txt`, a headed summary of `02-audit-main.json`).
- vitest 5.0.4 (the latest release) has no `tinypool` dependency, and lists `vite` only as a peer (`^6.4.0 || ^7.0.0 || ^8.0.0`); its `engines` is `node ^22.12.0 || ^24.0.0 || >=26.0.0` (local and CI use Node 22; local v22.23.0).
- `npm install -D vitest@5.0.4` on its own moves vite 7.3.6 to 8.3.4. On that tree `tsc --noEmit` fails at `vitest.config.ts(7,14)` (`'jsx' does not exist in type 'ESBuildOptions'`, exit 2), and `vitest run` fails 3 of 9 files (the three TSX test files fail to parse; `Test Files  3 failed | 6 passed (9)`, `Tests  78 passed (78)`, exit 1) (`08-mutant-unpinned.txt`).
- Dependabot PR 145's `gates` run 38456124574 fails at that same `tsc` error (`11-pr145-ci.txt`); PR 144's `gates` run 38456119856 fails too, and the two PRs' full diffs have the same SHA-1, b0513d6f… (`11b-pr144-145.txt`).
- The test files use `vi.fn`, `vi.mock`, `vi.mocked`, `vi.spyOn`, `vi.stubGlobal`, `vi.unstubAllGlobals` and `vi.restoreAllMocks`; `vitest.config.ts` sets `esbuild: { jsx: "automatic" }` and the `@` alias.

## 3. User decisions

1. Slice 71 is the vitest upgrade (options shown: vitest; postcss; mako).
2. Approach: vitest 5 and keep vite 7 (options shown: vitest 5 keeping vite 7; vitest 5 with vite 8, as Dependabot did; vitest 4.1.x).
3. Design sections 1 to 4 approved in chat, one "yes" per section.
4. After the proof showed plain vitest 5 pulls vite 8 (§2), re-asked: pin `vite` `^7.3.6` as a devDependency (options shown: pin as devDependency; go to vite 8; npm `overrides` for vite).
5. Revised sections 1 and 2 approved, one "yes" each; sections 3 and 4 confirmed with the new install command.
6. After spec review round 1 found that `lockdelta71.py` let a changed `resolved` or `integrity` through: add a whole-lock SHA-256 check as condition 6 (options shown: whole-lock SHA-256; full-entry comparison; reword the spec only).

## 4. The change

In `apps/web/`, with npm 10.9.8 and Node v22.23.0, starting from main's installed tree (`npm ci` first), one command:

```
npm install -D vitest@5.0.4 vite@7.3.6
```

It exits 0 (`03-patch.txt`). Two runs, each on its own copy of main, produce byte-identical `package-lock.json` and `package.json` files; the lock's SHA-256 is `9702766ff08ab3b34fbcc3657a0e0c8ce499821dc96766e1094b793aef1e6f99` (`03-patch.txt`, `03b-run2.txt`, `03c-run-cmp.txt`; run 1's header records the base, Node and npm but not the command; run 2's records `npm ci --no-audit --no-fund` and then the §4 command with `--no-fund`; both installs report `added 3 packages, removed 19 packages, changed 10 packages`). vitest and vite are exact in the command, but several of vitest 5.0.4's own dependencies are caret ranges (for example `chai ^6.3.0`, `std-env ^4.3.0`, `tinyexec ^1.3.1`), so a release published after this proof can change the lock; if it does, `lockdelta71.py` fails on its SHA-256 check and the slice stops for a user decision. `git diff --stat` (`10-diffstat.txt`): `apps/web/package-lock.json | 421`, `apps/web/package.json | 3`, 124 insertions and 300 deletions. The `package.json` change, generated from the scratch copy (`09-package-json-diff.txt`):

```diff
diff --git a/apps/web/package.json b/apps/web/package.json
index bba7269..1ef3c8a 100644
--- a/apps/web/package.json
+++ b/apps/web/package.json
@@ -27,6 +27,7 @@
     "eslint-config-next": "^15.0.0",
     "openapi-typescript": "^7.0.0",
     "typescript": "^5.6.0",
-    "vitest": "^3.0.0"
+    "vite": "^7.3.6",
+    "vitest": "^5.0.4"
   }
 }
```

The `vite` line exists only to hold vite on 7.x; `vitest.config.ts` and every test file stay unchanged. Nothing outside `apps/web/` changes.

The lockfile delta (`04-lockdelta.txt`, from `lockdelta71.py`) is 33 entries, every one on a named allow-list:

| Kind | Entries |
|---|---|
| Root `""` | `devDependencies` only: `vite` added as `^7.3.6`, `vitest` `^3.0.0` → `^5.0.4` |
| Added (3) | `@jridgewell/resolve-uri` 3.1.2, `@jridgewell/trace-mapping` 0.3.31, `obug` 3.0.0 |
| Removed (19) | `@vitest/expect`, `@vitest/pretty-format`, `@vitest/runner`, `@vitest/snapshot`, `@vitest/utils` (all 3.2.7), `cac` 6.7.14, `check-error` 2.1.3, `deep-eql` 5.0.2, `loupe` 3.2.1, `pathe` 2.0.3, `pathval` 2.0.1, `siginfo` 2.0.0, `stackback` 0.0.2, `strip-literal` 3.1.0, `strip-literal/node_modules/js-tokens` 9.0.1, `tinypool` 1.1.1, `tinyrainbow` 2.0.0, `tinyspy` 4.0.6, `vite-node` 3.2.4 |
| Changed (10) | `vitest` and `@vitest/mocker` and `@vitest/spy` 3.2.7 → 5.0.4, `chai` 5.3.3 → 6.3.0, `es-module-lexer` 1.7.0 → 2.3.2, `magic-string` 0.30.21 → 1.4.3, `std-env` 3.10.0 → 4.3.0, `tinybench` 2.9.0 → 6.2.2, `tinyexec` 0.3.2 → 1.3.1, `why-is-node-running` 2.3.0 → 3.2.1 |

`node_modules/vite` (7.3.6) and `node_modules/esbuild` (0.28.2) are byte-identical to main's.

`lockdelta71.py` (Python standard library only) takes main's lock (`git show 7368942:apps/web/package-lock.json`) and the patched one, compares every `packages` entry, and exits 1 on any of: (1) an added, removed or changed entry not on the allow-list at the listed versions; (2) an entry whose version is unchanged but whose content changed (`resolved`, `integrity` or any other field); (3) any change to the `vite` or `esbuild` entry; (4) a `tinypool` entry in the new lock; (5) a root-entry change other than the two `devDependencies` keys above; (6) a patched lock whose SHA-256 is not the proof's (above), which catches any byte difference, including fields conditions 1 to 5 do not compare, such as `resolved`, `integrity` or `dev` on an added or changed entry, or the top-level keys outside `packages`. It counts its OK rows and fails unless there are exactly 33, so a missing or extra row fails too. Conditions 1 to 5 name the entry at fault; condition 6 is the one that covers every byte. The script is embedded in the plan.

## 5. Proof

**Before the PR** (scratch copies of main 7368942; every `.txt` output has a UTC header, and each records the exit status of the commands it saves except `12-precheck.txt` (a process listing), `11-pr145-ci.txt` (an excerpt of CI's log, which carries CI's own `exit code 2`), the `gh pr diff | shasum` lines in `11b-pr144-145.txt` and the `shasum` lines in `03c-run-cmp.txt`; the two `.json` files are raw `npm audit` output, summarised in the headed `02-audit-main.txt` and `06-audit-patched.txt`):

- Red: alerts 5, 6, 8 and 9 are `open` (`00`); `npm ls` shows vitest 3.2.7, @vitest/mocker 3.2.7, tinypool 1.1.1 (`01`); `npm audit` lists GHSA-82fw-gwwq-j7x9, GHSA-85c8-ppgw-ccpr and GHSA-5gmw-xhrv-c9v3 (`02-audit-main.txt`; `npm audit` exits 1).
- Green: after §4's command, `npm ls` shows vitest 5.0.4, @vitest/mocker 5.0.4, top-level vite 7.3.6 (deduped under both), and no tinypool or vite-node (`05-green-npm-ls.txt`); `npm audit` no longer lists any of the three advisories and still exits 1, for the seven remaining postcss, next and braces-chain entries (`06-audit-patched.txt`).
- Web gate on the patched copy, after a saved pytest pre-check (`12-precheck.txt`: no pytest of this repo running): `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)`, `▲ Next.js 15.5.27`, `gen:check` clean, exit 0 (`13-green-gate.txt`). An earlier identical gate run on the same copy, made before any pre-check was saved, is kept as `13a-green-gate-without-precheck.txt` and not relied on.
- Lock delta: `lockdelta71.py` prints `SHA256-OK`, 33 OK rows, `FROZEN-OK` for vite 7.3.6 and esbuild 0.28.2, `ok=33 other=0`, exit 0 (`04`). `mutants71.py` writes each mutant the way npm writes a lock (two-space JSON and a final newline); the control m0, an unchanged round-trip, is byte-identical to the patched lock and exits 0 (`04m0`). Each tamper mutant makes it exit 1, and each also prints `OTHER sha256` (`04m1` to `04m6`):
  - m1, a `left-pad` entry added: `OTHER added 'node_modules/left-pad'`.
  - m2, `react`'s `integrity` changed with its version kept: `OTHER changed 'node_modules/react' ('19.3.0', '19.3.0')`.
  - m3, vite's version set to 8.3.4: `OTHER frozen-changed 'node_modules/vite'`.
  - m4, a `tinypool` entry put back: `OTHER tinypool-present` and `expected 33 OK rows, got 32`.
  - m5, a root `typescript` devDependency change: `OTHER root '' ['typescript', 'vite', 'vitest']` and `expected 33 OK rows, got 32`.
  - m6, `vitest`'s `resolved` and `integrity` replaced with its version kept: only `OTHER sha256`.
  - The four tamper locks from spec review round 1 (a foreign `resolved` and `integrity` on `vitest`, `dev: false` on `obug`, a changed `lockfileVersion` and `name`, an extra dependency under `chai`) passed the round-1 script; each now exits 1 on `OTHER sha256` alone (`04x1` to `04x4`).
- Mutations:
  - Without the vite pin (`npm install -D vitest@5.0.4` alone): vite 8.3.4, `tsc` exit 2, `vitest run` 3 files failed, exit 1 (`08-mutant-unpinned.txt`). The pin is what keeps typecheck and the TSX tests working.
  - One assertion flipped (`src/lib/api-paths.test.ts:96`, `toBeGreaterThanOrEqual(40)` → `(100000)`), then restored: main (`RUN  v3.2.7`) and patched (`RUN  v5.0.4`) both report `Tests  1 failed | 92 passed (93)` and exit 1 (`07`, `07b`). vitest 5 runs the same 93 tests and fails on a broken one.
- Planned, at execution: both local gates, each after a saved pytest pre-check (§6).

**After the merge:**

- Criterion: alerts 5, 6, 8 and 9 read `fixed` in `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh api repos/aiagencyindia-lab/bsi-platform/dependabot/alerts/<n>` (without that token the endpoint returns HTTP 403; `11c-alerts-auth.txt`), checked a few minutes apart for up to 30 minutes; each observation goes into the ledger when made.
  - Note (2026-10-14, after slice 71, PR #151): met at the first check (11:06:34Z): PR 151 merged at 11:06:23Z, alert 5 read `fixed` with `fixed_at` 11:06:28Z and alerts 6, 8 and 9 with 11:06:29Z (docs/findings-slice71.md).
- PRs 144 and 145: if Dependabot has not closed them by then, the controller asks the user before closing either.
  - Note (2026-10-14, after slice 71, PR #151): Dependabot closed both itself, 145 at 11:08:39Z and 144 at 11:08:41Z; the controller closed neither. It also closed PR 149 (next 16.4.0) at 11:08:45Z while postcss alerts 1 to 4 stay open; why is unknown (docs/findings-slice71.md).
- Any state other than `fixed` after 30 minutes is a finding reported to the user before the docs PR.

## 6. Verification and merge

1. Pytest pre-check as its own command, output saved; backend gate: expected `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, coverage 100%, `1811 passed, 2 deselected`, no warnings summary.
2. Pre-check again, saved; web gate: expected `RUN  v5.0.4`, `Tests  93 passed (93)` after stripping ANSI codes, `▲ Next.js 15.5.27`, `gen:check` clean.
3. The §5 checks on the committed branch (`npm ls`; `npm audit`, which is expected to exit 1 with none of the three advisories listed; `lockdelta71.py` against `git show 7368942:apps/web/package-lock.json`), saved with UTC headers and exit statuses.
4. PR opened; on "check ci": one `gh pr checks --watch`; `gates` must pass; merge with `--merge --delete-branch`; `git ls-remote --heads origin slice71-vitest5`.
5. After the merge, the §5 criterion, then PRs 144 and 145 as above.
6. No live checks against the app, no database migration, no worker, no model or DataForSEO spend. GitHub writes are this slice's PRs and their merges, plus closing PRs 144 and 145 only if the user says so.

## 7. Out of scope

- vite 8 (the `esbuild.jsx` setting would move to vite 8's `oxc` options) and vite 7.3.6 → 7.3.7.
- postcss (alerts 1 to 4; PR 149) and mako (alert 14; PR 140).
- `npm audit` also lists braces GHSA-vfj7-8cjw-p6xm (high, through `eslint-config-next`) on main and on the patched tree; no Dependabot alert lists it, and why is unknown. It is raised with the user after this slice.
- Any repository setting, including Dependabot's.

## 8. Handoff note

`apps/web/package.json` now has a direct `vite` `^7.3.6` devDependency whose only job is to hold vite on 7.x for vitest 5. Moving to vite 8 means removing that line and porting `vitest.config.ts`'s `esbuild: { jsx: "automatic" }` to vite 8's options, proved against the three TSX test files.
