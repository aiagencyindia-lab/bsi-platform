# Slice 9 design: competitor intelligence (PRD F07, first cut)

## Context

Slices 1–8 measure a brand in AI answers, recommend actions, audit the
brand's site and its entity. Competitors appear only as a share-of-voice
table on the Overview and as "rivals" inside citation and content rules.
PRD F07 asks for per-competitor metrics with deltas, a visibility change
feed with evidence, and a weekly crawl of rival domains. Decisions made in
brainstorming:

- **Scope:** per-competitor metrics, a leaderboard, and the change feed.
  The weekly rival crawl (sitemap diff, new structured data) is deferred:
  it needs a snapshot table and only becomes actionable with the content
  gap engine (F11).
- **Feed gate:** the PRD's count rule (≥ 10 prompts moved ≥ 10 points in
  one direction within 14 days) **plus** a pooled significance test: the
  competitor's rate over the moved prompts, before against after, must
  have a Newcombe interval that excludes zero. At n = 5 per window one
  observation moves a prompt by 20 points, so the count rule alone fires
  on noise.
- **Storage:** computed on read, like citations. No table, no migration,
  no job kind. Storing entries can come with alerts (F15).

Nothing spends money: every number is SQL over stored observations,
mentions and citations.

## Design

### A. Metrics — `bsi_core/competitors.py`

`entity_metrics(s, brand_id, f: Filters) -> list[dict]`: one row for the
brand and one per **active** competitor (`metrics._entities` order), sorted
by `mention_rate.value` descending with the brand winning ties, then name.
The base set is `metrics._where(brand_id, f)` restricted to
`o.status = 'done'`, so the numbers agree with the Overview tiles for the
same filters. A row:

| Field | Definition |
|---|---|
| `entity_id`, `name`, `type` | `brand` or `competitor` |
| `mention_rate` | done answers with a `mention` row for the entity / done answers |
| `recommendation_rate` | done answers with a mention whose `rec_status = 'recommended'` / done answers; the API flags it `experimental`, as the brand's is |
| `avg_position` | mean `mention.position` over the entity's mentions, `{value, n_mentioned}`; `value` null when `n_mentioned` = 0 |
| `citation_rate` | done answers with a citation whose domain is owned by one of the entity's domains / done answers. Brand domains come from `domain.host`; competitor domains from `competitor.domains`. Ownership is exact host or subdomain (`matching.is_owned` semantics, done in SQL without LIKE, so `_` or `%` in a host is not a wildcard: `c.domain = h.host OR right(c.domain, length(h.host) + 1) = '.' || h.host` over an unnest of (entity, host) pairs). No domains means k = 0 |
| `sov` | the entity's mention count / the sum of mention counts over the same entity list (one read of the active competitors gives the rows, the hosts and the total, so a competitor activated mid-call cannot skew it); `metrics.rate`. For the brand it equals `brand_metrics(...)["sov"]` |
| `prompt_coverage` | prompts with ≥ 1 done answer naming the entity / prompts with ≥ 1 done answer |
| `sentiment` | `{positive: Rate, negative: Rate, index: float|None}` where the rates are the entity's mentions with `sentiment = 'positive'` / `'negative'` over its mentions, and `index = positive.value − negative.value` (null when no mentions). Computed server-side so the page computes nothing |
| `citing_domains` | up to five `{domain, answers, owner}` for domains cited in done answers that name the entity, most answers first then domain; `owner` is `brand`, `rival` or `third_party` as in `citations.sources` |

Queries: a fixed number per call, whatever the number of competitors:
`_entities_and_hosts` (the brand, its domain rows and one read of the
active competitors), the totals, one query grouped by
`mn.entity_id` for the mention stats, one for citations and one for the
citing domains (`row_number() OVER (PARTITION BY entity ...)`). 7 in all,
measured by `test_query_count_does_not_grow_with_rivals`.

Every `Rate` is `{value, n, ci_low, ci_high}` from `metrics.rate` (95%
Wilson). Prompt status is not filtered, as in `metrics.py`.

`entity_deltas(s, brand_id, f, days, to) -> dict`: same windows as
`brand_deltas` (`before = [to − 2·days, to − days)`, `after = [to − days,
to)`), `entity_metrics` on each, the same `window_versions` comparability
rule and reason text, and per entity `deltas` for `mention_rate`,
`recommendation_rate`, `citation_rate`, `prompt_coverage` and `sov` via
`metrics.delta`. Shape:
`{before: {from, to, entities}, after: {...}, comparable, reason,
deltas: {entity_id: {metric: Delta}} | None}`. An entity present in only
one window gets deltas against a zero-count rate in the other.

### B. Change feed — `visibility_changes`

`visibility_changes(s, brand_id, f, days=14, to=None) -> dict`. Constants
`MIN_PROMPTS = 10`, `MIN_SHIFT = 0.10`, `EVIDENCE_CAP = 20`. Windows as in
A. Result `{comparable, reason, prompts, changes}` where `prompts` is the
number of prompts with done answers in both windows and `reason` is the
version reason, else `"fewer than 10 prompts with answers in both
windows"` when `prompts < MIN_PROMPTS`, else null.

For each active competitor:

1. Per prompt with done answers in both windows: `k/n` naming the
   competitor in each window.
2. A prompt **moved** when `after − before ≥ MIN_SHIFT` (up) or
   `before − after ≥ MIN_SHIFT` (down).
3. A direction **qualifies** when its moved prompts number
   `≥ MIN_PROMPTS` and `metrics.delta(pooled_before, pooled_after)` over
   those prompts has label `increase` (up) or `decrease` (down).

One entry per qualifying (competitor, direction):

| Field | Content |
|---|---|
| `competitor_id`, `name`, `direction` | `up` or `down` |
| `before`, `after` | pooled `Rate`s over the moved prompts |
| `delta` | `metrics.delta(before, after)` |
| `prompts` | `[{prompt_id, text, before: Rate, after: Rate}]`, largest shift first |
| `engines` | distinct engine codes of the after-window answers on those prompts that name the competitor |
| `new_citing_domains` | domains cited in after-window answers on those prompts that name the competitor, and cited in no before-window answer of the brand at all; sorted by answers |
| `observation_ids` | up to `EVIDENCE_CAP` after-window answers on those prompts naming the competitor, most recent first |

Entries are sorted by `abs(delta.value)` descending. Cited page URLs are
Vertex redirects with no title, so "new cited pages" stays at domain level.

Two limits, stated on the page and in findings: Run 1 was sampled in one
burst, so its feed is empty until a second window exists; a brand with
fewer than 10 prompts can never get an entry (the PRD's threshold).

### C. API — `routers/competitors.py`

Prefix `/brands/{brand_id}` (the existing router file `brands.py` keeps the
CRUD routes). `brand_or_404` and the `filters()` dependency from
`routers/metrics.py` are reused.

| Route | Returns |
|---|---|
| `GET /competitors/metrics` | `list[EntityMetricsOut]` |
| `GET /competitors/deltas?days=7` (1–90) | `EntityDeltasOut`; 422 when `date_from` is set, `to = date_to or now`, as `/deltas` |
| `GET /competitors/changes?days=14` (1–90) | `ChangesOut`; same `date_from` rule (both routes share `routers/metrics.window_end`) |

Schemas in `schemas.py`: `EntityMetricsOut` (rates as `Rate`/`RecRate`,
`avg_position: AvgPosition`, `sentiment: SentimentOut`, `citing_domains:
list[CitingDomainOut]`), `EntityDeltasOut`, `ChangeOut`, `ChangesOut`
(with `window: ChangeWindowOut`, `{before_from, split, to}`: the feed's
windows, `[before_from, split)` and `[split, to)`). All
three routes join `CASES` in `test_isolation.py` with an owner-path 200
test each. No writes.

### D. Web — Competitors tab

`b/[id]/competitors/page.tsx`, tab "Competitors" after Prompts in
`layout.tsx`. Server Component only:

- `Filters` with the days field (`apiQuery(sp, ["days"], ["date_from"])`
  for deltas, plain filters for metrics; three fetches in parallel).
  The change feed always uses a fixed 14-day window (`days=14`, without
  `date_from`), while the days filter sets the leaderboard deltas. The
  feed's label gives its actual dates from `ChangesOut.window`
  ("between 2026-08-26–2026-09-08 and 2026-09-09–2026-09-22" for
  `date_to` = 2026-09-23), not "the last 14 days", which is wrong once
  `date_to` is set. Window ends are exclusive, so each range prints its
  last included day (`format.lastDay`: the UTC date 1 ms before the end;
  with no `date_to` the end is now, so the label ends today). The days
  box shows `validDays(sp) ?? 7`.
- `days` is validated by `format.validDays`: digits only, 1–90. Anything
  else (missing, repeated, `0`, `91`, `abc`, `7.5`) is left out of the
  API query and the page shows 7, the API default; the Overview does the
  same.
- Leaderboard table: entity (brand row highlighted with a `you` tag, as on the Overview),
  mention rate with interval and its delta (`pts(...)` vs previous N days,
  hidden with the reason when not comparable), recommendation rate with
  the experimental tag, share of voice, coverage, citation rate, average
  position, sentiment index, citing domains (domain and answers).
- Change feed: one card per entry: name, direction, pooled before → after
  with the delta and interval, the moved prompts with their rates, engines,
  new citing domains, and links to `/o/{oid}`. Empty state prints
  `reason`, or "No competitor moved at least 10 points on at least 10
  prompts with a significant pooled change" when `reason` is null.
- `lib/types.ts` gains the three aliases; `npm run gen` regenerates
  `schema.d.ts`. The page sorts and computes nothing.

### Testing

`tests/integration/test_competitors.py`, expectations computed from the
fixture:

- **Scene:** brand, two active competitors (one with two domains, one with
  none), one suggested competitor; five done answers on three prompts;
  mentions with positions, `rec_status` and sentiment; citations on a
  brand domain, a rival subdomain and two third-party domains. Assert every
  field of every row as k/n with `pytest.approx` Wilson bounds; the
  suggested competitor is absent; the brand row's `mention_rate`,
  `recommendation_rate`, `citation_rate`, `prompt_coverage` and `sov`
  equal `brand_metrics` for the same filters; sorting by mention rate.
- **Deltas:** two windows by backdating `requested_at`; a competitor with
  no before-window mentions; mixed pipeline versions → not comparable with
  the same reason as `brand_deltas`.
- **Feed:** 12 prompts × 10 answers per window. Rival A named in 0/10
  before and 10/10 after on 11 prompts → one `up` entry with the computed pooled
  delta, prompts largest shift first, engines, capped observation ids, one
  new citing domain present and one old domain absent. Rival B moves on 9
  prompts → no entry. Rival C moves on 10 prompts by exactly one answer
  each (4/10 → 5/10) → pooled interval includes zero → no entry. Fewer than
  10 prompts in both windows → empty with the prompts reason.
- **Filters:** engine and locale filters apply to all three functions.
- **API:** owner-path 200 for the three routes, the isolation cases, 422 on
  `date_from` for deltas and changes.

`metrics.py` stays under the 100% coverage gate; `competitors.py` gets a
coverage figure in findings, not a gate.

### Live check (no spend)

Read-only calls of the three functions on Run 1 in a tenant session (no
writes). Expected: a leaderboard for the five rivals and the brand; deltas
and the feed empty or non-comparable because of the single burst, with the
reason. Recorded in `docs/findings-slice9.md`.

## Files touched

- `packages/core/bsi_core/competitors.py` (new)
- `apps/api/bsi_api/routers/competitors.py` (new), `main.py` (register),
  `schemas.py`
- `apps/web/src/app/(app)/b/[id]/competitors/page.tsx` (new),
  `b/[id]/layout.tsx`, `lib/types.ts`, `lib/schema.d.ts` (generated)
- `tests/integration/test_competitors.py` (new), `test_isolation.py`
- `docs/README.md`, `docs/findings-slice9.md`, this spec, the plan

## Out of scope, by decision

- Weekly crawl of rival domains (sitemap diff, new structured data).
- Stored change-feed entries and alerts (F15).
- Resolving cited page URLs; "new cited pages" is domain-level.
- A competitor archive status (delete stays a hard delete; orphaned
  mentions are ignored by the active-competitor join).

## Risks

- **Correlated windows.** `delta()` assumes independent samples; windows
  share prompts, so the pooled test is somewhat optimistic. The count rule
  in front of it limits how often that matters.
- **Empty feed on current data.** Run 1 cannot produce an entry; the rule
  is proved by the synthetic fixture only until a second sampling window
  exists.
- **Query cost.** Fixed per request, not per entity: `entity_metrics`
  runs 7 queries whatever the number of competitors (measured: 7 with 1
  rival and 7 with 6, `test_query_count_does_not_grow_with_rivals`);
  `entity_deltas` runs it twice plus 2; `visibility_changes` about 8 plus
  3 per entry. A Competitors page load is about 32 + 3E queries (E = feed
  entries), each scanning the brand's done answers in the window.
