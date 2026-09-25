# Findings: slice 16 — recommendations from competitor site changes

## 1. What was built

**Matching (`bsi_core/rivals.py`).** `_stem(word)` drops one trailing `s` when the word is longer than three characters (`sneakers` → `sneaker`, `kids` → `kid`, `bus` unchanged, `glass` → `glas`). `slug_words(url)` takes `urlsplit(url).path`, percent-decodes it (`unquote`), casefolds it, keeps each run of `[a-z0-9]` as a word and stems it; the query string and fragment are ignored and a bare host gives the empty set. `topic_words(topic)` applies the same split and stem to a cluster topic. A page matches a cluster when `topic_words(topic) <= slug_words(url)`; the rule skips a topic with no words.

**The rule (`bsi_core/recommend.py`).** Constants `RIVAL_DAYS = 14`, `RIVAL_PAGES_SATURATION = 5`, `RIVAL_PAGES_CAP = 10`, and `FEASIBILITY["respond_to_rival_content"] = 0.4`. `_rival_pages(s, brand_id)` is one SQL statement with bound parameters: `competitor_id, name, url, first_seen_at` from `rival_page` joined to `competitor` where the competitor is `active`, the page is `NOT baseline` and `first_seen_at >= now() - make_interval(days => :days)`, ordered `first_seen_at DESC, url`. `generate` now calls `gaps.clusters` once and passes the rows to both `_content_clusters` and the new `_rival_content`. The trigger: a cluster where `gap` is true or `spread < 0`, whose topic has at least one word, with at least one matching page. Each such cluster gives one candidate with `subject_key = f"rival:{key}"`, `reach = n / total` and `pressure = min(matched / 5, 1.0)`. Evidence: `prompt_ids` (every cluster prompt), `observation_ids` (`absent_obs`), `cluster {intent, topic}`, `cluster_key`, `n`, `spread`, `gap`, `pages` (`competitor_id, name, url, first_seen_at`, newest first, at most 10) and `pages_total`. `rival_content_copy` writes the title (`{Rival} published {k} new {topic} page(s)`, or `{k} new {topic} pages from {names}` for several rivals), one clause per rival naming up to three pages by their last path segment, the brand's standing (content gap, or `{brand} is named in x% of n answers; {rival} in y%`), `Publish a/an {page_type} on {topic} …` from `gaps.PAGE_TYPES[intent]`, and `Metric to watch: {brand}'s mention rate on the {topic} cluster.` `NO_IMPACT` is unchanged, so an accepted recommendation creates a task that measures impact.

**Migration `0018_respond_to_rival_content.py`.** `REC_TYPES` in `models.py` gains `respond_to_rival_content` (eight values); the migration recreates `ck_recommendation_type` with a copied `_rec_type_check`. Downgrade nulls `task.recommendation_id` for recommendations of the new type, deletes those recommendations and restores the seven-value constraint.

**Refresh after a crawl (`worker.py`).** `run_rival_crawl` ends, when at least one domain was stored, with one `refresh(s, org_id, brand_id)` in a fresh `tenant_session`, inside its own `try/log.exception`, so a refresh failure never fails the crawl job. No `recs_refreshed_at` stamp; the weekly refresh keeps its cadence.

**Labels.** Web `KIND.respond_to_rival_content = "Rival content"` (`format.ts`); `reports.REC_LABEL` has the same label, and `SEO_REC_TYPES` and `CONTENT_REC_TYPES` include the type. `METHODOLOGY_VERSION` is not bumped. No API change: `RecommendationOut.type` is a free string.

**Web.** `apps/web/src/components/RivalPages.tsx` (props `pages`, `total`, both `unknown`) renders `evidence.pages` on the recommendations page: nothing for an empty array or a non-array; at most 10 pages, each with the competitor name, the URL as a link (`target="_blank"`, `rel="noopener noreferrer"`) only when it starts `http://` or `https://`, otherwise as text, and the day first seen; then `and N more` when `total` exceeds the pages shown. `recommendations/page.tsx` types `Evidence.pages` and `pages_total` as `unknown` and renders `<RivalPages>`.

**Commits** (`git log --oneline main..HEAD`, before this one):

| Commit | What |
|---|---|
| beb9971 | docs: slice 16 design spec |
| dc60703 | docs: slice 16 implementation plan |
| deadeda | Task 1: slug and topic word matching |
| f26d782 | Task 2: type, migration 0018, feasibility and copy |
| 586ef8b, dadf538 | Task 3: the rule; then the statement-count test widened to a whole `_rival_content` call |
| f53c973 | Task 4: refresh after a rival crawl |
| 67d4ca0 | Task 5: labels, report type sets, `RivalPages` |

## 2. Live check

Run by the controller on dev before the finishing menu; filled in below.

| Check | Result |
|---|---|

## 3. Deferred / decisions

From the spec and the build:
- The stem is crude: it drops one trailing `s` on words longer than three characters. `bus` stays; `glass` becomes `glas`, on both the topic and the slug side, so matching is unaffected. Cost: irregular plurals and other suffixes (`running`/`run`, `boxes`/`box`) do not meet; a real stemmer is the upgrade path.
- No synonyms. Cost: a topic `sneakers` never matches a slug `trainers`.
- Only descriptive slugs match. Cost: pages at `/p/12345` or `/product?id=9` carry no topic words and never match, however relevant their content.
- `casefold()` expands `ß` to `ss`, and the `[a-z0-9]` split drops accented and non-Latin letters. Cost: non-English slugs and topics split into the wrong words or none.
- The weekly crawl samples at most 10 pages for `@type`, but every sitemap URL is eligible for matching. Cost: none for matching; `@type` plays no part in this rule.
- A cluster can carry both a `create_content` recommendation and this type. Cost: the operator sees two cards on one cluster; they are different actions (fill a gap, respond to a rival's move).
- The copy ban (the `FORBIDDEN` words in `test_recommend_copy.py`) binds `rival_content_copy`'s fixed wording only. Rival slugs and cluster topics quoted from stored data are exempt and are not checked against the banned words (Task 2 ruling; the same line as slice 15's ruling for quoted stored text). Cost: a real recommendation can quote a rival slug containing a banned word such as `boost`.

Minor items deferred from the task reviews, by task:

Task 1
- `casefold` expands `ß` to `ss` and `[a-z0-9]` drops accented letters. Cost: non-English slugs and topics mis-split (recorded with the synonym limit above).
- The suite prints two pre-existing starlette/anyio warnings. Cost: output noise.

Task 2
- With four or more rivals the title names only the first three (`names()` takes three), for example "4 new running shoes pages from Adidas, Puma and Bata" when Crocs also published; the body names every rival. Cost: a rival missing from the title.
- `rival_content_copy`'s `intent` parameter is unused (the page type is passed in already). Cost: a dead parameter.
- `page_type[0]` would raise `IndexError` on an empty string. Cost: none while every caller passes a `PAGE_TYPES` value.
- Live rival slugs and topics reach the copy verbatim and are not checked against `FORBIDDEN` (see the copy-ban decision above). Cost: a banned word can appear inside a quoted slug.

Task 3
- Two rival test `def` lines in `test_recommend.py` exceed 80 characters and rely on the `# noqa: F811` placement. Cost: a style exception to keep in mind if the lines are edited.
- No test covers the empty-topic guard (`if not behind or not words: continue`). Cost: removing it would let an empty topic match every page (the empty set is a subset of every set), and no test would fail.
- `by_rival` groups pages by competitor name, not id. Cost: two competitors with the same name would merge into one clause.

Task 4
- The failing-refresh test does not assert the log line (no `caplog`). Cost: a silently swallowed failure without the log would pass.
- The "make it due again" `UPDATE` on `rival_crawl` in `test_rival_crawl.py` has no `WHERE brand_id`. Cost: on the shared test DB it rewrites every brand's crawl rows, not only the test's.

Task 5
- `RivalPages` renders `[object Object]` for a non-string `url` (as escaped text). Cost: an unreadable entry for malformed evidence; no link, no injection.
- The `RivalPages` signature line is 83 characters. Cost: style only.

## 4. Not covered by tests

- The rule on real crawl data: dev's crawls are all baselines, so no non-baseline `rival_page` row exists there and the rule has produced nothing outside tests. How often real slugs match real topics is unmeasured.
- The empty-topic guard in `_rival_content` (Task 3, §3).
- The log line of a failing refresh after a crawl (Task 4, §3).
- The recommendations page route itself; only the `RivalPages` component (https link, `javascript:` as text, empty and non-array input, the cap of 10, "and N more") and the `KIND` label are unit-tested.
