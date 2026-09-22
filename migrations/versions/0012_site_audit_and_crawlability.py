"""site_audit table, due_crawl_audits(), fix_crawlability rec type"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
OLD_TYPES = (
    "'pursue_citation_source', 'create_content', "
    "'add_competitor', 'sample_more'"
)
NEW_TYPES = OLD_TYPES + ", 'fix_crawlability'"
AUDIT_DAYS = 7


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    op.create_table(
        "site_audit",
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
        sa.Column("job_id", sa.Uuid()),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_site_audit_latest",
        "site_audit",
        ["brand_id", "domain", "created_at"],
    )
    _protect("site_audit")
    op.execute(f"""
        CREATE FUNCTION due_crawl_audits()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT b.id, b.org_id FROM brand b
          LEFT JOIN (SELECT a.brand_id, max(a.created_at) AS last
                     FROM site_audit a GROUP BY a.brand_id) a
            ON a.brand_id = b.id
          WHERE b.status = 'active'
            AND EXISTS (SELECT 1 FROM domain d WHERE d.brand_id = b.id)
            AND (a.last IS NULL
                 OR a.last <= now() - make_interval(days => {AUDIT_DAYS}))
          ORDER BY a.last NULLS FIRST, b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_crawl_audits() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_crawl_audits() TO bsi_app")
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    _rec_type_check(OLD_TYPES)
    op.execute("DROP FUNCTION due_crawl_audits()")
    op.drop_index("ix_site_audit_latest", table_name="site_audit")
    op.drop_table("site_audit")
