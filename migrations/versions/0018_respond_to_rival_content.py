"""recommendation type respond_to_rival_content"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

OLD_TYPES = ", ".join(
    f"'{t}'"
    for t in (
        "pursue_citation_source",
        "create_content",
        "add_competitor",
        "sample_more",
        "fix_crawlability",
        "fix_entity",
        "optimize_page",
    )
)
NEW_TYPES = OLD_TYPES + ", 'respond_to_rival_content'"


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    # Tasks keep their rows: recommendation_id is nullable and the task is
    # the operator's record of work accepted.
    op.execute(
        "UPDATE task SET recommendation_id = NULL WHERE recommendation_id IN "
        "(SELECT id FROM recommendation "
        " WHERE type = 'respond_to_rival_content')"
    )
    op.execute(
        "DELETE FROM recommendation WHERE type = 'respond_to_rival_content'"
    )
    _rec_type_check(OLD_TYPES)
