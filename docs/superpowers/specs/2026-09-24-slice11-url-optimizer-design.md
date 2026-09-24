# Slice 11 design: URL optimizer and AI Citability Score (PRD F11, second half)

## Context

Slice 10 finds content-gap clusters and writes a model-free brief per gap.
The operator's next question is "here is my page — why isn't it cited?".
PRD F11 asks for a URL optimizer (fetch a page; score topic coverage,
intent fit, entity coverage, evidence, author attribution, structure,
FAQs, tables, direct answers; output add / remove / rewrite /
evidence-to-add lists) and an AI Citability Score (0–100, components
visible, weights versioned). Acceptance: ≤ 60 s p95 per URL; every
suggestion cites the observation or competitor page that motivates it.

Decisions made in brainstorming (all approved in chat):

- **Input** = URL + gap cluster, submitted from the Clusters tab.
- **Shape** = job kind `optimize_url` + stored `page_audit` row (the
  `audit_crawl` / `site_audit` pattern). Not a synchronous route.
- **Spend** = embeddings only (`gemini-embedding-001`, ≈ $0.002/page).
  No judge call. Everything else is parsed from the HTML.
- **Recs** = new type `optimize_page` (migration 0014), impact measured.
- **Live check** = read-only script; dev's `recommendation`, `task`,
  `page_audit` tables stay empty.
- Job uniqueness: `job` is unique on `(brand_id, kind, scheduled_slot)`
  and `enqueue_job` defaults the slot to the UTC hour. The optimize route
  passes `slot=now()` so each request is its own job. No migration.

Run 1 today: 20 labelled prompts, 15 clusters, 14 gaps, no `domain` rows.
Spend $9.2784 of $15. Session model: planning on Fable 5.1; implementers
and reviewers on Opus 5.5 only (ask the user to `/model claude-opus-5-5`
before dispatching).

## Design

### A. Parsing and scoring — `packages/core/bsi_core/pages.py` (new)

**`Page(HTMLParser)`** (own class; `crawl.Head` stays minimal). Collects:
title, meta description, meta author, JSON-LD scripts, headings h1–h3 in
document order with text, the text blocks (p, li) following each heading
(cap 2,000 chars per section, 60 sections), `<table>` count with ≥ 2
rows, ol/ul with ≥ 3 items, `<a href rel>` links, author hints
(`rel="author"`, class/id containing `author` or `byline`), word count.
Skips script, style, nav, header, footer, aside.

**`score(page, cluster, brand, rivals, hosts, query_vectors, section_vectors) -> Result`**
— pure; the embedder is called by the runner, not here. Constants:
`WEIGHTS_VERSION = "v1"`, `WEIGHTS` (sum 100), `PAGE_SCORE_THRESHOLD = 70`
(lives in `recommend.py`), cosine constants marked `# ponytail:` for
recalibration after real pages.

| Component | Weight | Rule |
|---|---|---|
| `topic_coverage` | 25 | per target query `max cos(query, section)`; mean over queries mapped by `clamp((cos − 0.55) / 0.30, 0, 1)`; a query with best cos < 0.70 is "uncovered". Query vectors = the cluster prompts' stored `prompt.embedding` (read as text via SQL, parsed). |
| `intent_fit` | 10 | fraction of signals for `gaps.PAGE_TYPES[intent]`: comparison page → table + ≥ 2 rivals named; best-of round-up → list ≥ 3 + ≥ 3 H2; guide → ≥ 3 H2 + ≥ 300 words; product/category page → `Product`/`Offer`/`ItemList` schema; how-to → `HowTo` schema or ordered list; alternatives/solution/local page → list + ≥ 2 H2. |
| `entity_coverage` | 10 | brand (whole-word, `entity._names_in`) in title or H1 0.5, in body 0.25; comparison/alternative intents: fraction of cluster rivals named 0.25; other intents: brand in meta description 0.25. |
| `evidence` | 15 | `0.6·min(1, links to cluster cited domains / 3) + 0.4·min(1, other third-party outbound / 5)`; owned and rival domains excluded (`competitors.owner_of`). |
| `author_attribution` | 5 | meta author, `Article`/`Person` author in JSON-LD, `rel="author"`, or byline element. |
| `structure` | 10 | exactly one H1 0.3; ≥ 3 H2 0.3; no level skipped 0.2; ≥ 300 words 0.2. |
| `faqs` | 10 | `FAQPage` schema 1.0; else ≥ 3 headings ending in `?` or a heading containing "faq"/"questions" 0.6. |
| `tables` | 5 | ≥ 1 table with ≥ 2 rows. |
| `direct_answers` | 10 | fraction of H2 sections whose first sentence ≤ 40 words and doesn't open with "in this article/post/guide". |

Score = `round(Σ weight × value)`. Component row:
`{code, weight, value, points, observed, evidence: [str]}`.

**Suggestions** `{add, remove, rewrite, evidence_to_add}`, each item
`{text, urls, prompt_ids, observation_ids}`, from fixed templates for
components below full marks. Uncovered queries carry their prompt ids and
the cluster's absent observation ids; `evidence_to_add` lists the
cluster's top 10 cited third-party/rival URLs with their observation ids;
`remove` is mechanical only (extra H1s, second FAQPage block, "in this
article" opener). Copy obeys the banned-word rule. Module note: the score
is a diagnostic, not a promised outcome. Test: every suggestion cites at
least one id or URL.

### B. Storage and job

**Migration `0014_page_audit_and_optimize_page`** (`down_revision="0013"`,
copy `_protect()` from 0012). Table `page_audit`: `id, created_at,
org_id, brand_id, job_id (nullable), url, cluster_key, final_url
(nullable), status int, error (nullable), weights_version, score int
(nullable), components JSONB '[]', suggestions JSONB '{}', evidence JSONB
'{}', fetches int 0`. Index `ix_page_audit_latest (brand_id, cluster_key,
url, created_at)`. `_protect("page_audit")`. Widen `ck_recommendation_type`
to add `optimize_page` (0012/0013 `_rec_type_check` pattern); downgrade
deletes those recs/tasks first. ORM `PageAudit(Tenant, Base)` in
`models.py`; `REC_TYPES` gains `optimize_page`. Add to `TENANT_TABLES` and
`org_b` in `tests/integration/test_rls.py`.

**Job kind `optimize_url`**, params `{url, cluster_key}`.
`JOB_ESTIMATES["optimize_url"] = PAGE_JOB_MICROS = 2_000` (budget-gated).
Runner `run_page_audit(org_id, brand_id, job_id, embedder, fetch)` in
`apps/workers/bsi_workers/worker.py` next to `run_crawl_audit`, added to
`runners`:

1. Session 1 (read, closed): brand name/aliases/hosts; `gaps.clusters(s,
   brand_id, Filters())` → cluster by key (missing → job fails "unknown
   cluster", no row); prompt vectors `SELECT id, embedding::text FROM
   prompt WHERE id = ANY(:ids)`; top 10 cited third-party/rival URLs by
   answers for the cluster's prompts (one grouped query on citation ⋈
   observation, status='done').
2. No transaction open: one `fetch(url, BROWSER_UA)` via `http_fetch`; one
   `embedder(sections)` (cost via `_Meter`).
3. Session 2 (write): one `page_audit` row; `refresh(s, org_id, brand_id)`.

Fetch failure / non-2xx / non-HTML → row with `error`, `score` null, job
`done`. Scoring crash → job `failed`. No `pause`.

URL rules (API and runner): http/https, hostname, no userinfo; scheme
lower-cased, fragment dropped. Not restricted to declared domains (SSRF
guard is the safety boundary; one fetch per job + budget gate).

### C. Recommendation rule — `recommend.py`

`_pages(s, brand_id, brand, total)`, called in `generate()` after
`_content_clusters` (inside `if total:`). One statement:
`SELECT DISTINCT ON (cluster_key, url) … FROM page_audit WHERE brand_id =
:brand AND score IS NOT NULL ORDER BY cluster_key, url, created_at DESC,
id DESC`. Per row with `score < PAGE_SCORE_THRESHOLD (70)`:
`Candidate("optimize_page", f"page:{cluster_key}:{url}", title, body,
evidence, reach, pressure)` with `reach = len(evidence.observation_ids) /
total`, `pressure = (100 − score) / 100`, `FEASIBILITY["optimize_page"] =
0.6`. Evidence = the audit row's `{prompt_ids, observation_ids}` plus
`page_audit_id, score, url`. Not in `NO_IMPACT`.
`page_copy(brand, url, topic, score, suggestions)`: title "Improve
{host}{path} for {topic}"; body: score + version, up to three suggestions
(add, rewrite, evidence_to_add order), "Metric to watch: brand mention
rate on the cluster's {n} prompts." Lifecycle via `refresh()` unchanged.

### D. API and web

Router `apps/api/bsi_api/routers/pages.py`, prefix `/brands/{brand_id}/pages`,
registered in `main.py`:

- `POST /optimize {url, cluster_key}` → 202 `QueuedOut`. `PageOptimizeIn`
  validates URL (422); `cluster_key` must be in `clusters(c.s, brand_id,
  Filters())` (422 "unknown cluster"); `enqueue_job(..., "optimize_url",
  params, slot=now())` via a `queue_suggestion` variant taking `slot`
  (409 archived brand).
- `GET /` `?cluster_key=` → `list[PageAuditOut]`, latest per
  `(cluster_key, url)` (DISTINCT ON), `created_at DESC`; failed rows
  included.
- `GET /{page_audit_id}` → `PageAuditOut` via `child_or_404`.

Schemas: `PageAuditOut` (all columns), `ComponentOut`, `SuggestionsOut`,
`SuggestionOut`. Components in weight order, suggestions in generation
order; the frontend sorts nothing. All three routes in `CASES`
(`test_isolation.py`) with owner-2xx tests. `npm run gen` and stage
`apps/web/openapi.json`, `src/lib/schema.d.ts`.

Web: Clusters tab — inside each gap's `<details>`, a form (`url` input,
hidden `brand_id`, `cluster_key`, "Score a URL") → `optimizeUrl` server
action in `clusters/actions.ts` → redirect `/b/{id}/pages?queued=`. New
Pages tab `app/(app)/b/[id]/pages/page.tsx` (+ `<Link>` in `layout.tsx`
after Site): `GET /pages`; empty state; one card per audit with URL (link
only when http(s), `rel="noreferrer"`), cluster, date, score "62 / 100
(weights v1)", components table, four suggestion lists with evidence
links (`/o/{id}`, `isWeb`-guarded URLs), or the error. `PAGE_NOTES` +
`pageNote` in `format.ts` with a vitest case. No Server-Component rule
broken; API key stays in `lib/api.ts`.

### E. Testing

- `tests/unit/test_pages.py`: parser fixtures; deterministic 768-dim
  bag-of-words hash embedder for cosine cases; per-component 0→1 and
  boundary cases with points computed from `WEIGHTS`; weights sum 100;
  every suggestion cites an id or URL; copy passes banned words.
  `test_recommend_copy.py` picks up `page_copy`.
- `tests/integration/test_page_audit.py`: success row and score; unknown
  cluster → failed, no row; fetch error → error row, job done; non-HTML →
  error row; budget gate; no-transaction-open during fetch and embed;
  cited-URL query top 10 third-party/rival only.
- `test_recommend.py`: 62 → candidate (reach/pressure from fixture); 70 →
  none; re-scored higher → open rec deleted; decided not raised; failed
  audit → none; `_pages` = 1 statement.
- `test_rls.py`, `test_isolation.py`, `test_api_pages.py` (422s, 202 with
  distinct jobs in the same hour, GET latest per pair, GET one, 404).
- Web: `format.test.ts` case; `npm run gate`.

### Live check (≈ $0.002, read-only)

`scripts/score_page.py <brand_id> <cluster_key> <url>`: sources `.env`,
reads cluster + prompt vectors + cited URLs from dev, fetches, embeds,
prints score/components/suggestions, writes nothing. Run once on one real
page for a Run 1 gap (e.g. `cluster:recommendation:school shoes`); record
in `docs/findings-slice11.md`; add to `docs/README.md`.

### Files touched

New: `packages/core/bsi_core/pages.py`, `migrations/versions/0014_page_audit_and_optimize_page.py`,
`apps/api/bsi_api/routers/pages.py`, `apps/web/src/app/(app)/b/[id]/pages/page.tsx`,
`scripts/score_page.py`, `tests/unit/test_pages.py`,
`tests/integration/test_page_audit.py`, `tests/integration/test_api_pages.py`,
`docs/findings-slice11.md`, spec + plan under `docs/superpowers/`.
Changed: `models.py`, `recommend.py`, `worker.py`, `schemas.py`, `main.py`,
`routers/runs.py` (slot), `clusters/page.tsx`, `clusters/actions.ts`,
`layout.tsx`, `lib/format.ts` (+test), `lib/types.ts`, generated types,
`test_rls.py`, `test_isolation.py`, `test_recommend.py`, `docs/README.md`.

### Out of scope, by decision

Fetching competitor pages; auto-scoring `brand_urls`; judge call;
per-engine scores; scheduled re-scoring; domain restriction on URLs.

### Risks

Cosine thresholds are guesses until a real page is scored (marked).
JS-rendered pages score near 0 with error text "no headings found".
Threshold 70 is arbitrary; changing it needs no migration.

