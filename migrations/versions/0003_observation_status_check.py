"""observation.status check constraint"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STATUSES = "'queued', 'running', 'retry', 'fetched', 'done', 'failed'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE observation ADD CONSTRAINT ck_observation_status "
        f"CHECK (status IN ({STATUSES}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE observation DROP CONSTRAINT ck_observation_status")
