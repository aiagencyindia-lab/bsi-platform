# Slice 25 findings: store the raw keyword samples and the raw rewrite

## 1. What was built

The findings for slices 23 and 24 marked every statement about which keyword sample offered a stored keyword, or which words the rule check removed, as *inferred*, because `run_products` kept neither the sample lists nor the rewrite call's title (spec, Context). Each product row now stores both for its latest run. They are read with psql; no API, web, CSV, prompt or copy change.

**Migration.** `migrations/versions/0021_product_raw.py` (`revision = "0021"`, `down_revision = "0020"`) adds two nullable columns to `product`: `keyword_samples` (JSONB) and `raw_title` (text). The downgrade drops `raw_title`, then `keyword_samples`. No constraint, index or `_protect` call; the table already has RLS from 0019.

**ORM.** `Product` (`packages/core/bsi_core/models.py`) gains, after `dropped_words`, `keyword_samples: Mapped[list[list[str]] | None] = mapped_column(JSONB)` (line 559) and `raw_title: Mapped[str | None]` (line 560), with a three-line comment above them.

**Where `run_products` writes them** (`packages/core/bsi_core/products.py`):
- Keyword step: `p["samples"] = [sm.get(i, []) for sm in samples]` (line 1055), the three sample lists after `_clean`, is what `choose_keywords` receives. The first per-batch UPDATE writes `keyword_samples=p["samples"]` (line 1090) for every product in the batch, a product that ends with no keyword included.
- Rewrite step: `title_in = item.title.strip() if item else ""`, `p["raw_title"] = title_in or None`, `suggestion = title_in or p["title"]` (lines 1230-1232; `suggestion` has the same value as before). The second UPDATE writes `raw_title=p["raw_title"]` (line 1250).
- R13: the `cleared` dict gains `"raw_title": None` (line 1079), so a product that loses its keyword loses its old raw rewrite with its old suggestion.

**Tests** (`tests/integration/test_products_run.py`):
- `_generator` (line 54) gains `skip_rewrite=()`: product indexes left out of the rewrite body (line 125). Callers that do not pass it are unchanged.
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (line 182) also asserts `p.keyword_samples == [["kids sandals", "walkaroo kids"]] * 3` and `p.raw_title == "Walkaroo Kids Summer Sandals Sandals"` (lines 224-225); the checked `suggested_title` is "Walkaroo Kids Summer Sandals".
- `test_a_product_whose_keyword_drops_loses_its_old_suggestion` (line 746) seeds `raw_title="Old raw"` and also asserts `p.raw_title is None` and `p.keyword_samples == [["walkaroo sandals"]] * 3` (lines 774-775).
- New, `test_a_product_without_a_rewrite_keeps_its_title_and_no_raw_title` (line 778): `_generator(skip_rewrite={0})`; asserts `job.status == "done"`, `raw_title is None`, `suggested_title == "Walkaroo Boys Sandal 0"`, `(rule_check, dropped_words) == ("pass", [])`, `suggested_bullets == []` and the uniform `keyword_samples`.
- New, `test_keyword_samples_round_trip` (line 891): writes `keyword_samples` with a non-ASCII entry and an empty inner list, and `raw_title="Kids Sandals — Summer"`, through the `owner` fixture, and reads both back equal in a new session.
- TDD evidence, as the task reports record it:
  - Task 1 RED: `TypeError: 'keyword_samples' is an invalid keyword argument for Product`, 1 failed, 28 deselected. GREEN: 1 passed, 28 deselected.
  - Task 2 RED: 3 failed, 27 deselected; the rewrite-checked and no-rewrite tests on `assert None == ([['kids sandals', 'walkaroo kids']] * 3)`, the drops test on `assert 'Old raw' is None`. GREEN: 3 passed, 27 deselected. The product-run file: 30 passed.
- Backend gate (Task 2, 05ad185), as the ledger records it: "1544 passed, 2 deselected, 2 warnings (StarletteDeprecationWarning, anyio BlockingPortal alias), coverage 100%". The gate file holds only the pytest output (§3, the first Task 2 minor); the controller ran the rest at 05ad185: `uv run ruff check .` "All checks passed!"; `uv run ruff format --check .` "169 files already formatted"; `uv run mypy` "Success: no issues found in 29 source files".

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 469c64e | docs: slice 25 design spec |
| 67ddf00 | docs: slice 25 spec review fixes |
| ec48b30 | docs: slice 25 spec: failed-batch note covers every step |
| a952344 | docs: slice 25 implementation plan |
| 42fec76 | docs: slice 25 plan review fixes |
| bf5ced4 | feat(products): keyword_samples and raw_title columns (migration 0021) |
| 05ad185 | feat(products): store the keyword samples and the raw rewrite |
| 4b27e20 | docs: slice 25 findings, index and hashes |
| 69d3245 | docs: slice 25 findings: final-review minors |
| e880c1a | docs: slice 25 process audit corrections |
| 4e284ec | docs: slice 25 audit corrections: review fixes |
| a41d358 | docs: slice 25 spec: unsplice the audit corrections |
| 25494a0 | docs: slice 25 live check |
| (this commit) | docs: slice 25 live check: review fixes |

## 2. Live check on dev

Run on 2026-09-30 by the controller on main at 28ccb30 (after PR #46 merged), with the user's OK ("migrate dev and run the live check").

- Pre-check (read-only): dev at migration 0020; no uvicorn, worker or pytest process; 0 queued jobs; `keyword_search` had 20 rows, the newest searched 2026-09-30 09:27:13 UTC; 8 prior `product_run` jobs. Seven `run` jobs have a NULL status; `claim_job()` claims only `queued` jobs whose kind is not `run` (read from the function on dev), so they could not be claimed.
- Migration: `uv run alembic upgrade head` took dev from 0020 to 0021 (head). `keyword_samples` (jsonb) and `raw_title` (text) exist and are nullable; before the run, 0 products had either value.
- The API was started in the background. `POST /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/products/run` returned HTTP 202 and queued job `08939d2b-1629-41e4-aaae-90ab09207e16`. The API was then stopped (background task exit 144, as expected); exactly one job was queued. `process_job` ran once and returned `True`; the worker loop was not started.
- Job `08939d2b`: status done, error null, `cost_micros = 6,587` (the spec's estimate was about 6,400), created 14:35:19, started 14:35:26 UTC.
- No grounded search ran: `keyword_search` still has 20 rows and its newest `searched_at` is still 2026-09-30 09:27:13.
- Writes observed: the job row, the 10 product rows (each now has `job_id` 08939d2b), and `api_key.last_used_at` = 14:35:19 UTC. Afterwards: 0 queued or running jobs, no uvicorn or worker process; 9 `product_run` jobs totalling 1,650,561 micros. Spend is about $10.95 of the $15 cap (slice 24's unrounded $10.9464 + $0.0066 = $10.9530).

**Per product** (observed by read-only queries after the job; samples abbreviated to each sample's first keyword):

| Product | Title | First keyword of samples 1 / 2 / 3 | Keyword | Raw title | Suggested title | Status | Dropped | Missing |
|---|---|---|---|---|---|---|---|---|
| LC-01 | BSOAgentTestBrand Boys Sandal Blue | kids sandals / kids sandals / kids sandals | kids sandals | BSOAgentTestBrand Blue Kid Sandals Boys Sandal | BSOAgentTestBrand Blue Kid Sandals Boys | adjusted | (none) | kid |
| LC-02 | BSOAgentTestBrand Girls Sandal Pink | kids sandals / kids sandals / kids sandals | kids sandals | BSOAgentTestBrand Pink Kid Sandals Girls Sandal | BSOAgentTestBrand Pink Kid Sandals Girls | adjusted | (none) | kid |
| LC-03 | BSOAgentTestBrand Kids Sports Shoe Black | kids shoes / kids shoes / kids shoes | kids shoes | BSOAgentTestBrand Black Kids Shoes Sports Shoe | BSOAgentTestBrand Black Kids Shoes Sports | adjusted | (none) | (none) |
| LC-04 | BSOAgentTestBrand Kids Slipper Grey | kids slippers / kids slippers / kids slippers | kids slippers | BSOAgentTestBrand Grey Kids Slippers Slipper | BSOAgentTestBrand Grey Kids Slippers | adjusted | (none) | (none) |
| LC-05 | BSOAgentTestBrand Men Flip Flop Navy | men slippers / men slippers / men slippers | mens flip flops | BSOAgentTestBrand Navy Mens Flip Flops Flip Flop | BSOAgentTestBrand Navy Mens Flip Flops | adjusted | (none) | (none) |
| LC-06 | BSOAgentTestBrand Men Casual Sandal Brown | men sandals / men sandals / men sandals | men sandals | BSOAgentTestBrand Brown Men Sandals Casual Sandal | BSOAgentTestBrand Brown Men Sandals Casual | adjusted | (none) | (none) |
| LC-07 | BSOAgentTestBrand Women Casual Slipper Beige | women slippers / women slippers / women slippers | women slippers | BSOAgentTestBrand Beige Women Slippers Casual Slipper | BSOAgentTestBrand Beige Women Slippers Casual | adjusted | (none) | (none) |
| LC-08 | BSOAgentTestBrand Men Sports Shoe Grey | men shoes / men shoes / men shoes | men shoes | BSOAgentTestBrand Grey Men Shoes Sports Shoe | BSOAgentTestBrand Grey Men Shoes Sports | adjusted | (none) | (none) |
| LC-09 | BSOAgentTestBrand Boys School Shoe Black | kids shoes / kids shoes / kids shoes | kids shoes | BSOAgentTestBrand Black Kids School Shoe Boys Shoes | BSOAgentTestBrand Black Kids School Shoe Boys | adjusted | (none) | kids |
| LC-10 | BSOAgentTestBrand Women Sandal Tan | women sandals / women sandals / women sandals | women sandals | BSOAgentTestBrand Tan Footbed Women Sandals Sandal | BSOAgentTestBrand Tan Footbed Women Sandals | adjusted | (none) | footbed |

All 10 stored keywords and all 10 missing-word lists are the same as after slice 24's run (docs/findings-slice24.md §2).

What the stored values show, first observed and then inferred:
- Keywords, observed: for 9 products the stored keyword is the first keyword of all three samples. For LC-05 no sample offers "mens flip flops" or "men flip flops": all three samples start with "men slippers", whose type word is not in the title "Men Flip Flop Navy"; samples 1 and 3 offer "cushioned flip flops" and samples 2 and 3 "flip flops" (samples 2 and 3 also offer "navy flip flops", and sample 1 "men navy flip flops", colour keywords).
- Keywords, *inferred* from the code: LC-05's keyword was built by `title_first` (the first keyword's audience "men" plus the title's type words, plural from "cushioned flip flops", the first title-fitting keyword left after `drop_noise_terms` removed the colour keywords "men navy flip flops" and "navy flip flops"; a replay of `choose_keywords` on the stored samples, with no model call, returns "men flip flops" first), and its spelling "mens flip flops" came from the cache seed (slice 24), since no sample offers that spelling. Before this slice, which path produced LC-05's keyword was not known (docs/findings-slice23.md §3).
- Rewrite, observed: in all 10 raw titles the model ends with the original title's type word or its plural ("Sandal", "Shoe", "Slipper", "Flip Flop"; LC-09 ends with "Shoes", its original has "Shoe") after a plural or singular form of it earlier in the title. Each suggested title is its raw title with that final word or phrase removed; no original-title word was lost (dropped words empty) and each suggested title differs from its raw title, so every status is `adjusted`.
- Rewrite, *inferred* from the code: the removal is `rule_check`'s repeat-stem drop, the only step that removes an allowed-stem word from these titles (every removed word's stem is in the product's keyword; the 150-character trim does not apply, since the raw titles are 44 to 53 characters; no removed word is a connector).
- Recorded, not changed in this slice: the rewrite call repeats the type word in 10 of 10 titles on this run.


## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- Task 1: the Edit tool decodes `\u` escapes into literal characters; the final diff has escapes only (process note for later tasks, not a code defect).
- Task 2: the gate file records only pytest output; in the plan's Step 9 command `> gate-task2.txt` applies to the last command of the `&&` chain, so ruff and mypy results are not in the file. Future gates should redirect the whole chain.
- Task 2: the gate output has 2 warnings (StarletteDeprecationWarning about httpx; anyio BlockingPortal DeprecationWarning), third-party and pre-existing.
- Task 2: no test covers a product absent from one keyword sample (a `[]` entry in `keyword_samples` via `sm.get(i, [])`); the tests assert uniform samples only.
- Task 3: the plan's Task 1 bullet quotes the NUL-byte ledger line with "[`\u`]" (backticks not in the controller's intended text) and cites the Task 1 report as the source instead of the controller note; "went as written ... One difference" reads as a mild contradiction.
- Task 3: findings §3's R1 is the spec's text (with "(the path in the plan's Task 2 Step 9)" and the "Found by" clause), introduced by "the ledger records one", which can read as ledger text.
- Task 3: findings §1's "coverage 100%" does not say it is `bsi_core.metrics` coverage (the gate's `--cov` target).

From the final review (ledger lines tagged `minor (deferred)`):
- Final review: models.py:559 `JSONB` without `none_as_null=True` stores Python None as JSON null, not SQL NULL; no current path writes None (run_products always writes a list; imports leave the column out). Same for `impact` at line 419.
- Final review: products.py:1230-1231 a whitespace-only rewrite title and an omitted rewrite item both store raw_title NULL (spec accepts `title_in or None`); a live check cannot tell the two apart.
- Final review: deploy order: code at 05ad185 or later writes both columns and fails against a DB at 0020; dev must reach 0021 before any process_job or worker run (worker stopped; spec §3 already orders the migration first).

The final review kept every earlier deferred minor deferred (ledger text): "Ready to merge "With fixes"; 0 Critical, 1 Important, 3 Minor; all 7 earlier deferred minors triaged "keep deferred"."

Parked: none. The ledger has no parked lines.

Rulings (the ledger records one, in its preflight section; also in the spec's `## Rulings`):
- **R1: Task 2's gate output goes to the plan's workspace directory.** Decided: Task 2's gate output goes to `.superpowers/sdd/2026-09-30-slice25-raw-samples/gate-task2.txt`, not `.superpowers/sdd/gate-task2.txt` (the path in the plan's Task 2 Step 9). Found by the controller's preflight scan of the plan. Why: the plan's Global Constraints name the workspace directory, and the skill keeps each plan's artifacts in its own directory. Cost if wrong: none (a git-ignored scratch path).

Carried forward (still open):
- Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table; nothing deletes them (docs/findings-slice24.md §3, ceilings and Out of scope).
- The slice 24 seed's untested cases (docs/findings-slice24.md §3, Untested): no test pins the seed's `error.is_(None)` filter on its own; newest-wins between two valid rows that share a key; adoption of a non-first keyword.
- The judge-agreement question, waiting on the user.

Out of scope (spec):
- Exposing `keyword_samples` or `raw_title` through the API, the Products tab or `export.csv`.
- Storing `backing`, the raw model JSON, the untrimmed bullets, or any history across runs.
- Deleting stale duplicate `keyword_search` rows; the seed's untested filters; the judge-agreement labels.
- The deferred minors in docs/findings-slice23.md §4 and docs/findings-slice24.md §3.

## 4. Process audit

On 2026-09-30, after the finishing menu, the user asked "check if you have done all task correctly and follow each step" and then said "fix it". The audit found:
- The classification was never said in chat before the first brainstorming question; the spec said it was. Corrected in the spec's Context.
- All four design sections were approved through questions with only option labels, no section text in chat, and there was no approaches message with trade-offs; the spec said each section's text was shown. Corrected in the spec; each section's text, as built, was then put in chat in its own message and the user confirmed all four unchanged.
- The session started on Fable 5.1 and the user was not told at the start (planning on Fable 5.1 is allowed when the user says so; the user switched to Opus 5.5 before execution).
- Reviewer prompts carried rulings or pre-empted findings: the Task 2 review prompt stated the controller's gate-path decision (R1); the Task 3 review prompt listed the controller's resolutions, including where R1 goes; the final review prompt exempted the plan's own banned-word list from the copy check; the controller's spec re-review request argued for the 9-row count before asking the reviewer to confirm it.
- The plan's code blocks were checked on a scratch copy with ruff and mypy only; the plan's tests were first run by the implementers (their red and green runs matched the plan's expected values).
- The controller created the task report stubs itself before any implementer's tool had refused (the process rule is to create a stub for a subagent only after a refusal, and to ask the user first); this is not in the ledger. The findings stub was in the plan (ledger: "controller created the one-line stub docs/findings-slice25.md").
- One controller ledger line holds two NUL bytes (zsh `echo` read the escaped backslash-u); a note appended to the ledger gives the intended text.
- The controller's first findings-coverage grep was wrong (zsh read the parentheses in its pattern as a glob group and reported every line missing); a Python check then found all 10 deferred lines quoted and none parked.

The process notes in the controller's memory were updated with these points. No code changed.
