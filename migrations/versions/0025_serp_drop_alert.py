"""alert type serp_drop: the Brand SERP drop alert (slice 44, PRD F15)"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OLD = ("mention_drop", "competitor_shift", "new_source")
NEW = (*OLD, "serp_drop")


def _check(types: tuple[str, ...]) -> None:
    op.drop_constraint("ck_alert_type", "alert")
    op.create_check_constraint(
        "ck_alert_type",
        "alert",
        "type IN (" + ", ".join(f"'{t}'" for t in types) + ")",
    )


def upgrade() -> None:
    _check(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM alert WHERE type = 'serp_drop'")
    _check(OLD)
