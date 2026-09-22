"""brand.recs_refreshed_at and due_recommendation_refreshes()"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Recommendations rest on weeks of answers, so a weekly pass is as often
# as the evidence can change meaningfully. Refreshing is pure SQL over
# stored rows: no model call, so no spend.
REFRESH_DAYS = 7


def upgrade() -> None:
    # Null means never refreshed, which is due: a brand created before
    # this migration should get its first automatic refresh.
    op.add_column(
        "brand",
        sa.Column("recs_refreshed_at", sa.DateTime(timezone=True)),
    )
    op.execute(f"""
        CREATE FUNCTION due_recommendation_refreshes()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT b.id, b.org_id FROM brand b
          WHERE b.status = 'active'
            AND (b.recs_refreshed_at IS NULL
                 OR b.recs_refreshed_at
                    <= now() - make_interval(days => {REFRESH_DAYS}))
          ORDER BY b.recs_refreshed_at NULLS FIRST, b.id
        $$""")
    op.execute(
        "REVOKE ALL ON FUNCTION due_recommendation_refreshes() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION due_recommendation_refreshes() TO bsi_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION due_recommendation_refreshes()")
    op.drop_column("brand", "recs_refreshed_at")
