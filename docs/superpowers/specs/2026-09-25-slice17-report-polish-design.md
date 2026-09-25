# Slice 17 design: report polish (same-origin PDF, readable labels, Intent column)

## Context

Slice 15 shipped reports with a public share page and a PDF. Its findings §3 left three items to fix before a real client gets a link: the PDF link is built from the server-side `API_URL`, so it breaks where the API host is not public and it exposes that host on the white-label page; client-facing cells print raw codes such as `third_party` and `impact_measured`; and the SEO report's "Content gaps" table repeats a topic across intents with nothing to tell the rows apart. The user asked to fix these three. Classification: bounded, but the user's process requires a spec and plan for every change; brainstorming ran on Opus 5.5 on 2026-09-25.

Decisions approved in chat:

- **PDF host:** a same-origin Route Handler in the web app, `/r/{token}/pdf`, proxies the API's `/v1/r/{token}.pdf` server-side. Rejected: a `next.config` rewrite (API_URL fixed at build time) and a separate `PUBLIC_API_URL` (the API host still shows on the client page).
- **Labels:** in the report documents only, for new runs. Stored runs stay frozen. The operator's web tabs are unchanged.
- **Live check:** read-only on dev, through the new route against the five runs already stored; no new run is generated.

Codebase facts the design rests on:

- `apps/web/src/lib/api.ts` exports `API_URL` (`process.env.API_URL ?? "http://localhost:8000"`), `api()` (cookie key) and `publicApi()` (no key). `API_URL` is also used to build the PDF href in `b/[id]/reports/page.tsx:136` and `r/[token]/page.tsx:33`, and by the login action.
- The API's `GET /v1/r/{token}.pdf` (`routers/public.py`) validates the token with `^[A-Za-z0-9_-]{20,64}$` (422 otherwise), 404s an unknown or revoked token, and returns `application/pdf` with `Content-Disposition: attachment; filename="…"` and `Cache-Control: no-store`.
- The web app has no Route Handlers; the project rule is "Server Components and server actions only". `apps/web/vitest.config.ts` exists; `api.test.ts` stubs global `fetch`.
- `bsi_core/reports.py` builders print raw codes: source `owner` (`citations.OWNERS = ("brand", "rival", "third_party")`) in the CMO and SEO source tables; `Task.status` (`TASK_STATUSES`) and `impact_label` (`IMPACT_LABELS`) in the Tasks table; `Mention.sentiment` in the PR sentiment mix; site-audit `code` and `severity` (`crawl.SEVERITY`, `entity.SEVERITY` keys; values high/medium/low) in the SEO Site audit table. The SEO gap table columns are `Topic, Prompts, Brand mention rate, Top rival`; the content report's gap table already carries a Page type column.
- `reports.METHODOLOGY_VERSION = "1"`, with the slice 15 rule: bump whenever a builder changes what it computes or how a cell is formatted. Every stored run records its version and prints it in the footer.
- `gaps.clusters` rows carry `intent` (one of `models.INTENTS`, hyphenated forms such as `problem-based`) and `topic`.

Brainstorming ran on Opus 5.5; the session switched to Fable 5.1 while the spec was written, and the plan is written there with the user's standing permission for planning on Fable 5.1. Implementers and reviewers run on Opus 5.5 only.

## Design

### 1. Same-origin PDF route (`apps/web`)

- `apps/web/src/app/r/[token]/pdf/route.ts` exports `GET(request, { params })`. It is the app's first Route Handler; the frontend rule becomes "Server Components, server actions, and this one Route Handler for the public PDF" (recorded in the process memory).
- Behaviour:
  1. If the token does not match `^[A-Za-z0-9_-]{20,64}$`, return a plain 404 without calling the API.
  2. `fetch(`${API_URL}/v1/r/${token}.pdf`, { cache: "no-store" })`: no Authorization header, no cookie; `API_URL` is the existing module constant from `lib/api.ts`, read when the server starts (not per request, and not at build time).
  3. API 404 or 422 → plain 404. Any other non-2xx, or a thrown fetch → plain 502 with no detail. No error body names the product or the API host.
  4. Otherwise stream the body with the API's `Content-Type` and `Content-Disposition`, plus `Cache-Control: no-store`.
- Both PDF links become the relative `/r/{token}/pdf`: the archive's "PDF" link in `b/[id]/reports/page.tsx` and the public page's "Download PDF" (`pdfHref`) in `r/[token]/page.tsx`. `API_URL` then appears only in `lib/api.ts`, the login action and the new route, all server-side. The API's own route is unchanged.
- Tests (vitest, stubbing `fetch`): a valid token streams the body with the three headers and the request carries no Authorization header; a malformed token gives 404 with `fetch` never called; API 404 and 422 give 404; API 500 and a throwing `fetch` give 502; and `ReportBody` renders `pdfHref` as given (the pages pass `/r/{token}/pdf`; their hrefs are checked by grep and the live check, not a unit test). `apps/web/vitest.config.ts` gains an `@` → `src` alias so the route's `@/lib/api` import resolves in tests.

### 2. Readable labels and the Intent column (`bsi_core/reports.py`)

- `label(code: str) -> str`: `OWNER_LABEL.get(code)` if present, else the code with underscores replaced by spaces and the first letter capitalised (`impact_measured` → `Impact measured`, `h1_missing` → `H1 missing`, `problem-based` → `Problem-based`, `high` → `High`). `OWNER_LABEL = {"brand": "Own site", "rival": "Competitor", "third_party": "Third party"}`.
- Applied in the builders, new runs only:
  - Owner cells in CMO/agency "Top cited sources" and SEO "Cited sources".
  - CMO/agency Tasks: Status and Impact cells (impact stays `—` when None).
  - PR "Sentiment mix": the Sentiment cell.
  - SEO "Site audit": Check and Severity cells.
- SEO "Content gaps" columns become `Intent, Topic, Prompts, Brand mention rate, Top rival`, with `label(c["intent"])` first. The content report's "Content gaps with briefs" is unchanged.
- `METHODOLOGY_VERSION` becomes `"2"`. New runs print `Methodology v2`; stored runs keep `v1`.
- Tests: unit tests for `label()` (owner overrides including `Own site`, underscore codes including `H1 missing`, a hyphenated intent, a one-word code, an empty string returns `""`) and one pinning `METHODOLOGY_VERSION == "2"`; the report integration tests updated to the labelled cells (`Third party`, `Impact measured`, `Improved`, `Llms txt`/`Low`, `Neutral`/`Negative`), plus a new test of the SEO gap table's five columns with Intent values `Commercial` and `Problem-based`; the CMO footer test now expects `Methodology v2`, and two existing tests that assert a stored run's `methodology_version` moved from `"1"` to `"2"`; the existing copy-ban test still scans every builder's output.

### 3. Live check, docs, out of scope

- Live check on dev, read-only, no new rows: API on :8000 and a production build of the web app; for the five report runs already stored (tokens read from dev with a read-only query), fetch `/r/{token}/pdf` and check 200, `%PDF-`, the `Content-Disposition` filename, `no-store`, and that the public page's "Download PDF" href is `/r/{token}/pdf`; a malformed and an unknown token give 404 with no product name. The new labels, the Intent column and `Methodology v2` need a new run, which is a write; they are covered by tests only unless the user asks for a run. Results are recorded as observed in `docs/findings-slice17.md` §2.
- Docs: `docs/findings-slice17.md` (what was built, live check, deferred/decisions, not covered by tests), a `docs/README.md` section, the spec's Rulings, the plan's "Changes made during execution", and the process-memory line for the Route Handler exception.

## Rulings

Made during execution, in the order recorded in the ledger. Each gives the decision, the reason, and the cost if it is wrong.

1. The PDF route reads `API_URL` as the existing module constant, evaluated when the server process starts, not at build time; §1's "read at request time" is corrected to that. The spec's reason was to avoid the build-time rewrite trap, which this meets. Cost if wrong: changing `API_URL` needs a web restart.
2. The pages' relative PDF hrefs are verified by a grep and the live check, not by a unit test of the Server Components, because rendering those pages in vitest needs the API and the Next runtime; `ReportBody`'s test covers rendering `pdfHref` as given. Cost if wrong: a regression in either page's href is caught only by the live check.
3. `apps/web/vitest.config.ts` gains an `@` → `src` alias. The route test is the first test that imports `@/` at runtime, slice 15's preflight already allowed this alias if needed, and relative imports would break the `@/` convention. Cost if wrong: one config line.
4. The PDF route also reads `API_URL` (server-side, imported from `lib/api`). §1's "`API_URL` then appears only in `lib/api.ts` and the login action" contradicted its own fetch line and is corrected to include the route; the key-secrecy rule is unaffected, since only the host constant is imported. Cost if wrong: none.
5. Two tests the plan did not name (the `generate` test in `tests/integration/test_reports.py` and the manual-run test in `tests/integration/test_api_reports.py`) move from `methodology_version` `"1"` to `"2"`. They follow directly from the approved bump, and no stored run is rewritten. Cost if wrong: none.
6. The integration tests assert `Third party` and `Llms txt` instead of §2's example cells `Own site` and `H1 missing`, because the test scene's data yields those codes; both prove the cells go through `label()`, and the unit test pins `Own site` and `H1 missing`. Cost if wrong: none.

## Out of scope

Readable labels on the operator's web tabs; rewriting labels in stored runs; removing or restricting the API's public `/v1/r/{token}.pdf`; caching or a CDN for the PDF; logos in the PDF; an Intent column in the content report.
