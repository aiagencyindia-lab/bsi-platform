"""product.rule_check gains 'review'; product.dropped_words (slice 19)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

OLD = ("pass", "adjusted")
NEW = ("pass", "adjusted", "review")


def _check(values: tuple[str, ...]) -> str:
    return (
        "rule_check IS NULL OR rule_check IN ("
        + ", ".join(f"'{v}'" for v in values)
        + ")"
    )


def upgrade() -> None:
    op.drop_constraint("ck_product_rule_check", "product", type_="check")
    op.create_check_constraint("ck_product_rule_check", "product", _check(NEW))
    op.add_column(
        "product", sa.Column("dropped_words", postgresql.ARRAY(sa.Text()))
    )


def downgrade() -> None:
    op.execute(
        "UPDATE product SET rule_check = 'adjusted' WHERE rule_check = 'review'"
    )
    op.drop_column("product", "dropped_words")
    op.drop_constraint("ck_product_rule_check", "product", type_="check")
    op.create_check_constraint("ck_product_rule_check", "product", _check(OLD))
