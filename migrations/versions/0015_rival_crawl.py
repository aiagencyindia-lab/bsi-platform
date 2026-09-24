"""rival_crawl and rival_page tables; due_rival_crawls()"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
RIVAL_DAYS = 7


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
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
        sa.Column("competitor_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column(
            "baseline", sa.Boolean(), server_default="false", nullable=False
        ),
    ]


def _fks() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        # The competitor DELETE route is a hard delete.
        sa.ForeignKeyConstraint(
            ["competitor_id"], ["competitor.id"], ondelete="CASCADE"
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rival_crawl",
        *_base(),
        sa.Column("job_id", sa.Uuid()),
        sa.Column(
            "complete", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "urls_seen", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("new_urls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "errors", postgresql.JSONB(), server_default="[]", nullable=False
        ),
        sa.Column(
            "types", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        *_fks(),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rival_crawl_latest",
        "rival_crawl",
        ["brand_id", "competitor_id", "domain", "created_at"],
    )
    _protect("rival_crawl")
    op.create_table(
        "rival_page",
        *_base(),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("types", postgresql.ARRAY(sa.Text())),
        *_fks(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competitor_id", "url"),
    )
    op.create_index(
        "ix_rival_page_new",
        "rival_page",
        ["brand_id", "competitor_id", "first_seen_at"],
    )
    _protect("rival_page")
    op.execute(f"""
        CREATE FUNCTION due_rival_crawls()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          -- Due when any active competitor's declared domain has no crawl
          -- in the window. Never-crawled first, then the oldest latest.
          WITH pairs AS (
            SELECT c.brand_id, c.id AS cid, d.domain
            FROM competitor c
            CROSS JOIN LATERAL unnest(c.domains) AS d(domain)
            WHERE c.status = 'active'
          ), latest AS (
            SELECT p.brand_id, p.cid, p.domain,
                   (SELECT max(r.created_at) FROM rival_crawl r
                    WHERE r.competitor_id = p.cid
                      AND r.domain = p.domain) AS last
            FROM pairs p
          )
          SELECT b.id, b.org_id FROM brand b
          JOIN latest l ON l.brand_id = b.id
          WHERE b.status = 'active'
          GROUP BY b.id, b.org_id
          HAVING bool_or(l.last IS NULL
                   OR l.last <= now() - make_interval(days => {RIVAL_DAYS}))
          ORDER BY CASE WHEN bool_and(l.last IS NOT NULL)
                        THEN min(l.last) END NULLS FIRST,
                   b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_rival_crawls() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_rival_crawls() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_rival_crawls()")
    op.drop_table("rival_page")
    op.drop_table("rival_crawl")
