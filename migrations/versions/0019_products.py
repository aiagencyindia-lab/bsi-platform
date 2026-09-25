"""product and keyword_search tables (slice 18, PRD F16)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
PRODUCT_SOURCES = ("csv", "feed")
RULE_CHECKS = ("pass", "adjusted")


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
    op.create_table(
        "product",
        *_row_columns(),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("url", sa.String()),
        sa.Column("price", sa.String()),
        sa.Column("category", sa.String()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("keyword", sa.String()),
        sa.Column("keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("missing_keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("suggested_title", sa.String()),
        sa.Column("suggested_bullets", postgresql.ARRAY(sa.Text())),
        sa.Column("rule_check", sa.String()),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("result_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            _in("source", PRODUCT_SOURCES), name="ck_product_source"
        ),
        sa.CheckConstraint(
            "rule_check IS NULL OR " + _in("rule_check", RULE_CHECKS),
            name="ck_product_rule_check",
        ),
        sa.UniqueConstraint(
            "brand_id", "external_id", name="uq_product_brand_external"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_list", "product", ["brand_id", "title"])
    _protect("product")
    op.create_table(
        "keyword_search",
        *_row_columns(),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column(
            "titles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.String(), server_default="", nullable=False),
        sa.Column(
            "cost_micros", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "searched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.String()),
        sa.UniqueConstraint(
            "brand_id", "keyword", name="uq_keyword_search_brand_keyword"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _protect("keyword_search")


def downgrade() -> None:
    op.drop_table("keyword_search")
    op.drop_table("product")
