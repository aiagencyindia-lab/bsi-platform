# Slice 30 design: readable audit-code labels in reports

## Context

Codebase facts: main `5ba32c8`, checked 2026-10-01.

The user asked for four smaller platform items: webhook signing, rate limits on the public routes, the slice 17 acronym labels, and "-es" folding in `rivals._stem`. Asked for an order in chat (with three options and trade-offs), the user chose A: acronym labels first (this slice), then rate limits, webhook signing, and "-es" folding, each its own later slice.

docs/findings-slice17.md §3 records: "`label()` reads acronyms awkwardly for real audit codes: `llms_missing` → "Llms missing", `bot_ua_blocked` → "Bot ua blocked", `org_sameas_missing` → "Org sameas missing". … an override table would read better and needs a methodology bump. Cost: wording in client-facing SEO reports. The integration test's site-audit fixture uses the code `llms_txt`, which is not a real crawl code."

Facts read before the approaches (packages/core/bsi_core/reports.py, crawl.py, entity.py; tests/unit/test_reports.py, tests/integration/test_reports.py, tests/integration/test_api_reports.py):
- `label(code)` (reports.py) returns `OWNER_LABEL[code]` for the three owner codes, and otherwise the code with underscores as spaces and its first letter capitalised. The SEO report's "Site audit" table calls it on each failed check's code and severity.
- The site audit codes are the keys of `crawl.SEVERITY` (11) and `entity.SEVERITY` (13): 24 codes. Two crawl codes carry a suffix in stored checks: `bot_blocked:{bot}` and `bot_ua_blocked:{bot}`, which read today as "Bot ua blocked:GPTBot". Others read awkwardly too, for example `org_url_mismatch` → "Org url mismatch".
- `METHODOLOGY_VERSION = "2"`, with the comment "Bump whenever a builder changes what it computes or how a cell is formatted". Stored runs keep their frozen cells and version (slice 17's convention for v1 → v2). Tests assert "2" in tests/unit/test_reports.py (`test_methodology_is_v2`), tests/integration/test_reports.py (the footer, and a stored run) and tests/integration/test_api_reports.py.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "taken as four separate sub-projects. Webhook signing changes what external receivers get, rate limits add a new layer in front of the public routes, the acronym labels change what users see, and the "-es" folding changes how competitor slugs are matched. Each touches a different part of the system, so each gets its own spec, plan and run, one slice at a time."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-01, in plan mode). The approaches for the labels (A: a hand-written table for all 24 audit codes; B: a word-level acronym map in `label()`; C: override only the three named codes) were written in a chat message with trade-offs and a recommendation; the user chose A. Each design section's text was in chat before its approval question; the user approved Section 1 and Section 2. The user then approved the plan-mode plan.

## Design

### 1. The labels and the lookup rule

In packages/core/bsi_core/reports.py, beside `OWNER_LABEL`, a new `AUDIT_LABEL` dict:

| Code | Label |
|---|---|
| `home_unreachable` | Homepage unreachable |
| `bot_blocked` | Crawler blocked by robots.txt |
| `bot_ua_blocked` | Crawler user agent blocked |
| `sitemap_missing` | Sitemap missing |
| `sitemap_invalid` | Sitemap invalid |
| `org_schema_missing` | Organization schema missing |
| `title_missing` | Page title missing |
| `description_missing` | Meta description missing |
| `h1_missing` | H1 heading missing |
| `canonical_missing` | Canonical URL missing |
| `llms_missing` | llms.txt missing |
| `org_name_mismatch` | Organization name mismatch |
| `org_url_mismatch` | Organization URL mismatch |
| `org_logo_missing` | Organization logo missing |
| `org_sameas_missing` | Organization sameAs profiles missing |
| `website_schema_missing` | WebSite schema missing |
| `title_brand_missing` | Brand missing from page title |
| `about_missing` | About page link missing |
| `about_unreachable` | About page unreachable |
| `about_brand_missing` | Brand missing from About page |
| `wikidata_missing` | Wikidata item missing |
| `wikidata_name_mismatch` | Wikidata name mismatch |
| `wikidata_logo_missing` | Wikidata logo missing |
| `social_links_conflict` | Social profiles conflict |

"llms.txt" keeps the file's lower case; "sameAs" and "WebSite" are schema.org names as schema.org writes them.

`label(code)` splits the code at the first ":" into a head and a tail. If the head is in `AUDIT_LABEL`, it returns that label, followed by ": " and the tail when the tail is not empty (`bot_ua_blocked:GPTBot` → "Crawler user agent blocked: GPTBot"). Otherwise it behaves as today, on the whole code (the tail is not dropped): `OWNER_LABEL`, then the words-and-capital rule. The docstring and the table's comment say audit codes come from the table and that a test checks every audit code has an entry.

Unchanged: the labels of task statuses, impact labels, intents, owners, severities and sentiments; `cluster_label`; crawl.py, entity.py and their codes; the API shapes (`openapi.json`, `schema.d.ts`).

### 2. Methodology, tests, docs

- `METHODOLOGY_VERSION = "3"`; the comment above it gains "v3 = audit codes read as words from AUDIT_LABEL." Stored runs keep their v2 cells and footer.
- tests/unit/test_reports.py: in `test_label_reads_codes_as_words`, `label("h1_missing")` → "H1 heading missing", plus cases for `llms_missing`, `org_sameas_missing`, `org_url_mismatch`, `bot_ua_blocked:GPTBot` → "Crawler user agent blocked: GPTBot" and `bot_blocked:ClaudeBot` → "Crawler blocked by robots.txt: ClaudeBot", `bot_blocked:` (an empty tail) → "Crawler blocked by robots.txt", and a non-audit code with a colon, `needs_review:x` → "Needs review:x" (as today); the other cases are unchanged. A new test checks that `AUDIT_LABEL`'s keys are exactly the keys of `crawl.SEVERITY` and `entity.SEVERITY`. `test_methodology_is_v2` becomes `test_methodology_is_v3`.
- tests/integration/test_reports.py: the footer assert reads "Methodology v3"; the stored-run assert reads "3"; the v1 fixture stays. The site-audit fixture's code `llms_txt` (not a real crawl code) becomes `llms_missing`, and the expected row becomes `["nike.com", "llms.txt missing", "Low", "404 (expected 200)"]`.
- tests/integration/test_api_reports.py: `methodology_version == "3"`.
- Red: on main's code the unit test file fails at import (`AUDIT_LABEL` does not exist) and the integration files fail 4 tests; green with the change. Checked on scratch copies on 2026-10-01: main gave the import error and `4 failed, 26 passed` for the two integration files; patched gave `40 passed` for the three files; ruff check and ruff format clean.
- Copy: the new labels, test names, fixtures and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff (by the implementer and the controller), not by a new test.
- Docs: docs/findings-slice30.md; a dated update (original kept) under the docs/findings-slice17.md §3 bullet on `label()`'s acronyms and the `llms_txt` fixture (one bullet); that file's line 76, a historical note citing "Llms txt", is left as is; README rows for the spec, the plan and the findings.
- No live check: no model call and no spend; the tests pin the cells.
- Gates: both, run by the controller before the finishing menu.

## Rulings

- **R1: the fixture's `robots_ok` code stays.** Decided: the integration fixture's other check code, `robots_ok` (not a real crawl code either), is left as is. Found by the controller writing the spec (not raised in chat). Why: it is a passing check, and the report renders only failed checks, so its label never shows. Cost if wrong: a second unreal code stays in a test fixture. Named in chat when made.
- **R2: `about_missing` reads "About page link missing".** Decided: the user chose this over the approved "About page missing" (options: this, "No About page linked from homepage", keep). Found by the spec review of 186989f: the check fails when the homepage has no link to an About page, which may still exist. Why: the label should say what the check tests. Cost if wrong: none. Asked in chat.
- **R3: `bot_blocked` keeps "Crawler blocked by robots.txt".** Decided: the user kept the approved label over "Crawler disallowed by robots.txt rules". Found by the spec review of 186989f: the check also fails when robots.txt is unreachable (read as disallow-all, RFC 9309). Why: right in the common case; the Detail column shows the other. Cost if wrong: an unreachable robots.txt reads as a block. Asked in chat.
- **R4: the spec review's four precision points were applied.** Decided: the fallback applies to the whole code; two test cases (an empty tail, a non-audit code with a colon); the copy check is a grep, not a test; impact labels named as unchanged; one findings-slice17 bullet to update and its line 76 left. Found by the spec review of 186989f. Why: a plan writer would otherwise guess; no design change. Cost if wrong: none. Named in chat when made.

## Out of scope

- The other three items (rate limits, webhook signing, "-es" folding): later slices.
- Labels for non-audit codes (task statuses, impact labels, intents, owners, severities, sentiments).
- Re-rendering stored v2 runs.
- The fixture's other check code `robots_ok` (passing checks are not rendered; R1).
