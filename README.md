# bsi-platform

Brand-visibility measurement platform: a Python uv workspace with
`packages/core` (shared models/config), `apps/api` (FastAPI service), and
`apps/workers` (background jobs), backed by Postgres.

Spec: `docs/superpowers/specs/2026-09-19-slice1-measurement-core-design.md`
All documents: the PRD, the spec, the plan, the findings and the audit are
indexed in [`docs/README.md`](docs/README.md).

## Quickstart

```sh
docker compose up -d                            # starts local Postgres on port 5433
cp .env.example .env                            # local config
uv sync                                         # installs the workspace
uv run alembic upgrade head                     # applies migrations
uv run python scripts/seed.py                   # seeds dev data, prints an API key once
uv run uvicorn bsi_api.main:app --port 8000     # starts the API
uv run python -m bsi_workers                    # starts the worker (separate shell)
```

Run tests with `uv run pytest`. Live tests that call real model providers
are opt-in via `uv run pytest -m live` and need Application Default
Credentials plus the `.env` variables exported into the shell, e.g.
`set -a && source .env && set +a`.

### Operator dashboard (`apps/web`)

```sh
cd apps/web && npm install     # installs the Next.js dashboard
npm run dev                    # starts it on port 3000
```

It talks to the API over `API_URL` (`apps/web/.env.example`, default
`http://localhost:8000`) and expects the API to already be running from
the steps above. Sign in with an API key printed by `scripts/seed.py`.

## Testing

Whenever an endpoint is added later, add its row to `CASES` in `tests/integration/test_isolation.py`.

Before merging a change to `apps/web`, run `npm run gate` there (typecheck,
lint, tests, build, and `gen:check` against the live OpenAPI) - it fails
the moment `schema.d.ts` drifts from a backend response model.

CI (`.github/workflows/ci.yml`) runs both gates on every pull request and
on pushes to `main`, against the same pgvector image `docker-compose`
uses - so a stale generated type or an unformatted file fails before
review rather than after merge.
