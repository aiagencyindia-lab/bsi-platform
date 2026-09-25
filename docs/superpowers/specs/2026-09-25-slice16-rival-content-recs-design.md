# Slice 16 design: recommendations from competitor site changes

## Context

Slice 12 added the weekly competitor site crawl and a change feed of new pages; findings-slice12 §3 deferred "recommendations from site changes; topic matching of rival pages to clusters". Slice 14 made the crawl read sitemaps in full, so a competitor's new pages are now seen reliably. This slice closes that gap: when a competitor publishes new pages on a topic where the brand is behind, the operator gets a recommendation to respond, citing the pages.

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-25; classification: architectural):

- **Purpose:** respond to a content move. One new recommendation type. The other reading (recommend new prompts for topics the brand has none for) is out of scope.
- **Matching:** URL path words against the cluster's topic words. No fetch, no model spend. Rejected: capturing title/H1 at crawl time (migration plus crawler change, only the ≤10 sampled pages eligible) and embeddings (spend per crawl, thresholds calibrated on one cluster).
- **Trigger:** at least one new, non-baseline rival page in the last 14 days matches a cluster where the brand is behind: the cluster is a content gap, or its `spread` (brand rate minus top rival's rate) is negative. A cluster with an existing `create_content` recommendation can also get this one; they are different actions.

Codebase facts the design rests on:

- `rival_page` (migration 0015) stores `brand_id, competitor_id, domain, url, first_seen_at, last_seen_at, baseline, types` with a unique `(competitor_id, url)`. No title, heading or text. The worker upserts one row per sitemap URL; `types` is set only for the ≤10 sampled pages. Dev's 17 crawls are all baselines, so no non-baseline row exists there yet.
- `rivals.site_changes` defines "new" as `NOT baseline AND first_seen_at` within `days` (default 14) for active competitors, capped at `NEW_PAGES_CAP = 20` per competitor in the feed.
- `matching.tokenize` strips URL-shaped text before tokenising, so it cannot tokenise a URL; the slug splitter is new.
- `Prompt.topic` is one to three lowercase words chosen by the label job (`suggest.py`, `MAX_TOPIC_CHARS = 60`); `Prompt.intent` is one of `INTENTS`. Only labelled prompts form clusters.
- `gaps.clusters(s, brand_id, f)` returns per cluster: `intent, topic, key, prompts[{prompt_id, text, n, absent}], n, brand (rate), absent, rival_absent, reasons, reason, rivals, top_rival, spread, cited, sources, brand_urls, gap, absent_obs, brief`. `spread = brand.value − top_rival.value` when a top rival exists.
- `recommend.generate(s, brand_id)` concatenates rule functions returning `Candidate(type, subject_key, title, body, evidence, reach, pressure)`; `priority = reach × pressure × FEASIBILITY[type]`. `refresh(s, org_id, brand_id)` upserts on `(brand_id, type, subject_key)`, rewriting only open rows and deleting open rows no longer produced. `_content_clusters` already calls `gaps.clusters` once per `generate`.
- `REC_TYPES` in `models.py` backs `ck_recommendation_type`; migrations 0012–0014 recreate it through a copied `_rec_type_check(values)` helper; `tests/integration/test_constraints.py` asserts the DB constraint equals `REC_TYPES`.
- Every rule's evidence carries `prompt_ids` and `observation_ids`; the accept route copies `prompt_ids` into the task and sets `measures_impact = type not in NO_IMPACT`.
- `run_rival_crawl` stores crawls and pages and does not call `refresh`; `run_page_audit` does. `refresh_due_recommendations` runs weekly per brand.
- Copy rules: every body ends with `Metric to watch: …`; `tests/unit/test_recommend_copy.py` scans `CASES` for the banned words.

Planning ran on Fable 5.1 with the user's approval. Implementers and reviewers run on Opus 5.5 only.

## Design

### 1. Matching (`bsi_core/rivals.py`)

- `_stem(word) -> str`: drop one trailing `s` when `len(word) > 3`. A deliberately crude stem so `sneakers`/`sneaker`, `shoes`/`shoe`, `kids`/`kid` meet; `bus` and `glass` are left as they are (marked in a comment as the known ceiling; a real stemmer is the upgrade path).
- `slug_words(url) -> frozenset[str]`: `urlsplit(url).path`, percent-decoded, casefolded, split on any run of characters outside `[a-z0-9]`, each word stemmed. Query string and fragment are ignored. `https://skechers.in/kids/Light-Up_Sneakers?x=1` → `{kid, light, up, sneaker}`. A bare host gives the empty set.
- `topic_words(topic) -> frozenset[str]`: the same split and stem on the topic text.
- A page **matches** a cluster when `topic_words(topic) <= slug_words(url)` and the topic has at least one word.

### 2. The rule (`bsi_core/recommend.py`)

- Constants: `RIVAL_DAYS = 14`, `RIVAL_PAGES_SATURATION = 5`, `RIVAL_PAGES_CAP = 10`. `FEASIBILITY["respond_to_rival_content"] = 0.4`.
- `_rival_pages(s, brand_id) -> list[Row]`: one SQL statement returning `competitor_id, name, url, first_seen_at` for rows of `rival_page` joined to `competitor` where the competitor is active for the brand, `NOT baseline`, and `first_seen_at >= now() − make_interval(days => :days)`; ordered `first_seen_at DESC, url`. Bound parameters only.
- `_rival_content(s, brand_id, brand, total, clusters)`: `clusters` is the list `generate` already obtains from `gaps.clusters` for `_content_clusters` (refactor: `generate` computes it once and passes it to both). For each cluster where `gap` is true or (`spread` is not None and `spread < 0`), collect the pages whose slug words contain every topic word. Skip the cluster if none. Otherwise emit one candidate:
  - `type = "respond_to_rival_content"`, `subject_key = f"rival:{cluster['key']}"`.
  - `reach = cluster["n"] / total`.
  - `pressure = min(len(matched) / RIVAL_PAGES_SATURATION, 1.0)`.
  - `title, body = rival_content_copy(...)` (§3).
  - `evidence`: `prompt_ids` (every cluster prompt), `observation_ids` (`absent_obs`), `cluster: {intent, topic}`, `cluster_key`, `n`, `spread`, `gap`, `pages: [{competitor_id, name, url, first_seen_at}]` newest first capped at `RIVAL_PAGES_CAP`, `pages_total`.
- The rule runs with the other `total`-dependent rules and adds exactly one SQL statement to `generate`.

### 3. Type, migration, copy, evidence

- `REC_TYPES` gains `"respond_to_rival_content"` (eight values). Migration `0018_respond_to_rival_content.py` recreates `ck_recommendation_type` with `_rec_type_check` copied from 0014; downgrade deletes recommendations of the new type (tasks keep their nullable `recommendation_id`), then restores the seven-value constraint.
- `rival_content_copy(brand, topic, intent, page_type, pages_by_rival, n, brand_rate, top_rival, gap) -> (title, body)`:
  - Title: `{Rival} published {k} new {topic} page(s)` for one competitor; `{k} new {topic} pages from {names(...)}` for several.
  - Body: one clause per competitor naming up to three pages by their last path segment; the brand's standing (`this cluster is a content gap` when `gap`, else `{brand} is named in {brand_rate:.0%} of {n} answers; {top_rival} in {rival_rate:.0%}`); the response (`Publish a {page_type} on {topic}` using `gaps.PAGE_TYPES[intent]`); and `Metric to watch: mention rate on the {topic} cluster.` No promised outcome.
- `NO_IMPACT` unchanged: accepting creates a task that measures impact on the cluster's prompts.
- Web `KIND["respond_to_rival_content"] = "Rival content"`. `reports.REC_LABEL` gets the same; `SEO_REC_TYPES` and `CONTENT_REC_TYPES` include the type. `METHODOLOGY_VERSION` is not bumped (ruling: it tracks how numbers are computed and formatted, not which recommendation types exist).

### 4. When it runs, API, web

- `run_rival_crawl` ends with one `refresh(s, org_id, brand_id)` in a fresh tenant session, in its own `try/log.exception`, so recommendations follow a crawl at once and a refresh failure never fails the crawl job. No `recs_refreshed_at` stamp (the weekly pass keeps its cadence). The manual `POST /competitors/crawl` therefore yields the recommendations once its job runs.
- API: no new routes; `RecommendationOut.type` is a free string. `npm run gen` is run and `gen:check` should show no diff.
- Web: `recommendations/page.tsx` renders `evidence.pages` (read defensively with `Array.isArray`) as up to 10 external links, http(s) only, with the competitor name and the day first seen; `KIND` gains the label.

### 5. Testing

- Unit (`tests/unit/test_rivals.py`): `slug_words` on query string, percent-encoding, uppercase, underscores, trailing slash, bare host; `_stem` on `sneakers`, `shoes`, `kids`, `bus`, `glass`; `topic_words` on a three-word topic.
- Unit (`tests/unit/test_recommend_copy.py`): `CASES` for one rival/one page, one rival/four pages, three rivals, gap form, behind form.
- Integration (`tests/integration/test_recommend.py`, using `test_rival_crawl`'s `_rival`/`_page` and `test_gaps`' labelled scene pattern): the matching scene (one matching new page; a matching baseline page; a matching 20-day-old page; a non-matching page; a matching page of a suggested competitor) yields exactly one candidate with only the first page in evidence and `pages_total == 1`; brand ahead yields none; gap cluster yields one with the gap wording; pressure `0.4` for two pages and `1.0` for six; evidence caps at 10 with `pages_total == 12`; `refresh` twice keeps one row, removing the page deletes the open rec, an accepted rec survives; the exact-key-set test includes the new key; the statement-count test shows one added statement.
- Integration (`tests/integration/test_rival_crawl.py`): after `run_rival_crawl` on a scene with a matching new page and a behind cluster, an open `respond_to_rival_content` row exists; a `refresh` that raises leaves the job `done`.
- Integration (`tests/integration/test_api_recommendations.py`): accept creates a task with the cluster's `prompt_ids` and `measures_impact` true.
- vitest: `KIND` has the label; a fixture with `evidence.pages` renders links for https only.

### 6. Live check

Dev has only baseline pages, so the rule produces nothing there. The check: both gates; then with the API up, `POST /v1/brands/{run1}/recommendations/generate` and confirm no error and zero `respond_to_rival_content` rows; record it in `docs/findings-slice16.md`. No fake pages are staged on dev. A real signal appears after the worker's next weekly crawl finds new pages.

## Rulings

Recorded here as they are made during execution.

## Out of scope

Prompt suggestions from new rival topics; title/H1 capture at crawl time; embedding-based matching; alerts on rival content moves; matching on rival `@type`s; crawl cadence or sampling changes; a real stemmer or synonym handling (`trainers` vs `sneakers` is a known limit, recorded in findings).
