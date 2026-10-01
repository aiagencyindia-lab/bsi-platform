# Slice 30 Audit Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Site audit codes read as client-facing words in reports ("Crawler user agent blocked: GPTBot"), from a hand-written table, with the report methodology bumped to v3.

**Architecture:** An `AUDIT_LABEL` dict beside `OWNER_LABEL` in packages/core/bsi_core/reports.py; `label()` looks up the part before ":" and keeps the tail; everything else is unchanged. Tests in tests/unit/test_reports.py, tests/integration/test_reports.py and tests/integration/test_api_reports.py.

**Tech Stack:** Python 3.13, pytest (the shared `bsi_test` database for the integration tests).

**Spec:** `docs/superpowers/specs/2026-10-01-slice30-audit-labels-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice30-audit-labels`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** crawl.py, entity.py and their codes; `cluster_label`; the labels of task statuses, impact labels, intents, owners, severities and sentiments; the API shapes (`openapi.json`, `schema.d.ts`); the v1 run fixture in tests/integration/test_reports.py.
- **Shared test DB:** run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it.
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Banned words:** copy (labels, comments, docstrings, test names, fixtures, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py); check by grepping the diff.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal, not to a file).
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/reports.py` | `METHODOLOGY_VERSION` and its comment, `AUDIT_LABEL`, `label()` |
| `tests/unit/test_reports.py` | label cases, the coverage test, the methodology test |
| `tests/integration/test_reports.py` | footer and stored-run version, the site-audit fixture and row |
| `tests/integration/test_api_reports.py` | the API's methodology version |
| docs | `docs/findings-slice30.md`, a dated update in `docs/findings-slice17.md` §3, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The audit labels

**Files:** Modify `packages/core/bsi_core/reports.py` (about lines 36–79); tests `tests/unit/test_reports.py`, `tests/integration/test_reports.py`, `tests/integration/test_api_reports.py`.

**Interfaces:** Produces `reports.AUDIT_LABEL: dict[str, str]` and `label(code: str) -> str` (same signature). Consumes `crawl.SEVERITY`, `entity.SEVERITY`.

- [ ] **Step 1: Write the failing tests.** Make these replacements (each old string is found once in its file).

In tests/unit/test_reports.py, replace

```python
from bsi_core.reports import (
    METHODOLOGY_VERSION,
```

with

```python
from bsi_core import crawl, entity
from bsi_core.reports import (
    AUDIT_LABEL,
    METHODOLOGY_VERSION,
```

then replace

```python
    assert label("h1_missing") == "H1 missing"
```

with

```python
    assert label("h1_missing") == "H1 heading missing"
    assert label("llms_missing") == "llms.txt missing"
    assert label("org_sameas_missing") == (
        "Organization sameAs profiles missing"
    )
    assert label("org_url_mismatch") == "Organization URL mismatch"
    assert label("bot_ua_blocked:GPTBot") == (
        "Crawler user agent blocked: GPTBot"
    )
    assert label("bot_blocked:ClaudeBot") == (
        "Crawler blocked by robots.txt: ClaudeBot"
    )
    assert label("bot_blocked:") == "Crawler blocked by robots.txt"
    assert label("needs_review:x") == "Needs review:x"
```

then replace

```python
def test_methodology_is_v2():
    assert METHODOLOGY_VERSION == "2"
```

with

```python
def test_every_audit_code_has_a_label():
    assert set(AUDIT_LABEL) == set(crawl.SEVERITY) | set(entity.SEVERITY)


def test_methodology_is_v3():
    assert METHODOLOGY_VERSION == "3"
```

In tests/integration/test_reports.py, replace `                        "code": "llms_txt",` with `                        "code": "llms_missing",`; replace

```python
    assert audit.rows == [["nike.com", "Llms txt", "Low", "404 (expected 200)"]]
```

with

```python
    assert audit.rows == [
        ["nike.com", "llms.txt missing", "Low", "404 (expected 200)"]
    ]
```

replace `    assert doc.footer.startswith("Methodology v2 · pipeline v")` with `    assert doc.footer.startswith("Methodology v3 · pipeline v")`; and replace `        assert run.methodology_version == "2"` with `        assert run.methodology_version == "3"`.

In tests/integration/test_api_reports.py, replace `run["methodology_version"] == "2"` with `run["methodology_version"] == "3"`.

- [ ] **Step 2: Run them to see them fail.** `pgrep -fl pytest` (expect nothing), then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_reports.py tests/integration/test_reports.py tests/integration/test_api_reports.py`. Expected: a collection error in tests/unit/test_reports.py (`ImportError: cannot import name 'AUDIT_LABEL'`). Then run the two integration files alone: `4 failed, 26 passed` (`test_cmo_opening_agrees_with_brand_deltas`, `test_seo_sections`, `test_generate_freezes_the_document`, `test_manual_run_returns_document_and_leaves_the_stamp`). If the result differs, stop and report it.

- [ ] **Step 3: Write the code.** In packages/core/bsi_core/reports.py, replace

```python
# v2 = readable labels and the SEO Intent column.
METHODOLOGY_VERSION = "2"
```

with

```python
# v2 = readable labels and the SEO Intent column.
# v3 = audit codes read as words from AUDIT_LABEL.
METHODOLOGY_VERSION = "3"
```

then replace

```python
# Client-facing wording for source owners; every other code reads as
# words by the rule in label().
```

with

```python
# Client-facing wording for source owners; every other non-audit code
# reads as words by the rule in label().
```

then replace

```python
    "third_party": "Third party",
}


def label(code: str) -> str:
    """A stored code as words: underscores become spaces and the first
    letter is capitalised, so no per-code table goes stale."""
    if code in OWNER_LABEL:
```

with

```python
    "third_party": "Third party",
}
# Client-facing wording for site audit codes (crawl.SEVERITY and
# entity.SEVERITY); a test checks every audit code has an entry. A
# suffix after ":" (the crawler in "bot_blocked:GPTBot") is kept.
AUDIT_LABEL = {
    "home_unreachable": "Homepage unreachable",
    "bot_blocked": "Crawler blocked by robots.txt",
    "bot_ua_blocked": "Crawler user agent blocked",
    "sitemap_missing": "Sitemap missing",
    "sitemap_invalid": "Sitemap invalid",
    "org_schema_missing": "Organization schema missing",
    "title_missing": "Page title missing",
    "description_missing": "Meta description missing",
    "h1_missing": "H1 heading missing",
    "canonical_missing": "Canonical URL missing",
    "llms_missing": "llms.txt missing",
    "org_name_mismatch": "Organization name mismatch",
    "org_url_mismatch": "Organization URL mismatch",
    "org_logo_missing": "Organization logo missing",
    "org_sameas_missing": "Organization sameAs profiles missing",
    "website_schema_missing": "WebSite schema missing",
    "title_brand_missing": "Brand missing from page title",
    "about_missing": "About page link missing",
    "about_unreachable": "About page unreachable",
    "about_brand_missing": "Brand missing from About page",
    "wikidata_missing": "Wikidata item missing",
    "wikidata_name_mismatch": "Wikidata name mismatch",
    "wikidata_logo_missing": "Wikidata logo missing",
    "social_links_conflict": "Social profiles conflict",
}


def label(code: str) -> str:
    """A stored code as words: an audit code reads from AUDIT_LABEL
    (keeping any ":" suffix; a test checks every audit code has an
    entry), an owner from OWNER_LABEL; any other code has underscores
    as spaces and its first letter capitalised."""
    head, _, tail = code.partition(":")
    if head in AUDIT_LABEL:
        return AUDIT_LABEL[head] + (f": {tail}" if tail else "")
    if code in OWNER_LABEL:
```

- [ ] **Step 4: Run them to see them pass.** `pgrep -fl pytest`, then the Step 2 command for the three files. Expected: `40 passed`. If the count or any result differs, stop and report it.

- [ ] **Step 5: Gate.** `pgrep -fl pytest`, then the Backend gate once. Expected: `gate exit 0`, `1554 passed, 2 deselected` (1553 plus `test_every_audit_code_has_a_label`; the methodology test is renamed, not added), metrics coverage 100%, and the 2 known third-party warnings. Grep the diff for the banned words: no match.

- [ ] **Step 6: Commit.** `git add packages/core/bsi_core/reports.py tests/unit/test_reports.py tests/integration/test_reports.py tests/integration/test_api_reports.py && git commit -m "feat(reports): readable audit-code labels, methodology v3" -m "<trailer>"`.

---

### Task 2: Docs

**Files:** Create `docs/findings-slice30.md` (the controller creates a one-line stub first; fill it with Edit). Modify `docs/findings-slice17.md` §3, `docs/README.md`, the spec's `## Rulings`, and this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice30.md` in the style of `docs/findings-slice29.md`:
  - `## 1. What was built`: the table and the rule, methodology v3, the test changes; the Step 2, 4 and 5 results as the Task 1 report records them; and a commit table from `git log --oneline --reverse main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "None: no model call and no spend; the tests pin the cells (spec §2)."
  - `## 3. Deferred and untested`: every `minor (deferred…)` and `parked` ledger line, quoted as recorded ("Parked: none" if none); every spec ruling quoted in full; the spec's Out of scope list; the still-open items under "Carried forward" in docs/findings-slice29.md §3; and "Untested: nothing beyond the Out of scope list."
- [ ] **Step 2: Dated update, original kept.** Add a sub-bullet starting "Update 2026-10-01 (slice 30):" under the docs/findings-slice17.md §3 bullet that begins "`label()` reads acronyms awkwardly": audit codes now read from `AUDIT_LABEL` (methodology v3), and the fixture uses `llms_missing` (docs/findings-slice30.md). Leave that file's line about "Llms txt" in the plan-deviation notes as it is.
- [ ] **Step 3: README rows** for the spec, the plan and the findings, after the row for `findings-slice29.md`, in the slice 29 rows' format; the spec row names the spec's final ruling range.
- [ ] **Step 4: Rulings.** For each ruling the ledger records that the spec's `## Rulings` does not already hold (match by R-number), add it after the spec's last ruling in the same format (Decided / Found by / Why / Cost if wrong), with its ending as the ledger records it. Mark any field not taken from the ledger as the writer's own wording.
- [ ] **Step 5: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, quoting departures and any tool refusals as recorded; the bullet for the commit that fills this section ends "(this commit)".
- [ ] **Step 6: Grep** the changed docs files for the banned words; expected: no match except this plan's Global Constraints line.
- [ ] **Step 7: Commit** `git add docs && git commit -m "docs: slice 30 findings, index and notes" -m "<trailer>"`.

---

## Self-review against the spec

- §1 table and rule: Task 1 Step 3 (the 24 labels, with R2's "About page link missing"; the head/tail rule; the fallback on the whole code; the comment and docstring). Unchanged items: Global Constraints.
- §2 methodology and tests: Task 1 Steps 1 and 3 (v3 and its comment; every listed test change, including R4's two asserts and the `llms_txt` fixture). Red and green: Steps 2 and 4. Copy: Step 5 and Task 2 Step 6 (a grep, per R4).
- §2 docs: Task 2 Steps 1–3 (findings-slice30; the one dated update in findings-slice17 §3, line 76 left; README rows). No live check: findings §2. Gates: the controller.
- Departures from the spec:
  1. Test code details the spec doesn't state: the line wraps, and `test_every_audit_code_has_a_label` written as a set equality.
  2. TDD order: the tests are written and seen failing first.
  3. Step 5's gate count (1554) and Step 4's 40 come from the scratch runs; the spec states 40 only.
  4. Task 2 also updates the spec's Rulings and this plan's changes section, and asks that derived ruling fields be marked (from the slice 29 lesson); the spec's docs list names neither.
  5. Step 3 also rewords the comment above `OWNER_LABEL` ("every other non-audit code"), which the spec does not mention; without it the comment would be wrong.
- Verified before committing this plan (2026-10-01): every replacement in Task 1 was applied, from this file's own code blocks and inline strings, to scratch copies of main (each old string found exactly once). On main's code the unit file failed at import (`AUDIT_LABEL`) and the two integration files gave `4 failed, 26 passed`; with the change the three files gave `40 passed`. ruff check, ruff format --check and `mypy --strict` (with the repo config) are clean.
- Placeholders: only `<workspace>` and `<trailer>`.

## Changes made during execution

- Task 1 (5f6c199): went as written. The ledger records: "report: Step 2 unit ImportError (AUDIT_LABEL), integration 4 failed, 26 passed (the 4 named); Step 4 40 passed; Step 5 gate exit 0, 1554 passed, 2 deselected, 2 warnings, metrics 100%; banned-word grep no match"; the review "✅ Spec compliant; Task quality: Approved; 0 Critical, 0 Important, 1 Minor", deferred (quoted in docs/findings-slice30.md §3); and one controller check, "⚠️ resolved by controller: the 5f6c199 commit trailer is "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (git log -1 --format=%B before the review); the red/green/gate runs are the report's record". No departures and no tool refusals.
- Task 2: the controller created the one-line stub `docs/findings-slice30.md` before dispatch, as this plan says. The ledger records two rulings, made before execution: R6 (the plan review's three minor points, commit 4dac8f1) and R7 (the "Verified before committing" line left unchanged); Step 4 added both after R5 in the spec's Rulings, and findings §3 quotes their ledger lines. One Edit call on docs/findings-slice17.md was rejected because the file had not yet been read in the session; the implementer read the file and repeated the same Edit; R8 rules that this was the Edit tool's precondition, not a tool refusal. The review "✅ Spec compliant; Task quality: Approved; 0 Critical, 0 Important, 3 Minor", all three deferred (quoted in docs/findings-slice30.md §3); and one controller check, "⚠️ resolved by controller: the 00556fe commit trailer is "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (git log -1 --format=%B before the review); R8 (ledgered after 00556fe) is not yet in the spec, the README range or the plan's Task 2 bullet — goes to the final review's fix wave". No departures. (00556fe)
- Final review (5ba32c8..00556fe), as recorded: "Final review (a01033c9042510ea1, 5ba32c8..00556fe): "Ready to merge? With fixes"; 0 Critical, 1 Important, 1 Minor." The Important finding and the deferred minor are quoted in docs/findings-slice30.md §3. The triage, as recorded: "Final triage of the deferred minors: Task 1 docstring repeat — leave deferred; Task 2 spec marking line — fix before merge; Task 2 R7 Why label — leave deferred; Task 2 nested quotes — leave deferred". Rulings R9, R10 and R11 followed (spec `## Rulings`).
- Fix wave (BASE 00556fe, R9): R8–R11 go into the spec and findings §3 with their ledger lines; the spec's marking line after the rulings adds "and R6's Why"; findings §3 quotes the three Task 2 deferred lines, the Final Important and deferred lines and the triage, each with a "Fixed in the fix wave (R9)" or "Left deferred (R10)" note; this section's Task 2 bullet names R8 and quotes the Task 2 review and the controller's ⚠️ line; the README spec row reads R1–R11; findings §1's commit table gives 00556fe its hash. (fb29c74)
  - Note (2026-10-01, after merge, R12): this bullet overstates slightly: the triage quote has no Fixed/Left note, a "Left deferred (R10)" note was also added under the Task 1 line, and only findings §3 (not the spec) carries the ledger lines.
- Fix-wave re-review, recorded after merge of PR #57 (main afc071f), as recorded: "Fix wave re-review (af2370254a032ea7d, 00556fe..fb29c74): "All findings addressed: Yes"; new breakage 2 Minor, 0 Critical, 0 Important; 2 out-of-scope observations." Its two new minors are parked under R12 and its two out-of-scope observations recorded without a ruling; all four are quoted in docs/findings-slice30.md §3. Post-merge docs and R12 (this commit).
