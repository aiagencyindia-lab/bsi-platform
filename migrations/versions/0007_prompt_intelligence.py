"""prompt labels and embeddings, job status, org budget"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

INTENTS = (
    "informational",
    "commercial",
    "transactional",
    "comparison",
    "alternative",
    "recommendation",
    "problem-based",
    "industry-specific",
    "persona-specific",
    "geographic",
)

CHECKS = [
    (
        "prompt",
        "ck_prompt_intent",
        "intent IS NULL OR intent IN ("
        + ", ".join(f"'{i}'" for i in INTENTS)
        + ")",
    ),
    (
        "prompt",
        "ck_prompt_status",
        "status IN ('suggested', 'active', 'paused', 'archived')",
    ),
    ("prompt", "ck_prompt_source", "source IN ('manual', 'generated')"),
    (
        "competitor",
        "ck_competitor_status",
        "status IN ('suggested', 'active')",
    ),
    ("organization", "ck_organization_budget", "daily_budget_usd >= 0"),
    (
        "job",
        "ck_job_status",
        "status IS NULL OR status IN ('queued', 'running', 'done', 'failed')",
    ),
]

COLUMNS = [
    ("prompt", sa.Column("intent", sa.String(), nullable=True)),
    ("prompt", sa.Column("topic", sa.String(), nullable=True)),
    (
        "competitor",
        sa.Column(
            "status", sa.String(), server_default="active", nullable=False
        ),
    ),
    ("competitor", sa.Column("evidence", sa.Integer(), nullable=True)),
    (
        "organization",
        sa.Column("daily_budget_usd", sa.Numeric(10, 2), nullable=True),
    ),
    ("job", sa.Column("status", sa.String(), nullable=True)),
    (
        "job",
        sa.Column(
            "params",
            sa.dialects.postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
    ),
    ("job", sa.Column("error", sa.String(), nullable=True)),
    (
        "job",
        sa.Column(
            "cost_micros", sa.Integer(), server_default="0", nullable=False
        ),
    ),
    (
        "job",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    ),
]


def upgrade() -> None:
    for table, column in COLUMNS:
        op.add_column(table, column)
    # Raw DDL so the migration needs no pgvector import.
    op.execute("ALTER TABLE prompt ADD COLUMN embedding vector(768)")
    for table, name, expr in CHECKS:
        op.create_check_constraint(name, table, expr)
    op.create_index(
        "ix_job_queued",
        "job",
        ["created_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )

    # Runs as its owner, like claim_observation() in 0002, so the worker
    # can claim across tenants without a tenant setting.
    op.execute("""
        CREATE FUNCTION claim_job()
        RETURNS TABLE(job_id uuid, org_id uuid, kind text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
          -- A stale job may already have spent money: fail it, never retry.
          UPDATE job SET status = 'failed', error = 'stale'
          WHERE status = 'running'
            AND started_at < now() - interval '10 minutes';
          RETURN QUERY
          UPDATE job j SET status = 'running', started_at = now()
          WHERE j.id = (SELECT q.id FROM job q
                        WHERE q.kind <> 'run' AND q.status = 'queued'
                        ORDER BY q.created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
          RETURNING j.id, j.org_id, j.kind::text;
        END;
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION claim_job() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION claim_job() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION claim_job()")
    op.drop_index("ix_job_queued", "job")
    for table, name, _ in CHECKS:
        op.drop_constraint(name, table, type_="check")
    op.execute("ALTER TABLE prompt DROP COLUMN embedding")
    for table, column in COLUMNS:
        op.drop_column(table, column.name)
