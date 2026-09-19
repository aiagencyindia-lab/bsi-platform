"""extraction.cost_micros and mention.evidence_sentence"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction",
        sa.Column(
            "cost_micros", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "mention", sa.Column("evidence_sentence", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("mention", "evidence_sentence")
    op.drop_column("extraction", "cost_micros")
