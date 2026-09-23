# Slice 9 findings: competitor intelligence

Date: 2026-09-23. Branch `slice9-competitor-intelligence`. Sources:
read-only calls of `bsi_core.competitors.entity_metrics()`,
`entity_deltas()` and `visibility_changes()` in a tenant session on the
dev database `bsi` (migration 0013), for the Run 1 brand, plus a few
read-only `psql` queries to explain what they returned. The three
functions only SELECT. No model call, no spend, nothing written.
Afterwards the dev tables `recommendation`, `task` and `site_audit` held
`0|0|0` rows.

## 1. What was measured, and how

Run 1 is 100 done answers from one engine over 20 prompts, requested
between 2026-09-19 09:17 and 2026-09-22 18:58 UTC. The brand is
BSOAgentTestBrand with five active competitors: Adidas (`adidas.co.in`),
Bata (`bata.com`), Campus (`campusshoes.com`), Crocs (`crocs.in`) and
Skechers (`skechers.in`). The brand has no `domain` rows.

Run from the repo root with the dev `.env` loaded
(`set -a && source .env && set +a && uv run python live_slice9.py`); the
script is a scratch file, not committed. Its core:

```python
ORG = uuid.UUID("de2e7f7b-3aab-45f9-843b-48bb54c1710e")
BRAND = uuid.UUID("34db213a-f484-4991-a969-c52cfa5e1c10")
now = datetime.now(UTC)
with tenant_session(ORG) as s:
    for e in entity_metrics(s, BRAND, Filters()):
        ...  # every rate as value (n, Wilson low-high), sentiment, citing domains
    for days in (7, 14, 30):
        d = entity_deltas(s, BRAND, Filters(), days, now)
        ...  # comparable, reason, window n per entity, mention_rate delta
    c = visibility_changes(s, BRAND, Filters(), 14, now)
    print(c["comparable"], c["reason"], c["prompts"], len(c["changes"]))
```

`now` was 2026-09-23 14:58:33 UTC.

## 2. The Run 1 leaderboard

Rates are value (n, 95% Wilson interval). Mention rate is over all 100
answers, coverage over the 20 prompts, SOV over the 174 mentions of all
six entities. Sentiment index is positive rate minus negative rate among
the entity's mentions.

| Entity | Mention rate | SOV | Coverage | Sentiment index | Avg position |
|---|---|---|---|---|---|
| Adidas | 0.470 (100, 0.375-0.567) | 0.270 (174, 0.210-0.341) | 0.700 (20, 0.481-0.855) | 0.489 (n=47) | 1.87 |
| Skechers | 0.410 (100, 0.319-0.508) | 0.236 (174, 0.179-0.304) | 0.600 (20, 0.387-0.781) | 0.561 (n=41) | 1.83 |
| Campus | 0.320 (100, 0.237-0.417) | 0.184 (174, 0.133-0.248) | 0.400 (20, 0.219-0.613) | 0.563 (n=32) | 2.09 |
| Bata | 0.260 (100, 0.184-0.354) | 0.149 (174, 0.104-0.210) | 0.300 (20, 0.145-0.519) | 0.577 (n=26) | 1.62 |
| Crocs | 0.190 (100, 0.125-0.278) | 0.109 (174, 0.071-0.164) | 0.400 (20, 0.219-0.613) | 0.158 (n=19) | 1.89 |
| BSOAgentTestBrand (you) | 0.090 (100, 0.048-0.162) | 0.052 (174, 0.027-0.095) | 0.100 (20, 0.028-0.301) | -0.111 (n=9) | 1.00 |

Recommendation and citation rates (n=100 each):

| Entity | Recommendation rate | Citation rate |
|---|---|---|
| Adidas | 0.110 (0.063-0.186) | 0.130 (0.078-0.210) |
| Skechers | 0.090 (0.048-0.162) | 0.040 (0.016-0.098) |
| Campus | 0.070 (0.034-0.137) | 0.160 (0.101-0.244) |
| Bata | 0.050 (0.022-0.112) | 0.130 (0.078-0.210) |
| Crocs | 0.030 (0.010-0.085) | 0.000 (0.000-0.037) |
| BSOAgentTestBrand | 0.000 (0.000-0.037) | 0.000 (0.000-0.037) |

Top five citing domains (answers naming the entity that cite the domain,
and the owner tag):

| Entity | Citing domains |
|---|---|
| Adidas | youtube.com 25, wearetto.com 18, starkidz.co.in 17, adidas.com 15 (third_party), forbes.com 14 |
| Skechers | youtube.com 21, starkidz.co.in 15, wearetto.com 15, zappos.com 13, facebook.com 12 |
| Campus | starkidz.co.in 20, wearetto.com 17, youtube.com 17, campusshoes.com 16 (rival), myntra.com 16 |
| Bata | youtube.com 17, walkaroo.in 14, bata.com 13 (rival), myntra.com 13, starkidz.co.in 13 |
| Crocs | forbes.com 6, magicalshoes24.com 6, thebudslife.com 6, wearetto.com 6, anklefootmd.com 5 |
| BSOAgentTestBrand | trustpilot.com 6, youtube.com 4, walmart.com 3, backcountry.com 1, firstwalkers.com.au 1 |

Every domain not marked is `third_party`.

**Reading it.**
- Adidas leads Skechers, but their mention-rate intervals overlap
  (0.375-0.567 and 0.319-0.508); on 100 answers the order of the top two
  is not settled. Every rival but Crocs is clearly ahead of the brand:
  the brand's upper bound (0.162) is below each of their lower bounds,
  but above Crocs's (0.125).
- The owner tag follows declared domains only. Adidas declares
  `adidas.co.in`, so `adidas.com` (15 answers) is tagged `third_party`,
  and Adidas's 0.130 citation rate counts only `adidas.co.in` hits. The
  same holds for Skechers (`skechers.in`) and Crocs (`crocs.in`): none of
  their own sites made their top five. Declaring `adidas.com` would move
  both numbers. This is data, not a bug, but an operator will read it as
  one.
- The brand's citation rate is 0 because the brand has no `domain` rows,
  so no citation can match it.
- Crocs is the one rival with a low sentiment index (0.158: 7 of 19
  positive, 4 of 19 negative). The brand's -0.111 is 1 negative mention
  of 9. Sentiment is model-judged (section 5).

## 3. Deltas and the change feed

**Deltas.** `entity_deltas` compares `[now - days, now)` with the `days`
before it. For 7, 14 and 30 days:

```
deltas days=7: comparable=True reason=None
  before: 2026-09-09..2026-09-16 ... every entity n=0
  after: 2026-09-16..2026-09-23 ... every entity n=100
  delta mention_rate <every entity>: None insufficient data
```

The 14- and 30-day runs print the same shape. All 100 answers fall in the
after window, so every before rate is empty, `comparable` is True (one
pipeline version), and every delta is `None` with the label
`insufficient data`. The leaderboard shows no arrows, as intended.

**The change feed.**

```
changes days=14: comparable=True reason=fewer than 10 prompts with answers in both windows prompts=0 changes=0
```

`prompts` counts prompts with done answers in both windows. Run 1 is one
burst of sampling inside the last four days, so no prompt has a before
answer, `prompts` is 0, and the count rule (at least 10 shared prompts)
stops the feed before any competitor is tested. The two windows are
`[now - 28d, now - 14d)` and `[now - 14d, now)`, so the feed stays empty
until a second burst lands and the page is viewed while the first burst
is 14-28 days old (the before window) and the second is within the last
14 days.

**The feed window is fixed.** Since `fed7141`, the web Competitors tab
always asks for the change feed with `days=14` and no `date_from`; the
days filter sets only the leaderboard deltas. The 14-day call above is
therefore exactly what the page shows for Run 1.

## 4. What the fixture proves that Run 1 cannot

`tests/integration/test_competitors.py` builds 12 prompts with 10 answers
per prompt in each window (n=10, so a one-answer change is a 0.1 shift),
and three competitors. The pooled numbers below were computed with
`metrics.delta(rate(...), rate(...))`, not copied from the fixture.

| Case | Per prompt | Prompts moved | Pooled before -> after | Pooled delta (95% CI) | Label | In feed? |
|---|---|---|---|---|---|---|
| A | 0/10 -> 10/10 | 11 | 0/110 -> 110/110 | 1.0 (0.9523, 1.0) | increase | yes, `up` |
| B | 0/10 -> 10/10 | 9 | not tested | - | - | no: count rule |
| C | 4/10 -> 5/10 | 10 | 40/100 -> 50/100 | 0.1 (-0.0373, 0.2321) | no significant change | no: pooled gate |
| A reversed | 10/10 -> 0/10 | 11 | 110/110 -> 0/110 | -1.0 (-1.0, -0.9523) | decrease | yes, `down` |

- **C is the case the pooled gate exists for.** It passes the count rule
  exactly: 10 prompts, each moved by exactly `MIN_SHIFT` (5/10 - 4/10 is
  0.0999... in floats; `_shift` rounds so it counts). Pooled, 40/100 ->
  50/100 has an interval that crosses 0, so it is dropped.
- The margin is thin. The fixture's comment notes that 1/10 -> 2/10 on
  the same 10 prompts would not do as a negative case: pooled 10/100 ->
  20/100 gives 0.1 (0.0001, 0.1995), labelled `increase`. The same
  one-answer shift is significant near 0 and not near 0.5, because the
  interval is widest at 0.5.
- A's entry carries its evidence: 11 prompt rows, the engine, `new.com`
  as the one newly cited domain (`old.com` was cited before), and 20
  observation ids, newest first. A newly cited domain is one cited in an
  after-window answer that names the competitor on a moved prompt, and
  not cited in any before-window answer under the same filters. The reversed case has no after-window
  answer naming A, so its evidence lists are empty.
- Other tests cover the empty case (`prompts=0` with the Run 1 reason),
  a prompt filter that leaves 5 shared prompts, and mixed pipeline
  versions (`comparable=False` with a reason naming them).

**Coverage.** `competitors.py` is not under the coverage gate (only
`metrics.py` is). Measured with
`uv run pytest -q tests/integration/test_competitors.py
tests/integration/test_api_competitors.py --cov=bsi_core.competitors
--cov-report=term`:

```
packages/core/bsi_core/competitors.py     127      0   100%
18 passed, 2 warnings
```

## 5. Deferred, by decision

- **Undeclared rival domains.** Ownership follows declared domains
  only: `adidas.com` counts as `third_party` until it is declared.
  Suggesting or auto-adding a rival's other domains is not built.
- **Rival crawl.** The weekly crawl of rival domains (sitemap diff, new
  structured data) is not built. The feed reads answers only.
- **Stored entries and alerts.** The feed is computed on read; nothing
  is stored and nothing alerts (F15).
- **New cited pages.** "Newly cited" is domain-level. Grounded answers
  cite Vertex redirect URLs, so page-level would first need the redirects
  resolved.
- **Competitor archive.** Deleting a competitor stays a hard delete;
  orphaned mentions drop out through the active-competitor join.
- **Sentiment is model-judged and unlabelled.** The index is positive
  minus negative as the extractor judged them; no labelled set checks it.
- **Correlated windows.** `delta()` assumes independent samples. The two
  windows share prompts, so the pooled test is somewhat optimistic; the
  count rule in front of it limits how often that matters.
- **Query cost.** Queries run per entity: `entity_metrics` is 2 per
  entity plus about 5 fixed, `entity_deltas` runs it twice plus 2, and
  `visibility_changes` about 8 plus 3 per entry. A Competitors page load
  for a brand with 25 competitors is about 181 + 3E queries (E = feed
  entries), each scanning the brand's done answers in the window. Fine at
  current sizes. Upgrade path: one grouped query per window (`GROUP BY
  mn.entity_id`, and an unnest of (entity, host) pairs for citations).

## 6. Spend

Unchanged: $9.2762 of the $15 cap. This run made no model calls.
