# Slice 5 design: operator dashboard (`apps/web`)

## Context

Slices 1-4 built measurement, cost control, scheduling and prompt
intelligence, all reachable only through curl and scripts. The next PRD step
is the web dashboard. Decisions from brainstorming:

- **Audience:** the operator (you), not customers. Auth is a pasted API key.
- **Views:** brand overview, prompt table + evidence, ops and spend, judge labelling.
- **Stack:** Next.js 15 (App Router, TypeScript) in `apps/web`, per the PRD, so
  nothing is thrown away later.

The slice should also answer two open questions with data: which prompts
discriminate between brands, and whether the judge bar can be raised (needs
more labels than the current 30 answers / 50 labels).

## Architecture

```
browser ──> Next.js (apps/web, :3000) ──server-side fetch──> FastAPI (:8000) ──> Postgres
             httpOnly cookie holds the API key; the browser never sees it
```

- Server Components fetch the API; no client-side data fetching, so **no CORS
  and no key in the browser**. Client components only for interactions
  (sort, label buttons).
- `/login`: paste key → server action calls `GET /v1/brands` to validate →
  sets an httpOnly, SameSite=Lax cookie. Any API 401 redirects to `/login`.
- Types generated from FastAPI's `/openapi.json` with `openapi-typescript`
  (dev dependency, types only) plus one ~20-line `api()` fetch wrapper.
  Skipped: a generated runtime client; add if the wrapper grows.
- Filters (`engine`, `locale_id`, `date_from`, `date_to`, `days`) live in URL
  search params and pass straight through to the API, which already takes
  the same names (`metrics.py: filters()`).
- **No chart library.** SOV bars and CI range bars are CSS. Sparklines are
  skipped: they need a daily-series endpoint nothing else wants yet.
- Styling: CSS modules + design tokens as CSS variables on `:root`. No
  Tailwind, no component library.
- The frontend never computes a metric. Rates, CIs, deltas and significance
  all come from `bsi_core.metrics`, so UI and API cannot disagree (PRD 6.1).

## Pages

| Route | Shows | API |
|---|---|---|
| `/login` | key form | `GET /brands` |
| `/` | brand list | `GET /brands` |
| `/b/[id]` | tiles: mention, recommendation (tagged *experimental*), citation rate, each with n, 95% CI, 7-day delta; grey "no significant change" when the delta interval spans 0; "not comparable" on mixed pipeline versions; SOV bars vs confirmed competitors; n_failed | `/metrics`, `/deltas`, `/sov` |
| `/b/[id]/prompts` | per-prompt table: intent, topic, n, brand mention rate + CI, top competitor rate, spread; sortable; low-n rows greyed | **new** `/prompts/metrics` |
| `/b/[id]/prompts/[pid]` | that prompt's observations | `GET /observations?prompt_id=` |
| `/o/[id]` | answer text with evidence sentences highlighted, mentions, citations, search queries run, cost | `GET /observations/{id}` (+ `text`) |
| `/ops` | spend today vs daily budget, queue counts by status, recent failures with error, searched-rate, schedules with next run | **new** `/ops`, `GET /brands/{id}/schedule` |
| `/b/[id]/label` | one mention at a time: evidence sentence in context, pick a label, next. **Judge's verdict hidden until you save**, so labels aren't anchored | **new** labels endpoints |

## Backend changes (found while reading the API)

1. **Typed responses for `/metrics`, `/sov`, `/deltas`.** They return
   `dict[str, Any]` today, so generated TS types would be `any`. Add pydantic
   response models; no behaviour change.
2. **`prompt_metrics(s, brand_id, f)`** in `metrics.py`: one GROUP BY over
   prompt × entity, reusing `_where`, `rate`, `wilson`. Must keep the file at
   100% coverage. Exposed as `GET /brands/{id}/prompts/metrics`.
3. **`text` on `GET /observations/{id}`**, reusing the adapter's existing
   text extraction, so the frontend never parses Gemini's raw payload.
4. **Migration 0008: `observation.search_queries int NULL`.** Whether an
   answer actually searched is computed in `gemini.py` for pricing and then
   discarded; it lives only in the raw file. Store it at write time, and add
   `scripts/backfill_search_queries.py` (owner-side, reads the raw store).
   This makes the 26-33% grounding problem visible and filterable.
5. **`GET /v1/ops`**: today's spend (the same `kind <> 'run'` rule as
   `scheduling.budget_fits`; extract its spend query into a shared function
   rather than writing a third copy), `budget_micros`, queue counts, last 20
   failures, searched-rate via `rate()`.
6. **Labelling.** Migration 0008 also adds `rec_label` (org_id,
   observation_id, entity_type, entity_id, label, created_at; unique on
   observation + entity; ENABLE + FORCE RLS like every tenant table; label
   CHECK generated from the same constant as `rec_status`). Endpoints:
   `GET /brands/{id}/labels/next` (oldest unlabelled mention),
   `PUT /observations/{id}/labels/{entity_id}`. `export_rec_labels.py` learns
   to read the table. Skipped: multiple labellers and agreement stats; add
   when a second labeller exists.

## Error handling

- API problems (RFC 9457) render in a route `error.tsx`: title, detail,
  `X-Request-Id`. 401 → `/login`. 404 → `not-found.tsx`.
- Empty states say why: "no completed observations in this window" rather
  than zeros, since `rate()` already returns null for n=0.

## Testing

- Backend: pytest as always; the full gate after every task; RLS tests for
  `rec_label` and `/ops` (cross-tenant → 404 / `[]`).
- Frontend gate, added to the existing one:
  `npm run typecheck && npm run lint && npm test && npm run build`
  with vitest covering only the pure functions (rate/CI formatting,
  significance label, filter ↔ search-params round trip).
- A check that the committed generated types match the live OpenAPI, so
  API drift fails the gate.
- Skipped: Playwright. End-to-end verification is done by driving the real
  app in the browser pane against the dev database ("Run 1" org has 60
  observations). Add Playwright when there is CI.

## Task order (for writing-plans)

1. Typed metric responses + `text` on observation detail
2. `prompt_metrics` + endpoint
3. `apps/web` scaffold, API wrapper, generated types, login, brand list
4. Overview page
5. Prompt table, prompt detail, observation evidence page
6. Migration 0008 (`search_queries`, `rec_label`), adapter write, backfill
7. `/ops` endpoint + page
8. Labelling endpoints + page + export script
9. Whole-branch review, audit, findings doc, docs index

Read-only views land first (1-5), so the slice is useful even if labelling
slips.

## Out of scope

Sign-up/sign-in, users and roles, the brand wizard UI, Visibility Score,
Google surfaces, recommendations, sparklines, mobile layouts, deployment.

## Verification

- Full backend gate + frontend gate green.
- `docker compose up -d`, API on :8000, `npm run dev` on :3000, log in with
  the "Run 1" key, and in the browser pane confirm: tile numbers equal
  `curl /v1/brands/{id}/metrics` exactly; a filter change updates the URL and
  the numbers; a prompt row drills to an observation with highlighted
  evidence; `/ops` spend equals an independent SQL sum of today's
  observation and non-run-job costs for that org (it is not comparable
  to the process-level ledger in `spend.py`, which covers every org
  since `spend_since`); saving a label writes a `rec_label` row and the
  next mention appears.
- A key from a second org sees none of the first org's brands.
