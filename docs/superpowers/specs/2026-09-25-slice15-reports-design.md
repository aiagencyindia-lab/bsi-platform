# Slice 15 design: reports (PRD F15, reports only)

## Context

PRD F15 covers alerts, reports and agency mode. Slice 13 built alerts. This slice builds reports: five report types, generated on a weekly or monthly schedule or on demand, kept as an archive, viewable through a public share link, and downloadable as a PDF. Every report prints its methodology version, the sample size and the 95% interval of every rate. Agency mode (workspaces, client Viewers, users) does not exist yet; the agency client report is a client-facing variant of the CMO summary with per-brand branding fields.

Decisions approved in chat:

- **All five PRD types**: `cmo`, `seo`, `content`, `pr`, `agency`. PR has real data because every mention stores a sentiment. Agency is the CMO builder in client-facing mode.
- **Fixed copy only.** Every sentence is a template filled from computed numbers. No model call, no spend.
- **Per (brand, type) cadence**: off / weekly / monthly. Weekly covers the last 7 days against the prior 7; monthly the last 30 against the prior 30; both end at generation time. Manual runs use the weekly window. Runs are an archive.
- **Share link**: one random token per run, no expiry, revocable and re-shareable. Public page and PDF need no login.
- **PDF by reportlab, on demand**, from the stored document; nothing is written to disk.
- **Frozen snapshot**: the run stores the whole document as JSONB. Renderers only render.

Codebase facts the design rests on:

- Every dashboard number is computed live: `metrics.brand_metrics`, `brand_deltas(s, brand_id, f, days, to)`, `brand_sov`, `prompt_metrics`; `competitors.entity_metrics`; `citations.sources`; `gaps.clusters` and `brief`; `recommend.top_by_type`; `Task.impact_label`/`impact`; `Alert` rows. All take `Filters(date_from, date_to)` built through `metrics._where`, half-open on `observation.requested_at`.
- `rate()` returns `{value, n, ci_low, ci_high}` (95% Wilson); `delta()` returns `{value, ci_low, ci_high, label}` (95% Newcombe method 10) with labels increase / decrease / no significant change / insufficient data. `brand_deltas` carries `comparable` and `reason`.
- The only version constant is `extraction.PIPELINE_VERSION = "2"`; `brand_metrics` returns `pipeline_versions` seen in the window. There is no methodology version.
- `SiteAudit.checks` (JSONB list) holds the crawl and entity checks; `PageAudit` has `url, cluster_key, score, components, suggestions`; `Mention` has `entity_type, sentiment, evidence_sentence, position, rec_status`.
- Scheduling pattern: a SECURITY DEFINER `due_*()` function read from `system_session()`, per-brand work in `tenant_session(org_id)`, the stamp set with `func.now()` in the same transaction (`scan_due_alerts`, `alerts_scanned_at`). The manual API call never stamps.
- Auth: every route has `c: Ctx = TENANT` except `GET /healthz`. The web app sends the `bsi_key` cookie's key as a Bearer header from `lib/api.ts` only.
- No templating or PDF library is installed. `crawl.http_fetch` is the only outbound HTTP path; no transaction may be open during it.

Planning ran on Fable 5.1 with the user's approval. Implementers and reviewers run on Opus 5.5 only.

## Design

### 1. Data

Migration `0017_reports.py`, with `_protect()` copied in as every tenant migration does:

- Table `report` (the definition): `id`, `created_at`, `org_id`, `brand_id` (FK brand), `type` (CHECK over `cmo, seo, content, pr, agency`), `cadence` (CHECK over `off, weekly, monthly`, default `off`), `generated_at` timestamptz nullable. Unique `(brand_id, type)`. Rows are created lazily by the cadence PUT; the list route synthesises `cadence="off"` for types without a row.
- Table `report_run`: `id`, `created_at`, `org_id`, `brand_id` (FK brand), `report_id` (FK report), `type` (same CHECK), `source` (CHECK over `scheduled, manual`), `period_from`, `period_to`, `compare_from` (timestamptz, not null; the prior period is `[compare_from, period_from)`), `document` jsonb not null, `methodology_version` text not null, `share_token` text nullable. Unique partial index on `share_token` where not null; index `(brand_id, created_at)` for the archive.
- `brand.report_logo_url`, `brand.report_accent`, `brand.report_prepared_by` (text, nullable).
- `due_report_runs()` returns `(report_id, brand_id, org_id, type, cadence)` for active brands where `cadence <> 'off'` and `generated_at IS NULL OR generated_at <= now() - make_interval(days => 7)` for weekly, `30` for monthly; `ORDER BY generated_at NULLS FIRST, id`.
- `report_run_by_token(token text)` returns `(run_id, org_id)` for the run with that `share_token`. It is the only cross-tenant read; the API then loads the row in `tenant_session(org_id)` so RLS stays in force.
- Both functions: SECURITY DEFINER, `SET search_path = public`, REVOKE from PUBLIC, GRANT EXECUTE to `bsi_app`, as `due_alert_scans()`.
- ORM: `Report`, `ReportRun`, `REPORT_TYPES`, `REPORT_CADENCES`, `RUN_SOURCES` in `models.py`; three `Brand` columns. Both tables go in `TENANT_TABLES` and the `org_b` fixture.

Versions: `reports.METHODOLOGY_VERSION = "1"`. Every run stores it. The rule: bump it whenever a builder changes what it computes or how a cell is formatted.

### 2. Document (`bsi_core/reports.py`)

Pydantic models, also used as the API schema for `ReportRunOut.document`:

- `Document(title, brand, type, period: Period, branding: Branding | None, sections: list[Section], footer: str)`; `Period(from_, to, compare_from)` with `from` as the alias; `Branding(logo_url, accent, prepared_by)`, set only for `agency`, copied from the brand row at build time so the public route never reads the brand.
- `Section(heading, blocks: list[Block])`; `Block` is `Paragraph(kind="p", text)` or `Table(kind="table", columns: list[str], rows: list[list[str]])`.
- Cells are pre-formatted strings. `fmt_rate(r)` gives `0.42 [0.33, 0.52] n=100`, or `— (n=0)` when `n == 0`; `fmt_delta(d)` gives `-0.09 [-0.18, +0.01] no significant change` (ASCII signs, not the Unicode minus); `fmt_pct` for SOV share. Rounding to two decimals happens in the formatter only.
- No links or ids in the document: readers are outside the app, and citation URLs are Vertex redirects. Domains, prompt texts and evidence sentences appear as text.
- The footer string: `Methodology v1 · pipeline v{versions} · rates: 95% Wilson interval · deltas: 95% Newcombe interval · generated {ts} UTC`. For `agency`, the same line; the product name appears nowhere in any document.

Builders, one per type, `build_<type>(s, brand, days, to, *, client_facing=False) -> Document`. Every builder starts with the common opening, then its sections:

- **Common opening.** A "Period" paragraph (`{from} to {to}, compared with {compare_from} to {from}`), then a *Visibility* table from `brand_deltas(s, brand_id, Filters(), days, to)`: one row per `DELTA_METRICS` metric: metric, this period (`fmt_rate`), prior period, delta (`fmt_delta`). When `comparable` is false the delta column reads `not comparable: {reason}` in every row.
- **cmo**: *Share of voice* (`brand_sov`, top 10 by share: entity, share with CI, mentions) · *Competitors* (`entity_metrics`, top 10: name, mention rate, SOV, sentiment index) · *Top cited sources* (`sources`, top 10: domain, owner, answers, prompts) · *Recommendations* (`top_by_type` over open recommendations: type label, title, priority to two decimals) · *Tasks* (open tasks and tasks done in the period: title, owner, status, impact label, impact delta; `client_facing` drops owner) · *Alerts in period* (type label, title, window).
- **seo**: *Cited sources* (`sources`, top 20: domain, owner, answers, prompts, gap yes/no) · *Site audit* (failing checks from the latest `SiteAudit` per domain: domain, check, severity, detail) · *Page citability* (latest `PageAudit` per url with a score: url, cluster, score) · *Content gaps* (`gaps.clusters`, top 10: cluster, prompts, brand mention rate, top rival and its rate) · *Recommendations* (open recommendations of the site and page types).
- **content**: *Prompt performance by topic* (`prompt_metrics` grouped by `Prompt.topic`, "untopiced" for null: topic, prompts, pooled mention rate, most frequent top competitor) · *Content gaps with briefs* (`gaps.clusters` + `brief`: cluster, page type, structure, prompts) · *Page citability with next step* (latest `PageAudit` per url: url, score, first suggestion) · *Recommendations* (open recommendations of the content types).
- **pr**: *Sentiment mix* (one SQL count over `mention` for `entity_type = 'brand'` joined through `_where`: sentiment, mentions, share of mentions) · *Negative mentions* (up to 20: date, prompt text, evidence sentence) · *Competitor sentiment* (`entity_metrics`: name, positive, negative, index) · *Third-party sources naming the brand* (`sources` where `brand_named` and owner is `third_party`, top 20) · *New sources in period* (`new_source` alerts: domain, title, window).
- **agency**: `build_cmo(..., client_facing=True)`. Title is `{brand} visibility report` with a `Prepared by {report_prepared_by}` paragraph when set; the Tasks table drops owner and notes; the footer has no product name (true of every type).

Every section with nothing to show renders one paragraph (`No cited sources in this period.`) instead of an empty table. This includes the competitor tables (CMO *Competitors* and PR *Competitor sentiment*): `entity_metrics` returns a row per entity even at n=0, so when the window has no answers those rows are dropped and the section is the paragraph. Recommendation type groups per report reuse the existing type constants in `recommend.py`; the plan names the exact sets.

### 3. Generation and scheduling

`reports.generate(s, org_id, brand_id, type, *, days, to, source) -> m.ReportRun`: computes `period_to = to`, `period_from = to − days`, `compare_from = to − 2·days`, loads the brand, calls the builder, inserts the run with `share_token = secrets.token_urlsafe(32)` and `methodology_version`. It runs inside the caller's `tenant_session`; every read is SQL; no HTTP, no model call, no spend. `days` is 7 for weekly and manual, 30 for monthly.

Worker: `generate_due_reports()` in `worker.py`, the shape of `scan_due_alerts`: rows from `due_report_runs()` in `system_session()`, then per row a `tenant_session(org_id)` calling `generate(source="scheduled")` and setting `report.generated_at = func.now()` in the same transaction; per-row `try/log.exception`. Added to `main()` after `deliver_due_alerts`.

Rejected: queueing runs as jobs. `enqueue_job`/`process_job` exist for budget reservation and model spend, which reports have none of, and would delay a manual run by up to a minute.

### 4. API

`routers/reports.py`, prefix `/brands/{brand_id}/reports`, every route `c: Ctx = TENANT`, registered in `main.py`. `type` is a `Literal[...]` path parameter, so an unknown type is 422.

| Route | Behaviour |
|---|---|
| `GET /` | Five `ReportOut` (type, cadence, generated_at), `off` synthesised for missing rows |
| `PUT /{type}` body `{cadence}` | Upsert. When cadence changes from `off` to anything, `generated_at` is set NULL so the first scheduled run is due at once |
| `POST /{type}/runs` | Manual run, 201 `ReportRunOut` with document; does not stamp `generated_at` |
| `GET /runs?limit=` | Archive newest first, `ReportRunListOut` (no document); limit 1–200, default 50 |
| `GET /runs/{run_id}` | `ReportRunOut` with document |
| `POST /runs/{run_id}/share` | New token; returns the run |
| `DELETE /runs/{run_id}/share` | Token NULL; 204 |

`routers/public.py`, prefix `/r`, no `TENANT`:

- `GET /r/{token}` → `ReportRunOut`; `GET /r/{token}.pdf` → `application/pdf` with `Content-Disposition: attachment; filename="{brand-slug}-{type}-{period_to date}.pdf"`. Both: the token must match `^[A-Za-z0-9_-]{20,64}$`, so a malformed token is 422; `report_run_by_token(:token)` from `system_session()`, 404 on no row, then the run from `tenant_session(org_id)`; `Cache-Control: no-store`. The token is only ever a bound parameter. The PDF is rendered after the session closes.

`BrandPatch` gains `report_logo_url` (https only, the `_webhook_url` validator's style), `report_accent` (`^#[0-9a-fA-F]{6}$`), `report_prepared_by` (≤ 80 chars); `BrandOut` returns them. `ReportRunOut` and `ReportRunListOut` expose `share_token` so the web app can build the link.

### 5. Rendering

HTML: Next.js route `apps/web/src/app/r/[token]/page.tsx`, outside `(app)`, no cookie. `lib/api.ts` gains `publicApi<T>(path)` (server-only, no Authorization header, 404 or 422 → `notFound()`, any other failure throws); the key stays where it is. A malformed or unknown token therefore shows the not-found page, and a 5xx shows a neutral error page (`app/r/error.tsx`); both sit under `app/r/layout.tsx`, whose title is "Report", so no `/r` page shows the product name. The page itself sets the tab title to the document's title. The page renders title, period, sections (`<h2>`, `<p>`, `<table>`), footer, a "Download PDF" link to the API's `/r/{token}.pdf` built from the API base URL on the server, and print CSS. For `agency` runs the brand's logo `<img>` shows only when `report_logo_url` is https, and `report_accent` sets a CSS variable for headings. The page reads branding from the document (the builder copies `logo_url` and `accent` into `Document.branding`), so the public route never exposes the brand row.

PDF: `bsi_core/pdf.py`, `render_pdf(document) -> bytes` with reportlab platypus: `SimpleDocTemplate` A4, built-in Helvetica, a page-footer callback printing the methodology line and `page n`, headings coloured with `document.branding.accent` when set (a value that is not `#rrggbb` falls back to black), tables with a repeating header row, a grid, and `Paragraph` cells so long text wraps, `KeepTogether` on a heading and its first block. No logo in the PDF (fetching an image inside a request is out; deliberate simplification). `reportlab` is added to `packages/core` as a direct dependency; mypy gets `ignore_missing_imports` for `reportlab.*`.

### 6. Web (tenant side)

Reports tab in `layout.tsx`; page `b/[id]/reports/page.tsx` with three parts and server actions in `actions.ts`:

- Schedules: five rows, type label, `<select>` off / weekly / monthly, last scheduled run; `setCadence` → PUT.
- Generate now: type `<select>` and a button; `generateNow` → POST; redirect with `?queued=generated`; `reportNote()` on `note()`.
- Archive: type, period, source, created; per row View (link to `/r/{token}`, or "not shared"), PDF, Re-share, Revoke (`share`, `revoke` actions).
- Branding form (logo URL, accent, prepared by) → `setBranding` PATCH, in the webhook form's style.
- `format.ts`: `REPORT_TYPE` labels, `reportNote`. `types.ts`: `Report`, `ReportRun`. `npm run gen` after the API lands; `openapi.json` and `schema.d.ts` committed.

### 7. Testing

- Unit `tests/unit/test_reports.py`: document models; `fmt_rate`, `fmt_delta`, `fmt_pct` including `n=0` and the rounding boundary; `render_pdf` returns bytes starting `%PDF-`, one page for a small document and more than one for a 300-row table, and a synthetic 20-page document renders under 30 s; the HTML-side check is a vitest test rendering a fixture document and asserting every heading and cell string appears.
- Copy ban: `tests/integration/test_reports.py` has a `test_copy` that imports the banned-word list from `tests/unit/test_recommend_copy.py` and scans every string of every builder's output on the seeded brand. It is an integration test because builders need a session.
- Integration `tests/integration/test_reports.py`: a seeded brand with answers in both periods; each builder produces the expected section headings; the Visibility cells equal `fmt_rate`/`fmt_delta` of `brand_deltas` for the same window; the Competitors and Sources cells agree with `entity_metrics` and `sources`; the document is unchanged after a new answer is inserted; `generate` sets a token and the version; `due_report_runs()` returns a row only when cadence is on and the stamp is NULL or old, and honours 7 vs 30 days; `generate_due_reports` stamps `generated_at`, and a failing brand does not stop the others.
- Integration `tests/integration/test_api_reports.py`: every route; PUT off→weekly nulls the stamp; manual run leaves it; archive order and limit; share and revoke; public GET 200 → revoke 404 → re-share new token 200 and old token 404; `.pdf` content type and disposition; unknown type 422; the `pg_stat_activity` probe during the PDF route; `test_rls` and `test_isolation` rows for both tables and every id-taking route.
- vitest: `reportNote`, `REPORT_TYPE` covers every type in the generated schema.

### 8. Live check

Before the finishing menu, on dev with the API running: generate all five types for Run 1 through the API, open `/r/{token}` and the PDF, record page counts, byte sizes and timings in `docs/findings-slice15.md`, and state what was observed. This writes `report_run` rows on dev and nothing else. The worker is not started.

## Rulings

Made during execution, in the order recorded in the ledger. Each gives the decision, the reason, and the cost if it is wrong.

1. The Task 3 test `test_empty_brand_gets_a_complete_report` asserts that the Visibility Change cell reads "insufficient data" instead of starting with "not comparable: ". A brand with no answers has no pipeline versions, so `brand_deltas` calls it comparable, and this spec says the column reads "not comparable" only when `brand_deltas` does. Cost if wrong: one assertion.
2. The Task 5 tests live in `tests/integration/test_reports.py`; `tests/integration/test_worker.py` is re-run for regressions but not edited. The plan's code already put them there, and one file per feature matches `test_alerts.py`. Cost if wrong: test location only.
3. The Task 6 implementer could run `uv sync` (package index only) after adding reportlab to `packages/core/pyproject.toml`, with no other network use. The dependency was approved in this spec and could not be installed otherwise. Cost if wrong: none beyond the approved dependency.
4. The Task 10 implementer could create `apps/web/vitest.config.ts` with only what the TSX test needs to compile (the automatic JSX runtime). The plan anticipated this. Cost if wrong: a small config file.
5. From planning: signs in delta cells are ASCII (`-0.09`, `+0.01`), not the Unicode minus in this spec's first example; a malformed share token (not `[A-Za-z0-9_-]{20,64}`) is a 422 at the API and an unknown one a 404. Cost if wrong: a formatting change and one status code.
6. The CMO builder drops competitor rows when the window has no answers, so the Competitors section becomes the empty-section paragraph. §2 says every section with nothing to show renders one paragraph, and `entity_metrics` returns a row per entity even at n=0. Cost if wrong: a new brand's Competitors section shows a paragraph instead of a table of dashes.
7. The Task 3 fixture's done task has `window_days=14`, because the DB CHECK `ck_task_done_has_window` requires it. Cost if wrong: none (fixture only).
8. The copy ban (the `FORBIDDEN` words) binds the report's fixed copy only. Stored text quoted verbatim (prompt texts, evidence sentences, page suggestions, brief structure lines built from prompts) is exempt: §2 says prompt texts and evidence sentences appear as text, and editing them would misquote the evidence. Cost if wrong: a report can quote an answer containing, for example, "certain"; the findings state the ban's scope.
9. The PR builder applies the same n=0 guard to its competitor-sentiment table, with an extra test, by the same rule as ruling 6. Cost if wrong: none.
10. The PDF falls back to black for an accent that is not `#rrggbb`, with a test: a document built from a brand row must render even if the row holds a bad value. Cost if wrong: none.
11. The shared URL validator's message became field-neutral ("must be an https URL on a public host") because it now serves both `webhook_url` and `report_logo_url`. Cost if wrong: message text only.
12. The plan's Task 8 assertion that "Secret" is absent from an unknown token's response was vacuous: nothing in that test's data contains "Secret" (it is the isolation fixture's title). It was replaced by assertions that the 404 body is generic and does not name the brand, for both a revoked real run and an unknown token. A test that asserts nothing is a defect whatever the plan says. Cost if wrong: none.
13. Generate now redirects with `?queued=generated` (as the plan, brief and test have it), not `?queued=report`; §6 was corrected. The five notes (cadence, generated, shared, revoked, branding) each name what happened, and "report" would be ambiguous. Cost if wrong: one query value.
14. The `REPORT_TYPE` vitest test compares against a literal object, not the generated schema: `ReportOut.type` is a plain string in the OpenAPI schema, so there is no union to check against; the literal equals `models.REPORT_TYPES`. Cost if wrong: a new type could ship without a label (it falls back to the raw type).
15. Two files not in the plan were accepted: `app/r/layout.tsx` (neutral title "Report") and `app/r/not-found.tsx`. The root layout titles every page "BSI operator", which would put the product name on a client-facing page. Cost if wrong: two small files.
16. `app/r/error.tsx` (neutral copy under the `/r` "Report" title), added in the Task 10 fix round, was accepted: it keeps 5xx pages white-label. Cost if wrong: one small file.

## Out of scope

Email delivery and recipients, per-user preferences, digest mode, white-label custom sender and domain, workspaces and client Viewers, a model-written narrative, calendar-month periods, logos in the PDF, PDFs in object storage, usage metering, report builder (custom sections).
