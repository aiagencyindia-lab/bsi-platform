# Slice 73: Mako 1.4.1 → 1.4.2 in uv.lock (design)

Date: 2026-10-14 (IST). Base: main 04388a7. Session model Opus 5.5.

## 1. Goal

Close Dependabot alert 14 by moving Mako from 1.4.1 to 1.4.2 in `uv.lock`. It is one reviewed change, made with uv on the project's own branch. It reproduces Dependabot's PR 140 byte for byte.

## 2. Facts the design rests on

- **Alert 14** (`00-red.txt`, and `00b-alert14.txt` from `gh api …/dependabot/alerts/14` with the `aiagencyindia-lab` token) is open on Mako, GHSA-5639-2j2p-m4mx.
  - Severity: medium.
  - Vulnerable versions: `<= 1.4.1`; first patched: 1.4.2.
  - Manifest: `uv.lock`; runtime scope, transitive.
  - The advisory is a path traversal through a Windows drive-letter URI in `TemplateLookup`.
- **Who uses Mako:**
  - `uv tree --invert --package mako` on main shows `mako v1.4.1` under `alembic v1.20.0` only, which `bsi-core` requires (`packages/core/pyproject.toml`: `alembic>=1.13`) (`00`, `01-red-tree.raw`).
  - No `pyproject.toml` names Mako.
  - Alembic uses Mako to render `migrations/script.py.mako` when it generates a migration file.
  - The app does not run on Windows.
- **Dependabot PR 140** (mako 1.4.1 → 1.4.2):
  - Its head is 01777c2, on base 35fe8b3.
  - It changes only `uv.lock`: 3 lines (version, sdist, wheel).
  - Its `gates` check passed, and GitHub reports it `MERGEABLE CLEAN`.
  - `uv.lock` has not changed on main since its base.
- **No override is needed.** Alembic 1.20.0 requires Mako with no version bound (its metadata reads `Requires-Dist: Mako`, and `uv.lock` records `{ name = "mako" }`), so `uv lock --upgrade-package` can move it to 1.4.2 (`02`). Next, by contrast, pinned postcss exactly in slice 72.
- **`alembic.ini`:**
  - `revision_environment` is left at its default (false), so `alembic revision` does not run `migrations/env.py`.
  - `[post_write_hooks]` has no active hooks.
- **CI** installs with `astral-sh/setup-uv@v10.3.0` and `uv sync`.

## 3. User decisions

1. Slice 73 is the Mako alert ("start slice 73 with the mako alert").
2. Approach: our own branch with `uv lock` (options shown: own branch with uv lock, recommended; merge PR 140 directly; dismiss the alert).
3. Design sections 1–4 approved in chat, one "yes" per section.

## 4. The change

At the repo root, with uv 0.9.28, run one command:

```
uv lock --upgrade-package mako==1.4.2
```

It exits 0 and prints `Updated mako v1.4.1 -> v1.4.2` (`02-patch.txt`). A following `uv sync` installs it: `uv pip show mako` gives `Version: 1.4.2`.

Two runs, each on its own copy of main, produce byte-identical `uv.lock` files (`02-patch.txt`, `06-run2.txt`: `cmp uv.lock exit 0`). The lock's SHA-256 is `e229c405fdcd27dc371e18f0ba736a193bc5a20072bbee0ab0dbc24c903caa5f`, and main's lock is `301314633e401799459849947d95be15ca4ef51e5033159b9fa5bbb7a1d96067`.

The patched lock is byte-identical to PR 140's (`04-pr140-compare.txt`: `cmp exit 0` against PR 140's head 01777c2). If a run at execution produces any other lock, `lockdelta73.py` fails its SHA-256 check and the slice stops for a user decision.

`git diff --stat`: `uv.lock | 6 +++---`, 1 file changed, 3 insertions and 3 deletions. The hunk from `03-uvlock.diff` (its `diff --git`, `index` and file-name lines omitted):

```diff
@@ -861,14 +861,14 @@ wheels = [
 
 [[package]]
 name = "mako"
-version = "1.4.1"
+version = "1.4.2"
 source = { registry = "https://pypi.org/simple" }
 dependencies = [
     { name = "markupsafe" },
 ]
-sdist = { url = "https://files.pythonhosted.org/packages/2a/12/b5fa2353e2754cd67fb9f83793fa48ff42c213a5da7e719869d2301f6ab8/mako-1.4.1.tar.gz", hash = "sha256:d7904710b662996425a21627710c4777c45053146942cf8a7aebf757c92b8c27", size = 410165, upload-time = "2026-08-05T06:10:56.611Z" }
+sdist = { url = "https://files.pythonhosted.org/packages/05/7f/0b891a82379ffd96d2d8cc6d435fb1055cdaed52829287f81d2a43fd71cb/mako-1.4.2.tar.gz", hash = "sha256:7227a060ee3af55a493af61d73d6beef13044b81dba9586736c13945f09464ce", size = 412231, upload-time = "2026-09-22T20:40:55.06Z" }
 wheels = [
-    { url = "https://files.pythonhosted.org/packages/a5/54/12ed58d458474aaab5c3d180173e745a4fe131bb330370596876d19ff60f/mako-1.4.1-py3-none-any.whl", hash = "sha256:a359d9a94a541213958742b2698d0a7757bb83551767bc468a74b9905aba9617", size = 80010, upload-time = "2026-08-05T06:10:58.248Z" },
+    { url = "https://files.pythonhosted.org/packages/f0/bb/0e4c30a18858adebc75496ea8a8c3fb65cbf4b36ea1c5028ed8a0a5fa196/mako-1.4.2-py3-none-any.whl", hash = "sha256:e70a2a4308952b33a21208bfd6725da79fae5a8c224578f8cfdeb60e5ace03df", size = 80163, upload-time = "2026-09-22T20:40:56.423Z" },
 ]
```

No `pyproject.toml` and no source file changes.

`lockdelta73.py` (Python standard library, `tomllib`) takes main's lock (`git show 04388a7:uv.lock`) and the patched one. It matches `[[package]]` entries by name and source, and exits 1 on any of the following:
1. any package other than `mako` added, removed or changed in any field;
2. `mako` not going from 1.4.1 to 1.4.2, or changing a field other than `version`, `sdist` and `wheels`;
3. a new `mako` sdist or wheel URL that is not on `https://files.pythonhosted.org/`, or that does not name `mako-1.4.2`;
4. any change outside the package list (`version`, `revision`, `requires-python`, `manifest`, or any other top-level key);
5. a patched lock whose SHA-256 is not the proof's.

It also counts its OK rows and fails unless there is exactly 1. Conditions 1 to 3 are not independent checks for every case: a duplicate package entry hides behind its twin in the name-and-source index, and the URL test is a substring match. Condition 5, the SHA-256 of the whole lock, fails on any byte change and is the backstop, as mutant m2 shows. The script is embedded in the plan.

## 5. Proof

All runs are on scratch copies of main 04388a7, with outputs in `out73/`. Each numbered `.txt` has a UTC header and records the exit status of its main commands. A command whose output is filtered has its raw output saved first, or (in `06`) its exit taken from zsh's `pipestatus[1]`, which is the command's own status.

The exceptions:
- `08-precheck.txt` has a header and a one-line verdict, with no exit line;
- `sync-main.txt`, `sync-proof.txt` and `02-sync.raw` are empty (0 bytes) and record no command; `02` records `uv sync exit 0` for the patched copy, no file records the exit of the two first syncs, and `07` shows both copies' Mako installed (1.4.1 and 1.4.2);
- `03-uvlock.diff` is a raw `git diff`;
- in `09`, the ruff and mypy output sits in the `.txt` and the pytest output in `09-green-gate.raw`.

**Red** (`00`): alert 14 `open`; `mako v1.4.1` under `alembic v1.20.0`; `uv pip show mako` gives `Version: 1.4.1`.

**Green:**
- `02`: `uv lock exit 0`, `Updated mako v1.4.1 -> v1.4.2`, `uv sync exit 0`, `Version: 1.4.2`, and only `uv.lock` modified.
- `09`: the backend gate on the patched copy, after a saved pytest pre-check (`08`: no pytest of this repo running), gives `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, `gate exit 0`, `TOTAL … 100%`, `1811 passed, 2 deselected` and `warning hits: 0`.

**Lock check** (`05`): `SHA256-OK`, `OK    changed 'mako' 1.4.1 -> 1.4.2 ['sdist', 'version', 'wheels']`, `ok=1 other=0`, `lockdelta exit 0`.

`mutants73.py` makes each mutant by text substitution on the patched lock, and asserts that the substitution matched once and changed the text. The control m0 is byte-identical and exits 0 (`05m0`). Each tamper mutant exits 1 and prints `OTHER sha256` (`05m1` to `05m6`):

| Mutant | Change | What the check prints besides `OTHER sha256` |
|---|---|---|
| m1 | `alembic` 1.20.0 → 1.20.1 | `OTHER package changed 'alembic'` |
| m2 | mako's wheel hash zeroed, version kept | nothing more (the SHA-256 alone catches it) |
| m3 | mako's version line put back to 1.4.1 | `OTHER mako version 1.4.1 -> 1.4.1`, `expected 1 OK row, got 0` |
| m4 | the lock's `revision` 3 → 99 | `OTHER top-level keys changed ['revision']` |
| m5 | a `left-pad` package added | `OTHER package added 'left-pad'` |
| m6 | mako's sdist URL on another host | `OTHER mako url not https://files.pythonhosted.org/ or not 1.4.2`, `expected 1 OK row, got 0` |

**Mako exercised** (`07`): in each copy, main (`Version: 1.4.1`) and patched (`Version: 1.4.2`), `uv run alembic revision --rev-id proof73 -m proof` exits 0 and renders `migrations/script.py.mako` to `migrations/versions/proof73_proof.py`.
- The two files differ only in their `Create Date` line: `diff` with that line ignored exits 0, and the raw `diff` shows only line 5.
- Both files are saved as `07-rendered-main.py` and `07-rendered-proof.py`.
- They were then removed from the scratch copies before the gate, so the test run's `alembic upgrade` could not apply them.

**Planned at execution:** both local gates, each after a saved pytest pre-check (§6).

**After the merge:**
- Criterion: alert 14 reads `fixed` in `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh api repos/aiagencyindia-lab/bsi-platform/dependabot/alerts/14`. Check every two minutes for up to 30 minutes, and ledger each observation when it is made.
- The dependency-graph SBOM (`gh api …/dependency-graph/sbom`) is read for Mako's versions.
- Whether Dependabot closes PR 140 is observed. The controller does not close it.
- Any state other than `fixed` after 30 minutes is a finding, reported to the user before the docs PR.
- The alerts are re-listed in all states, together with the open PRs.

## 6. Verification and merge

1. Pytest pre-check as its own command, output saved. Backend gate expected: `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, coverage 100%, `1811 passed, 2 deselected`, no warnings summary.
2. Pre-check again, saved. Web gate expected: `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)` after stripping ANSI codes, `▲ Next.js 15.5.27`, `gen:check` clean. The web app is untouched by this change.
3. On the branch, before the commit, saved with UTC headers and exit statuses:
   - `lockdelta73.py`;
   - `uv pip show mako`, expected `Version: 1.4.2`;
   - `git diff --stat`, expected `uv.lock` only, with 3 insertions and 3 deletions.
4. Open the PR. On "check ci": one `gh pr checks --watch`; `gates` must pass; merge with `--merge --delete-branch`; `git ls-remote --heads origin slice73-mako`.
5. After the merge: the §5 criterion.
6. No live checks against the app, no database migration, no worker, no model or DataForSEO spend. The planned GitHub writes are the branch push, this slice's PRs and their merges. Any other write, such as an alert dismissal, needs the user's decision and is recorded as a departure.

## 7. Out of scope

- Any other Python or npm package, including alembic, markupsafe and SQLAlchemy.
- Merging, closing or commenting on PR 140 by hand.
- The dismissed postcss alerts 1–4 and the auto-dismissed braces alert 7.
- Any `pyproject.toml` constraint on Mako.
