"""ix_serp_audit_brand_fetched on serp_audit (brand_id, fetched_at)

Replaces the upgrade migration 0024's due_serp_audits() comment named,
(brand_id, kind, fetched_at), without kind: no read filters by kind. It
serves due_serp_audits() and the Brand SERP drop detector (brand and a
fetched_at range); the Brand SERP page's API uses its brand_id part
(slice 45).
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_serp_audit_brand_fetched", "serp_audit", ["brand_id", "fetched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_serp_audit_brand_fetched", table_name="serp_audit")
