"""brand.webhook_secret (slice 32)"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand", sa.Column("webhook_secret", sa.Text()))


def downgrade() -> None:
    op.drop_column("brand", "webhook_secret")
