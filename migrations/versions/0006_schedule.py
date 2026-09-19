"""schedule table, its row-level security and due_schedules()"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "schedule",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("cadence", sa.String(), nullable=False),
        sa.Column("hour_utc", sa.Integer(), nullable=False),
        sa.Column("samples", sa.Integer(), server_default="2", nullable=False),
        sa.Column(
            "status", sa.String(), server_default="active", nullable=False
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(), nullable=True),
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
        sa.CheckConstraint(
            "cadence IN ('daily', 'every_3_days', 'weekly')",
            name="ck_schedule_cadence",
        ),
        sa.CheckConstraint(
            "hour_utc BETWEEN 0 AND 23", name="ck_schedule_hour"
        ),
        sa.CheckConstraint(
            "samples BETWEEN 1 AND 10", name="ck_schedule_samples"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused')", name="ck_schedule_status"
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id"),
    )
    op.create_index("ix_schedule_org_id", "schedule", ["org_id"])

    op.execute("ALTER TABLE schedule ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE schedule FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON schedule "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON schedule TO bsi_app")

    # Runs as its owner, like the functions in 0002, so the scheduler can
    # list due rows across tenants without a tenant setting.
    op.execute("""
        CREATE FUNCTION due_schedules()
        RETURNS TABLE(schedule_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT s.id, s.org_id FROM schedule s
          WHERE s.status = 'active' AND s.next_run_at <= now()
          ORDER BY s.next_run_at
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_schedules() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_schedules() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_schedules()")
    op.drop_table("schedule")
