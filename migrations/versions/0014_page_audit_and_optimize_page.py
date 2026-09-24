"""page_audit table; optimize_page rec type"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
OLD_TYPES = (
    "'pursue_citation_source', 'create_content', "
    "'add_competitor', 'sample_more', 'fix_crawlability', 'fix_entity'"
)
NEW_TYPES = OLD_TYPES + ", 'optimize_page'"


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
        "page_audit",
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
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("cluster_key", sa.String(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("weights_version", sa.String(), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column(
            "components",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "suggestions",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "evidence", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_audit_latest",
        "page_audit",
        ["brand_id", "cluster_key", "url", "created_at"],
    )
    _protect("page_audit")
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM task WHERE recommendation_id IN "
        "(SELECT id FROM recommendation WHERE type = 'optimize_page')"
    )
    op.execute("DELETE FROM recommendation WHERE type = 'optimize_page'")
    _rec_type_check(OLD_TYPES)
    op.drop_index("ix_page_audit_latest", table_name="page_audit")
    op.drop_table("page_audit")
