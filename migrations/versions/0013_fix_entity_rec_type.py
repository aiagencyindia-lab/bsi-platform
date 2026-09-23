"""fix_entity rec type"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

OLD_TYPES = (
    "'pursue_citation_source', 'create_content', "
    "'add_competitor', 'sample_more', 'fix_crawlability'"
)
NEW_TYPES = OLD_TYPES + ", 'fix_entity'"


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM task WHERE recommendation_id IN "
        "(SELECT id FROM recommendation WHERE type = 'fix_entity')"
    )
    op.execute("DELETE FROM recommendation WHERE type = 'fix_entity'")
    _rec_type_check(OLD_TYPES)
