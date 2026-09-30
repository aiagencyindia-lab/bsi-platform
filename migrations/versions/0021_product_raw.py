"""product.keyword_samples and product.raw_title (slice 25)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column("keyword_samples", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("product", sa.Column("raw_title", sa.Text()))


def downgrade() -> None:
    op.drop_column("product", "raw_title")
    op.drop_column("product", "keyword_samples")
