"""report and report_run tables; brand.report_logo_url, report_accent,
report_prepared_by; due_report_runs(), report_run_by_token()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")
REPORT_CADENCES = ("off", "weekly", "monthly")
RUN_SOURCES = ("scheduled", "manual")
WEEKLY_DAYS = 7
MONTHLY_DAYS = 30


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _row_columns() -> list[sa.Column]:
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
        sa.Column("brand_id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    for col in ("report_logo_url", "report_accent", "report_prepared_by"):
        op.add_column("brand", sa.Column(col, sa.String()))
    op.create_table(
        "report",
        *_row_columns(),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("cadence", sa.String(), server_default="off", nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_type"),
        sa.CheckConstraint(
            _in("cadence", REPORT_CADENCES), name="ck_report_cadence"
        ),
        sa.UniqueConstraint("brand_id", "type", name="uq_report_brand_type"),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _protect("report")
    op.create_table(
        "report_run",
        *_row_columns(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compare_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("methodology_version", sa.String(), nullable=False),
        sa.Column("share_token", sa.String()),
        sa.CheckConstraint(
            _in("type", REPORT_TYPES), name="ck_report_run_type"
        ),
        sa.CheckConstraint(
            _in("source", RUN_SOURCES), name="ck_report_run_source"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["report.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_report_run_list", "report_run", ["brand_id", "created_at"]
    )
    op.create_index(
        "ix_report_run_token",
        "report_run",
        ["share_token"],
        unique=True,
        postgresql_where=sa.text("share_token IS NOT NULL"),
    )
    _protect("report_run")
    op.execute(f"""
        CREATE FUNCTION due_report_runs()
        RETURNS TABLE(report_id uuid, brand_id uuid, org_id uuid,
                      report_type text, cadence text)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT r.id, r.brand_id, r.org_id, r.type, r.cadence
          FROM report r JOIN brand b ON b.id = r.brand_id
          WHERE b.status = 'active'
            AND r.cadence <> 'off'
            AND (r.generated_at IS NULL
                 OR r.generated_at <= now() - make_interval(days =>
                      CASE r.cadence WHEN 'weekly' THEN {WEEKLY_DAYS}
                                     ELSE {MONTHLY_DAYS} END))
          ORDER BY r.generated_at NULLS FIRST, r.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_report_runs() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_report_runs() TO bsi_app")
    op.execute("""
        CREATE FUNCTION report_run_by_token(token text)
        RETURNS TABLE(run_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT rr.id, rr.org_id FROM report_run rr
          WHERE rr.share_token = token
        $$""")
    op.execute("REVOKE ALL ON FUNCTION report_run_by_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION report_run_by_token(text) TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION report_run_by_token(text)")
    op.execute("DROP FUNCTION due_report_runs()")
    op.drop_table("report_run")
    op.drop_table("report")
    for col in ("report_prepared_by", "report_accent", "report_logo_url"):
        op.drop_column("brand", col)
