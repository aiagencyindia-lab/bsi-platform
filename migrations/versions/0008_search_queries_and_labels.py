"""observation.search_queries, and the rec_label table with its RLS"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "observation", sa.Column("search_queries", sa.Integer(), nullable=True)
    )
    op.create_table(
        "rec_label",
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
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
            "label IN ('recommended', 'listed', 'mentioned', 'negative')",
            name="ck_rec_label_label",
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["observation.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", "entity_id"),
    )
    op.create_index("ix_rec_label_org_id", "rec_label", ["org_id"])
    op.execute("ALTER TABLE rec_label ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rec_label FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON rec_label "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rec_label TO bsi_app")


def downgrade() -> None:
    op.drop_table("rec_label")
    op.drop_column("observation", "search_queries")
