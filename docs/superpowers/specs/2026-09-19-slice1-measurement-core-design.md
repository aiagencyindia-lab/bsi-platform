# Slice 1: Measurement core — design

- **Date:** 2026-09-19
- **Status:** Draft for review
- **Source:** Brand Search Intelligence Platform PRD v1.0 (2026-09-18)
- **PRD modules touched:** F03 (monitoring), F04 (extraction), F05 (metrics), with the minimum of §3 (tenancy), §7 (data model) and §8 (API) needed to run them.

## 1. Why this slice exists

The PRD is a 12-month programme for a nine-person team. It has been split into
sub-projects, and this is the first. It answers the question the rest of the
product depends on:

> Can we measure a brand's visibility in an AI engine honestly, meaning with
> sample size and a 95% confidence interval on every number, at 3 samples per
> prompt, and what does each observation cost?

The slice runs end to end, from prompt to metric, on one engine (Gemini
grounding). It runs locally on Docker Compose with no new cloud spend.

### 1.1 In scope

- A new repository, `bsi-platform`, laid out as the PRD monorepo (§15.1).
- Postgres 16 with row-level security (RLS) keyed on `org_id` on every tenant table.
- Alembic migrations.
- The provider adapter interface (`query`, `cost`, `health`, `rate_budget`), with one implementation: Gemini grounding.
- On-demand runs with idempotent enqueueing.
- Raw payload storage, rule-based matching, and model extraction with `pipeline_version`.
- Mention, recommendation and citation rate, prompt coverage, and share of voice (SOV), each with `n` and a Wilson confidence interval.
- A REST API for the above, with problem+json errors.
- Tests: unit, integration, tenant isolation, and a small hand-labelled benchmark.
- A findings document with measured cost and confidence-interval widths.

### 1.2 Stubbed (behind an interface, replaced later)

| PRD component | Stub in this slice | Replaced in |
|---|---|---|
| Identity Platform login and user roles | Static API key → organisation | Foundation sub-project |
| Pub/Sub queues | `observation` table rows with a status, claimed with `SKIP LOCKED` | Production GCP sub-project |
| Cloud Storage for raw payloads | `LocalRawStore` writing to `./data/` | Production GCP sub-project |
| Cloud Scheduler | None; runs are on demand only | Measurement v2 |

### 1.3 Out of scope

- Any UI.
- Engines other than Gemini.
- The Google SERP provider.
- Workspaces beyond one seeded row.
- The user and user_role tables.
- Redis.
- `Idempotency-Key` headers and rate limiting.
- Cursor pagination (only `limit` and `offset` are supported).
- BigQuery mirroring.
- pgvector columns (the extension is installed but unused).
- `metric_daily`.
- Monthly partitioning.
- Deltas and "no significant change".
- Sentiment index.
- The composite Brand Visibility Score.
- Resolving grounding redirect URLs.

## 2. Repository layout

```
bsi-platform/
├── docker-compose.yml          # pgvector/pgvector:pg16, nothing else
├── pyproject.toml              # uv workspace root; ruff, mypy, pytest config
├── alembic.ini
├── .env.example                # DATABASE_URL, OWNER_DATABASE_URL, GOOGLE_CLOUD_PROJECT, ...
├── packages/core/bsi_core/
│   ├── config.py               # settings from env (pydantic-settings)
│   ├── db.py                   # engine, tenant_session(org_id)
│   ├── models.py               # SQLAlchemy 2 declarative models
│   ├── matching.py             # find_mentions(); normalize_domain()
│   ├── metrics.py              # wilson(); metric queries on one filter builder
│   ├── extraction.py           # schema, model call, sanity rules
│   ├── storage.py              # RawStore protocol, LocalRawStore
│   └── providers/
│       ├── base.py             # EngineAdapter protocol, EngineResult
│       └── gemini.py           # GeminiGroundingAdapter
├── apps/api/bsi_api/
│   ├── main.py                 # app factory, problem+json handler, request id
│   ├── deps.py                 # Bearer key → org_id → tenant session
│   └── routers/                # brands, prompts, runs, jobs, observations, metrics
├── apps/workers/bsi_workers/
│   └── worker.py               # claim → query → store → extract loop
├── migrations/versions/        # Alembic revisions, including roles and RLS
├── scripts/seed.py             # one org, one workspace, one API key (printed once)
├── eval/benchmark_v0.jsonl     # hand-labelled observations (written in step 10)
├── docs/
│   ├── superpowers/specs/      # this file
│   └── findings-slice1.md      # written at the end of the slice
└── tests/
    ├── unit/                   # no database
    ├── integration/            # docker compose Postgres
    └── fixtures/               # recorded Gemini and Flash-Lite payloads
```

`bsi_core` has no web or worker imports. The API and the worker depend on it,
and they communicate only through Postgres.

**Stack:**

- Python 3.12, uv workspace.
- FastAPI, SQLAlchemy 2 with psycopg 3, Alembic, pydantic-settings.
- `google-genai` using Vertex AI through Application Default Credentials (ADC).
- pytest, ruff (line length 80), and mypy (`--strict` on `bsi_core`).

## 3. Tenancy and authentication

### 3.1 Database roles

| Role | Used by | Rights |
|---|---|---|
| `bsi_owner` | Alembic, the seed script | Owns all tables |
| `bsi_app` | API, worker | DML on tenant tables; `NOBYPASSRLS`; not the table owner |

Tables use `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.

### 3.2 Policy

Every tenant table has `org_id uuid NOT NULL` and one policy:

```sql
CREATE POLICY tenant ON <table>
  USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);
```

`current_setting(..., true)` is NULL when never set and `''` after a
transaction-local value ends; `NULLIF` turns both into NULL, so such a session
sees zero rows instead of raising.

### 3.3 Sessions

`tenant_session(org_id)` is a context manager that opens a transaction and runs
`SELECT set_config('app.org_id', :org_id, true)`, which is transaction-local.
It is the only way application code gets a session.

### 3.4 API keys

- The `api_key` table holds `(id, org_id, workspace_id, hashed_key, scopes, last_used_at, expires_at)`.
- `hashed_key` is the SHA-256 hex digest of a 256-bit random token.
- The seed script prints the plain token once.
- Looking up a key happens before any tenant is known. It uses a
  `SECURITY DEFINER` function, `resolve_api_key(hash text) RETURNS uuid`, which
  returns the org id or NULL. `bsi_app` has `EXECUTE` on it and nothing else.
- A missing or unknown key returns 401.
- Any id belonging to another tenant is invisible under RLS and so returns 404,
  as PRD §8.1 requires.

### 3.5 Worker queue access

`claim_observation() RETURNS TABLE(observation_id uuid, org_id uuid)` is a
`SECURITY DEFINER` function. It:

1. selects one `queued` observation, or a `retry` whose `next_attempt_at <= now()`;
2. locks it with `FOR UPDATE SKIP LOCKED`;
3. sets `status='running'`;
4. returns the ids.

All further work happens inside `tenant_session(org_id)`.

## 4. Data model

Column names follow PRD §7.2. Every table has `id uuid` as its primary key,
using `gen_random_uuid()`, plus `created_at`. Every table except `engine` has
`org_id` and the RLS policy.

| Table | Columns in this slice |
|---|---|
| organization | id, name, plan, region, settings jsonb |
| workspace | id, org_id, name |
| api_key | see §3.4 |
| brand | id, org_id, workspace_id, name, aliases text[], category, status (`active` or `archived`) |
| domain | id, org_id, brand_id, host (normalized), is_primary |
| competitor | id, org_id, brand_id, name, aliases text[], domains text[] |
| locale | id, org_id, brand_id, country, language; one `IN`/`en` row is created with each brand |
| prompt | id, org_id, brand_id, locale_id, text, source (`manual`), status (`active` or `paused`) |
| engine | id, code (`gemini`), provider, default_model; reference data, no RLS |
| job | id, org_id, brand_id, kind (`run`), scheduled_slot, created_at; unique on (brand_id, kind, scheduled_slot) |
| observation | id, org_id, brand_id, job_id, prompt_id, engine_id, locale_id, sample_index, scheduled_slot, status, attempts, next_attempt_at, error, model, model_version, params jsonb, raw_uri, cost_micros, requested_at, completed_at |
| extraction | id, org_id, observation_id (unique), pipeline_version, model_used, brand_mentioned, position, rec_status, sentiment, sentiment_conf, context, absence_reason, parsed jsonb |
| mention | id, org_id, observation_id, entity_type (`brand` or `competitor`), entity_id, position, rec_status, sentiment |
| citation | id, org_id, observation_id, url, domain, position, is_brand_owned |

**Key constraints:**

- `observation` is unique on `(prompt_id, engine_id, scheduled_slot, sample_index)`.
- `observation.status` must be one of `queued`, `running`, `retry`, `fetched`, `done`, `failed`.
- `mention` unique on `(observation_id, entity_id)`; the metrics SQL relies on at most one brand row per observation.
- Indexes are on `(org_id, brand_id, prompt_id, engine_id, requested_at DESC)` for observation, `(org_id, entity_id, observation_id)` for mention, and `(org_id, domain, observation_id)` for citation.

Job progress, including `total`, is not stored. `GET /jobs/{id}` computes it
with `count(*) GROUP BY status` over the job's observations, so it stays right
when a same-hour re-POST adds rows for newly added prompts. It also avoids
updating a counter row from every worker.

## 5. Run pipeline

### 5.1 Enqueue: `POST /brands/{id}/runs`

This happens in one transaction:

1. `slot = date_trunc('hour', now() at time zone 'utc')`.
2. Find the job for `(brand_id, slot)`, or insert one if there is none.
3. Insert one `queued` observation for every active prompt, every enabled
   engine (just `gemini` in this slice), and every sample index from 0 to
   `samples - 1`. The default for `samples` is 3, and the request body can set
   it from 1 to 10. The insert uses `ON CONFLICT DO NOTHING`.
4. Return `202 {"job_id": ..., "status_url": "/v1/jobs/{id}", "enqueued": <rows inserted>}`.

A second POST in the same hour returns the same job with `enqueued: 0`.

### 5.2 Worker loop (`python -m bsi_workers.worker`)

```
loop:
  row = claim_observation()          # nothing to do → sleep 1 s
  with tenant_session(row.org_id):
      obs, prompt = load(row.observation_id)
      result = adapter.query(prompt.text, locale)       # never raises
      match result.kind:
        ok        → raw_uri = store.put(org, obs.id, result.raw)
                    save model, model_version, params, cost_micros; status=fetched
                    extract(obs)                          # §6, same process
                    status=done
        retryable → attempts += 1
                    attempts < 3 ? status=retry, next_attempt_at = now + 2^attempts s
                                 : status=failed, error
        fatal     → status=failed, error
```

- Run concurrency by starting more worker processes. `SKIP LOCKED` keeps them
  from claiming the same row.
- A worker that crashes leaves its row in `running`. On startup, any `running`
  row older than 10 minutes is reset to `retry`.
- Unexpected exceptions inside the loop body are caught, logged with
  `observation_id`, and treated as `retryable`. One bad row must never stop the
  loop.

### 5.3 Provider adapter (`providers/base.py`)

```python
class EngineResult:            # dataclass
    kind: Literal["ok", "retryable", "fatal"]
    raw: dict | None           # JSON-serialisable provider payload
    error: str | None
    model: str; model_version: str | None
    params: dict; cost_micros: int

class ParsedAnswer:            # dataclass
    text: str
    citations: list[tuple[str, str]]   # (url, domain), in answer order

class EngineAdapter(Protocol):
    code: str
    def query(self, prompt: str, locale: Locale) -> EngineResult: ...
    def parse(self, raw: dict) -> ParsedAnswer: ...
    def cost(self, raw: dict) -> int: ...          # micros
    def health(self) -> bool: ...
    def rate_budget(self) -> int: ...               # requests/min; informational in this slice
```

### 5.4 `GeminiGroundingAdapter`

- Calls `models.generate_content` on `gemini-2.5-flash` with
  `tools=[Tool(google_search=GoogleSearch())]` through Vertex AI.
- Temperature is left at the provider default, per PRD §10.3.
- Error mapping:
  - HTTP 429, 5xx and timeouts map to `retryable`.
  - Other 4xx errors, and a missing API key or credentials, map to `fatal`.
- `raw` is `response.model_dump(mode="json")`.
- `parse(raw)` joins the text parts. Citations come from
  `grounding_metadata.grounding_chunks[].web`:
  - `url` is the redirect URI.
  - `domain` is `normalize_domain(web.domain or web.title)`.

  The real host is only exposed there, which was verified in the ADK repo on
  2026-09-19.
- `cost(raw)`:
  - token usage × list price, plus $0.014 per grounded query when grounding
    metadata is present;
  - prices are constants in `gemini.py` with a dated comment.
- Locale: the prompt is sent as written. Country and language go into `params`
  for the record. Real locale targeting is a later concern.

### 5.5 Raw storage

- `RawStore.put(org_id, observation_id, payload) -> uri` and `get(uri) -> dict`.
- `LocalRawStore` writes `data/orgs/{org_id}/raw/{observation_id}.json` and
  returns a `file://` URI.
- `get` rejects any path outside `data/orgs/{org_id}/`.

## 6. Extraction

`PIPELINE_VERSION = "1"` is a constant in `extraction.py`. `extract(obs)`
reads the raw payload back from storage, so re-extraction never needs a new
engine call.

### 6.1 Rule-based pass

- `parse(raw)` produces the text and citations.
- `find_mentions(text, entities)` runs, where `entities` is the brand plus its
  competitors, each with its name and aliases.
- Each citation domain is flagged `is_brand_owned` when it equals, or is a
  subdomain of, one of the brand's `domain.host` values.

### 6.2 Matcher (`matching.py`, pure functions)

1. **Normalize:** Unicode NFKC, then `casefold()`.
2. **Strip URLs:** remove every `https?://\S+` and bare `\b[\w-]+(\.[\w-]+)+/\S*`
   span before splitting into tokens. A brand that appears only in a URL
   counts as a citation, never as a mention.
3. **Split into tokens:** use `re.findall(r"[^\W_]+", text)`. It is
   Unicode-aware, so Devanagari words become tokens. Aliases are split the
   same way.
4. **Possessive:** this needs no rule. Apostrophes (`'` and `’`) are not word
   characters, so `Nike's` splits into `nike` and `s`, and `nike` matches. The
   case is still in the test table so a later tokeniser change can't break it.
5. **Match:** an alias with k tokens matches k consecutive text tokens.
   - A token matches exactly.
   - If both tokens are at least 5 characters long, a Levenshtein distance of
     1 or less also counts.
6. **Overlaps:** when matches overlap, the longest alias wins. A tie goes to
   the exact match over the fuzzy one.
7. **Output:** `Hit(entity_id, entity_type, start_token, alias, fuzzy)`, sorted
   by `start_token`.

Nike vs NikeKids passes without special-case code: `nikekids` is a single
token, and it does not equal `nike`.

### 6.3 Model pass

This runs only when the text is non-empty.

- **Model:** `gemini-2.5-flash-lite` with `response_mime_type="application/json"`
  and `response_schema=ExtractionOut`, at temperature 0 because extraction must
  be deterministic.
- **Prompt:** a fixed template. The answer text sits between
  `<answer>` and `</answer>` delimiters, with an explicit instruction that the
  content is data and never instructions (PRD §12.4). The list of entities is
  passed in the same way.

```python
class EntityJudgement(BaseModel):
    name: str
    position: int | None            # model's view; stored in parsed only
    rec_status: Literal["recommended", "listed", "mentioned", "negative"]
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    sentiment_conf: float           # 0..1

class ExtractionOut(BaseModel):
    entities: list[EntityJudgement]
    context: str                    # ≤ 40 words about the brand, or ""
    absence_reason: Literal["not_retrieved", "competitor_dominance",
                            "category_mismatch", "off_topic"] | None
```

### 6.4 Sanity rules (the rule-based result wins)

- **Which entities count:** only entities found by the matcher get a `mention`
  row. If the model names an entity the matcher missed, that goes into
  `parsed.disagreements` and is not counted. `position` always comes from the
  matcher's order of first appearance. A matcher-found entity the model left
  out gets `rec_status="mentioned"` and `sentiment="neutral"`.
- **Absence reason:** `absence_reason` is kept only when the brand was not
  mentioned.
- **Context:** `context` is truncated to 40 words.
- **If the model call fails or its output fails validation:**
  - the extraction is still written, using the rule-based results;
  - `model_used="none"` and `parsed.model_error` are set;
  - the observation still reaches `done`.

  Metrics that depend on the model, such as recommendation rate, count that
  observation's brand `rec_status` as `mentioned`.

### 6.5 Writes

In one transaction:

- one `extraction` row, upserted on `observation_id`;
- the observation's `mention` and `citation` rows are deleted, then re-inserted;
- `observation.status` is set to `done`.

The delete-and-re-insert keeps re-extraction idempotent.

## 7. Metrics

### 7.1 Confidence interval

`wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]`. It returns
`(0.0, 1.0)` when `n == 0`, and the result is clamped to `[0, 1]`.

### 7.2 Filters

The same filter builder is used for every metric:

- `brand_id` (from the path)
- `engine` (optional)
- `locale_id` (optional)
- `date_from` / `date_to` on `requested_at`, in UTC, half-open
- `prompt_ids[]` (optional)

**Eligible observations** are the filtered observations with `status='done'`.
`n_failed` is the count of filtered observations with `status='failed'`.

### 7.3 Definitions

Each is returned as `{value, n, ci_low, ci_high}`. When `n = 0`, `value` is
`null` and the interval is `[0, 1]`.

| Metric | k | n |
|---|---|---|
| mention_rate | eligible observations with a brand `mention` | eligible observations |
| recommendation_rate | eligible observations whose brand mention has `rec_status='recommended'` | eligible observations |
| citation_rate | eligible observations with ≥ 1 citation where `is_brand_owned` | eligible observations |
| prompt_coverage | distinct prompts with ≥ 1 brand mention among eligible observations | distinct prompts among eligible observations |
| sov | eligible observations with a brand mention | brand + Σ competitors: eligible observations mentioning each entity, summed per entity |

`avg_position` is returned as `{value, n_mentioned}` with no confidence
interval.

`/brands/{id}/sov` returns the same SOV split per entity. Each entity gets
`{entity_id, name, type, mentions, share, ci_low, ci_high}`, and the interval
is Wilson over the summed denominator.

Every metrics response also includes `{filters, n_failed, pipeline_version, computed_at}`.

### 7.4 Stated limitation

With 3 samples, a single prompt's rate carries almost no information. For
example, 1 mention in 3 samples gives a Wilson interval of about [0.06, 0.79].
The API does not offer per-prompt rates. `/observations?prompt_id=` returns
raw samples for that. Brand-level numbers need tens of prompts before the
interval narrows to a useful width. The findings document will measure this.

## 8. API

- **Base path:** `/v1`. Requests and responses are JSON; timestamps are UTC ISO-8601.
- **Request id:** every response carries `X-Request-Id`, echoed from the
  request if present and generated otherwise.
- **Errors:** RFC 9457 `application/problem+json`, with
  `{type, title, status, detail, request_id, errors[]}`. One handler covers
  validation (422), not found (404), auth (401) and unexpected errors (500).
  The 500 response shows no internals.

| Endpoint | Methods | Notes |
|---|---|---|
| `/brands` | GET, POST | POST creates the brand plus its default locale |
| `/brands/{id}` | GET, PATCH, DELETE | DELETE sets `status='archived'` |
| `/brands/{id}/competitors` | GET, POST; `/{cid}` PATCH, DELETE | |
| `/brands/{id}/domains` | GET, POST; `/{did}` DELETE | host normalized on write |
| `/brands/{id}/prompts` | GET, POST (object or list ≤ 5,000); `/{pid}` PATCH | PATCH toggles status |
| `/brands/{id}/runs` | GET, POST | §5.1 |
| `/jobs/{id}` | GET | `{status, total, queued, running, retry, done, failed}`; status = `done` when queued + running + retry = 0 |
| `/observations` | GET | filters: brand_id, prompt_id, status, engine; `limit` ≤ 200, `offset` |
| `/observations/{id}` | GET | includes extraction, mentions, citations |
| `/observations/{id}/raw` | GET | stored payload |
| `/brands/{id}/metrics` | GET | §7 |
| `/brands/{id}/sov` | GET | §7 |
| `/healthz` | GET | no auth |

## 9. Configuration

Configuration is read from environment variables, loaded from `.env`, which is
not tracked:

- `DATABASE_URL`: the `bsi_app` connection.
- `OWNER_DATABASE_URL`: the `bsi_owner` connection, used by Alembic and the seed script.
- `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT=rasayan`, `GOOGLE_CLOUD_LOCATION=us-central1`.
- `ENGINE_MODEL=gemini-2.5-flash`, `EXTRACT_MODEL=gemini-2.5-flash-lite`.
- `RAW_STORE_DIR=./data`.

Docker Compose creates both roles through an init SQL script. Authentication
uses the existing ADC (`aiagencyindia@gmail.com`); no new keys are needed.

## 10. Testing

| Layer | What | Needs |
|---|---|---|
| Unit | Matcher case table (below); `wilson` against known values; `normalize_domain`; `GeminiGroundingAdapter.parse` and `cost` on recorded payloads; sanity rules on recorded extraction outputs | nothing |
| Integration | API → enqueue → worker (fake adapter, fake extractor) → metrics; idempotent re-POST; retryable then success; fatal → failed and job completes; crash recovery of stale `running` rows; re-extraction replaces mentions | compose Postgres |
| Isolation | Two orgs: every endpoint called with org A's key and org B's ids returns 404; `bsi_app` with no `app.org_id` selects 0 rows from every tenant table; an unknown key returns 401 | compose Postgres |
| Benchmark | `eval/benchmark_v0.jsonl` (about 30 hand-labelled observations: `raw` + expected brand and competitor mentions); matcher precision and recall ≥ 0.95 | fixture file |
| Live (opt-in) | One real Gemini query and one real extraction, marked `@pytest.mark.live` and skipped by default | ADC |

**Coverage and checks:**

- 100% line coverage on `metrics.py`.
- ruff clean.
- `mypy --strict` clean on `bsi_core`.

**Matcher cases**, each a test row:

- exact match
- alias match
- case and NFKC folding
- possessive (`Nike's`)
- plural not matched as the brand when the alias is short
- `Nike` vs `NikeKids`
- multi-token alias (`Foot Locker`)
- fuzzy on a long token (`Adiddas`, `Adidas`)
- no fuzzy on a short token (`Puma`, `Pumas`)
- Devanagari alias (`नाइकी`)
- brand only inside a URL gives no mention
- overlapping aliases, where the longest wins

## 11. Definition of done

1. `docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py`
   goes from nothing to a working API key.
2. For one real brand the user chooses, with about 5 competitors and about 20
   prompts, `POST /runs` completes 60 live Gemini observations. Each has a raw
   payload, an extraction and a `cost_micros`.
3. `/metrics` and `/sov` return values with `n` and confidence intervals.
   Posting again in the same hour enqueues 0 rows.
4. All unit, integration, isolation and benchmark tests pass, along with ruff
   and mypy.
5. `eval/benchmark_v0.jsonl` exists, labelled from the real run.
6. `docs/findings-slice1.md` reports:
   - the measured cost per observation;
   - confidence-interval widths at brand level;
   - disagreements between the rule-based matcher and the model;
   - a recommendation on the default sample count.

## 12. Reuse from `brand-search-optimization`

This code is copied, never imported. That repo stays unchanged.

| Asset | Used for |
|---|---|
| `sub_agents/search_results/agent.py`, including `fill_sources` | Shape of the grounding metadata; `web.domain` and `web.title` give the real host, while `uri` is a redirect; segment offsets are UTF-8 bytes |
| The "tools never raise" convention (`site_browsing/agent.py::_get_driver`, `tools/bq_connector.py`) | Adapters return `EngineResult(kind=...)` and never raise |
| `pyproject.toml` ruff and mypy settings | Lint config |
| Vertex and ADC environment setup | §9 |

## 13. Risks

| Risk | Mitigation in this slice |
|---|---|
| Vertex 429s during the 60-observation run (seen in the ADK repo) | Retryable with backoff; run 1–2 worker processes |
| Grounding redirect URIs expire | Only the domain is used for metrics; the raw payload is kept |
| Flash-Lite ignores the schema or picks up instructions from the answer | Rule-based results win; schema validation; delimited data; failure falls back to rule-based results only |
| RLS silently bypassed by the table owner | The app connects as the non-owner `bsi_app` with `FORCE ROW LEVEL SECURITY`; isolation tests cover every table |
