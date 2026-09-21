# Slice 6 findings: recommendations, tasks, measured impact

Date: 2026-09-21. Branch `slice6-recommendations-and-tasks`. Sources: a live
`POST /v1/brands/{id}/recommendations/generate` against the dev database
(`bsi`) for "Run 1" (brand `BSOAgentTestBrand`, 80 observations) and "Slice4
check" (the only org with suggested competitors), one recommendation walked
through accept -> in_progress -> done -> a backdated impact window, and a
direct read of the dev database. Fresh API keys were minted owner-side for
both orgs, the same way `tests/conftest.py`'s `make_org` does. Every
recommendation and task row this task created was deleted afterward; nothing
else was touched.

**Correction (2026-09-21, after review):** the numbers below were first
measured with the `recommendation` table not fully empty — an earlier
verification pass had already **accepted** the citation recommendation for
youtube.com and a `sample_more` recommendation, and **dismissed** the
citation recommendation for adidas.com. `generate()`'s upsert deliberately
never resurrects an accepted or dismissed row (decision-safety, by design),
so those three were correctly absent from the *open* list that first
measurement recorded — but that made the count and the top three wrong as a
description of what the rules currently find. This is itself a real
property an operator will meet: **re-running generate after some
recommendations have been acted on shows only what remains open, so its
count understates what the rules actually produce.** The numbers below are
from a second run against a table restored to empty (0 rows in both
`recommendation` and `task`, confirmed before generating), which is what
"what the rules produce" has to mean when it's stated as a fact about the
rules rather than about the table's current decision state.

## 1. What `generate` produced on real data

"Run 1", after the citation fix (commit `c6fb701`):

| Type | Count |
|---|---|
| `pursue_citation_source` | 72 |
| `create_content` | 18 |
| `sample_more` | 7 |
| `add_competitor` | 0 (expected -- no suggested competitors on this org) |

(`Counter(x['type'] for x in generate_response)` against the empty table.)

**Re-measured after the reach change (final review, I1).** Reach was first
counted in prompts for citations (prompts touched / 20 active) but as one
prompt for content and sampling (1/20), so the three types were not in one
unit. It is now counted in answers for every type except `add_competitor`:
the evidence's answers (citation, content) or the prompt's n (sample_more)
over the brand's done answers on active prompts - 80 on "Run 1". The rules
that fire did not change, so the counts above are the same; every priority
did. Measured from an empty `recommendation` table (0 rows confirmed before
generating), `POST .../generate` then `GET .../recommendations`, which
returned the same list in the same order.

Top of the list (list endpoint order):

| # | Type | Subject | Reach | Pressure | Feasibility | Priority |
|---|---|---|---|---|---|---|
| 1 | citation | youtube.com | 0.3625 (29/80) | 0.9655 | 0.3 | **0.105** |
| 2 | citation | starkidz.co.in | 0.225 (18/80) | 1.0 | 0.3 | **0.0675** |
| 3 | citation | forbes.com | 0.275 (22/80) | 0.7727 | 0.3 | **0.0638** |
| 4 | citation | wearetto.com | 0.2125 (17/80) | 1.0 | 0.3 | **0.0638** |

forbes.com and wearetto.com tie at 0.0638, exactly at the overview's
top-three boundary. Ties now list in `generate()`'s order, `(type,
subject_key)`, so forbes.com is third every time; before the review's
tie-order fix the list endpoint broke ties by UUID, and which of the two
the overview showed was arbitrary (fixed per stored row, since the upsert
keeps each row's id - a reload did not reshuffle it, but nothing about the
choice was meaningful). Behind them adidas.com, facebook.com, myntra.com,
walkaroo.in and zappos.com tie at 0.0488 (13 answers each).

**The reach change does not surface a content gap on this data.** The
highest `create_content` recommendation ("best sports shoes for girls aged
8 to 12", brand absent from 4 of 4 answers) has reach 4/80 = 0.05,
pressure 1.0, feasibility 0.4, priority **0.02**, and ranks **29th of 97**
(`create_content` ranks: 29-41, 50, 51, 75, 86, 94). 21 citation sources
and 7 `sample_more` recommendations sit above it. The reason is structural,
not a weight: "Run 1" samples every prompt 4 times, so a content gap can
never cover more than 4 answers, while a citation source pools answers
across prompts. With pressure 1.0 on both, a citation outranks the best
content gap once it is cited in 6 or more brand-absent answers (0.3 x k/80
> 0.4 x 4/80 when k > 5.33). One unit made the types comparable; it did
not make a single prompt as wide as a domain cited across many. Before the
change the content reach was 1/20 = 0.05 too - the same number, because 4
samples per prompt over 80 answers is 1/20 - while citation reach fell
(youtube.com from 0.65 to 0.3625), so the gap narrowed but did not close.
Whether a content gap should outrank a wide citation is a weighting
decision; it has not been tuned here to make the list look better.

Three highest-cited citation domains: **youtube.com** (29 brand-absent
answers), **forbes.com** (22), **starkidz.co.in** (18).
(`len(x['evidence']['observation_ids'])` per citation candidate, sorted
descending.)

"Slice4 check" produced **9 `add_competitor`** recommendations and nothing
else (no citation/content/sampling data exists for that org). All 9 sit at
priority 0.6-0.9, because `add_competitor`'s reach is fixed at 1.0 (PRD: it
changes every rival rate) and feasibility is the highest of the four types
(0.9). That figure is from the first measurement: the reach change does not
touch `add_competitor`, whose reach stays 1.0, so it holds by construction.
With every other reach now a share of answers, a confirmation outranks any
other recommendation on "Run 1" by a factor of 6 or more. Keeping 1.0 is
**the user's call**, flagged rather than changed. See §7.

## 2. The citation rule's rival-domain fix, and its honest residue

Before `c6fb701`, "Run 1" produced 101 recommendations, 76 of them citation
sources -- including domains an active competitor owns outright, seen live
as "Earn coverage on adidas.com." The fix loads each active competitor's
declared `domains` once per `generate()` call and skips any cited domain
matching them via `matching.is_owned`, the same helper `extraction` uses for
`is_brand_owned`.

After the fix, "Run 1" has **72** citation recommendations. None of the 5
active competitors' *declared* domains (bata.com, campusshoes.com,
skechers.in, crocs.in, adidas.co.in) appear anywhere in those 72.

The fix is deliberately narrow: it only catches domains a rival has
declared, never a name-based guess at corporate ownership. **The residue is
real, expected, and now visible at the very top of the list (§1)**:
`adidas.com` is cited in **13** brand-absent answers — the same count as
zappos.com and facebook.com — and is declared as active only under
`adidas.co.in`, so `adidas.com` passes the filter untouched and lands at
priority 0.0488, fifth on the list, tied with facebook.com, myntra.com,
walkaroo.in and zappos.com (§1).
`skechers.com` (6 citing answers)
and `skechers.com.au` (3) are the same story: Skechers is declared active
with only `skechers.in`. The rule cannot know adidas.com or skechers.com is
the same company without being told — correctly, per the ruling, since
guessing from the name risks silently hiding an unrelated publisher that
happens to share it. `puma.com` (11 citing answers) also appears, but Puma
is not a competitor on this brand at all (no competitor record, active or
otherwise) on "Run 1" — that is not residue from the fix, it is just an
untracked domain.

(All counts above and the full 72-domain list are from
`{x['subject_key']: len(x['evidence']['observation_ids']) for x in cites}`
against the clean-table generation.)

## 3. The citation threshold, and what raising it would cost

`MIN_CITING_ANSWERS = 3` is the spec's chosen value, kept as configured; the
controller ruled to report it rather than change it. At 80 observations it
is permissive -- recomputed directly from the live "Run 1" generation
against the clean table, by
`sum(1 for v in counts.values() if v >= threshold)` over the same
`{domain: citing-answer count}` mapping used in §2:

| Threshold | Citation recommendations remaining |
|---|---|
| 3 (current) | 72 |
| 5 | 36 |
| 10 | 13 |

Raising the threshold to 5 would cut the citation list roughly in half;
raising it to 10 would cut it to 13 -- closer to a shortlist an operator
could act on in a week, at the cost of dropping every domain cited in 4-9
brand-absent answers. The 13 that survive at 10 are: `youtube.com` (29),
`forbes.com` (22), `starkidz.co.in` (18), `wearetto.com` (17),
`adidas.com`, `facebook.com`, `myntra.com`, `reddit.com`, `walkaroo.in`,
`zappos.com` (13 each), `firstcry.com`, `puma.com` (11 each), and
`pediped.com` (10) — from the same domain -> count listing in §2. Several
of those, and several dropped at 10 (`flipkart.com` at 9, `tatacliq.com`
at 8, `decathlon.in` at 5), are large retail/marketplace or platform sites
plausibly worth pursuing regardless of citation count. This is exactly the
judgment call the controller deferred to the user: 3 is right for *seeing
everything the data supports*, 10 is right for *acting on the top handful
without re-prioritizing weekly*.

## 4. The loop end to end, and why its first honest answer is "insufficient data"

Walked live on "Run 1": accepted the highest-priority `create_content`
recommendation ("Publish content that answers 'best light-up sneakers for
kids'"), which created task `296c05d5`; `PATCH .../tasks/{id}` moved it
`open -> in_progress -> done`, which stamped `done_at` and copied
`impact_window_days` (14) onto the task at that moment, exactly as the
design intends (a later settings change cannot move an open window).
`done_at` was then backdated 15 days with a direct `UPDATE` (no clock
freezing, the tests' method), and
`uv run python -c "from bsi_workers.worker import close_due_impact_windows as f; print(f())"`
returned `1` -- one window closed.

**Impact label: `insufficient_data`.** Every one of "Run 1"'s 80
observations was recorded well after the fabricated 15-days-ago `done_at`
(the whole dataset is a single batch from this slice's build), so the
"before" window (`done_at - window_days` to `done_at`) contains zero
observations for the task's one affected prompt, while the "after" window
picked up all 3. `brand_deltas` correctly refuses to call that a comparison
and returns `insufficient_data` rather than fabricating a before-rate of
zero. This is the honest answer, not a bug: the dev database has no data
older than the task, so nothing about before/after can be said yet --
exactly the case the design spec called out in advance ("likely
'insufficient data', which is itself the correct honest output"). The Tasks
page (`/b/{id}/tasks`, fetched with a minted "Run 1" key) renders the label
and the "association, not a cause" caption next to it -- confirmed by direct
HTML fetch (the string appeared twice, once in the server-rendered HTML and
once in the RSC payload Next also streams, as the task instructions
anticipated).

## 5. Weights as set, and that they are judgment calls

`FEASIBILITY` (`packages/core/bsi_core/recommend.py`): `add_competitor` 0.9,
`sample_more` 1.0, `create_content` 0.4, `pursue_citation_source` 0.3 -- an
ordering the code's own comment justifies ("confirming a competitor or
scheduling samples takes minutes; content takes weeks; outreach takes weeks
and depends on someone else"), not a measured cost. `MIN_CITING_ANSWERS = 3`,
`MIN_COMPETITOR_EVIDENCE = 2`, `SAMPLE_MORE_WITHIN = 10` are similarly
chosen, not derived. None of these have been tuned against outcomes -- there
are no outcomes yet, per §4 -- so they should be read as reasonable starting
points awaiting real use, not calibrated weights. §1 and §3 above are the
concrete evidence for where that shows up first: `add_competitor`'s
feasibility plus its fixed reach of 1.0 means it will tend to sit at the top
of any list that has one at all, and the citation threshold's permissiveness
is a direct, visible consequence of `MIN_CITING_ANSWERS`'s value.

## 6. A concurrency defect found and fixed during review

Code review of the accept/dismiss endpoints found a Critical: two
overlapping accepts on one recommendation (or an accept racing a dismiss)
both read `status='open'` under READ COMMITTED and both proceeded, so the
second commit hit the `task.recommendation_id` unique constraint and
surfaced as an opaque 500 instead of a clean conflict response. Commit
`60abab1` fixes it by re-reading the recommendation row with
`SELECT ... FOR UPDATE` after the initial 404 check, so a racing request
waits for the first transaction to commit and then sees the now-`accepted`
or `dismissed` status; a new deterministic integration test drives two
overlapping requests and asserts the loser gets `409`, not `500`.

The final review found a second race of the same family: `generate`
deleted stale open recommendations one by one by id after an unlocked
read, so a dismiss that committed in between was deleted anyway (the
user's decision and reason lost, and later evidence could bring the row
back as open), and a racing accept made `generate` 500 on the task's
foreign key. It is now one `DELETE` with `status = 'open'` in its WHERE,
which Postgres re-checks after the lock wait; a deterministic test holds
the row locked mid-dismiss and asserts it survives, dismissed, reason
intact.

## 7. Known gaps

Carried from the design's explicit out-of-scope list, plus what this run
surfaced:

1. **The four audit-dependent recommendation types** (crawl, entity, SERP,
   content-gap analysis from the PRD's F12) are not built -- the audits they
   need don't exist yet.
2. **LLM drafting and the critic loop.** Recommendation text is templated,
   not generated; a unit test scans every template for forbidden words
   ("guarantee", "will rank", "ensure", "boost"...) instead of relying on a
   critic model to catch overclaiming.
3. **No weekly automatic regeneration.** `generate()` only runs when called;
   the design notes this as "one line in `tick()` later."
4. **No users or assignment.** `task.owner` is free text; there is no user
   model to assign a task to, and nothing enforces who can accept, dismiss,
   or complete a task.
5. **No notifications.** Nothing tells an operator a recommendation was
   generated, a task's impact window closed, or a label landed.
6. **No board view.** Tasks are a flat list (`/b/{id}/tasks`); there's no
   kanban-style open/in-progress/done view.
7. **No snooze.** A recommendation is only `open`, `accepted`, or
   `dismissed` -- there's no way to defer one without dismissing it outright
   (which requires a reason and is meant to be closer to "no").
8. **`add_competitor`'s fixed reach of 1.0 will put confirmations at the
   top** whenever any exist: all 9 on "Slice4 check" landed at 0.6-0.9,
   against 0.105 for the best recommendation on "Run 1" (§1). Now that
   every other reach is a share of answers, 1.0 is not in the same unit as
   anything else. Whether to keep it is **the user's call**; it was
   flagged, not changed.
9. **Confirming a competitor and taking samples have no measured impact.**
   Mention rate is the only impact metric and neither can move it, so their
   tasks are stamped `measures_impact = false` at accept and get no impact
   window; the tasks page says so. Measuring them (share of voice, whether
   the prompt separates) is a later slice.
