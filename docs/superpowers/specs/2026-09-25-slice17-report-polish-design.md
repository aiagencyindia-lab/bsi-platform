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
  2. `fetch(`${API_URL}/v1/r/${token}.pdf`, { cache: "no-store" })`: no Authorization header, no cookie; `API_URL` is read at request time.
  3. API 404 or 422 → plain 404. Any other non-2xx, or a thrown fetch → plain 502 with no detail. No error body names the product or the API host.
  4. Otherwise stream the body with the API's `Content-Type` and `Content-Disposition`, plus `Cache-Control: no-store`.
- Both PDF links become the relative `/r/{token}/pdf`: the archive's "PDF" link in `b/[id]/reports/page.tsx` and the public page's "Download PDF" (`pdfHref`) in `r/[token]/page.tsx`. `API_URL` then appears only in `lib/api.ts` and the login action. The API's own route is unchanged.
- Tests (vitest, stubbing `fetch`): a valid token streams the body with the three headers and the request carries no Authorization header; a malformed token gives 404 with `fetch` never called; API 404 and 422 give 404; API 500 and a throwing `fetch` give 502; and `ReportBody` renders `pdfHref` as given (the pages pass `/r/{token}/pdf`).

### 2. Readable labels and the Intent column (`bsi_core/reports.py`)

- `label(code: str) -> str`: `OWNER_LABEL.get(code)` if present, else the code with underscores replaced by spaces and the first letter capitalised (`impact_measured` → `Impact measured`, `h1_missing` → `H1 missing`, `problem-based` → `Problem-based`, `high` → `High`). `OWNER_LABEL = {"brand": "Own site", "rival": "Competitor", "third_party": "Third party"}`.
- Applied in the builders, new runs only:
  - Owner cells in CMO/agency "Top cited sources" and SEO "Cited sources".
  - CMO/agency Tasks: Status and Impact cells (impact stays `—` when None).
  - PR "Sentiment mix": the Sentiment cell.
  - SEO "Site audit": Check and Severity cells.
- SEO "Content gaps" columns become `Intent, Topic, Prompts, Brand mention rate, Top rival`, with `label(c["intent"])` first. The content report's "Content gaps with briefs" is unchanged.
- `METHODOLOGY_VERSION` becomes `"2"`. New runs print `Methodology v2`; stored runs keep `v1`.
- Tests: unit tests for `label()` (owner overrides, an underscore code, a hyphenated intent, a one-word code, an empty string returns `""`); the report integration tests updated to the labelled cells (`Own site`, `Impact measured`, `Improved`, `H1 missing`/`Low`, `Neutral`/`Negative`) and to the SEO gap table's five columns with an Intent value; a test that a new document's footer starts `Methodology v2`; the existing copy-ban test still scans every builder's output.

### 3. Live check, docs, out of scope

- Live check on dev, read-only, no new rows: API on :8000 and a production build of the web app; for the five report runs already stored (tokens read from dev with a read-only query), fetch `/r/{token}/pdf` and check 200, `%PDF-`, the `Content-Disposition` filename, `no-store`, and that the public page's "Download PDF" href is `/r/{token}/pdf`; a malformed and an unknown token give 404 with no product name. The new labels, the Intent column and `Methodology v2` need a new run, which is a write; they are covered by tests only unless the user asks for a run. Results are recorded as observed in `docs/findings-slice17.md` §2.
- Docs: `docs/findings-slice17.md` (what was built, live check, deferred/decisions, not covered by tests), a `docs/README.md` section, the spec's Rulings, the plan's "Changes made during execution", and the process-memory line for the Route Handler exception.

## Rulings

Recorded here as they are made during execution.

## Out of scope

Readable labels on the operator's web tabs; rewriting labels in stored runs; removing or restricting the API's public `/v1/r/{token}.pdf`; caching or a CDN for the PDF; logos in the PDF; an Intent column in the content report.
