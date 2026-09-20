# Slice 4: Prompt intelligence and the brand wizard — implementation plan

**Spec:** `docs/superpowers/specs/2026-09-20-slice4-prompt-intelligence-design.md`. It wins on any conflict with this plan.

**Branch:** `slice4-prompt-intelligence` (off `main` at `482eac5`).

**Process:** one implementer per task, then one review. Ledger: `.superpowers/sdd/2026-09-20-slice4-prompt-intelligence/progress.md`.

## Global rules

- **Test first.** Write the tests, run them, and **paste the failing output into the task report** before implementing. Then paste the passing output.
- **Gate** at the end of every task:

  ```bash
  uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  ```

- `bsi_core.metrics` stays at 100% line coverage, no `pragma: no cover`. mypy is strict over `bsi_core` only. Ruff line length 80.
- **Tests never call Vertex.** Model work is injected as plain callables (the `SentenceJudge` pattern in `labels.py`, the fakes in `tests/integration/test_extraction.py`). Only Tasks 0 and 10 spend.
- **Model calls run with no database transaction open** (see `Extractor.prepare` / `worker.process_one`).
- Always `cd /Users/vineet/Downloads/ADK/bsi-platform`. Never use `gcloud` or `bq`.
- Commits: conventional subject, then a **blank line**, then the `Co-Authored-By:` line from the current session's attribution reminder. Don't push.

## File map

| File | Tasks |
|---|---|
| `migrations/versions/0007_prompt_intelligence.py` (new), `packages/core/bsi_core/models.py` | 1 |
| `packages/core/bsi_core/extraction.py`, `metrics.py`, `scripts/export_benchmark.py`, `tests/conftest.py` | 2 |
| `packages/core/bsi_core/scheduling.py`, `spend.py`, `config.py`, `scripts/set_budget.py` (new) | 3, 8 |
| `packages/core/bsi_core/suggest.py` (new), `judge.py`, `labels.py` | 4, 5 |
| `apps/workers/bsi_workers/worker.py` | 6 |
| `apps/api/bsi_api/routers/prompts.py`, `brands.py`, `runs.py`, `schedules.py` | 7, 8 |
| `tests/integration/test_isolation.py` | 9 |
| `scripts/wizard.py`, `scripts/prompt_eval.py`, `docs/findings-slice4.md` | 0, 10 |

---

## Task 0: Probe (live, about $0.25)

Answers what the design cannot decide offline. Run by the controller, not a subagent.

1. **Embedding model.** Try, in `GOOGLE_CLOUD_LOCATION=global`: `gemini-embedding-001`, then `text-embedding-005` and `text-multilingual-embedding-002` if it 404s. Record the working id, whether `global` works or another location is needed, per-call latency, and what token/billing fields the response carries (`response.embeddings[0].statistics.token_count`, `response.metadata.billable_character_count`). Confirm `output_dimensionality=768` and `task_type="SEMANTIC_SIMILARITY"` are accepted, and whether a list of texts is accepted in one call.
2. **Price.** Record the published price per million tokens for that model and the resulting `EMBED_PRICES` entry.
3. **Generation.** One call at `temperature=1.0` asking for 60 prompts for a real brand (use `eval/run1.json`'s brand, category "kids footwear", competitors from that file), with the schema from §3 of the spec. Record: seconds, output tokens, cost, how many came back, the intent spread, and the topics used.
4. **Threshold.** Embed those prompts, print the pairwise cosine distribution (min, median, p90, p99, max) and every pair at or above 0.88. This is the evidence for keeping or moving the 0.92 duplicate threshold.
5. **Competitors.** One grounded query through `GeminiGroundingAdapter` asked 3 times for that brand, parsed to `{name, domain}` by the generator; record names, evidence counts and cost.

Spend-guard every call with `bsi_core.spend` (`check(est)` then `record(kind, actual, release=est)` in a `finally`), as `scripts/judge_eval.py` does. Keep the script at `scripts/probe_embed.py`. Write the results into `docs/findings-slice4.md` under "Step 0 probe" and commit both.

**Commit:** `eval: slice 4 step-0 probe (embedding model, threshold, generation)`

---

## Task 1: Migration 0007, models, pgvector

- `uv add pgvector` in `packages/core` (it pulls numpy). If `pgvector` ships no `py.typed`, add to the root `pyproject.toml`:

  ```toml
  [[tool.mypy.overrides]]
  module = "pgvector.*"
  ignore_missing_imports = true
  ```

- **Models** (`models.py`): `from pgvector.sqlalchemy import Vector`.
  - `Prompt`: `intent: Mapped[str | None]`, `topic: Mapped[str | None]`, `embedding: Mapped[list[float] | None] = mapped_column(Vector(768))`, plus `__table_args__` with `ck_prompt_intent` (the 10 classes **or NULL**), `ck_prompt_status` (`suggested`, `active`, `paused`, `archived`), `ck_prompt_source` (`manual`, `generated`).
  - `Competitor`: `status: Mapped[str] = mapped_column(server_default="active")`, `evidence: Mapped[int | None]`, CHECK `ck_competitor_status`.
  - `Organization`: `daily_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))`, CHECK `ck_organization_budget` (`>= 0`).
  - `Job`: `status: Mapped[str | None]`, `params: Mapped[dict[str, Any]] = mapped_column(server_default="{}")`, `error: Mapped[str | None]`, `cost_micros: Mapped[int] = mapped_column(server_default="0")`, `started_at: Mapped[datetime | None] = mapped_column(TSZ)`, CHECK `ck_job_status` (NULL or the four values).
- **Migration** `0007_prompt_intelligence.py` (`revision = "0007"`, `down_revision = "0006"`): `op.add_column` for each, the embedding via `op.execute("ALTER TABLE prompt ADD COLUMN embedding vector(768)")` so the migration needs no import, the CHECKs via `op.create_check_constraint`, and:

  ```python
  op.create_index(
      "ix_job_queued", "job", ["created_at"],
      postgresql_where=sa.text("status = 'queued'"),
  )
  ```

  `claim_job()` (plpgsql, SECURITY DEFINER, `SET search_path = public`), then `REVOKE ALL … FROM PUBLIC` and `GRANT EXECUTE … TO bsi_app`:

  ```sql
  UPDATE job SET status = 'failed', error = 'stale'
  WHERE status = 'running' AND started_at < now() - interval '10 minutes';
  RETURN QUERY
  UPDATE job j SET status = 'running', started_at = now()
  WHERE j.id = (SELECT q.id FROM job q
                WHERE q.kind <> 'run' AND q.status = 'queued'
                ORDER BY q.created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
  RETURNING j.id, j.org_id, j.kind;
  ```

  `downgrade()` drops the function, the index, the constraints and the columns.

**Tests** (`tests/integration/test_constraints.py`, and `test_worker.py` for the function):
- each new CHECK rejects a bad value, asserting the constraint name (`pytest.raises(IntegrityError, match="ck_…")`);
- a prompt row round-trips an embedding (write a list; don't select the column back — compare with a `<=>` query instead);
- `claim_job()` through `system_session()`: claims a queued non-run job and returns `(id, org_id, kind)`; ignores `kind='run'` and NULL status; a second call returns nothing; a `running` job with `started_at` 11 minutes ago is failed with `error='stale'` and not returned.

**Also run, with output in the report:** `alembic check` on `bsi_test`, `downgrade 0006`, `upgrade head`, `alembic check` again, then `alembic upgrade head` on the dev DB.

**Commit:** `feat(db): prompt labels and embeddings, job status, org budget (0007)`

---

## Task 2: Suggestions must not affect measurement

Add `AND c.status = 'active'` (or the ORM equivalent) to:
- `extraction.load_entities` (`extraction.py:115`),
- `metrics.brand_sov` (`metrics.py:92`),
- `scripts/export_benchmark.py:27`.

`tests/conftest.py:97`'s job lookup gains `kind == "run"`, or observations attach to suggestion jobs.

**Tests, each of which must fail before the change:**
- `test_metrics.py`: a suggested competitor **with a mention row** does not appear in `brand_sov` and does not change the brand's share;
- `test_extraction.py`: `load_entities` omits a suggested competitor, so the matcher cannot label it.

`metrics.py` stays at 100% coverage.

**Commit:** `fix(core): suggested competitors stay out of matching and share of voice`

---

## Task 3: Budget override and job spend

- `Organization.daily_budget_usd` is already in the model (Task 1). In `scheduling.budget_fits(s, org_id, n_obs, extra_micros=0)`:
  - cap = `s.get_one(m.Organization, org_id).daily_budget_usd`, else `settings.daily_budget_usd`; convert with `round(float(cap) * 1_000_000)`;
  - the comparison becomes `spent + extra_micros + (pending + n_obs) * estimate <= cap`;
  - **read no new setting**: `tests/integration/test_budget.py` stubs `get_settings` with only two attributes.
- `_SPENT_AND_PENDING` gains today's job spend as a **scalar subquery**, so the extraction join cannot fan it out:

  ```sql
  + (SELECT coalesce(sum(j.cost_micros), 0) FROM job j, day
     WHERE j.created_at >= day.start) AS spent
  ```

- `spend._DB_SPEND` gains the same, or wizard spend is invisible to the $15 script cap.
- `scripts/set_budget.py "<org name>" <usd|none>`: owner session, sets or clears the override, prints the old and new values.

**Tests:** an org with an override fits above the settings default and stops at its own; clearing it falls back; a job's `cost_micros` today counts toward the daily budget and toward `spend.db_micros`; `extra_micros` shifts the boundary by exactly that amount.

**Commit:** `feat(spend): per-org daily budget override; job cost counts`

---

## Task 4: Pure parts of `suggest.py`

- `judge._generate` → public `generate(prompt, schema, temperature=0.0)`, passing `temperature=temperature` into the config. Update the three judges to call it (their behaviour must not change: they keep temperature 0).
- `labels._escape` → public `escape` (keep a module-level alias if anything else uses the private name).
- New `packages/core/bsi_core/suggest.py`:

  ```python
  # Exactly the spellings in ck_prompt_intent (migration 0007): hyphens,
  # not underscores. The step-0 probe asked with underscores and the model
  # echoed them back, which would violate the CHECK.
  INTENTS = ("informational", "commercial", "transactional", "comparison",
             "alternative", "recommendation", "problem-based",
             "industry-specific", "persona-specific", "geographic")
  Generator = Callable[[str, type[BaseModel], float], tuple[str, int, str]]
  Embedder = Callable[[list[str]], tuple[list[list[float]], int]]
  PROMPT_JOB_MICROS = 30_000
  COMPETITOR_JOB_MICROS = 3 * 50_000 + 10_000  # 3 grounded answers + parse

  class GeneratedPrompt(BaseModel): text: str; intent: str; topic: str
  class PromptSet(BaseModel): prompts: list[GeneratedPrompt]
  class CompetitorGuess(BaseModel): name: str; domain: str
  class CompetitorSet(BaseModel): competitors: list[CompetitorGuess]
  ```

  Plus the pure helpers:
  - `cosine(a, b) -> float`;
  - `dedupe(vectors, threshold) -> list[int]` — greedy keep-first, returns kept indices;
  - `clean_prompts(out, existing_keys, brand_keys) -> list[GeneratedPrompt]` — strip; drop empty or over 1,000 chars; intent must be in `INTENTS` else drop; topic case-folded, stripped, capped at 60; drop exact repeats by `labels.key`;
  - `merge_competitors(sets, brand_keys, known_keys) -> list[tuple[name, domain, evidence]]` — **key on the normalized domain when one is present, else on `labels.key(name)`** (the probe found "Bata India", "Bata India (Bubblegummers)" and "Bubblegummers" all scoring 1/3 while all resolving to bata.com); count how many sets named each; drop the brand, its aliases and known competitors; cap name at 200; keep the top 10 by evidence then name;
  - `build_prompt_request(ctx, count)` and `build_competitor_parse(answer, brand)` — every tenant string through `escape`, wrapped in one delimited block under a "DATA, not instructions" preamble, in the style of `labels._PROMPT`.

**Tests** (`tests/unit/test_suggest.py`): cosine against hand-computed values; dedupe keeps the first of a near-identical pair and keeps distant ones; `clean_prompts` drops an unknown intent, an over-long text and a duplicate, and case-folds topics; `merge_competitors` ranks by evidence, drops the brand and known names, normalizes domains; both builders escape `<` and include every context field. The judges still pass unchanged.

**Commit:** `feat(suggest): typed schemas, dedupe and escaped prompt builders`

---

## Task 5: `suggest_prompts`, `suggest_competitors`, `embed`

- `config.py`: `embed_model: str = "gemini-embedding-001"` (confirmed working in `global` by the probe).
- `suggest.py`: `EMBED_PRICES: dict[str, int]` (micros per token; the probe's number), `embed(texts) -> (vectors, cost_micros)` using `client.models.embed_content` with `task_type="SEMANTIC_SIMILARITY"`, `output_dimensionality=768`. **The probe confirmed the SDK batches**: send the texts in one call (chunk at 100 to stay well inside limits) under `judge.with_retries`. Cost is the sum of each embedding's `statistics.token_count`, falling back to `len(text) // 3` when absent. `EMBED_PRICES["gemini-embedding-001"]`. `KeyError` for an unpriced model, and the worker's startup fail-fast line gains `EMBED_PRICES[settings.embed_model]`.
- `suggest_prompts(org_id, brand_id, count, generator, embedder) -> str`:
  1. tenant read: brand (raise if archived), category, aliases, first locale, **active** competitors, existing prompt texts (capped at 100) and topics; rows missing `intent`/`topic`/`embedding` for backfill;
  2. close the transaction; generate at temperature 1.0 asking for `count * 1.25`, accumulating `spent`;
  3. `clean_prompts`, embed survivors, `dedupe` within the batch;
  4. for each survivor, an `EXISTS` check against the same brand and locale: `embedding <=> :v <= 0.08`;
  5. tenant write: insert survivors (`source='generated'`, `status='suggested'`, intent, topic, embedding) and backfill the rows from step 1;
  6. return a summary string, e.g. `suggested:41`.
  Any failure raises `JudgeFailed(e, spent)`.
- `suggest_competitors(org_id, brand_id, adapter, generator) -> str`: three grounded `adapter.query(...)` calls (positional args; it never raises — skip failed answers, fail only if all three fail), each answer parsed by the generator into `CompetitorSet`, merged by `merge_competitors`, written with `status='suggested'` and `evidence`. Returns e.g. `suggested:6`.

**Tests** (`tests/integration/test_suggest.py`) with fakes: a fake generator returning canned JSON, a fake embedder returning fixed vectors, a fake adapter returning `EngineResult`s.
- generation writes suggested rows with labels and embeddings, and returns the count;
- a candidate near-identical to an existing prompt is dropped by the SQL check (build the vectors so the distance is under and over the threshold);
- `count=0` backfills labels and embeddings for existing rows and inserts nothing;
- an archived brand raises before any model call (assert the fake was never called);
- invalid JSON raises `JudgeFailed` carrying the generation cost, and nothing is written;
- competitors: three answers merge with the right evidence counts; one failing answer still produces a result; all three failing raises;
- a rerun does not duplicate an existing suggested competitor.

**Commit:** `feat(suggest): prompt and competitor suggestion jobs`

---

## Task 6: Worker

- `tick()` claims a **job first**, then an observation: jobs are rare, user-facing and about a minute long, and a 9,000-observation run must not delay one for hours.
- `process_job(adapter, generator, embedder) -> bool`:
  1. `claim_job()` through `system_session()`; `None` → return False;
  2. tenant transaction: budget check via `budget_fits(s, org_id, 0, extra_micros=<the kind's estimate>)`; if it fails → `status='failed'`, `error='budget'`, return True;
  3. run the kind's function with **no transaction open**;
  4. final write in one tenant transaction: `s.get(m.Job, job_id, with_for_update=True)`; **if its status is no longer `running`, discard everything**; else `status='done'`, `error=None`, `cost_micros += spent`;
  5. on exception: `status='failed'`, `error=repr(e)[:2000]`, `cost_micros += getattr(e, "cost_micros", 0)`.
- `tick` gains keyword defaults `generator=judge.generate`, `embedder=suggest.embed`, so existing callers are untouched.

**Tests** (`test_worker.py`): a queued prompts job runs and is marked done with its cost; a failing job is marked failed with the error and keeps its spent cost; a job whose status is changed to `failed` mid-flight (monkeypatch the suggestion function to flip it) writes nothing; over budget gives `failed`/`budget` without calling the model; `tick` prefers a job over a queued observation.

**Commit:** `feat(worker): run suggestion jobs, claimed before observations`

---

## Task 7: API

- **Suggest endpoints** (`prompts.py`, `brands.py`): `POST …/prompts/suggest` (`{count: int = 50, ge=0, le=100}`, `extra="forbid"`) and `POST …/competitors/suggest` (no body). Both: `brand_or_404`, 409 if archived, then find-or-create a job for `(brand_id, kind, hour_slot(now))` with `status='queued'`, `params`; **if the existing job is `failed`, requeue it** (`status='queued'`, `error=None`; `cost_micros` is left alone so it accumulates). 202 `{job_id, status_url}`.
- `_job_view` branches on `kind`: non-run jobs return `{id, brand_id, kind, status, error, cost_micros}`. `list_runs` filters `kind == "run"`.
- **Prompts:** `PromptOut` gains `intent`, `topic`; `GET` gains `status` and `intent` query filters; `PATCH /{pid}` accepts all four statuses; new bulk `PATCH ""` with `{ids: list[UUID], status}` — the rows matched by `(brand_id, id in ids)` must number `len(set(ids))`, else 404; returns the updated count and the cost preview (Task 8).
- **Plan limit:** `scheduling.check_active_limit(s, org_id, adding) -> tuple[int, int] | None` under `pg_advisory_xact_lock(hashtext(org))`, reading `organization.plan` (`starter` 100, `pro` 500, `agency` 2,000, anything else 100). Called on create, single activation and bulk activation; on failure `Problem(409, "Plan limit reached", f"{current} + {adding} > {limit}")`.
- `GET /v1/brands/{id}/clusters` → `[{intent, topic, active, suggested, paused}]`, grouped in SQL, ordered by active desc then intent, topic.
- **Competitors:** `CompetitorOut` gains `status`, `evidence`; `CompetitorPatch` accepts `status: Literal["active"]`; `GET` gains `?status=`; `max_length=200` on `BrandIn.category`, alias items and competitor name/domain items.
- **Fix the existing test:** `tests/integration/test_runs.py:117-128` creates 3,000 prompts through the API and would now hit the plan limit. Seed those rows through the `owner` session instead; the test is about `enqueue_run`, not the API.

**Tests** (`test_api_crud.py` or a new `test_api_suggest.py`): the two suggest endpoints return 202 and create a job; a repeat in the same hour returns the same job id; a failed job is requeued; archived → 409; bulk PATCH activates and rejects a foreign id with 404; the plan limit refuses with 409 at the boundary; clusters groups correctly; competitor confirm flips status.

**Commit:** `feat(api): prompt suggestion, states, plan limits and clusters`

---

## Task 8: Cost preview

`scheduling.daily_cost_preview(s, org_id, brand_id) -> dict`:

```python
{"brand": {"active_prompts", "samples", "runs_per_day", "est_daily_usd"},
 "org": {"est_daily_usd"}, "budget_usd": float, "fits": bool}
```

- per brand: active prompts × the brand schedule's samples (default 2) ÷ `CADENCE_DAYS[cadence]` (no schedule → 1 run/day), × `settings.obs_cost_estimate_micros`;
- per org: the same summed over every **active** schedule in the org, so two brands that each look affordable are still caught;
- `budget_usd` is the override or the setting; `fits = org est <= budget`.

Returned in the schedule `PUT`/`GET` view (under `cost_preview`) and in the bulk-activation response. Nothing is refused on its basis.

**Tests:** a brand with no schedule assumes one run a day; cadence divides; two brands sum into the org figure; `fits` flips exactly at the boundary and follows the org override.

**Commit:** `feat(api): daily cost preview on activation and schedule`

---

## Task 9: Isolation suite

- `other` fixture: add a suggestion job (`kind="suggest_prompts"`, `status="done"`) for org B and return its id as `j2`.
- New `CASES`: `POST …/prompts/suggest {}`, `POST …/competitors/suggest`, `PATCH …/prompts {"ids": [], "status": "paused"}`, `GET …/clusters`, `GET /v1/jobs/{j2}`, `PATCH …/competitors/{c} {"status": "active"}`.
- `test_org_b_data_is_untouched` also asserts: org B's job count is unchanged (no suggest job was created), its competitor is still `active`, and its prompt's `intent`, `topic` and `embedding` are still NULL.
- One non-parametrised test: org A bulk-PATCHing **its own** brand with org B's prompt id gets 404, and B's prompt is unchanged.

**Commit:** `test(isolation): cover the suggestion endpoints`

---

## Task 10: Wizard, eval and findings (live, about $0.60)

- `scripts/wizard.py <spec.json>`: create the brand (name, category, aliases, domains) → `POST competitors/suggest` → `POST prompts/suggest` → poll both jobs → print suggestions, the clusters view and the cost preview → optionally bulk-activate with `--activate N`.
- `scripts/prompt_eval.py`: for three brand specs (kids footwear, a B2B SaaS CRM, an Indian D2C skincare brand), generate 50 prompts each; report seconds, pre-dedupe near-duplicate rate, post-dedupe count, intent spread, and the pairwise similarity histogram; write `eval/results/prompt_gen_v0.json`. Spend-guarded with `bsi_core.spend`.
- **User review stop.** Show the user one full generated set and the similarity distribution, and ask them to confirm (a) the prompts are worth running and (b) the 0.92 threshold. Do not close the slice before they answer.
- **Live wizard check** (spec §8): both jobs finish `done` with `cost_micros > 0`; ~50 suggested prompts with intents, topics and embeddings in ≤ 90 s; competitors carry evidence; a second suggest in a later hour adds new prompts; activating shows `fits: false` at $2 and `true` after `scripts/set_budget.py`; a scheduled run then enqueues. Stop the API and worker and confirm with `ps`.
- `docs/findings-slice4.md`: the probe, the eval numbers, the live check, spend, the threshold decision, and follow-ups (other prompt sources, volume estimates, HNSW, relabelling, on-demand run exposure).

**Commit:** `docs: slice 4 findings, wizard and prompt eval`

---

## Definition of done

Spec §8, then a final whole-branch review, one fix wave, and `superpowers:finishing-a-development-branch` (merge with a **merge commit**).
