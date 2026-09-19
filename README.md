# bsi-platform

Brand-visibility measurement platform: a Python uv workspace with
`packages/core` (shared models/config), `apps/api` (FastAPI service), and
`apps/workers` (background jobs), backed by Postgres.

Spec: `.superpowers/sdd/2026-09-19-slice1-measurement-core/`

## Quickstart

```sh
docker compose up -d   # starts local Postgres on port 5433
uv sync                # installs the workspace
uv run pytest          # runs the test suite
```

Copy `.env.example` to `.env` and adjust as needed for local overrides.
