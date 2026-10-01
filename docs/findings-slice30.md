# Slice 30 findings: readable audit-code labels in reports

## 1. What was built

The open item "`label()` reads acronyms awkwardly for real audit codes" from docs/findings-slice17.md §3 is fixed: the SEO report's "Site audit" table now reads each audit code from a hand-written table.

**Code** (`packages/core/bsi_core/reports.py`):
- A new `AUDIT_LABEL` dict (line 75), beside `OWNER_LABEL`, with one label for each of the 24 site audit codes (the keys of `crawl.SEVERITY` and `entity.SEVERITY`), as the spec's §1 table gives them; for example `llms_missing` → "llms.txt missing", `org_sameas_missing` → "Organization sameAs profiles missing", `bot_ua_blocked` → "Crawler user agent blocked", `about_missing` → "About page link missing" (R2). Its comment says the codes come from `crawl.SEVERITY` and `entity.SEVERITY`, that a test checks every audit code has an entry, and that a suffix after ":" is kept.
- `label(code)` (line 103) splits the code at the first ":" into a head and a tail. If the head is in `AUDIT_LABEL`, it returns that label, followed by ": " and the tail when the tail is not empty (`bot_ua_blocked:GPTBot` → "Crawler user agent blocked: GPTBot"). Otherwise it behaves as before, on the whole code: `OWNER_LABEL`, then the words-and-capital rule. Its docstring says the same.
- The comment above `OWNER_LABEL` now says "every other non-audit code" (R6).
- `METHODOLOGY_VERSION = "3"`, with the added comment line "v3 = audit codes read as words from AUDIT_LABEL." Stored runs keep their v2 cells and footer.
- Unchanged: crawl.py, entity.py and their codes; `cluster_label`; the labels of task statuses, impact labels, intents, owners, severities and sentiments; the API shapes (`openapi.json`, `schema.d.ts`).

**Tests**:
- tests/unit/test_reports.py: imports `crawl`, `entity` and `AUDIT_LABEL`. In `test_label_reads_codes_as_words`, `label("h1_missing")` is now "H1 heading missing", with new cases for `llms_missing`, `org_sameas_missing`, `org_url_mismatch`, `bot_ua_blocked:GPTBot`, `bot_blocked:ClaudeBot`, `bot_blocked:` (an empty tail → "Crawler blocked by robots.txt") and `needs_review:x` (a non-audit code with a colon → "Needs review:x", as before). New `test_every_audit_code_has_a_label`: `set(AUDIT_LABEL) == set(crawl.SEVERITY) | set(entity.SEVERITY)`. `test_methodology_is_v2` becomes `test_methodology_is_v3`.
- tests/integration/test_reports.py: the site-audit fixture's code `llms_txt` (not a real crawl code) becomes `llms_missing`, and the expected row is `["nike.com", "llms.txt missing", "Low", "404 (expected 200)"]`; the footer assert reads "Methodology v3"; the stored-run assert reads "3". The v1 run fixture is unchanged.
- tests/integration/test_api_reports.py: `methodology_version == "3"`.

Results, as the Task 1 report records them:
- Step 2 (red, on the unchanged code): the three files stopped at collection with "ImportError: cannot import name 'AUDIT_LABEL' from 'bsi_core.reports'" (`1 error in 0.36s`); the two integration files alone gave `4 failed, 26 passed, 2 warnings in 18.84s` (test_cmo_opening_agrees_with_brand_deltas, test_seo_sections, test_generate_freezes_the_document, test_manual_run_returns_document_and_leaves_the_stamp).
- Step 4 (green, the three files): `40 passed, 2 warnings in 11.00s`.
- Step 5 (backend gate, from `gate-task1.txt`; the exit code is the `gate exit 0` the step printed): ruff format "169 files left unchanged"; ruff check "All checks passed!"; ruff format --check "169 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1554 passed, 2 deselected, 2 warnings in 238.83s (0:03:58)" (the 2 known third-party warnings: the `StarletteDeprecationWarning` from fastapi/testclient.py and the anyio `BlockingPortal` `DeprecationWarning` from starlette/testclient.py); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%"). The banned-word grep over `git diff` had no match.

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 186989f | docs: slice 30 spec, readable audit-code labels |
| 44490a0 | docs: slice 30 spec review fixes |
| 8059859 | docs: slice 30 spec, re-run scratch evidence |
| b13d0d4 | docs: slice 30 plan |
| 4dac8f1 | docs: slice 30 plan review fixes |
| 5f6c199 | feat(reports): readable audit-code labels, methodology v3 |
| 00556fe | docs: slice 30 findings, index and notes |
| fb29c74 | docs: slice 30 final review fixes |

## 2. Live check on dev

None: no model call and no spend; the tests pin the cells (spec §2).

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): reports.py:104-107, the docstring repeats "a test checks every audit code has an entry", which the comment at reports.py:72-74 already says; harmless; the brief's exact text"
  - Left deferred (R10).
- "Task 2: minor (deferred): the spec's marking line after R7 says only the titles of R6 and R7 are the writer's wording, but R6's Why is too (marked inline); the findings version (findings-slice30.md:54) adds "and R6's Why""
  - Fixed in the fix wave (R9).
- "Task 2: minor (deferred): R7's "Why" label is the writer's field assignment of the ledger's clause (verbatim text), not marked"
  - Left deferred (R10).
- "Task 2: minor (deferred): the R6 and R7 ledger quotes (findings-slice30.md:51,53) nest double quotes inside double quotes; cosmetic"
  - Left deferred (R10).

From the final whole-branch review (ledger lines tagged `Important` and `minor (deferred)`). The result, as recorded: "Final review (a01033c9042510ea1, 5ba32c8..00556fe): "Ready to merge? With fixes"; 0 Critical, 1 Important, 1 Minor."
- "Final: Important: the docs lack what the ledger recorded after 00556fe: R8 and the three Task 2 minor (deferred) lines; add them to the spec Rulings, README range, the plan's Task 2 bullet and findings §3"
  - Fixed in the fix wave (R9).
- "Final: minor (deferred): spec line 87, the marking line after R7 leaves out "R6's Why"; fix in the same edit"
  - Fixed in the fix wave (R9).

The final review's triage, as recorded: "Final triage of the deferred minors: Task 1 docstring repeat — leave deferred; Task 2 spec marking line — fix before merge; Task 2 R7 Why label — leave deferred; Task 2 nested quotes — leave deferred"

From the fix wave's scoped re-review (recorded after merge, R11 and R12). The result, as recorded: "Fix wave re-review (af2370254a032ea7d, 00556fe..fb29c74): "All findings addressed: Yes"; new breakage 2 Minor, 0 Critical, 0 Important; 2 out-of-scope observations."
- "Fix wave: parked — in R8–R11 (spec 80–83 and findings §3) the split of each ledger line into Decided and Why is the writer's choice and is not marked; the marking line still says "their other fields are from the ledger" — Ruling: R12 — no second fix wave; mark it in the post-merge docs commit — cost if wrong: an unmarked field assignment until then"
  - Note (2026-10-01, after merge, R12): marked under the rulings below.
- "Fix wave: parked — the plan's Fix wave bullet says every quoted line got a Fixed/Left note (the triage quote has none), omits the note added under the Task 1 line, and reads as if the spec also carries the ledger lines — Ruling: R12 — correct it by a dated note in the post-merge docs commit — cost if wrong: a slightly overstated bullet until then"
  - Note (2026-10-01, after merge, R12): corrected by a dated note under the plan's Fix wave bullet.
- "Fix wave: minor (deferred): out of scope: the plan's Task 2 bullet says "The ledger records two rulings, made before execution: R6 … and R7"; true as worded, but R8 appears later in the same bullet, easy to misread"
  - Not ruled on; recorded here as observed.
- "Fix wave: minor (deferred): out of scope: the ledger's "Fix wave" line is not quoted in the docs; R9 does not ask for it"
  - Not ruled on; recorded here as observed.

Parked: none. The ledger has no parked lines. (Correction, 2026-10-01, after merge: the fix wave's re-review led to the two parked lines quoted above.)

Rulings (spec `## Rulings`, quoted in full):
- **R1: the fixture's `robots_ok` code stays.** Decided: the integration fixture's other check code, `robots_ok` (not a real crawl code either), is left as is. Found by the controller writing the spec (not raised in chat). Why: it is a passing check, and the report renders only failed checks, so its label never shows. Cost if wrong: a second unreal code stays in a test fixture. Named in chat when made.
- **R2: `about_missing` reads "About page link missing".** Decided: the user chose this over the approved "About page missing" (options: this, "No About page linked from homepage", keep). Found by the spec review of 186989f: the check fails when the homepage has no link to an About page, which may still exist. Why: the label should say what the check tests. Cost if wrong: none. Asked in chat.
- **R3: `bot_blocked` keeps "Crawler blocked by robots.txt".** Decided: the user kept the approved label over "Crawler disallowed by robots.txt rules". Found by the spec review of 186989f: the check also fails when robots.txt is unreachable (read as disallow-all, RFC 9309). Why: right in the common case; the Detail column shows the other. Cost if wrong: an unreachable robots.txt reads as a block. Asked in chat.
- **R4: the spec review's four precision points were applied.** Decided: the fallback applies to the whole code; two test cases (an empty tail, a non-audit code with a colon); the copy check is a grep, not a test; impact labels named as unchanged; one findings-slice17 bullet to update and its line 76 left. Found by the spec review of 186989f. Why: a plan writer would otherwise guess; no design change. Cost if wrong: none. Named in chat when made.
- **R5: the scratch evidence was re-run after R2 and R4.** Decided: re-run red and green with the new label and the two added asserts, and record the result. Found by the re-review of 44490a0. Why: the recorded run predated them. Cost if wrong: none. Named in chat when made.
- **R6: the plan review's three minor points were applied.** Decided: the plan review's three minor points were applied (commit 4dac8f1): the comment above `OWNER_LABEL` now says "every other non-audit code"; the docstring says a test checks every audit code has an entry; the findings outline gains an "Untested" line. Found by the plan review of b13d0d4. Why (the writer's own wording; the ledger records none): accuracy and completeness; no design change. Cost if wrong: none. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R6 — the plan review's three minor points were applied (commit 4dac8f1): the comment above `OWNER_LABEL` now says "every other non-audit code"; the docstring says a test checks every audit code has an entry; the findings outline gains an "Untested" line — found by the plan review of b13d0d4 — cost if wrong: none. Named in chat when made."
- **R7: the plan's "Verified before committing" line stays.** Decided: the plan's "Verified before committing" line is left unchanged although the re-review of 4dac8f1 asked whether it predates that commit. Found by the plan re-review of 4dac8f1. Why: the scratch re-run with all 14 blocks (including the new comment and docstring) was chained before the 4dac8f1 commit and passed (main integration 4 failed, 26 passed; patched 40 passed; ruff, format and mypy clean). Cost if wrong: one line that does not name its re-run. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R7 — the plan's "Verified before committing" line is left unchanged although the re-review of 4dac8f1 asked whether it predates that commit: the scratch re-run with all 14 blocks (including the new comment and docstring) was chained before the 4dac8f1 commit and passed (main integration 4 failed, 26 passed; patched 40 passed; ruff, format and mypy clean) — found by the plan re-review of 4dac8f1 — cost if wrong: one line that does not name its re-run. Named in chat when made."
- **R8: a read-before-edit failure is not a tool refusal.** Decided: the read-before-edit failure is not a tool refusal. Found by the Task 2 implementer's report (its concern 1). Why: it is the Edit tool's precondition, the dispatch told the implementer to read each file first, and it repeated the same Edit with the same tool after reading — no workaround. Cost if wrong: a refusal counted as a precondition. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R8 — the read-before-edit failure is not a tool refusal: it is the Edit tool's precondition, the dispatch told the implementer to read each file first, and it repeated the same Edit with the same tool after reading — no workaround — cost if wrong: a refusal counted as a precondition. Named in chat when made."
- **R9: the one fix wave completes the docs.** Decided: the one fix wave adds R8–R11 to the spec and findings §3, quotes the Task 2 and Final deferred lines, the Final Important line and the triage in findings §3, adds "and R6's Why" to the spec's marking line, names R8 in the plan's Task 2 bullet, adds final-review and fix-wave bullets, and sets the README range to R1–R11. Found by the final review of 5ba32c8..00556fe. Why: the final review asked for these before merge. Cost if wrong: none. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R9 — the one fix wave adds R8–R11 to the spec and findings §3, quotes the Task 2 and Final deferred lines, the Final Important line and the triage in findings §3, adds "and R6's Why" to the spec's marking line, names R8 in the plan's Task 2 bullet, adds final-review and fix-wave bullets, and sets the README range to R1–R11 — the final review asked for these before merge — cost if wrong: none. Named in chat when made."
- **R10: three minors stay deferred.** Decided: leave deferred: the docstring repeat (reports.py:104-107), R7's unmarked Why field label, and the nested double quotes. Found by the Task 1 review and the Task 2 review; triaged by the final review. Why: harmless, verbatim and cosmetic respectively, per the final review's triage. Cost if wrong: three small polish points stay. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R10 — leave deferred: the docstring repeat (reports.py:104-107), R7's unmarked Why field label, and the nested double quotes — harmless, verbatim and cosmetic respectively, per the final review's triage — cost if wrong: three small polish points stay. Named in chat when made."
- **R11: the post-merge docs commit gets one review only.** Decided: the post-merge docs commit records the fix wave's re-review result and gets one review only; anything that review finds goes into the PR description. Found by the controller. Why: the slice 29 precedent. Cost if wrong: a last finding lives outside the docs. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R11 — the post-merge docs commit records the fix wave's re-review result and gets one review only; anything that review finds goes into the PR description — the slice 29 precedent — cost if wrong: a last finding lives outside the docs. Named in chat when made."
- The ruling titles of R6–R11 and R6's Why are the writer's own wording, and so are the "Found by" fields of R8–R11 (the ledger's ruling lines give none: R8's is derived from the Task 2 implementer's concern (1), R9's from the final review line, R10's from the review lines and the triage, R11's from the controller recording it); their other fields are from the ledger.
  - Note (2026-10-01, after merge, R12): in R8–R11 the split of each ledger line into Decided, Why and Cost if wrong is the writer's field assignment; the text of each field is the ledger's. "Their other fields are from the ledger" above means the text, not the labels. (Writer's own wording.)
- **R12: the fix wave's re-review minors were parked for the post-merge docs commit.** (Title: writer's own wording.) Decided: no second fix wave; mark the Decided/Why split of R8–R11 and correct the plan's Fix wave bullet by dated notes in the post-merge docs commit. Found by the scoped re-review of 00556fe..fb29c74 (writer's own wording; the ledger names the finding, not the finder). Why: the process allows one fix wave (writer's own wording; the ledger gives no Why). Cost if wrong: an unmarked field assignment and a slightly overstated bullet until then. Named in chat when made; recorded here after merge.
  - The ledger lines, as recorded: "Fix wave: parked — in R8–R11 (spec 80–83 and findings §3) the split of each ledger line into Decided and Why is the writer's choice and is not marked; the marking line still says "their other fields are from the ledger" — Ruling: R12 — no second fix wave; mark it in the post-merge docs commit — cost if wrong: an unmarked field assignment until then"; "Fix wave: parked — the plan's Fix wave bullet says every quoted line got a Fixed/Left note (the triage quote has none), omits the note added under the Task 1 line, and reads as if the spec also carries the ledger lines — Ruling: R12 — correct it by a dated note in the post-merge docs commit — cost if wrong: a slightly overstated bullet until then"

Out of scope (spec):
- The other three items (rate limits, webhook signing, "-es" folding): later slices.
  - Note (2026-10-01): done in slices 31, 32 and 33.
- Labels for non-audit codes (task statuses, impact labels, intents, owners, severities, sentiments).
- Re-rendering stored v2 runs.
- The fixture's other check code `robots_ok` (passing checks are not rendered; R1).

Carried forward from docs/findings-slice29.md §3 ("Carried forward from docs/findings-slice28.md §3"), still open:
- The judge-agreement question, waiting on the user.

Untested: nothing beyond the Out of scope list.
