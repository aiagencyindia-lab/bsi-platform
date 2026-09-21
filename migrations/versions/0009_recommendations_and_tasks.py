"""recommendation and task tables, their RLS, and due_impact_windows()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def _row() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
    ]


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def upgrade() -> None:
    op.create_table(
        "recommendation",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("dismiss_reason", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("reach", sa.Float(), nullable=False),
        sa.Column("pressure", sa.Float(), nullable=False),
        sa.Column("feasibility", sa.Float(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        *_row(),
        sa.CheckConstraint(
            "type IN ('pursue_citation_source', 'create_content', "
            "'add_competitor', 'sample_more')",
            name="ck_recommendation_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'dismissed')",
            name="ck_recommendation_status",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "type", "subject_key"),
    )
    _protect("recommendation")

    op.create_table(
        "task",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("notes", sa.String(), server_default="", nullable=False),
        sa.Column(
            "prompt_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("impact_label", sa.String(), nullable=True),
        sa.Column(
            "impact", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        *_row(),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'done', 'impact_measured')",
            name="ck_task_status",
        ),
        sa.CheckConstraint(
            "impact_label IS NULL OR impact_label IN ('improved', "
            "'no_change', 'declined', 'insufficient_data', 'not_comparable')",
            name="ck_task_impact_label",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress') "
            "OR (done_at IS NOT NULL AND window_days IS NOT NULL)",
            name="ck_task_done_has_window",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id"),
    )
    _protect("task")

    # Runs as its owner, like due_schedules() in 0006, so the worker can
    # find closed windows across tenants without a tenant setting.
    op.execute("""
        CREATE FUNCTION due_impact_windows()
        RETURNS TABLE(task_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT t.id, t.org_id FROM task t
          WHERE t.status = 'done'
            AND t.done_at + make_interval(days => t.window_days) <= now()
          ORDER BY t.done_at
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_impact_windows() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_impact_windows() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_impact_windows()")
    op.drop_table("task")
    op.drop_table("recommendation")
