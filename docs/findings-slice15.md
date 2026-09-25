# Findings: slice 15 — reports

## 1. What was built

**Data (migration `0017_reports.py`).** Table `report` holds one definition per (brand, type): `type` (CHECK over `cmo, seo, content, pr, agency`), `cadence` (CHECK over `off, weekly, monthly`, default `off`) and `generated_at`, unique on `(brand_id, type)`. Table `report_run` holds the archive: `report_id`, `type`, `source` (CHECK over `scheduled, manual`), `period_from`, `period_to`, `compare_from`, the whole `document` as JSONB, `methodology_version` and a nullable `share_token` with a unique partial index where it is not null; `(brand_id, created_at)` is indexed for the archive. Both tables get `_protect()` (RLS, org index, `bsi_app` grants) and rows in `TENANT_TABLES` and the `org_b` fixture. `brand` gains `report_logo_url`, `report_accent` and `report_prepared_by`. Two SECURITY DEFINER functions, each with `SET search_path = public`, REVOKE from PUBLIC and EXECUTE granted to `bsi_app`: `due_report_runs()` returns `(report_id, brand_id, org_id, report_type, cadence)` for active brands whose cadence is on and whose stamp is NULL or at least 7 (weekly) or 30 (monthly) days old; `report_run_by_token(token)` returns `(run_id, org_id)` and is the only cross-tenant read. ORM: `Report`, `ReportRun`, `REPORT_TYPES`, `REPORT_CADENCES`, `RUN_SOURCES` and the three `Brand` columns in `models.py`.

**Document and builders (`bsi_core/reports.py`).** `METHODOLOGY_VERSION = "1"`. Pydantic models `Document`, `Period` (`from` alias), `Branding`, `Section`, `Paragraph`, `Table`; every cell is a pre-formatted string. Formatters: `fmt_rate` (`0.42 [0.33, 0.52] n=100`, or `— (n=0)`), `fmt_delta` (ASCII signs, `-0.09 [-0.18, +0.01] no significant change`, or the label alone when there is no value), `fmt_pct`, `fmt_signed`, `fmt_day`, `footer` (methodology, pipeline versions, interval methods, generation time in UTC). Five builders, each starting with the Period paragraph and the Visibility table from `brand_deltas`: `build_cmo` (share of voice, competitors, top cited sources, recommendations, tasks, alerts), `build_agency` (`build_cmo` in client-facing mode: title `{brand} visibility report`, a `Prepared by` paragraph when set, no Owner column in Tasks, `Branding` copied from the brand row), `build_seo` (cited sources, site audit, page citability, content gaps, recommendations), `build_content` (prompt performance by topic, content gaps with briefs, page citability, recommendations), `build_pr` (sentiment mix, negative mentions, competitor sentiment, third-party sources naming the brand, new sources). A section with nothing to show is one paragraph (`No … in this period.`). `definition()` upserts the (brand, type) row with `ON CONFLICT DO NOTHING`; `generate()` builds and stores one run with `secrets.token_urlsafe(32)` as its token, SQL only (no HTTP, no model call, no spend) and never stamps `generated_at`.

**PDF (`bsi_core/pdf.py`).** `render_pdf(document) -> bytes` with reportlab 5.0.1 (the version in `uv.lock`; `packages/core` declares `reportlab>=4.2`, and mypy ignores missing imports for `reportlab.*`). A4, built-in Helvetica, a page footer with the methodology line (cut at 180 characters) and `page n`, headings in the branding accent (black when absent or not `#rrggbb`), tables with a repeating header row, a grid and wrapping `Paragraph` cells, and `KeepTogether` on each heading with its first block. No logo; nothing is fetched or written to disk.

**Worker.** `generate_due_reports()` in `worker.py`: reads `due_report_runs()` in `system_session()`, then per row a `tenant_session(org_id)` that calls `generate(source="scheduled")` with 7 or 30 days ending now and sets `report.generated_at = func.now()` in the same transaction; each row has its own `try/log.exception`. `main()` calls it after `deliver_due_alerts`.

**API.** `routers/reports.py`, prefix `/brands/{brand_id}/reports`, every route `TENANT`: `GET ""` (five `ReportOut`, `off` synthesised), `GET /runs?limit=` (1–200, default 50, newest first), `GET /runs/{run_id}`, `POST /runs/{run_id}/share` (new token), `DELETE /runs/{run_id}/share` (204), `PUT /{type}` (cadence; off→on nulls the stamp), `POST /{type}/runs` (manual run, 201). The `/runs` routes are declared before `/{type}`. `routers/public.py`, prefix `/r`, no key: `GET /r/{token}` (`ReportRunOut`) and `GET /r/{token}.pdf` (attachment named `{brand-slug}-{type}-{period_to date}.pdf`); the token must match `^[A-Za-z0-9_-]{20,64}$` (else 422), an unknown or revoked token is a 404 with a generic body, both send `Cache-Control: no-store`, and the PDF is rendered after the session closes. `BrandPatch` and `BrandOut` gain the three branding fields (logo URL through the shared https/public-host validator, accent `#rrggbb`, prepared-by up to 80 characters). Schemas `ReportOut`, `CadenceIn`, `ReportRunListOut`, `ReportRunOut` (with `document: Document`).

**Web.** A Reports tab (`b/[id]/reports/page.tsx` and `actions.ts`): Schedules (type, cadence select, last scheduled run), Generate now, Agency branding form, and the Archive (type, period, source, created, View link to `/r/{token}` or "not shared", PDF link, Share/Re-share, Revoke). `format.ts` gains `REPORT_TYPE` and `reportNote`; `types.ts` gains `Report`, `ReportRun`, `ReportRunDetail`, `ReportDocument`; `openapi.json` and `schema.d.ts` regenerated. Public page `app/r/[token]/page.tsx` renders `components/ReportBody.tsx` (title, period, sections, footer, a Download PDF link built from the server-side `API_URL`, the logo only when https, the accent as a CSS variable on headings, print CSS) and sets the tab title to the document's title with `generateMetadata`. `lib/api.ts` gains `publicApi` (no cookie, no key; 404 and 422 go to `notFound()`, anything else not ok throws). `app/r/layout.tsx` gives every `/r` page the neutral title "Report", `app/r/not-found.tsx` keeps the 404 under it, and `app/r/error.tsx` shows neutral copy for a failed load. `vitest.config.ts` sets the automatic JSX runtime so TSX tests compile.

**Commits** (`586f699..HEAD`, before this one):

| Commit | What |
|---|---|
| 3b3ca46 | docs: slice 15 design spec |
| 77e555c | docs: slice 15 implementation plan |
| f1dbe0f | Task 1: tables, due and token functions |
| dd0387d | Task 2: document models and formatters |
| df5dbb5 | Task 3: opening section, CMO and agency builders |
| 20500f5 | Task 4: SEO, content and PR builders; copy ban test |
| 27f0c97 | Task 5: generate on demand and on schedule |
| fd3cc89, 0153544, 5f7e94d | Task 6: PDF renderer; prepared-by line added, then removed because the document already holds it |
| 4c02812 | Task 7: tenant routes, cadence, archive, share links, branding |
| 6f97b6a, d093374 | Task 8: public routes; a dead token's 404 body names nothing |
| 0170fc7 | Task 9: Reports tab |
| 819f461, bdbc4e0 | Task 10: public report page; malformed token is a 404 page and `/r` errors stay white-label |

## 2. Live check

Run by the controller on dev before the finishing menu; filled in below.

| Type | Pages | Bytes | Seconds |
|---|---|---|---|

## 3. Deferred / decisions

From the spec and the build:
- No logo in the PDF (spec §5 and Out of scope): fetching an image inside a request is out. Cost: agency PDFs carry only the accent colour and the prepared-by line; the logo appears on the HTML page only.
- The PDF link (on the public page and in the Archive) is built from the server-side `API_URL`. Cost: it works only where the reader's browser can reach that host; on a deployment where the API is internal the link is dead.
- Periods are rolling 7 or 30 days ending at generation time, not calendar months (spec Out of scope). Cost: a "monthly" report does not line up with a calendar month.
- The public routes are not rate-limited; the tokens are 256-bit (`token_urlsafe(32)`). Cost: nothing stops a client hammering the PDF route, which renders on every request.
- Prompts with no topic are grouped as "untopiced" in the content report. Cost: a label a client may not understand.
- `_topic_rows` recovers each prompt's mention count `k` by rounding `value × n`, since `rate()` stores only the ratio. Cost: none while `n` is small enough for the float to round back exactly; wrong if `rate()` ever stores a rounded value.
- The copy ban (the `FORBIDDEN` words) binds the report's fixed copy only. Stored text quoted verbatim (prompt texts, evidence sentences, page suggestions, brief structure lines built from prompts) is exempt, because editing it would misquote the evidence. Cost: a report can quote an answer containing, for example, "certain".

Minor items deferred from the task reviews, by task:

Task 1
- The stamp-change assertion in `tests/integration/test_reports.py` (lines 52–58) is masked by the archive in the same transaction, and no test shows a monthly report becoming due at 30 days or more. Cost: a wrong monthly interval would pass the tests.
- No DB CHECK rejects an empty `share_token`; the route's token pattern covers the public path. Cost: an empty token could be stored by code other than `generate()`.
- The DB does not enforce `report_run.brand_id == report.brand_id`; `generate()` copies both. Cost: a future writer could store a run under the wrong definition.

Task 2
- The footer sorts pipeline versions as text, so "10" sorts before "2". Cost: an odd order once versions reach two digits.
- The footer and `fmt_day` print UTC without normalising the timezone. Cost: a non-UTC datetime would be labelled UTC wrongly (callers pass UTC today).
- `fmt_delta` can print `-0.00`. Cost: a cosmetic negative zero.
- `fmt_day`, `Branding` and the label maps are tested only through the builders (Tasks 3–5). Cost: a regression there shows up only in builder tests.
- `Document.type` is `str`, not a `Literal`. Cost: the schema does not constrain the type.

Task 3
- The CMO section is headed "Alerts", not the spec's "Alerts in period" (brief-mandated). Cost: a heading that differs from the spec.
- The tasks filter has no `done_at < period.to` bound. Cost: none while `to` is always now; a back-dated run would include later tasks.
- The Tasks status cell prints the raw enum (`impact_measured`) in a client-facing report. Cost: an internal word in front of a client.
- Untested paths: an open task row with owner or impact None, an agency report without prepared-by, the not-comparable branch, the alert window cell, a non-empty SOV table. Cost: those cells are checked by reading only.
- `_open_recommendations(types)`, `_alerts_in(type_)` and `Builder` were unused until Tasks 4–5. Cost: none now (all used).

Task 4
- `_latest_page_audits` filters on score after `DISTINCT ON`, so a URL whose newest fetch failed drops out even with an older scored audit (`recommend.py` filters before); its docstring says "latest scored". Cost: a page can vanish from the citability tables.
- The headings "Content gaps", "Page citability" and "New sources" are shorter than the spec §2 names (brief-mandated). Cost: headings that differ from the spec.
- The Site audit column is "Observed", not the spec's "detail". Cost: a column name that differs from the spec.
- The Sentiment mix share prints without an interval or n (plan-mandated `75.0%`), against the constraint that every rate cell carries its interval. Cost: one table breaks the interval rule.
- Untested: gap-table rows, PR competitor sentiment rows, SEO cited-source rows. Cost: those cells are checked by reading only.
- Owner cells print the raw enum (`third_party`). Cost: an internal word in front of a client.
- The negatives query repeats the `_MENTIONS` fragment inline. Cost: two copies to keep in step.

Task 5
- The failing-brand worker test raises before the flush, so the run-and-stamp rollback in one transaction is not exercised; the test checks stamps only. Cost: a split transaction would pass the tests.
- `days_for` maps any cadence other than "monthly" to 7. Cost: a new cadence would silently be weekly.
- The suite prints two pre-existing starlette/anyio warnings. Cost: output noise.

Task 6
- The PDF footer is cut at 180 characters, not by `stringWidth`. Cost: with many pipeline versions it could overflow or cut mid-word.
- Built-in Helvetica cannot render non-Latin stored text (spec-mandated font). Cost: prompts or evidence in, for example, Hindi print as missing glyphs.
- The `pdf.py` docstring says the prepared-by line carries the branding, though the renderer no longer draws it (the document does). Cost: a misleading docstring.

Task 7
- The `ReportType` Literal duplicates `models.REPORT_TYPES`, and no test ties them. Cost: a new type could be added to one and not the other.
- `LogoUrl` is a copy of the `WebhookUrl` alias. Cost: two definitions to keep in step.
- `list_runs` loads the JSONB document for up to 200 rows and discards it (no `defer()`). Cost: wasted reads on a long archive.
- No tests for the runs `limit` bounds or a run id from another brand of the same org. Cost: those paths are checked by reading only.
- Stored documents are re-validated against `Document` on read, so a future `Document` change could make old runs 500. Cost: the archive breaks unless document changes stay backward-compatible or are versioned.

Task 8
- The idle-in-transaction probe runs after the PDF response, so it cannot see a transaction held during `render_pdf`. Cost: a regression that renders inside the session would pass (fix: probe from inside a monkeypatched `render_pdf`).
- The token lookup and the tenant read are separate transactions; a revoke between them serves one more response. Cost: one response after revoke in a narrow race (fix: re-check `run.share_token == token`); flagged for the final review to triage.
- The public JSON exposes `id`, `brand_id` and `share_token` (the spec mandates `ReportRunOut`). Cost: internal ids reach the reader.
- No rate limiting on the public routes (see above).

Task 9
- The Schedules table puts the select, timestamp and Save in one `colSpan=3` cell under a four-column header. Cost: a misaligned table.
- Timestamps show as a raw ISO slice without a UTC label. Cost: a reader may assume local time.
- The PDF link uses the server-side `API_URL` (see above).
- Share and Revoke are stacked forms in one cell. Cost: layout only.

Task 10
- The report's `--accent` CSS variable collides with the app's global `--accent` (`globals.css`, `#1d4ed8`, used for links): unbranded headings take the app blue, and a brand accent also colours the PDF link. Cost: unbranded reports show app blue headings (fix: rename to `--report-accent`).
- React keys use heading and column text, which can repeat. Cost: a React key warning and possible mis-rendering on duplicate headings or columns.
- Only `h2` takes the accent, not `h1`. Cost: the title stays in the default colour.

## 4. Not covered by tests
- The Next.js public page route itself (`app/r/[token]/page.tsx`); only `ReportBody` (rendering a fixture document) and `publicApi` (404 and 422 to not-found, 5xx throws, no auth sent) are unit-tested. The route is exercised in the live check (§2).
- The tab title on `/r` error paths (not-found and error pages under the "Report" layout title); no test renders them.
- Whether Next dedupes the `generateMetadata` fetch and the page fetch into one GET. The page's comment says it does; nothing measures it, and both use `cache: "no-store"`.
- `app/r/layout.tsx`, `not-found.tsx` and `error.tsx` have no tests.
- The ledger's other untested paths, listed with their tasks in §3: a monthly report becoming due at 30 days (Task 1); `fmt_day`, `Branding` and the labels directly (Task 2); the Task 3 and Task 4 cells named there; the run-and-stamp rollback (Task 5); the runs `limit` bounds and a same-org run id from another brand (Task 7); a transaction held during `render_pdf` (Task 8).
