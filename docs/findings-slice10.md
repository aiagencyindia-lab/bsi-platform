# Slice 10 findings: content gaps

Date: 2026-09-23. Branch `slice10-content-gaps`. Sources: one live
`label_prompts` job on the dev database `bsi` for the Run 1 brand (the
only paid call in this slice, approved at about $0.01), then read-only
calls of `bsi_core.gaps.clusters()`, `unlabelled()`,
`bsi_core.recommend.generate()` and `top_by_type()` in a tenant session,
plus a few read-only `psql` queries. `refresh()` was not called and the
read session was rolled back. The gap numbers below were re-read the
same way after the gap rule dropped its rival condition (section 3).
Afterwards the dev tables `recommendation`,
`task` and `site_audit` held `0|0|0` rows.

## 1. What was run, and how

Run 1 is 100 done answers from one engine over 20 active prompts, five
answers each, for BSOAgentTestBrand and five active competitors (Adidas,
Bata, Campus, Crocs, Skechers). Before this task none of the 20 prompts
had an intent, a topic or an embedding (`count(intent), count(topic),
count(embedding)` was `0|0|0`).

**Labelling.** No job was queued, running or retrying beforehand (`0`).
The job was queued with `enqueue_job(s, ORG, BRAND, "label_prompts", {})`
in a tenant session and run with exactly one call of
`process_job(GeminiGroundingAdapter(), generate, embed)`, the adapter,
generator and embedder `tick()` passes. `worker.main()` and `tick()` were
not called, so no schedule, crawl sweep or recommendation refresh ran.
Scripts are scratch files, not committed. The worker log:

```
... gemini-3.5-flash-lite:generateContent "HTTP/1.1 200 OK"
... gemini-embedding-001:predict "HTTP/1.1 200 OK"
... bsi.worker job 36213eb2-c8cb-4d62-9b01-3e758d48bff0: suggested:0
```

One label call and one embedding call. `suggested:0` is right: the job
runs `suggest_prompts` with `count=0`, so it labels and embeds and adds
no prompts. The job row:

```
kind          | status | error | cost_micros | params
label_prompts | done   |       |        2238 | {}
```

After it, `count(intent), count(topic), count(embedding)` for the brand
was `20|20|20`, `unlabelled()` returned 0, and the queue was empty again.

**Reading.** Core of the read-only script:

```python
with tenant_session(ORG) as s:
    print("unlabelled", unlabelled(s, BRAND))
    cs = clusters(s, BRAND, Filters())
    ...  # each cluster: key, prompts, n, brand rate, top rival, absent, spread, gap
    cands = generate(s, BRAND)
    ...  # every candidate, ranked
    top_by_type(cands); top_by_type(cands, 10)
    s.rollback()
```

`top_by_type` reads only `.type`, so it ran on the `generate()` candidates
directly; no recommendation rows were needed.

## 2. The 20 labels

| Intent | Topic | Prompt |
|---|---|---|
| commercial | kids shoes | durable kids shoes under 1500 rupees |
| commercial | kids sneakers | affordable kids sneakers brands in India |
| comparison | kids shoe brands | Bata vs Campus shoes for kids which is better |
| comparison | kids shoe brands | Skechers or Adidas for kids, which should I buy |
| informational | kids shoe brands | Is BSOAgentTestBrand a good brand for kids shoes? |
| informational | kids shoe brands | which kids shoe brand lasts the longest |
| informational | kids shoes | are Crocs good for kids everyday use |
| informational | light-up sneakers | BSOAgentTestBrand light-up sneakers review |
| problem-based | kids shoes | which kids shoes are good for flat feet |
| problem-based | school shoes | my child's feet hurt in school shoes, what should I buy |
| recommendation | kids shoe brands | top rated kids shoe brands on Amazon India |
| recommendation | kids shoes | best shoes for kids in India |
| recommendation | kids shoes | kids joggers with velcro recommendation |
| recommendation | light-up sneakers | best light-up sneakers for kids |
| recommendation | school shoes | best black school shoes for boys in India |
| recommendation | school shoes | which brand makes the most comfortable school shoes for children |
| recommendation | sports shoes | best sports shoes for girls aged 8 to 12 |
| recommendation | sports shoes | good running shoes for a 10 year old boy in India |
| recommendation | toddler shoes | best shoes for toddlers learning to walk |
| recommendation | waterproof shoes | best waterproof shoes for kids during monsoon |

Six intents and eight topics, giving 15 `(intent, topic)` clusters.

## 3. The clusters

In the order `clusters()` returns them (spread ascending, clusters with
no rival last, then larger n, then key).
Brand rate and top-rival rate are value (n, 95% Wilson interval) over the
cluster's answers. Absent is answers without the brand; "rival in absent"
is those of them naming an active rival. Spread is brand minus top rival.

| Cluster | Prompts | n | Brand rate | Top rival | Absent | Rival in absent | Spread | Top reason | Gap |
|---|---|---|---|---|---|---|---|---|---|
| commercial: kids shoes | 1 | 5 | 0.000 (0.000-0.434) | Campus 1.000 (0.566-1.000) | 5 | 5 | -1.0 | competitor_dominance 5 | yes |
| commercial: kids sneakers | 1 | 5 | 0.000 (0.000-0.434) | Campus 1.000 (0.566-1.000) | 5 | 5 | -1.0 | competitor_dominance 5 | yes |
| informational: kids shoes | 1 | 5 | 0.000 (0.000-0.434) | Crocs 1.000 (0.566-1.000) | 5 | 5 | -1.0 | competitor_dominance 5 | yes |
| recommendation: kids shoe brands | 1 | 5 | 0.000 (0.000-0.434) | Adidas 1.000 (0.566-1.000) | 5 | 5 | -1.0 | competitor_dominance 5 | yes |
| recommendation: light-up sneakers | 1 | 5 | 0.000 (0.000-0.434) | Skechers 1.000 (0.566-1.000) | 5 | 5 | -1.0 | competitor_dominance 5 | yes |
| recommendation: sports shoes | 2 | 10 | 0.000 (0.000-0.278) | Adidas 0.900 (0.596-0.982) | 10 | 10 | -0.9 | competitor_dominance 10 | yes |
| comparison: kids shoe brands | 2 | 10 | 0.000 (0.000-0.278) | Adidas 0.700 (0.397-0.892) | 10 | 10 | -0.7 | competitor_dominance 10 | yes |
| recommendation: kids shoes | 2 | 10 | 0.000 (0.000-0.278) | Adidas 0.700 (0.397-0.892) | 10 | 8 | -0.7 | competitor_dominance 8, not_retrieved 2 | yes |
| recommendation: school shoes | 2 | 10 | 0.000 (0.000-0.278) | Adidas 0.600 (0.313-0.832) | 10 | 9 | -0.6 | competitor_dominance 9, not_retrieved 1 | yes |
| recommendation: waterproof shoes | 1 | 5 | 0.000 (0.000-0.434) | Adidas 0.600 (0.231-0.882) | 5 | 5 | -0.6 | competitor_dominance 5 | yes |
| problem-based: kids shoes | 1 | 5 | 0.000 (0.000-0.434) | Adidas 0.400 (0.118-0.769) | 5 | 2 | -0.4 | not_retrieved 3, competitor_dominance 2 | yes |
| problem-based: school shoes | 1 | 5 | 0.000 (0.000-0.434) | Crocs 0.200 (0.036-0.624) | 5 | 1 | -0.2 | not_retrieved 4, competitor_dominance 1 | yes |
| informational: kids shoe brands | 2 | 10 | 0.400 (0.168-0.687) | Skechers 0.500 (0.237-0.763) | 6 | 5 | -0.1 | competitor_dominance 5, not_retrieved 1 | yes |
| informational: light-up sneakers | 1 | 5 | 1.000 (0.566-1.000) | Skechers 0.200 (0.036-0.624) | 0 | 0 | +0.8 | none | no |
| recommendation: toddler shoes | 1 | 5 | 0.000 (0.000-0.434) | none | 5 | 0 | none | not_retrieved 5 | yes |

14 of 15 clusters are gaps. The brand's cited rate is 0.000 in every
cluster: it has no `domain` rows, so no citation can be brand-owned
(findings-slice9 §2).

**Reading it.**
- Ten clusters are a single prompt, n=5. The brand-rate interval at 0/5
  runs to 0.434, so a one-prompt cluster says little more than the
  per-prompt rule did. The clustering pays off only in the five
  two-prompt clusters, where n=10 narrows the brand's upper bound to
  0.278.
- `informational: kids shoe brands` is a gap on 6 absent of 10, but its
  two prompts differ: "which kids shoe brand lasts the longest" is 5/5
  absent, the brand's own "Is BSOAgentTestBrand a good brand for kids
  shoes?" is 1/5. The prompt that names the brand props up the cluster's
  brand rate (0.400). The brief lists both as target queries.
- `recommendation: toddler shoes` is a gap with no rival: all five
  answers are `not_retrieved` and none names an active competitor
  (rival in absent 0). The gap rule first required a rival in an absent
  answer, which left this cluster out; at the user's decision after
  review that condition was dropped, so the cluster rule now matches the
  old per-prompt rule (section 5).
- The only cluster the brand leads is its own light-up review prompt
  (+0.8), as in every slice so far.

## 4. The briefs

Every gap has a brief; none needed a model call. Per gap: page type (a
template by intent), the rivals named in the cluster, the first three
sources (all `third_party`) and the rival-owned sources the brief sorts
after the third-party ones. Each brief carries 10 sources (`SOURCES_CAP`)
and 0 internal links (no brand-owned citations).

| Cluster | Page type | Rivals | First sources (answers) | Rival sources | Evidence |
|---|---|---|---|---|---|
| commercial: kids shoes | category page | Campus, Bata | puma.com 5, walkaroo.in 4, flipkart.com 3 | campusshoes.com | 1 prompt, 5 obs |
| commercial: kids sneakers | category page | Campus, Adidas, Skechers, Bata | ludic.life 5, starkidz.co.in 5, ajio.com 4 | adidas.co.in, bata.com | 1, 5 |
| informational: kids shoes | guide | Crocs | anklefootmd.com 5, firstwalkers.com.au 5, freelandfoot.com 5 | - | 1, 5 |
| recommendation: kids shoe brands | best-of round-up | Adidas, Bata, Skechers, Campus, Crocs | youtube.com 5, starkidz.co.in 4, wearetto.com 4 | adidas.co.in, bata.com | 1, 5 |
| recommendation: light-up sneakers | best-of round-up | Skechers, Adidas, Campus | shoecarnival.com 5, striderite.com 5, todaysparent.com 5 | - | 1, 5 |
| recommendation: sports shoes | best-of round-up | Adidas, Skechers, Campus | youtube.com 7, forbes.com 5, starkidz.co.in 5 | adidas.co.in, campusshoes.com | 2, 10 |
| comparison: kids shoe brands | comparison page | Adidas, Bata, Campus, Skechers | youtube.com 8, facebook.com 7, adidas.com 6 | bata.com, campusshoes.com | 2, 10 |
| recommendation: kids shoes | best-of round-up | Adidas, Skechers, Bata, Campus, Crocs | starkidz.co.in 5, target.com 5, walkaroo.in 5 | - | 2, 10 |
| recommendation: school shoes | best-of round-up | Adidas, Bata, Campus, Skechers, Crocs | youtube.com 6, forbes.com 5, indiatimes.com 5 | bata.com, adidas.co.in | 2, 10 |
| recommendation: waterproof shoes | best-of round-up | Adidas, Crocs | forbes.com 4, wearetto.com 4, adidas.com 3 | - | 1, 5 |
| problem-based: kids shoes | how-to | Adidas, Crocs, Skechers | childrensphysicaltherapyandwellness.com 5, pediped.com 5, reddit.com 5 | - | 1, 5 |
| problem-based: school shoes | how-to | Crocs | completefeetusa.com 5, naplespodiatrist.com 5, forbes.com 4 | - | 1, 5 |
| informational: kids shoe brands | guide | Skechers, Adidas, Crocs | reviewed.com 6, facebook.com 5, forbes.com 5 | - | 2, 6 |
| recommendation: toddler shoes | best-of round-up | - | napacenter.org 5, pediped.com 5, pibaby.com 5 | - | 1, 5 |

The structure for `comparison: kids shoe brands`, as generated:

```
H1: kids shoe brands: how the options compare
H2: Bata vs Campus shoes for kids which is better
H2: Skechers or Adidas for kids, which should I buy
H2: Side-by-side table
H2: Sources and evidence
H2: FAQ
```

with the note "Page type and structure are templates by intent, not a
judgement of the site."

**Reading it.**
- Rival brand domains sit among the third-party sources: `adidas.com`
  in the comparison, waterproof and `recommendation: kids shoes` briefs,
  and `skechers.com` in the comparison brief (10th of its 10 sources, 4
  answers). Ownership follows declared domains, and Adidas and Skechers
  declare only `adidas.co.in` and `skechers.in` (findings-slice9 §2), so
  the `.com` domains count as `third_party`. An operator would read
  "earn coverage on adidas.com" as odd advice.
- The how-to template read badly with a noun topic: its H1 was
  `How to {topic}`, so the two problem-based briefs opened with "How to
  kids shoes" and "How to school shoes". The template assumed a verb
  phrase that the labeller does not produce. Fixed in the final review
  wave: the heading is now `{topic}: problems and fixes` ("H1: kids
  shoes: problems and fixes").
- The problem-based sources are US podiatry and physio sites; the
  answers draw on foot-health content, not retailers. That is the
  evidence, and the brief reports it as found.

## 5. Where the cluster recommendations land

`generate()` returned 76 candidates: 56 `pursue_citation_source`, 14
`create_content` (one per gap cluster, none per prompt since every
prompt is labelled) and 6 `sample_more`. The `create_content` ranks
overall:

| Rank | Priority | Reach | Pressure | Cluster |
|---|---|---|---|---|
| 10 | 0.0400 | 0.100 | 1.000 | comparison: kids shoe brands |
| 11 | 0.0400 | 0.100 | 1.000 | recommendation: sports shoes |
| 15 | 0.0360 | 0.100 | 0.900 | recommendation: school shoes |
| 21 | 0.0320 | 0.100 | 0.800 | recommendation: kids shoes |
| 34-40 | 0.0200 | 0.050-0.060 | 0.833-1.000 | the six other single-prompt gap clusters, and informational: kids shoe brands |
| 65 | 0.0080 | 0.050 | 0.400 | problem-based: kids shoes |
| 73 | 0.0040 | 0.050 | 0.200 | problem-based: school shoes |
| 74 | 0.0000 | 0.050 | 0.000 | recommendation: toddler shoes |

Nine citation sources outrank the best content gap (youtube.com leads at
0.1080). Content's feasibility is 0.4 against citations' 0.3, but a
source's reach spreads over many prompts while a cluster's reach is its
own absent answers over 100, at most 0.100 here. The two-prompt clusters
double the reach of a single prompt and so rank first among content, as
intended. The two problem-based clusters rank low because few of their
absent answers name a rival (pressure 0.400 and 0.200), and toddler
shoes, where none does, has pressure 0 and so priority 0.0, ranking
74th of 76.

`top_by_type` (k=3), which the Overview shortlist uses, gives:

```
pursue_citation_source 0.108 youtube.com
create_content 0.04 cluster:comparison:kids shoe brands
sample_more 0.04 28e90862-10bb-4272-8f4d-08da2b2f84c2
```

So the best content gap makes the shortlist at second place, where the
overall ranking has it tenth. At k=10 the remaining seven places are all
citation sources.

**What the cluster rule replaced.** The per-prompt rule, applied to all
20 prompts as if unlabelled (the `_content` query and logic without the
label filter, read-only), fires on 18 prompts: every prompt except the
brand's two named prompts. The cluster rule gives 14 recommendations
covering all 18. Neither rule asks for a rival in an absent answer: the
cluster rule first did, which dropped "best shoes for toddlers learning
to walk" (`not_retrieved` 5/5, no rival named), and the user decided
after review to drop that condition so the two rules agree. Net: 18
per-prompt recommendations became 14 cluster recommendations, 4 fewer;
four two-prompt clusters each merged two.

Pooling can move a prompt either way. It can drop a prompt's gap: a
prompt 3/5 absent pooled with one 0/5 absent gives 3/10, under half, so
neither is a gap. It can add one: a brand-named prompt pulled into a gap
cluster becomes a target query of that cluster's brief even when the
brand is present in its own answers (`informational: kids shoe brands`,
section 3). The toddler-shoes recommendation keeps the priority the old
rule gave it: with no rival in any absent answer its pressure is 0, so
its priority is 0.0 under both rules.

## 6. Label quality

- **Topics are too fine for 20 prompts.** 15 clusters from 20 prompts,
  10 of them single-prompt. "kids shoes", "kids sneakers" and "kids shoe
  brands" overlap, and "kids shoes" appears under four intents. At this
  size, intent does most of the splitting.
- **Some topics are too coarse in the other direction.** "kids shoes"
  covers flat feet (problem-based), Crocs for everyday use
  (informational) and durable shoes under 1500 rupees (commercial); only
  the intent keeps them apart.
- **Brand-named prompts cluster with generic ones.** "Is
  BSOAgentTestBrand a good brand for kids shoes?" shares
  `informational: kids shoe brands` with a generic prompt, and a guide on
  kids shoe brands is a poor target for a review query. The labeller has
  no notion of branded vs generic.
- **The intents read as plausible.** Each of the 20 intent labels fits the
  prompt's wording; "top rated kids shoe brands on Amazon India" as
  recommendation rather than commercial is arguable either way.

## 7. Deferred, by decision

- **URL optimizer.** The other half of F11 (optimising an existing page
  for a cluster) is not built.
- **Embedding merging.** Clusters are exact `(intent, topic)` matches.
  The 20 embeddings now exist but are not used to merge near-duplicate
  topics such as "kids shoes" and "kids sneakers".
- **Relabelling.** A label is written once; nothing relabels when the
  prompt set or the labeller changes. The labels above stay until a
  prompt is edited.
- **Per-engine cluster metrics.** Clusters pool all engines under the
  filters; Run 1 has one engine.
- **Stored clusters.** Clusters and briefs are computed on read; nothing
  is stored beyond the recommendation that `refresh()` would write.
- **Alerts.** Nothing alerts when a cluster becomes or stops being a gap.
- **Fixed later: decided cluster recommendations.** Prompts that join a
  cluster after its recommendation was accepted or dismissed now get
  their own recommendation, keyed `cluster:<intent>:<topic>:+<hash>`,
  when they alone are a gap; prompts under a decided recommendation are
  never raised again, and an accepted task keeps its prompt ids. A
  prompt whose per-prompt recommendation was dismissed still reappears
  as a target query of its cluster once labelled. No live rerun: no
  recommendation is decided in Run 1, so its output is unchanged.
- **Query count (fixed later).** `clusters()` now runs 6 statements
  (was 8) regardless of the number of clusters; brief target queries are
  capped at 20 with `prompts_total`, and a cluster recommendation stores
  the brief's evidence once.

## 8. Spend

| | Micros | USD |
|---|---|---|
| Total before this task | 9,276,208 | $9.2762 |
| `label_prompts` job (1 label call, 1 embedding call) | 2,238 | $0.0022 |
| **Total after** | **9,278,446** | **$9.2784** |

Of the $15 cap, within the task's approved $0.01. The total is the
spend guard's own sum (`spend.ledger_micros()` plus
`spend.db_micros(spend_since)`): the ledger stayed at 6,858,204 and the
database part went from 2,418,004 to 2,420,242.
