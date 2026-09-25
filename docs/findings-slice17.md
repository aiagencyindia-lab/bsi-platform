# Findings: slice 17 — report polish

## 1. What was built

**Same-origin PDF route (`apps/web/src/app/r/[token]/pdf/route.ts`).** The web app's first Route Handler. `GET` checks the token against `^[A-Za-z0-9_-]{20,64}$` (the API's own rule) and returns a plain-text 404 `Not found` without calling the API when it does not match. Otherwise it fetches `${API_URL}/v1/r/${token}.pdf` with `cache: "no-store"`, a 30 s timeout (`signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)`, `UPSTREAM_TIMEOUT_MS = 30_000`) and no Authorization header or cookie. An API 404 or 422 becomes a plain 404 `Not found`; any other non-2xx, or a thrown `fetch` (a timeout included), becomes a plain 502 `Report unavailable`. Neither body names the product or the API host. On success it streams the API's body with status 200, the API's `Content-Type` and `Content-Disposition`, and `Cache-Control: no-store`. The error responses also carry `Cache-Control: no-store`. `API_URL` is the existing constant from `lib/api.ts` (`process.env.API_URL ?? "http://localhost:8000"`), read once when the server process loads the module: not per request, and not at build time.

**Relative links.** The archive's "PDF" link in `app/(app)/b/[id]/reports/page.tsx` is now `/r/${r.share_token}/pdf`, and the public page's `pdfHref` in `app/r/[token]/page.tsx` is `/r/${encodeURIComponent(token)}/pdf`. Neither page imports `API_URL` any more; it is used in `lib/api.ts`, the login action (`app/login/actions.ts`) and the new route, all server-side. The API's own `/v1/r/{token}.pdf` is unchanged.

**Vitest alias.** `apps/web/vitest.config.ts` gained `resolve.alias` `@` → `./src`, mirroring tsconfig's `@/*` path, because the route test is the first test that imports `@/…` at runtime (through the route's `@/lib/api` import).

**Labels (`bsi_core/reports.py`).** `OWNER_LABEL = {"brand": "Own site", "rival": "Competitor", "third_party": "Third party"}`. `label(code)` returns `OWNER_LABEL[code]` when present; otherwise the code with underscores replaced by spaces and the first letter capitalised (`impact_measured` → `Impact measured`, `h1_missing` → `H1 missing`, `problem-based` → `Problem-based`, `""` → `""`). Relabelled cells, new runs only:
- Owner in CMO/agency "Top cited sources" and SEO "Cited sources".
- Status and Impact in the CMO/agency Tasks table (Impact stays `—` when there is none).
- Sentiment in the PR "Sentiment mix".
- Check and Severity in the SEO "Site audit".
- Cluster in the SEO "Page citability", through `cluster_label(key)`: a key `cluster:{intent}:{topic}` reads `{label(intent)} · {topic}` (`cluster:commercial:shoes` → `Commercial · shoes`); the key is split on its first two colons only, so a topic may hold a colon, and a key that does not start with `cluster:` or lacks an intent or a topic is shown as stored. The column header stays "Cluster".

**Intent column.** The SEO "Content gaps" table's columns are `Intent, Topic, Prompts, Brand mention rate, Top rival`, with `label(intent)` in the first cell. The content report's "Content gaps with briefs" is unchanged.

**Methodology.** `METHODOLOGY_VERSION = "2"`; new runs record `2` and print `Methodology v2` in the footer. Stored runs are not rewritten and keep `1` and their v1 wording.

**Commits** (`git log --oneline main..HEAD`, oldest first, before this one):

| Commit | Subject |
|---|---|
| 3478b62 | docs: slice 17 design spec, report polish |
| 2efd910 | docs: slice 17 implementation plan, report polish |
| 21f47c4 | feat(web): serve the report PDF from the app's own domain |
| c202adf | feat(reports): readable labels, SEO Intent column, methodology v2 |
| 0e0d1c8 | docs: slice 17 findings, index and rulings |
| ca8f3f1 | fix(reports): readable Cluster cell; time out the PDF proxy fetch |

## 2. Live check

Run by the controller on dev before the finishing menu; filled in below.

| Check | Result |
|---|---|

## 3. Deferred / decisions

From the spec and the build:
- Out of scope (spec): readable labels on the operator's web tabs; rewriting labels in stored runs; removing or restricting the API's public `/v1/r/{token}.pdf`; caching or a CDN for the PDF; logos in the PDF; an Intent column in the content report. Cost: the operator's tabs still show raw codes, and the API's PDF URL still works for anyone who has it.
- Frontend rule exception: the rule was "Server Components and server actions only"; it now also allows this one Route Handler, `app/r/[token]/pdf/route.ts`. Cost: one more kind of server code in the web app to keep in mind.
- "No scored pages in this period." (carried over from slice 15, findings-slice15 §3; still open): the SEO "Page citability" and content "Page citability with next step" sections use the latest page audit per cluster and URL, not filtered by the period, so "in this period" is inaccurate. Cost: wording.
- `label()` reads acronyms awkwardly for real audit codes: `llms_missing` → "Llms missing", `bot_ua_blocked` → "Bot ua blocked", `org_sameas_missing` → "Org sameas missing". The Detail column gives context; an override table would read better and needs a methodology bump. Cost: wording in client-facing SEO reports. The integration test's site-audit fixture uses the code `llms_txt`, which is not a real crawl code.
- The PDF route's upstream fetch times out after 30 s and returns the 502 (spec ruling 8). Cost: a PDF that takes the API longer than 30 s fails; the PRD target is 30 s for 20 pages.
- `API_URL` is read at server start, not per request (spec ruling 1). It is not baked in at build time, which was the spec's concern. Cost: changing `API_URL` needs a web restart.
- Stored runs keep methodology v1 and their raw-code cells; only new runs get v2 wording. Cost: a v1 and a v2 run of the same type read differently side by side; the footer version says why.
- The pages' relative PDF hrefs have no unit test (spec ruling 2); they are checked by grep and the live check. Cost: a regression in either page's href is caught only by the live check.

Minor items deferred from the task reviews, by task:

Task 1
- The route does not cancel the unread upstream body on its 404, 422 and 502 early returns. Cost: the socket is held until garbage collection.
- Any 2xx from the API other than 200 is returned as 200. Cost: none today, since the API returns only 200 on success.
- The archive page builds `/r/{token}/pdf` without `encodeURIComponent`, while the public page encodes. Cost: none while tokens are `[A-Za-z0-9_-]` only.

Task 2
- The gap-table test checks only the first two cells of each row, with no row-length check against the five-column header. Cost: a row missing a trailing cell would pass.
- The `ReportBody.test.tsx` fixture footer still says `Methodology v1`. Cost: none; it is a static fixture, not generated output.
- The suite prints two pre-existing starlette/anyio warnings. Cost: output noise.

Task 3
- The plan's "Changes made during execution" lists the integration label examples (`Third party`, `Llms txt`), which deviate from the spec's §2 examples, not from the plan. Cost: none.
- Fixed in the final review: the plan's line saying the `API_URL` Global Constraint "holds with the route added" now says the constraint was amended to include the route, and this section's commit table now quotes the real subjects.

## 4. Not covered by tests

- The new labels, the Intent column and `Methodology v2` on real dev data: the live check generates no new run, so they are covered only by the unit and integration tests.
- The pages' relative PDF links: checked only by grep and the live check; `ReportBody`'s test covers rendering `pdfHref` as given.
- The Route Handler under a real Next server: the vitest tests call `GET` directly with `fetch` stubbed; it runs under Next only in the live check.
