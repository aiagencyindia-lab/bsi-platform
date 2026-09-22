# Slice 6 design: recommendations to measured impact

## Context

Slices 1-5 measure visibility and show it; nothing yet tells the operator
what to do about it or whether doing it worked. The PRD's next slice is F12
(recommendation engine) + F13 (action management). Decisions from
brainstorming:

- **Cut:** a thin loop end to end — recommendation → accept/dismiss → task →
  done → measured impact — rather than either half done deeply.
- **Text:** templates only. No model calls, no spend, and a forbidden claim
  ("will rank", "guaranteed") is preventable by test instead of by a critic
  model. LLM drafting + the critic loop is a later slice on top.
- Only the four recommendation types the existing data supports. The other
  four in F12 need audits (crawl, entity, SERP, content gap) that don't exist.

## The loop

```
rules read observations ─> recommendation (evidence linked)
   ├─ dismiss (reason required)
   └─ accept ─> task: open → in_progress → done
                            done opens a window on the affected prompts
                            the worker closes it after window_days
                            └─> impact: improved | no_change | declined |
                                        insufficient_data | not_comparable
```

## Rules — `packages/core/bsi_core/recommend.py` (new; SQL + templates)

| Type | Fires when | Evidence |
|---|---|---|
| `pursue_citation_source` | a non-owned domain is cited in ≥ 3 done answers that omit the brand | observation ids, rivals named there |
| `create_content` | a prompt's dominant `extraction.absence_reason` is `competitor_dominance` or `not_retrieved` | prompt id, its observation ids |
| `add_competitor` | a `competitor.status='suggested'` row has `evidence >= 2` | competitor id |
| `sample_more` | a prompt's `needs_samples - n` is ≤ 10 and it is not yet separated | prompt id, n, needs_samples |

Verified against dev data: forbes.com is cited in 22 brand-absent answers;
absence reasons are 61 `competitor_dominance` / 12 `not_retrieved`; 10
suggested competitors await confirmation.

- `generate(s, brand_id) -> list[Candidate]` is pure over a tenant session.
  Upsert key is `(brand_id, type, subject_key)` so regeneration is idempotent:
  open rows refresh their evidence and priority; accepted and dismissed rows
  are never resurrected.
- **Priority = reach × pressure × feasibility**, each part stored and returned
  so the weights are visible (PRD F12). Reach = share of the brand's
  answers affected, in one unit: the evidence's answers (citation,
  content) or the prompt's n (sample_more), over the brand's done answers
  on active prompts; 1.0 for `add_competitor`, which changes every rival
  rate. *Amended after review:* reach was first counted in prompts, with
  one prompt per content or sampling rec, so a prompt the brand is absent
  from could never outrank a citation spanning two prompts and the
  overview's top three could not surface a content gap. Pressure = what is at stake, per type: the share of the relevant
  answers naming an active rival (citation, content), evidence / 3
  (competitor), or the size of the gap awaiting confirmation, |spread|
  (sample_more - a rival-rate definition would score zero wherever the brand
  is winning). Feasibility = a per-type constant in one dict. Computed in
  `bsi_core` only.
- Templates never promise an outcome. A unit test scans every template's
  output for forbidden words (guarantee, will rank, ensure, boost…).

## Reuse (do not rebuild)

- `metrics.brand_deltas(s, brand_id, Filters(prompt_ids=…), days, to)` already
  compares two windows with Newcombe intervals, labels, and the mixed-
  pipeline-version refusal → impact measurement is one call with the task's
  affected `prompt_ids` and `to = done_at + window_days`.
- `metrics.prompt_metrics` / `samples_to_separate` → the `sample_more` rule.
- `scheduling.due_schedules()` + `worker.run_due_schedules` → the pattern for
  `due_impact_windows()` (SECURITY DEFINER, `system_session`) and a
  `close_due_impact_windows()` call in `main()`'s 60-second loop beside
  `run_due_schedules()`, one window per `try` so one failure never blocks
  the rest.
- `schemas.py` for response models; `deps.child_or_404`; RFC 9457 `Problem`.
- Frontend: `api()`, `format.ts`, `Tile`/`CiBar`, server actions as in the
  label page (no client components), evidence links into existing `/o/{id}`.

## Data — migration `0009`

- `recommendation`: brand_id, type (CHECK from a `REC_TYPES` constant, as
  `INTENTS` does), subject_key, status (`open|accepted|dismissed`),
  dismiss_reason, title, body, evidence JSONB (`prompt_ids`,
  `observation_ids`, extras), reach, pressure, feasibility, priority;
  UNIQUE (brand_id, type, subject_key).
- `task`: brand_id, recommendation_id (nullable FK), title, owner (free text —
  no users exist), due_date, status
  (`open|in_progress|done|impact_measured`), notes, prompt_ids (uuid[]),
  done_at, window_days, impact_label, impact JSONB (the before/after mention
  rates and the delta). Impact labels: improved | no_change | declined |
  insufficient_data | not_comparable - the last because `brand_deltas`
  refuses to compare windows with mixed pipeline versions, and that refusal
  must not be reported as a shortage of data.
- Both tenant tables: `org_id`, ENABLE + FORCE RLS, `tenant` policy, grant to
  `bsi_app`, exactly as `0008`. Both added to `TENANT_TABLES` in
  `tests/integration/test_rls.py` and every id-bearing route to `CASES` in
  `tests/integration/test_isolation.py`.
- `due_impact_windows()` SECURITY DEFINER: tasks with `status='done'` and
  `done_at + window_days <= now()`.
- Setting `impact_window_days: int = 14` in `config.py`, copied onto the task
  at done-time so a later settings change cannot move an open window.

## API (all `/v1`, tenant-scoped, typed via `schemas.py`)

```
POST  /brands/{id}/recommendations/generate     GET /brands/{id}/recommendations?status=
POST  /brands/{id}/recommendations/{rid}/accept   → creates the task
POST  /brands/{id}/recommendations/{rid}/dismiss  {reason}  (reason required → 422)
GET   /brands/{id}/tasks          PATCH /brands/{id}/tasks/{tid}
```

Status transitions are validated server-side (no done → open; `done` stamps
`done_at` + `window_days`; `impact_measured` is set only by the worker).

## UI (`apps/web`)

- `/b/{id}/recommendations`: ranked list, priority parts shown, evidence links
  to `/o/{id}` and the prompt page, Accept / Dismiss-with-reason server
  actions, a Generate button.
- Top 3 open recommendations on the overview page (PRD dashboard row 4).
- `/b/{id}/tasks`: list with status change, owner, due date, notes; once
  measured, the impact label with its delta and interval, captioned
  "association, not causation".
- New "Recommendations" and "Tasks" tabs in `b/[id]/layout.tsx`.

## Out of scope

The four audit-dependent types; LLM drafting and critic; weekly automatic
regeneration (one line in `tick()` later); users/assignment; notifications;
attachments; the board view; snooze.

## Verification

- Backend gate (`bsi_core.metrics` stays 100%) + `npm run gate`; CI green on
  the PR.
- Tests: each rule fires and stays silent on crafted data; idempotent
  regeneration; dismissed rows stay dismissed; forbidden-word scan; illegal
  task transitions → 422; impact closes via backdated `done_at` (owner
  UPDATE, no clock freezing) with each of the four labels; RLS + isolation
  rows for both tables; `tick()` survives a failing window close.
- Live on the dev DB ("Run 1"): generate → expect a forbes.com citation rec,
  `create_content` recs for competitor-dominated prompts, `sample_more` for
  the n=4 prompts needing 7; `add_competitor` can only be seen on the
  "Slice4 check" org, since "Run 1" has no suggested competitors; accept one → task → mark done →
  backdate `done_at` owner-side, as the tests do → run the worker's
  `close_due_impact_windows()` → impact label appears
  (likely "insufficient data", which is itself the correct honest output).
