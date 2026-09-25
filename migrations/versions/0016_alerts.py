"""alert table; brand.alerts_scanned_at, brand.webhook_url;
due_alert_scans(), due_alert_deliveries()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
SCAN_DAYS = 1
ALERT_TYPES = ("mention_drop", "competitor_shift", "new_source")


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
    op.add_column(
        "brand", sa.Column("alerts_scanned_at", sa.DateTime(timezone=True))
    )
    op.add_column("brand", sa.Column("webhook_url", sa.String()))
    op.create_table(
        "alert",
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
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String()),
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in ALERT_TYPES) + ")",
            name="ck_alert_type",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_subject",
        "alert",
        ["brand_id", "type", "subject_key", "window_to"],
    )
    op.create_index("ix_alert_list", "alert", ["brand_id", "created_at"])
    op.create_index(
        "ix_alert_due",
        "alert",
        ["next_attempt_at"],
        postgresql_where=sa.text(
            "delivered_at IS NULL AND next_attempt_at IS NOT NULL"
        ),
    )
    _protect("alert")
    op.execute(f"""
        CREATE FUNCTION due_alert_scans()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT b.id, b.org_id FROM brand b
          WHERE b.status = 'active'
            AND (b.alerts_scanned_at IS NULL
                 OR b.alerts_scanned_at
                    <= now() - make_interval(days => {SCAN_DAYS}))
          ORDER BY b.alerts_scanned_at NULLS FIRST, b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_alert_scans() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_alert_scans() TO bsi_app")
    op.execute("""
        CREATE FUNCTION due_alert_deliveries()
        RETURNS TABLE(alert_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT a.id, a.org_id FROM alert a
          JOIN brand b ON b.id = a.brand_id
          WHERE a.delivered_at IS NULL
            AND a.next_attempt_at IS NOT NULL
            AND a.next_attempt_at <= now()
            AND b.webhook_url IS NOT NULL
            AND b.status = 'active'
          ORDER BY a.next_attempt_at, a.id
          LIMIT 100
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_alert_deliveries() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_alert_deliveries() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_alert_deliveries()")
    op.execute("DROP FUNCTION due_alert_scans()")
    op.drop_table("alert")
    op.drop_column("brand", "webhook_url")
    op.drop_column("brand", "alerts_scanned_at")
