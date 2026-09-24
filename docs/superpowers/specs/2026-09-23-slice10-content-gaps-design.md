# Slice 10 design: content gaps (PRD F11, gap half)

## Context

Slices 1–9 measure a brand in AI answers, recommend actions, audit its
site and entity, and compare it with rivals. The `create_content` rule
(slice 6) fires per prompt, so a losing topic with six prompts gives six
briefs with no structure. PRD F11 asks for content gaps at cluster level:
target queries, intent, page type, evidence, competitors, citation
sources, suggested structure, internal links and a priority. Decisions made in brainstorming:

- **Cluster** = an `(intent, topic)` group of active prompts (PRD F02's
  definition; the `/clusters` count endpoint already groups this way).
  Unlabelled prompts keep the per-prompt rule.
- **Gap rule** = the slice 6 absence rule at cluster level (brand absent
  in ≥ half the cluster's answers; most common absence reason in
  `CONTENT_REASONS`).
- **Rec shape** = `create_content` keyed by cluster replaces the per-prompt
  rec for labelled prompts. No new rec type, no migration.
- **Labelling** = new job kind `label_prompts` that calls
  `suggest_prompts(..., count=0, ...)` (which already backfills intent,
  topic and embedding without generating prompts), budget-gated with a
  small estimate. Run 1's 20 prompts have no labels; the live check labels
  them once (≈ a cent, approved).
- **Brief fields** are heuristics without a model call: page type and
  structure are templates by intent, labelled as such.
- Changed after review at the user's decision: the rival condition was
  dropped so the cluster rule matches the old per-prompt rule (no rival
  required; such gaps get pressure 0).

Run 1 today: 20 prompts, 0 labelled, 100 done answers. Spend $9.2762 of
$15.

## Design


### A. Clusters and the gap rule — `bsi_core/gaps.py`

`clusters(s, brand_id, f: Filters) -> list[dict]`: one row per
`(intent, topic)` of the brand's **active** prompts with both labels
non-null, over done answers under `metrics._where` (so numbers agree with
the Prompts page). Per cluster:

| Field | Definition |
|---|---|
| `intent`, `topic`, `key` | `key = f"cluster:{intent}:{topic}"` |
| `prompts` | `[{prompt_id, text, n, absent}]`, worst (highest absent share) first |
| `n` | done answers on the cluster's prompts |
| `brand` | `rate(answers with a brand mention, n)` |
| `absent` | answers with no brand mention |
| `reasons` | `{reason: count}` from `extraction.absence_reason` over absent answers (null ignored) |
| `rivals` | `[{competitor_id, name, answers}]` active competitors named in the cluster's answers, most first |
| `top_rival` | first of `rivals` as a `rate(answers, n)` with name, or null |
| `spread` | `brand.value − top_rival.value` (null when either is null) |
| `cited` | `rate(answers citing a brand-owned domain (is_brand_owned), n)` |
| `sources` | top 10 `{domain, answers, owner}` cited in the cluster's answers (`owner` via `competitors.owner_of`) |
| `brand_urls` | distinct `citation.url` with `is_brand_owned` in the cluster's answers, up to 10 |
| `rival_absent` | absent answers naming ≥ 1 active rival (drives the rec's pressure) |
| `gap` | `absent ≥ n/2` and `max(reasons) ∈ CONTENT_REASONS` (ties: highest count, then name) |
| `brief` | null unless `gap`; see B |

Sorted by `spread` ascending (null last), then `n` desc, then key. Both
gaps and winning clusters are returned; the page shows both.

`clusters()` runs a fixed 6 statements whatever the number of clusters
(brand, active competitors, brand domains, answers, rivals, citations):
per-answer brand/rival/owned-citation flags come from LEFT JOINs to
subqueries grouped by observation, and cited domains and owned URLs come
from one `UNION ALL` citation read. Every value is bound.

`unlabelled(s, brand_id) -> int`: active prompts with a null intent or
topic.

### B. The brief

`brief(cluster) -> dict` (pure):

| Field | Source |
|---|---|
| `target_queries` | the cluster's prompt texts, worst first, capped at `QUERIES_CAP = 20` |
| `prompts_total` | how many prompts the cluster has; the page shows "and N more" past the cap |
| `page_type` | `PAGE_TYPES[intent]`: comparison→"comparison page", alternative→"alternatives page", recommendation→"best-of round-up", informational→"guide", commercial→"category page", transactional→"product page", problem-based→"how-to", persona-specific→"solution page", industry-specific→"solution page", geographic→"local page" |
| `structure` | `STRUCTURES[page_type]`: a list of heading strings, with the capped target queries slotted in as questions (e.g. guide: "What is …", one "H2: {prompt}" per prompt, "Sources and evidence", "FAQ") |
| `competitors` | `rivals` names in order |
| `sources` | `sources` with `owner != "brand"`, third-party first |
| `internal_links` | `brand_urls`, or `[]` (page says "none cited yet") |
| `evidence` | `{prompt_ids, observation_ids}`: up to `EVIDENCE_CAP = 20` absent answers, most recent first |
| `note` | fixed: "Page type and structure are templates by intent, not a judgement of the site." |

### C. Recommendation rule — `recommend.py`

- `_content` (per prompt) now restricts to prompts with `intent IS NULL
  OR topic IS NULL`.
- New `_content_clusters(s, brand_id, brand, total)`: for each gap cluster
  (via `gaps.clusters` with default `Filters()`), one `Candidate` of type
  `create_content`, `subject_key = key`, `reach = absent/total`,
  `pressure` = share of absent answers naming ≥ 1 active rival (same
  meaning as `_rivals`), evidence = the brief without its inner
  `evidence` (stored once) + `{"cluster": {intent, topic}, "reason": top
  reason, "absent", "n", "prompt_ids" (every cluster prompt, uncapped),
  "observation_ids" (≤ EVIDENCE_CAP)}`.
- Decided clusters: once a cluster rec is accepted or dismissed it is not
  raised again. `covered` = the `prompt_ids` of decided recs keyed `K` or
  `K:+…`; the cluster's other prompts (`new`), if any, are re-clustered
  with `Filters(prompt_ids=new)` and, when they alone are a gap (the
  whole cluster need not still be one), raised
  as one candidate keyed `K:+<first 8 hex of sha1(",".join(sorted(new)))>`
  with their own numbers and only their prompt ids. A further new prompt
  changes the hash, so `refresh()` replaces the open `:+` row; decided
  rows are untouched and accepted tasks keep their prompt ids.
- `cluster_copy(brand, intent, topic, page_type, worst_prompts, absent,
  n, rivals) -> (title, body)`: title "Publish a {page_type} for {topic}
  ({intent})"; body names the absence share, the two worst prompts, the
  rivals, and ends "Metric to watch: mention rate on the cluster's
  prompts." No forbidden words.
- `generate()` calls both rules. `refresh()` unchanged: newly labelled
  prompts' open per-prompt recs disappear (not regenerated) and the
  cluster rec appears; accepted/dismissed rows stay.
- Accepting a cluster rec creates a task whose `prompt_ids` are the
  cluster's prompts (the router already copies `evidence.prompt_ids`), so
  impact is measured across them as today.

### D. Labelling job

- `worker.JOB_ESTIMATES["label_prompts"] = LABEL_JOB_MICROS` (new
  constant in `suggest.py`, 10_000 = $0.01: one Flash-Lite label call +
  embeddings for ≤ 100 prompts), runner
  `lambda: suggest_prompts(org_id, brand_id, 0, generator, embedder)`.
  `suggest_prompts` returns "suggested:0" and records spent cost as today.
- `POST /brands/{id}/prompts/label` → 202 `QueuedOut` via
  `queue_suggestion(c, brand_id, "label_prompts", {})` (hour slot, 409 on
  archived).
- `GET /brands/{id}/clusters/gaps` → `ClustersOut{unlabelled: int,
  clusters: list[ClusterOut]}` with the `filters()` dependency.
- Both routes join `CASES` in `test_isolation.py`; owner-path tests.

### E. Web — Clusters tab

`b/[id]/clusters/page.tsx`, tab after Prompts. Server Component:
- Banner when `unlabelled > 0`: "N prompts have no intent or topic yet"
  + form action `labelPrompts` (POST the route, redirect with
  `?queued=<status>`, `auditNote`-style message).
- Table: intent, topic, prompts, n, brand rate (+interval), top rival and
  rate, absent share, spread as `pts`, and a `gap` tag. Server order.
- Each gap row: a `<details>` block with the brief (page type, target
  queries, structure, competitors, sources with owner tags, internal
  links or "none cited yet", evidence links to `/o/{oid}`, the note).
- Recommendations page: when `evidence.prompt_ids` has > 1 entry, list
  each as a link to `/b/{id}/prompts/{pid}` (replacing "N prompts").
- Types via `npm run gen`. The page computes and sorts nothing.

### Testing

`tests/integration/test_gaps.py` (expectations computed):
- Scene: brand + 2 active rivals + 1 suggested; clusters
  `(comparison, running shoes)` gap: 2 prompts, 8 answers, brand present
  in 2, rivals named in 5 absent answers, reasons 5×competitor_dominance
  + 1×not_retrieved; `(informational, sizing)` winning: brand 4/4;
  `(recommendation, kids)` mixed: absent 1/4; one unlabelled prompt with
  brand 0/3 competitor_dominance. Citations: brand-owned url on a gap
  answer, rival subdomain, two third-party domains. Assert every field;
  `brief` only on the gap; sources owners; `brand_urls`; evidence cap;
  sort order.
- Rule: `generate()` gives one `create_content` keyed
  `cluster:comparison:running shoes` with priority
  `round((6/19)*(5/6)*0.4, 4)` (total = 19 done answers on active
  prompts), and the unlabelled prompt's per-prompt rec `str(pid)`; no
  per-prompt recs for labelled prompts. Labelling that prompt (owner
  UPDATE) then `refresh()` drops its open rec; an accepted one stays.
- Filters: `prompt_ids`/engine narrow the cluster numbers.
- Job: `process_job` with fake generator/embedder labels only unlabelled
  prompts, writes cost, is budget-gated (`test_worker` patterns), returns
  "suggested:0"; the API queue route 202 and 409.
- Isolation + owner-path for both routes; copy test covers
  `cluster_copy`.

### Live check (spend ≈ $0.01, approved)

1. Queue `label_prompts` for Run 1 via the API or `enqueue_job`, run the
   worker once (`set -a && source .env && set +a`), confirm 20 labels and
   embeddings and the job cost.
2. Read-only: `gaps.clusters()` and `generate()` in a tenant session,
   rolled back; record clusters, gaps, briefs, and `top_by_type` position.
3. `recommendation`/`task`/`site_audit` stay empty; spend updated in
   findings.

### Files touched

`packages/core/bsi_core/{gaps.py (new), recommend.py, suggest.py}`,
`apps/workers/bsi_workers/worker.py`, `apps/api/bsi_api/{schemas.py,
routers/prompts.py or clusters.py (new), main.py}`,
`apps/web/src/app/(app)/b/[id]/{clusters/{page.tsx,actions.ts} (new),
layout.tsx, recommendations/page.tsx}`, `lib/{types.ts, schema.d.ts,
format.ts}`, `tests/integration/{test_gaps.py (new), test_isolation.py,
test_worker.py}`, `tests/unit/test_recommend_copy.py`, docs.

### Out of scope, by decision

URL optimizer and AI Citability Score (model spend); embedding-based
cluster merging and cluster labelling by LLM; a stored cluster table;
alerts on new losing clusters; per-engine cluster metrics.

### Risks

- **Label quality is model-judged** (slice 4 found the topic instruction
  soft); a bad topic splits or merges clusters. Relabelling is not built.
- **Small n per cluster** at 5 samples/prompt: the gap rule is a majority
  rule, not a significance test; the page shows intervals.
- **Spend**: `label_prompts` is budget-gated; Run 1's run is ≈ $0.01.
