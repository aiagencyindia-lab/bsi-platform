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

## 1. What `generate` produced on real data

"Run 1", after the citation fix (commit `c6fb701`):

| Type | Count |
|---|---|
| `pursue_citation_source` | 70 |
| `create_content` | 18 |
| `sample_more` | 6 |
| `add_competitor` | 0 (expected -- no suggested competitors on this org) |

Top three by priority (reach x pressure x feasibility):

1. `pursue_citation_source` **zappos.com** -- reach 0.35, pressure 1.0,
   feasibility 0.3, priority **0.105**
2. `pursue_citation_source` **wearetto.com** -- reach 0.35, pressure 1.0,
   feasibility 0.3, priority **0.105**
3. `pursue_citation_source` **forbes.com** -- reach 0.4, pressure 0.773,
   feasibility 0.3, priority **0.0927**

Three highest-cited citation domains: **forbes.com** (22 brand-absent
answers), **starkidz.co.in** (18), **wearetto.com** (17).

Does the ranking read as sensible? Partly. Citation sources dominate the top
of the list because pressure is defined as "share of answers naming an
active rival," which citation rows can hit at 1.0 easily (a domain cited
only in brand-absent answers that happen to name a rival), while
`create_content`'s pressure is capped by how many of the prompt's own
answers are absent. A citation source cited in as few as 3 answers
(`MIN_CITING_ANSWERS`) can outrank a `create_content` fix for a prompt where
the brand is absent from every single answer, because reach is defined
per-type and not comparably: a citation's reach is the fraction of active
*prompts* its citing answers touch (0.35-0.4 here), while one prompt's
reach is 1/20 = 0.05 regardless of how badly that prompt is failing. That is
an artifact of the priority formula, not obviously wrong on its own terms
(citation problems genuinely span more prompts; content problems are
concentrated but severe) but worth flagging before an operator trusts the
ranking blindly.

"Slice4 check" produced **9 `add_competitor`** recommendations and nothing
else (no citation/content/sampling data exists for that org). All 9 sit at
priority 0.6-0.9, because `add_competitor`'s reach is fixed at 1.0 (PRD: it
changes every rival rate) and feasibility is the highest of the four types
(0.9): confirming a competitor is cheap and touches everything, so it will
tend to sit at the top of any list that has one. See §7.

## 2. The citation rule's rival-domain fix, and its honest residue

Before `c6fb701`, "Run 1" produced 101 recommendations, 76 of them citation
sources -- including domains an active competitor owns outright, seen live
as "Earn coverage on adidas.com." The fix loads each active competitor's
declared `domains` once per `generate()` call and skips any cited domain
matching them via `matching.is_owned`, the same helper `extraction` uses for
`is_brand_owned`.

After the fix, "Run 1" has **70** citation recommendations. None of the 5
active competitors' *declared* domains (bata.com, campusshoes.com,
skechers.in, crocs.in, adidas.co.in) appear anywhere in those 70.

The fix is deliberately narrow: it only catches domains a rival has
declared, never a name-based guess at corporate ownership. **The residue is
real and expected**: `skechers.com` and `skechers.com.au` both still appear
in the 70, because Skechers is declared active with only `skechers.in`. The
rule cannot know skechers.com is the same company without being told --
correctly, per the ruling, since guessing from the name risks silently
hiding an unrelated publisher that happens to share it. `puma.com` also
appears, but Puma is not a competitor on this brand at all (no competitor
record, active or otherwise) on "Run 1" -- that is not residue from the fix,
it is just an untracked domain.

## 3. The citation threshold, and what raising it would cost

`MIN_CITING_ANSWERS = 3` is the spec's chosen value, kept as configured; the
controller ruled to report it rather than change it. At 80 observations it
is permissive -- recomputed directly from the live "Run 1" generation:

| Threshold | Citation recommendations remaining |
|---|---|
| 3 (current) | 70 |
| 5 | 34 |
| 10 | 11 |

Raising the threshold to 5 would cut the citation list by roughly half;
raising it to 10 would cut it to 11 -- closer to a shortlist an operator
could act on in a week, at the cost of dropping domains cited in 4-9
brand-absent answers, several of which (myntra.com at 13, decathlon.in,
flipkart.com) are large retail/marketplace sites plausibly worth pursuing
regardless of citation count. This is exactly the judgment call the
controller deferred to the user: 3 is right for *seeing everything the data
supports*, 10 is right for *acting on the top handful without
re-prioritizing weekly*.

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
8. **`add_competitor`'s fixed reach of 1.0 will tend to put confirmations at
   the top** whenever any exist, as shown directly in §1: all 9 on "Slice4
   check" landed at 0.6-0.9, well above anything a citation or content rule
   produced on "Run 1". This is a property of the priority formula, not a
   bug, but it means an operator with both suggested competitors and
   citation/content gaps open at once will see competitor confirmations
   crowd the top regardless of how urgent the actual content or citation
   gaps are.
